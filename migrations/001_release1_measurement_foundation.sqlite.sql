CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_versions (
    version_key TEXT PRIMARY KEY,
    component TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL,
    description TEXT,
    registered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidate_ledger (
    candidate_id TEXT PRIMARY KEY,
    correlation_id TEXT NOT NULL,
    canonical_event_id TEXT NOT NULL,
    canonical_market_id TEXT NOT NULL,
    canonical_outcome_id TEXT NOT NULL,
    period TEXT NOT NULL DEFAULT '',
    market_line TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL,
    settlement_scope TEXT NOT NULL DEFAULT '',
    settlement_rules TEXT NOT NULL DEFAULT '',
    detected_at TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    event_start_time TEXT,
    sport TEXT,
    league TEXT,
    event_title TEXT,
    market_title TEXT,
    selection TEXT,
    current_decision TEXT NOT NULL,
    current_reason_codes_json TEXT NOT NULL DEFAULT '[]',
    execution_snapshot_json TEXT NOT NULL DEFAULT '{}',
    candidate_snapshot_json TEXT NOT NULL,
    trade_scoring_version TEXT NOT NULL,
    recommendation_version TEXT NOT NULL,
    fair_price_version TEXT NOT NULL,
    kelly_version TEXT NOT NULL,
    risk_policy_version TEXT NOT NULL,
    wallet_registry_version TEXT NOT NULL,
    execution_plan_version TEXT NOT NULL,
    composite_price_status TEXT NOT NULL DEFAULT 'UNAVAILABLE',
    composite_price_missing_reason TEXT,
    UNIQUE(canonical_event_id, canonical_market_id, canonical_outcome_id, period, market_line, provider, settlement_scope, settlement_rules, recommendation_version)
);

CREATE INDEX IF NOT EXISTS idx_candidate_ledger_decision_seen
    ON candidate_ledger(current_decision, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_candidate_ledger_event
    ON candidate_ledger(canonical_event_id, canonical_market_id, canonical_outcome_id);
CREATE INDEX IF NOT EXISTS idx_candidate_ledger_correlation
    ON candidate_ledger(correlation_id, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS candidate_decisions (
    decision_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    primary_reason_code TEXT,
    decided_at TEXT NOT NULL,
    decision_snapshot_json TEXT NOT NULL,
    recommendation_version TEXT NOT NULL,
    calculation_version TEXT NOT NULL,
    FOREIGN KEY(candidate_id) REFERENCES candidate_ledger(candidate_id)
);

CREATE INDEX IF NOT EXISTS idx_candidate_decisions_candidate_time
    ON candidate_decisions(candidate_id, decided_at DESC);
CREATE INDEX IF NOT EXISTS idx_candidate_decisions_outcome_time
    ON candidate_decisions(decision, decided_at DESC);

CREATE TABLE IF NOT EXISTS candidate_monitoring (
    candidate_id TEXT PRIMARY KEY,
    monitoring_status TEXT NOT NULL,
    exchange_clv_status TEXT NOT NULL DEFAULT 'PENDING',
    composite_clv_status TEXT NOT NULL DEFAULT 'UNAVAILABLE',
    exchange_closing_price REAL,
    composite_closing_probability REAL,
    exchange_probability_point_clv REAL,
    exchange_stake_return_clv REAL,
    composite_probability_point_clv REAL,
    composite_stake_return_clv REAL,
    execution_loss REAL,
    fee_adjusted_clv REAL,
    closing_timestamp TEXT,
    result TEXT,
    hypothetical_stake REAL NOT NULL DEFAULT 100.0,
    hypothetical_profit_loss REAL,
    maximum_favorable_movement REAL,
    maximum_adverse_movement REAL,
    pass_reason_justified INTEGER,
    missing_reason TEXT,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    FOREIGN KEY(candidate_id) REFERENCES candidate_ledger(candidate_id)
);

CREATE TABLE IF NOT EXISTS dual_clv_measurements (
    measurement_id TEXT PRIMARY KEY,
    tracker_type TEXT NOT NULL,
    tracker_record_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    candidate_id TEXT,
    entry_price REAL,
    exchange_closing_price REAL,
    composite_closing_probability REAL,
    exchange_probability_point_clv REAL,
    exchange_stake_return_clv REAL,
    composite_probability_point_clv REAL,
    composite_stake_return_clv REAL,
    execution_loss REAL,
    fee_adjusted_clv REAL,
    exchange_clv_status TEXT NOT NULL,
    composite_clv_status TEXT NOT NULL,
    exchange_missing_reason TEXT,
    composite_missing_reason TEXT,
    closing_timestamp TEXT,
    exchange_calculation_version TEXT NOT NULL,
    composite_calculation_version TEXT NOT NULL,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(tracker_type, tracker_record_id)
);

CREATE INDEX IF NOT EXISTS idx_dual_clv_tracker_time
    ON dual_clv_measurements(tracker_type, user_id, closing_timestamp DESC);

CREATE TABLE IF NOT EXISTS composite_price_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    candidate_id TEXT,
    correlation_id TEXT NOT NULL,
    quote_timestamp TEXT NOT NULL,
    composite_fair_probability REAL,
    source_count INTEGER NOT NULL DEFAULT 0,
    source_dispersion REAL,
    mapping_confidence TEXT NOT NULL,
    status TEXT NOT NULL,
    missing_reason TEXT,
    calculation_version TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(candidate_id) REFERENCES candidate_ledger(candidate_id)
);

CREATE INDEX IF NOT EXISTS idx_composite_snapshots_candidate_time
    ON composite_price_snapshots(candidate_id, quote_timestamp DESC);

CREATE TABLE IF NOT EXISTS composite_source_contributions (
    snapshot_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_event_id TEXT,
    provider_market_id TEXT,
    provider_selection_id TEXT,
    native_odds TEXT,
    decimal_odds REAL,
    raw_implied_probability REAL,
    no_vig_probability REAL,
    contribution_weight REAL,
    quote_timestamp TEXT,
    quote_freshness TEXT,
    included INTEGER NOT NULL DEFAULT 0,
    exclusion_reason TEXT,
    source_snapshot_json TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, provider),
    FOREIGN KEY(snapshot_id) REFERENCES composite_price_snapshots(snapshot_id)
);
