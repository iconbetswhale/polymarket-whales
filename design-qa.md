# Prediction Traders design-system extraction QA

## Combined comparison evidence

The frozen production reference and the post-refactor local render were placed
side by side and judged together at identical target dimensions:

- `docs/design-system/comparisons/prediction-traders-compare-1920x1080.png`
- `docs/design-system/comparisons/prediction-traders-compare-1440x900.png`
- `docs/design-system/comparisons/prediction-traders-compare-390x844.png`

## Visual judgment

Result: passed.

- Application shell, command header, four-metric summary, filter bar, opportunity
  geometry, selection hierarchy, executable quote chips, provider-logo colors,
  stake alignment, detail rail, evidence metrics, and chart proportions match.
- Desktop card width and height remain exactly 1171.203 × 112px at 1920 and
  732 × 112px at 1440.
- Mobile card width remains 354.109px; the approximately one-pixel height change
  follows removal of the preview badge, not a spacing redesign.
- The 390px screenshot was exported at exact 390 × 844. The in-app browser's
  scrollbar reduces document content width to 375px at that breakpoint, which
  matches the frozen computed mobile reference.
- No horizontal document overflow was introduced.

## Intentional differences

- Confirmed temporary `DESIGN PREVIEW` badges and their all-card purple
  preview-border treatment were removed.
- Production client-preview data was removed; post-refactor images use the
  deterministic local five-trade fixture. Dynamic times, quotes, liquidity, and
  chart paths therefore differ without affecting design parity.
- A single `Bet Size` label replaces the former duplicated Stake treatment.

## Severity review

- P0: none
- P1: none
- P2: none

## Interaction and accessibility

- Native controls retain focus-visible treatment and keyboard operation.
- Detail drawer modal semantics, inert background, focus containment, Escape
  close, and focus restoration remain intact at drawer breakpoints.
- Provider identity, quote links, price-chart keyboard navigation, and state
  announcements retain accessible labels.
- Shared chart styling does not alter Bet Tracker's dollar-domain chart logic.

## Verification

- Full Python regression suite: 639 passed.
- JavaScript syntax validation: passed.
- Python visual-QA fixture compilation: passed.
- Browser console at the verified mobile state: no warnings or errors.
- Horizontal-overflow check at 390px: passed.
- Diff whitespace validation: passed.

final result: passed

---

# Positive EV — v2 Color-Base Typography Restoration QA

## Evidence and comparison method

- Source visual truth: `C:\Users\sport\OneDrive\Pictures\Screenshots\Screenshot 2026-08-21 103753.png` (2292 × 726 px).
- Reported v2 regression: `C:\Users\sport\OneDrive\Pictures\Screenshots\Screenshot 2026-08-21 103812.png` (2292 × 720 px).
- Final browser implementation: `C:\Users\sport\Documents\polymarket-whales\design-audits\positive-ev-v2-restoration\06-final-preview.png` (1826 × 1272 px).
- Native-scale combined comparison: `C:\Users\sport\Documents\polymarket-whales\design-audits\positive-ev-v2-restoration\05-reference-vs-restored.png` (2714 × 822 px).
- Verified route: `http://127.0.0.1:5097/positive-ev?preview=1`.
- State: temporary preview opportunities, Philadelphia Phillies selected, detail rail open, explanatory disclosures closed.

The combined comparison keeps the 96px opportunity card and the 550px detail rail at native pixel scale. The card widths differ because the source is a wide cropped content view and the in-app browser includes the 232px application sidebar; neither card crop is rescaled. The detail crops are an exact 551px/550px width comparison.

## Resolved findings

- P1 — The v2 migration reduced the previously approved desktop type hierarchy across EV, Track, matchup, market, selection, wager metrics, execution odds, and the expanded details rail.
  - Fix: restored the locked desktop scale while continuing to use only v2 typography families and color/surface tokens.
  - Post-fix evidence: EV is 30px; Track is 12px with a 16px icon; time is 13px; matchup and selection are 18px; league is 14px; market is 20px; labels are 10px; amounts and execution odds are 16px. Expanded-detail matchup/selection are 18px, stake is 24px, Market Odds is 20px, sides are 14px, liquidity is 11px, and prices are 18px.
- P1 — The initial restoration allowed v2 shared-control specificity to keep Track at 34px tall, the sportsbook mark at 24px, and the executable quote narrower than the approved geometry.
  - Fix: added page-owned v2 selectors for the 72 × 28px Track control, 26px sportsbook mark, and at least 98 × 46px executable quote.
  - Post-fix evidence: browser computed styles match those dimensions and preserve an 8px right buffer inside the 202px score column.
- P1 — At the available 1826px browser width, the 550px details rail left the selection cell too narrow and caused unnecessary three-line wrapping.
  - Fix: rebalanced the opportunity tracks to `202px / minmax(200px, .9fr) / minmax(140px, .65fr) / minmax(450px, 1.8fr)` and restored the execution cell's intended padding.
  - Post-fix evidence: the 993px card resolves to 202/200/140/450px tracks; selection measures 142 × 46px; every cell stays inside the card and all four visible rows preserve left-to-right ordering.
- P2 — Market Odds price cells stretched wider than last night's approved inspector layout.
  - Fix: centered the comparison content in a 448px rail and set 45px rows.
  - Post-fix evidence: each price box measures 189 × 30px inside the fixed 550px details rail, matching the source proportions.

No actionable P0, P1, or P2 findings remain.

## Visual and interaction QA

- The new v2 navy color base, purple brand/focus treatment, green positive-value treatment, border tokens, and shared surfaces remain intact; no legacy stylesheet was reintroduced.
- The selected opportunity retains the requested purple selection outline through v2 interactive/focus tokens.
- No card cell extends outside its row, no adjacent columns overlap, and the page has no horizontal overflow at 1826 × 1272.
- Track opened the sportsbook tracking dialog, `Track and Hide` remained visible, and the dialog closed without saving.
- Positive EV Filter opened with the capitalized title and all three market groups, then closed normally.
- Browser diagnostic log: no warnings or errors.

## Automated verification

- Positive EV, typography, and sidebar-focused suite: 32 passed.
- Positive EV design-system suite after the final spacing adjustment: 7 passed.
- `git diff --check`: passed with line-ending notices only.
- No deploy, commit, or push was performed.

final result: passed

# Positive EV Large-Score Card Exploration — 2026-08-19

## Evidence

- Source visual truth: `C:\Users\sport\OneDrive\Pictures\Screenshots\Screenshot 2026-08-19 200951.png` (669 × 481 pixels).
- Browser-rendered implementation: `C:\Users\sport\Documents\polymarket-whales\design-audits\positive-ev-score-exploration\04-large-ev-refined-page.png` (1759 × 1261 pixels).
- Focused implementation crop: 1011 × 444 pixels, covering the four visible play cards.
- Same-input comparison: `C:\Users\sport\Documents\polymarket-whales\design-audits\positive-ev-score-exploration\05-reference-vs-large-ev.png` (1653 × 444 pixels).
- Verified route: `http://127.0.0.1:5097/positive-ev?preview=1`.
- CSS viewport: 1774 × 1272 at device pixel ratio 1.
- State: four temporary preview opportunities, Philadelphia Phillies selected, detail panel open, and two tracked states visible.

