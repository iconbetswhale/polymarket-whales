CREATE TABLE IF NOT EXISTS edge_map_runs (
    run_id TEXT PRIMARY KEY, window_start TEXT, window_end TEXT, candidate_count INTEGER NOT NULL,
    config_json TEXT NOT NULL, calculation_version TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS edge_map_segment_snapshots (
    snapshot_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, dimension TEXT NOT NULL, segment_value TEXT NOT NULL,
    candidate_count INTEGER NOT NULL, played_count INTEGER NOT NULL, passed_count INTEGER NOT NULL,
    settled_count INTEGER NOT NULL, stake REAL NOT NULL, roi REAL, stake_weighted_exchange_clv REAL,
    stake_weighted_composite_clv REAL, positive_composite_clv_rate REAL, median_clv REAL,
    execution_loss REAL NOT NULL, average_fees REAL, maximum_drawdown REAL,
    statistical_reliability REAL NOT NULL, status TEXT NOT NULL, snapshot_json TEXT NOT NULL,
    calculation_version TEXT NOT NULL, created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES edge_map_runs(run_id), UNIQUE(run_id, dimension, segment_value)
);
CREATE INDEX IF NOT EXISTS idx_edge_map_dimension_status ON edge_map_segment_snapshots(dimension, status, candidate_count DESC);
CREATE TABLE IF NOT EXISTS holdout_evaluations (
    evaluation_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, segment_dimension TEXT NOT NULL,
    segment_value TEXT NOT NULL, baseline_start TEXT, baseline_end TEXT, holdout_start TEXT NOT NULL,
    holdout_end TEXT NOT NULL, baseline_metrics_json TEXT NOT NULL, holdout_metrics_json TEXT NOT NULL,
    status TEXT NOT NULL, sample_sufficient INTEGER NOT NULL, calculation_version TEXT NOT NULL,
    evaluated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_holdout_proposal_time ON holdout_evaluations(proposal_id, evaluated_at DESC);
CREATE TABLE IF NOT EXISTS configuration_proposals (
    proposal_id TEXT PRIMARY KEY, segment_dimension TEXT NOT NULL, segment_value TEXT NOT NULL,
    proposal_type TEXT NOT NULL, old_config_json TEXT NOT NULL, proposed_config_json TEXT NOT NULL,
    evidence_snapshot_json TEXT NOT NULL, status TEXT NOT NULL, created_by TEXT NOT NULL,
    approved_by TEXT, rejection_reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    approved_at TEXT, applied_at TEXT, config_version_before TEXT, config_version_after TEXT
);
CREATE INDEX IF NOT EXISTS idx_config_proposal_status_time ON configuration_proposals(status, created_at DESC);
CREATE TABLE IF NOT EXISTS rule_violations (
    violation_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, trade_id TEXT NOT NULL,
    candidate_id TEXT, warning_code TEXT NOT NULL, confirmed_action TEXT NOT NULL,
    confirmation_text TEXT NOT NULL, entry_price REAL, outcome TEXT, profit_loss REAL,
    exchange_clv REAL, composite_clv REAL, context_json TEXT NOT NULL,
    calculation_version TEXT NOT NULL, created_at TEXT NOT NULL, settled_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_rule_violations_user_time ON rule_violations(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_rule_violations_warning_time ON rule_violations(warning_code, created_at DESC);
