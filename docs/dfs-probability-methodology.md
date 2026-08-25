# DFS fair-probability methodology

## What the competing products disclose

- OddsJam says its Fantasy Optimizer pulls prices from sharp sportsbooks and uses a weighted average to create its Algo Odds and hit-rate estimate.
- OddsJam separately documents multiplicative, additive, Shin, and power devig methods. For two-outcome markets, it says Shin is equivalent to additive.
- DGFantasy says its optimizer combines player props and fantasy-app lines, uses linemakers' probabilities, and calculates the chance that each Over or Under hits.
- Upside describes its optimizer workflow as fair-price comparison, line-discrepancy review, and devigged hit-rate analysis.

The competitors do not publish their exact source weights, calibration coefficients, stale-quote rules, or market-matching implementation. IconLabs therefore uses a transparent independently implemented consensus model rather than claiming access to a proprietary formula.

Public references:

- https://oddsjam.com/betting-education/how-to-use-the-oddsjam-fantasy-screen
- https://oddsjam.com/betting-education/uncovering-true-outcome-probabilities
- https://dev.dgfantasy.com/
- https://upside.tools/tools

## IconLabs calculation

For American odds `a`, raw implied probability is:

- positive odds: `100 / (a + 100)`
- negative odds: `abs(a) / (abs(a) + 100)`

Every source must provide paired Over and Under prices for the exact DFS strike. We remove the two-way overround independently for each source. The API supports power, multiplicative, additive, and Shin devigging. Shin is treated as additive for a two-outcome prop market.

For source `i`, its effective weight is:

`effective_weight_i = configured_weight_i * 0.5 ** (age_seconds_i / freshness_half_life_seconds)`

The fair probability is the normalized weighted mean of the included no-vig probabilities:

`p_fair = sum(p_i * effective_weight_i) / sum(effective_weight_i)`

The default IconLabs Algo Odds profile is FanDuel 30%, NoVIG 20%, ProphetX 15%, DraftKings 10%, Pinnacle 10%, Circa 7%, Kalshi 5%, and Polymarket 3%. User-defined profiles replace this allocation.

The response also returns weighted source dispersion, a reliability score based on configured-weight coverage, source count, and agreement, plus fair American odds. If a DFS slip's per-leg breakeven odds are supplied, edge is `p_fair - p_breakeven`.

## Guardrails

- Alternate sportsbook lines are excluded from the target probability rather than incorrectly treated as exact matches.
- Only the freshest exact-line quote from each provider is used.
- Stale, unmapped, invalid, one-sided, and zero-weight sources are excluded with explicit reasons.
- Missing evidence produces `UNAVAILABLE`; the engine never invents a hit rate.
- DFS line discrepancies remain useful context, but they are not converted into probability until a separately validated alternate-line distribution model is available.
