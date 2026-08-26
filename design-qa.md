# Mobile Tools Design QA

## Scope

Responsive phone workspace for Prediction Traders, Sharp Money, Positive EV, Arbitrage, Middles, Low Hold, Sportsbook Screen, Fantasy Optimizer, and Calculators.

Primary viewport: 390 × 844 CSS px (375 px content width with the test browser scrollbar). Additional checks: 320 × 720 and 768 × 1024.

## Source comparison

The supplied iPhone references were treated as the visual source of truth. Their 590 px screenshots correspond to roughly 393 CSS points at device scale, matching the 390 px implementation viewport.

- Arbitrage source: `2801E49C-0A44-44D8-B386-4FEDEA350FE3/8-Photo-8.jpg`
- Fantasy source: `2801E49C-0A44-44D8-B386-4FEDEA350FE3/5-Photo-5.jpg`
- Calculator source: `572899DA-A9E8-42DA-9D8C-56E0A5123F1F/2-Photo-2.jpg`
- Implementation captures: `mobile-arbitrage-collapsed.png`, `mobile-dfs-collapsed.png`, and `mobile-calculator.png` in the task visualization directory.

The reference and implementation images were reviewed together in the same comparison inputs. The implementation preserves the source hierarchy, dark navy/purple palette, compact metrics, 11–13 px outer gutters, 8–17 px radii, one-column phone flow, and green positive-value emphasis. Fixture values differ intentionally; structure and density are the comparison targets.

## Component and layout checks

- Shared header is 60 px high, preserves the IconLabs lockup, and exposes a 40 px menu control with an accessible label.
- Main tool gutters are 11–13 px; no content touches the screen edge.
- Search, select, input, tab, and primary tool controls are at least 46 px tall where they are primary touch targets.
- Arbitrage, middle, low-hold, +EV, sharp-money, and trader opportunities render as compact scan-first cards.
- Expanded opportunity details mount directly beneath the selected card and expose execution sizing, all-book prices, calculations, explanations, and chart regions without a side panel.
- DFS switches from the desktop comparison table to native disclosure cards. Each card exposes the selected-app line, modeled probability/fair odds, and every sportsbook/DFS comparison.
- Fantasy-app selection remains a native horizontal rail; filters remain two-column and the player search/reset controls use the full width.
- Odds uses compact game cards and a 90dvh bottom sheet for full market/book comparisons.
- Calculator tabs show Arbitrage, Expected Value, Bonus Bet, and Half Point together at 390 px, while remaining horizontally reachable for the full calculator set.
- Dialogs become bottom sheets and include iOS safe-area padding.
- No handmade icons or placeholder art were introduced; existing product and provider assets plus the current Phosphor icon system are reused.

## Interaction checks

- Navigation drawer opens, scrolls through all destinations, traps page scrolling, and closes correctly.
- Opportunity cards open and close inline on all six expandable feeds.
- A Prediction Trader disclosure remains open through the five-second live refresh.
- DFS player cards open through native `details` behavior and reveal all comparison rows.
- Odds game cards open and close the full market comparison sheet.
- Calculator category selection works; changing the EV wager from $100 to $250 recalculated expected net from $26 to $65.
- Existing filters, selectors, refresh controls, sportsbook buttons, links, and calculation actions remain in the original DOM rather than being replaced with visual-only copies.

## Responsive and runtime checks

- 390 × 844: all nine core routes reported equal document/client widths and `scrollX = 0`.
- 320 × 720: page overflow is clipped by the existing shell and attempting horizontal scroll returns `scrollX = 0` on every core route.
- 768 × 1024: arbitrage, +EV, DFS, and calculators retain their tablet/desktop compositions without horizontal scroll.
- The existing mobile layouts for Bet Tracker, LabTracker, Shadow Lab, Live Positions, Sharp Wallets, Position History, Edge Map, and Intelligence were also checked at 390 × 844; every route remained at the viewport width with `scrollX = 0`.
- Clean browser regression across all nine routes produced zero console warnings and zero console errors.
- Expanded inline details remain connected after live data refresh.
- Real production-preview APIs were not seeded; realistic fixtures were served only by an isolated visual-QA server outside the repository.

## Automated checks

- `node --check static/mobile-tools.js`: passed.
- `node --check static/app.js`: passed.
- `node tests/test_calculator_math.js`: passed.
- `pytest -q -p no:cacheprovider tests/test_mobile_tools_assets.py`: 4 passed.
- Existing design-system selection: 96 tests passed; 11 fixture setups were blocked by the machine's pre-existing pytest temp-directory ACL, not by product assertions.
- `git diff --check`: passed (line-ending notices only).

## QA history

1. Removed filter-strip overflow and matched the compact three-control mobile command rows.
2. Corrected the middles summary from a cramped two-column shell to a full-width three-metric row.
3. Corrected DFS selectors to the production DOM and removed the duplicate horizontal scrollbar.
4. Kept the full IconLabs wordmark visible in the phone header.
5. Centered +EV and sharp-money score rails without clipping long values.
6. Reduced calculator-tab padding so the first four categories fit the reference viewport.
7. Moved disclosure capture to the document level and retained card identity through feed refreshes.
8. Guarded the trader error state while its detail panel is temporarily mounted inline.

final result: passed
