"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(require.resolve("../static/app.js"), "utf8");
const dateHelpers = source.slice(source.indexOf("function trackerIsoDate"), source.indexOf("function trackerWeekEnd"));
const shiftHelper = source.slice(source.indexOf("function trackerShiftedPeriodAnchor"), source.indexOf("function trackerTimeframeDateBounds"));
const recapHelper = source.slice(source.indexOf("function trackerRecapSnapshot"), source.indexOf("function trackerLatestPeriodAnchor"));
const money = (value) => `$${Number(value).toFixed(2)}`;
const context = {
  appState: { graphRange: "month", trackerPeriodAnchor: new Date(2026, 8, 1) },
  number: (value) => value === null || value === undefined || value === "" ? null : Number(value),
  trackerPerformancePoints: (graph) => graph,
  trackerPeriodProfit: () => 9999,
  signedMoney: (value) => `${value > 0 ? "+" : value < 0 ? "−" : ""}${money(Math.abs(value))}`,
  formatMoney: money,
  formatPercent: (value) => `${(value * 100).toFixed(1)}%`,
  formatClvPercent: (value) => `${value > 0 ? "+" : ""}${value.toFixed(2)}%`,
};
vm.runInNewContext(`${dateHelpers}\n${shiftHelper}\n${recapHelper}\nthis.recap = trackerRecapSnapshot;`, context);
const payload = {
  summary: { total_tracked_bets: 25, realized_profit_loss: 5000, total_wagered: 9000 },
  period_summary: { wins: 14, losses: 11, pushes_voids: 0, settled_wagered: 3000, realized_profit_loss: 191.93, roi: 191.93 / 3000 },
  clv: { periods: { all: { bets_measured: 11, stake_weighted_clv_pct: 1.75 } } },
};
const now = new Date(2026, 8, 12, 14);
const yesterday = context.recap(payload, [], { range: "today", anchor: new Date(2026, 8, 11), now });
assert.equal(yesterday.headline, "Yesterday, 25 Bets Settled.");
assert.equal(yesterday.profitText, "+$191.93");
assert.equal(yesterday.wageredText, "$3000.00");
assert.equal(yesterday.roiText, "6.4%");
assert.equal(yesterday.recordText, "14–11–0");
assert.equal(yesterday.coverageText, "11 Of 25 Bets Priced");
assert.equal(yesterday.clvText, "+1.75%");
assert.equal(yesterday.dayOffset, -1);
assert.equal(context.recap(payload, [], { range: "month", now }).dayOffset, undefined);
const future = context.recap({}, [], { range: "today", anchor: new Date(2026, 8, 13), now });
assert.equal(future.headline, "Tomorrow’s Results Are Still Ahead.");
assert.equal(future.profitText, "—");
assert.equal(future.roiText, "—");
assert.equal(future.recordText, "—");
const empty = context.recap({ period_summary: { realized_profit_loss: 0 } }, [], { range: "today", anchor: now, now });
assert.equal(empty.profitText, "$0.00");
assert.equal(empty.roiText, "—");
assert.equal(empty.clvText, "—");
assert.equal(empty.coverageText, "0 Of 0 Bets Priced");
assert.equal(empty.profitLabel, "Your Net Result So Far");

// Re-rendering the recap must clear old CLV border states, including missing data.
const recapNodes = new Map();
function recapNode(id) {
  if (!recapNodes.has(id)) {
    const classes = new Set();
    recapNodes.set(id, {
      classList: {
        toggle(name, enabled) { enabled ? classes.add(name) : classes.delete(name); },
        contains(name) { return classes.has(name); },
      },
    });
  }
  return recapNodes.get(id);
}
context.document = { getElementById: recapNode, querySelectorAll: () => [] };
context.pnlTone = (value) => value > 0 ? "positive" : value < 0 ? "negative" : "neutral";
context.trackerLatestPeriodAnchor = () => new Date(2026, 8, 12);
const recapRenderer = source.slice(source.indexOf("function renderTrackerPeriodRecap("), source.indexOf("function selectTrackerRecapDay("));
vm.runInNewContext(`${recapRenderer}\nthis.renderRecap = renderTrackerPeriodRecap;`, context);
for (const clv of [1.75, -1.25, 0, null, 1.75]) {
  context.renderRecap({ ...payload, clv: { periods: { all: { bets_measured: clv === null ? 0 : 11, stake_weighted_clv_pct: clv } } } }, []);
  const card = recapNode("tracker-recap-clv-card");
  assert.equal(card.classList.contains("is-positive"), clv !== null && clv > 0);
  assert.equal(card.classList.contains("is-negative"), clv !== null && clv < 0);
  assert.equal(recapNode("tracker-summary-clv").className, clv === null ? "" : context.pnlTone(clv));
}

