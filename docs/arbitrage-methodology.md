# IconLabs arbitrage methodology

IconLabs detects arbitrage from current executable prices; it does not estimate
the probability of an outcome and it does not reuse the Positive EV consensus
model. The implementation is independent and uses standard equal-payout
arbitrage mathematics.

## Market matching

An opportunity is eligible only when all legs refer to the same event, market
type, period, participant or player, and exact line. The scanner builds the
complete outcome signature quoted by each book and uses the dominant complete
signature. Incomplete books do not contribute a price. This prevents a
two-outcome calculation from silently ignoring a draw in a three-way market.

DFS pick'em platforms are excluded because a multi-pick entry is not an
independently executable single-outcome wager. Started events and quotes older
than the configured freshness threshold are also excluded.

## Odds and fees

American odds are converted to decimal odds:

- Positive odds: `decimal = 1 + american / 100`
- Negative odds: `decimal = 1 + 100 / abs(american)`

For exchanges, an optional commission buffer is applied to net winnings:

`effective decimal = 1 + (decimal - 1) × (1 - commission rate)`

The default buffer is zero because the feed does not currently provide a
user-specific fee tier. Users can set a conservative buffer in the tool.

## Qualification

For decimal odds `d₁ … dₙ`, the implied-probability sum is:

`S = Σ(1 / dᵢ)`

The market is an arbitrage only when `S < 1`. The theoretical return on the
total amount deployed is:

`return % = (1 / S - 1) × 100`

The calculation uses effective, fee-adjusted decimal odds when a buffer is
configured.

## Equal-payout stake sizing

For total stake `T`, the unrounded stake on outcome `i` is:

`stakeᵢ = T × (1 / dᵢ) / S`

This makes every theoretical payout equal to `T / S`. IconLabs converts the
stakes to cents, preserves the exact requested total stake, and assigns any
remaining cents to the leg with the lowest current payout. The displayed
guaranteed profit is the minimum rounded, after-fee payout minus the actual
total stake. If rounding removes the requested minimum return, the opportunity
is rejected.

## Execution caveats

The result is guaranteed only if every leg accepts the displayed stake at the
displayed odds. Line movement, rejected wagers, stake limits, account limits,
void rules, grading differences, currency conversion, and fees outside the
configured buffer can remove the edge. Users should verify the event, market,
line, rules, price, and accepted stake before submitting each wager.
