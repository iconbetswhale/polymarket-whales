CREATE TABLE IF NOT EXISTS normalized_market_quotes (
    provider TEXT NOT NULL,
    provider_selection_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    market_id TEXT NOT NULL,
    selection_id TEXT NOT NULL,
    quote_timestamp TEXT NOT NULL,
    received_timestamp TEXT NOT NULL,
    meaningful_hash TEXT NOT NULL,
    quote_json TEXT NOT NULL,
    PRIMARY KEY (provider, provider_selection_id)
);

CREATE INDEX IF NOT EXISTS idx_normalized_quotes_market
    ON normalized_market_quotes(event_id, market_id, selection_id);
CREATE INDEX IF NOT EXISTS idx_normalized_quotes_received
    ON normalized_market_quotes(received_timestamp DESC);

CREATE TABLE IF NOT EXISTS normalized_market_quote_history (
    id BIGSERIAL PRIMARY KEY,
    snapshot_hash TEXT NOT NULL UNIQUE,
    meaningful_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_event_id TEXT NOT NULL,
    provider_market_id TEXT NOT NULL,
    provider_selection_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    market_id TEXT NOT NULL,
    selection_id TEXT NOT NULL,
    sport TEXT NOT NULL,
    league TEXT NOT NULL,
    event_name TEXT NOT NULL,
    home_team TEXT,
    away_team TEXT,
    start_time TEXT NOT NULL,
    market_type TEXT NOT NULL,
    market_family TEXT NOT NULL,
    period TEXT NOT NULL,
    is_alternate BOOLEAN NOT NULL DEFAULT FALSE,
    line DOUBLE PRECISION,
    selection TEXT NOT NULL,
    side TEXT,
    american_odds INTEGER NOT NULL,
    decimal_odds DOUBLE PRECISION NOT NULL,
    implied_probability DOUBLE PRECISION NOT NULL,
    quote_timestamp TEXT NOT NULL,
    received_timestamp TEXT NOT NULL,
    available_liquidity DOUBLE PRECISION,
    market_limit DOUBLE PRECISION,
    mapping_confidence DOUBLE PRECISION,
    settlement_rule_key TEXT,
    checkpoint_only BOOLEAN NOT NULL DEFAULT FALSE,
    quote_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_quote_history_identity_time
    ON normalized_market_quote_history(provider, provider_selection_id, received_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_quote_history_canonical_time
    ON normalized_market_quote_history(event_id, market_id, selection_id, received_timestamp DESC);
