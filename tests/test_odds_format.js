const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");
const odds = require("../static/odds-format.js");
const source = file => fs.readFileSync(path.join(__dirname, "../static", file), "utf8");

test("all formats represent the same probability; American is the default", () => {
  assert.equal(odds.getFormat(), "american");
  const cases = [[125, 1 / 2.25, "+125", "44.4¢", "2.25"], [-150, 0.6, "-150", "60¢", "1.67"], [-100, 0.5, "+100", "50¢", "2.00"]];
  for (const [american, p, ...displays] of cases) {
    for (let index = 0; index < odds.formats.length; index++) {
      const options = {format: odds.formats[index]};
      assert.equal(odds.fromAmerican(american, options), displays[index]);
      assert.equal(odds.fromProbability(p, options), displays[index]);
      assert.equal(odds.fromDecimal(1 / p, options), displays[index]);
      assert.equal(odds.fromCents(p * 100, options), displays[index]);
    }
  }
});

test("no fake zero odds, even money, or terminal prices for unavailable data", () => {
  for (const value of [null, undefined, "", " ", false, true, [], [125], {}, "—", "Unavailable", NaN, Infinity, 0, 80, -80]) {
    assert.equal(odds.fromAmerican(value), "—");
  }
  for (const value of [null, undefined, "", false, NaN, Infinity, 0, 1, -0.5, 2]) assert.equal(odds.fromProbability(value), "—");
  assert.equal(odds.fromProbability(null, {unavailable: "N/A"}), "N/A");
  assert.notEqual(odds.fromProbability(0.00001, {format: "cents"}), "0¢");
  assert.notEqual(odds.fromProbability(0.99999, {format: "cents"}), "100¢");
  assert.notEqual(odds.fromProbability(0.99999, {format: "decimal"}), "1.00");
});

test("native cents and tagged decimal quotes cannot bypass the preference", () => {
  assert.equal(odds.fromDisplay("62.5¢"), "-167");
  assert.equal(odds.fromDisplay("40 cents"), "+150");
  assert.equal(odds.fromDisplay("EVEN"), "+100");
  assert.equal(odds.fromDisplay("5/4"), "+125");
  assert.equal(odds.fromDisplay("1.91", {sourceFormat: "decimal"}), "-110");
  assert.equal(odds.fromDisplay("1.91", {sourceFormat: "Decimal"}), "-110");
  assert.equal(odds.fromDisplay("1.91"), "—");
  assert.equal(odds.quote({displayOdds: "62.5¢"}), "-167");
  assert.equal(odds.quote({displayOdds: "1.91", oddsFormat: "decimal"}), "-110");
  assert.equal(odds.quote({americanOdds: 125, displayOdds: "44.4¢"}), "+125");
  assert.equal(odds.quote({americanOdds: null, contractPrice: 0.4, displayOdds: "garbage"}), "+150");
  assert.equal(odds.quote({}), "—");
});

test("fee-adjusted execution prices win without modifying any quote or model input", () => {
  const quote = Object.freeze({providerKey: "kalshi", contractPrice: 0.4, effectiveEntryPrice: 0.42, americanOdds: 150, displayOdds: "40¢"});
  assert.equal(odds.quote(quote), "+138");
  assert.equal(odds.quote(quote, {format: "cents"}), "42¢");
  assert.equal(quote.contractPrice, 0.4);
  assert.equal(quote.americanOdds, 150);
  assert.equal(odds.americanToProbability(125), 1 / 2.25);
  assert.ok(Math.abs(odds.probabilityToAmerican(0.42) - 138.0952380952381) < 1e-10);
});

function browser(saved, unavailableStorage = false) {
  const values = new Map(Object.entries(saved || {}));
  const listeners = new Map();
  const changes = [];
  const window = {
    localStorage: {getItem: key => { if (unavailableStorage) throw Error("blocked"); return values.get(key) ?? null; }, setItem: (key, value) => { if (unavailableStorage) throw Error("blocked"); values.set(key, value); }},
    addEventListener: (key, listener) => listeners.set(key, listener),
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    dispatchEvent: event => changes.push(event),
  };
  vm.runInNewContext(source("odds-format.js"), {window});
  return {api: window.IconLabsOdds, values, changes, storage: listeners.get("storage")};
}

