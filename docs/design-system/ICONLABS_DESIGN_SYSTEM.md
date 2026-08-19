# IconLabs design system — canonical v1

Prediction Traders is the visual source of truth for this opt-in system. The
tokens and primitives below were extracted from the approved running page; they
are not a new palette or a restyle of the rest of IconLabs.

## Pre-refactor inventory

The Prediction Traders route was powered by `templates/base.html`,
`templates/trades.html`, `static/app.js`, `static/design-system.css`,
`static/stage2-trades.css`, and the legacy `static/style.css` layer. The page
already had a strong route boundary (`body[data-page="trades"]`) but its
foundation values were repeated between page rules and component rules.

Before extraction:

- `stage2-trades.css` contained 2,467 lines, seven same-context duplicate
  selectors, 32 non-token color literals, three `!important` declarations,
  an undefined focus-ring alias, and several dead preview/legacy selectors.
- `app.js` mixed reusable provider, metric, quote, chart, and state markup with
  the page renderer, and also contained a client-only five-trade visual preview.
- the approved page still depended on the legacy stylesheet for the application
  shell, dialogs, account controls, and a small number of shared utilities.
- the temporary preview badge and purple preview-border rules were not part of
  production data behavior and were safe to remove.

## Canonical tokens

All canonical values live in `static/design-system.css` under `:root`. The page
opts in with `data-design-system="v2"`; pages not yet migrated keep their
existing styling.

### Color

| Role | Token | Approved value |
| --- | --- | --- |
| App / workspace | `--il-bg-app`, `--il-bg-workspace` | `#030a11` |
| Sidebar | `--il-bg-sidebar` | `#06111a` |
| Primary surface | `--il-surface-1` | `#07131c` |
| Secondary surface | `--il-surface-2` | `#0a1822` |
| Elevated / hover | `--il-surface-elevated`, `--il-surface-hover` | `#0d1d28`, `#0d202b` |
| Selected | `--il-surface-selected` | `rgba(141, 68, 246, .08)` |
| Borders | `--il-border-subtle`, `--il-border-standard` | `rgba(83, 126, 151, .2)`, `rgba(83, 126, 151, .34)` |
| Primary / secondary / muted text | `--il-text-primary`, `--il-text-secondary`, `--il-text-muted` | `#f5f7fa`, `#b4becc`, `#7d899a` |
| Brand | `--il-brand`, `--il-brand-hover`, `--il-brand-strong` | `#8d44f6`, `#9e5cff`, `#7427e6` |
| Positive / negative / warning | `--il-positive`, `--il-negative`, `--il-warning` | `#50d977`, `#ff5b70`, `#e9b85e` |
| Chart | `--il-chart-history`, `--il-chart-trader`, `--il-chart-current`, `--il-chart-grid` | purple, warning, positive, subtle border aliases |

The same file also records the approved subtle state fills, focus colors,
backdrops, shadows, and scrollbar colors so components do not hard-code them.

### Typography

DM Sans remains the UI and numeric-data family. The extracted roles are:

| Role | Token | Approved value |
| --- | --- | --- |
| Page title | `--il-type-page-title` | 700 / 28px / 1.12 |
| Section title | `--il-type-section-title` | 700 / 18px / 1.12 |
| Card title | `--il-type-card-title` | 700 / 16px / 1.25 |
| Primary metric | `--il-type-primary-metric` | 700 / 30px / 1 |
| Body | `--il-type-body` | 400 / 14px / 1.45 |
| Metadata | `--il-type-metadata` | 500 / 13px / 1.2 |
| Micro label | `--il-type-micro-label` | 650 / 12px / 1.2 |
| Table header | `--il-type-table-header` | 650 / 10.5px / 1.2 |
| Numeric / odds | `--il-type-numeric-data` | 700 / 19px / 1.2 |
| Sidebar navigation | `--il-type-sidebar-nav` | 600 / 14px / 1.2 |
| Controls | `--il-type-control` | 600 / 13px / 1.2 |

Responsive type adjustments remain page-scoped where the approved mobile
composition differs (for example, 24px page titles and 22px confidence scores).

### Layout and interaction

