# IconLabs vs. OddsJam: production, model, and product audit

> This document is the pre-remediation baseline. The completed code pass and
> remaining production gates are tracked in
> [implementation-status-20260831.md](implementation-status-20260831.md).

Audit date: 2026-08-31
Production audited: `https://iconbets-polymarket-wallet-tracker.vercel.app/`
Local implementation reviewed: `mobile-optimizer-ux-20260829`, commit `994b390`

## Executive verdict

IconLabs is not currently an OddsJam replacement. Several of the underlying calculators are thoughtful and their unit tests are healthy, but the live product is still a request-driven collection of tools rather than a continuously running odds platform. The biggest gap is not styling or another filter. It is the data plane.

The production experience currently has four credibility-breaking failures:

1. Live quotes are REST snapshots cached for 30-60 seconds, with cold scans taking 4-15 seconds. This is not sub-second.
2. The Odds Screen advertises a large provider catalog while the audited live rows contained only Polymarket execution options.
3. Arbitrage and Middles hit `RATE_LIMITED` on first use, while Sharp Money returned different states from different requests.
4. Fantasy Optimizer is a line-shopping table, not a slip optimizer, and it can show a green 57.4% play derived from one exact source with 0.05 reliability.

The shortest route to competing is: build a shared streaming ingestion service first, then enforce executable-data rules, then complete Fantasy/Sharp Money/line-history semantics, and only then add more surface features.

## Journey health

| Area | Health | What worked | What prevents an OddsJam switch |
|---|---:|---|---|
| Data pipeline and speed | Critical | OddsEngine and direct exchange adapters exist | 60-second caches, 4-15 second cold loads, request-driven scans, rate limits, no shared quote state |
| Positive EV | At risk | Leave-one-out consensus, 3-source minimum, de-vig options, confidence-adjusted Kelly | Sparse/unavailable production board, stale tolerance, unvalidated weights, no results/CLV proof |
| EV line history | Partial | Real timestamped Pinnacle, Circa, and selected-book observations were plotted | No Pinnacle limits in the audited data, traffic-dependent history, fixed-line price movement is hidden |
| Fantasy Optimizer | Critical | Exact-line comparison and transparent contributions | Not a slip optimizer; one-source green picks; no push/settlement or correlation model; only five DFS apps in the UI |
| Sharp Money | Critical | Direct exchange-depth code paths exist | In-memory serverless state, no Advanced order book in production, price-only rows can remain, inconsistent 0 vs. 51 signals |
| Odds Screen | Critical | Broad catalog and horizontal book comparison UI | Live MLB audit showed only Polymarket quotes; catalog is presented as coverage; 60-second polling |
| Arbitrage | Critical | Multi-outcome math, fee buffer, cent-rounded equalized stakes | First-use rate limit; no shared slate; no hard liquidity/limit enforcement; no quote-skew guard |
| Middles | Critical | Correct window, push-scenario, break-even, and stake calculations | First-use rate limit; no middle probability/EV model; contradictory error/empty states |
| Low Hold | At risk | Correct hold/stake calculations and useful sizing UI | Approximately 15-second load, 542-row dump, negative holds mixed with arbs, weak date/freshness controls |
| Trust and retention | Critical | Cohesive visual identity and methodology details in places | Claims exceed live evidence; no integrated tracking, CLV, calibration, uptime, or independently verifiable performance proof |

## Direct answers

### Is IconLabs faster than OddsJam or sub-second?

No. The audited production implementation cannot honestly claim sub-second updates.

- `/api/positive-ev/live`: 13.8 seconds on the first successful request; later returned a provider-reconnecting error.
- `/api/dfs/lines`: 4.0 seconds.
- active targeted Odds Screen scan: 11.5 seconds.
- Low Hold UI: about 15 seconds before rows appeared.
- Sharp Money: 30-second automatic refresh.
- Positive EV, Fantasy, Odds Screen, Arbitrage, Middles, and Low Hold: generally 60-second refresh payloads.
- `ODDSENGINE_CACHE_TTL_SECONDS` is forced to at least 60 seconds.
- OddsEngine production diagnostics reported REST snapshots, no WebSocket, no order-book support, no Advanced access, and a 60-request quota.

