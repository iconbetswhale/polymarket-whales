const fs = require("fs");
const path = require("path");
const sharp = require("sharp");

const root = path.resolve(__dirname, "..");
const input = path.join(root, "outputs", "lead-cohort-report", "four-lead-fixed-bet-counts.json");
const output = path.join(root, "outputs", "lead-cohort-report", "four-lead-60-90-120.png");
const payload = JSON.parse(fs.readFileSync(input, "utf8"));

const W = 1600;
const H = 920;
const colors = {
  bg: "#071018",
  panel: "#0d1923",
  border: "#29404f",
  grid: "#263642",
  text: "#f4f7f8",
  muted: "#8ca0ae",
  blue: "#2c9cf0",
  cyan: "#20bed3",
  green: "#73d13d",
};
const scenarios = [
  { key: "60", label: "60 bets / month", accent: colors.blue },
  { key: "90", label: "90 bets / month", accent: colors.cyan },
  { key: "120", label: "120 bets / month", accent: colors.green },
].map((meta) => ({ ...meta, ...payload.scenarios[meta.key] }));

const esc = (v) => String(v).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
const money = (v) => `$${Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;

function line(values, x, y, width, height, min, max) {
  return values.map((value, index) => {
    const px = x + (index / (values.length - 1)) * width;
    const py = y + height - ((value - min) / (max - min)) * height;
    return `${px.toFixed(1)},${py.toFixed(1)}`;
  }).join(" ");
}

function card(s, x) {
  const e = s.ending_bankroll;
  return `
    <rect x="${x}" y="120" width="485" height="235" rx="14" fill="${colors.panel}" stroke="${colors.border}"/>
    <circle cx="${x + 34}" cy="153" r="6" fill="${s.accent}"/>
    <text x="${x + 52}" y="160" class="card-title">${esc(s.label)}</text>
    <text x="${x + 28}" y="214" class="profit" fill="${s.accent}">${money(e.p50)}</text>
    <text x="${x + 28}" y="240" class="muted">median ending bankroll</text>
    <line x1="${x + 28}" y1="262" x2="${x + 457}" y2="262" stroke="${colors.grid}"/>
    <text x="${x + 28}" y="291" class="metric">${(s.median_roi * 100).toFixed(2)}%</text>
    <text x="${x + 28}" y="314" class="muted">median ROI</text>
    <text x="${x + 180}" y="291" class="metric">${(s.probability_profitable * 100).toFixed(2)}%</text>
    <text x="${x + 180}" y="314" class="muted">profitable paths</text>
    <text x="${x + 340}" y="291" class="metric">${s.average_bets_per_day.toFixed(1)}</text>
    <text x="${x + 340}" y="314" class="muted">bets per day</text>
    <text x="${x + 28}" y="340" class="range">P05 ${money(e.p05)}  ·  P95 ${money(e.p95)}</text>
  `;
}

const chartX = 95;
const chartY = 430;
const chartW = 1410;
const chartH = 315;
const allPaths = scenarios.flatMap((s) => [
  ...s.daily_bankroll_percentiles.p05,
  ...s.daily_bankroll_percentiles.p95,
]);
const min = Math.floor((Math.min(...allPaths, 10000) - 100) / 250) * 250;
const max = Math.ceil((Math.max(...allPaths, 10000) + 100) / 250) * 250;

let grid = "";
for (let i = 0; i <= 5; i++) {
  const py = chartY + (i / 5) * chartH;
  const value = max - (i / 5) * (max - min);
  grid += `<line x1="${chartX}" y1="${py}" x2="${chartX + chartW}" y2="${py}" stroke="${colors.grid}"/>`;
  grid += `<text x="${chartX - 18}" y="${py + 5}" text-anchor="end" class="axis">${money(value)}</text>`;
}
for (const day of [0, 5, 10, 15, 20, 25, 30]) {
  const px = chartX + (day / 30) * chartW;
  grid += `<text x="${px}" y="${chartY + chartH + 32}" text-anchor="middle" class="axis">${day}</text>`;
}

const plotted = scenarios.map((s) => `
  <polyline points="${line(s.daily_bankroll_percentiles.p50, chartX, chartY, chartW, chartH, min, max)}"
    fill="none" stroke="${s.accent}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
`).join("");

const legend = scenarios.map((s, i) => `
  <circle cx="${chartX + i * 225}" cy="402" r="6" fill="${s.accent}"/>
  <text x="${chartX + 16 + i * 225}" y="408" class="legend">${esc(s.label)} median</text>
`).join("");

const svg = `
<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
  <style>
    text { font-family: Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; fill: ${colors.text}; }
    .title { font-size: 31px; font-weight: 780; letter-spacing: -.5px; }
    .subtitle { font-size: 15px; fill: ${colors.muted}; }
    .card-title { font-size: 18px; font-weight: 750; }
    .profit { font-size: 38px; font-weight: 820; letter-spacing: -.7px; }
    .metric { font-size: 20px; font-weight: 760; }
    .muted { font-size: 13px; fill: ${colors.muted}; }
    .range { font-size: 13px; font-weight: 650; fill: ${colors.muted}; }
    .axis { font-size: 12px; fill: ${colors.muted}; }
    .legend { font-size: 14px; font-weight: 650; fill: ${colors.muted}; }
    .foot { font-size: 13px; fill: ${colors.muted}; }
    .warning { font-size: 13px; font-weight: 680; fill: #e7b74b; }
  </style>
  <rect width="${W}" height="${H}" fill="${colors.bg}"/>
  <text x="50" y="52" class="title">Four-Lead Strategy: 60 vs. 90 vs. 120 Bets</text>
  <text x="50" y="83" class="subtitle">$10,000 starting bankroll · 5,000 bootstrap paths · 30 days · bankroll-scaled historical stakes</text>
  ${card(scenarios[0], 50)}
  ${card(scenarios[1], 558)}
  ${card(scenarios[2], 1066)}
  <text x="95" y="388" class="subtitle">Median bankroll path</text>
  ${legend}
  ${grid}
  <line x1="${chartX}" y1="${chartY + chartH - ((10000 - min) / (max - min)) * chartH}"
    x2="${chartX + chartW}" y2="${chartY + chartH - ((10000 - min) / (max - min)) * chartH}"
    stroke="${colors.muted}" opacity=".65" stroke-dasharray="7 7"/>
  ${plotted}
  <text x="${chartX + chartW / 2}" y="${chartY + chartH + 55}" text-anchor="middle" class="axis">Day</text>
  <text x="50" y="842" class="foot">“Profitable paths” is a bootstrap estimate assuming the historical sample remains representative—not a guaranteed real-world probability.</text>
  <text x="50" y="872" class="warning">Validation warning: the four-lead uplift includes a 47–1 incremental historical sample; exact two-hour executable prices, fees, slippage, and liquidity were not reconstructed.</text>
</svg>`;

fs.mkdirSync(path.dirname(output), { recursive: true });
sharp(Buffer.from(svg)).png().toFile(output).then(() => console.log(output));
