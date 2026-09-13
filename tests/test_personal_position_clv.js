const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const script = fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8");
const extract = (name, next) => `function ${name}${script.split(`function ${name}`, 2)[1].split(`function ${next}`, 1)[0]}`;
const context = {};
vm.runInNewContext([
  extract("personalPositionFilterKey", "personalPositionSourceMeta"),
  extract("personalPositionLineComparison", "personalPositionLinePercent"),
].join("\n"), context);

test("CLV uses the placed sportsbook even when another book is first", () => {
  const novig = {key: "novig", label: "NoVIG", price: 0.48};
  const other = {key: "prophetx", label: "ProphetX", price: 0.47};
  const result = context.personalPositionLineComparison({provider: "NoVIG", lineValue: {comparisons: [other, novig]}});
  assert.equal(result, novig);
});

test("missing placed-book data cannot fall back to a different book or fair benchmark", () => {
  const result = context.personalPositionLineComparison({provider: "NoVIG", lineValue: {comparisons: [
    {key: "prophetx", label: "ProphetX", price: 0.47},
    {key: "sharp_fair", label: "Sharp no-vig benchmark", price: 0.48},
  ]}});
  assert.equal(result, null);
});

test("placed-book names and keys tolerate casing and punctuation", () => {
  const fanduel = {key: "fanduel", label: "FanDuel", price: 0.54};
  assert.equal(context.personalPositionLineComparison({provider: "Fan Duel", lineValue: {comparisons: [fanduel]}}), fanduel);
  const labelled = {key: "provider-id", label: "NoVIG", price: 0.48};
  assert.equal(context.personalPositionLineComparison({provider: " NOVIG ", lineValue: {comparisons: [labelled]}}), labelled);
});

test("CLV stays unavailable without a sportsbook or comparison data", () => {
  assert.equal(context.personalPositionLineComparison({}), null);
  assert.equal(context.personalPositionLineComparison({provider: "NoVIG"}), null);
  assert.equal(context.personalPositionLineComparison({lineValue: {comparisons: [{key: "novig"}]}}), null);
});

function previewPositions(enabled) {
  const previewContext = {};
  vm.runInNewContext(`const PERSONAL_CLV_LOCAL_PREVIEW = ${enabled};\n${extract("personalClvPreviewPositions", "renderPersonalClvDetails")}`, previewContext);
  return previewContext.personalClvPreviewPositions();
}

test("preview has three player props plus the original two prematch samples", () => {
  const positions = previewPositions(true);
  assert.equal(positions.length, 5);
  assert.equal(new Set(positions.map(p => p.positionId)).size, 5);
  const props = positions.filter(p => p.previewType === "player_prop");
  assert.equal(props.length, 3);
  assert.ok(props.some(p => p.selection === "Aaron Judge Over 1.5 Total Bases" && p.marketTitle === "Player Total Bases"));
  assert.ok(props.some(p => p.selection === "A'ja Wilson Over 24.5 Points" && p.marketTitle === "Player Points"));
  assert.ok(props.some(p => p.selection === "Paul Skenes Over 6.5 Strikeouts" && p.marketTitle === "Player Strikeouts"));
});

test("prop samples stay illustrative, upcoming, and matched to their placed book", () => {
  for (const position of previewPositions(true)) {
    assert.equal(position.isPreview, true);
    assert.equal(position.status, "scheduled");
    assert.equal(position.fills.length, 0);
    assert.ok(Date.parse(position.eventStartTime) > Date.now());
    assert.equal(position.lineValue.status, "preview");
    assert.equal(position.lineValue.comparisons.length, 1);
    assert.ok(context.personalPositionLineComparison(position));
    assert.equal(position.remainingShares, position.grossPurchaseCost / position.averageBuyEntry);
  }
});

test("no preview bets are created outside the local preview gate", () => {
  assert.equal(previewPositions(false).length, 0);
});

const startTimeContext = {escapeHtml: text => String(text)};
vm.runInNewContext(extract("personalPositionStartTimeMarkup", "personalWorkspacePositionRow"), startTimeContext);

test("table start date and time are separate lines in the existing Eastern timezone", () => {
  const markup = startTimeContext.personalPositionStartTimeMarkup("2026-09-13T23:05:00Z");
  assert.ok(markup.includes('<time datetime="2026-09-13T23:05:00.000Z">'));
  assert.ok(markup.includes("<span>Sep 13, 2026</span>"));
  assert.match(markup, /<span>7:05[\s\u202f]*PM EDT<\/span>/);
  const winter = startTimeContext.personalPositionStartTimeMarkup("2026-12-13T23:05:00Z");
  assert.match(winter, /<span>6:05[\s\u202f]*PM EST<\/span>/);
});

test("table start time has an honest fallback for missing or invalid dates", () => {
  for (const value of [null, undefined, "", "not a date"]) {
    assert.equal(startTimeContext.personalPositionStartTimeMarkup(value), "<small>Start time unavailable</small>");
  }
});

const currentOddsContext = {
  number: value => value == null ? null : Number(value),
  personalPositionLineComparison: position => position.lineValue.comparisons[0] || null,
  probabilityToAmerican: () => 108,
  formatAmericanOdds: value => `+${value}`,
  formatCents: value => `${value * 100}¢`,
  escapeHtml: value => String(value),
};
vm.runInNewContext(extract("personalPositionCurrent", "personalPositionLineComparison"), currentOddsContext);

test("Current table odds omit subtext while mobile metadata remains unchanged", () => {
  const prematch = {lineValue: {stage: "current", comparisons: [{price: 0.48}]}};
  const live = {quote: {effectiveSellPrice: 0.5, quoteFreshness: "live"}};
  assert.equal(currentOddsContext.personalPositionCurrent(prematch, false), '<strong class="mono">+108</strong>');
  assert.equal(currentOddsContext.personalPositionCurrent(live, false), '<strong class="mono">50¢</strong>');
  assert.ok(currentOddsContext.personalPositionCurrent(prematch).includes("<small>Prematch odds</small>"));
  assert.ok(currentOddsContext.personalPositionCurrent(live).includes("<small>live</small>"));
});

test("Current table odds retain unavailable-data messages", () => {
  assert.equal(currentOddsContext.personalPositionCurrent({}, false), '<span class="position-data-unavailable">No live feed</span>');
  assert.equal(currentOddsContext.personalPositionCurrent({lineValue: {stage: "current", comparisons: []}}, false), '<span class="position-data-unavailable">Awaiting odds</span>');
});

function richSortContext() {
  const elements = {};
  const sortContext = {
    appState: {personalPositionSort: "start-asc", personalPositionSportsbook: "", personalPositionSource: "", personalPositionStatus: "upcoming", personalActivePositions: []},
    document: {getElementById: id => elements[id] ||= {value: "", textContent: "", innerHTML: "", open: true, querySelector: () => ({focus: () => {sortContext.focused = true;}})}},
    escapeHtml: value => String(value),
    personalPositionPhase: () => "upcoming",
    personalPositionTrackedAt: position => Date.parse(position.trackedAt),
    renderPersonalWorkspacePositions: () => {sortContext.renderCount = (sortContext.renderCount || 0) + 1;},
  };
  vm.runInNewContext([
    extract("personalPositionSortOptions", "personalPositionFilterConfig"),
    extract("personalPositionFilterConfig", "personalPositionFilterIcon"),
    extract("personalPositionFilterIcon", "personalPositionFilterLabel"),
    extract("personalPositionFilterLabel", "renderPersonalPositionFilter"),
    extract("renderPersonalPositionFilter", "selectPersonalPositionFilter"),
    extract("selectPersonalPositionFilter", "filteredPersonalWorkspacePositions"),
    extract("filteredPersonalWorkspacePositions", "renderPersonalWorkspacePositions"),
  ].join("\n"), sortContext);
  return {sortContext, elements};
}

test("rich sort menu keeps the original three choices in order with one active option", () => {
  const {sortContext, elements} = richSortContext();
  sortContext.renderPersonalPositionFilter("sort");
  const options = elements["personal-position-sort-options"].innerHTML;
  assert.equal((options.match(/role="option"/g) || []).length, 3);
  assert.equal((options.match(/aria-selected="true"/g) || []).length, 1);
  assert.ok(!options.includes("personal-filter-option-icon"));
  assert.ok(!options.includes("<i "));
  assert.equal(sortContext.personalPositionFilterIcon("sort", "start-asc"), "");
  assert.ok(!Object.hasOwn(elements, "null"));
  assert.ok(options.indexOf("start-asc") < options.indexOf("stake-desc"));
  assert.ok(options.indexOf("stake-desc") < options.indexOf("recent-desc"));
  assert.equal(elements["personal-position-sort-label"].textContent, "Start Time");
});

test("rich sort selection updates sorting without overwriting sportsbook or source filters", () => {
  const {sortContext, elements} = richSortContext();
  Object.assign(sortContext.appState, {personalPositionSportsbook: "NoVIG", personalPositionSource: "Positive EV"});
  sortContext.selectPersonalPositionFilter("sort", "stake-desc");
  assert.equal(sortContext.appState.personalPositionSort, "stake-desc");
  assert.equal(sortContext.appState.personalPositionSportsbook, "NoVIG");
  assert.equal(sortContext.appState.personalPositionSource, "Positive EV");
  assert.equal(elements["personal-position-sort-label"].textContent, "Highest Stake");
  assert.equal(elements["personal-position-sort"].open, false);
  assert.equal(sortContext.focused, true);
  assert.equal(sortContext.renderCount, 1);
});

test("rich sort state retains start-time, stake, and recently-tracked ordering", () => {
  const {sortContext} = richSortContext();
  sortContext.appState.personalActivePositions = [
    {positionId: "a", grossPurchaseCost: 10, eventStartTime: "2030-01-01", trackedAt: "2029-01-01"},
    {positionId: "b", grossPurchaseCost: 100, eventStartTime: "2030-01-02", trackedAt: "2029-01-02"},
    {positionId: "c", grossPurchaseCost: 25, eventStartTime: "2030-01-03", trackedAt: "2029-01-03"},
  ];
  for (const [sort, expected] of [["start-asc", ["a", "b", "c"]], ["stake-desc", ["b", "c", "a"]], ["recent-desc", ["c", "b", "a"]]]) {
    sortContext.appState.personalPositionSort = sort;
    assert.deepEqual(Array.from(sortContext.filteredPersonalWorkspacePositions(), position => position.positionId), expected);
  }
});

test("unknown rich sort state safely defaults to Start Time", () => {
  const {sortContext, elements} = richSortContext();
  sortContext.appState.personalPositionSort = "unknown";
  sortContext.renderPersonalPositionFilter("sort");
  assert.equal(sortContext.appState.personalPositionSort, "start-asc");
  assert.equal(elements["personal-position-sort-label"].textContent, "Start Time");
});