test("preference persists across tools; old inert profile choices never change defaults", () => {
  const first = browser({"iconlabs-profile-preferences": JSON.stringify({oddsFormat: "Decimal"})});
  assert.equal(first.api.getFormat(), "american");
  first.api.setFormat("Cents");
  assert.equal(first.api.fromAmerican(125), "44.4¢");
  assert.equal(first.values.get(odds.STORAGE_KEY), "cents");
  assert.equal(first.changes.length, 1);
  assert.equal(first.changes[0].type, odds.EVENT);
  const next = browser(Object.fromEntries(first.values));
  assert.equal(next.api.getFormat(), "cents");
  next.api.setFormat("Decimal");
  assert.equal(next.api.fromAmerican(125), "2.25");
  assert.equal(next.api.fromAmerican(125, {format: "american"}), "+125"); // Explicit calculation inputs stay American.
});

test("cross-tab changes, resets, unsupported choices and blocked storage are safe", () => {
  const b = browser();
  b.storage({key: odds.STORAGE_KEY, newValue: "decimal"});
  assert.equal(b.api.getFormat(), "decimal");
  b.storage({key: "another-key", newValue: "cents"});
  assert.equal(b.api.getFormat(), "decimal");
  b.storage({key: null, newValue: null});
  assert.equal(b.api.getFormat(), "american");
  assert.equal(browser({[odds.STORAGE_KEY]: "fractional"}).api.getFormat(), "american");
  const blocked = browser({}, true);
  blocked.api.setFormat("decimal");
  assert.equal(blocked.api.fromAmerican(-150), "1.67");
  assert.equal(blocked.api.setFormat("bad"), "american");
});