OddsJam publicly claims every-second live refreshes, push feeds, 100+ books, and processing more than one million odds per second. Those are vendor claims, not an independent benchmark, but IconLabs' measured behavior is currently far below even a one-second product target.

### Does the blue line-history graph work?

Partly.

What is working:

- The audited graph rendered real, non-synthetic, timestamped observations.
- For a main-market play it showed the selected execution book plus Pinnacle and Circa. The implementation can also include Bookmaker.eu.
- The selected book is labeled `Compared` and has its own series.
- The example API response contained 42 observations across Circa, FanDuel, and Pinnacle.

What is not working or is misleading:

- All Pinnacle `marketLimit` values in the audited response were null, so no Pinnacle limit line was actually displayed.
- The UI silently omits the limit series instead of saying `Pinnacle limit unavailable from the feed`.
- Player-prop history uses selected book + Pinnacle + FanDuel, not Circa. Circa is therefore not consistently shown across market types.
- History is recorded when the Positive EV endpoint is requested. There is no dedicated always-on quote-history collector, so `throughout the day` depends on scans/user traffic.
- The chart chooses line value when a line exists. A move from -105 to -125 at the same 7.5 line looks flat, even though the price moved materially.
- `Open` means the first observation IconLabs stored, not necessarily the market's true opening line.
- A Pinnacle limit, exchange liquidity, and sportsbook bet limit need distinct typed fields. They are not interchangeable.

Required change: add separate Line, Price, and Limit modes; show an explicit unavailable state; collect every quote continuously; label first-seen vs. market-open correctly; and retain selected book, Pinnacle, Circa, and configurable comparisons for every supported market.

### Are all OddsEngine books and markets actually shown?

No.

- The live Odds Screen response advertised a catalog of roughly 100 providers, but every inspected execution option was Polymarket. MLB showed one actual provider column.
- No audited row contained the expected `all_book_event` structure or an `oddsengine__*` execution option.
- The generic OddsEngine path caps collection at 5 events per league and 20 total events. The Odds Screen currently calls this generic event path instead of the provider's fuller odds-screen path.
- Supported sports are currently limited to NCAAF, NFL, MLB, NBA, NCAAB, NCAAW, WNBA, NHL, EPL, and MLS.
- The normalized market allowlist covers moneyline, spread, total, alternate spread/total, MLB player props, and NBA/WNBA player props. It is not comprehensive across sports, periods, team totals, futures, soccer props, tennis, golf, combat sports, and many other market families.

A provider logo or catalog entry must never count as coverage. Coverage should mean: a fresh, mapped, executable quote was received for that book x sport x market in the last N seconds.

## Detailed findings

### 1. Data architecture and speed

The current provider flow makes one REST event-list request per league and then one odds request per event. A cold scan can consume about 10 league requests plus up to 20 event requests. Multiple serverless instances and tools repeat this work because caches are local to each process. A 60-request provider quota can therefore be exhausted by only a few cold scans.

The target architecture should be:

`OddsEngine streaming/advanced feed + direct exchanges -> always-on ingest workers -> canonical quote bus -> shared Redis/Postgres current-quote store -> materialized EV/arb/middle/low-hold views -> SSE/WebSocket clients`

Every quote needs:

- provider event, market, and selection IDs plus canonical IDs;
- observed-at, provider-updated-at, received-at, and persisted-at timestamps;
- sequence/version ID;
- price, line, status, limit, top-price liquidity, and depth;
- region/account eligibility;
- mapping confidence and settlement rules;
- staleness and source-health state.

Target service-level objectives:

- p50 provider-to-browser latency under 500 ms for streamed sources;
- p95 under 1.5 seconds and p99 under 3 seconds;
- client render under 150 ms after message receipt;
- no executable recommendation from a quote older than the tool-specific cutoff;
- no arb/middle when the two legs' observation times differ by more than 1 second for live or 3 seconds pre-match;
- 99.9% quote-pipeline availability measured independently per source.

### 2. Positive EV

The EV engine has a better foundation than the production experience suggests. It uses leave-one-out fair prices, a three-source minimum, four de-vig methods, outlier clipping, confidence-adjusted fractional Kelly, event exposure caps, fee buffers, and execution-capacity fields.

