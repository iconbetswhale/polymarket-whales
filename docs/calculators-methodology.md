# IconLabs calculator methodology

The Calculators page is an independent implementation of standard betting mathematics. It does not copy third-party source code, text, hidden constants, or proprietary historical datasets.

## Deterministic calculators

- **American odds conversion:** positive odds convert to `1 + odds / 100`; negative odds convert to `1 + 100 / abs(odds)`.
- **Implied probability:** `1 / decimal odds`.
- **Arbitrage:** an opportunity exists when `sum(1 / decimal odds) < 1`. Stake is allocated in proportion to inverse decimal odds, then balanced to whole cents against the lowest payout.
- **Expected value:** `p(win) * win profit - p(loss) * stake`.
- **Bonus bet conversion:** the promotional stake is assumed not to be returned. The cash hedge is `bonus profit / hedge decimal odds`.
- **Hold:** raw overround, `sum(implied probabilities) - 1`.
- **Vig:** theoretical balanced-handle commission, `overround / sum(implied probabilities)`.
- **No-vig:** proportional normalization, `raw probability / sum(raw probabilities)`.
- **Kelly:** `((b * p) - q) / b`, multiplied by the selected fractional-Kelly setting and floored at zero.
- **Parlay:** the decimal prices of all legs are multiplied.
- **Prediction market:** a price in cents maps directly to probability before fees and spread.
- **Poisson:** `P(X = k) = exp(-lambda) * lambda^k / k!` with cumulative sums for at-most and at-least outcomes.
- **Round robin:** every `k`-leg combination is enumerated. Ticket count is `n choose k`, and the entered stake applies to each ticket.

## Calibrated calculators

### Half point

The half-point tool estimates the probability mass on the crossed whole number. IconLabs keeps league and key-number push-rate assumptions in `static/calculator-math.js`. A favorable move turns that push mass into wins; an unfavorable move turns it into losses.

These calibration values are transparent comparison baselines. They are not a copy of another vendor's proprietary database and should be reviewed periodically as league scoring environments change.

### Point spread to moneyline

The spread converter uses a league-specific logistic curve:

`favorite probability = 1 / (1 + exp(-abs(spread) / league scale))`

The selected target hold is divided across the two outcomes to produce quoted moneyline equivalents. League scale constants live in `static/calculator-math.js`.

The result is a historical baseline, not a live price. Injuries, totals, venue, home field, and matchup-specific distribution shape can all move the actual moneyline.

## Product safeguards

- Invalid American odds between -99 and +99 are rejected.
- Probabilities must be strictly between 0% and 100%.
- Arbitrage results disclose that every leg must fill at the displayed stake and price.
- Poisson results state the distribution assumption.
- Parlays state that correlation adjustments are not included.
- Prediction-market results state that fees, bid-ask spread, slippage, and resolution risk are excluded.