The full browser capture verifies the score column within the complete card-and-inspector layout. The focused side-by-side comparison is required because the source is a cropped card-list reference and the requested fidelity target is specifically its oversized green score hierarchy.

## Findings and comparison history

- Initial P2 — Enlarging the EV column to 150px reduced the first selection cell enough that `Philadelphia` wrapped mid-word under the existing `overflow-wrap: anywhere` rule.
  - Fix: the large-card breakpoint now uses natural word wrapping and disables hyphenation for selection text.
  - Post-fix evidence: `Philadelphia Phillies` wraps at the space, all four selection boxes remain readable, and the card has no horizontal overflow.
- Final comparison — No actionable P0, P1, or P2 differences remain for the requested score treatment.
- Intentional product adaptation: the reference's integer confidence score becomes the complete green EV percentage, while the requested Track/Tracked control replaces the Confidence label and progress bar.
- Intentional design-system adaptation: the existing IconLabs typeface, green EV token, purple active border, sportsbook controls, and Phosphor tracking icons remain unchanged.

## Required fidelity surfaces

- Fonts and typography: EV increases from 22px to 36px with tighter display tracking, matching the reference's dominant score hierarchy while retaining the complete percentage value. Track stays at the requested 10px with its 14px icon.
- Spacing and layout rhythm: the first divider moves from 90px to 150px at play rails 900px and wider. EV and Track are centered as one vertical score group; narrower rails retain the prior layout.
- Colors and visual tokens: the current green positive-EV treatment and purple selected-card emphasis are preserved; no new palette or gradient was introduced.
- Image quality and asset fidelity: the reference contains no new raster asset to reproduce. Existing sportsbook logos and Phosphor icons remain source assets rather than approximations.
- Copy and content: the full EV percentage and Track/Tracked labels remain visible, and all matchup, market, selection, bet sizing, payout, and odds content is retained.

## Interaction and browser QA

- Clicking Track on the third card opened `Track a sportsbook bet` with the correct Chicago Cubs vs Milwaukee Brewers event, Under 8.5 selection, $58 recommendation, and +105 odds; the modal then closed normally without saving.
- Browser console log check returned no entries.
- The first card measures 1011 × 96 CSS pixels with `150px 260.594px 193.031px 405.375px` tracks; neither the card nor page overflows horizontally.

## Automated verification

- Focused Positive EV tests: 6 passed.
- `node --check static/positive-ev.js`: passed.
- `git diff --check`: passed with line-ending notices only.
- No publish, deploy, commit, or push was performed.

final result: passed

---

# Positive EV — Expanded Detail Fit QA

## Evidence and normalization

- Source visual truth: `C:\Users\sport\OneDrive\Pictures\Screenshots\Screenshot 2026-08-18 213957.png` (1464 × 929 px).
- Final browser implementation: `C:\Users\sport\.codex\visualizations\2026\08\16\01a00b17-7cc8-7132-9b9d-ffffc0547e8e\positive-ev-narrow-detail-qa.png` (1265 × 712 px).
- Focused same-input comparison: `C:\Users\sport\.codex\visualizations\2026\08\16\01a00b17-7cc8-7132-9b9d-ffffc0547e8e\positive-ev-detail-fit-comparison.png` (1428 × 1404 px).
- Requested desktop viewport: 1464 × 929. The in-app browser surface captured at its available 1265 × 712 desktop viewport; the feed/detail regions were cropped and normalized to the same 1428px comparison width.
- Route and state: `http://127.0.0.1:5097/positive-ev?preview=1`, Philadelphia Phillies selected, detail expanded, five fake opportunities.

## Findings and comparison history

- [P1, fixed] The 450px inspector rail and late compact-card overrides left too little execution width. In the source screenshot, Recommended bet, To win, and the sportsbook odds button covered the selection and the odds button was clipped.
  - Fix: reduced the persistent rail to 290px (252px at the narrow desktop breakpoint), widened the available feed, restored the four-column play hierarchy, and gave execution an explicit selection / bet metrics / odds grid.
  - Post-fix evidence: the focused comparison shows every selection, both labeled amounts, the full sportsbook logo, odds, arrow, and complete button border with no overlap.
- [P2, fixed] The first fit pass retained oversized compact-card typography and a 30px sportsbook mark, causing event wrapping and crowding.
  - Fix: reduced detail-open event and EV type, tightened cell padding, and sized the execution mark to 22px while preserving the real logo asset.
  - Post-fix evidence: event names use a readable two-line hierarchy and all execution controls remain inside the row.

No actionable P0, P1, or P2 findings remain.

## Required fidelity surfaces

- Fonts and typography: existing DM Sans hierarchy retained; detail-open EV, event, market, selection, labels, and odds now fit without clipping or illegible compression.
- Spacing and layout rhythm: 12px feed/rail gap, 290px rail, stable four-column cards, and explicit three-part execution grid remove overlap while preserving dense sportsbook scanning.
- Colors and tokens: existing IconLabs purple selection, green executable value, cyan Track, and dark panel tokens are unchanged.
- Image quality and assets: existing real sportsbook logos and Phosphor icons remain sharp; no generated or placeholder assets were introduced.
- Copy and content: Recommended bet, To win, selection, event, market, sportsbook odds, and detail explanation are all present and visible.

## Interaction and accessibility QA

- Selecting New York Liberty updated the detail rail, then returning to Philadelphia Phillies restored the original state.
- Track toggled to Tracked and back to Track with the correct accessible names and pressed state.
- The sportsbook odds link remains a separate executable control and is no longer clipped.
- Browser console: no warnings or errors.

## Automated verification

- Full Python suite: 649 passed.
- `git diff --check`: passed (line-ending notices only).
- No publish, deploy, commit, or push was performed.

final result: passed

---

# Positive EV — Opportunity Feed QA

## Evidence

- Visual direction: `C:\Users\sport\Downloads\Screenshot_2026-08-18_at_3.17.04_PM.png` (2318 × 1001).
- Final desktop implementation: `C:\Users\sport\.codex\visualizations\2026\08\16\01a00b17-7cc8-7132-9b9d-ffffc0547e8e\positive-ev-left-row-v2-qa.png`.
- Same-input comparison: `C:\Users\sport\.codex\visualizations\2026\08\16\01a00b17-7cc8-7132-9b9d-ffffc0547e8e\positive-ev-reference-comparison.png`.
- Verified route: `http://127.0.0.1:5097/positive-ev?preview=1`.
- State: five temporary preview opportunities with Philadelphia Phillies selected.

The supplied reference and the implementation capture were placed side by side in one comparison image before this result was recorded.

## Visual match