Critical model gaps:

1. A source or execution quote with no timestamp is still accepted. It gets a warning rather than becoming non-executable.
2. Source quotes may be ten minutes old and execution quotes three minutes old. That is far too stale for an actionable odds product.
3. Weights are global hard-coded values: Pinnacle 35, Circa 28, Bookmaker.eu 28, Betfair 7, FanDuel 2. There is no demonstrated calibration by sport, market, time to start, line range, or liquidity regime.
4. `fairConfidence` is a heuristic, not a calibrated probability interval. A user cannot tell whether +2% EV is distinguishable from noise.
5. Depth fields exist, but EV is calculated at the top price. It does not calculate a stake-specific blended execution price through order-book levels.
6. Portfolio control caps only individual bets and aggregate event exposure. It does not constrain correlated players, alternate lines, same-game outcomes, team/league exposure, or book/account exposure.
7. There is no production proof loop: no auto-grading, CLV, calibration curve, Brier/log loss, ROI by decile, or source-ablation dashboard.
8. Sparse data and provider errors produce empty boards instead of last-known plays with a visible age and disabled execution.

To beat OddsJam, ship source-specific backtests and let users inspect them. Recommended filters should be learned from out-of-sample CLV/results and versioned, not asserted.

### 3. Fantasy Optimizer

The current name overpromises. The page is an exact-line fair-odds comparison table with configurable source weights and a static `Best Parlay Type` guide. It does not build or optimize a slip.

Observed example:

- Ian Seymour Under 6 strikeouts;
- 57.4% displayed hit rate and -134 fair odds;
- one exact source, ProphetX;
- model reliability 0.05;
- many other books excluded because their lines were 5.5 or 6.5.

That row should not be green or presented as a top play. One source is permitted because `minimum_sources = 1`. The reliability indicator does not stop qualification.

Required modeling additions:

1. Require at least three independent exact-line sources for a green play, or two sharp sources plus a validated projection model. One source should be gray/watch-only.
2. Model app-specific push/tie/reboot, overtime, dead-heat, stat-correction, and void rules. A two-way sportsbook Under 6 market includes push probability; it cannot be treated as a DFS binary win probability without settlement adjustment.
3. Build an actual slip optimizer: pick count, payout table, flex/all-in structure, expected return distribution, joint hit probability, maximum downside, and recommended stake.
4. Model same-game/player/team correlations. Multiplying marginal hit rates will overstate a slip's probability.
5. Add exposure constraints, duplicate-player rules, app-specific restrictions, and portfolio generation for multiple slips.
6. Calculate payout-specific EV for every offered slip type rather than using a single equivalent per-leg odds reference.
7. Pull live DFS board availability, not just sportsbook comparables, and disable entries that no longer exist.
8. Add injuries, starters, scratches, projected minutes/usage, weather, lineups, and stat-model context.
9. Calibrate hit rates by sport/stat/line/source count and publish reliability bins.
10. Expand beyond the five selectable UI apps. OddsJam currently advertises 16.

UX issues:

- The primary desktop grid is extremely wide and important controls clip/require horizontal scrolling.
- Row expanders use button-like rows containing links, creating invalid nested interactive behavior for keyboard and assistive-technology users.
- Drag-only column reordering needs keyboard controls and a column manager.
- A slip drawer with chosen legs, correlation warnings, EV, payout, and `open in app` actions should be the page's central object.

### 4. Sharp Money

The product currently conflates three levels of evidence:

1. verified executable order-book depth;
2. exchange top-price liquidity;
3. price-only sportsbook comparisons.

Only the first two can support a directional-liquidity claim, and neither proves sportsbook handle/ticket percentages. Production diagnostics reported no OddsEngine Advanced/order-book/WebSocket access. The direct API returned 51 cached signals while the browser instance showed zero, which is consistent with the collector's histories and previous snapshots being held in serverless process memory.

Required changes:

