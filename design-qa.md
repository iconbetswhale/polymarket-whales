# DFS Odds Detail and DVIG Design QA — 2026-08-27

## Scope and source comparison

Implemented the expandable sportsbook comparison and private IconLabs DVIG state in the existing Fantasy Optimizer. The two supplied OddsJam images were reviewed beside the final 1440 × 900 implementation capture in one comparison pass:

- Sources: `ACE585E1-1FFF-40A7-96FE-488F882A3C00/1-Photo-1.jpg` (1278 × 338) and `ACE585E1-1FFF-40A7-96FE-488F882A3C00/2-Photo-2.jpg` (1278 × 253).
- Implementation: `dfs-expanded-implementation.png` in the task visualization directory.
- Supporting states: `dfs-devig-private-model.png` and `dfs-scrolled-player-column.png` in the same directory.

The result preserves IconLabs typography, navy surfaces, purple selection, existing provider logos, and numeric styling while matching the reference hierarchy: player context, Best Odds, Avg Odds, one shared sportsbook header, and tightly aligned Over/Under rows. The best available price uses the existing green positive-value token. No placeholder or handmade assets were introduced.

## Interaction and responsive checks

- Clicking anywhere on a prop row expands or collapses its paired market; Enter also expands it and updates `aria-expanded`.
- The detail shows both Over and Under for the same player, line, and stat across 16 sportsbook columns.
- Horizontal scrolling moves the entire player column out of view; it no longer overlays later odds columns.
- IconLabs Algo opens as selected with a 100% green allocation state while all eight visible sliders remain at 0%.
- Moving FanDuel to 30% immediately turns the private preset off, shows a 30% custom allocation, and leaves the apply action disabled until the allocation totals 100%.
- A 60% FanDuel / 40% Pinnacle custom allocation applied successfully, changed the displayed hit rate immediately, and updated the summary to `Custom DVIG · 100%`.
- Re-selecting IconLabs Algo restored the private 100% state without exposing its internal weights.
- At 390 × 844 the existing mobile card layout remains intact; the desktop-only table and detail do not leak into the phone layout.
- Desktop and mobile browser passes produced zero console warnings and zero console errors.

## Calculation and automated checks

- The API rejects custom allocations that do not total exactly 100%.
- The DFS payload retains per-book no-vig probability and freshness data so saved custom weights can reweight the board immediately.
- Zero-weight books remain available for later custom allocation without contributing to the active aggregate.
- `node --check static/dfs.js`: passed.
- Focused pytest suite: 61 passed in 16.18s.
- `git diff --check`: passed (line-ending notices only).

final result: passed

---

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

---

# Positive EV plays-first mobile QA

## Comparison target

- Source visual truth: `C:\Users\15617\.codex\codex-remote-attachments\01a04079-93e0-70e2-a501-ce3f763bc948\9C763005-C625-4713-A73E-E66A24C0248D\1-Photo-1.jpg`.
- Browser-rendered implementation: `C:\Users\15617\Documents\Polymarket\positive-ev-mobile-plays-first-20260826\.codex-artifacts\positive-ev-mobile-collapsed-final.png`.
- Expanded-control state: `C:\Users\15617\Documents\Polymarket\positive-ev-mobile-plays-first-20260826\.codex-artifacts\positive-ev-mobile-info-open-final.png`.
- Combined full-view evidence: `C:\Users\15617\Documents\Polymarket\positive-ev-mobile-plays-first-20260826\.codex-artifacts\positive-ev-mobile-before-after.png`.
- Combined focused evidence: `C:\Users\15617\Documents\Polymarket\positive-ev-mobile-plays-first-20260826\.codex-artifacts\positive-ev-mobile-header-before-after.png`.
- Viewport and density: 390 × 844 CSS px at device scale factor 1. The in-app browser capture is 375 × 812 pixels after browser-owned scrollbar/chrome cropping. The source is 589 × 1280 pixels and includes iOS status and Safari chrome; the app-owned source region was cropped from y=83 to y=1100 and proportionally normalized for the combined comparisons.
- State: dark theme, ten populated +EV plays, information drawer collapsed and expanded.

## Findings