- Typography: preserves the IconLabs type system while adopting the reference's compact, bold scan hierarchy for EV, event, market, selection, and executable odds.
- Layout: the left feed now uses dense sportsbook-style columns with a restrained active border, a Track control directly below EV, an explicit bet-sizing group, and a separate green execution-odds button.
- Colors: uses the existing purple IconLabs selection state, green only for value/executable outcomes, cyan for Track, and subdued navy surfaces and separators.
- Image assets: reuses the existing real sportsbook logo assets and the installed Phosphor icon set; no placeholder or fabricated assets were added.
- Copy: `Recommended bet` and `To win` make the two dollar values unambiguous. The profit value is rounded to two decimals and uses the quote's effective payout after applicable exchange fees.

## Intentional differences

- The expanded detail rail was not redesigned because the requested scope was specifically the left opportunity feed.
- Track replaces the reference's win-probability badge as requested. It is a local preview state and does not create a Bet Tracker record or place a wager.
- Recommended bet and To win are labeled cards instead of the reference's unlabeled stake amount.
- The purple IconLabs brand system remains in place instead of copying OddsJam's cyan shell.

## Interaction and accessibility QA

- The full row is selectable through a named overlay button without invalid nested-button markup.
- Track toggles to Tracked, exposes pressed state and a descriptive accessible name, and persists locally.
- Sportsbook execution remains a separate named link above the row-selection layer.
- Selecting a different opportunity updates the existing detail rail, then returns cleanly to the first play.
- Browser console: no warnings or errors.

## Responsive behavior

- Desktop keeps a compact four-column scan pattern.
- At narrower breakpoints the row collapses market metadata, stacks the event and execution content, and retains Track, Recommended bet, To win, and executable odds.
- The existing mobile detail-drawer and application-shell behavior were preserved rather than redesigned in this desktop-reference task.

## Automated verification

- Full Python suite: 649 passed.
- Focused Positive EV suite: 12 passed.
- `node --check static/positive-ev.js`: passed.
- `git diff --check`: passed (line-ending notices only).
- No publish, deploy, commit, or push was performed.

final result: passed

---

# Positive EV — Full-Width Workspace QA

## Evidence

- Reported desktop state: `C:\Users\sport\OneDrive\Pictures\Screenshots\Screenshot 2026-08-18 215957.png` (1480 × 1064).
- Final local implementation: `C:\Users\sport\.codex\visualizations\2026\08\16\01a00b17-7cc8-7132-9b9d-ffffc0547e8e\positive-ev-full-width-detail-qa.png` (1265 × 712).
- Normalized visual comparison: `C:\Users\sport\.codex\visualizations\2026\08\16\01a00b17-7cc8-7132-9b9d-ffffc0547e8e\positive-ev-full-width-comparison.png` (1480 × 1991).
- Verified route: `http://127.0.0.1:5097/positive-ev?preview=1`.
- State: five temporary preview opportunities with Philadelphia Phillies selected.

The final in-app-browser capture was normalized to the reference width in the comparison image because the available browser canvas was narrower than the submitted screenshot.

## Resolved findings

- P1 — The 1180px content cap left approximately 283px of unused space to the right of the expanded details rail in the supplied screenshot.
  - Fix: the Positive EV content and workspace now use the full available application width, with only the existing page padding at the right edge.
  - Post-fix evidence: the details panel reaches the workspace's right boundary with no separate dead-space column.
- P2 — Expanding the detail panel could not reduce the feed width or reintroduce overlap in the execution controls.
  - Fix: the desktop grid is `minmax(0, 888px) minmax(280px, 1fr)` with a 12px gap. This increases the play-card column by exactly 10px at the submitted desktop width while the detail panel absorbs every remaining pixel.
  - Post-fix evidence: measured in the available browser canvas, the play-card column increased from 683px to 693px, the detail rail retained its 280px minimum, and all Recommended bet, To win, and odds controls remained visible.

No actionable P0, P1, or P2 findings remain.

## Required fidelity surfaces

- Fonts and typography: the existing IconLabs hierarchy remains unchanged and legible at both the wider feed and expanded detail widths.
- Spacing and layout rhythm: the play-card column gains exactly 10px, the 12px inter-column gap remains stable, and the detail rail consumes the remaining workspace width.
- Colors and tokens: the existing purple, green, cyan, navy, and divider tokens are unchanged.
- Image quality and assets: existing sportsbook logos and Phosphor icons remain crisp; no placeholder assets were introduced.
- Copy and content: EV, event, market, selection, Recommended bet, To win, sportsbook odds, and sharp-book details remain present without clipping.

## Interaction and accessibility QA

- Selecting New York Liberty updated the detail rail, then returning to Philadelphia Phillies restored the original state.
- Track toggled to Tracked and back to Track with the correct accessible names and pressed state.
- All execution controls remained visible and independently interactive.
- Browser console: no warnings or errors.

## Automated verification

- Full Python suite: 649 passed.
- `git diff --check`: passed (line-ending notices only).
- No publish, deploy, commit, or push was performed.

final result: passed

---

# Positive EV — 400px Feed and Detail Hierarchy QA

## Evidence

- Source visual truth: `C:\Users\sport\.codex\visualizations\2026\08\16\01a00b17-7cc8-7132-9b9d-ffffc0547e8e\positive-ev-400px-before.png` (1265 × 712).
- Final viewport implementation: `C:\Users\sport\.codex\visualizations\2026\08\16\01a00b17-7cc8-7132-9b9d-ffffc0547e8e\positive-ev-400px-detail-viewport.png` (1265 × 712).
- Final full-page hierarchy: `C:\Users\sport\.codex\visualizations\2026\08\16\01a00b17-7cc8-7132-9b9d-ffffc0547e8e\positive-ev-400px-detail-full.png` (1265 × 1576).
- Same-state comparison: `C:\Users\sport\.codex\visualizations\2026\08\16\01a00b17-7cc8-7132-9b9d-ffffc0547e8e\positive-ev-400px-comparison.png` (2530 × 746).
- Verified route: `http://127.0.0.1:5097/positive-ev?preview=1`.
- CSS viewport: 1280 × 720 at device pixel ratio 1. The in-app Browser capture excludes a small amount of browser-owned scrollbar/chrome area, yielding the 1265 × 712 raster.
- State: five temporary preview opportunities, Philadelphia Phillies selected, Market Trend tab selected, and both detail accordions closed.

The before and after viewport captures were combined into one same-size comparison image before this result was recorded. The full-page capture was reviewed separately because the requested Market Trend and closed accordions sit below the initial 720px viewport.

## Comparison history and resolved findings

- P1 — The existing 693px feed did not match the requested 400px play-card width.
  - Fix: the desktop workspace now uses a fixed 400px feed track and an elastic details track. Each rendered play card measures exactly 400px in the browser.
  - Post-fix evidence: the card grid uses a two-row compact arrangement, preserving EV, Track, event, league, market, selection, Recommended bet, To win, and execution odds without overlap.