function functionSource(file, name) {
  const script = source(file);
  const start = script.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${file} defines ${name}`);
  let parameterEnd = script.indexOf("(", start) + 1, parentheses = 1;
  while (parentheses && parameterEnd < script.length) { const c = script[parameterEnd++]; if (c === "(") parentheses++; else if (c === ")") parentheses--; }
  const body = script.indexOf("{", parameterEnd);
  let depth = 1, end = body + 1;
  while (depth && end < script.length) { const c = script[end++]; if (c === "{") depth++; else if (c === "}") depth--; }
  return script.slice(start, end);
}

for (const [file, name] of [["sharp-money.js", "odds"], ["arbitrage.js", "odds"], ["middles.js", "odds"], ["low-hold.js", "odds"], ["lab-tracker.js", "odds"], ["dfs.js", "formatAmericanOdds"], ["calculators.js", "american"]]) {
  test(`${file} displays all three formats through the shared boundary`, () => {
    const b = browser();
    const ctx = {window: {IconLabsOdds: b.api}};
    vm.runInNewContext(functionSource(file, name), ctx);
    assert.equal(ctx[name](-150), "-150");
    b.api.setFormat("cents");
    assert.equal(ctx[name](-150), "60¢");
    b.api.setFormat("decimal");
    assert.equal(ctx[name](-150), "1.67");
    assert.equal(ctx[name](null), "—");
  });
}

test("Fantasy detail snapshots normalize native exchange prices but retain American math", () => {
  const b = browser();
  const ctx = {window: {IconLabsOdds: b.api}, sourceOddsKeys: []};
  vm.runInNewContext(functionSource("dfs.js", "marketSnapshot"), ctx);
  const row = {oddsByBook: {polymarket: {odds: "40¢", liquidity: 500, line: 1.5, deepLink: "https://example.com/bet"}}};
  const first = ctx.marketSnapshot(row, "polymarket");
  assert.equal(first.display, "+150");
  assert.ok(Math.abs(first.american - 150) < 1e-10);
  b.api.setFormat("decimal");
  const second = ctx.marketSnapshot(row, "polymarket");
  assert.equal(second.display, "2.50");
  assert.equal(second.american, first.american);
  assert.equal(second.line, 1.5);
  assert.equal(second.liquidity, 500);
  assert.equal(ctx.marketSnapshot({oddsByBook: {novig: null}}, "novig").american, null);
  const longshot = ctx.marketSnapshot({oddsByBook: {novig: {odds: "100.0", oddsFormat: "decimal"}}}, "novig");
  assert.equal(longshot.display, "100.00");
  assert.equal(longshot.american, 9900);
  assert.equal(ctx.marketSnapshot({oddsByBook: {polymarket: "62.5¢"}}, "polymarket").american, -167);
});

test("tracker snapshots, core probability views, Odds Screen and Futures use one format", () => {
  const b = browser();
  const ctx = {window: {IconLabsOdds: b.api}, number: value => value === null || value === undefined ? null : Number(value)};
  for (const [file, name] of [["app.js", "formatCents"], ["app.js", "formatAmericanOdds"], ["app.js", "trackerDisplayOdds"], ["app.js", "executionOptionDisplayOdds"], ["app.js", "oddsMobilePrice"], ["futures.js", "oddsText"]]) vm.runInNewContext(functionSource(file, name), ctx);
  for (const format of b.api.formats) {
    b.api.setFormat(format);
    const expected = b.api.fromAmerican(150);
    assert.equal(ctx.formatCents(0.4), expected);
    assert.equal(ctx.formatAmericanOdds(150), expected);
    assert.equal(ctx.trackerDisplayOdds({provider_display_odds: "40¢"}, 0.4), expected);
    assert.equal(ctx.executionOptionDisplayOdds({contractPrice: 0.4, displayOdds: "40¢"}), expected);
    assert.equal(ctx.oddsMobilePrice({americanOdds: 150, displayOdds: "40¢"}), expected);
    assert.equal(ctx.oddsText({americanOdds: 150, displayOdds: "40¢"}), expected);
  }
});

test("every page loads the shared preference first; no Account expansion required", () => {
  const template = fs.readFileSync(path.join(__dirname, "../templates/base.html"), "utf8");
  assert.ok(template.indexOf("filename='odds-format.js'") < template.indexOf("filename='app.js'"));
  assert.match(template, /id="profile-odds-format"><option>American<\/option><option>Cents<\/option><option>Decimal<\/option>/);
  for (const file of ["app.js", "sharp-money.js", "positive-ev.js", "arbitrage.js", "middles.js", "low-hold.js", "futures.js", "lab-tracker.js", "dfs.js", "calculators.js"]) {
    assert.match(source(file), /IconLabsOdds/);
    assert.match(source(file), /IconLabsOdds.EVENT/);
  }
  assert.match(source("app.js"), /IconLabsOdds.setFormat\(profile.oddsFormat\)/);
});

test("Positive EV price-history axes use probabilities, not invalid American gap ticks", () => {
  const script = source("positive-ev.js");
  const ctx = {window: {IconLabsOdds: odds}};
  const value = script.slice(script.indexOf("const liveHistoryValue ="), script.indexOf("const liveHistoryHasMovement ="));
  const label = script.slice(script.indexOf("const historyValueLabel ="), script.indexOf("const compactDollars ="));
  vm.runInNewContext(`${value}\n${label}\nthis.value = liveHistoryValue; this.label = historyValueLabel;`, ctx);
  const favorite = ctx.value({americanOdds: -105}, "americanOdds");
  const underdog = ctx.value({americanOdds: 105}, "americanOdds");
  assert.ok(Math.abs(favorite - underdog) < 0.03);
  assert.equal(ctx.label((favorite + underdog) / 2, "americanOdds"), "+100");
  assert.equal(ctx.value({line: 8.5}, "line"), 8.5);
  assert.equal(ctx.value({marketLimit: 5000}, "marketLimit"), 5000);
});
