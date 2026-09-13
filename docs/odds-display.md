# Site-wide Odds Display

`static/odds-format.js` is the shared display boundary, loaded before every tool. The default is **American**; the supported view preferences are `american`, `cents`, and `decimal`. Even money consistently displays as `+100`.

## Future Account Setting

Use `window.IconLabsOdds.getFormat()` and `window.IconLabsOdds.setFormat(value)` for the Account odds-view selector. The existing profile form uses these same methods and offers American, Cents, and Decimal; no new Account section is added. The preference is saved to the browser's `iconlabs-odds-format` key, is shared across navigation, and synchronizes across browser tabs. Account/server synchronization can be added when the Account settings section is built; do not mistake browser persistence for cross-device account storage.

Subscribers receive `iconlabs:odds-format-changed` with `event.detail.format`. Tools re-render their current views when the preference changes. Unsupported/corrupt preferences fall back to American. Previously inert profile choices are not automatically activated.

## Coverage

Prediction Traders, Sharp Money, Positive EV, Odds Screen (desktop and mobile), Fantasy Optimizer, Arbitrage, Middles, Low Hold, Futures, Bet Tracker (tracked bets, personal bets, calendar and CLV breakdowns), LabTracker, Positions (My Bets, Sharp Positions, and CLV pop-out), Sharp Wallets, Bet History, overview, Edge Map and Shadow Lab use the shared boundary for quoted betting prices.

Use `fromProbability`, `fromAmerican`, `fromDecimal`, or `fromCents` with the known input type. `quote()` handles structured provider quotes and prefers verified fee-adjusted executable prices. Never render provider `displayOdds`/`provider_display_odds` directly. Bare decimal strings require an explicit source-format hint; guessing could invent odds from unavailable data.

The historical `formatCents()` name in `app.js` now formats a probability in the selected view format. It is not a mathematical cents conversion. American math helpers remain independent of the display preference.

## Intentional Units

- Stakes, payouts, fees, shares, market lines, win probabilities, CLV percentages, and probability-point differences are not odds and retain their own units.
- Actual exchange share-price entry/exit fields and share-price thresholds are monetary inputs, explicitly labeled in cents; they are not sportsbook odds fields. Their API contracts and validation remain unchanged.
- Calculation editors explicitly accept American odds, regardless of display preference, so saving a bet or calculating a stake never parses formatted cents/decimal as American odds.
- The purpose-built Odds Converter deliberately labels equivalent formats together. Other calculator quote results follow the preference.
- Settled contracts at 0 or 1 represent terminal payouts, not finite odds. Missing/invalid prices show unavailable states, never fake zero odds or even money.

Stored probabilities, native provider prices, fee calculations, CLV capture and bankroll math remain unrounded and unchanged. Conversion/rounding occurs only while rendering.

## Checks

Run `node --test tests/test_odds_format.js tests/test_personal_position_clv.js tests/test_tracker_recap.js` and `python -m pytest tests -q` before publishing. Verify at least the Positions/CLV, Odds Screen, and scanner views in desktop and mobile layouts.