- P1 — The detail order led with the EV explanation and sharp-source list instead of executable market pricing.
  - Fix: Market Odds now follows the selected-play summary, Market Trend follows Market Odds, and the explanatory sections follow the trend.
  - Post-fix evidence: measured document offsets are Market Odds 175px, Market Trend 624px, Why 1199px, and Sharp Odds 1252px.
- P2 — The explanation and sharp-source sections were always expanded, making the inspector longer and slower to scan.
  - Fix: both were converted to native, keyboard-accessible `details` disclosures and render closed by default.
  - Post-fix evidence: both disclosures began closed, opened on activation, and returned to the closed state without console errors.
- P2 — A very wide desktop could stretch detail content excessively after reducing the feed.
  - Fix: the inspector rail still reaches the right workspace edge, while its inner detail card is capped at 920px and centered. At the verified viewport the rail measures 573px, so the cap does not introduce unused space.

No actionable P0, P1, or P2 findings remain.

## Required fidelity surfaces

- Fonts and typography: the existing IconLabs DM Sans hierarchy is preserved; compact card labels remain legible, and disclosure summaries retain a clear heading/meta hierarchy.
- Spacing and layout rhythm: the 12px feed/inspector gap remains stable, the feed is exactly 400px, and the inspector absorbs the remaining width without overlap.
- Colors and visual tokens: existing purple selection, green value, cyan tracking, dark surfaces, and divider tokens are unchanged.
- Image quality and asset fidelity: existing sportsbook logos and Phosphor icons remain sharp; no placeholder or fabricated assets were introduced.
- Copy and content: every play-card value remains present. Market Odds, Market Trend, Why Is This +EV?, and Sharp Odds Used for Fair Value appear in the requested order.

## Interaction and accessibility QA

- Selecting New York Liberty updated the detail content, then returning to Philadelphia Phillies restored the primary state.
- Track toggled to Tracked and back to Track with the correct accessible names and pressed state.
- Market Trend and Line History tabs both changed selected state correctly.
- Both native disclosures opened and closed correctly and start closed after render.
- Browser console: no warnings or errors.

## Automated verification

- Focused Positive EV app tests: 4 passed.
- Full Python suite: 649 passed.
- `node --check static/positive-ev.js`: passed.
- `git diff --check`: passed (line-ending notices only).
- No publish, deploy, commit, or push was performed.

final result: passed

---

# Positive EV — Exact 585px / 400px Columns QA

## Evidence

- Source visual truth: `C:\Users\sport\.codex\visualizations\2026\08\16\01a00b17-7cc8-7132-9b9d-ffffc0547e8e\positive-ev-400px-detail-viewport.png` (1265 × 712).
- Final viewport implementation: `C:\Users\sport\.codex\visualizations\2026\08\16\01a00b17-7cc8-7132-9b9d-ffffc0547e8e\positive-ev-585-400-viewport.png` (1265 × 712).
- Final full-page implementation: `C:\Users\sport\.codex\visualizations\2026\08\16\01a00b17-7cc8-7132-9b9d-ffffc0547e8e\positive-ev-585-400-full.png` (1265 × 1515).
- Same-state comparison: `C:\Users\sport\.codex\visualizations\2026\08\16\01a00b17-7cc8-7132-9b9d-ffffc0547e8e\positive-ev-585-400-comparison.png` (2530 × 746).
- Verified route: `http://127.0.0.1:5097/positive-ev?preview=1`.
- CSS viewport: 1280 × 720 at device pixel ratio 1.
- State: five temporary preview opportunities, Philadelphia Phillies selected, Market Trend selected, and both disclosures closed.

The before and after captures use the same viewport and interaction state and were reviewed together in one side-by-side comparison.
No separate focused crop was needed because both column boundaries and every affected card control are clearly readable in the full-size viewport comparison.

## Comparison history and resolved findings

- P1 — The previous layout used a 400px play column and a 573px detail rail, the inverse of the requested emphasis.
  - Fix: the desktop workspace now uses exact `585px 400px` grid tracks with the existing 12px gap.
  - Post-fix evidence: browser geometry measured every play card at 585px and the expanded detail rail at 400px.
- P2 — The exact 585px + 400px tracks and 12px gap require 997px, while the prior workspace exposed only 985px.
  - Fix: the Positive EV shell's right padding was reduced from 34px to 22px, preserving the 34px left inset and fitting the 997px workspace without overflow.
  - Post-fix evidence: the workspace ends at x=1243 with 22px of right breathing room; no content is clipped.

No actionable P0, P1, or P2 findings remain.

## Required fidelity surfaces

- Fonts and typography: existing IconLabs typography and compact card hierarchy remain unchanged and readable at the new proportions.
- Spacing and layout rhythm: play cards measure 585px, details measure 400px, the inter-column gap remains 12px, and the right inset is 22px.
- Colors and visual tokens: existing purple, green, cyan, dark-surface, and divider tokens are unchanged.
- Image quality and asset fidelity: sportsbook logos and Phosphor icons remain sharp with no replacement assets.
- Copy and content: EV, Track, event, market, selection, stake, payout, odds, Market Odds, Market Trend, and both disclosures remain present.

## Interaction and accessibility QA

- Selecting New York Liberty and returning to Philadelphia Phillies updated the detail rail correctly.
- Track toggled to Tracked and back with the correct accessible state.
- Why Is This +EV? opened and closed correctly; both disclosures finished closed.
- Browser console: no warnings or errors.

## Automated verification

- Focused Positive EV app tests: 4 passed.
- Full Python suite: 649 passed.
- `node --check static/positive-ev.js`: passed.
- `git diff --check`: passed (line-ending notices only).
- No publish, deploy, commit, or push was performed.

final result: passed

---

# Positive EV — Responsive Wide-Screen Rail QA

## Evidence

- Source visual truth: `C:\Users\sport\OneDrive\Pictures\Screenshots\Screenshot 2026-08-18 224728.png` (2287 × 1357).
- Final viewport implementation: `C:\Users\sport\.codex\visualizations\2026\08\16\01a00b17-7cc8-7132-9b9d-ffffc0547e8e\positive-ev-fluid-feed-450-detail-viewport.png` (1265 × 712).
- Final full-page implementation: `C:\Users\sport\.codex\visualizations\2026\08\16\01a00b17-7cc8-7132-9b9d-ffffc0547e8e\positive-ev-fluid-feed-450-detail-full.png` (1265 × 1539).
- Normalized comparison: `C:\Users\sport\.codex\visualizations\2026\08\16\01a00b17-7cc8-7132-9b9d-ffffc0547e8e\positive-ev-wide-responsive-comparison.png` (2530 × 785).
- Verified route: `http://127.0.0.1:5097/positive-ev?preview=1`.
- Browser QA viewport: 1280 × 720 CSS pixels at device pixel ratio 1.
- State: five temporary preview opportunities, Philadelphia Phillies selected, Market Trend selected, and both disclosures closed.

The 2287px source was proportionally normalized to the implementation capture width in the combined comparison so the reported empty-region failure and corrected edge alignment could be judged together. A separate focused crop was unnecessary because the card/detail boundary and right edge are both clearly visible.