- persist collector state and history in a shared store;
- require verified two-sided depth for a `Sharp Money` signal;
- move price-only rows to `Market movement` and never rank them as flow;
- show exchange, side, exact depth, price levels, net imbalance, crossed retail line, and observation age;
- separate market limit from available liquidity throughout the schema;
- add steam/reverse-line-movement detection with explicit evidence;
- validate signal thresholds against subsequent line movement and closing price;
- add alerts, saved filters, and one-click execution links;
- show when Advanced data is unavailable instead of implying equivalent evidence.

OddsJam's current public Sharp Money proposition is unusually clear: detect unusually large exchange liquidity, find the corresponding side at a retail book, show liquidity, compare every book, auto-refresh, and retain line history. IconLabs needs the same causal clarity and stronger proof, not just more signals.

### 5. Odds Screen

The audited screen is not production-ready as a line-shopping product.

- Initial all-sports rows were mostly Polymarket-only esports/tennis markets.
- Selecting MLB still showed only a Polymarket quote column.
- A +99900 price was displayed, indicating missing odds sanitation.
- `Best` and `Average` were identical because only one provider was present.
- The page says `Compare odds across sportsbooks in real time`, but polls REST snapshots every 60 seconds and stores a ten-minute local payload.

Required changes:

1. Fix the backend merge/deployment path so real OddsEngine book options survive into the live response.
2. Use the provider's full odds-screen slate path, not the 5-per-league/20-total EV path.
3. Build a live coverage matrix and hide catalog-only books by default.
4. Reject impossible prices and malformed markets at normalization time.
5. Add freshness/status per cell: live, stale, suspended, removed, error.
6. Stream cell deltas; flash changes without redrawing the table.
7. Add best-price and consensus sorting, custom weighted consensus, hold, fair price, and difference-from-sharp columns.
8. Add book pinning, column groups, saved layouts, virtualization, and compact mobile market cards.
9. Default into a current popular league/date instead of a 1,700-row mixed slate.
10. Add line movement, opening/current/closing comparison, alerts, injuries, scores, clock, weather, and period state.
11. Add complete market taxonomy and coverage for periods, team totals, alternate/player/team props, futures, soccer, tennis, golf, combat sports, and supported international leagues.

### 6. Arbitrage

The calculator correctly supports complete multi-outcome markets, not only two-way markets. It also applies an exchange commission buffer and rounds stakes to cents. Those are real strengths.

Production and execution gaps:

- the page hit `RATE_LIMITED` on first use;
- missing timestamps are allowed with a warning;
- no maximum cross-leg quote skew is enforced;
- stake sizing does not hard-enforce per-book limits, top-price liquidity, depth slippage, minimum/maximum bet, balance, currency, or rounding rules;
- distinct books are optional rather than the safe default;
- there is no state/region/account eligibility model;
- there is no execution-order/race-risk score;
- no last-known opportunity remains visible during an upstream outage;
- no one-click betslip workflow, tracking, or post-bet confirmation exists.

An arb is only `Guaranteed` after fees, limits, depth, settlement equivalence, timing, and executability are verified. Rename the current status to `Theoretical` until all gates pass.

### 7. Middles

The deterministic calculations are good: the code identifies windows, sizes the two legs to equalize outside payouts, reports push scenarios, computes middle payoff and break-even middle probability, and includes exchange commission buffers.

The major missing feature is an estimate of the probability of landing inside the window. The code explicitly invents no probability, which is honest, but this means it cannot rank middles by expected value.

Add:

- sport/league/market-specific score distributions;
- NFL/NCAAF key-number probabilities and push rates;
- NBA/WNBA margin/total distributions conditioned on the market;
- player-prop discrete distributions;
- estimated middle probability with confidence interval;
- expected value, worst case, capital required, and annualized/turnover return;
- settlement compatibility and quote-skew gates;
- historical hit-rate and calibration by window type.

The audited UI also displayed `RATE_LIMITED`, `Ready`, and `No middles match these filters` simultaneously. Errors, genuine empty results, and paused scans must be mutually exclusive states.

### 8. Low Hold

Low Hold was the healthiest opportunity page in the live audit and eventually returned 542 rows with usable stake sizing. It also surfaced a -1.30% hold, which is actually an arbitrage opportunity.

Required changes:

