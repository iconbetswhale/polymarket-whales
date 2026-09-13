/* Shared display boundary. Keep stored prices, execution fees and model math unrounded. */
(function (root, factory) {
  const api = factory(root);
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.IconLabsOdds = api;
})(typeof window === "object" ? window : null, function (root) {
  "use strict";
  const STORAGE_KEY = "iconlabs-odds-format";
  const EVENT = "iconlabs:odds-format-changed";
  const formats = Object.freeze(["american", "cents", "decimal"]);
  let preference = "american";
  const normalize = value => formats.includes(String(value).toLowerCase()) ? String(value).toLowerCase() : "american";
  const numeric = value => !["number", "string"].includes(typeof value) || String(value).trim() === "" ? null : Number.isFinite(Number(value)) ? Number(value) : null;
  const validProbability = value => { const n = numeric(value); return n !== null && n > 0 && n < 1 ? n : null; };
  function americanToProbability(value) {
    const n = numeric(value);
    return n !== null && Math.abs(n) >= 100 ? n > 0 ? 100 / (n + 100) : -n / (-n + 100) : null;
  }
  function probabilityToAmerican(value) {
    const p = validProbability(value);
    return p === null ? null : p <= 0.5 ? 100 * (1 - p) / p : -100 * p / (1 - p);
  }
  function decimalToProbability(value) {
    const n = numeric(value);
    return n !== null && n > 1 ? 1 / n : null;
  }
  function centsToProbability(value) {
    const n = numeric(value);
    return n === null ? null : validProbability(n / 100);
  }
  function displayToProbability(value, sourceFormat) {
    sourceFormat = String(sourceFormat ?? "american").toLowerCase();
    const text = String(value ?? "").trim();
    if (/^(even|evens|evs)$/i.test(text)) return 0.5;
    const cents = text.match(/^([0-9]+(?:\.[0-9]+)?)\s*(?:¢|cents?)$/i);
    if (cents) return centsToProbability(cents[1]);
    const fractional = text.match(/^(\d+)\/(\d+)$/);
    if (fractional) return Number(fractional[2]) > 0 ? decimalToProbability(1 + Number(fractional[1]) / Number(fractional[2])) : null;
    if (sourceFormat === "probability") return validProbability(value);
    if (sourceFormat === "cents") return centsToProbability(value);
    if (sourceFormat === "decimal") return decimalToProbability(value);
    // Bare decimals are ambiguous: never guess that a missing/invalid price is odds.
    return americanToProbability(value);
  }
  function fromProbability(value, options = {}) {
    const p = validProbability(value);
    if (p === null) return options.unavailable ?? "—";
    const format = normalize(options.format ?? preference);
    if (format === "decimal") {
      const decimal = 1 / p;
      return decimal.toFixed(2) === "1.00" ? String(decimal) : decimal.toFixed(2);
    }
    if (format === "cents") {
      const cents = Number((p * 100).toFixed(1));
      return `${cents === 0 || cents === 100 ? String(p * 100) : cents}¢`;
    }
    const rounded = Math.round(probabilityToAmerican(p));
    // +100 and -100 are equivalent; use one canonical even-money spelling.
    return Math.abs(rounded) === 100 ? "+100" : `${rounded > 0 ? "+" : ""}${rounded}`;
  }
  const fromAmerican = (value, options) => fromProbability(americanToProbability(value), options);
  const fromDecimal = (value, options) => fromProbability(decimalToProbability(value), options);
  const fromCents = (value, options) => fromProbability(centsToProbability(value), options);
  const fromDisplay = (value, options = {}) => fromProbability(displayToProbability(value, options.sourceFormat), options);
  function quote(value = {}, options = {}) {
    const american = value.americanOdds ?? value.american_odds;
    const effective = value.bestExecutablePrice ?? value.effectiveEntryPrice ?? value.effectivePrice;
    const p = validProbability(effective) ?? americanToProbability(american) ?? validProbability(value.contractPrice)
      ?? displayToProbability(value.displayOdds ?? value.display_odds ?? value.nativePrice, value.oddsFormat ?? value.odds_format);
    return fromProbability(p, options);
  }
  function getFormat() { return preference; }
  function notify() {
    if (root?.dispatchEvent && root.CustomEvent) root.dispatchEvent(new root.CustomEvent(EVENT, { detail: { format: preference } }));
  }
  function setFormat(value) {
    const next = normalize(value);
    try { root?.localStorage?.setItem(STORAGE_KEY, next); } catch (_) { /* Private browsing still supports this session. */ }
    if (next !== preference) { preference = next; notify(); }
    return preference;
  }
  try { preference = normalize(root?.localStorage?.getItem(STORAGE_KEY)); } catch (_) { /* American is the safe default. */ }
  root?.addEventListener?.("storage", event => {
    if (event.key !== STORAGE_KEY && event.key !== null) return;
    const next = normalize(event.newValue);
    if (next !== preference) { preference = next; notify(); }
  });
  return Object.freeze({ formats, STORAGE_KEY, EVENT, getFormat, setFormat, fromProbability, fromAmerican, fromDecimal, fromCents, fromDisplay, quote,
    americanToProbability, probabilityToAmerican, decimalToProbability, centsToProbability, displayToProbability });
});