## Comparison history and resolved findings

- P1 — Fixed feed and detail tracks occupied only the left side of the wide workspace, leaving a large unused region to the right.
  - Fix: the desktop grid now uses `minmax(0, 1fr) 450px`, so the detail rail stays fixed while the play-card track absorbs all surplus width.
  - Post-fix evidence: at the verified viewport the card track measures 557px, the detail rail measures 450px, and the gap remains 12px. The fractional card track will continue growing with the viewport.
- P1 — The detail rail did not reach the right edge in the expanded view.
  - Fix: the workspace now bleeds through the shell's 34px right inset while preserving the page's left alignment.
  - Post-fix evidence: the detail rail's measured right gap is 0px and its width is exactly 450px.

No actionable P0, P1, or P2 findings remain.

## Required fidelity surfaces

- Fonts and typography: existing IconLabs typography, hierarchy, wrapping, and compact labels remain unchanged.
- Spacing and layout rhythm: the card track is fluid, the inspector is fixed at 450px, the inter-column gap remains 12px, and the inspector reaches the screen edge.
- Colors and visual tokens: existing purple, green, cyan, dark-surface, and divider tokens are unchanged.
- Image quality and asset fidelity: sportsbook logos and Phosphor icons remain sharp; no replacement assets were introduced.
- Copy and content: all play data, Market Odds, Market Trend, and both explanatory disclosures remain present.

## Interaction and accessibility QA

- Selecting New York Liberty and returning to Philadelphia Phillies updated the detail rail correctly.
- Track toggled to Tracked and back with the correct accessible state.
- Sharp Odds opened and closed correctly; both disclosures finished closed.
- Browser console: no warnings or errors.

## Automated verification

- Focused Positive EV app tests: 4 passed.
- Full Python suite: 649 passed.
- `node --check static/positive-ev.js`: passed.
- `git diff --check`: passed (line-ending notices only).
- No publish, deploy, commit, or push was performed.

final result: passed

---

# Positive EV — 20px Inset and Wide Play-Card QA

## Evidence

- Source visual truth: `C:\Users\sport\OneDrive\Pictures\Screenshots\Screenshot 2026-08-18 231109.png` (717 × 520 pixels).
- Browser-rendered implementation: `C:\Users\sport\.codex\visualizations\2026\08\16\01a00b17-7cc8-7132-9b9d-ffffc0547e8e\positive-ev-20px-inset-wide-cards.png` (1728 × 1261 pixels).
- Focused implementation crop: `C:\Users\sport\.codex\visualizations\2026\08\16\01a00b17-7cc8-7132-9b9d-ffffc0547e8e\positive-ev-wide-card-crop.png` (982 × 540 pixels).
- Same-input card comparison: `C:\Users\sport\.codex\visualizations\2026\08\16\01a00b17-7cc8-7132-9b9d-ffffc0547e8e\positive-ev-card-reference-comparison.png` (1719 × 568 pixels).
- Verified route: `http://127.0.0.1:5097/positive-ev?preview=1`.
- CSS viewport: 1743 × 1272 at device pixel ratio 1; browser content raster: 1728 × 1261.
- State: five temporary preview opportunities, Philadelphia Phillies selected, Market Trend selected, and both explanatory disclosures closed.

The source is itself a focused play-card crop, so the comparison places that entire source beside the corresponding implementation region. The full implementation capture separately verifies the card rail, 450px inspector, and screen edge together.

## Comparison history and resolved findings

- P1 — The inspector previously ended flush with the right edge instead of retaining the requested breathing room.
  - Fix: the desktop workspace bleed was reduced by 20px.
  - Post-fix evidence: browser geometry measures an exact 20px right inset, a 450px inspector, a 12px card-to-inspector gap, and zero horizontal page overflow.
- P1 — Expanded cards used a narrow two-row layout rather than the reference's single horizontal information hierarchy.
  - Fix: wide card rails now use a container-driven four-track grid: EV/Track, event, league/market, and selection plus bet controls. Rails below 680px retain the compact two-row fallback so controls cannot overlap.
  - Post-fix evidence: the verified 980px card renders at 96px high with `82px 282.297px 208.656px 405.031px` tracks, zero clipped key text, and all stake, payout, and odds controls visible.
- P2 — The initial wide-card pass used a 96px internal grid row inside a 96px bordered card, producing two hidden overflow pixels.
  - Fix: the internal row was aligned to the 94px content box while retaining the 96px outer card height.
  - Post-fix evidence: `clientHeight` and `scrollHeight` both measure 94px.

No actionable P0, P1, or P2 findings remain.

## Required fidelity surfaces

- Fonts and typography: the reference hierarchy is preserved with a 22px EV value, time above the matchup, league above market, and compact labeled wager metrics; no key text clips.
- Spacing and layout rhythm: cards are 96px high, the inspector is 450px wide, the inter-column gap is 12px, and the right inset is exactly 20px.
- Colors and visual tokens: existing IconLabs purple selection, green value, cyan tracking, dark surfaces, and divider tokens remain unchanged.
- Image quality and asset fidelity: existing sportsbook logos and Phosphor icons remain sharp; no source asset was approximated or replaced.
- Copy and content: EV, Track, event, league, market, selection, Recommended Bet, To Win, and sportsbook odds remain present in the reference order.

## Interaction and accessibility QA

- Track toggled to Tracked and back.
- Selecting New York Liberty updated the detail rail; returning to Philadelphia restored the original play.
- Why Is This +EV? opened and closed; both disclosures finished closed.
- Browser console: no warnings or errors.

## Automated verification

- Focused Positive EV app tests: 4 passed.
- `node --check static/positive-ev.js`: passed.
- `git diff --check`: passed (line-ending notices only).
- Full suite: 647 passed; two unrelated, time-sensitive `test_three_sharp_strategy.py` checks failed because their `now + 1 hour` fixture crossed midnight Eastern and returned `NOT_TODAY`.
- No publish, deploy, commit, or push was performed.

final result: passed

---

# Positive EV — Personal Bet Tracking Modal QA

## Evidence

- Source visual truth: `C:\Users\sport\OneDrive\Pictures\Screenshots\Screenshot 2026-08-19 095703.png` (781 × 646 pixels).
- Browser-rendered implementation: `C:\Users\sport\.codex\visualizations\2026\08\16\01a00b17-7cc8-7132-9b9d-ffffc0547e8e\positive-ev-tracker-modal-full.png` (1728 × 1261 pixels).
- Focused implementation crop: `C:\Users\sport\.codex\visualizations\2026\08\16\01a00b17-7cc8-7132-9b9d-ffffc0547e8e\positive-ev-tracker-modal-crop.png` (775 × 631 pixels).
- Same-input comparison: `C:\Users\sport\.codex\visualizations\2026\08\16\01a00b17-7cc8-7132-9b9d-ffffc0547e8e\positive-ev-tracker-comparison.png` (1576 × 684 pixels).
- Verified route: `http://127.0.0.1:5097/positive-ev?preview=1`.
- CSS viewport: 1743 × 1272 at device pixel ratio 1; browser content raster: 1728 × 1261.
- Rendered dialog: 760 × 615 CSS pixels; focused crop includes a 10px context margin.
- State: first Positive EV play selected; tracker modal open with NoVIG, +118 odds, $84 stake, $0 fees, $99.12 potential profit, and $183.12 total payout.

The source and implementation are both focused desktop modal states. The combined image preserves their near-native dimensions, so the form hierarchy, density, typography, controls, and footer alignment are directly comparable. No additional focused region was needed because all labels and values are legible in the same-input comparison.

## Findings and comparison history

No actionable P0, P1, or P2 differences were found in the first comparison, so no design-QA repair iteration was required.

- Intentional product adaptation: “Track a personal purchase” becomes “Track a sportsbook bet,” cents/shares become American odds/stake, and the cost panel adds potential profit and total payout. These changes preserve the source hierarchy while fitting the sportsbook workflow.
- Intentional design-system adaptation: the Positive EV version uses the existing IconLabs purple focus and primary-action tokens while retaining the source modal’s cyan outline, dark teal fields, compact labels, and two-column rhythm.

## Required fidelity surfaces

- Fonts and typography: the existing IconLabs family, bold 22px title, uppercase eyebrow, compact field labels, and strong value hierarchy closely match the source. Wrapping and truncation remain controlled.
- Spacing and layout rhythm: the 760px dialog preserves the source’s header, two-by-two summary, sportsbook/tag row, three-field wager row, cost panel, explanatory note, and right-aligned actions. The dialog has no internal overflow.
- Colors and visual tokens: dark teal surfaces, cyan border, muted metadata, green payout state, and purple primary action are mapped to existing project tokens with sufficient contrast.
- Image quality and asset fidelity: the source contains no illustrative or photographic asset to reproduce. Existing application icons remain library-rendered and sharp; no placeholder or handcrafted asset was introduced.
- Copy and content: all sportsbook-specific data is explicit, and the note clearly states that tracking writes to Bet Tracker and LabTracker → My Bets without placing a wager.

## Interaction and persistence QA

- Clicking Track opens the modal with the selected play, recommended stake, offered odds, and default sportsbook prefilled.
- Odds, stake, and fees drive the displayed profit, payout, and paid-total calculations.
- Confirming the modal saved one personal bet record and changed the play-card action to Tracked.
- The same saved record appeared in Bet Tracker and in LabTracker with My Bets and Open bets selected.
- Duplicate/opposing exposure confirmation is covered by the endpoint integration test.
- The temporary browser QA bet was removed from active exposure after verification; LabTracker returned to “No open bets.”

## Automated verification

- Full Python suite: 651 passed.
- `node --check static/positive-ev.js`: passed.
- `node --check static/lab-tracker.js`: passed.
- `python -m py_compile app.py lab_tracker.py`: passed.
- `git diff --check`: passed with line-ending notices only.
- No publish, deploy, commit, or push was performed.

final result: passed

---

# Positive EV — Selected-Outline Restoration QA

## Evidence and normalization

- Source visual truth: `C:\Users\sport\OneDrive\Pictures\Screenshots\Screenshot 2026-08-21 103753.png` (2292 × 726 px).
- Reported thin-outline state: `C:\Users\sport\OneDrive\Pictures\Screenshots\Screenshot 2026-08-21 110618.png` (1755 × 634 px).
- Final browser implementation: `C:\Users\sport\Documents\polymarket-whales\design-audits\positive-ev-outline-restoration\01-stronger-outlines.png` (1826 × 1272 px).
- Native-scale focused comparison: `C:\Users\sport\Documents\polymarket-whales\design-audits\positive-ev-outline-restoration\02-reference-vs-stronger-outlines.png` (2714 × 279 px).
- Verified route and viewport: `http://127.0.0.1:5097/positive-ev?preview=1` at 1826 × 1272 CSS px, DPR 1.
- State: Philadelphia Phillies opportunity selected with its selection field and complete play-card outline active.

The focused comparison keeps both 95px-tall cards at native pixel scale and includes 4× nearest-neighbor corner crops for the card and selection outlines. The source card is wider because it was captured from a wide cropped content view; neither border sample is rescaled before the magnified comparison.

## Findings and comparison history

- P2 — The v2 active card used a 1px border at 32% brand opacity and only a 3px left inset, making the complete selected outline read materially thinner than the supplied reference.
  - Fix: raised the active border to the v2 interactive token, increased the left inset to 4px, and added a one-pixel brand-token perimeter plus restrained token-based glow without changing the card's box dimensions.
  - Post-fix evidence: the 4× corner comparison shows the same thick left brand rail and clearly defined full perimeter as the reference; the card remains 993 × 96px.
- P2 — The active selection field used a 1px 52%-opacity border with a faint focus shadow, while the reference has a clearly heavier neon-purple edge.
  - Fix: changed the active field to a 2px `--il-brand-hover` border with layered v2 interactive, focus, and brand-glow tokens.
  - Post-fix evidence: computed selection border is 2px; its outer size remains 142 × 46px and its content does not overflow.

No actionable P0, P1, or P2 findings remain.

## Required fidelity surfaces

- Fonts and typography: unchanged from the approved restoration; no type metric or wrapping changed.
- Spacing and layout rhythm: card and selection outer dimensions are unchanged; the thicker appearance is produced without shifting grid tracks or introducing page overflow.
- Colors and visual tokens: all new outline layers use v2 interactive, brand, focus, and glow tokens; the new navy base remains intact.
- Image quality and assets: sportsbook logos and Phosphor icons are unchanged and remain source assets.
- Copy and content: all play, market, stake, payout, and execution text is unchanged.

## Interaction and automated verification

- Selecting the second play moved the heavier card and selection outline to that row; selecting the first play restored it correctly.
- Exactly one opportunity remained selected throughout the state-change check.
- Browser diagnostics: no warnings or errors.
- Positive EV design-system suite: 7 passed.
- `git diff --check`: passed with line-ending notices only.
- No deploy, commit, or push was performed.

final result: passed

---

# Positive EV — Universal Selection and Hover-Safe Card QA

## Evidence and normalization

- Desired active-card reference: `C:\Users\sport\OneDrive\Pictures\Screenshots\Screenshot 2026-08-21 103753.png` (2292 × 726 px).
- Reported one-selection-only state: `C:\Users\sport\OneDrive\Pictures\Screenshots\Screenshot 2026-08-21 111824.png` (1928 × 782 px).
- Final browser implementation: `C:\Users\sport\Documents\polymarket-whales\design-audits\positive-ev-outline-restoration\04-universal-selection-hover-safe-final.png` (1280 × 720 px).
- Native-scale comparison: `C:\Users\sport\Documents\polymarket-whales\design-audits\positive-ev-outline-restoration\05-universal-outline-comparison.png` (2444 × 214 px).
- Route, viewport, and state: `http://127.0.0.1:5097/positive-ev?preview=1`, 1280 × 720 CSS px, DPR 1, first card selected and hovered.

The comparison keeps all 95px-tall card crops at native scale. Its first row compares the desired active perimeter against the final active perimeter; its second row compares the reported plain inactive selection against the final universal neon selection. Card widths differ because the supplied captures use wider content crops.

## Findings and comparison history

- P1 — The 2px neon selection perimeter was scoped to `.ev-opportunity.active .ev-selection`, so only the selected opportunity received it.
  - Fix: moved the complete border and glow treatment to the base `.ev-selection` component.
  - Post-fix evidence: all four rendered selections compute to the same 2px `--il-brand-hover` border with identical token-based glow, regardless of which card is selected.
- P1 — The active play card still used a 1px physical border with an outer shadow simulating extra thickness, which did not reproduce the supplied full-card perimeter consistently.
  - Fix: replaced the simulated perimeter with a true 2px active border while retaining the 4px internal brand rail and restrained glow.
  - Post-fix evidence: the active card computes to a 2px border on all four sides and remains exactly 96px tall.
- P1 — Hover translated cards upward by one pixel; on the first row, the feed's clipped overflow removed the top edge.
  - Fix: removed hover translation while retaining the hover surface and border-color feedback.
  - Post-fix evidence: the hovered selected card reports `transform: none`, its top remains fixed at 190px, and the browser screenshot retains the complete top border.
- P2 — The narrower desktop breakpoint could overflow the execution grid after the restored full-size controls increased intrinsic width.
  - Fix: raised the responsive execution selectors to the component's specificity so the existing 92px/64px compact selection tracks take effect.
  - Post-fix evidence: every visible card reports `scrollWidth <= clientWidth` at the 1280px browser viewport, and neither the page nor cards overflow horizontally.

No actionable P0, P1, or P2 findings remain.

## Required fidelity surfaces

- Fonts and typography: unchanged; no type metric, wrapping rule, or hierarchy was altered.
- Spacing and layout rhythm: all cards remain 96px tall; the active perimeter no longer depends on movement or a simulated outer line.
- Colors and tokens: universal selection and active card borders use only v2 brand, interactive, focus, and glow tokens.
- Image quality and assets: sportsbook logos and Phosphor icons are unchanged.
- Copy and content: all play, selection, wager, payout, and odds text remains unchanged.

## Interaction and automated verification

- Hovered the first active card using the in-app browser and confirmed the top border remains present.
- Confirmed all four selections share the neon perimeter and all four cards fit their content boxes.
- Browser diagnostics: no warnings or errors.
- Positive EV design-system suite: 7 passed.
- `git diff --check`: passed with line-ending notices only.
- No deploy, commit, or push was performed.

final result: passed

---

# Positive EV — League Watermark Preview QA

## Evidence and normalization

- Visual treatment reference: `C:\Users\sport\OneDrive\Pictures\Screenshots\Screenshot 2026-08-21 113126.png` (986 × 669 px).
- Final browser implementation: `C:\Users\sport\Documents\polymarket-whales\design-audits\positive-ev-league-watermarks\implementation.png` (1280 × 720 px).
- Side-by-side comparison: `C:\Users\sport\Documents\polymarket-whales\design-audits\positive-ev-league-watermarks\comparison.png` (1366 × 478 px).
- Verified route and viewport: `http://127.0.0.1:5097/positive-ev?preview=1` at 1280 × 720 CSS px, DPR 1.
- State: second opportunity selected so the WNBA watermark and selected-card treatment are visible together.

The source is a treatment reference rather than a layout reference. Its partially transparent team logos were adapted into league-specific decorative watermarks behind the existing league and market-type content, while the approved IconLabs card grid and typography remain unchanged.

## Findings and implementation

- P1 — The market-type column previously used only a small generic sport icon, so it did not carry the layered league identity shown in the reference.
  - Fix: added authentic local league artwork as a large, low-opacity watermark behind the league and market text.
  - Post-fix evidence: every rendered MLB and WNBA preview card contains its matching local asset at 12% opacity; the complete mapping also covers ATP, WTA, NBA, NFL, NHL, NCAA, MLS, EPL, UEFA, and FIFA.
- P1 — A decorative logo could otherwise create duplicated accessible names or intercept card actions.
  - Fix: every watermark uses an empty alt value, `aria-hidden="true"`, and `pointer-events: none`.
  - Post-fix evidence: the accessibility snapshot retains only the visible league text, and selecting another opportunity continues to update the expanded panel.
- P2 — The compact desktop market column needs a different watermark scale from the wide layout.
  - Fix: the base watermark is 86px and partially cropped at the right edge; the 1320px desktop breakpoint reduces it to 68px.
  - Post-fix evidence: the 1280px preview has no page overflow, the logo remains clipped inside its own market cell, and the foreground copy remains legible.

No actionable P0, P1, or P2 findings remain.

## Required fidelity surfaces

- Fonts and typography: unchanged; league and market text keep their approved size, weight, line height, and foreground hierarchy.
- Spacing and layout rhythm: no card grid track, row height, or execution-box spacing changed; the watermark is absolutely positioned within the existing market cell.
- Colors and tokens: the original league artwork is preserved and softened only through opacity; the current navy surfaces and purple/green state tokens remain intact.
- Image quality and assets: reused the repository's authentic transparent PNG league assets instead of a letter fallback, generic icon, or recreated trademark.
- Copy and content: league names, market labels, matchup, selection, bet size, payout, and odds are unchanged.

## Interaction and automated verification

- Selected the second opportunity and confirmed its expanded details updated to Las Vegas Aces vs New York Liberty.
- Four visible preview cards produced four matching decorative watermark assets with empty alt text and `aria-hidden="true"`.
- Browser diagnostics: no warnings or errors.
- Positive EV design-system suite: 8 passed.
- `node --check static/positive-ev.js`: passed with the bundled Node.js runtime.
- `git diff --check`: passed with line-ending notices only.
- No deploy, commit, or push was performed.

final result: passed

---

# Positive EV — Full-Height League and Team Matchup Logo QA

## Evidence and normalization

- Watermark treatment reference: `C:\Users\sport\OneDrive\Pictures\Screenshots\Screenshot 2026-08-21 113126.png` (986 × 669 px).
- Previous browser state: `C:\Users\sport\Documents\polymarket-whales\design-audits\positive-ev-team-matchups\before.png` (1280 × 720 px).
- Final browser implementation: `C:\Users\sport\Documents\polymarket-whales\design-audits\positive-ev-team-matchups\final.png` (1280 × 720 px).
- Full-view comparison: `C:\Users\sport\Documents\polymarket-whales\design-audits\positive-ev-team-matchups\comparison.png` (1326 × 335 px).
- Native card-region comparison: `C:\Users\sport\Documents\polymarket-whales\design-audits\positive-ev-team-matchups\focused-comparison.png` (1406 × 456 px).
- Verified route, viewport, and density: `http://127.0.0.1:5097/positive-ev?preview=1`, 1280 × 720 CSS px, DPR 1.
- State: Las Vegas Aces vs New York Liberty selected; all four locally visible team-sport opportunities and their expanded-details response verified.

