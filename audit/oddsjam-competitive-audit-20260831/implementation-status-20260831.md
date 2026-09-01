# OddsJam remediation implementation status

Status date: 2026-08-31
Scope: IconLabs codebase, including OddsEngine-backed ProphetX read-only data
Baseline: [oddsjam-competitive-audit.md](oddsjam-competitive-audit.md)
Product map: [Figma implementation board](https://www.figma.com/board/25lzERsrJL0atAAY6kae6J)

## Honest release verdict

The identified code-side correctness, safety, persistence, and core workflow
gaps are implemented and covered by the repository test suite. This does not
establish OddsJam parity yet. The owner reports that the custom trial key has
Advanced entitlements for WebSocket, Pinnacle limits, and NoVIG/ProphetX full
order books. The public OpenAPI confirms those capabilities, but its referenced
`docs/WEBSOCKET_API.md` protocol is not publicly retrievable. Streaming,
production credential validation, observed coverage, and multi-day comparative
telemetry remain external or deployment-dependent.

No page may claim sub-second updates, complete book/market coverage, or faster
performance than OddsJam until the production release gates at the end of this
document pass.

## Tool-by-tool status

| Area | Implemented in this pass | Still required outside this code pass |
|---|---|---|
| Shared odds foundation | Strict provider timestamps, future-skew rejection, odds bounds, typed capacity, durable cross-instance snapshots, provider health, last-known verified payloads, minute reconciliation job | Always-on ingest service and a streaming/push feed |
| Positive EV | Three-source minimum; leave-one-out fair price; 90s execution age, 120s source age, 3s skew; missing eligibility/capacity/rules block execution; stake becomes zero when blocked; event/book/player exposure caps; durable degraded state | Calibrated sport/market weights, production CLV/results proof, live account eligibility and limits |
| EV line history | Selected book + Pinnacle + Circa + Bookmaker; real timestamped observations only; Line/Price/Limit modes; first-seen wording; explicit Pinnacle-limit unavailable state; scheduled collection; `/v1/linehistory` price/line points merge with local limit observations using OddsEngine event/selection/series IDs | OddsEngine line-history points do not document historical limits, so limits must continue to be captured locally; production history must accumulate after deployment |
| Fantasy Optimizer | Payout-aware slip builder and optimizer; exact Poisson-binomial distribution; deterministic correlated Monte Carlo when explicit correlations exist; push/void outcomes; reduced-pick payout tables; unique-player constraint; live payout/rule confirmations; one-source watch-only; two-sharp or three-source evidence gate | Live app payout/rule feeds, injuries/lineups/projections, validated correlation inputs, broader app inventory from the provider |
| Sharp Money | Durable collector state; depth/top-liquidity/price-only evidence classification; Advanced REST enabled by default; `/v1/orderbook/top` requests both NoVIG and ProphetX; price-only data cannot masquerade as verified flow; keyboard comparison ordering | Live key entitlement and returned two-sided depth still require a production smoke test; tick-level streaming awaits the missing protocol |
| Odds Screen | Uses the broad screen loader; unfiltered scans preserve every observed OddsEngine market via wildcard normalization; observed books only; no catalog-only provider columns; book x market coverage matrix; malformed odds rejection; explicit REST/snapshot transport status; keyboard column ordering | Current model maps ten league keys; additional leagues need adapters; standard REST remains 60-second UI polling; observed completeness depends on live credentials and quota |
| Arbitrage | Distinct books by default; 90s age and 3s cross-leg skew; fees; per-leg capacity, account, settlement, and timestamp gates; maximum executable stake; theoretical vs executable state; durable fallback | Live book limits, balances, eligibility, and settlement-rule IDs must arrive from providers; no automated multi-book bet placement |
| Middles | Distribution-based middle probability and EV; push/middle/outside scenarios; execution gates; quote skew; durable fallback; mutually exclusive empty/error states | Production calibration by sport/market/key number and provider settlement metadata |
| Low Hold | Negative holds route to Arbitrage; execution gates; 48-hour default; progressive 100-row rendering; durable fallback; typed liquidity vs limits; modeled/verified wording | Rewards/VIP economics and live account balances if these are product requirements |
| Accessibility/performance | Removed nested interactive DFS rows; explicit expand buttons; Alt+Arrow column ordering; large Low Hold board no longer renders hundreds of rows at once; mobile Fantasy slip drawer | Full assistive-technology audit with real populated production states |

## New or materially changed interfaces

- `POST /api/dfs/slips/evaluate`
- `POST /api/dfs/slips/optimize`
- `GET /api/odds/coverage`
- `GET /api/providers/odds-engine/books`
- `GET /api/providers/odds-engine/orderbook`
- `GET /api/positive-ev/line-history` now merges OddsEngine Advanced history
  with locally captured limit/liquidity observations
- `GET /api/odds-screen` now reports observed-only coverage and transport truth
- Arbitrage, Middles, Low Hold, DFS, and Positive EV payloads expose execution
  status/summary rather than treating mathematical rows as executable
- Durable odds-tool state migration `008_odds_tool_state` exists for SQLite and
  Postgres
- Vercel reconciliation cron records line history and durable verified state

## Line-chart acceptance criteria

The chart implementation now satisfies the code-side requirement when the feed
contains the data:

1. The play's selected book is requested and marked `Compared`.
2. Pinnacle, Circa, and Bookmaker are requested for the same exact canonical
   event, market, selection, side, period, line, and alternate status.
3. Provider timestamps are used; no synthetic chart points are created.
4. Line, American price, and market limit are distinct metrics.
5. Pinnacle limit is a separate dashed series only when at least two real limit
   observations exist.
6. A missing Pinnacle limit is displayed as `Unavailable`, not inferred from
   liquidity or a sportsbook limit.
7. `First seen` is not labeled as the market's true opening line.

Therefore the graph logic is repaired. Historical price and line changes can
come from OddsEngine directly, while a visible Pinnacle-limit line still
depends on the collector storing repeated real `limit` observations because
the documented `/v1/linehistory` points omit that field.

## Coverage acceptance criteria

The Odds Screen no longer equates a configured logo/catalog entry with live
coverage. A book is present only when a row contains an observed quote from it.
The coverage API reports each observed provider x market cell with quote and
executable-quote counts.

Opportunity engines intentionally remain allowlisted. The Odds Screen preserves
new/unlisted market families for comparison, while EV/Arbitrage/Middles/Low Hold
exclude market types that do not yet have safe canonical settlement logic.

## Speed acceptance criteria

Current code reports `rest_snapshot`, `websocketConnected: false`, and
`subsecondCapable: false`. That is the correct claim for the configured standard
transport.

To claim parity or superiority, deploy a shared streaming ingest path and run a
neutral seven-day same-book/same-market comparison. Measure provider timestamp
to browser render at p50/p95/p99, stale rate, missed changes, rate limits, and
cross-instance disagreement. The target remains p50 under 500 ms, p95 under
1.5s, and p99 under 3s for streamed sources.

## Verification completed

- Python modules compile.
- Changed JavaScript files pass `node --check`.
- `git diff --check` passes.
- Final full repository suite passed: 1,100 tests in 316.42 seconds after the
  Advanced REST, ProphetX/NoVIG depth, line-history integration, and serialized
  PostgreSQL cold-start migration updates.
- In-app browser QA covered Fantasy desktop/mobile, Positive EV, Odds Screen,
  Arbitrage, Middles, Low Hold, and Sharp Money.
- Fantasy `Build best slip` was exercised and returned the correct insufficient-
  qualified-legs state with no browser console errors.

## First production smoke result

Commit `4237e47` deployed successfully to the production Vercel project. The
Linux test suite, deployment, and NoVIG WebSocket smoke passed. The first
post-deployment Model Tracker reconciliation exposed concurrent serverless cold
starts deadlocking while applying the new PostgreSQL schema migration. The
bootstrap now obtains a transaction-scoped PostgreSQL advisory lock and
rechecks the schema under that lock before executing DDL.

Live provider evidence from that release showed:

- the configured OddsEngine key reported a 60-request limit with no quota
  remaining during the scan;
- the Advanced `/orderbook/top` capability probe was rejected, so
  `advancedAccess` was `false` rather than the promised custom entitlement;
- the book registry returned 47 books and included Pinnacle and NoVIG, but did
  not include ProphetX in that observed response;
- the Sharp Money direct-exchange fallback produced 50 read-only signals with
  both NoVIG and ProphetX depth after the OddsEngine Advanced rejection; and
- the Odds Screen correctly reported a degraded REST snapshot with only the
  books present in its live result instead of claiming unobserved coverage.

The deployment workflow now performs a protected OddsEngine authentication,
quota, registry, transport, and Advanced-access diagnostic on every production
release. Advanced rejection and quota exhaustion are surfaced as release
warnings; an explicit unauthorized response still fails the release smoke test.

## Production release gates

1. Deploy migrations and application together, then verify the cron writes to
   the shared production database.
2. Verify the custom production OddsEngine key through the protected diagnostic
   endpoint and capture its actual rate-limit headers and Advanced entitlement.
3. Verify actual observed book x sport x market coverage from
   `/api/odds/coverage`; never substitute catalog counts.
4. Verify real Pinnacle limits, provider timestamps, capacity, account
   eligibility, and settlement IDs. Unknown values must remain theoretical.
5. Run seven days of comparative latency/coverage and 30 days of versioned model
   telemetry before publishing OddsJam-parity, speed, or ROI claims.
6. Obtain the referenced `WEBSOCKET_API.md`, implement a persistent streaming
   worker, and run production smoke tests. Direct ProphetX credentials remain
   necessary only for account balances, orders, cancels, and fills—not for
   OddsEngine-backed read-only prices, limits, liquidity, or depth.

Only after all six gates pass is it accurate to say ProphetX was the final
remaining issue and everything else operates to the intended production
standard.
