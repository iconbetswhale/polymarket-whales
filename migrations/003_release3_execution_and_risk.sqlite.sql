CREATE TABLE IF NOT EXISTS execution_plan_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    candidate_id TEXT,
    correlation_id TEXT,
    recommendation_snapshot_id TEXT,
    recommended_stake REAL NOT NULL,
    maximum_average_price REAL,
    effective_price REAL,
    amount_executable_below_max REAL NOT NULL,
    unfilled_amount REAL NOT NULL,
    execution_method TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    quote_timestamp TEXT,
    quote_fresh INTEGER NOT NULL,
    calculation_version TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_execution_plan_candidate_time ON execution_plan_snapshots(candidate_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_execution_plan_method_time ON execution_plan_snapshots(execution_method, created_at DESC);

CREATE TABLE IF NOT EXISTS portfolio_risk_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    candidate_id TEXT,
    recommendation_snapshot_id TEXT,
    bucket TEXT NOT NULL,
    risk_state TEXT NOT NULL,
    proposed_stake REAL NOT NULL,
    final_capped_stake REAL NOT NULL,
    correlation_multiplier REAL NOT NULL,
    reason_codes_json TEXT NOT NULL,
    calculation_version TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_portfolio_risk_user_time ON portfolio_risk_snapshots(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_portfolio_risk_candidate_time ON portfolio_risk_snapshots(candidate_id, created_at DESC);

CREATE TABLE IF NOT EXISTS bankroll_bucket_configs (
    user_id TEXT PRIMARY KEY,
    core_allocation REAL NOT NULL DEFAULT 0.70,
    discovery_allocation REAL NOT NULL DEFAULT 0.10,
    liquidity_reserve_allocation REAL NOT NULL DEFAULT 0.15,
    operational_buffer_allocation REAL NOT NULL DEFAULT 0.05,
    combine_model_and_personal INTEGER NOT NULL DEFAULT 1,
    config_version TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_account_state (
    user_id TEXT PRIMARY KEY,
    current_bankroll REAL NOT NULL,
    high_water_mark REAL NOT NULL,
    recent_stake_weighted_composite_clv REAL,
    recent_valid_trade_count INTEGER NOT NULL DEFAULT 0,
    material_error_count_7d INTEGER NOT NULL DEFAULT 0,
    wallet_data_invalid INTEGER NOT NULL DEFAULT 0,
    provider_unreliable INTEGER NOT NULL DEFAULT 0,
    manual_kill_switch INTEGER NOT NULL DEFAULT 0,
    manual_reason TEXT,
    state_version TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kill_switch_audit (
    audit_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    reason_code TEXT NOT NULL,
    actor TEXT NOT NULL,
    override INTEGER NOT NULL DEFAULT 0,
    prior_state_json TEXT NOT NULL,
    new_state_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kill_switch_user_time ON kill_switch_audit(user_id, created_at DESC);

