"use strict";

const assert = require("node:assert/strict");
const math = require("../static/calculator-math.js");

function close(actual, expected, tolerance = 1e-8) {
  assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} is not within ${tolerance} of ${expected}`);
}

close(math.americanToDecimal(110), 2.1);
close(math.americanToDecimal(-200), 1.5);
close(math.decimalToAmerican(8), 700);
assert.equal(math.decimalProfitToFraction(0.5), "1/2");

const arb = math.arbitrage({ stake: 100, odds: [110, 110] });
assert.equal(arb.isArbitrage, true);
assert.deepEqual(arb.stakes, [50, 50]);
close(arb.guaranteedProfit, 5);
close(arb.roi, 0.05);

const ev = math.expectedValue({ stake: 100, odds: 110, winProbability: 0.6 });
close(ev.expectedProfit, 26);
close(ev.roi, 0.26);

const bonus = math.bonusBet({ amount: 100, bonusOdds: 300, hedgeOdds: -275 });
close(bonus.hedgeStake, 220);
close(bonus.lockedProfit, 80);
close(bonus.conversionRate, 0.8);

const halfPoint = math.halfPoint({ market: "total", league: "MLB", line: 8, odds: -110, direction: "buy" });
close(halfPoint.pushMass, 0.095);
assert.ok(halfPoint.adjustedWin > halfPoint.conditionalWin);

const hold = math.hold({ odds: [-110, -110] });
close(hold.hold, 0.04761904761904767);
close(hold.fairProbabilities[0], 0.5);

const implied = math.implied({ stake: 100, odds: 110 });
close(implied.probability, 1 / 2.1);
close(implied.profit, 110);
close(implied.payout, 210);

const kelly = math.kelly({ bankroll: 12000, odds: 110, winProbability: 0.6, multiplier: 0.25 });
close(kelly.fullKelly, 0.23636363636363633);
close(kelly.recommendedStake, 709.090909090909);

const noVig = math.noVig({ odds: [-180, 155] });
close(noVig.fairProbabilities.reduce((sum, value) => sum + value, 0), 1);

const parlay = math.parlay({ stake: 100, odds: [100, 100, 100] });
close(parlay.combinedDecimal, 8);
close(parlay.combinedAmerican, 700);
close(parlay.payout, 800);

const prediction = math.predictionMarket({ price: 65, stake: 100 });
close(prediction.probability, 0.65);
close(prediction.decimal, 1 / 0.65);
close(prediction.grossPayout, 100 / 0.65);

const spread = math.pointSpread({ league: "NFL", spread: -5, marketHold: 1 / 21 });
assert.ok(spread.favoriteMoneyline < -225 && spread.favoriteMoneyline > -245);
close(spread.favoriteProbability + spread.underdogProbability, 1);

const poisson = math.poisson({ average: 2.7, proposition: 4 });
close(poisson.atLeast, 0.2859078243837889);
close(poisson.exactly, 0.14881568706635565);
assert.equal(math.poisson({ average: 0.01, proposition: 170 }).exactlyOdds, Number.POSITIVE_INFINITY);

assert.equal(math.choose(8, 2), 28);
const roundRobin = math.roundRobin({ stakePerBet: 5, odds: [110, 110, 110, 110, 110], parlaySize: 2, results: [true, true, false, true, false] });
assert.equal(roundRobin.combinations, 10);
assert.equal(roundRobin.winningTickets, 3);
close(roundRobin.totalRisk, 50);

const vig = math.vig({ odds: [-110, -110] });
close(vig.overround, 0.04761904761904767);
close(vig.vig, 0.0454545454545455);

assert.throws(() => math.americanToDecimal(0), /American odds/);
assert.throws(() => math.poisson({ average: -1, proposition: 2 }), /greater than zero/);

console.log("calculator math tests passed");
