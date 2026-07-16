# IconBets Phase 0 audit and Release 1 invariants

## Authoritative production boundaries

- Candidate construction, canonical sides, Lead/Supporting roles, opposition, and the existing confidence score live in `trade_scoring.py`.
- Research classifications and their Model Tracker restrictions live in `trade_research.py`.
- Current executable entry, order-book depth walking, slippage, the wallet-evidence probability adjustment, Kelly, and recommended sizing live in `bet_sizing.py`.
- The canonical Model Tracker eligibility decision lives in `recommendation_service.evaluate_trade_recommendation`.
- Tracker snapshot freezing and replay live in `bet_tracker.py`; reconciliation and automatic insertion live in `position_tracker.TrackerService`.
- Personal records live in `personal_bet_fills` and `personal_position_exits`, built by `personal_tracker.py` and `personal_positions.py`.
- Exchange CLV capture uses Polymarket CLOB quotes in `position_tracker._capture_closing_lines`, `clv.py`, `clv_quote_snapshots`, and `closing_line_snapshots`.
- Wallet category evidence is calculated during refresh in `TrackerService._build_category_metrics` and attached during trade scoring.
- Bankrolls are user-owned fields in `user_settings`; Model and Personal replay and exposure remain separate.

## Current provider truth

- Polymarket: connected for wallet positions, live CLOB order books, execution links, price history, and exchange CLV.
- NoVIG: adapter exists; no local credentials are configured.
- ProphetX: adapter exists; no local credentials are configured.
- Pinnacle, Circa, Bookmaker, BetOnline, Kalshi, and 4CX: no connected price feed in this release.

Unavailable providers must return an explicit unavailable state. Release 1 never fabricates quotes, composite probability, liquidity, or CLV.

## Measurement gaps found

- Passed candidates are not permanent. Latest Model Tracker rejections are replaceable diagnostics and pre-play exclusions are in-memory only.
- Existing estimated win probability is executable entry plus a wallet-evidence adjustment. It is not an independently sourced fair probability. Release 1 records this limitation without changing live sizing.
- SQLite stores local/global monitoring state. Optional PostgreSQL stores durable user/serverless state. Release 1 must migrate and support both.
- Existing schema changes are idempotent startup migrations rather than Alembic revisions.

## Release 1 invariants

- Existing confidence, Kelly, eligibility, sizing, Model Tracker, Personal Tracker, Whiteboard, wallet sync, live price, and CLV decisions remain unchanged.
- Candidate recording is observational and cannot create a Model Tracker position.
- The first candidate snapshot is immutable; later decisions and monitoring records are append-only or independently versioned.
- Display text is never the sole candidate identity.
- Historical tracker and personal records are not rewritten.
- Composite CLV remains unavailable until an independent real composite quote is connected.
- Release 2 code is not connected to production.
