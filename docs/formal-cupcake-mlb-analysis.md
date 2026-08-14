# Formal-Cupcake MLB Moneyline Review

## Decision

Use `Formal-Cupcake` (`0xb8c842bc049bf208f73354c7b037b811d741d8a4`) as a conditional MLB Lead during the model's paper-testing phase.

A clean pregame position of at least one measured unit may provide the Directional Core for a candidate. It cannot create a model recommendation alone: at least one independent eligible Lead or Supporting Sharp must agree. This lets the forward tracker measure Formal-Cupcake's incremental value without treating the historical sample as conclusive proof.

## Why The Displayed ROI Was Misleading

Polymarket's closed-position endpoint returned 76 profitable MLB positions and no losses. Taken alone, that produced a false 100% positive rate and an apparent 55.25% return.

The missing 79 resolved losing positions remained in the current-position endpoint at a zero price. Combining both endpoints produces the actual settled record:

| Metric | Corrected result |
| --- | ---: |
| Settled MLB moneylines | 155 |
| Wins | 76 |
| Losses | 79 |
| Win rate | 49.03% |
| Amount risked | $195,103 |
| Realized P&L | +$25,805 |
| ROI | +13.23% |

The closed endpoint also reports `totalBought` as shares, not position cost. Cost was reconstructed using average entry price for winners and `initialValue` for losing positions.

## Trading Behavior

The supplied export contains 580 executions across all sports and 164 MLB executions covering 158 exact moneyline markets.

- All 158 MLB markets were clean directional.
- No opposing moneyline positions were found.
- No material hedges or two-sided MLB structures were found.
- Median activity was two MLB markets per active day.
- The 90th percentile was three markets per day.
- Median fills per exact market was one.
- Median entry was approximately 524.5 minutes before first pitch.
- Approximately 98.1% of positions were visible more than two hours before the game.

Structurally, this is one of the most copyable wallets reviewed. The bettor appears to use an almost fixed `$1,300` risk amount rather than scaling conviction materially.

## Corrected Performance

| Month | Bets | Win rate | ROI |
| --- | ---: | ---: | ---: |
| April | 39 | 53.85% | +31.99% |
| May | 47 | 38.30% | -15.40% |
| June | 41 | 51.22% | +17.92% |
| July | 28 | 57.14% | +27.61% |

The maximum historical drawdown was approximately `$15,186`, or `11.68` measured wallet units. The longest losing streak was five bets.

Performance was concentrated by price:

| Entry price | Bets | ROI |
| --- | ---: | ---: |
| Under 40 cents | 33 | +46.63% |
| 40–49 cents | 95 | +8.58% |
| 50–59 cents | 26 | -12.47% |
| 60 cents or higher | 1 | +16.24% |

The underdog result is interesting but based on only 33 bets. It should be monitored as a research segment, not promoted into a special production rule.

## Uncertainty And CLV

A 20,000-resample bootstrap estimated a 91.84% probability that the historical ROI is positive. Its 95% interval ranged from approximately -5.22% to +32.00%, which still includes no edge.

CLOB price history was available for 152 settled positions:

| CLV metric | Result |
| --- | ---: |
| Mean exchange CLV | -0.14 probability points |
| Stake-weighted exchange CLV | -0.15 probability points |
| Median exchange CLV | -0.50 probability points |
| Positive-CLV rate | 47.37% |

The wallet won more often than its entry prices implied, but it generally did not beat the closing market. That combination is consistent with either a real edge not recognized by the close or favorable variance. The current sample cannot distinguish those explanations confidently.

## Forward Validation

Formal-Cupcake is active in the paper model, but its role should be reviewed after forward observation provides:

- at least 100 new settled MLB moneylines
- positive stake-weighted exchange CLV
- positive CLV on more than 50% of qualified bets
- positive forward ROI after executable price slippage
- acceptable drawdown relative to the `$1,300` unit
- evidence that the under-40-cent segment remains profitable
- low dependency with existing Directional Core wallets
- a comparison of results with and without Formal-Cupcake as the Directional Core

The current production guardrail is consensus, not exclusion: Formal-Cupcake may anchor a candidate, but an independent wallet must confirm the same side before the recommendation is tracked. Its negative historical CLV remains a diagnostic and should not be treated as a veto while the complete system is being paper-tested.