// Each selected Share tab owns one visible preview and the export selection.
const shareNames = { chart: "Chart", calendar: "Calendar", recap: "Period Recap", pulse: "Monthly Pulse", clv: "CLV Details", profit: "Profit Over Time" };
const buttons = Object.keys(shareNames).map((key) => ({
  dataset: { trackerShareSection: key },
  classList: { toggle() {} },
  attributes: {},
  setAttribute(name, value) { this.attributes[name] = value; },
}));
const slides = Object.keys(shareNames).map((key) => ({ dataset: { trackerShareSlide: key }, hidden: false }));
const selectionTitle = {};
const selectionCopy = {};
context.TRACKER_SHARE_SECTIONS = Object.fromEntries(Object.entries(shareNames).map(([key, label]) => [key, { label }]));
context.document = {
  querySelectorAll: (selector) => selector === "[data-tracker-share-section]" ? buttons : slides,
  getElementById: (id) => id === "tracker-share-selection-title" ? selectionTitle : selectionCopy,
};
const sectionHelper = source.slice(source.indexOf("function setTrackerShareSection("), source.indexOf("async function renderTrackerShareGallery("));
vm.runInNewContext(`${sectionHelper}\nthis.selectShare = setTrackerShareSection;`, context);
for (const key of Object.keys(shareNames)) {
  context.selectShare(key);
  assert.equal(context.appState.trackerShareSection, key);
  assert.equal(slides.filter((slide) => !slide.hidden).length, 1);
  assert.equal(slides.find((slide) => !slide.hidden).dataset.trackerShareSlide, key);
  assert.equal(buttons.filter((button) => button.attributes["aria-selected"] === "true").length, 1);
  assert.equal(selectionTitle.textContent, `${shareNames[key]} Ready to Share`);
}
context.selectShare("unknown");
assert.equal(context.appState.trackerShareSection, "profit");

// The exported recap contains one padded result card plus four metric cards.
const drawing = [];
const canvasContext = {
  beginPath() {}, fill() {}, stroke() {}, clearRect() {}, fillRect() {}, arc() {}, moveTo() {}, lineTo() {},
  roundRect(x, y, width, height, radius) { drawing.push({ kind: "card", x, y, width, height, radius }); },
  fillText(text, x, y) { drawing.push({ kind: "text", text, x, y, font: this.font, width: this.measureText(text).width, tone: this.fillStyle, align: this.textAlign }); },
  measureText(text) { return { width: text.length * Number(this.font.match(/([0-9.]+)px/)?.[1] || 16) * .55 }; },
  createLinearGradient(x0, y0, x1, y1) {
    const gradient = { kind: "border", x0, y0, x1, y1, stops: [], addColorStop(offset, color) { this.stops.push([offset, color]); } };
    drawing.push(gradient);
    return gradient;
  },
};
const glossHelper = source.slice(source.indexOf("function trackerShareGlossBorder("), source.indexOf("function drawTrackerShareBase("));
const drawHelper = source.slice(source.indexOf("function drawTrackerShareRecap("), source.indexOf("function drawTrackerAlternateShareCard("));
vm.runInNewContext(`${glossHelper}\n${drawHelper}\nthis.drawRecap = drawTrackerShareRecap;`, context);
context.drawRecap(canvasContext, { recap: yesterday });
const cards = drawing.filter((command) => command.kind === "card");
assert.equal(cards.length, 5);
assert.ok(cards.every((card) => card.x >= 88 && card.x + card.width <= 992 && card.y + card.height <= 1100));
assert.ok(drawing.some((command) => command.text === yesterday.profitText && command.x === 118));
assert.ok(drawing.some((command) => command.text === yesterday.coverageText));
const borders = drawing.filter((command) => command.kind === "border");
assert.equal(borders.length, 5);
assert.ok(borders.every((border) => border.y1 > border.y0 && border.x0 === border.x1));
assert.deepEqual(borders[0].stops, [[0, "#79d995"], [.35, "#348450"], [1, "#163a28"]]);
assert.deepEqual(borders[1].stops, [[0, "#8e95a3"], [.35, "#596170"], [1, "#232a35"]]);
for (const [profit, future, colors] of [
  [-20, false, ["#ef8894", "#9f4858", "#401e28"]],
  [0, false, ["#8e95a3", "#596170", "#232a35"]],
  [20, true, ["#8e95a3", "#596170", "#232a35"]],
]) {
  drawing.length = 0;
  context.drawRecap(canvasContext, { recap: { ...yesterday, profit, future } });
  assert.deepEqual(drawing.find((command) => command.kind === "border").stops, [[0, colors[0]], [.35, colors[1]], [1, colors[2]]]);
}

