# MLB Strategy A/B Test: 2,000-Bet Outlook

## Decision

Do not replace the current hybrid with unrestricted lead-originator tailing.
The lead-only strategy creates the most volume, but its measured edge is too
thin to survive ordinary price deterioration.

The best next forward test is the **Balanced One Lead** strategy:

- One qualifying precision lead may originate a play.
- A disagreement between precision leads still cancels the play.
- Supporting wallets do not need to confirm the play.
- Strong net opposing portfolio action may still reject the play.
- Agreement increases confidence and sizing; it is not required for entry.

This is a shadow-test recommendation, not a recommendation to overwrite the
current production strategy before forward results exist.

## Historical Comparison

Evaluation window: July 1 through July 26, 2026. Standard MLB moneylines only.

| Strategy | Bets | Bets/day | Win rate | Flat ROI | Sized ROI | Days to 2,000 |
|---|---:|---:|---:|---:|---:|---:|
| Current Hybrid | 57 | 2.19 | 75.4% | 33.6% | 36.4% | 912 |
| Balanced One Lead | 125 | 4.81 | 61.6% | 19.2% | 25.5% | 416 |
| Lead Originators Only | 176 | 6.77 | 54.0% | 4.6% | 4.8% | 296 |

The historical rates are upper-bound screening estimates. They are not the
number of Discord alerts that production will necessarily send because the
closed-position export cannot reconstruct the exact two-hour state, available
price, or candidate rejection ledger.

## 2,000-Bet Simulation

Each result uses 20,000 paths, a $10,000 starting bankroll, 1 unit equal to 1%
of current bankroll, a 2% maximum risk per bet, and random execution
deterioration with a 0.9-point median. Calibration uses only plays through June
30; July supplies the price and sizing distribution.

The 50% edge-retention case is the primary planning scenario because the wallet
cohorts were selected using historical results. It assumes half of the
pre-July calibrated edge survives selection bias, execution delay, and future
market adaptation.

| Strategy | Median final | Mean final | Profitable paths | 5th percentile | P95 max drawdown |
|---|---:|---:|---:|---:|---:|
| Current Hybrid | $9,817 | $10,637 | 48.0% | $5,119 | 59.0% |
| Balanced One Lead | $10,583 | $11,012 | 57.8% | $6,618 | 44.3% |
| Lead Originators Only | $8,869 | $9,494 | 37.4% | $4,850 | 59.2% |

If 100% of the calibrated edge survives, median final bankrolls are $15,175,
$15,121, and $11,784 respectively. If only 25% survives, all three median
paths lose money after modeled execution costs. This sensitivity is the most
important result: line shopping and forward CLV measurement matter more than
the attractive historical ROI.

## Interpretation

The current hybrid has the highest edge per accepted bet, but it concentrates
risk into fewer observations and may leave long periods with no actionable
play. Lead-only solves the volume problem by accepting many marginal signals,
but those signals have only about 2.4 calibrated probability points of
pre-execution edge and are vulnerable to a one- or two-point worse fill.

Balanced One Lead provides the strongest tradeoff in this dataset. It more
than doubles expected play volume versus the current hybrid while retaining a
meaningful conflict filter. Its recommended average historical size was also
smaller, about 0.61u versus 0.95u for current hybrid, which lowers bankroll
volatility.

## Required Forward Test

Track the current hybrid and Balanced One Lead simultaneously from the clean
reset. Do not count the same event twice within a model. For each candidate,
store the two-hour snapshot, 30-minute snapshot, executed book and price,
composite close, same-book close, wallet additions and reversals, rejection
reason, and final result.

Review at 100 settled bets per model, with an earlier safety review after 30.
Promote Balanced One Lead only if it improves alert volume while keeping
positive net CLV, positive realized ROI after execution, and no materially
worse drawdown than current hybrid.

## Limitations

- Closed positions show final wallet exposures, not exact exposure at alert time.
- Historical wallet selection creates survivorship and look-ahead bias.
- The July evaluation contains only 57 current-hybrid bets.
- The simulation resamples a short MLB period to reach 2,000 bets.
- MLB findings must not be transferred directly to NFL, NBA, or tennis.
- No historical exchange order-book depth was available.

Reproducible inputs and output:

- `outputs/mlb-hybrid-monte-carlo/source-replay.json`
- `scripts/simulate_strategy_ab_2000.py`
- `outputs/strategy-ab-2000.json`