- No actionable P0, P1, or P2 findings remain.
- Fonts and typography: the existing IconLabs UI/data font hierarchy is preserved. +EV and Pre-Match are compact, search remains at a legible 16 px input size, metadata is secondary, and matchup/selection values stay visually dominant without unintended wrapping or clipping.
- Spacing and layout rhythm: the inherited 72 px desktop top padding is removed on phones. The first play begins at y=205, all primary content sits on consistent 11 px gutters, and the document and client widths both measure 375 px with no horizontal overflow.
- Colors and visual tokens: the existing navy, near-black, purple, green, border, glow, and state tokens are reused. The information drawer reads as part of the same product rather than a new visual system.
- Image quality and asset fidelity: existing team, league, and provider assets remain sharp and correctly contained. Existing Phosphor icons are used for Info, Filters, More, status, and carets; no handmade SVG, CSS art, emoji, or placeholder assets were introduced.
- Copy and content: the collapsed phone state contains only +EV, Pre-Match count, Search, Info, live status, updated time, and plays. Validation counts, bankroll, unit size, filters, and secondary actions move into the Info drawer.
- Accessibility and affordances: Info uses native `details`/`summary` behavior, the drawer has an explicit accessible label and state caret, search remains labelled, and existing filter, menu, bankroll, and card controls retain their original semantics.

## Full-view and focused comparison evidence

- Full-view: the supplied reference and final implementation were combined into one image. The reference devotes most of the first viewport to a blank band, validation banner, finance strip, and action chrome; the final layout removes the blank band and places the first complete play immediately after one compact command row.
- Focused region: the header/card comparison confirms that the title, tab, search, and Info control share one aligned plane; the desktop finance strip no longer leaks into the collapsed phone state; and the first play keeps even metric columns and a full-width card boundary.
- No additional focused image crop was required because the source and implementation use the same existing team/provider imagery and icon system, all of which is readable in the captured header/card region.

## Interaction and runtime checks

- Info opens and exposes validation counts, bankroll, unit size, Filters, and More.
- Filters opens the existing bottom-sheet dialog and closes normally.
- More opens the existing action menu.
- Bankroll opens its editable popover.
- Searching for `Aces` reduces the populated feed to exactly one play, then clearing search restores the feed.
- The collapsed document reports `body.scrollWidth = documentElement.clientWidth = 375`; horizontal overflow is zero.
- Browser console check after all interactions: zero errors.

## Comparison history

1. P1 — desktop shell padding produced the large blank band above +EV. Fixed with a page-specific phone shell reset. Post-fix evidence: first play starts at y=205 in `positive-ev-mobile-collapsed-final.png`.
2. P1 — bankroll, unit size, filter, validation, and More controls all remained exposed above the feed. Fixed by grouping them into one native Info disclosure while leaving Search visible. Post-fix evidence: `positive-ev-mobile-info-open-final.png`.
3. P2 — the Pre-Match tab inherited a full-row width and extended the title row beyond the phone canvas. Fixed by constraining the tab to its content width and allowing it to shrink. Post-fix measurement: document and client widths are both 375 px.
4. P2 — recommended-bet and total-payout metrics used uneven flex sizing. Fixed with equal minmax grid tracks and consistent compact metric heights.

## Automated checks

- `node --check static/positive-ev.js`: passed.
- `node --check static/mobile-tools.js`: passed.
- `pytest tests/test_positive_ev_design_system.py tests/test_mobile_tools_assets.py -q -p no:cacheprovider`: 34 passed.
- `pytest tests/test_app.py -k "positive_ev" -q -p no:cacheprovider`: 8 passed, 82 deselected.

final result: passed

---

# Flush mobile navigation, DFS app picker, and scan-first Traders QA

## Comparison target

- Source visual truth:
  - `C:\Users\15617\.codex\codex-remote-attachments\01a03fdb-84b7-7442-952c-cf114d152ca9\01CD801D-70E3-4A7A-86EE-0F01E1854DC5\1-Photo-1.jpg`
  - `C:\Users\15617\.codex\codex-remote-attachments\01a03fdb-84b7-7442-952c-cf114d152ca9\01CD801D-70E3-4A7A-86EE-0F01E1854DC5\2-Photo-2.jpg`
- Browser-rendered implementation states: Fantasy Optimizer with the contained app picker, Prediction Traders with five live fixture cards, and Prediction Traders with an expanded labelled sample trade.
- CSS viewport: 390 × 844 for primary comparisons, with additional checks at 320 × 720 and 1280 × 800.
- The two source screenshots and final browser captures were opened in one combined comparison input before this QA was written.

