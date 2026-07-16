# Release 2 decision-engine audit

Base commit: `4fa7808f30c9eb6c71fa7b258ef02babd06c120c`  
Implementation branch: `feature/sharp-system-release-2`

## Authoritative pre-release paths

- `trade_scoring.py::build_trades_to_play` built the live candidate feed and `_confidence_score` assigned a consensus-first score dominated by wallet count.
- `bet_sizing.py::build_recommendation` used the executable entry price as the probability baseline and added wallet evidence before Kelly.
- `recommendation_service.py::evaluate_trade_recommendation` was and remains the canonical Model Tracker eligibility boundary.
- `position_tracker.py::TrackerService._refresh_unlocked` controls refresh ordering: wallet ingestion, order books, candidates, measurement, then Model Tracker reconciliation.
- `position_tracker.py::TrackerService._record_candidate_measurements` is the Candidate Ledger persistence boundary.
- `execution_providers.py` contains exact market mapping and the connected Polymarket, NoVIG, and ProphetX adapters.
- `database.py` owns SQLite state; `durable_user_store.py::PostgresUserStore` owns the configured durable Postgres deployment state.

## Database dependencies and preservation requirements

Release 1 tables remain authoritative for the Candidate Ledger, decision history, monitoring, composite snapshots, dual CLV, Model Tracker, Personal Tracker, wallet registry, and user settings. Release 2 uses only additive tables and model-version rows. It does not rewrite or delete historical records.

New snapshot tables are `trade_quality_snapshots`, `liquidity_quality_snapshots`, `wallet_dependency_edges`, and `opposition_snapshots`. Both SQLite and Postgres receive the same `002_release2_decision_engine` migration.

## Provider audit

- Polymarket is the execution venue and is deliberately excluded as an independent fair-price source for a Polymarket trade.
- NoVIG and ProphetX provide real connected market data when credentials are configured. Their existing exact event, market, side, period, line, alternative-market, and settlement matching is reused.
- A no-vig probability is emitted only when every mutually exclusive sibling outcome needed for normalization is present.
- Pinnacle, Circa, Bookmaker, BetOnline, 4CX, and Kalshi remain interfaces/unavailable until real access exists. No line, price, liquidity, fee, or CLV value is fabricated.

## Migration and release risks

- A recommendation algorithm change requires a new recommendation version. Release 2 uses `v3`; canonical identity checks prevent a v2/v3 duplicate from entering Model Tracker.
- Existing candidates retain their historical decision rows. Release 2 candidate identity includes the new recommendation version so observations do not overwrite Release 1 identities.
- Missing independent fair price, expected fees, mapping, freshness, or executable liquidity must fail closed.
- Provider quote age and equivalent-market mapping are checked before composite inclusion.
- SQLite and Postgres migrations must remain idempotent because serverless workers can initialize concurrently.

## Implemented sequence

1. Add provider-normalized, no-vig fair-price quotes and weighted composite calculation.
2. Add wallet independence, weighted opposition, separate Liquidity Quality, and four-stage Trade Quality scoring.
3. Replace entry-derived probability sizing with uncertainty-haircut Kelly from independent fair probability.
4. Run provider enrichment and scoring before Candidate Ledger recording and Model Tracker reconciliation.
5. Add additive historical snapshots and protected decision-engine diagnostics.
6. Verify full automated regression coverage before any deployment.

Release 3 execution/risk-policy work is not connected here. In particular, this release does not invent provider fees, portfolio correlations, news certainty, timing suitability, or order-book behavioral history when those inputs are unavailable.
