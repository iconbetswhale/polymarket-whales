# HomeRunHazard MLB Forensic Review

## Decision

Add `HomeRunHazard` (`0x5268527977f700f9bf9b6d5cd843859e4e70135d`) as a tightly filtered **MLB Supporting Sharp**.

He is useful as an independent pregame confirmation signal, but he is not suitable as a Lead Sharp or standalone recommendation originator. Raw fills, final positions assembled after first pitch, and gross wallet dollars must never be copied directly.

Production policy:

- Registry status: `SUPPORTING_ONLY`
- Consensus role: `NETTED_CONFIRMER`
- Measured MLB unit: `$9,750`
- Minimum supporting direction: `0.25u` or `$2,437.50`
- Supporting weight: `0.65`
- Lead eligible: `false`
- Standard originator eligible: `false`
- Exact fills must be aggregated.
- Related MLB markets must be netted at event level.
- Material hedges, two-sided events, and market-making/uncertain structures are ineligible.
- The signal must be present while the event is still pregame.

## Evidence

The four supplied exports contain 40,000 unique BUY executions, including 16,081 MLB rows. Their MLB fill coverage runs from May 31 through July 27, 2026. Complete provider closed-position history contains 17,534 MLB rows across 9,666 exact markets, 1,127 events, and 99 active days.

Provider-settled MLB results:

| Segment | Markets | Gross bought | Realized P&L | Gross-turnover ROI |
| --- | ---: | ---: | ---: | ---: |
| All MLB | 9,666 | $87,993,328 | $1,281,068 | 1.46% |
| Clean directional | 4,696 | $22,028,177 | $807,418 | 3.67% |
| Minor hedge | 1,046 | $9,064,393 | $514,810 | 5.68% |
| Material hedge | 1,886 | $22,104,187 | $45,940 | 0.21% |
| Two-sided | 2,038 | $34,796,572 | -$87,100 | -0.25% |

The separation is decisive: clean and minor-hedge positions were profitable, while two-sided volume lost money and material hedges added almost no return. Filtering is therefore part of the edge, not merely a safety preference.

By market type, gross-turnover ROI was 0.83% on moneylines, 1.74% on spreads, and 2.07% on totals. This does not justify copying every total or spread because related alternate lines frequently form one event portfolio.

## Behavior

HomeRunHazard is an automated, ultra-high-frequency event-portfolio trader:

- Median exact MLB markets per active export day: 89
- 90th percentile exact markets per day: 131.4
- Median exact markets per event: 7
- Both moneyline teams traded: 608 of 730 export events
- Opposing totals traded: 594 of 730 export events
- Total middle corridors detected: 492 events
- Median first moneyline entry: 15.9 minutes after scheduled start
- First moneyline entry after start: 84.84%
- Last moneyline fill after start: 98.73%

These figures rule out treating fill count, gross dollars, or final event direction as pregame conviction. They also explain why the wallet can be profitable without being directly copyable.

## Unit And Size

The provider-backed clean-position distribution supports a measured `$9,750` MLB unit with high confidence.

| Percentile | Clean net position |
| --- | ---: |
| 25th | $1,499 |
| Median | $4,306 |
| 75th | $8,582 |
| 90th | $16,386 |

The largest positions were not the best-performing group. Clean positions below 0.5u had the strongest measured ROI, while positions of 3u or more were slightly negative. The model must not equate a large raw position with high confidence.

## Pregame Copyability

At the two-hour pregame checkpoint, only 43 moneyline markets reached 0.15u in the BUY-only export. Thirty-eight were settled in the sample, and the direction visible then matched the wallet's final dominant direction 86.05% of the time. The reconstructed flat-stake ROI was 10.01%.

This is encouraging but not sufficient for Lead status:

- The sample is small.
- The export contains buys but not a complete sell ledger.
- Most of the wallet's total activity occurs after first pitch.
- Reconstructed checkpoint returns are not executable audited CLV.

The model therefore uses the more conservative 0.25u threshold and only accepts a signal while the market lifecycle is `upcoming`.

## Model Value

HomeRunHazard should improve coverage when a Directional Core wallet already has a valid play and HomeRunHazard independently reaches the same pregame net direction. He cannot create a play alone, replace a Core wallet, or turn two portfolio traders into a recommendation.

Historical final-direction overlap with existing MLB wallets was generally modest, with higher agreement with Ferrari than the rest of the group. Because most final directions include in-play information, those overlap results are dependency diagnostics only and are not used as proof of pregame predictive value.

The first 100 tracked model bets should report HomeRunHazard separately:

- opportunities seen before first pitch
- threshold-qualified confirmations
- agreement and contradiction with each Core wallet
- confirmation-time price and closing price
- CLV, once a reliable close is available
- incremental ROI and drawdown for plays added because of his confirmation
- rejected hedge and two-sided counts

## Data Limitations

The supplied execution exports are BUY-only. Provider closed positions supply settlement and realized P&L but not a complete timestamped sell history or trustworthy closing-price series. Exchange CLV, composite CLV, and true pre-move/post-move attribution are unavailable and must remain labeled `UNAVAILABLE_NOT_FABRICATED`.

Gross-turnover ROI is realized P&L divided by total purchased cost. It is not bankroll ROI and cannot be compared directly with the dashboard's model ROI.
