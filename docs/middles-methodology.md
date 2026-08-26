# IconLabs Middles methodology

## Scope

The Middles scanner finds pairs of independently executable sportsbook prices
where an ordinary result settles one ticket as a winner and a result inside a
line gap can settle both tickets as winners.

OddsJam's public explanation describes the same core construction: pair a
lower Over with a higher Under, or two overlapping opposing spreads, so a
result inside the gap wins both wagers. It does not publish a proprietary
middle-hit probability or ranking formula. IconLabs therefore uses only
auditable payout math and never labels a modeled hit chance as fact.

Public references:

- https://oddsjam.com/betting-tools/middles
- https://dev.oddsjam.com/betting-education/middles

## Market matching

Every pair must share the same event and market family.

- Totals and player props: `Over L` pairs with `Under U` only when `L < U`.
- Spreads: opposing selections with signed points `p1` and `p2` pair only when
  `p1 + p2 > 0`.
- Player props are additionally grouped by normalized player description, so
  quotes for different players cannot be combined.
- Started events, unsupported outcomes, invalid odds, and quotes older than the
  configured freshness limit are rejected before pairing.
- DFS pick'em entries are not treated as independently executable single-bet
  legs.

## Effective odds

American odds are converted to decimal odds. For exchanges, an optional
commission buffer is applied to net winnings:

```text
effective decimal = 1 + (decimal odds - 1) × (1 - commission rate)
```

Sportsbooks use their quoted decimal odds without an exchange commission.

## Stake sizing

For a total stake `S` and two effective decimal prices `d1` and `d2`, the ideal
stakes are:

```text
s1 = S × (1 / d1) / ((1 / d1) + (1 / d2))
s2 = S × (1 / d2) / ((1 / d1) + (1 / d2))
```

The implementation rounds to cents, then distributes remaining cents to the
leg with the smaller current payout. This maximizes the minimum outside payout
after real ticket rounding.

## Scenario values

For either outside result, only one ticket wins:

```text
outside profit i = si × di - S
worst outside profit = min(outside profit 1, outside profit 2)
```

Inside the middle, both tickets win:

```text
middle profit = s1 × d1 + s2 × d2 - S
```

The displayed cost is the percentage of stake lost in the worst outside case:

```text
cost % = max(0, -worst outside profit / S) × 100
```

When the worst outside profit is non-negative, the pair is also a guaranteed
arbitrage and the displayed middle cost is zero.

## Break-even middle probability

IconLabs reports a conservative break-even threshold instead of inventing a
hit probability:

```text
break-even % = outside risk / (middle profit + outside risk) × 100
outside risk = max(0, -worst outside profit)
```

This is the minimum middle frequency needed to break even if the worst outside
result is used for every non-middle outcome. It is intentionally conservative.

## Push boundaries

When a boundary is a whole number, the exact boundary can push one ticket while
the other ticket wins. The scanner reports those returned-stake scenarios
separately. Half-point boundaries cannot push under ordinary settlement rules.

## Ranking

Qualified rows are ranked by:

1. non-negative worst-case profit first;
2. lower break-even middle probability;
3. wider middle window;
4. larger middle profit percentage.

The list can be constrained by sportsbook, market, minimum window width,
maximum cost, maximum quote age, exchange commission, and distinct-book mode.

## Operational limits

- The calculation assumes both displayed prices remain available and both
  tickets are accepted at the shown stakes.
- Book limits, void rules, stat-provider differences, and odds movement can
  change the realized result.
- Live middle scanning is not enabled by this implementation.
- Preview mode is deterministic and never requests paid provider data.
