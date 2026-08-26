(function calculatorMathFactory(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.IconLabsCalculatorMath = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildCalculatorMath() {
  "use strict";

  const EPSILON = 1e-12;
  const DEFAULT_BOOK_HOLD = 1 / 21;

  function finite(value, label = "Value") {
    const number = Number(value);
    if (!Number.isFinite(number)) throw new Error(`${label} must be a number.`);
    return number;
  }

  function positive(value, label = "Value") {
    const number = finite(value, label);
    if (number <= 0) throw new Error(`${label} must be greater than zero.`);
    return number;
  }

  function probability(value, label = "Probability") {
    const number = finite(value, label);
    if (number <= 0 || number >= 1) throw new Error(`${label} must be between 0% and 100%.`);
    return number;
  }

  function validateAmerican(value) {
    const odds = finite(value, "American odds");
    if (Math.abs(odds) < 100) throw new Error("American odds must be +100 or higher, or -100 or lower.");
    return odds;
  }

  function americanToDecimal(value) {
    const odds = validateAmerican(value);
    return odds > 0 ? 1 + odds / 100 : 1 + 100 / Math.abs(odds);
  }

  function decimalToAmerican(value) {
    const decimal = finite(value, "Decimal odds");
    if (decimal <= 1) throw new Error("Decimal odds must be greater than 1.00.");
    return decimal >= 2 ? (decimal - 1) * 100 : -100 / (decimal - 1);
  }

  function impliedProbability(value) {
    return 1 / americanToDecimal(value);
  }

  function probabilityToAmerican(value) {
    return decimalToAmerican(1 / probability(value));
  }

  function gcd(left, right) {
    let a = Math.abs(Math.round(left));
    let b = Math.abs(Math.round(right));
    while (b) [a, b] = [b, a % b];
    return a || 1;
  }

  function decimalProfitToFraction(value, maxDenominator = 100) {
    const target = positive(value, "Fractional return");
    let numerator = Math.round(target);
    let denominator = 1;
    let error = Math.abs(target - numerator);
    for (let candidate = 1; candidate <= maxDenominator; candidate += 1) {
      const nextNumerator = Math.round(target * candidate);
      const nextError = Math.abs(target - nextNumerator / candidate);
      if (nextError < error - EPSILON) {
        numerator = nextNumerator;
        denominator = candidate;
        error = nextError;
      }
    }
    const divisor = gcd(numerator, denominator);
    return `${numerator / divisor}/${denominator / divisor}`;
  }

  function oddsFormatsFromAmerican(value) {
    const american = validateAmerican(value);
    const decimal = americanToDecimal(american);
    const implied = 1 / decimal;
    return {
      american,
      decimal,
      fractional: decimalProfitToFraction(decimal - 1),
      probability: implied,
    };
  }

  function allocateEqualPayout(totalStake, decimalOdds) {
    const total = positive(totalStake, "Total stake");
    if (!Array.isArray(decimalOdds) || decimalOdds.length < 2) throw new Error("Enter at least two outcomes.");
    const decimals = decimalOdds.map((value) => {
      const decimal = finite(value, "Decimal odds");
      if (decimal <= 1) throw new Error("Every outcome needs valid odds.");
      return decimal;
    });
    const inverse = decimals.map((decimal) => 1 / decimal);
    const inverseSum = inverse.reduce((sum, value) => sum + value, 0);
    const totalCents = Math.round(total * 100);
    const stakeCents = inverse.map((value) => Math.floor((totalCents * value) / inverseSum));
    let remaining = totalCents - stakeCents.reduce((sum, value) => sum + value, 0);
    while (remaining > 0) {
      let lowestPayoutIndex = 0;
      let lowestPayout = Number.POSITIVE_INFINITY;
      stakeCents.forEach((cents, index) => {
        const payout = (cents / 100) * decimals[index];
        if (payout < lowestPayout) {
          lowestPayout = payout;
          lowestPayoutIndex = index;
        }
      });
      stakeCents[lowestPayoutIndex] += 1;
      remaining -= 1;
    }
    return stakeCents.map((cents) => cents / 100);
  }

  function arbitrage({ stake, odds }) {
    const totalStake = positive(stake, "Total stake");
    const americanOdds = (odds || []).map(validateAmerican);
    if (americanOdds.length < 2) throw new Error("Enter at least two outcomes.");
    const decimalOdds = americanOdds.map(americanToDecimal);
    const rawProbabilities = decimalOdds.map((decimal) => 1 / decimal);
    const inverseSum = rawProbabilities.reduce((sum, value) => sum + value, 0);
    const stakes = allocateEqualPayout(totalStake, decimalOdds);
    const payouts = stakes.map((value, index) => value * decimalOdds[index]);
    const minimumPayout = Math.min(...payouts);
    const guaranteedProfit = minimumPayout - totalStake;
    return {
      isArbitrage: inverseSum < 1 - EPSILON,
      americanOdds,
      decimalOdds,
      impliedTotal: inverseSum,
      stakes,
      payouts,
      minimumPayout,
      guaranteedProfit,
      roi: guaranteedProfit / totalStake,
      theoreticalRoi: 1 / inverseSum - 1,
    };
  }

  function expectedValue({ stake, odds, winProbability }) {
    const wager = positive(stake, "Stake");
    const decimal = americanToDecimal(odds);
    const win = probability(winProbability, "Win probability");
    const profitIfWin = wager * (decimal - 1);
    const expectedProfit = win * profitIfWin - (1 - win) * wager;
    return {
      decimal,
      winProbability: win,
      profitIfWin,
      expectedProfit,
      expectedReturn: wager + expectedProfit,
      roi: expectedProfit / wager,
      fairAmerican: probabilityToAmerican(win),
      edge: win - 1 / decimal,
    };
  }

  function bonusBet({ amount, bonusOdds, hedgeOdds }) {
    const freeAmount = positive(amount, "Bonus bet amount");
    const bonusDecimal = americanToDecimal(bonusOdds);
    const hedgeDecimal = americanToDecimal(hedgeOdds);
    const freeBetProfit = freeAmount * (bonusDecimal - 1);
    const hedgeStake = freeBetProfit / hedgeDecimal;
    const lockedProfit = hedgeStake * (hedgeDecimal - 1);
    return {
      bonusDecimal,
      hedgeDecimal,
      freeBetProfit,
      hedgeStake,
      lockedProfit,
      conversionRate: lockedProfit / freeAmount,
      bonusWinsNet: freeBetProfit - hedgeStake,
      hedgeWinsNet: lockedProfit,
    };
  }

  const HALF_POINT_MASS = Object.freeze({
    spread: {
      NFL: { default: 0.025, 1: 0.038, 2: 0.034, 3: 0.091, 4: 0.044, 6: 0.033, 7: 0.061, 10: 0.032, 14: 0.022 },
      NCAAF: { default: 0.021, 3: 0.066, 7: 0.043, 10: 0.025, 14: 0.019 },
      NBA: { default: 0.028 },
      WNBA: { default: 0.031 },
      NCAAB: { default: 0.034 },
    },
    total: {
      NFL: { default: 0.020 },
      NCAAF: { default: 0.015 },
      NBA: { default: 0.009 },
      WNBA: { default: 0.012 },
      NCAAB: { default: 0.015 },
      MLB: { default: 0.095 },
      NHL: { default: 0.110 },
    },
  });

  function halfPointMass(market, league, line) {
    const marketTable = HALF_POINT_MASS[market] || HALF_POINT_MASS.spread;
    const leagueTable = marketTable[league] || marketTable.NFL;
    const key = Math.abs(Math.round(finite(line, "Reference line")));
    return leagueTable[key] || leagueTable.default;
  }

  function halfPoint({ market = "spread", league = "NFL", line = 3, odds, direction = "buy" }) {
    const decimal = americanToDecimal(odds);
    const conditionalWin = 1 / decimal;
    const pushMass = halfPointMass(market, league, line);
    const favorable = direction === "buy";
    const adjustedWin = favorable
      ? (1 - pushMass) * conditionalWin + pushMass
      : (1 - pushMass) * conditionalWin;
    return {
      conditionalWin,
      pushMass,
      adjustedWin,
      fairAmerican: probabilityToAmerican(adjustedWin),
      fairDecimal: 1 / adjustedWin,
      direction: favorable ? "buy" : "sell",
    };
  }

  function hold({ odds }) {
    const probabilities = (odds || []).map(impliedProbability);
    if (probabilities.length < 2) throw new Error("Enter at least two sides.");
    const impliedTotal = probabilities.reduce((sum, value) => sum + value, 0);
    const fairProbabilities = probabilities.map((value) => value / impliedTotal);
    return {
      probabilities,
      impliedTotal,
      hold: impliedTotal - 1,
      fairProbabilities,
      fairOdds: fairProbabilities.map(probabilityToAmerican),
    };
  }

  function implied({ stake, odds }) {
    const wager = positive(stake, "Bet amount");
    const formats = oddsFormatsFromAmerican(odds);
    return {
      ...formats,
      profit: wager * (formats.decimal - 1),
      payout: wager * formats.decimal,
    };
  }

  function kelly({ bankroll, odds, winProbability, multiplier = 1 }) {
    const capital = positive(bankroll, "Bankroll");
    const decimal = americanToDecimal(odds);
    const win = probability(winProbability, "Win probability");
    const factor = finite(multiplier, "Kelly multiplier");
    if (factor < 0 || factor > 1) throw new Error("Kelly multiplier must be between 0 and 1.");
    const netOdds = decimal - 1;
    const fullKelly = (netOdds * win - (1 - win)) / netOdds;
    const recommendedFraction = Math.max(0, fullKelly * factor);
    const ev = win * netOdds - (1 - win);
    return {
      fullKelly,
      recommendedFraction,
      recommendedStake: capital * recommendedFraction,
      ev,
      edge: win - 1 / decimal,
    };
  }

  function noVig({ odds }) {
    const rawProbabilities = (odds || []).map(impliedProbability);
    if (rawProbabilities.length < 2) throw new Error("Enter at least two outcomes.");
    const impliedTotal = rawProbabilities.reduce((sum, value) => sum + value, 0);
    const fairProbabilities = rawProbabilities.map((value) => value / impliedTotal);
    return {
      rawProbabilities,
      impliedTotal,
      overround: impliedTotal - 1,
      fairProbabilities,
      fairOdds: fairProbabilities.map(probabilityToAmerican),
    };
  }

  function oddsConverter({ stake, american }) {
    return implied({ stake, odds: american });
  }

  function parlay({ stake, odds }) {
    const wager = positive(stake, "Stake");
    const americanOdds = (odds || []).map(validateAmerican);
    if (americanOdds.length < 2) throw new Error("Enter at least two parlay legs.");
    const decimalOdds = americanOdds.map(americanToDecimal);
    const combinedDecimal = decimalOdds.reduce((product, value) => product * value, 1);
    const payout = wager * combinedDecimal;
    return {
      decimalOdds,
      combinedDecimal,
      combinedAmerican: decimalToAmerican(combinedDecimal),
      impliedProbability: 1 / combinedDecimal,
      payout,
      profit: payout - wager,
    };
  }

  function predictionMarket({ price, stake = 100 }) {
    const cents = finite(price, "Market price");
    if (cents <= 0 || cents >= 100) throw new Error("Market price must be between 0 and 100 cents.");
    const probabilityValue = cents / 100;
    const decimal = 1 / probabilityValue;
    const contracts = positive(stake, "Order amount") / probabilityValue;
    return {
      price: cents,
      probability: probabilityValue,
      decimal,
      american: decimalToAmerican(decimal),
      fractional: decimalProfitToFraction(decimal - 1),
      contracts,
      grossPayout: contracts,
      profit: contracts - positive(stake, "Order amount"),
    };
  }

  const SPREAD_SCALES = Object.freeze({ NFL: 6.65, NCAAF: 8.15, NBA: 8.25, WNBA: 7.8 });

  function pointSpread({ league = "NFL", spread, marketHold = DEFAULT_BOOK_HOLD }) {
    const line = finite(spread, "Point spread");
    const scale = SPREAD_SCALES[league] || SPREAD_SCALES.NFL;
    const holdValue = finite(marketHold, "Market hold");
    if (holdValue < 0 || holdValue >= 0.25) throw new Error("Market hold must be between 0% and 25%.");
    const favoriteProbability = 1 / (1 + Math.exp(-Math.abs(line) / scale));
    const underdogProbability = 1 - favoriteProbability;
    const favoriteQuotedProbability = Math.min(0.999, favoriteProbability + holdValue / 2);
    const underdogQuotedProbability = Math.min(0.999, underdogProbability + holdValue / 2);
    return {
      favoriteProbability,
      underdogProbability,
      favoriteMoneyline: probabilityToAmerican(favoriteQuotedProbability),
      underdogMoneyline: probabilityToAmerican(underdogQuotedProbability),
      marketHold: holdValue,
      scale,
    };
  }

  function poissonTerm(lambda, k) {
    let term = Math.exp(-lambda);
    for (let index = 1; index <= k; index += 1) term *= lambda / index;
    return term;
  }

  function probabilityBoundaryToAmerican(value) {
    if (value <= 0) return Number.POSITIVE_INFINITY;
    if (value >= 1) return Number.NEGATIVE_INFINITY;
    return probabilityToAmerican(value);
  }

  function poisson({ average, proposition }) {
    const lambda = positive(average, "Expected average");
    const k = Math.floor(finite(proposition, "Proposition"));
    if (k < 0 || k > 170) throw new Error("Proposition must be a whole number from 0 to 170.");
    const exactly = poissonTerm(lambda, k);
    let atMost = 0;
    let term = Math.exp(-lambda);
    for (let index = 0; index <= k; index += 1) {
      if (index > 0) term *= lambda / index;
      atMost += term;
    }
    atMost = Math.min(1, atMost);
    const atLeast = k === 0 ? 1 : Math.max(0, 1 - (atMost - exactly));
    return {
      exactly,
      atLeast,
      atMost,
      exactlyOdds: probabilityBoundaryToAmerican(exactly),
      atLeastOdds: probabilityBoundaryToAmerican(atLeast),
      atMostOdds: probabilityBoundaryToAmerican(atMost),
    };
  }

  function choose(n, k) {
    if (!Number.isInteger(n) || !Number.isInteger(k) || n < 0 || k < 0 || k > n) return 0;
    const smaller = Math.min(k, n - k);
    let result = 1;
    for (let index = 1; index <= smaller; index += 1) result = (result * (n - smaller + index)) / index;
    return Math.round(result);
  }

  function combinations(items, size) {
    const results = [];
    function walk(start, selected) {
      if (selected.length === size) {
        results.push(selected.slice());
        return;
      }
      for (let index = start; index <= items.length - (size - selected.length); index += 1) {
        selected.push(items[index]);
        walk(index + 1, selected);
        selected.pop();
      }
    }
    walk(0, []);
    return results;
  }

  function roundRobin({ stakePerBet, odds, parlaySize, results }) {
    const stake = positive(stakePerBet, "Stake per parlay");
    const americanOdds = (odds || []).map(validateAmerican);
    const size = Math.floor(finite(parlaySize, "Parlay size"));
    if (americanOdds.length < 3) throw new Error("A round robin needs at least three legs.");
    if (size < 2 || size >= americanOdds.length) throw new Error("Parlay size must be at least 2 and smaller than the number of legs.");
    const legs = americanOdds.map((oddsValue, index) => ({
      index,
      decimal: americanToDecimal(oddsValue),
      won: !results || results[index] !== false,
    }));
    const tickets = combinations(legs, size);
    const maxPayout = tickets.reduce((sum, ticket) => sum + stake * ticket.reduce((product, leg) => product * leg.decimal, 1), 0);
    const simulatedPayout = tickets.reduce((sum, ticket) => {
      if (!ticket.every((leg) => leg.won)) return sum;
      return sum + stake * ticket.reduce((product, leg) => product * leg.decimal, 1);
    }, 0);
    const totalRisk = stake * tickets.length;
    return {
      combinations: tickets.length,
      expectedCombinations: choose(americanOdds.length, size),
      totalRisk,
      maxPayout,
      maxProfit: maxPayout - totalRisk,
      simulatedPayout,
      simulatedProfit: simulatedPayout - totalRisk,
      winningTickets: tickets.filter((ticket) => ticket.every((leg) => leg.won)).length,
    };
  }

  function vig({ odds }) {
    const probabilities = (odds || []).map(impliedProbability);
    if (probabilities.length < 2) throw new Error("Enter at least two sides.");
    const impliedTotal = probabilities.reduce((sum, value) => sum + value, 0);
    const overround = impliedTotal - 1;
    return {
      probabilities,
      impliedTotal,
      overround,
      vig: overround / impliedTotal,
      fairProbabilities: probabilities.map((value) => value / impliedTotal),
    };
  }

  return Object.freeze({
    americanToDecimal,
    decimalToAmerican,
    impliedProbability,
    probabilityToAmerican,
    decimalProfitToFraction,
    oddsFormatsFromAmerican,
    allocateEqualPayout,
    arbitrage,
    expectedValue,
    bonusBet,
    halfPoint,
    hold,
    implied,
    kelly,
    noVig,
    oddsConverter,
    parlay,
    predictionMarket,
    pointSpread,
    poisson,
    choose,
    roundRobin,
    vig,
    constants: Object.freeze({ HALF_POINT_MASS, SPREAD_SCALES, DEFAULT_BOOK_HOLD }),
  });
});