- route negative holds to Arbitrage and deduplicate across tools;
- keep Low Hold focused on 0% to the configured loss ceiling;
- add event-date and time-to-start filters; audited results mixed near-term MLB with October NBA;
- enforce hard freshness, limit, liquidity, fee, and quote-skew gates;
- paginate/virtualize rather than rendering hundreds of rows at once;
- show dollars lost per $1,000, rewards/VIP value, and effective net value after rewards;
- add locked-first-leg workflows for promo rollover and account balances;
- retain last-known rows with age when refresh fails.

### 9. Trust, results, and reasons users would not switch

OddsJam's moat is not just math. Its public product bundles alerts, one-click tracking, auto-grading, CLV, large coverage claims, coaching/community, mobile access, and visible social proof. IconLabs currently asks the user to trust a recommendation without an equally complete proof loop.

Reasons a serious user would not switch today:

1. They cannot trust availability: first-use waits, rate limits, and contradictory states are common.
2. They cannot verify coverage: logos/catalog entries appear even when no live quote exists.
3. They cannot verify speed: the product is demonstrably not sub-second.
4. They cannot verify edge: no audited CLV, calibration, or out-of-sample ROI is attached to model versions.
5. They cannot finish the workflow: Fantasy does not build slips; betting tools lack a unified tracker and post-bet lifecycle.
6. They cannot distinguish executable from theoretical opportunities reliably.
7. Marketing claims such as `50+ sportsbooks`, `real-time`, ratings, and winner counts are not supported inside the product by transparent evidence.
8. Repeated/duplicated testimonials weaken trust and create compliance risk if not independently sourced.

## Prioritized fix list

### P0 - block launch/paid acquisition

1. Replace request-triggered OddsEngine scans with an always-on central ingest service.
2. Upgrade to OddsEngine Advanced/WebSocket/push access or add a feed that can meet the latency target.
3. Put current quotes, provider health, histories, and opportunity views in shared Redis/Postgres state.
4. Stream deltas to browsers with SSE/WebSockets; remove 30-60 second page polling as the primary transport.
5. Fix the production Odds Screen merge so actual all-book quotes reach the UI.
6. Remove catalog-only book columns and replace headline book counts with verified live coverage.
7. Reject missing/stale timestamps for execution; enforce quote-age and cross-leg-skew limits.
8. Split global app health from each odds feed/tool. Stop showing `Connecting live data` from unrelated tracker health.
9. Return last-known data plus age during upstream failures; never replace a useful board with a spinner/error.
10. Create a dedicated continuous line-history collector independent of page traffic.
11. Either ingest real Pinnacle limits or explicitly say unavailable; do not imply the limit line is present.
12. Convert Fantasy into a real slip optimizer or rename it `Fantasy Line Shopping` until it is one.
13. Make one-source Fantasy results watch-only and implement settlement/push adjustments.
14. Persist Sharp Money state and require verified depth for Sharp Money classification.
15. Add production integration tests for quote coverage, latency, provider quota, deployment revision, and cross-instance consistency.

### P1 - make the models defensible and executable

16. Backtest EV source weights by sport, market, time to start, and liquidity regime.
17. Publish model-version calibration, CLV, ROI by EV decile, Brier score/log loss, and confidence intervals.
18. Calculate stake-specific EV through exchange depth and respect sportsbook/exchange capacity.
19. Add correlated portfolio exposure limits across events, teams, players, alternates, and books.
20. Add live saved filters and push/SMS/email/Slack/Discord notifications.
21. Add a unified betslip/tracker with one-click add, auto-grade, CLV, P&L, and model-version attribution.
22. Complete Fantasy payout, flex, joint-probability, correlation, and multi-slip portfolio optimization.
23. Add app-specific DFS settlement rules and live app-board availability.
24. Add verified injury, lineup, weather, score, clock, and live-state context.
25. Separate Sharp Money, market movement, steam, reverse line movement, and price-only signals.
26. Add a probability/EV layer to Middles with key-number and discrete-stat models.
27. Add liquidity/limit/depth/min-max bet/account-region gates to Arbitrage, Middles, and Low Hold.
28. Make distinct-book arbitrage the default and validate settlement equivalence.
29. Route negative holds to Arbitrage; deduplicate the same opportunity across all tools.
30. Expand sport and market adapters based on an explicit customer coverage roadmap.
31. Sanitize extreme odds and quarantine mapping anomalies before they reach users.
32. Add Price/Line/Limit chart modes, true open vs. first-seen labels, and configurable comparison books.

