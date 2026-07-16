# Release 3 execution and risk audit

## Release boundary

This branch implements only Release 3: order-book depth walking, maximum average price enforcement, maker/taker execution recommendations, portfolio correlation caps, bankroll buckets, the drawdown protocol, and audited kill switches. Release 4 learning-system work is not connected or started.

## Authoritative paths

- `position_tracker.py`: orchestrates current candidate evaluation, builds the user-scoped risk context, reconciles Model Tracker records, and records measurement snapshots.
- `recommendation_service.py`: final Model Tracker eligibility gate and machine-readable rejection precedence.
- `bet_sizing.py`: fee-adjusted Kelly sizing from Release 2, followed by the additive Release 3 risk cap and execution plan.
- `execution_engine.py`: maximum price, ask-depth walk, partial-liquidity calculation, and TAKE_NOW / POST_LIMIT / SPLIT_ORDER / WAIT / PASS selection.
- `risk_engine.py`: exposure normalization, correlation keys and caps, bankroll buckets, drawdown states, and strategy-stop logic.
- `database.py` and `durable_user_store.py`: SQLite and PostgreSQL persistence, diagnostics, per-user policy configuration, account state, and kill-switch audit history.
- `bet_tracker.py`: immutable execution/risk trace copied into new Model Tracker snapshots.
- `measurement_foundation.py`: candidate reason vocabulary and versioned Release 3 execution/risk snapshot payloads.
- `app.py`: public user-scoped bankroll-bucket APIs and protected admin risk controls/diagnostics.
- `static/app.js`: execution method, maximum price, effective price, correlated-risk reduction, bankroll bucket, and drawdown presentation.

## Database dependencies and migration risk

The application supports SQLite through `TrackerDatabase` and PostgreSQL through `DurableUserStore`. Migration `003_release3_execution_and_risk` is additive and idempotent in both dialects. It creates new tables and indexes only; no Release 1/2 or historical tracker row is updated, deleted, or recalculated.

Primary risks and mitigations:

- Partial migration: each dialect uses `CREATE TABLE IF NOT EXISTS`; migration registration occurs only through the existing schema migration path.
- User-data leakage: Personal Tracker exposure is loaded only for the authenticated user; the global Model Tracker remains separate.
- Historical drift: existing snapshots are preserved and new records carry `execution-engine-v3`, `portfolio-risk-v3`, `bankroll-buckets-v3`, and `drawdown-protocol-v3` versions.
- Duplicate snapshots: snapshot IDs use the existing stable correlation/recommendation identifiers and database primary keys.
- Unsafe configuration: bankroll bucket allocations must be finite, non-negative, and sum to 1.0.
- Unintended live recommendations: WAIT, PASS, stale or non-actionable execution plans, zero remaining risk capacity, and strategy-stop states are rejected before Model Tracker insertion.

## Current real-data integrations

Release 3 consumes the existing Polymarket quote/order-book fields supplied by the application. It does not create order-book levels, timestamps, fee rates, sportsbook prices, composite probabilities, liquidity, news, lineup, or behavioral-history values. When a required quote, fee, fair price, or depth input is absent, the existing unavailable/pass path remains authoritative.

External sportsbook/exchange composite sources still depend on provider access configured in Release 1/2. Until those providers return supported observations, composite fair price and composite CLV remain unavailable rather than estimated.

## Before/after behavior

Before Release 3, the Release 2 recommendation amount was eligible without an account-level correlation/drawdown cap and had no complete execution plan. After Release 3, the same Release 2 Kelly result is retained as `recommended_amount_before_portfolio_risk`, capped against current Model plus user-owned Personal exposure, and paired with a versioned execution plan. Existing records are unchanged.

## Validation fixtures

Automated fixtures cover an approved actionable plan, a maximum-price pass, partial-depth split execution, all five execution methods, combined Model/Personal correlation reduction, bucket exhaustion, every drawdown threshold, every strategy-stop input, admin authorization, migration registration, and snapshot persistence. Fixture prices are confined to tests and are never inserted into live application data.

Browser QA on the isolated local Release 3 server verified the `/trades` page loads without console errors and honestly shows no actionable trades when the local QA database has no real provider observations. The screenshot is `docs/qa/release3-trades.png`.
