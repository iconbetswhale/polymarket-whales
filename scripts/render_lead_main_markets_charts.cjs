const fs = require("fs");
const path = require("path");
const sharp = require("sharp");

const root = path.resolve(__dirname, "..");
const input = path.join(
  root,
  "outputs",
  "lead-cohort-main-markets-30-day-simulation-2026-07-28.json"
);
const outDir = path.join(root, "outputs", "lead-main-markets-report");
fs.mkdirSync(outDir, { recursive: true });
const payload = JSON.parse(fs.readFileSync(input, "utf8"));
const three = payload.cohorts.THREE_LEADS;
const four = payload.cohorts.FOUR_LEADS;

const C = {
  bg: "#071018",
  panel: "#0d1923",
  panel2: "#102331",
  border: "#29404f",
  grid: "#263642",
  text: "#f4f7f8",
  muted: "#8798a6",
  green: "#73d13d",
  blue: "#23b7e5",
  gold: "#e5b94b",
  red: "#d96c64",
};
const esc = (value) =>
  String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
const fmtMoney = (value, digits = 0) =>
  `$${Number(value).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
const fmtPct = (value, digits = 1) => `${(Number(value) * 100).toFixed(digits)}%`;

function polyline(values, x, y, width, height, min, max) {
  return values
    .map((value, index) => {
      const px = x + (index / (values.length - 1)) * width;
      const py = y + height - ((value - min) / (max - min)) * height;
      return `${px.toFixed(1)},${py.toFixed(1)}`;
    })
    .join(" ");
}

function band(top, bottom, x, y, width, height, min, max) {
  const topPoints = polyline(top, x, y, width, height, min, max);
  const bottomPoints = bottom
    .map((value, index) => {
      const px = x + (index / (bottom.length - 1)) * width;
      const py = y + height - ((value - min) / (max - min)) * height;
      return `${px.toFixed(1)},${py.toFixed(1)}`;
    })
    .reverse()
    .join(" ");
  return `${topPoints} ${bottomPoints}`;
}

function baseStyles() {
  return `
    <style>
      text { font-family: Inter, Arial, sans-serif; fill: ${C.text}; }
      .title { font-size: 34px; font-weight: 800; }
      .subtitle { font-size: 16px; fill: ${C.muted}; }
      .section { font-size: 23px; font-weight: 760; }
      .metric { font-size: 28px; font-weight: 800; }
      .label { font-size: 13px; font-weight: 700; letter-spacing: 1.2px; fill: ${C.muted}; }
      .body { font-size: 16px; }
      .small { font-size: 13px; fill: ${C.muted}; }
      .axis { font-size: 12px; fill: ${C.muted}; }
      .mono { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
    </style>`;
}

function outcomePanel(cohort, label, accent, y) {
  const sim = cohort.simulation;
  const hist = cohort.historical;
  const paths = sim.daily_bankroll_percentiles;
  const all = [...paths.p05, ...paths.p95, 10000];
  const min = Math.floor((Math.min(...all) - 250) / 250) * 250;
  const max = Math.ceil((Math.max(...all) + 250) / 250) * 250;
  const x = 490;
  const cy = y + 75;
  const w = 1035;
  const h = 260;
  let svg = `
    <rect x="35" y="${y}" width="1530" height="375" rx="14" fill="${C.panel}" stroke="${C.border}"/>
    <text x="65" y="${y + 46}" class="section">${esc(label)}</text>
    <text x="65" y="${y + 82}" class="label">30-DAY MEDIAN ENDING BANKROLL</text>
    <text x="65" y="${y + 124}" class="metric" fill="${accent}">${fmtMoney(
      sim.final_bankroll.p50,
      0
    )}</text>
    <text x="65" y="${y + 153}" class="body">${fmtPct(sim.roi.p50, 2)} median ROI</text>
    <text x="65" y="${y + 181}" class="small">${fmtPct(
      sim.probability_profitable,
      1
    )} of paths profitable</text>
    <line x1="65" y1="${y + 207}" x2="425" y2="${y + 207}" stroke="${C.grid}"/>
    <text x="65" y="${y + 238}" class="label">OBSERVED INPUTS</text>
    <text x="65" y="${y + 272}" class="body mono">${hist.bets_per_calendar_day.toFixed(
      2
    )} bets/day</text>
    <text x="65" y="${y + 302}" class="body mono">${fmtMoney(
      hist.average_initial_bet_on_10000,
      2
    )} avg bet at $10k</text>
    <text x="65" y="${y + 332}" class="body mono">${sim.median_bets.toFixed(
      0
    )} median bets / 30d</text>`;
  for (let i = 0; i <= 4; i++) {
    const py = cy + (i / 4) * h;
    const value = max - (i / 4) * (max - min);
    svg += `<line x1="${x}" y1="${py}" x2="${x + w}" y2="${py}" stroke="${C.grid}"/>`;
    svg += `<text x="${x - 15}" y="${py + 4}" text-anchor="end" class="axis">${fmtMoney(
      value,
      0
    )}</text>`;
  }
  for (const day of [0, 5, 10, 15, 20, 25, 30]) {
    const px = x + (day / 30) * w;
    svg += `<text x="${px}" y="${cy + h + 27}" text-anchor="middle" class="axis">${day}</text>`;
  }
  const baselineY = cy + h - ((10000 - min) / (max - min)) * h;
  svg += `
    <polygon points="${band(paths.p95, paths.p05, x, cy, w, h, min, max)}" fill="${accent}" opacity=".07"/>
    <polygon points="${band(paths.p75, paths.p25, x, cy, w, h, min, max)}" fill="${accent}" opacity=".15"/>
    <line x1="${x}" y1="${baselineY}" x2="${x + w}" y2="${baselineY}" stroke="${C.muted}" opacity=".55" stroke-dasharray="5 6"/>
    <polyline points="${polyline(paths.p05, x, cy, w, h, min, max)}" fill="none" stroke="${C.muted}" opacity=".4"/>
    <polyline points="${polyline(paths.p95, x, cy, w, h, min, max)}" fill="none" stroke="${C.muted}" opacity=".4"/>
    <polyline points="${polyline(paths.p50, x, cy, w, h, min, max)}" fill="none" stroke="${accent}" stroke-width="4"/>
    <text x="${x}" y="${y + 45}" class="small" fill="${accent}">P50 median</text>
    <text x="${x + 125}" y="${y + 45}" class="small">shaded P05–P95 range</text>`;
  return svg;
}

async function renderOutcomes() {
  const svg = `
  <svg width="1600" height="930" viewBox="0 0 1600 930" xmlns="http://www.w3.org/2000/svg">
    <rect width="1600" height="930" fill="${C.bg}"/>
    ${baseStyles()}
    <text x="35" y="58" class="title">Lead-wallet MLB main-market outcomes</text>
    <text x="35" y="88" class="subtitle">Moneyline, main ±1.5 run line, and main total · 5,000 calendar-day block bootstrap paths · $10,000 starting bankroll</text>
    ${outcomePanel(three, "Three lead wallets", C.blue, 120)}
    ${outcomePanel(four, "Four lead wallets", C.green, 515)}
    <text x="35" y="915" class="small">Observed settled positions through July 27, 2026. Scenario ranges are not guarantees and exclude executable two-hour price, fees, slippage, and liquidity.</text>
  </svg>`;
  const svgPath = path.join(outDir, "lead-main-markets-outcomes.svg");
  const pngPath = path.join(outDir, "lead-main-markets-outcomes.png");
  fs.writeFileSync(svgPath, svg);
  await sharp(Buffer.from(svg)).png().toFile(pngPath);
}

function metricCard(x, y, w, label, value, sub, accent = C.text) {
  return `
    <rect x="${x}" y="${y}" width="${w}" height="118" rx="12" fill="${C.panel2}" stroke="${C.border}"/>
    <text x="${x + 18}" y="${y + 28}" class="label">${esc(label)}</text>
    <text x="${x + 18}" y="${y + 68}" class="metric" fill="${accent}">${esc(value)}</text>
    <text x="${x + 18}" y="${y + 94}" class="small">${esc(sub)}</text>`;
}

function roiBars(cohort, x, y, label, accent) {
  const data = ["moneyline", "spread", "total"].map((market) => ({
    market,
    ...cohort.historical.by_market_type[market],
  }));
  const scale = 470 / 0.35;
  let svg = `<text x="${x}" y="${y}" class="section">${esc(label)}</text>`;
  data.forEach((row, index) => {
    const py = y + 42 + index * 75;
    const roi = Number(row.stake_weighted_roi || 0);
    const zero = x + 310;
    const width = Math.min(470, Math.abs(roi) * scale);
    const bx = roi >= 0 ? zero : zero - width;
    svg += `
      <text x="${x}" y="${py + 20}" class="body">${row.market[0].toUpperCase() + row.market.slice(
      1
    )}</text>
      <text x="${x + 140}" y="${py + 20}" class="small mono">${row.bets} bets</text>
      <line x1="${zero}" y1="${py - 8}" x2="${zero}" y2="${py + 30}" stroke="${C.muted}" opacity=".6"/>
      <rect x="${bx}" y="${py}" width="${width}" height="22" rx="4" fill="${
      roi >= 0 ? accent : C.red
    }"/>
      <text x="${roi >= 0 ? zero + width + 12 : bx + 12}" y="${
      py + 17
    }" text-anchor="start" class="body mono">${fmtPct(
      roi,
      1
    )}</text>`;
  });
  return svg;
}

async function renderProfile() {
  const th = three.historical;
  const fh = four.historical;
  const ts = three.simulation;
  const fsim = four.simulation;
  const svg = `
  <svg width="1600" height="1000" viewBox="0 0 1600 1000" xmlns="http://www.w3.org/2000/svg">
    <rect width="1600" height="1000" fill="${C.bg}"/>
    ${baseStyles()}
    <text x="35" y="58" class="title">Strategy frequency, edge, and path risk</text>
    <text x="35" y="88" class="subtitle">Historical settled sample and 30-day scenario distributions · units use 1% of starting bankroll</text>
    ${metricCard(35, 125, 290, "THREE · HISTORICAL ROI", fmtPct(th.stake_weighted_roi, 2), `${th.bets} bets · ${th.wins}-${th.losses}`, C.blue)}
    ${metricCard(340, 125, 290, "THREE · BETS / DAY", th.bets_per_calendar_day.toFixed(2), `${ts.median_bets.toFixed(0)} median in 30 days`, C.blue)}
    ${metricCard(645, 125, 290, "THREE · HIST. DD / RUN-UP", `${th.max_drawdown_units.toFixed(1)}u / ${th.max_runup_units.toFixed(1)}u`, "peak-to-trough / trough-to-peak")}
    ${metricCard(950, 125, 290, "THREE · 30D MEDIAN DD", `${ts.max_drawdown_units.p50.toFixed(1)}u`, `P95 ${ts.max_drawdown_units.p95.toFixed(1)}u`)}
    ${metricCard(1255, 125, 310, "THREE · 30D MEDIAN RUN-UP", `${ts.max_runup_units.p50.toFixed(1)}u`, `P95 ${ts.max_runup_units.p95.toFixed(1)}u`)}

    ${metricCard(35, 260, 290, "FOUR · HISTORICAL ROI", fmtPct(fh.stake_weighted_roi, 2), `${fh.bets} bets · ${fh.wins}-${fh.losses}`, C.green)}
    ${metricCard(340, 260, 290, "FOUR · BETS / DAY", fh.bets_per_calendar_day.toFixed(2), `${fsim.median_bets.toFixed(0)} median in 30 days`, C.green)}
    ${metricCard(645, 260, 290, "FOUR · HIST. DD / RUN-UP", `${fh.max_drawdown_units.toFixed(1)}u / ${fh.max_runup_units.toFixed(1)}u`, "peak-to-trough / trough-to-peak")}
    ${metricCard(950, 260, 290, "FOUR · 30D MEDIAN DD", `${fsim.max_drawdown_units.p50.toFixed(1)}u`, `P95 ${fsim.max_drawdown_units.p95.toFixed(1)}u`)}
    ${metricCard(1255, 260, 310, "FOUR · 30D MEDIAN RUN-UP", `${fsim.max_runup_units.p50.toFixed(1)}u`, `P95 ${fsim.max_runup_units.p95.toFixed(1)}u`)}

    <rect x="35" y="415" width="750" height="380" rx="14" fill="${C.panel}" stroke="${C.border}"/>
    <rect x="815" y="415" width="750" height="380" rx="14" fill="${C.panel}" stroke="${C.border}"/>
    ${roiBars(three, 65, 465, "Three-wallet ROI by market", C.blue)}
    ${roiBars(four, 845, 465, "Four-wallet ROI by market", C.green)}

    <rect x="35" y="825" width="1530" height="130" rx="14" fill="${C.panel}" stroke="${C.border}"/>
    <text x="65" y="863" class="label">WHAT CHANGED WHEN FORMAL-CUPCAKE WAS ADDED</text>
    <text x="65" y="903" class="metric" fill="${C.green}">33 incremental bets · 21–12 · ${fmtPct(
      payload.four_lead_incremental_vs_three.stake_weighted_roi,
      1
    )} historical ROI</text>
    <text x="65" y="932" class="small">The fourth wallet improves the corrected sample, but the incremental slice is still small and moneyline-only; it is no longer the invalid 47–1 result.</text>
    <text x="35" y="985" class="small">Main spreads were negative in this historical sample; totals were positive. Treat those market-level results as descriptive until two-hour executable-price replay is available.</text>
  </svg>`;
  const svgPath = path.join(outDir, "lead-main-markets-profile.svg");
  const pngPath = path.join(outDir, "lead-main-markets-profile.png");
  fs.writeFileSync(svgPath, svg);
  await sharp(Buffer.from(svg)).png().toFile(pngPath);
}

Promise.all([renderOutcomes(), renderProfile()])
  .then(() => console.log(outDir))
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });
