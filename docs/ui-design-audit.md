# IconLabs UI design audit

## Authoritative presentation surfaces

- `templates/base.html` owns the shared application shell, product identity, primary navigation, system status, and account dialog.
- `templates/trades.html` owns Prediction Traders controls, filters, workspaces, and initial loading/empty states.
- `templates/odds_screen.html` owns the Sportsbook Screen filters, provider selector, sticky grid shell, and initial loading state.
- `static/app.js` owns rendered trade rows, selected-trade intelligence, provider execution controls, sportsbook price cells, error/empty states, and data-driven state transitions.
- `static/style.css` contains the legacy visual rules. It has accumulated several overlapping redesign layers and breakpoint overrides.

## Findings

1. The visual hierarchy is distributed across repeated late-file overrides rather than a single semantic token layer.
2. The shell uses very small typography and control heights at common desktop widths, which makes the product feel zoomed out.
3. Healthy system status is visually as prominent as primary task controls.
4. The Prediction Traders header does not explain the page purpose and the workspace lacks a useful model-activity state before selection.
5. Trade rows expose many metrics at the same visual weight, reducing scanability.
6. The Sportsbook Screen uses strong blue row fills and repeated unavailable copy, creating a database-grid appearance.
7. Provider price states are not visually differentiated for best, stale, suspended, missing exact market, or unknown liquidity.
8. Loading, error, and empty states occupy large blank regions without enough operational context.
9. Desktop and mobile rules are present, but multiple competing breakpoint layers make control sizing and spacing inconsistent.
10. Phosphor Icons already provides a consistent accessible icon family and can be retained.

## Refactoring decision

Keep the existing templates, routes, APIs, data contracts, and event bindings. Add one final, centralized `static/design-system.css` layer containing semantic tokens and component primitives. Make only structural template additions that provide missing hierarchy and data slots. Update renderer markup only where a presentation state needs a semantic class or accessible tooltip.

## Data and logic boundary

No recommendation formula, Candidate Ledger logic, market mapping, provider adapter, Kelly sizing, wallet logic, tracking logic, route, or API response is changed by this refinement.
