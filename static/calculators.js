(function calculatorsPage() {
  "use strict";

  const math = window.IconLabsCalculatorMath;
  const form = document.getElementById("calc-form");
  const tabs = document.getElementById("calc-tabs");
  if (!math || !form || !tabs) return;

  const moneyFormatter = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const compactMoneyFormatter = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 });
  const numberFormatter = new Intl.NumberFormat("en-US", { maximumFractionDigits: 3 });

  function esc(value) {
    return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[character]));
  }

  function money(value) {
    return Number.isFinite(Number(value)) ? moneyFormatter.format(Number(value)) : "—";
  }

  function compactMoney(value) {
    return Number.isFinite(Number(value)) ? compactMoneyFormatter.format(Number(value)) : "—";
  }

  function percent(value, digits = 2) {
    return Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(digits)}%` : "—";
  }

  function decimal(value, digits = 2) {
    return Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "—";
  }

  function number(value, digits = 2) {
    return Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "—";
  }

  function american(value) {
    const rounded = Math.round(Number(value));
    if (!Number.isFinite(rounded)) return "—";
    return rounded > 0 ? `+${rounded}` : String(rounded);
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function field({ key, label, value, type = "number", min, max, step = "any", prefix = "", suffix = "", help = "", options = [], full = false }) {
    const classes = ["calc-field", full ? "full" : ""].filter(Boolean).join(" ");
    if (type === "select") {
      return `<label class="${classes}"><span>${esc(label)}</span><span class="calc-select-shell"><select data-value="${esc(key)}">${options.map((option) => {
        const optionValue = typeof option === "string" ? option : option.value;
        const optionLabel = typeof option === "string" ? option : option.label;
        return `<option value="${esc(optionValue)}" ${String(optionValue) === String(value) ? "selected" : ""}>${esc(optionLabel)}</option>`;
      }).join("")}</select><i class="ph ph-caret-down" aria-hidden="true"></i></span>${help ? `<small>${esc(help)}</small>` : ""}</label>`;
    }
    const shellClasses = ["calc-input-shell", prefix ? "has-prefix" : "", suffix ? "has-suffix" : ""].filter(Boolean).join(" ");
    return `<label class="${classes}"><span>${esc(label)}</span><span class="${shellClasses}">${prefix ? `<b>${esc(prefix)}</b>` : ""}<input data-value="${esc(key)}" type="${esc(type)}" value="${esc(value)}" ${min !== undefined ? `min="${esc(min)}"` : ""} ${max !== undefined ? `max="${esc(max)}"` : ""} step="${esc(step)}" inputmode="decimal">${suffix ? `<em>${esc(suffix)}</em>` : ""}</span>${help ? `<small>${esc(help)}</small>` : ""}</label>`;
  }

  function note(title, copy, icon = "ph-info") {
    return `<section class="calc-inline-note"><i class="ph ${esc(icon)}" aria-hidden="true"></i><div><strong>${esc(title)}</strong><p>${esc(copy)}</p></div></section>`;
  }

  function oddsList(values, { min = 2, max = 8, results = null, label = "Outcomes", help = "Enter American odds for every mutually exclusive outcome." } = {}) {
    return `<section class="calc-list"><header><div><span>${esc(label)}</span><small>${esc(help)}</small></div><button type="button" data-add-leg ${values.length >= max ? "disabled" : ""}><i class="ph ph-plus" aria-hidden="true"></i>Add leg</button></header><div class="calc-leg-list">${values.map((value, index) => `<div class="calc-leg-row ${results ? "with-result" : ""}"><span>${results ? `Leg ${index + 1}` : `Outcome ${index + 1}`}</span><input type="number" data-array="odds" data-index="${index}" value="${esc(value)}" step="1" inputmode="numeric" aria-label="${results ? "Leg" : "Outcome"} ${index + 1} American odds">${results ? `<span class="calc-select-shell"><select data-array="results" data-index="${index}" aria-label="Leg ${index + 1} result"><option value="win" ${results[index] !== false ? "selected" : ""}>Win</option><option value="loss" ${results[index] === false ? "selected" : ""}>Loss</option></select><i class="ph ph-caret-down" aria-hidden="true"></i></span>` : ""}<button type="button" data-remove-leg="${index}" ${values.length <= min ? "disabled" : ""} aria-label="Remove ${results ? "leg" : "outcome"} ${index + 1}"><i class="ph ph-x" aria-hidden="true"></i></button></div>`).join("")}</div></section>`;
  }

  function metric(label, value, detail = "", tone = "") {
    return { label, value, detail, tone };
  }

  function result({ heading, label, value, detail, tone = "", icon = "ph-function", metrics = [], verdict, formula, caveat }) {
    return { heading, hero: { label, value, detail, tone, icon }, metrics, verdict, formula, caveat };
  }

  const definitions = {
    arbitrage: {
      title: "Arbitrage Calculator",
      kicker: "HEDGE & RISK",
      icon: "ph-intersect-three",
      description: "Split a stake across every outcome to equalize payout and identify a guaranteed return.",
      defaults: { stake: 1000, odds: [110, 110] },
      example: { stake: 1000, odds: [138, 245, 330] },
      fields(values) {
        return field({ key: "stake", label: "Total stake", value: values.stake, min: 1, step: 25, prefix: "$", help: "The full amount allocated across all outcomes.", full: true }) + oddsList(values.odds, { max: 5 });
      },
      calculate(values) {
        const output = math.arbitrage(values);
        const tone = output.isArbitrage ? "positive" : "negative";
        return result({
          heading: "Guaranteed return",
          label: output.isArbitrage ? "Guaranteed profit" : "Guaranteed loss",
          value: money(output.guaranteedProfit),
          detail: `${percent(output.roi)} return after cent-level stake balancing`,
          tone,
          icon: output.isArbitrage ? "ph-shield-check" : "ph-warning",
          metrics: [
            metric("Total stake", money(values.stake)),
            metric("Minimum payout", money(output.minimumPayout), "Lowest payout across outcomes", tone),
            metric("Implied total", percent(output.impliedTotal), "Must be below 100% for an arb", output.isArbitrage ? "positive" : "negative"),
            metric("Stake plan", output.stakes.map((stake) => money(stake)).join(" · "), "One amount per outcome"),
          ],
          verdict: {
            tone,
            icon: output.isArbitrage ? "ph-check-circle" : "ph-x-circle",
            title: output.isArbitrage ? "Arbitrage found" : "No arbitrage at these prices",
            copy: output.isArbitrage ? "Every outcome is sized to return nearly the same payout." : "The implied probabilities meet or exceed 100%, so equalizing payouts locks in a loss.",
          },
          formula: "stakeᵢ = total stake × (1 ÷ decimal oddsᵢ) ÷ Σ(1 ÷ decimal odds)",
          caveat: "A return is only guaranteed when every leg is accepted at the displayed price and stake.",
        });
      },
    },
    "expected-value": {
      title: "Expected Value Calculator",
      kicker: "VALUE & EDGE",
      icon: "ph-trend-up",
      description: "Compare your estimated win probability with the price offered by the market.",
      defaults: { stake: 100, odds: 110, winProbability: 60 },
      example: { stake: 100, odds: 110, winProbability: 55 },
      fields(values) {
        return field({ key: "stake", label: "Wager", value: values.stake, min: 0.01, step: 5, prefix: "$" }) + field({ key: "odds", label: "American odds", value: values.odds, step: 1, help: "Use + for underdogs and − for favorites." }) + field({ key: "winProbability", label: "Your win probability", value: values.winProbability, min: 0.01, max: 99.99, step: 0.1, suffix: "%", full: true }) + note("Use a fair probability", "Your estimate should exclude the sportsbook margin. The no-vig calculator can normalize a two- or three-way market.", "ph-shield-check");
      },
      calculate(values) {
        const output = math.expectedValue({ ...values, winProbability: Number(values.winProbability) / 100 });
        const tone = output.expectedProfit >= 0 ? "positive" : "negative";
        return result({
          heading: "Expected value",
          label: "Expected net per wager",
          value: money(output.expectedProfit),
          detail: `${percent(output.roi)} expected ROI on ${money(values.stake)}`,
          tone,
          icon: output.expectedProfit >= 0 ? "ph-trend-up" : "ph-trend-down",
          metrics: [
            metric("Profit if win", money(output.profitIfWin)),
            metric("Fair price", american(output.fairAmerican), "Based on your win estimate"),
            metric("Probability edge", percent(output.edge), "Your probability minus break-even", tone),
            metric("Expected return", money(output.expectedReturn), "Stake plus expected net"),
          ],
          verdict: { tone, icon: output.expectedProfit >= 0 ? "ph-check-circle" : "ph-warning-circle", title: output.expectedProfit >= 0 ? "Positive expected value" : "Negative expected value", copy: output.expectedProfit >= 0 ? "Your estimated win rate is above the price's break-even probability." : "The offered price requires a higher win rate than your estimate." },
          formula: "EV = p(win) × profit if win − p(loss) × stake",
          caveat: "Expected value describes the long-run average, not the result of one wager.",
        });
      },
    },
    "bonus-bet": {
      title: "Bonus Bet Conversion Calculator",
      kicker: "HEDGE & RISK",
      icon: "ph-gift",
      description: "Size a cash hedge against a stake-not-returned bonus bet and lock the same net result.",
      defaults: { amount: 100, bonusOdds: 300, hedgeOdds: -275 },
      example: { amount: 250, bonusOdds: 450, hedgeOdds: -400 },
      fields(values) {
        return field({ key: "amount", label: "Bonus bet amount", value: values.amount, min: 1, step: 5, prefix: "$", help: "Assumes the promotional stake is not returned." }) + field({ key: "bonusOdds", label: "Bonus bet odds", value: values.bonusOdds, step: 1 }) + field({ key: "hedgeOdds", label: "Hedge odds", value: values.hedgeOdds, step: 1, full: true }) + note("Opposite outcomes only", "The bonus selection and hedge must cover mutually exclusive sides of the same market.", "ph-arrows-left-right");
      },
      calculate(values) {
        const output = math.bonusBet(values);
        return result({
          heading: "Conversion return",
          label: "Locked cash profit",
          value: money(output.lockedProfit),
          detail: `${percent(output.conversionRate)} conversion of the bonus amount`,
          tone: "positive",
          icon: "ph-currency-dollar",
          metrics: [
            metric("Hedge stake", money(output.hedgeStake), "Cash wager on the opposite side", "warning"),
            metric("Bonus-side net", money(output.bonusWinsNet)),
            metric("Hedge-side net", money(output.hedgeWinsNet)),
            metric("Bonus profit before hedge", money(output.freeBetProfit)),
          ],
          verdict: { tone: "positive", icon: "ph-lock-key", title: "Outcomes equalized", copy: "If both wagers fill, either result produces the same net profit before taxes, limits, or settlement differences." },
          formula: "hedge stake = bonus amount × (bonus decimal − 1) ÷ hedge decimal",
          caveat: "This model assumes stake-not-returned bonus rules and no commission on either side.",
        });
      },
    },
    "half-point": {
      title: "Half Point Calculator",
      kicker: "LINE CONVERSION",
      icon: "ph-plus-minus",
      description: "Estimate the fair price of buying or selling a half point using league-specific push frequencies.",
      defaults: { market: "spread", league: "NFL", line: 3, odds: -110, direction: "buy" },
      example: { market: "total", league: "MLB", line: 8, odds: -110, direction: "buy" },
      fields(values) {
        const leagueOptions = ["NFL", "NCAAF", "NBA", "WNBA", "NCAAB", "MLB", "NHL"];
        return field({ key: "market", label: "Bet type", type: "select", value: values.market, options: [{ value: "spread", label: "Spread" }, { value: "total", label: "Total" }] }) + field({ key: "league", label: "League", type: "select", value: values.league, options: leagueOptions }) + field({ key: "line", label: "Reference whole number", value: values.line, step: 1, help: "Key-number push frequency changes by league." }) + field({ key: "odds", label: "Current price", value: values.odds, step: 1 }) + field({ key: "direction", label: "Half-point move", type: "select", value: values.direction, full: true, options: [{ value: "buy", label: "Buy half point (more favorable)" }, { value: "sell", label: "Sell half point (less favorable)" }] }) + note("Historical calibration", "IconLabs uses transparent league and key-number push-rate assumptions; these are not a copy of any third-party proprietary dataset.", "ph-database");
      },
      calculate(values) {
        const output = math.halfPoint(values);
        return result({
          heading: "Adjusted fair price",
          label: output.direction === "buy" ? "Fair price after buying" : "Fair price after selling",
          value: american(output.fairAmerican),
          detail: `${decimal(output.fairDecimal, 3)} decimal · ${percent(output.adjustedWin)} break-even`,
          tone: output.direction === "buy" ? "warning" : "positive",
          icon: "ph-plus-minus",
          metrics: [
            metric("Reference price", american(values.odds)),
            metric("Push mass used", percent(output.pushMass), `${values.league} ${values.market} at ${values.line}`),
            metric("Original break-even", percent(output.conditionalWin)),
            metric("Adjusted break-even", percent(output.adjustedWin)),
          ],
          verdict: { tone: "warning", icon: "ph-database", title: "Model-based estimate", copy: "Half-point value depends on the historical chance of landing exactly on the crossed number." },
          formula: output.direction === "buy" ? "adjusted p = (1 − push mass) × original p + push mass" : "adjusted p = (1 − push mass) × original p",
          caveat: "League scoring environments evolve; use this as a comparison baseline, not a live market quote.",
        });
      },
    },
    hold: {
      title: "Hold Calculator",
      kicker: "MARKET QUALITY",
      icon: "ph-scales",
      description: "Measure the market overround by adding the implied probability of every side.",
      defaults: { odds: [-110, -110] },
      example: { odds: [120, -145] },
      fields(values) { return oddsList(values.odds, { max: 5, label: "Market sides", help: "Use all mutually exclusive outcomes in the market." }); },
      calculate(values) {
        const output = math.hold(values);
        const tone = output.hold <= 0 ? "positive" : output.hold <= 0.05 ? "warning" : "negative";
        return result({
          heading: "Sportsbook hold",
          label: "Market overround",
          value: percent(output.hold),
          detail: `${percent(output.impliedTotal)} combined implied probability`,
          tone,
          icon: "ph-scales",
          metrics: output.fairProbabilities.slice(0, 4).map((value, index) => metric(`Fair side ${index + 1}`, percent(value), american(output.fairOdds[index]))),
          verdict: { tone, icon: output.hold <= 0.05 ? "ph-check-circle" : "ph-warning", title: output.hold <= 0.05 ? "Competitive market" : "High-hold market", copy: "Lower hold generally means less price friction for the bettor." },
          formula: "hold = Σ implied probabilities − 100%",
          caveat: "Hold is a pricing measure, not the sportsbook's guaranteed realized profit.",
        });
      },
    },
    "implied-probability": {
      title: "Implied Probability Calculator",
      kicker: "ODDS CONVERSION",
      icon: "ph-percent",
      description: "Translate American odds into break-even probability, profit, payout, and other price formats.",
      defaults: { stake: 100, odds: 110 },
      example: { stake: 250, odds: -135 },
      fields(values) { return field({ key: "stake", label: "Bet amount", value: values.stake, min: 0.01, step: 5, prefix: "$" }) + field({ key: "odds", label: "American odds", value: values.odds, step: 1 }) + note("Break-even threshold", "You need a true win rate above the implied probability to have positive expected value at this price.", "ph-target"); },
      calculate(values) {
        const output = math.implied(values);
        return result({
          heading: "Break-even probability",
          label: "Implied win probability",
          value: percent(output.probability),
          detail: `${american(output.american)} · ${decimal(output.decimal)} decimal · ${output.fractional}`,
          icon: "ph-percent",
          metrics: [metric("Profit if win", money(output.profit), "Net winnings"), metric("Total payout", money(output.payout), "Stake plus profit"), metric("Decimal odds", decimal(output.decimal)), metric("Fractional odds", output.fractional)],
          verdict: { tone: "", icon: "ph-target", title: "Your break-even line", copy: `At ${american(output.american)}, winning more than ${percent(output.probability)} of comparable bets produces a positive long-run expectation.` },
          formula: "positive odds: p = 100 ÷ (odds + 100) · negative odds: p = |odds| ÷ (|odds| + 100)",
          caveat: "The implied probability includes any sportsbook margin embedded in the price.",
        });
      },
    },
    kelly: {
      title: "Kelly Criterion Calculator",
      kicker: "BANKROLL SIZING",
      icon: "ph-chart-donut",
      description: "Turn your edge into a bankroll fraction using full, half, or quarter Kelly sizing.",
      defaults: { bankroll: 12000, odds: 110, winProbability: 60, multiplier: 0.25 },
      example: { bankroll: 5000, odds: -105, winProbability: 54, multiplier: 0.5 },
      fields(values) {
        return field({ key: "bankroll", label: "Bankroll", value: values.bankroll, min: 1, step: 100, prefix: "$" }) + field({ key: "odds", label: "American odds", value: values.odds, step: 1 }) + field({ key: "winProbability", label: "Fair win probability", value: values.winProbability, min: 0.01, max: 99.99, step: 0.1, suffix: "%" }) + field({ key: "multiplier", label: "Kelly multiplier", type: "select", value: values.multiplier, options: [{ value: 1, label: "Full Kelly (1.00×)" }, { value: 0.5, label: "Half Kelly (0.50×)" }, { value: 0.25, label: "Quarter Kelly (0.25×)" }, { value: 0.1, label: "Tenth Kelly (0.10×)" }] }) + note("Protect against model error", "Fractional Kelly reduces volatility and the impact of an overconfident win estimate.", "ph-shield-check");
      },
      calculate(values) {
        const output = math.kelly({ ...values, winProbability: Number(values.winProbability) / 100, multiplier: Number(values.multiplier) });
        const hasBet = output.recommendedStake > 0;
        return result({
          heading: "Recommended stake",
          label: hasBet ? "Amount to wager" : "Recommended wager",
          value: money(output.recommendedStake),
          detail: `${percent(output.recommendedFraction)} of bankroll at ${Number(values.multiplier)}× Kelly`,
          tone: hasBet ? "positive" : "negative",
          icon: "ph-chart-donut",
          metrics: [metric("Full Kelly fraction", percent(Math.max(0, output.fullKelly))), metric("Expected ROI", percent(output.ev), "Per dollar staked", output.ev >= 0 ? "positive" : "negative"), metric("Probability edge", percent(output.edge)), metric("Bankroll", compactMoney(values.bankroll))],
          verdict: { tone: hasBet ? "positive" : "negative", icon: hasBet ? "ph-check-circle" : "ph-hand", title: hasBet ? "Positive edge supports a wager" : "Pass at this price", copy: hasBet ? "The fraction is scaled by your selected Kelly multiplier." : "Kelly recommends no bet when the estimated edge is zero or negative." },
          formula: "Kelly fraction = (b × p − q) ÷ b, where b is net decimal profit",
          caveat: "Kelly is highly sensitive to probability error. Treat bankroll as money you can afford to lose.",
        });
      },
    },
    "no-vig": {
      title: "No-Vig Fair Odds Calculator",
      kicker: "VALUE & EDGE",
      icon: "ph-shield-check",
      description: "Remove the market margin by proportionally normalizing every implied probability to 100%.",
      defaults: { odds: [-110, -110] },
      example: { odds: [-180, 155] },
      fields(values) { return oddsList(values.odds, { max: 5, label: "Market prices", help: "Include every mutually exclusive outcome from the same source." }) + note("Proportional normalization", "IconLabs uses the transparent multiplicative method: each raw probability is divided by the market total.", "ph-function"); },
      calculate(values) {
        const output = math.noVig(values);
        return result({
          heading: "Fair market",
          label: "Margin removed",
          value: percent(output.overround),
          detail: `${percent(output.impliedTotal)} raw total normalized to 100%`,
          tone: output.overround >= 0 ? "warning" : "positive",
          icon: "ph-shield-check",
          metrics: output.fairProbabilities.slice(0, 4).map((value, index) => metric(`Outcome ${index + 1}`, percent(value), `${american(output.fairOdds[index])} fair odds`, "positive")),
          verdict: { tone: "positive", icon: "ph-check-circle", title: "Fair probabilities sum to 100%", copy: "Use these normalized prices as a market-implied baseline for EV comparisons." },
          formula: "fair pᵢ = raw implied pᵢ ÷ Σ raw implied probabilities",
          caveat: "Different de-vig methods can produce different fair prices, especially in longshot markets.",
        });
      },
    },
    "odds-converter": {
      title: "Odds Converter Calculator",
      kicker: "ODDS CONVERSION",
      icon: "ph-arrows-left-right",
      description: "Convert an American price to decimal, fractional, implied probability, profit, and payout.",
      defaults: { stake: 100, american: 110 },
      example: { stake: 50, american: -200 },
      fields(values) { return field({ key: "stake", label: "Bet amount", value: values.stake, min: 0.01, step: 5, prefix: "$" }) + field({ key: "american", label: "American odds", value: values.american, step: 1 }) + note("One price, four formats", "Decimal odds include the returned stake. Fractional odds describe profit relative to stake.", "ph-arrows-left-right"); },
      calculate(values) {
        const output = math.oddsConverter(values);
        return result({
          heading: "Converted odds",
          label: "Decimal odds",
          value: decimal(output.decimal),
          detail: `${american(output.american)} American · ${output.fractional} fractional`,
          icon: "ph-arrows-left-right",
          metrics: [metric("Implied probability", percent(output.probability)), metric("Fractional odds", output.fractional), metric("Profit", money(output.profit)), metric("Payout", money(output.payout))],
          verdict: { tone: "", icon: "ph-equals", title: "Equivalent price formats", copy: "Every displayed format represents the same break-even probability and potential return." },
          formula: "positive American: decimal = 1 + odds ÷ 100 · negative: decimal = 1 + 100 ÷ |odds|",
          caveat: "Fractional output is reduced to a practical denominator and may be a close approximation for unusual prices.",
        });
      },
    },
    parlay: {
      title: "Parlay Calculator",
      kicker: "COMBINATIONS",
      icon: "ph-stack",
      description: "Multiply leg prices to calculate combined parlay odds, payout, and break-even probability.",
      defaults: { stake: 100, odds: [110, 110, 110] },
      example: { stake: 50, odds: [-110, 125, 180, -105] },
      fields(values) { return field({ key: "stake", label: "Parlay stake", value: values.stake, min: 0.01, step: 5, prefix: "$", full: true }) + oddsList(values.odds, { max: 10, label: "Parlay legs", help: "All legs must win for the parlay to pay." }); },
      calculate(values) {
        const output = math.parlay(values);
        return result({
          heading: "Parlay payout",
          label: "Total payout",
          value: money(output.payout),
          detail: `${american(output.combinedAmerican)} combined odds · ${values.odds.length} legs`,
          tone: "positive",
          icon: "ph-stack",
          metrics: [metric("Total profit", money(output.profit), "Payout minus stake", "positive"), metric("Combined decimal", decimal(output.combinedDecimal, 3)), metric("Implied probability", percent(output.impliedProbability)), metric("Stake", money(values.stake))],
          verdict: { tone: "warning", icon: "ph-warning", title: "Every leg must win", copy: "The combined probability falls as more legs are added, even while the potential payout rises." },
          formula: "combined decimal odds = decimal leg₁ × decimal leg₂ × … × decimal legₙ",
          caveat: "This assumes independent legs and does not apply same-game-parlay correlation adjustments.",
        });
      },
    },
    "prediction-market": {
      title: "Prediction Markets Converter",
      kicker: "ODDS CONVERSION",
      icon: "ph-chart-line-up",
      description: "Convert a prediction-market price into probability and traditional betting odds.",
      defaults: { price: 65, stake: 100 },
      example: { price: 37, stake: 250 },
      fields(values) { return field({ key: "price", label: "Market price", value: values.price, min: 0.01, max: 99.99, step: 0.1, suffix: "¢" }) + field({ key: "stake", label: "Order amount", value: values.stake, min: 0.01, step: 5, prefix: "$" }) + note("Fee-free baseline", "A 65¢ contract pays $1 if the outcome resolves yes, before exchange fees and slippage.", "ph-coins"); },
      calculate(values) {
        const output = math.predictionMarket(values);
        return result({
          heading: "Traditional odds",
          label: "American odds",
          value: american(output.american),
          detail: `${percent(output.probability)} implied probability · ${decimal(output.decimal)} decimal`,
          icon: "ph-chart-line-up",
          metrics: [metric("Fractional odds", output.fractional), metric("Contracts", number(output.contracts, 2), "At the entered order amount"), metric("Gross payout", money(output.grossPayout)), metric("Profit before fees", money(output.profit), "If the contract resolves yes", "positive")],
          verdict: { tone: "", icon: "ph-arrows-left-right", title: "Direct probability conversion", copy: "Prediction-market cents map directly to probability when fees, spread, and slippage are excluded." },
          formula: "probability = price in cents ÷ 100 · decimal odds = 1 ÷ probability",
          caveat: "Actual execution may include fees, bid-ask spread, partial fills, and resolution risk.",
        });
      },
    },
    "point-spread": {
      title: "Point Spread Calculator",
      kicker: "LINE CONVERSION",
      icon: "ph-arrows-out-line-horizontal",
      description: "Estimate moneyline equivalents from a point spread with calibrated league scoring curves.",
      defaults: { league: "NFL", spread: -5, marketHold: 4.76 },
      example: { league: "NBA", spread: -7.5, marketHold: 4.76 },
      fields(values) {
        return field({ key: "league", label: "League", type: "select", value: values.league, options: ["NFL", "NCAAF", "NBA", "WNBA"] }) + field({ key: "spread", label: "Favorite spread", value: values.spread, step: 0.5, help: "Use the favorite's negative spread; magnitude drives the model." }) + field({ key: "marketHold", label: "Target market hold", value: values.marketHold, min: 0, max: 24.99, step: 0.01, suffix: "%", full: true }) + note("Calibrated curve", "Spread-to-moneyline conversion uses an IconLabs logistic league baseline plus the selected market hold. It is not a live price feed.", "ph-chart-line");
      },
      calculate(values) {
        const output = math.pointSpread({ ...values, marketHold: Number(values.marketHold) / 100 });
        return result({
          heading: "Moneyline equivalents",
          label: "Favorite moneyline",
          value: american(output.favoriteMoneyline),
          detail: `${values.league} ${Number(values.spread).toFixed(1)} spread · ${percent(output.marketHold)} modeled hold`,
          icon: "ph-arrows-out-line-horizontal",
          metrics: [metric("Underdog moneyline", american(output.underdogMoneyline)), metric("Favorite fair win rate", percent(output.favoriteProbability)), metric("Underdog fair win rate", percent(output.underdogProbability)), metric("League scale", number(output.scale, 2), "IconLabs calibration")],
          verdict: { tone: "warning", icon: "ph-chart-line", title: "Historical baseline, not a quote", copy: "Compare the model output with live moneylines to spot meaningful price differences." },
          formula: "favorite p = 1 ÷ (1 + e^(−|spread| ÷ league scale)); hold is then split across both sides",
          caveat: "Injuries, totals, home field, and matchup shape can make a live moneyline differ from this baseline.",
        });
      },
    },
    poisson: {
      title: "Poisson Calculator",
      kicker: "PROBABILITY MODEL",
      icon: "ph-wave-sine",
      description: "Estimate exact, at-least, and at-most event probabilities from an expected average.",
      defaults: { average: 2.7, proposition: 4 },
      example: { average: 1.45, proposition: 2 },
      fields(values) { return field({ key: "average", label: "Expected average", value: values.average, min: 0.001, step: 0.01, help: "The Poisson rate λ for the selected time period." }) + field({ key: "proposition", label: "Proposition", value: values.proposition, min: 0, max: 170, step: 1, help: "A whole-number count such as goals, threes, or strikeouts." }) + note("Distribution assumption", "Poisson is most useful for independent count events with a stable rate. It is a baseline, not a complete player or game model.", "ph-wave-sine"); },
      calculate(values) {
        const output = math.poisson(values);
        return result({
          heading: "Poisson probabilities",
          label: `At least ${Math.floor(Number(values.proposition))}`,
          value: percent(output.atLeast),
          detail: `${american(output.atLeastOdds)} fair odds under the Poisson assumption`,
          icon: "ph-wave-sine",
          metrics: [metric(`Exactly ${Math.floor(Number(values.proposition))}`, percent(output.exactly), american(output.exactlyOdds)), metric(`At most ${Math.floor(Number(values.proposition))}`, percent(output.atMost), american(output.atMostOdds)), metric("Expected average λ", number(values.average, 2)), metric("At-least fair price", american(output.atLeastOdds))],
          verdict: { tone: "warning", icon: "ph-function", title: "Model-implied fair line", copy: "Compare the fair odds with the offered price only when the Poisson assumptions are reasonable for the event." },
          formula: "P(X = k) = e^(−λ) × λᵏ ÷ k!",
          caveat: "Rate changes, overdispersion, playing time, and event dependence can make real outcomes differ materially.",
        });
      },
    },
    "round-robin": {
      title: "Round Robin Calculator",
      kicker: "COMBINATIONS",
      icon: "ph-circles-three-plus",
      description: "Build every k-leg parlay combination, calculate total risk, and simulate settled legs.",
      defaults: { stakePerBet: 5, parlaySize: 2, odds: [110, 110, 110, 110, 110], results: [true, true, true, true, true] },
      example: { stakePerBet: 10, parlaySize: 3, odds: [-110, 120, 145, -105, 180], results: [true, true, false, true, false] },
      fields(values) {
        const maxSize = Math.max(2, values.odds.length - 1);
        const sizeOptions = Array.from({ length: maxSize - 1 }, (_, index) => ({ value: index + 2, label: `${index + 2}-leg parlays` }));
        if (Number(values.parlaySize) > maxSize) values.parlaySize = maxSize;
        return field({ key: "stakePerBet", label: "Stake per parlay", value: values.stakePerBet, min: 0.01, step: 1, prefix: "$" }) + field({ key: "parlaySize", label: "Parlay size", type: "select", value: values.parlaySize, options: sizeOptions }) + oddsList(values.odds, { min: 3, max: 8, results: values.results, label: "Round-robin legs", help: "Set each leg to win or loss to simulate the final return." });
      },
      calculate(values) {
        const output = math.roundRobin(values);
        const tone = output.simulatedProfit >= 0 ? "positive" : "negative";
        return result({
          heading: "Round-robin return",
          label: "Simulated net",
          value: money(output.simulatedProfit),
          detail: `${output.winningTickets} of ${output.combinations} tickets win in the selected scenario`,
          tone,
          icon: "ph-circles-three-plus",
          metrics: [metric("Total risk", money(output.totalRisk), `${money(values.stakePerBet)} × ${output.combinations} parlays`, "warning"), metric("Maximum payout", money(output.maxPayout)), metric("Maximum profit", money(output.maxProfit), "If every leg wins", "positive"), metric("Simulated payout", money(output.simulatedPayout), "Winning tickets only", tone)],
          verdict: { tone, icon: tone === "positive" ? "ph-check-circle" : "ph-warning", title: `${output.combinations} separate parlays`, copy: `A ${values.odds.length}-leg round robin by ${values.parlaySize}s creates C(${values.odds.length}, ${values.parlaySize}) = ${output.combinations} tickets.` },
          formula: "ticket count = n! ÷ (k! × (n − k)!); each ticket payout multiplies its k decimal odds",
          caveat: "Stake is interpreted per combination, matching the common sportsbook round-robin convention.",
        });
      },
    },
    vig: {
      title: "Vig Calculator",
      kicker: "MARKET QUALITY",
      icon: "ph-receipt",
      description: "Translate market overround into the bookmaker's theoretical commission share of balanced handle.",
      defaults: { odds: [-110, -110] },
      example: { odds: [-125, 105] },
      fields(values) { return oddsList(values.odds, { max: 5, label: "Market sides", help: "Include every mutually exclusive outcome in the same market." }) + note("Vig versus hold", "Hold is raw overround. Vig divides that overround by total implied probability to estimate the commission share of balanced action.", "ph-receipt"); },
      calculate(values) {
        const output = math.vig(values);
        const tone = output.vig <= 0 ? "positive" : output.vig <= 0.05 ? "warning" : "negative";
        return result({
          heading: "Sportsbook vig",
          label: "Theoretical vig",
          value: percent(output.vig),
          detail: `${percent(output.overround)} raw hold · ${percent(output.impliedTotal)} implied total`,
          tone,
          icon: "ph-receipt",
          metrics: output.fairProbabilities.slice(0, 4).map((value, index) => metric(`Fair side ${index + 1}`, percent(value), "Normalized probability")),
          verdict: { tone, icon: output.vig <= 0.05 ? "ph-check-circle" : "ph-warning", title: output.vig <= 0.05 ? "Typical or low vig" : "Expensive market", copy: "Compare the vig across books and markets; a lower percentage generally means a better price environment." },
          formula: "vig = (Σ implied probabilities − 1) ÷ Σ implied probabilities",
          caveat: "This is a theoretical balanced-market measure and can differ from a book's realized margin.",
        });
      },
    },
  };

  const state = {
    active: definitions[location.hash.slice(1)] ? location.hash.slice(1) : "arbitrage",
    values: {},
    lastResult: null,
  };

  Object.entries(definitions).forEach(([key, definition]) => { state.values[key] = clone(definition.defaults); });

  const elements = {
    title: document.getElementById("calc-active-title"),
    kicker: document.getElementById("calc-active-kicker"),
    description: document.getElementById("calc-active-description"),
    icon: document.getElementById("calc-active-icon"),
    resultHeading: document.getElementById("calc-result-heading"),
    hero: document.getElementById("calc-result-hero"),
    grid: document.getElementById("calc-result-grid"),
    verdict: document.getElementById("calc-verdict"),
    formula: document.getElementById("calc-formula"),
    search: document.getElementById("calc-search"),
    workspace: document.querySelector(".calc-workspace"),
    empty: document.getElementById("calc-empty-search"),
    methodPanel: document.getElementById("calc-method-panel"),
    methodToggle: document.getElementById("calc-method-toggle"),
  };

  function renderResult(output) {
    state.lastResult = output;
    elements.resultHeading.textContent = output.heading;
    elements.hero.innerHTML = `<div><span>${esc(output.hero.label)}</span><strong class="${esc(output.hero.tone)}">${esc(output.hero.value)}</strong><p>${esc(output.hero.detail)}</p></div><i class="ph ${esc(output.hero.icon)}" aria-hidden="true"></i>`;
    elements.grid.innerHTML = output.metrics.map((item) => `<article><span>${esc(item.label)}</span><strong class="${esc(item.tone || "")}">${esc(item.value)}</strong>${item.detail ? `<small>${esc(item.detail)}</small>` : ""}</article>`).join("");
    elements.verdict.className = `calc-verdict ${output.verdict.tone || ""}`;
    elements.verdict.innerHTML = `<i class="ph ${esc(output.verdict.icon)}" aria-hidden="true"></i><div><strong>${esc(output.verdict.title)}</strong><p>${esc(output.verdict.copy)}</p></div>`;
    elements.formula.innerHTML = `<span>Formula</span><code>${esc(output.formula)}</code><p>${esc(output.caveat)}</p>`;
  }

  function renderError(error) {
    state.lastResult = null;
    elements.resultHeading.textContent = "Check your inputs";
    elements.hero.innerHTML = `<section class="calc-error"><i class="ph ph-warning-circle" aria-hidden="true"></i><strong>Unable to calculate</strong><p>${esc(error.message || "Enter valid values to continue.")}</p></section>`;
    elements.grid.innerHTML = "";
    elements.verdict.innerHTML = "";
    elements.formula.innerHTML = "";
  }

  function calculateActive() {
    try {
      renderResult(definitions[state.active].calculate(state.values[state.active]));
    } catch (error) {
      renderError(error);
    }
  }

  function renderActive({ focus = false } = {}) {
    const definition = definitions[state.active];
    const values = state.values[state.active];
    elements.title.textContent = definition.title;
    elements.kicker.textContent = definition.kicker;
    elements.description.textContent = definition.description;
    elements.icon.innerHTML = `<i class="ph ${esc(definition.icon)}" aria-hidden="true"></i>`;
    form.innerHTML = definition.fields(values);
    tabs.querySelectorAll("[data-calculator]").forEach((button) => {
      const selected = button.dataset.calculator === state.active;
      button.classList.toggle("active", selected);
      button.setAttribute("aria-selected", selected ? "true" : "false");
    });
    calculateActive();
    if (focus) form.querySelector("input, select")?.focus();
  }

  function selectCalculator(key, { updateHash = true, focus = false } = {}) {
    if (!definitions[key]) return;
    state.active = key;
    if (updateHash) history.replaceState(null, "", `#${key}`);
    renderActive({ focus });
  }

  function filterTabs(query) {
    const needle = query.trim().toLowerCase();
    let visibleCount = 0;
    let firstVisible = null;
    tabs.querySelectorAll("[data-calculator]").forEach((button) => {
      const key = button.dataset.calculator;
      const definition = definitions[key];
      const haystack = `${definition.title} ${definition.kicker} ${definition.description} ${key}`.toLowerCase();
      const visible = !needle || haystack.includes(needle);
      button.hidden = !visible;
      if (visible) {
        visibleCount += 1;
        firstVisible ||= key;
      }
    });
    elements.empty.hidden = visibleCount > 0;
    elements.workspace.hidden = visibleCount === 0;
    if (visibleCount && tabs.querySelector(`[data-calculator="${CSS.escape(state.active)}"]`)?.hidden) selectCalculator(firstVisible, { updateHash: false });
  }

  form.addEventListener("input", (event) => {
    const input = event.target;
    const values = state.values[state.active];
    if (input.dataset.value) values[input.dataset.value] = input.value;
    if (input.dataset.array) {
      const index = Number(input.dataset.index);
      if (input.dataset.array === "results") values.results[index] = input.value === "win";
      else values[input.dataset.array][index] = input.value;
    }
    calculateActive();
  });

  form.addEventListener("change", (event) => {
    event.target.dispatchEvent(new Event("input", { bubbles: true }));
  });

  form.addEventListener("click", (event) => {
    const values = state.values[state.active];
    const add = event.target.closest("[data-add-leg]");
    if (add) {
      values.odds.push(110);
      if (Array.isArray(values.results)) values.results.push(true);
      renderActive();
      return;
    }
    const remove = event.target.closest("[data-remove-leg]");
    if (remove) {
      const index = Number(remove.dataset.removeLeg);
      values.odds.splice(index, 1);
      if (Array.isArray(values.results)) values.results.splice(index, 1);
      renderActive();
    }
  });

  tabs.addEventListener("click", (event) => {
    const button = event.target.closest("[data-calculator]");
    if (button) selectCalculator(button.dataset.calculator);
  });

  tabs.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    const buttons = [...tabs.querySelectorAll("[data-calculator]:not([hidden])")];
    const current = buttons.indexOf(event.target.closest("[data-calculator]"));
    if (current < 0) return;
    event.preventDefault();
    const direction = event.key === "ArrowRight" ? 1 : -1;
    const next = buttons[(current + direction + buttons.length) % buttons.length];
    next.focus();
    selectCalculator(next.dataset.calculator);
  });

  elements.search.addEventListener("input", () => filterTabs(elements.search.value));
  document.getElementById("calc-reset").addEventListener("click", () => {
    state.values[state.active] = clone(definitions[state.active].defaults);
    renderActive({ focus: true });
  });
  document.getElementById("calc-example").addEventListener("click", () => {
    state.values[state.active] = clone(definitions[state.active].example);
    renderActive({ focus: true });
  });
  document.getElementById("calc-copy").addEventListener("click", () => {
    if (!state.lastResult) return;
    const output = state.lastResult;
    const copy = [definitions[state.active].title, `${output.hero.label}: ${output.hero.value}`, output.hero.detail, ...output.metrics.map((item) => `${item.label}: ${item.value}`)].join("\n");
    navigator.clipboard?.writeText(copy).then(() => {
      const toast = document.getElementById("app-toast");
      if (toast) { toast.textContent = "Calculation copied."; toast.classList.add("show"); window.setTimeout(() => toast.classList.remove("show"), 1800); }
    }).catch(() => {});
  });

  function setMethodPanel(open) {
    elements.methodPanel.hidden = !open;
    elements.methodToggle.setAttribute("aria-expanded", open ? "true" : "false");
  }
  elements.methodToggle.addEventListener("click", () => setMethodPanel(elements.methodPanel.hidden));
  document.getElementById("calc-method-close").addEventListener("click", () => setMethodPanel(false));

  document.addEventListener("keydown", (event) => {
    const editable = event.target.matches("input, textarea, select") || event.target.isContentEditable;
    if (event.key === "/" && !editable) {
      event.preventDefault();
      elements.search.focus();
    }
    if (event.key === "Escape" && !elements.methodPanel.hidden) setMethodPanel(false);
  });

  window.addEventListener("hashchange", () => {
    const key = location.hash.slice(1);
    if (definitions[key]) selectCalculator(key, { updateHash: false });
  });

  renderActive();
})();