The supplied screenshot remains a treatment reference rather than a complete layout target. The team matchup order follows the user's explicit visual sequence: first-team logo, shortened first-team name, “vs,” shortened second-team name, and second-team logo.

## Findings and comparison history

- P1 — The earlier 12%-opacity league logos occupied only 68px at the compact desktop breakpoint and did not fill the play-card height.
  - Fix: made the league watermark 100% of the market cell height, retained the approved right alignment, increased opacity to 16%, and removed the compact size reduction.
  - Post-fix evidence: every rendered MLB/WNBA watermark measures 94px high inside the 96px card and remains clipped to its market cell.
- P1 — The original 32 × 32 ATP raster contained an opaque navy square and could not scale cleanly.
  - Fix: rejected an extraction draft that altered the letterforms and replaced it with the official transparent 960 × 284 ATP wordmark; the ATP-only CSS filter presents the mark as white letters.
  - Post-fix evidence: the final ATP asset is RGBA with real alpha, has no opaque background, and renders from a source thirty times wider than the previous file.
- P1 — Matchups were text-only and used full city/team names on two lines.
  - Fix: added authentic 500 × 500 transparent team marks and compact team names for all 30 MLB and 13 WNBA teams. Team-sport cards now render the requested logo/name/vs/name/logo order; tennis keeps the existing player-name treatment because it has no team identity.
  - Post-fix evidence: the four visible team-sport cards produce eight matching logos, preserve the full matchup as the accessible label, and use empty-alt decorative images.
- P2 — The first compact-breakpoint pass left the new matchup unit too compressed.
  - Fix: widened the matchup grid track to 140px, restored 18px team logos and 12px team names, and reduced the score track only enough to preserve the approved execution controls.
  - Post-fix evidence: the focused comparison shows clear separation around “vs” and legible marks without changing row height.
- P2 — The widened compact layout initially produced one pixel of internal card overflow.
  - Fix: reduced the compact score track by two pixels.
  - Post-fix evidence: all four cards and the page report zero horizontal overflow at 1280px.

No actionable P0, P1, or P2 findings remain.

## Required fidelity surfaces

- Fonts and typography: existing fonts, weights, time metadata, EV hierarchy, market type, selection, bet values, and odds are unchanged. Short team names prevent forced city-name wrapping in the new inline matchup.
- Spacing and layout rhythm: cards remain 96px tall; matchups use one inline flex unit, league art fills the market cell vertically, and all grid tracks fit without overflow.
- Colors and visual tokens: the new artwork retains authentic team colors; league opacity is a restrained 16%, and the current navy, purple, and positive-green token system is unchanged.
- Image quality and asset fidelity: all 43 team assets are 500 × 500 RGBA files; the ATP mark is 960 × 284 RGBA. No letter fallbacks, recreated logos, custom SVGs, or low-resolution stretched assets remain.
- Copy and content: team-sport matchups intentionally use shortened team names while the full event title remains available to assistive technology and in expanded details. All wager content is unchanged.

## Interaction and automated verification

- Selected the second opportunity and confirmed the expanded details changed to Las Vegas Aces vs New York Liberty.
- Browser diagnostics: no warnings or errors.
- Positive EV design-system suite: 9 passed.
- Positive EV page/preview integration checks: 2 passed.
- `node --check static/positive-ev.js`: passed with the bundled Node.js runtime.
- `git diff --check`: passed with line-ending notices only.
- No deploy, commit, or push was performed.

final result: passed

---

# Positive EV — Filled Matchup Cell QA

## Evidence

- Treatment reference: `C:\Users\sport\OneDrive\Pictures\Screenshots\Screenshot 2026-08-21 113126.png`.
- Before: `C:\Users\sport\Documents\polymarket-whales\design-audits\positive-ev-filled-matchups\before.png`.
- Final: `C:\Users\sport\Documents\polymarket-whales\design-audits\positive-ev-filled-matchups\final.png`.
- Reference/before/final comparison: `C:\Users\sport\Documents\polymarket-whales\design-audits\positive-ev-filled-matchups\comparison.png`.
- Verified route and viewport: `http://127.0.0.1:5097/positive-ev?preview=1`, 1280 × 720 CSS px.
- State: Las Vegas Aces vs New York Liberty selected so both the play card and its expanded-details response are visible.

## Findings and fixes

- P1 — The game time and matchup shared a vertically centered stack, leaving the logos and names undersized within the event cell.
  - Fix: split the event cell into a centered metadata row and a flexible matchup row; the time is centered at the top and the logo/name/vs/name/logo composition centers within all remaining height.
  - Post-fix evidence: the first event cell is 140 × 94px, its time center differs from the cell center by 0px, and the matchup owns the remaining 60.4px-high row.
- P1 — Compact desktop team marks did not visually fill the matchup cell.
  - Fix: raised compact team marks from 18px to 24px, team names from 12px to 13px, and reduced only the event cell's internal horizontal padding. Larger desktop breakpoints scale to 28px/16px and 34px/18px.
  - Post-fix evidence: every visible matchup reports zero internal horizontal overflow and retains the requested first-logo/name/vs/name/second-logo order.
- P1 — The MLB watermark was right-aligned but did not visually reach the market cell's vertical edges because of transparent padding inside the source artwork.
  - Fix: added MLB-specific sizing at 118% height with a compensating -9% top offset while preserving right alignment and clipping inside the market cell.
  - Post-fix evidence: the rendered MLB image is 110.9px tall inside the 94px market cell, allowing the visible league art to touch the top and bottom without escaping the card.

No actionable P0, P1, or P2 findings remain.

## Required fidelity surfaces

- Fonts and typography: the approved EV, tracking, market, selection, bet, and odds typography is unchanged; only matchup names scale responsively to fill their dedicated cell.
- Spacing and layout rhythm: card height remains 96px, time occupies its own centered top row, and matchup content fills the remaining event-cell height without moving execution controls.
- Colors and visual tokens: no color tokens changed; authentic team colors, purple selection emphasis, green pricing, and the existing league-watermark opacity remain intact.
- Image quality and asset fidelity: the existing 500 × 500 RGBA team marks and high-resolution league assets are reused without stretching or replacement.
- Copy and content: team-sport cards retain compact team names; full event names and all betting content remain unchanged.

## Interaction and automated verification

- Selected the second opportunity and confirmed exactly one active card and an expanded-details heading of “Las Vegas Aces vs New York Liberty.”
- Page horizontal overflow: 0px. All four visible matchup compositions: 0px internal overflow.
- Browser error log: empty.
- Positive EV design-system suite: 9 passed.
- Positive EV page/preview integration checks: 2 passed.
- `node --check static/positive-ev.js`: passed with the bundled Node.js runtime.
- `git diff --check`: passed with line-ending notices only.
- No deploy, commit, or push was performed.

final result: passed
