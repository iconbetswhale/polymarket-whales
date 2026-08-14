const fs = require("fs");
const path = require("path");
const sharp = require("sharp");

const root = path.resolve(__dirname, "..");
const input = path.join(root, "outputs", "lead-cohort-30-day-simulation-2026-07-28.json");
const output = path.join(root, "outputs", "lead-cohort-report", "lead-sharp-outcomes.png");
const payload = JSON.parse(fs.readFileSync(input, "utf8"));

const W = 1600;
const H = 1010;
const colors = {
  bg: "#071018",
  panel: "#0d1923",
  border: "#29404f",
  grid: "#263642",
  text: "#f4f7f8",
  muted: "#8798a6",
  green: "#73d13d",
  blue: "#23b7e5",
  gray: "#7a8994",
};

const esc = (value) =>
  String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
const seriesValues = (value) =>
  Array.isArray(value) ? value.map(Number) : String(value).trim().split(/\s+/).map(Number);
const money = (value, digits = 0) =>
  `$${Number(value).toLocaleString("en-US", { maximumFractionDigits: digits })}`;

function polyline(values, x, y, width, height, min, max) {
  return values
    .map((value, index) => {
      const px = x + (index / (values.length - 1)) * width;
      const py = y + height - ((value - min) / (max - min)) * height;
      return `${px.toFixed(1)},${py.toFixed(1)}`;
    })
    .join(" ");
}

function band(topValues, bottomValues, x, y, width, height, min, max) {
  const top = polyline(topValues, x, y, width, height, min, max);
  const bottom = polyline([...bottomValues].reverse(), x, y, width, height, min, max);
  return `${top} ${bottom}`;
}

function panel(y, label, cohort, accent) {
  const hist = cohort.historical;
  const sim = cohort.simulation;
  const paths = Object.fromEntries(
    Object.entries(sim.daily_bankroll_percentiles).map(([key, value]) => [
      key,
      seriesValues(value),
    ])
  );
  const chartX = 430;
  const chartY = y + 78;
  const chartW = 1115;
  const chartH = 245;
  const min = Math.floor((Math.min(...paths.p05, 10000) - 250) / 250) * 250;
  const max = Math.ceil((Math.max(...paths.p95, 10000) + 250) / 250) * 250;
  const medianProfit = sim.median_profit_dollars;
  const final = sim.final_bankroll;

  let svg = `
    <rect x="35" y="${y}" width="1530" height="360" rx="12" fill="${colors.panel}" stroke="${colors.border}"/>
    <text x="65" y="${y + 48}" class="eyebrow">30-DAY MEDIAN</text>
    <text x="65" y="${y + 98}" class="profit" fill="${accent}">+${esc(money(medianProfit, 2))}</text>
    <text x="65" y="${y + 130}" class="label">${esc(label)}</text>
    <text x="65" y="${y + 174}" class="metric">${(sim.roi.p50 * 100).toFixed(2)}% median ROI</text>
    <text x="65" y="${y + 201}" class="muted">${(sim.probability_profitable * 100).toFixed(2)}% of paths profitable</text>
    <line x1="65" y1="${y + 225}" x2="380" y2="${y + 225}" stroke="${colors.grid}"/>
    <text x="65" y="${y + 255}" class="eyebrow">SELECTED INPUTS</text>
    <circle cx="75" cy="${y + 285}" r="5" fill="${accent}"/>
    <text x="95" y="${y + 291}" class="small">${hist.bets_per_calendar_day.toFixed(2)} bets/day</text>
    <circle cx="75" cy="${y + 321}" r="5" fill="${accent}"/>
    <text x="95" y="${y + 327}" class="small">$${hist.median_bet_per_100_bankroll.toFixed(2)} median bet / $100</text>
    <text x="95" y="${y + 347}" class="muted-small">$${hist.average_stake_units.toFixed(2)} historical average</text>
  `;

  for (let i = 0; i <= 4; i++) {
    const py = chartY + (i / 4) * chartH;
    const value = max - (i / 4) * (max - min);
    svg += `<line x1="${chartX}" y1="${py}" x2="${chartX + chartW}" y2="${py}" stroke="${colors.grid}" opacity=".72"/>`;
    svg += `<text x="${chartX - 15}" y="${py + 4}" text-anchor="end" class="axis">$${(value / 1000).toFixed(1)}k</text>`;
  }
  for (const day of [0, 5, 10, 15, 20, 25, 30]) {
    const px = chartX + (day / 30) * chartW;
    svg += `<text x="${px}" y="${chartY + chartH + 28}" text-anchor="middle" class="axis">${day}</text>`;
  }
  svg += `
    <polygon points="${band(paths.p95, paths.p05, chartX, chartY, chartW, chartH, min, max)}" fill="${accent}" opacity=".045"/>
    <polygon points="${band(paths.p75, paths.p25, chartX, chartY, chartW, chartH, min, max)}" fill="${accent}" opacity=".10"/>
    <polyline points="${polyline(paths.p05, chartX, chartY, chartW, chartH, min, max)}" fill="none" stroke="${colors.gray}" opacity=".40" stroke-width="1.5"/>
    <polyline points="${polyline(paths.p25, chartX, chartY, chartW, chartH, min, max)}" fill="none" stroke="${colors.gray}" opacity=".72" stroke-width="2"/>
    <polyline points="${polyline(paths.p50, chartX, chartY, chartW, chartH, min, max)}" fill="none" stroke="${accent}" stroke-width="4"/>
    <polyline points="${polyline(paths.p75, chartX, chartY, chartW, chartH, min, max)}" fill="none" stroke="${colors.gray}" opacity=".72" stroke-width="2"/>
    <polyline points="${polyline(paths.p95, chartX, chartY, chartW, chartH, min, max)}" fill="none" stroke="${colors.gray}" opacity=".40" stroke-width="1.5"/>
    <line x1="${chartX}" y1="${chartY + chartH - ((10000 - min) / (max - min)) * chartH}" x2="${chartX + chartW}" y2="${chartY + chartH - ((10000 - min) / (max - min)) * chartH}" stroke="${colors.border}" stroke-width="1.5"/>
    <text x="${chartX}" y="${y + 45}" class="legend" fill="${accent}">● P50 median</text>
    <text x="${chartX + 135}" y="${y + 45}" class="legend">● P25 / P75</text>
    <text x="${chartX + 270}" y="${y + 45}" class="legend" opacity=".7">● P05 / P95</text>
    <text x="${chartX + chartW}" y="${y + 45}" text-anchor="end" class="small">
      P05 ${esc(money(final.p05))}  •  Median ${esc(money(final.p50))}  •  P95 ${esc(money(final.p95))}
    </text>
    <text x="${chartX + chartW / 2}" y="${chartY + chartH + 49}" text-anchor="middle" class="axis">Day</text>
  `;
  return svg;
}

