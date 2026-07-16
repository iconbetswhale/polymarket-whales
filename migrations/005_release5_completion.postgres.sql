CREATE TABLE IF NOT EXISTS production_configuration_versions (
    config_version TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, config_json TEXT NOT NULL,
    activated_by TEXT NOT NULL, activated_at TEXT NOT NULL, superseded_at TEXT,
    status TEXT NOT NULL, calculation_version TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_production_config_status_time ON production_configuration_versions(status, activated_at DESC);
CREATE TABLE IF NOT EXISTS segment_policy_assignments (
    policy_id TEXT PRIMARY KEY, config_version TEXT NOT NULL, segment_dimension TEXT NOT NULL,
    segment_value TEXT NOT NULL, stake_multiplier REAL NOT NULL, status TEXT NOT NULL,
    rationale TEXT, created_at TEXT NOT NULL, FOREIGN KEY(config_version) REFERENCES production_configuration_versions(config_version)
);
CREATE INDEX IF NOT EXISTS idx_segment_policy_active ON segment_policy_assignments(status, segment_dimension, segment_value);
CREATE TABLE IF NOT EXISTS post_change_monitoring_runs (
    monitoring_id TEXT PRIMARY KEY, config_version TEXT NOT NULL, edge_map_run_id TEXT,
    segment_dimension TEXT NOT NULL, segment_value TEXT NOT NULL, metrics_json TEXT NOT NULL,
    status TEXT NOT NULL, calculation_version TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_post_change_config_time ON post_change_monitoring_runs(config_version, created_at DESC);