- spacing scale: 0, 4, 8, 12, 16, 20, 24, 32, 40, and 48px
- radii: 4px small, 7px controls, 9px panels, 12px overlays
- controls: 44px standard, 34px compact, 32px tab
- icons: 16px small and 18px medium
- desktop gutter: 18px
- sidebar: 232px
- desktop header: 78px (responsive wrapping is preserved at 1440 and mobile)
- detail panel: 450–480px desktop, 420px at the compact desktop breakpoint
- opportunity card: 112px desktop
- motion: 140ms fast and 180ms standard
- focus: 2px `--il-focus` outline plus the approved soft focus shadow
- layers: content, sticky, popover, backdrop, account drawer, detail drawer,
  tooltip

## Shared component contracts

These classes are intentionally small, composable contracts. Page-specific
grid placement and breakpoint behavior remain in `stage2-trades.css`.

| Component | Contract |
| --- | --- |
| Application shell / sidebar / nav item | opt-in `body[data-design-system="v2"]` shell and navigation rules |
| Page header | `.il-page-header`, `.il-page-title` |
| Tabs / segmented control | existing workspace-tab contract backed by shared control tokens |
| Search and finance controls | existing semantic controls plus `.il-finance-controls` |
| Buttons / icon buttons | existing native button contracts backed by control, radius, focus, and motion tokens |
| KPI summary | `.il-kpi-strip`, `.il-kpi-metric` |
| Filters | `.il-filter-bar` |
| Confidence | `.il-confidence-display` |
| Executable quote | `.il-executable-quote` |
| Provider identity / row | `.il-provider-logo`, `.il-provider-list`, `.il-provider-head`, `.il-provider-row`, and cell hooks |
| Metric group | `.il-metric-group`, `.il-metric` |
| Detail section | `.il-detail-section` |
| Chart | `.il-chart-container` |
| Loading / empty / error / stale | `.il-state`, `.il-state-loading`, `.il-state-empty`, `.il-state-error`, `.il-state-stale` |
| Tooltips | `.il-tooltip-trigger`, `.il-tooltip-bubble` |

One-off Prediction Traders composition—opportunity-row grid, Signal Activity,
detail drawer choreography, and route-specific evidence order—remains page
specific. It was not abstracted merely because a wrapper existed.

## Page archetypes

### Master/detail

Applies to Prediction Traders, Positive EV, Sharp Money, and Live Positions.
Use the opt-in application shell, page header, tabs/search/finance controls, KPI
strip, filters, selection list, detail sections, provider rows, metrics, charts,
and standard states. Keep each page's row schema, selection semantics, evidence
order, and business logic local.

### Data table

Applies to Fantasy Optimizer, Sportsbook Screen, Sharp Wallets, and Bet History.
Use the shell, page header, filters/search, table-header typography, provider
identity, numeric data, buttons, focus contract, and standard states. Do not
force master/detail card geometry onto dense tabular workflows.

### Analytics dashboard

Applies to Bet Tracker, LabTracker, Intelligence, and Edge Map where its
information architecture fits. Use the shell, page header, KPI strip, metric
groups, chart containers, filters, and standard states. Dashboard grids and
chart domains remain feature-specific; the shared chart container does not
change data logic.

## Isolation and remaining legacy dependencies

- Only Prediction Traders loads the canonical design-system and page stylesheet
  contract today. No other IconLabs page was migrated.
- `static/style.css` remains loaded for the legacy shell, modal/account
  behavior, and utilities still shared by unmigrated pages.
- `static/app.js` is still a monolithic application bundle. The reusable markup
  contracts are separated semantically, but moving them into JavaScript modules
  should wait for a behavior-focused refactor.
- Jinja base-template structure, Phosphor icons, provider image assets, and the
  existing session/API contracts remain dependencies.

## Positive EV implementation plan (not implemented)

1. Freeze Positive EV at the same three viewports and inventory its live data,
   states, and unique interactions.
2. Classify it as master/detail and map only compatible shell, header, control,
   filter, KPI, provider, metric, chart, and state contracts.
3. Preserve its row schema, value calculations, filters, and detail evidence;
   do not copy Prediction Traders opportunity content or business logic.
4. Opt the route into the canonical tokens at the page boundary, migrate one
   component group at a time, and keep its legacy CSS isolated until replaced.
5. Compare baseline and post-migration at 1920, 1440, and 390px, fix any visible
   drift, run route and full regression tests, and request approval before the
   next page.
