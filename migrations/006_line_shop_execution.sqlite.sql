CREATE TABLE IF NOT EXISTS line_shop_initial_snapshots (
    user_id TEXT NOT NULL,
    recommendation_snapshot_id TEXT NOT NULL,
    trade_id TEXT NOT NULL,
    best_provider TEXT,
    best_provider_market_id TEXT,
    best_provider_outcome_id TEXT,
    best_executable_price REAL,
    effective_entry_price REAL,
    native_price TEXT,
    native_price_format TEXT,
    quote_timestamp TEXT,
    quotes_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, recommendation_snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_line_shop_initial_trade
    ON line_shop_initial_snapshots(trade_id, created_at);

CREATE TABLE IF NOT EXISTS line_shop_quote_observations (
    observation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    recommendation_snapshot_id TEXT NOT NULL,
    trade_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_event_id TEXT,
    provider_market_id TEXT,
    provider_outcome_id TEXT,
    selection TEXT,
    native_price TEXT,
    native_price_format TEXT,
    implied_probability REAL,
    best_executable_price REAL,
    effective_entry_price REAL,
    available_liquidity REAL,
    recommended_stake REAL,
    estimated_fees REAL,
    quote_timestamp TEXT,
    quote_age_seconds REAL,
    market_status TEXT,
    mapping_confidence TEXT,
    is_exact_match INTEGER NOT NULL,
    is_stale INTEGER NOT NULL,
    can_fill_recommended_stake INTEGER,
    is_best_price INTEGER NOT NULL,
    failure_reason TEXT,
    quote_json TEXT NOT NULL,
    captured_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_line_shop_quotes_snapshot
    ON line_shop_quote_observations(user_id, recommendation_snapshot_id, captured_at);

CREATE INDEX IF NOT EXISTS idx_line_shop_quotes_trade_provider
    ON line_shop_quote_observations(trade_id, provider, captured_at);