## Findings

- No actionable P0, P1, or P2 visual findings remain.
- The mobile navigation now terminates exactly at the visible viewport bottom (`bottom = 844` at 390 × 844 and `bottom = 720` at 320 × 720) with zero side gutters and top-only rounding.
- Fantasy Apps presents one active source plus a same-width `Other apps` picker. The five source buttons remain authoritative in the DOM, and choosing Underdog through the mobile picker updated the active source and comparison heading without horizontal overflow.
- Prediction Traders now begins 10 px below the 62 px brand bar. The command dashboard, KPI strip, filter toolbar, and signal-activity panel are hidden only at phone widths.
- Live cards are approximately 153 px tall, retain the event, selection, best executable price, confidence, and sample sizing, and fit five partially or fully visible opportunities above the navigation at 390 × 844.
- Empty or fully filtered feeds expose three non-actionable examples explicitly labelled `Sample layout · not live recommendations`, followed by `More plays are coming`.
- Expanded real trades remain inline beneath their source card and continue to expose execution prices, sharp comparisons, model detail, sizing, price history, and advanced evidence.
- Existing provider logos and the Phosphor icon system are reused. No placeholder imagery, handmade SVGs, emoji, or approximate asset drawings were introduced.

## Interaction and responsive checks

- The mobile DFS picker changed PrizePicks to Underdog and reset itself to the `Other apps` prompt while leaving only Underdog visible as the active card.
- A real Prediction Traders card opened inline, remained open across more than one live refresh interval, retained five live cards, and produced no error state.
- Sample disclosures enforce one open example at a time and show current price, model fair price, projected edge, sizing, and an explicit preview-only notice.
- 390 × 844: all tested phone states stayed within the document width; the navigation edge equalled the viewport edge.
- 320 × 720: the app picker retained one active card plus the other-app control, sample cards remained usable, and body-level overflow clipping prevented horizontal scrolling.
- 1280 × 800: mobile navigation, the other-app picker, and sample trades are hidden; all five DFS source cards and the full Prediction Traders dashboard remain visible.

## QA history

1. Replaced the overflowing mobile fantasy-app rail with an active-source slot and a native other-app selector.
2. Removed the floating navigation gap and changed the rail to full viewport width with safe-area-aware internal padding.
3. Removed dense Prediction Traders controls from the phone composition and compressed live rows for faster scanning.
4. Moved personal-exposure warnings inside the confidence column so they no longer overlap event names.
5. Prevented the legacy tablet modal from competing with phone inline disclosures.
6. Preserved the inline detail node during live feed replacement, eliminating a refresh race that previously disconnected the detail panel.
7. Removed the modal-only sheet header from the inline detail presentation.

## Automated checks

- `node --check static/app.js`: passed.
- `node --check static/mobile-tools.js`: passed.
- `node tests/test_calculator_math.js`: passed.
- `pytest -q -p no:cacheprovider tests/test_mobile_tools_assets.py`: 8 passed.
- `git diff --check`: passed, with line-ending notices only.

final result: passed

---

# Mobile bottom navigation and Prediction Traders search QA

## Comparison target

- Source visual truth:
  - `C:\Users\15617\.codex\codex-remote-attachments\01a03fdb-84b7-7442-952c-cf114d152ca9\AF81555B-9ACC-4EF0-A4BA-F604DF151470\1-Photo-1.jpg`
  - `C:\Users\15617\.codex\codex-remote-attachments\01a03fdb-84b7-7442-952c-cf114d152ca9\AF81555B-9ACC-4EF0-A4BA-F604DF151470\2-Photo-2.jpg`
  - `C:\Users\15617\.codex\codex-remote-attachments\01a03fdb-84b7-7442-952c-cf114d152ca9\AF81555B-9ACC-4EF0-A4BA-F604DF151470\3-Photo-3.jpg`
- Browser-rendered implementation:
  - `C:\Users\15617\.codex\visualizations\2026\08\26\01a03fdb-84b7-7442-952c-cf114d152ca9\mobile-bottom-nav-traders.png`
  - `C:\Users\15617\.codex\visualizations\2026\08\26\01a03fdb-84b7-7442-952c-cf114d152ca9\mobile-more-sheet.png`
