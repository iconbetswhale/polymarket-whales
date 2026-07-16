CREATE TABLE IF NOT EXISTS trade_quality_snapshots (
    snapshot_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES candidate_ledger(candidate_id),
    correlation_id TEXT NOT NULL, score INTEGER NOT NULL, grade TEXT NOT NULL,
    uncapped_grade TEXT NOT NULL, signal_points DOUBLE PRECISION NOT NULL,
    price_points DOUBLE PRECISION NOT NULL, liquidity_points DOUBLE PRECISION NOT NULL,
    context_points DOUBLE PRECISION NOT NULL, fair_price_status TEXT NOT NULL,
    calculation_version TEXT NOT NULL, snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trade_quality_candidate_time ON trade_quality_snapshots(candidate_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trade_quality_grade_time ON trade_quality_snapshots(grade, created_at DESC);

CREATE TABLE IF NOT EXISTS liquidity_quality_snapshots (
    snapshot_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES candidate_ledger(candidate_id),
    status TEXT NOT NULL, score DOUBLE PRECISION NOT NULL, spread DOUBLE PRECISION,
    top_depth_dollars DOUBLE PRECISION, ladder_depth_dollars DOUBLE PRECISION,
    calculation_version TEXT NOT NULL, snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_liquidity_quality_candidate_time ON liquidity_quality_snapshots(candidate_id, created_at DESC);

CREATE TABLE IF NOT EXISTS wallet_dependency_edges (
    edge_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES candidate_ledger(candidate_id),
    source_wallet_id TEXT NOT NULL, target_wallet_id TEXT, dependency_type TEXT NOT NULL,
    dependency_weight DOUBLE PRECISION NOT NULL, evidence_json TEXT NOT NULL,
    calculation_version TEXT NOT NULL, observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wallet_dependency_candidate_time ON wallet_dependency_edges(candidate_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS opposition_snapshots (
    snapshot_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES candidate_ledger(candidate_id),
    raw_count INTEGER NOT NULL, weighted_opposition DOUBLE PRECISION NOT NULL,
    penalty DOUBLE PRECISION NOT NULL, action TEXT NOT NULL, calculation_version TEXT NOT NULL,
    snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_opposition_candidate_time ON opposition_snapshots(candidate_id, created_at DESC);