// Every enclosing share body has a silver finish; branded headers stay original.
const baseHelper = source.slice(source.indexOf("function drawTrackerShareBase("), source.indexOf("function drawTrackerShareFooter("));
vm.runInNewContext(`${baseHelper}\nthis.drawBase = drawTrackerShareBase;`, context);
drawing.length = 0;
context.drawBase(canvasContext, { periodLabel: "September 12, 2026" }, "Period Recap");
assert.deepEqual(drawing.filter((command) => command.kind === "border").map((border) => [border.y0, border.y1]), [[190, 1298]]);
drawing.length = 0;
context.drawBase(canvasContext, { periodLabel: "September 2026" }, "Chart");
assert.deepEqual(drawing.filter((command) => command.kind === "border").map((border) => [border.y0, border.y1]), [[190, 1298]]);

// CLV percentages stay padded inside the donut and outside the progress bars.
context.clvPercent = (value) => value === null ? "—" : `${value.toFixed(2)}%`;
const clvHelper = source.slice(source.indexOf("function drawTrackerShareClv("), source.indexOf("function drawTrackerShareProfit("));
const profitHelper = source.slice(source.indexOf("function drawTrackerShareProfit("), source.indexOf("function drawTrackerShareRecap("));
const pulseHelper = source.slice(source.indexOf("function drawTrackerSharePulse("), source.indexOf("function drawTrackerShareClv("));
context.trackerShareDailyMap = () => new Map([[1, 45], [2, -30]]);
context.trackerShareWeekdayTotals = () => [0, 45, -30, 0, 0, 0, 0];
context.TRACKER_SHARE_MONTHLY_PROFIT_FONT_PX = 22;
vm.runInNewContext(`${clvHelper}\n${profitHelper}\n${pulseHelper}\nthis.drawClv = drawTrackerShareClv; this.drawProfit = drawTrackerShareProfit; this.drawPulse = drawTrackerSharePulse;`, context);
for (const [positive, negative, even, color] of [
  [10, 0, 0, "#79d995"], [1, 8, 1, "#ef8894"], [1, 1, 8, "#8e95a3"], [5, 5, 0, "#8e95a3"], [0, 0, 0, "#8e95a3"],
]) {
  drawing.length = 0;
  const measured = positive + negative + even;
  context.drawClv(canvasContext, { clvSummary: { expectedValue: 1.75, beating: measured ? positive / measured : null, measured, positive, negative, even } });
  assert.equal(drawing.find((command) => command.kind === "border").stops[0][1], color);
  const donutText = drawing.find((command) => command.kind === "text" && command.x === 310);
  assert.ok(donutText.width <= 160, "donut percentage leaves internal padding");
  for (const text of drawing.filter((command) => command.kind === "text" && command.x === 968)) {
    assert.ok(text.x - text.width >= 840, "bar percentages have a separate column and 25px minimum gap");
  }
}
drawing.length = 0;
context.drawPulse(canvasContext, { profit: 15, profitText: "+$15.00" });
assert.deepEqual(drawing.filter((command) => command.kind === "border").map((border) => border.stops[0][1]), ["#79d995", "#ef8894", "#8e95a3"]);
assert.ok(drawing.some((command) => command.text === "Best Day" && command.font.includes("24px")));
drawing.length = 0;
context.drawProfit(canvasContext, { profitMetrics: [["Total Profit", "+$100.00"], ["Total Stake", "$100000000.00"], ["Total Profit", "−$30.00"]] });
assert.deepEqual(drawing.filter((command) => command.kind === "border").map((border) => border.stops[0][1]), ["#79d995", "#8e95a3", "#ef8894"]);
assert.ok(drawing.filter((command) => command.kind === "text").every((command) => command.width <= 388));
assert.ok(drawing.some((command) => command.text === "Total Profit" && command.font.includes("23px")));
console.log("tracker recap tests passed");