- CSS viewport: 390 × 844, dark theme, Prediction Traders route, collapsed navigation and open More-sheet states.
- Pixel dimensions: each source screenshot is 589 × 1280; each implementation capture is 375 × 812. The images were normalized by proportional width during the combined comparison. Source-only iOS status/home chrome and browser-owned viewport cropping were excluded from fidelity findings.

## Findings

- No actionable P0, P1, or P2 findings remain.
- Fonts and typography: the implementation keeps the existing IconLabs Inter/DM Sans hierarchy while matching the reference navigation's compact labels, high-contrast active item, and 16 px sheet-row text. The search placeholder now begins after the icon with a readable 10 px visual gap.
- Spacing and layout rhythm: the six equal-width primary actions remain inside 10 px phone gutters. The More sheet starts at roughly 43% of the visible implementation height, matching the reference's lower-sheet proportion, and uses a scrollable row stack for the larger IconLabs route set.
- Colors and tokens: the navy/near-black surfaces, cool gray text, subtle borders, purple active state, dimmed backdrop, and blurred bottom rail remain consistent with IconLabs and the supplied reference.
- Image quality and assets: no raster imagery is required in these navigation states. All visible icons use the product's existing Phosphor icon family; no handmade SVG, CSS art, emoji, or placeholder assets were introduced.
- Copy and content: the primary labels are Money, Traders, Arbs, +EV, Track, and More. The sheet contains every remaining IconLabs destination and a Settings entry instead of copying OddsJam-only product labels.
- Accessibility and behavior: primary items and sheet rows meet practical touch heights; the sheet is a labelled modal region, traps keyboard focus, honors Escape and backdrop dismissal, restores focus to More, locks background scrolling, and disables animation for reduced-motion users.

## Full-view and focused comparison evidence

- Full-view comparison: the OddsJam bottom rail and open sheet were opened beside the final IconLabs captures in the same comparison input. The fixed rounded rail, six-item hierarchy, dimmed backdrop, top handle, upward sheet motion, and large stacked destinations are visibly preserved.
- Focused comparison: the supplied Prediction Traders screenshot and the final collapsed capture were compared together. The source showed the search icon sitting on top of the placeholder; the final capture shows separate 18 px icon and input boxes with no rectangle intersection.
- Additional focused checks were unnecessary because the states contain no product imagery or unusually fine visual assets beyond the navigation icons and search control.

## Interaction and responsive checks

- Prediction Traders search accepted `Liberty`, kept focus, and reduced the fixture feed to one matching visible card.
- More opened upward, exposed 12 route links, kept its internal list scrollable, and closed through Escape while restoring focus to the More button.
- Fantasy Optimizer correctly marks More and the matching sheet route active. Navigation from More to Calculators and from the primary rail back to Traders completed successfully.
- 390 × 844: document width equals client width, horizontal scroll remains zero, the search icon and input do not overlap, and all six primary actions are visible.
- 320 × 720: the bar remains within 10 px gutters, all six actions remain visible, the search stays separated, and the sheet remains scrollable.
- 1280 × 800: the mobile bar and sheet are hidden; the existing 256 px desktop sidebar remains visible and unchanged.
- Browser console: zero errors and zero warnings across the tested states and route changes.

## Comparison history

1. P1 — the inherited absolute icon positioning overlapped the Prediction Traders placeholder. Fixed by returning the icon to flex flow, assigning an 18 px slot, and removing native search-field appearance. Post-fix evidence: `mobile-bottom-nav-traders.png`; geometric overlap check is false.
2. P0 — the first More-sheet pass remained hidden because the base display rule was not overridden inside the phone media query. Fixed with explicit phone-only display declarations. Post-fix evidence: the sheet renders at full viewport width with all 12 links present.
3. P2 — the first visible sheet occupied 78dvh and rose materially higher than the supplied reference. Reduced it to 58dvh while retaining internal scrolling. Post-fix evidence: `mobile-more-sheet.png`, with the sheet beginning at y=364 in the 844 px CSS viewport.

## Automated checks

- `node --check static/app.js`: passed.
- `node --check static/mobile-tools.js`: passed.
- `node tests/test_calculator_math.js`: passed.
- `pytest -q -p no:cacheprovider tests/test_mobile_tools_assets.py`: 6 passed.
- Broader design-system selection: 107 assertions passed; 18 fixture setups remain blocked by the machine's existing pytest temporary-directory ACL rather than product assertions.
- `git diff --check`: passed, with line-ending notices only.

final result: passed