const svg = `
<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
  <style>
    text { font-family: Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; fill: ${colors.text}; }
    .title { font-size: 29px; font-weight: 750; letter-spacing: -.4px; }
    .subtitle { font-size: 14px; fill: ${colors.muted}; }
    .eyebrow { font-size: 12px; font-weight: 700; letter-spacing: 1.2px; fill: ${colors.muted}; }
    .profit { font-size: 36px; font-weight: 800; letter-spacing: -.6px; }
    .label { font-size: 18px; font-weight: 750; }
    .metric { font-size: 17px; font-weight: 700; }
    .small { font-size: 14px; font-weight: 650; }
    .muted { font-size: 13px; fill: ${colors.muted}; }
    .muted-small { font-size: 12px; fill: ${colors.muted}; }
    .axis { font-size: 12px; fill: ${colors.muted}; }
    .legend { font-size: 13px; font-weight: 650; fill: ${colors.muted}; }
  </style>
  <rect width="${W}" height="${H}" fill="${colors.bg}"/>
  <text x="35" y="48" class="title">Lead Sharp Strategy Outcomes</text>
  <text x="35" y="78" class="subtitle">$10,000 starting bankroll  •  5,000 simulations  •  30 days  •  settled 2026 MLB moneylines through July 26</text>
  ${panel(110, "Three lead sharps", payload.cohorts.THREE_LEADS, colors.blue)}
  ${panel(495, "Four lead sharps", payload.cohorts.FOUR_LEADS, colors.green)}
  <text x="35" y="902" class="eyebrow">HOW TO READ IT</text>
  <text x="35" y="930" class="subtitle">The bright line is the median path. Inner and outer gray paths show the middle and wider outcome ranges.</text>
  <text x="35" y="965" class="muted-small">Scenario model only. Closed positions do not reconstruct exact two-hour executable prices, fees, slippage, or liquidity.</text>
  <text x="35" y="987" class="muted-small">Important: the four-lead uplift includes an unusually strong 47–1 incremental historical sample and needs forward validation.</text>
</svg>`;

fs.mkdirSync(path.dirname(output), { recursive: true });
sharp(Buffer.from(svg)).png().toFile(output).then(() => console.log(output));
