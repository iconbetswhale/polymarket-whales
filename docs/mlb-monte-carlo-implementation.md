# MLB Hybrid Monte Carlo Implementation

Analysis date: July 27, 2026

## What Was Built

This is the current-data version of the requested production simulation
architecture. It reuses the tracker wallet registry, exact-condition
aggregation, opposing-outcome netting, role eligibility, unit thresholds,
and `HYBRID_CONSENSUS_2` selection logic.

The engine adds:

- Chronological training, validation, and untouched July test partitions.
- Training-only development calibration and train-plus-validation final
  calibration.
- Historical replay with bankroll compounding.
- Calendar-day block bootstrap that preserves same-slate correlation.
- Configurable latency, slippage, fills, fees, price blocking, and stake caps.
- Fixed percentage, fixed dollar, quarter Kelly, half Kelly, and
  confidence-adjusted half Kelly sizing.
- Named execution, edge-decay, wallet-removal, and severe-loss stresses.
- Chunked NumPy simulation without retaining trade-level path records.
- VaR, CVaR, drawdown, loss thresholds, final-bankroll percentiles, and
  losing-day streak distributions.
- A frozen provider source snapshot and deterministic random seed.

## Run

Install the optional simulation dependencies:

```powershell
python -m pip install -e ".[simulation]"
```

Run from a fresh provider snapshot:

```powershell
python scripts/run_mlb_hybrid_monte_carlo.py `
  --config configs/mlb_hybrid_monte_carlo_100k.json
```

Repeat from the frozen source without provider requests:

```powershell
python scripts/run_mlb_hybrid_monte_carlo.py `
  --config configs/mlb_hybrid_monte_carlo_100k.json `
  --source-report outputs/mlb-hybrid-monte-carlo/source-replay.json
```

## Current Result

The frozen replay contains 111 current-rule hybrid signals:

- Training: 20
- Validation: 34
- Final July test: 57

The July test replay at modeled execution returned:

| Sizing | Test ROI | Max drawdown |
|---|---:|---:|
| Fixed $100 | 17.9% | 4.9% |
| Fixed 1% bankroll | 19.3% | 4.9% |
| Quarter Kelly | 20.7% | 4.5% |
| Half Kelly | 31.3% | 7.9% |
| Confidence-half-Kelly | 23.0% | 5.0% |

These are proxy returns using wallet average entry plus modeled execution.
They are not claims about prices that were actually available at alert time.

The baseline block bootstrap is strongly positive because it repeatedly
samples an unusually favorable 26-day July test segment. It must not be used
as the expected live return. The edge-decay regimes are more decision-useful:

| Confidence-half-Kelly regime | Median ROI | Profitable paths | P95 max DD |
|---|---:|---:|---:|
| Historical July bootstrap | 139.4% | 100.0% | 5.4% |
| Realized edge reduced 50% | -1.2% | 46.8% | 27.8% |
| Realized edge gone, model still bets | -6.6% | 32.3% | 30.9% |
| Realized edge reverses by 50% | -11.5% | 20.6% | 34.1% |

## Recommendation

Continue the dynamic confidence/Kelly sizing in the paper tracker so the
forward data captures what production would recommend. Do not interpret the
historical baseline as evidence for aggressive real-money half Kelly.

For actual capital before 100 forward-settled recommendations exist, fixed
dollar sizing is the safest tested choice. It had the lowest baseline P95
drawdown and does not increase stake after a favorable run.

The most important control is not another confidence filter. It is a
calibration kill switch: if rolling executable-price CLV or forward ROI shows
roughly half of the modeled edge has disappeared, Kelly sizing should
automatically fall back to fixed validation stakes or pause.

## Bias Status

Protections currently implemented:

- Signal outcomes are split chronologically.
- July is excluded from probability calibration.
- Opposing wallets and two-sided positions cannot become confirmations.
- Same-day signals remain grouped in bootstrap paths.
- Slippage-blocked and missed fills produce no execution.
- Stake cannot exceed configured trade, daily, or bankroll limits.
- Simulation is seeded, chunked, and path counts are asserted.

Remaining bias:

- Wallet roles and thresholds were selected after reviewing this history.
- Closed positions reveal eventual wallet exposure, not the position visible
  at the exact recommendation timestamp.
- The dataset does not include inactive or failed wallets that were never
  added to the registry.
- Historical rejected candidates are incomplete.

## Missing Data For A Reliable Production Backtest

- Exact signal-created timestamp and every later recommendation revision.
- Scheduled event time as known at each historical evaluation.
- Executable order books from Polymarket, Kalshi, NoVIG, ProphetX, and 4Cx at
  signal time and after each latency interval.
- Provider-specific fees, limits, minimums, and rejected order responses.
- Historical liquidity and depth at the requested stake.
- Closing prices and provider-specific CLV.
- All candidates that failed filters, including exact rejection reasons.
- Wallet eligibility and category statistics as they existed on each date.
- Wallet inactivity, removed-wallet, and failed-wallet history.

Until those fields accumulate in the forward tracker, this engine is
appropriate for strategy comparison and risk sensitivity, not for claiming
a precise expected live ROI.
