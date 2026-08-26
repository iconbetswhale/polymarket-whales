# IconLabs Low Hold methodology

IconLabs Low Hold compares current executable prices. It does not estimate a
fair probability and it does not claim access to OddsJam's proprietary ranking,
source weights, market-matching implementation, or private code. The product
uses the standard hold and hedge formulas described publicly by sportsbook
education tools, including OddsJam's public hold calculator and middle-bet guide.

## 1. Price conversion

For positive American odds `A`:

```text
decimal = 1 + A / 100
implied probability = 100 / (A + 100)
```

For negative American odds `A`:

```text
decimal = 1 + 100 / |A|
implied probability = |A| / (|A| + 100)
```

If a selected venue is an exchange, the configured commission buffer applies
only to net winnings:

```text
effective decimal = 1 + (decimal - 1) × (1 - commission rate)
```

## 2. Exact-line hold

IconLabs requires a complete set of mutually exclusive outcomes for the exact
same event, participant, market, and line. It selects the qualified prices that
minimize the total implied probability:

```text
S = Σ(1 / effective decimal odds)
hold % = (S - 1) × 100
```

- `hold > 0`: the equalized plan has a small worst-case cost.
- `hold = 0`: the plan is approximately break-even before cent rounding.
- `hold < 0`: the prices form an arbitrage and the equalized plan has a
  guaranteed profit if every leg fills and is honored.

## 3. Equal-return stake sizing

The default workflow locks the user's first bet at amount `B`. Its effective
decimal odds define the target payout:

```text
target payout = B × odds_1
hedge_i = target payout / odds_i
```

Each hedge is rounded to the cent value whose returned payout is closest to the
target. The first-bet stake never changes. This matches the efficient public
low-hold workflow in which a bettor enters the intended amount for one side and
receives the amount needed on every opposing side. The displayed total stake is
the sum of the locked first bet and all calculated hedges.

Users can switch to total-bankroll mode. For a user-selected total stake `T`,
each leg then receives:

```text
stake_i = T × (1 / odds_i) / S
```

The theoretical payout is `T / S` in every mutually exclusive outside outcome.
IconLabs converts that allocation to cents, preserves the exact total stake,
and adds remaining cents to the leg with the lowest current payout. In both
modes, the displayed cost, return, and capital-retained figures use the actual
rounded stakes rather than an unrounded estimate.

## 4. Middle windows

For compatible totals and player props, IconLabs may pair `Over L` with
`Under H` when `H > L`. It still equalizes the two outside outcomes using the
selected sizing mode. It then enumerates attainable integer results from
`ceil(L)` through `floor(H)`:

- a winning leg returns `stake × effective decimal odds`;
- a pushed leg returns its stake;
- a losing leg returns zero.

This distinguishes a true both-win middle from a win-and-push half-point
window. The middle profit is conditional on the final graded result landing at
the displayed value; it is not guaranteed.

## 5. Structural safeguards

The scanner rejects:

- started or invalid events;
- invalid American prices;
- quotes older than the configured limit;
- incomplete exact-line outcome sets;
- odds outside the user's range;
- pairs above the maximum hold;
- middle lines narrower than the configured distance;
- same-book assignments when distinct sportsbooks are required;
- DFS pick'em entries that cannot be executed as independent single bets.

Low hold reduces pricing loss. It does not remove line movement, rejected stake,
limit, grading, void, account, or sportsbook counterparty risk.

Public references:

- https://oddsjam.com/betting-calculators/hold
- https://oddsjam.com/betting-tools/middles