### P2 - beat OddsJam on product quality, not parity

33. Show a public real-time coverage and latency status page by provider/book/market.
34. Give every recommendation an evidence drawer: source books, freshness, dispersion, limit/depth, model version, uncertainty, and exclusion reasons.
35. Add execution probability/race-risk and `still available` revalidation before the user clicks out.
36. Build custom consensus presets and shareable professional workspaces.
37. Add line-move alerts, market-posting alerts, injury alerts, and closing-line alerts.
38. Add bankroll/account balances and recommended allocations across books.
39. Add historical replay/backtest mode so users can inspect what the tool would have shown at any timestamp.
40. Add mobile-native compact workflows and persistent notifications.
41. Virtualize large boards and support saved column layouts, keyboard reordering, and screen-reader summaries.
42. Fix nested interactive table rows, focus handling, color-only status signals, and wide-grid keyboard navigation.
43. Replace unverified/repeated testimonials and headline counts with sourceable, date-bounded evidence.
44. Add onboarding that verifies location/books/accounts and configures only executable opportunities.
45. Add support/community/coaching only after the data and proof foundation is reliable.

## Validation plan before claiming parity

Do not claim `faster than OddsJam` until a neutral test harness records the same books/markets on both products for at least seven full days.

Measure:

- provider change timestamp to UI appearance;
- p50/p95/p99 update latency;
- quote recall and precision against direct sportsbook observations;
- stale/suspended quote rate;
- arb false-positive and successful-execution rate;
- EV calibration, CLV, and ROI by decile;
- Fantasy calibration and realized slip EV by app/type;
- Sharp Money signal precision for subsequent line movement;
- uptime, empty-board minutes, rate-limit incidents, and cross-instance disagreement.

Release gates:

- zero catalog-only coverage claims;
- zero executable recommendations with missing timestamps;
- less than 0.5% stale executable cells;
- at least 95% of streamed changes visible within the latency SLO;
- 30 days of versioned, reproducible production telemetry;
- model results independently reproducible from stored quotes and settlements.

## Evidence and limitations

The audit combined live production walkthroughs, API timing/response inspection, current source review, and targeted automated tests. All 110 selected EV, DFS probability, OddsEngine, Arbitrage, Middles, Low Hold, and Sharp Money unit tests passed in 17.32 seconds. That is good evidence for isolated calculator behavior, but it also demonstrates the missing test layer: production feed, serverless-state, quota, deployment, latency, and actual-coverage failures are not caught by those tests.

The OddsJam comparison uses its current public product pages, not an authenticated paid account. Its speed and coverage numbers are marketing claims and should be independently benchmarked before being treated as fact.

Public comparison sources:

- [OddsJam Odds Screen](https://dev.oddsjam.com/odds-screen)
- [OddsJam odds/API feed](https://oddsjam.com/odds-api)
- [OddsJam Positive EV](https://oddsjam.com/betting-tools/positive-ev)
- [OddsJam Fantasy Optimizer](https://fantasy.dev.oddsjam.com/optimizer)
- [OddsJam Sharp Money](https://oddsjam.com/betting-tools/sharp-money)
- [OddsJam Middles](https://oddsjam.com/betting-tools/middles)
- [OddsJam betting tools](https://dev.oddsjam.com/betting-tools)

## Captured production evidence

- `01-positive-ev.png` - waiting for first refresh
- `02-positive-ev-late-state.png` - one loaded EV row
- `03-positive-ev-line-history.png` - selected book/Pinnacle/Circa history
- `04-fantasy-optimizer.png` - one-source 57.4% example and wide grid
- `05-sharp-money.png` - zero-market browser state
- `06-odds-screen.png` - initial Polymarket-heavy slate
- `07-odds-screen-mlb.png` - MLB with only Polymarket quotes
- `08-arbitrage.png` - first-use rate limit
- `09-middles.png` - contradictory rate-limit/ready/empty state
- `10-low-hold.png` - loading state
- `11-low-hold-final.png` - 542-row final state
