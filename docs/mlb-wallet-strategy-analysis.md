# MLB Wallet Portfolio Strategy

Analysis date: July 27, 2026

## Recommendation

Do not remove the automated/event-portfolio wallets, and do not let every
wallet vote equally.

Use a hybrid two-wallet consensus:

1. At least two eligible wallets must agree on the same standard MLB
   moneyline.
2. At least one agreeing wallet must be from the low-conflict directional
   core: Wordylittleneck, phonesculptor, or Soarin22.
3. The second agreeing wallet may be another core wallet or a netted
   event-portfolio confirmer: 0x4f2, sportmaster777, or
   ferrariChampions2026.
4. Every wallet must independently clear its measured unit threshold.
5. Aggregate BUY and SELL fills before measuring the position.
6. Materially hedged, two-sided, or unclear event portfolios do not vote.
7. An automated wallet's raw fills never create multiple votes.
8. A meaningful opposing core signal blocks the recommendation.

This structure produced the best combination of estimated edge, drawdown,
and usable play volume in the strategy screen.

## June-Forward Comparison

The comparison covers standard MLB moneylines dated June 1 through July 26,
2026. ROI uses the median agreeing wallet's average entry as a proxy because
historical two-hours-before-first-pitch prices are not available.

| Strategy | Bets | Bets/day | Sized ROI | Profit | Max drawdown | ROI after +5 price points |
|---|---:|---:|---:|---:|---:|---:|
| Hybrid consensus 2 | 139 | 2.57 | 44.52% | +61.08u | 2.52u | 32.13% |
| Broad consensus 2 | 302 | 5.59 | 37.75% | +111.51u | 3.63u | 25.64% |
| Hybrid, one core allowed | 263 | 4.87 | 31.42% | +51.34u | 3.25u | 19.43% |
| Broad, one wallet allowed | 489 | 9.06 | 25.93% | +125.11u | 8.62u | 12.92% |
| Strict two-core consensus | 62 | 1.15 | 11.29% | +5.25u | 4.01u | 1.66% |
| Precision core, one allowed | 400 | 7.41 | 3.15% | +9.93u | 9.21u | -6.12% |

The absolute ROI values are optimistic and must not be treated as expected
live returns. The relative ordering is the useful result. Hybrid consensus 2
remained first after two-point and five-point price deterioration.

## Why Precision-Only Lost

Low hedge frequency did not automatically mean strong entry value.
Wordylittleneck and phonesculptor were operationally clean, but their
threshold-qualified moneyline subsets returned only about 2.9% each at the
wallet average-entry proxy. Soarin22 was much stronger but had a smaller
sample.

The event-portfolio wallets were noisy at the raw-position level but very
strong after opposing exposure was removed. Excluding them discarded useful
confirmation. Letting them originate freely, however, increased volume and
drawdown.

The profitable information is therefore not "automated wallet equals bad."
It is the dominant clean direction that remains after the automated wallet's
event inventory is netted.

## Wallet Roles

### Directional Core

- Wordylittleneck: core originator; require 0.5u and clean direction.
- phonesculptor: core originator; require 0.5u and clean direction.
- Soarin22: core originator; require 0.5u and clean direction.

### Netted Confirmers

- 0x4f2: confirmer only because 73.1% of sampled moneyline markets were
  materially hedged or two-sided before filtering.
- ferrariChampions2026: confirmer only because 56.3% were materially hedged
  or two-sided before filtering.
- sportmaster777: confirmer only because 29.2% were materially hedged or
  two-sided before filtering.

### Research

- 1winstreak1: keep in research/confirmation until execution-level behavior
  is reviewed. Its final-position sample showed a 52.2% material/two-sided
  rate.
- Weflyhigh: remain research-only for MLB because no measured MLB unit is
  available.

## Sizing And Risk

Agreement should raise size gradually, not create an "absolute 100" bet.
No historical agreement pattern eliminates variance.

For the initial forward test:

- Start at 0.25u for a two-wallet hybrid consensus.
- Increase toward 0.50u when both wallets are core originators.
- Increase toward 0.75u when two core wallets and one netted confirmer agree.
- Cap any single recommendation at 0.75u during validation.
- Cap total exposure to one MLB event at 1.0u.
- Do not use estimated Kelly sizing until recommendation-time fair prices and
  executable prices are stored.

Fractional Kelly can still suffer meaningful drawdowns when probability
estimates are wrong. A fixed conservative unit schedule is safer during the
forward-validation period.

## Required Forward Test

Run the broad-consensus and hybrid-consensus strategies in parallel shadow
trackers for at least 30 days or 100 settled hybrid recommendations,
whichever is longer.

Store for every candidate:

- Exact candidate timestamp
- Scheduled game time
- Every wallet's net position at that timestamp
- Supporting and opposing wallets
- Polymarket executable price
- Best executable exchange price
- Composite fair price
- Recommended size before rounding
- Closing price
- Result and realized P&L

The production decision should use forward ROI, CLV, maximum drawdown,
bet frequency, and price decay from alert to execution. Do not promote the
backtest ROI to an expected-return assumption.

## Method Limitations

- Closed positions show eventual exposure, not necessarily exposure visible
  two hours before first pitch.
- Wallet average entry can be materially better than the price available when
  IconLabs alerts.
- Current thresholds and wallet roles were informed by historical results, so
  the test is not a pristine untouched out-of-sample experiment.
- The bootstrap resamples observed days. It measures historical path
  variability, not regime change, model error, or provider failure.
- This screen covers standard MLB moneylines only. Spreads, totals, and
  alternate lines require separate simulations.

The research literature also warns that strategy selection from many
backtests can overfit, and that Kelly-style growth optimization can create
substantial drawdown. Those risks are why the recommended next step is a
shadow forward test rather than immediate aggressive staking.

Supporting analysis:

- `docs/mlb-wallet-strategy-simulation.json`
- `scripts/simulate_mlb_wallet_portfolios.py`
