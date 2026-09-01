CREATE TABLE IF NOT EXISTS odds_tool_snapshots (
    snapshot_key TEXT PRIMARY KEY,
    tool TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    source_updated_at TEXT NOT NULL,
    stored_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ok'
);

CREATE INDEX IF NOT EXISTS idx_odds_tool_snapshots_tool_updated
    ON odds_tool_snapshots(tool, source_updated_at DESC);

CREATE TABLE IF NOT EXISTS odds_provider_health (
    provider_key TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    transport TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    last_success_at TEXT,
    last_error_at TEXT,
    latency_ms DOUBLE PRECISION,
    quote_count INTEGER NOT NULL DEFAULT 0,
    executable_quote_count INTEGER NOT NULL DEFAULT 0,
    stale_quote_count INTEGER NOT NULL DEFAULT 0,
    missing_timestamp_count INTEGER NOT NULL DEFAULT 0,
    details_json TEXT NOT NULL DEFAULT '{}'
);
