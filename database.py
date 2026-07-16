from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from durable_user_store import PostgresUserStore
from measurement_foundation import (
    COMPOSITE_CLV_VERSION,
    RELEASE1_MIGRATION_VERSION,
    decision_id,
    migration_sql,
    model_version_rows,
    stable_hash,
)
from release2_foundation import (
    RELEASE2_MIGRATION_VERSION,
    migration_sql as release2_migration_sql,
    model_version_rows as release2_model_version_rows,
)
from release3_foundation import (
    RELEASE3_MIGRATION_VERSION,
    migration_sql as release3_migration_sql,
    model_version_rows as release3_model_version_rows,
)
from release4_foundation import (
    RELEASE4_MIGRATION_VERSION,
    migration_sql as release4_migration_sql,
    model_version_rows as release4_model_version_rows,
)
from release5_foundation import RELEASE5_MIGRATION_VERSION, migration_sql as release5_migration_sql, model_version_rows as release5_model_version_rows


class SettingsVersionConflict(RuntimeError):
    def __init__(self, current: dict) -> None:
        super().__init__("User settings changed in another session.")
        self.current = current


class TrackerDatabase:
    def __init__(self, path: Path, durable_database_url: str | None = None) -> None:
        self.path = path
        self.user_store: PostgresUserStore | None = None
        self.initialize()
        if durable_database_url:
            self.user_store = PostgresUserStore(durable_database_url)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tracked_positions (
                    wallet_address TEXT NOT NULL,
                    position_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    category TEXT,
                    league TEXT,
                    market_title TEXT,
                    outcome TEXT,
                    resolution_time TEXT,
                    first_detected_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    last_changed_at TEXT NOT NULL,
                    closed_at TEXT,
                    snapshot_json TEXT NOT NULL,
                    PRIMARY KEY (wallet_address, position_key)
                );

                CREATE INDEX IF NOT EXISTS idx_tracked_positions_status
                    ON tracked_positions(status);
                CREATE INDEX IF NOT EXISTS idx_tracked_positions_category
                    ON tracked_positions(category, league);
                CREATE INDEX IF NOT EXISTS idx_tracked_positions_resolution
                    ON tracked_positions(resolution_time);

                CREATE TABLE IF NOT EXISTS position_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wallet_address TEXT NOT NULL,
                    position_key TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE,
                    detected_at TEXT NOT NULL,
                    category TEXT,
                    league TEXT,
                    market_title TEXT,
                    outcome TEXT,
                    event_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_position_events_wallet_detected
                    ON position_events(wallet_address, detected_at DESC);
                CREATE INDEX IF NOT EXISTS idx_position_events_type_detected
                    ON position_events(event_type, detected_at DESC);

                CREATE TABLE IF NOT EXISTS tracked_wallet_registry (
                    normalized_address TEXT PRIMARY KEY COLLATE NOCASE,
                    display_label TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    sync_status TEXT NOT NULL DEFAULT 'pending',
                    last_synced_at TEXT,
                    last_error TEXT,
                    config_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK (normalized_address = lower(normalized_address))
                );

                CREATE TABLE IF NOT EXISTS wallet_execution_fills (
                    fill_id TEXT PRIMARY KEY,
                    wallet_address TEXT NOT NULL COLLATE NOCASE,
                    transaction_hash TEXT,
                    condition_id TEXT NOT NULL,
                    outcome_id TEXT NOT NULL,
                    side TEXT NOT NULL,
                    shares REAL NOT NULL,
                    price REAL NOT NULL,
                    usd_amount REAL NOT NULL,
                    executed_at INTEGER NOT NULL,
                    event_slug TEXT,
                    market_slug TEXT,
                    market_title TEXT,
                    outcome TEXT,
                    fill_json TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    CHECK (wallet_address = lower(wallet_address))
                );

                CREATE INDEX IF NOT EXISTS idx_wallet_fills_position
                    ON wallet_execution_fills(
                        wallet_address,
                        condition_id,
                        outcome_id,
                        executed_at
                    );
                CREATE INDEX IF NOT EXISTS idx_wallet_fills_transaction
                    ON wallet_execution_fills(wallet_address, transaction_hash);

                CREATE TABLE IF NOT EXISTS refresh_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id TEXT PRIMARY KEY,
                    starting_bankroll REAL NOT NULL,
                    trades_to_play_bankroll REAL NOT NULL,
                    sizing_bankroll_configured INTEGER NOT NULL DEFAULT 0,
                    tracker_bankroll REAL NOT NULL,
                    personal_tracker_bankroll REAL NOT NULL,
                    tracker_view TEXT NOT NULL DEFAULT 'model',
                    settings_version INTEGER NOT NULL DEFAULT 1,
                    unit_percentage REAL NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_accounts (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    password_iterations INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_auth_sessions_user
                    ON auth_sessions(user_id, expires_at);

                CREATE TABLE IF NOT EXISTS bet_tracker (
                    user_id TEXT NOT NULL,
                    dedupe_key TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT,
                    settled_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    PRIMARY KEY (user_id, dedupe_key)
                );

                CREATE INDEX IF NOT EXISTS idx_bet_tracker_user_created
                    ON bet_tracker(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_bet_tracker_status
                    ON bet_tracker(status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS discord_trade_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    dedupe_key TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    notification_type TEXT NOT NULL DEFAULT 'model_tracker_insert',
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    discord_message_id TEXT,
                    response_status INTEGER,
                    last_error TEXT,
                    next_attempt_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    delivered_at TEXT,
                    UNIQUE (user_id, dedupe_key, notification_type)
                );

                CREATE INDEX IF NOT EXISTS idx_discord_notifications_delivery
                    ON discord_trade_notifications(status, next_attempt_at, created_at);

                CREATE TABLE IF NOT EXISTS tracking_job_state (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tracking_rejections (
                    user_id TEXT NOT NULL,
                    dedupe_key TEXT NOT NULL,
                    rejection_reason TEXT NOT NULL,
                    last_evaluated_at TEXT NOT NULL,
                    evaluation_json TEXT NOT NULL,
                    PRIMARY KEY (user_id, dedupe_key)
                );

                CREATE INDEX IF NOT EXISTS idx_tracking_rejections_user_evaluated
                    ON tracking_rejections(user_id, last_evaluated_at DESC);

                CREATE TABLE IF NOT EXISTS hidden_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    canonical_event_id TEXT NOT NULL,
                    canonical_market_id TEXT NOT NULL,
                    market_line TEXT NOT NULL DEFAULT '',
                    canonical_outcome_id TEXT NOT NULL,
                    event_title TEXT,
                    market_title TEXT,
                    selection TEXT,
                    event_start_time TEXT,
                    hidden_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (
                        user_id,
                        canonical_event_id,
                        canonical_market_id,
                        market_line,
                        canonical_outcome_id
                    )
                );

                CREATE INDEX IF NOT EXISTS idx_hidden_trades_user_hidden
                    ON hidden_trades(user_id, hidden_at DESC);

                CREATE TABLE IF NOT EXISTS whiteboard_pins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    canonical_event_id TEXT NOT NULL,
                    canonical_market_id TEXT NOT NULL,
                    market_line TEXT NOT NULL DEFAULT '',
                    canonical_outcome_id TEXT NOT NULL,
                    market_type TEXT,
                    period TEXT,
                    snapshot_json TEXT NOT NULL,
                    pinned_at TEXT NOT NULL,
                    archived_at TEXT,
                    archive_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_whiteboard_active_unique
                    ON whiteboard_pins(
                        user_id, canonical_event_id, canonical_market_id,
                        market_line, canonical_outcome_id
                    ) WHERE archived_at IS NULL;
                CREATE INDEX IF NOT EXISTS idx_whiteboard_user_active
                    ON whiteboard_pins(user_id, archived_at, pinned_at DESC);

                CREATE TABLE IF NOT EXISTS personal_bet_fills (
                    fill_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    canonical_event_id TEXT NOT NULL,
                    canonical_event_slug TEXT,
                    canonical_market_id TEXT NOT NULL,
                    canonical_market_slug TEXT,
                    market_line TEXT NOT NULL DEFAULT '',
                    canonical_outcome_id TEXT NOT NULL,
                    event_title TEXT,
                    market_title TEXT,
                    selection TEXT,
                    event_start_time TEXT,
                    market_url TEXT,
                    entry_price REAL NOT NULL,
                    shares REAL NOT NULL,
                    position_cost REAL NOT NULL,
                    fees REAL NOT NULL DEFAULT 0,
                    total_paid REAL NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT,
                    settled_at TEXT,
                    sportsbook TEXT NOT NULL DEFAULT 'Polymarket',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    sharp_snapshot_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_personal_fills_user_event
                    ON personal_bet_fills(user_id, canonical_event_id, status);
                CREATE INDEX IF NOT EXISTS idx_personal_fills_user_market
                    ON personal_bet_fills(
                        user_id,
                        canonical_event_id,
                        canonical_market_id,
                        market_line,
                        canonical_outcome_id,
                        status
                    );

                CREATE TABLE IF NOT EXISTS personal_position_exits (
                    exit_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    canonical_event_id TEXT NOT NULL,
                    canonical_market_id TEXT NOT NULL,
                    market_line TEXT NOT NULL DEFAULT '',
                    canonical_outcome_id TEXT NOT NULL,
                    sportsbook TEXT NOT NULL,
                    shares_sold REAL NOT NULL,
                    sell_price REAL NOT NULL,
                    gross_proceeds REAL NOT NULL,
                    fees REAL NOT NULL DEFAULT 0,
                    net_proceeds REAL NOT NULL,
                    sold_at TEXT NOT NULL,
                    mode TEXT NOT NULL DEFAULT 'tracker_only',
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_personal_exits_user_position
                    ON personal_position_exits(
                        user_id, canonical_event_id, canonical_market_id,
                        market_line, canonical_outcome_id, sportsbook
                    );

                CREATE TABLE IF NOT EXISTS clv_quote_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    provider_event_id TEXT NOT NULL,
                    provider_market_id TEXT NOT NULL,
                    provider_selection_id TEXT NOT NULL,
                    quote_timestamp TEXT NOT NULL,
                    provider_status TEXT,
                    best_bid REAL,
                    best_ask REAL,
                    midpoint REAL,
                    last_trade REAL,
                    depth_json TEXT NOT NULL DEFAULT '[]',
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(provider, provider_market_id, provider_selection_id, quote_timestamp)
                );
                CREATE INDEX IF NOT EXISTS idx_clv_quotes_selection_time
                    ON clv_quote_snapshots(
                        provider, provider_market_id, provider_selection_id,
                        quote_timestamp DESC
                    );

                CREATE TABLE IF NOT EXISTS closing_line_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tracker_type TEXT NOT NULL,
                    tracker_record_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    provider_event_id TEXT NOT NULL,
                    provider_market_id TEXT NOT NULL,
                    provider_selection_id TEXT NOT NULL,
                    entry_price REAL,
                    entry_native_odds TEXT,
                    entry_implied_probability REAL,
                    entry_stake REAL,
                    closing_snapshot_timestamp TEXT,
                    official_event_start_timestamp TEXT,
                    closing_effective_price REAL,
                    closing_midpoint REAL,
                    clv_cents REAL,
                    clv_probability_points REAL,
                    clv_pct REAL,
                    midpoint_clv_pct REAL,
                    clv_status TEXT NOT NULL,
                    clv_unavailable_reason TEXT,
                    snapshot_json TEXT NOT NULL,
                    calculation_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(tracker_type, tracker_record_id)
                );
                CREATE INDEX IF NOT EXISTS idx_closing_lines_tracker_time
                    ON closing_line_snapshots(
                        tracker_type, user_id, closing_snapshot_timestamp DESC
                    );
                """
            )
            settings_columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(user_settings)")
            }
            personal_fill_columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(personal_bet_fills)")
            }
            if "sportsbook" not in personal_fill_columns:
                conn.execute(
                    "ALTER TABLE personal_bet_fills ADD COLUMN sportsbook TEXT NOT NULL DEFAULT 'Polymarket'"
                )
            if "tags_json" not in personal_fill_columns:
                conn.execute(
                    "ALTER TABLE personal_bet_fills ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'"
                )
            if "sharp_snapshot_json" not in personal_fill_columns:
                conn.execute(
                    "ALTER TABLE personal_bet_fills ADD COLUMN sharp_snapshot_json TEXT NOT NULL DEFAULT '{}'"
                )
            if "tracker_bankroll" not in settings_columns:
                conn.execute(
                    "ALTER TABLE user_settings ADD COLUMN tracker_bankroll REAL"
                )
            if "trades_to_play_bankroll" not in settings_columns:
                conn.execute(
                    "ALTER TABLE user_settings ADD COLUMN trades_to_play_bankroll REAL"
                )
                conn.execute(
                    "UPDATE user_settings SET trades_to_play_bankroll = starting_bankroll"
                )
            if "sizing_bankroll_configured" not in settings_columns:
                conn.execute(
                    "ALTER TABLE user_settings ADD COLUMN sizing_bankroll_configured INTEGER NOT NULL DEFAULT 0"
                )
                # Existing values may have been manually selected; preserve them as saved.
                conn.execute(
                    "UPDATE user_settings SET sizing_bankroll_configured = 1"
                )
            if "personal_tracker_bankroll" not in settings_columns:
                conn.execute(
                    "ALTER TABLE user_settings ADD COLUMN personal_tracker_bankroll REAL"
                )
                conn.execute(
                    "UPDATE user_settings SET personal_tracker_bankroll = starting_bankroll"
                )
            if "tracker_view" not in settings_columns:
                conn.execute(
                    "ALTER TABLE user_settings ADD COLUMN tracker_view TEXT NOT NULL DEFAULT 'model'"
                )
            if "settings_version" not in settings_columns:
                conn.execute(
                    "ALTER TABLE user_settings ADD COLUMN settings_version INTEGER NOT NULL DEFAULT 1"
                )
            conn.execute(
                """
                UPDATE user_settings
                SET tracker_bankroll = starting_bankroll
                WHERE tracker_bankroll IS NULL
                """
            )
            conn.execute(
                """
                UPDATE user_settings
                SET trades_to_play_bankroll = starting_bankroll
                WHERE trades_to_play_bankroll IS NULL
                """
            )
            conn.execute(
                """
                UPDATE user_settings
                SET personal_tracker_bankroll = starting_bankroll
                WHERE personal_tracker_bankroll IS NULL
                """
            )
            invalid_rows = []
            for row in conn.execute(
                "SELECT user_id, dedupe_key, snapshot_json FROM bet_tracker"
            ):
                try:
                    snapshot = json.loads(row["snapshot_json"])
                    fraction = float(snapshot.get("final_recommended_fraction") or 0)
                    amount = snapshot.get("original_displayed_amount")
                    amount = float(amount) if amount is not None else None
                except (TypeError, ValueError, json.JSONDecodeError):
                    invalid_rows.append((row["user_id"], row["dedupe_key"]))
                    continue
                if fraction <= 1e-12 or (amount is not None and amount < 0.01):
                    invalid_rows.append((row["user_id"], row["dedupe_key"]))
            conn.executemany(
                "DELETE FROM bet_tracker WHERE user_id = ? AND dedupe_key = ?",
                invalid_rows,
            )
            conn.executescript(migration_sql("sqlite"))
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (RELEASE1_MIGRATION_VERSION, now),
            )
            conn.executemany(
                """
                INSERT OR IGNORE INTO model_versions(
                    version_key, component, version, status, description, registered_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["version_key"], row["component"], row["version"],
                        row["status"], row["description"], row["registered_at"],
                    )
                    for row in model_version_rows()
                ],
            )
            conn.executescript(release3_migration_sql("sqlite"))
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (RELEASE3_MIGRATION_VERSION, now),
            )
            conn.executemany(
                """
                INSERT OR IGNORE INTO model_versions(
                    version_key, component, version, status, description, registered_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["version_key"], row["component"], row["version"],
                        row["status"], row["description"], row["registered_at"],
                    )
                    for row in release3_model_version_rows()
                ],
            )
            conn.executescript(release4_migration_sql("sqlite"))
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (RELEASE4_MIGRATION_VERSION, now),
            )
            conn.executemany(
                """
                INSERT OR IGNORE INTO model_versions(
                    version_key, component, version, status, description, registered_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [(row["version_key"], row["component"], row["version"], row["status"], row["description"], row["registered_at"]) for row in release4_model_version_rows()],
            )
            conn.executescript(release5_migration_sql("sqlite"))
            conn.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)", (RELEASE5_MIGRATION_VERSION, now))
            conn.executemany("INSERT OR IGNORE INTO model_versions(version_key, component, version, status, description, registered_at) VALUES (?, ?, ?, ?, ?, ?)", [(row["version_key"], row["component"], row["version"], row["status"], row["description"], row["registered_at"]) for row in release5_model_version_rows()])
            conn.executescript(release2_migration_sql("sqlite"))
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (RELEASE2_MIGRATION_VERSION, now),
            )
            conn.executemany(
                """
                INSERT OR IGNORE INTO model_versions(
                    version_key, component, version, status, description, registered_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["version_key"], row["component"], row["version"],
                        row["status"], row["description"], row["registered_at"],
                    )
                    for row in release2_model_version_rows()
                ],
            )

    def sync_wallet_registry(self, wallets: list[dict]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            for wallet in wallets:
                address = str(wallet.get("address") or "").strip().lower()
                if not address:
                    continue
                conn.execute(
                    """
                    INSERT INTO tracked_wallet_registry (
                        normalized_address,
                        display_label,
                        enabled,
                        sync_status,
                        config_json,
                        updated_at
                    )
                    VALUES (?, ?, ?, 'pending', ?, ?)
                    ON CONFLICT(normalized_address) DO UPDATE SET
                        display_label = excluded.display_label,
                        enabled = excluded.enabled,
                        config_json = excluded.config_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        address,
                        str(wallet.get("label") or address),
                        1 if wallet.get("enabled") else 0,
                        json.dumps(wallet),
                        now,
                    ),
                )

    def set_wallet_sync_state(
        self,
        wallet_address: str,
        status: str,
        *,
        last_synced_at: str | None = None,
        error: str | None = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE tracked_wallet_registry
                SET sync_status = ?,
                    last_synced_at = COALESCE(?, last_synced_at),
                    last_error = ?,
                    updated_at = ?
                WHERE normalized_address = ?
                """,
                (
                    status,
                    last_synced_at,
                    error,
                    datetime.now(timezone.utc).isoformat(),
                    str(wallet_address or "").lower(),
                ),
            )

    def insert_wallet_execution_fills(self, fills: list[dict]) -> int:
        if not fills:
            return 0
        imported_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            before = conn.total_changes
            conn.executemany(
                """
                INSERT OR IGNORE INTO wallet_execution_fills (
                    fill_id,
                    wallet_address,
                    transaction_hash,
                    condition_id,
                    outcome_id,
                    side,
                    shares,
                    price,
                    usd_amount,
                    executed_at,
                    event_slug,
                    market_slug,
                    market_title,
                    outcome,
                    fill_json,
                    imported_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        fill["fill_id"],
                        str(fill["wallet_address"]).lower(),
                        fill.get("transaction_hash"),
                        fill["condition_id"],
                        fill["outcome_id"],
                        fill["side"],
                        fill["shares"],
                        fill["price"],
                        fill["usd_amount"],
                        fill["timestamp"],
                        fill.get("event_slug"),
                        fill.get("market_slug"),
                        fill.get("market_title"),
                        fill.get("outcome"),
                        json.dumps(fill.get("raw_fill") or {}),
                        imported_at,
                    )
                    for fill in fills
                ],
            )
            return conn.total_changes - before

    def get_wallet_execution_fills(self, wallet_address: str) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT fill_id, wallet_address, transaction_hash, condition_id,
                       outcome_id, side, shares, price, usd_amount,
                       executed_at AS timestamp, event_slug, market_slug,
                       market_title, outcome
                FROM wallet_execution_fills
                WHERE wallet_address = ?
                ORDER BY executed_at ASC, fill_id ASC
                """,
                (str(wallet_address or "").lower(),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_wallet_fill_counts(self) -> dict[str, int]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT wallet_address, COUNT(*) AS count
                FROM wallet_execution_fills
                GROUP BY wallet_address
                """
            ).fetchall()
        return {str(row["wallet_address"]).lower(): int(row["count"]) for row in rows}

    def get_open_positions_for_wallet(self, wallet_address: str) -> dict[str, dict]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT position_key, snapshot_json
                FROM tracked_positions
                WHERE wallet_address = ? AND status = 'open'
                """,
                (wallet_address,),
            ).fetchall()
        return {row["position_key"]: json.loads(row["snapshot_json"]) for row in rows}

    def get_all_open_positions(self) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT snapshot_json
                FROM tracked_positions
                WHERE status = 'open'
                ORDER BY resolution_time ASC, market_title ASC
                """
            ).fetchall()
        return [json.loads(row["snapshot_json"]) for row in rows]

    def save_open_position(self, snapshot: dict) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO tracked_positions (
                    wallet_address,
                    position_key,
                    status,
                    category,
                    league,
                    market_title,
                    outcome,
                    resolution_time,
                    first_detected_at,
                    last_seen_at,
                    last_changed_at,
                    closed_at,
                    snapshot_json
                )
                VALUES (?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                ON CONFLICT(wallet_address, position_key) DO UPDATE SET
                    status = 'open',
                    category = excluded.category,
                    league = excluded.league,
                    market_title = excluded.market_title,
                    outcome = excluded.outcome,
                    resolution_time = excluded.resolution_time,
                    first_detected_at = excluded.first_detected_at,
                    last_seen_at = excluded.last_seen_at,
                    last_changed_at = excluded.last_changed_at,
                    closed_at = NULL,
                    snapshot_json = excluded.snapshot_json
                """,
                (
                    snapshot["wallet_address"],
                    snapshot["position_key"],
                    snapshot.get("category"),
                    snapshot.get("league"),
                    snapshot.get("market_title"),
                    snapshot.get("outcome"),
                    snapshot.get("resolution_time"),
                    snapshot.get("first_detected_at"),
                    snapshot.get("last_seen_at"),
                    snapshot.get("last_changed_at"),
                    json.dumps(snapshot),
                ),
            )

    def close_position(self, snapshot: dict) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE tracked_positions
                SET status = 'closed',
                    category = ?,
                    league = ?,
                    market_title = ?,
                    outcome = ?,
                    resolution_time = ?,
                    last_seen_at = ?,
                    last_changed_at = ?,
                    closed_at = ?,
                    snapshot_json = ?
                WHERE wallet_address = ? AND position_key = ?
                """,
                (
                    snapshot.get("category"),
                    snapshot.get("league"),
                    snapshot.get("market_title"),
                    snapshot.get("outcome"),
                    snapshot.get("resolution_time"),
                    snapshot.get("last_seen_at"),
                    snapshot.get("last_changed_at"),
                    snapshot.get("closed_at"),
                    json.dumps(snapshot),
                    snapshot["wallet_address"],
                    snapshot["position_key"],
                ),
            )

    def insert_event(self, event: dict) -> bool:
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO position_events (
                    wallet_address,
                    position_key,
                    event_type,
                    event_hash,
                    detected_at,
                    category,
                    league,
                    market_title,
                    outcome,
                    event_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["wallet_address"],
                    event["position_key"],
                    event["event_type"],
                    event["event_hash"],
                    event["detected_at"],
                    event.get("category"),
                    event.get("league"),
                    event.get("market_title"),
                    event.get("outcome"),
                    json.dumps(event),
                ),
            )
            return cursor.rowcount > 0

    def get_recent_events(self, limit: int = 200) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT event_json
                FROM position_events
                ORDER BY detected_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [json.loads(row["event_json"]) for row in rows]

    def get_events_page(
        self,
        page: int = 1,
        per_page: int = 50,
        *,
        search: str = "",
        wallet: str = "",
        sport: str = "",
        league: str = "",
        event_type: str = "",
        start: str = "",
        end: str = "",
        sort: str = "desc",
    ) -> dict:
        page = max(1, int(page or 1))
        per_page = max(1, min(100, int(per_page or 50)))
        offset = (page - 1) * per_page
        where: list[str] = []
        params: list[object] = []
        if search:
            where.append("(market_title LIKE ? OR outcome LIKE ? OR event_json LIKE ?)")
            needle = f"%{search}%"
            params.extend([needle, needle, needle])
        if wallet:
            where.append("(wallet_address = ? OR event_json LIKE ?)")
            params.extend([wallet.lower(), f'%"wallet_label": "{wallet}%'])
        if sport:
            where.append("category = ?")
            params.append(sport)
        if league:
            where.append("league = ?")
            params.append(league)
        if event_type:
            where.append("event_type = ?")
            params.append(event_type)
        if start:
            where.append("detected_at >= ?")
            params.append(start)
        if end:
            where.append("detected_at <= ?")
            params.append(end)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        direction = "ASC" if str(sort).lower() == "asc" else "DESC"
        with self.connection() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS count FROM position_events {where_sql}",
                params,
            ).fetchone()["count"]
            rows = conn.execute(
                f"""
                SELECT event_json
                FROM position_events
                {where_sql}
                ORDER BY detected_at {direction}, id {direction}
                LIMIT ? OFFSET ?
                """,
                [*params, per_page, offset],
            ).fetchall()
        return {
            "data": [json.loads(row["event_json"]) for row in rows],
            "page": page,
            "per_page": per_page,
            "total": total,
            "has_next": offset + per_page < total,
            "has_prev": page > 1,
        }

    def get_events_for_wallet(
        self, wallet_address: str, limit: int = 200
    ) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT event_json
                FROM position_events
                WHERE wallet_address = ?
                ORDER BY detected_at DESC, id DESC
                LIMIT ?
                """,
                (wallet_address, limit),
            ).fetchall()
        return [json.loads(row["event_json"]) for row in rows]

    def set_refresh_state(self, key: str, value: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO refresh_state (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def get_refresh_state(self) -> dict[str, str]:
        with self.connection() as conn:
            rows = conn.execute("SELECT key, value FROM refresh_state").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def get_wallet_history_counts(self) -> dict[str, int]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT wallet_address, COUNT(*) AS count
                FROM position_events
                GROUP BY wallet_address
                """
            ).fetchall()
        return {str(row["wallet_address"]).lower(): int(row["count"]) for row in rows}

    def get_or_create_user_settings(
        self, user_id: str, default_bankroll: float, unit_percentage: float
    ) -> dict:
        if self.user_store:
            return self.user_store.get_or_create_user_settings(
                user_id, default_bankroll, unit_percentage
            )
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO user_settings (
                    user_id, starting_bankroll, trades_to_play_bankroll,
                    sizing_bankroll_configured, tracker_bankroll,
                    personal_tracker_bankroll, tracker_view, settings_version,
                    unit_percentage, updated_at
                )
                VALUES (?, ?, ?, 0, ?, ?, 'model', 1, ?, ?)
                """,
                (
                    user_id,
                    default_bankroll,
                    default_bankroll,
                    default_bankroll,
                    default_bankroll,
                    unit_percentage,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT user_id, starting_bankroll, trades_to_play_bankroll,
                       sizing_bankroll_configured, tracker_bankroll,
                       personal_tracker_bankroll, tracker_view,
                       settings_version, unit_percentage, updated_at
                FROM user_settings
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        return dict(row)

    def update_user_settings(
        self,
        user_id: str,
        starting_bankroll: float,
        unit_percentage: float,
        expected_version: int | None = None,
    ) -> dict:
        if self.user_store:
            return self.user_store.update_user_settings(
                user_id, starting_bankroll, unit_percentage, expected_version
            )
        self.get_or_create_user_settings(user_id, starting_bankroll, unit_percentage)
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            version_sql = " AND settings_version = ?" if expected_version is not None else ""
            values: list[object] = [
                starting_bankroll,
                starting_bankroll,
                unit_percentage,
                now,
                user_id,
            ]
            if expected_version is not None:
                values.append(expected_version)
            cursor = conn.execute(
                f"""
                UPDATE user_settings
                SET starting_bankroll = ?, trades_to_play_bankroll = ?,
                    sizing_bankroll_configured = 1,
                    unit_percentage = ?, updated_at = ?,
                    settings_version = settings_version + 1
                WHERE user_id = ?{version_sql}
                """,
                values,
            )
            if cursor.rowcount == 0:
                current = conn.execute(
                    "SELECT * FROM user_settings WHERE user_id = ?", (user_id,)
                ).fetchone()
                raise SettingsVersionConflict(dict(current))
        return self.get_or_create_user_settings(
            user_id, starting_bankroll, unit_percentage
        )

    def update_tracker_bankroll(self, user_id: str, tracker_bankroll: float) -> dict:
        if self.user_store:
            return self.user_store.update_tracker_bankroll(user_id, tracker_bankroll)
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE user_settings
                SET tracker_bankroll = ?, updated_at = ?,
                    settings_version = settings_version + 1
                WHERE user_id = ?
                """,
                (tracker_bankroll, now, user_id),
            )
            row = conn.execute(
                """
                SELECT user_id, starting_bankroll, trades_to_play_bankroll,
                       sizing_bankroll_configured, tracker_bankroll,
                       personal_tracker_bankroll, tracker_view,
                       settings_version, unit_percentage, updated_at
                FROM user_settings
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"User settings not found for {user_id}")
        return dict(row)

    def update_personal_tracker_bankroll(
        self, user_id: str, personal_tracker_bankroll: float
    ) -> dict:
        if self.user_store:
            return self.user_store.update_personal_tracker_bankroll(
                user_id, personal_tracker_bankroll
            )
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE user_settings
                SET personal_tracker_bankroll = ?, updated_at = ?,
                    settings_version = settings_version + 1
                WHERE user_id = ?
                """,
                (personal_tracker_bankroll, now, user_id),
            )
            if cursor.rowcount == 0:
                raise LookupError(f"User settings not found for {user_id}")
        return self.get_or_create_user_settings(user_id, personal_tracker_bankroll, 0.01)

    def update_tracker_view(self, user_id: str, tracker_view: str) -> dict:
        if self.user_store:
            return self.user_store.update_tracker_view(user_id, tracker_view)
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE user_settings
                SET tracker_view = ?, updated_at = ?,
                    settings_version = settings_version + 1
                WHERE user_id = ?
                """,
                (tracker_view, now, user_id),
            )
            if cursor.rowcount == 0:
                raise LookupError(f"User settings not found for {user_id}")
        return self.get_or_create_user_settings(user_id, 1, 0.01)

    def list_user_settings(self) -> list[dict]:
        if self.user_store:
            return self.user_store.list_user_settings()
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT user_id, starting_bankroll, trades_to_play_bankroll,
                       sizing_bankroll_configured, tracker_bankroll,
                       personal_tracker_bankroll, tracker_view,
                       settings_version, unit_percentage, updated_at
                FROM user_settings
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def create_account(
        self,
        user_id: str,
        email: str,
        password_salt: str,
        password_hash: str,
        password_iterations: int,
    ) -> dict:
        if self.user_store:
            return self.user_store.create_account(
                user_id, email, password_salt, password_hash, password_iterations
            )
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO user_accounts (
                        user_id, email, password_salt, password_hash,
                        password_iterations, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        email,
                        password_salt,
                        password_hash,
                        password_iterations,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("An account already exists for that email.") from exc
        return self.get_account_by_email(email) or {}

    def get_account_by_email(self, email: str) -> dict | None:
        if self.user_store:
            return self.user_store.get_account_by_email(email)
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM user_accounts WHERE email = ? COLLATE NOCASE",
                (email,),
            ).fetchone()
        return dict(row) if row else None

    def create_auth_session(
        self, user_id: str, token_hash: str, expires_at: str
    ) -> None:
        if self.user_store:
            self.user_store.create_auth_session(user_id, token_hash, expires_at)
            return
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO auth_sessions (token_hash, user_id, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (token_hash, user_id, expires_at, now),
            )

    def get_auth_session(self, token_hash: str) -> dict | None:
        if self.user_store:
            return self.user_store.get_auth_session(token_hash)
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT a.user_id, a.email, s.expires_at
                FROM auth_sessions s
                JOIN user_accounts a ON a.user_id = s.user_id
                WHERE s.token_hash = ? AND s.expires_at > ?
                """,
                (token_hash, now),
            ).fetchone()
        return dict(row) if row else None

    def delete_auth_session(self, token_hash: str) -> None:
        if self.user_store:
            self.user_store.delete_auth_session(token_hash)
            return
        with self.connection() as conn:
            conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,))

    def promote_tracker_records_to_global(self, global_user_id: str) -> int:
        if self.user_store:
            return self.user_store.promote_tracker_records_to_global(global_user_id)
        with self.connection() as conn:
            conn.execute(
                """
                WITH ranked AS (
                    SELECT dedupe_key, snapshot_id, status, result, settled_at,
                           created_at, updated_at, snapshot_json,
                           ROW_NUMBER() OVER (
                               PARTITION BY dedupe_key
                               ORDER BY created_at ASC, user_id ASC
                           ) AS source_rank
                    FROM bet_tracker
                    WHERE user_id <> ?
                )
                INSERT OR IGNORE INTO bet_tracker (
                    user_id, dedupe_key, snapshot_id, status, result, settled_at,
                    created_at, updated_at, snapshot_json
                )
                SELECT ?, dedupe_key, snapshot_id, status, result, settled_at,
                       created_at, updated_at, snapshot_json
                FROM ranked
                WHERE source_rank = 1
                """,
                (global_user_id, global_user_id),
            )
            row = conn.execute("SELECT changes() AS count").fetchone()
        return int(row["count"] or 0)

    def insert_tracker_snapshot(
        self,
        user_id: str,
        snapshot: dict,
        status: str = "scheduled",
        discord_payload: dict | None = None,
    ) -> bool:
        if self.user_store:
            if discord_payload is None:
                return self.user_store.insert_tracker_snapshot(user_id, snapshot, status)
            return self.user_store.insert_tracker_snapshot(
                user_id, snapshot, status, discord_payload
            )
        fraction = float(snapshot.get("final_recommended_fraction") or 0)
        amount = snapshot.get("original_displayed_amount")
        if fraction <= 1e-12 or (amount is not None and float(amount) < 0.01):
            return False
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO bet_tracker (
                    user_id, dedupe_key, snapshot_id, status, result, settled_at,
                    created_at, updated_at, snapshot_json
                )
                VALUES (?, ?, ?, ?, NULL, NULL, ?, ?, ?)
                """,
                (
                    user_id,
                    snapshot["dedupe_key"],
                    snapshot["snapshot_id"],
                    status,
                    snapshot["recommendation_timestamp"],
                    now,
                    json.dumps(snapshot),
                ),
            )
            inserted = cursor.rowcount > 0
            if inserted and discord_payload is not None:
                conn.execute(
                    """
                    INSERT INTO discord_trade_notifications (
                        user_id, dedupe_key, snapshot_id, notification_type,
                        status, attempts, payload_json, created_at, updated_at
                    ) VALUES (?, ?, ?, 'model_tracker_insert', 'pending', 0, ?, ?, ?)
                    """,
                    (
                        user_id,
                        snapshot["dedupe_key"],
                        snapshot["snapshot_id"],
                        json.dumps(discord_payload),
                        now,
                        now,
                    ),
                )
            return inserted

    def claim_discord_notifications(self, limit: int = 10) -> list[dict]:
        if self.user_store:
            return self.user_store.claim_discord_notifications(limit)
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        stale_iso = (now.replace(microsecond=0) - timedelta(minutes=10)).isoformat()
        claimed: list[dict] = []
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id
                FROM discord_trade_notifications
                WHERE (
                    status IN ('pending', 'retry')
                    AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                ) OR (status = 'sending' AND updated_at <= ?)
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (now_iso, stale_iso, max(int(limit), 1)),
            ).fetchall()
            for row in rows:
                cursor = conn.execute(
                    """
                    UPDATE discord_trade_notifications
                    SET status = 'sending', attempts = attempts + 1,
                        updated_at = ?, next_attempt_at = NULL
                    WHERE id = ? AND (
                        status IN ('pending', 'retry')
                        OR (status = 'sending' AND updated_at <= ?)
                    )
                    """,
                    (now_iso, row["id"], stale_iso),
                )
                if cursor.rowcount:
                    claimed_row = conn.execute(
                        """
                        SELECT id, attempts, payload_json
                        FROM discord_trade_notifications WHERE id = ?
                        """,
                        (row["id"],),
                    ).fetchone()
                    claimed.append(
                        {
                            "id": claimed_row["id"],
                            "attempts": claimed_row["attempts"],
                            "payload": json.loads(claimed_row["payload_json"]),
                        }
                    )
        return claimed

    def mark_discord_notification_delivered(
        self, notification_id: int, message_id: str | None, response_status: int | None
    ) -> None:
        if self.user_store:
            self.user_store.mark_discord_notification_delivered(
                notification_id, message_id, response_status
            )
            return
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE discord_trade_notifications
                SET status = 'delivered', discord_message_id = ?,
                    response_status = ?, last_error = NULL,
                    delivered_at = ?, updated_at = ?, next_attempt_at = NULL
                WHERE id = ?
                """,
                (message_id, response_status, now, now, notification_id),
            )

    def mark_discord_notification_failed(
        self,
        notification_id: int,
        error_code: str,
        response_status: int | None,
        *,
        retry_at: datetime | None = None,
        terminal: bool = False,
    ) -> None:
        if self.user_store:
            self.user_store.mark_discord_notification_failed(
                notification_id,
                error_code,
                response_status,
                retry_at=retry_at,
                terminal=terminal,
            )
            return
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE discord_trade_notifications
                SET status = ?, response_status = ?, last_error = ?,
                    next_attempt_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    "failed" if terminal else "retry",
                    response_status,
                    str(error_code)[:80],
                    retry_at.astimezone(timezone.utc).isoformat() if retry_at else None,
                    now,
                    notification_id,
                ),
            )

    def get_discord_notification_stats(self) -> dict[str, int]:
        if self.user_store:
            return self.user_store.get_discord_notification_stats()
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM discord_trade_notifications GROUP BY status
                """
            ).fetchall()
        stats = {"pending": 0, "sending": 0, "retry": 0, "delivered": 0, "failed": 0}
        stats.update({str(row["status"]): int(row["count"]) for row in rows})
        return stats

    def get_discord_notification(self, user_id: str, dedupe_key: str) -> dict | None:
        if self.user_store:
            return self.user_store.get_discord_notification(user_id, dedupe_key)
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT id, status, attempts, payload_json, discord_message_id,
                       response_status, last_error, next_attempt_at,
                       created_at, updated_at, delivered_at
                FROM discord_trade_notifications
                WHERE user_id = ? AND dedupe_key = ?
                """,
                (user_id, dedupe_key),
            ).fetchone()
        if row is None:
            return None
        payload = dict(row)
        payload["payload"] = json.loads(payload.pop("payload_json"))
        return payload

    def get_tracker_records(self, user_id: str) -> list[dict]:
        if self.user_store:
            return self.user_store.get_tracker_records(user_id)
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT dedupe_key, snapshot_id, status, result, settled_at,
                       created_at, updated_at, snapshot_json
                FROM bet_tracker
                WHERE user_id = ?
                ORDER BY created_at ASC
                """,
                (user_id,),
            ).fetchall()
        return [
            {
                "dedupe_key": row["dedupe_key"],
                "snapshot_id": row["snapshot_id"],
                "status": row["status"],
                "result": row["result"],
                "settled_at": row["settled_at"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "snapshot": json.loads(row["snapshot_json"]),
            }
            for row in rows
        ]

    def get_tracker_record(self, user_id: str, dedupe_key: str) -> dict | None:
        if self.user_store:
            return self.user_store.get_tracker_record(user_id, dedupe_key)
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT dedupe_key, snapshot_id, status, result, settled_at,
                       created_at, updated_at, snapshot_json
                FROM bet_tracker
                WHERE user_id = ? AND dedupe_key = ?
                """,
                (user_id, dedupe_key),
            ).fetchone()
        if row is None:
            return None
        return {
            "dedupe_key": row["dedupe_key"],
            "snapshot_id": row["snapshot_id"],
            "status": row["status"],
            "result": row["result"],
            "settled_at": row["settled_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "snapshot": json.loads(row["snapshot_json"]),
        }

    def set_tracking_job_state(self, state: dict) -> None:
        if self.user_store:
            self.user_store.set_tracking_job_state(state)
            return
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO tracking_job_state (key, value_json, updated_at)
                VALUES ('model_tracker', ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (json.dumps(state), now),
            )

    def get_tracking_job_state(self) -> dict:
        if self.user_store:
            return self.user_store.get_tracking_job_state()
        with self.connection() as conn:
            row = conn.execute(
                "SELECT value_json FROM tracking_job_state WHERE key = 'model_tracker'"
            ).fetchone()
        return json.loads(row["value_json"]) if row else {}

    def replace_tracking_rejections(self, user_id: str, rows: list[dict]) -> None:
        if self.user_store:
            self.user_store.replace_tracking_rejections(user_id, rows)
            return
        with self.connection() as conn:
            conn.execute(
                "DELETE FROM tracking_rejections WHERE user_id = ?", (user_id,)
            )
            conn.executemany(
                """
                INSERT INTO tracking_rejections (
                    user_id, dedupe_key, rejection_reason,
                    last_evaluated_at, evaluation_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        user_id,
                        row["recommendation_idempotency_key"],
                        row["rejection_reason"],
                        row["last_evaluated_at"],
                        json.dumps(row),
                    )
                    for row in rows
                ],
            )

    def get_tracking_rejections(self, user_id: str) -> list[dict]:
        if self.user_store:
            return self.user_store.get_tracking_rejections(user_id)
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT evaluation_json
                FROM tracking_rejections
                WHERE user_id = ?
                ORDER BY last_evaluated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [json.loads(row["evaluation_json"]) for row in rows]

    def get_active_tracker_records(self) -> list[dict]:
        if self.user_store:
            return self.user_store.get_active_tracker_records()
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT user_id, dedupe_key, status, snapshot_json
                FROM bet_tracker
                WHERE status IN ('scheduled', 'live', 'unresolved')
                """
            ).fetchall()
        return [
            {
                "user_id": row["user_id"],
                "dedupe_key": row["dedupe_key"],
                "status": row["status"],
                "snapshot": json.loads(row["snapshot_json"]),
            }
            for row in rows
        ]

    def update_tracker_status(
        self,
        user_id: str,
        dedupe_key: str,
        status: str,
        result: str | None,
        settled_at: str | None,
    ) -> None:
        if self.user_store:
            self.user_store.update_tracker_status(
                user_id, dedupe_key, status, result, settled_at
            )
            return
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE bet_tracker
                SET status = ?, result = ?, settled_at = ?, updated_at = ?
                WHERE user_id = ? AND dedupe_key = ?
                """,
                (
                    status,
                    result,
                    settled_at,
                    datetime.now(timezone.utc).isoformat(),
                    user_id,
                    dedupe_key,
                ),
            )

    def hide_trade(self, user_id: str, trade: dict) -> dict:
        if self.user_store:
            return self.user_store.hide_trade(user_id, trade)
        now = datetime.now(timezone.utc).isoformat()
        values = (
            user_id,
            trade["canonical_event_id"],
            trade["canonical_market_id"],
            trade.get("market_line") or "",
            trade["canonical_outcome_id"],
            trade.get("event_title"),
            trade.get("market_title"),
            trade.get("selection"),
            trade.get("event_start_time"),
            now,
            now,
            now,
        )
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO hidden_trades (
                    user_id, canonical_event_id, canonical_market_id,
                    market_line, canonical_outcome_id, event_title, market_title,
                    selection, event_start_time, hidden_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (
                    user_id, canonical_event_id, canonical_market_id,
                    market_line, canonical_outcome_id
                ) DO UPDATE SET
                    event_title = excluded.event_title,
                    market_title = excluded.market_title,
                    selection = excluded.selection,
                    event_start_time = excluded.event_start_time,
                    updated_at = excluded.updated_at
                """,
                values,
            )
            row = conn.execute(
                """
                SELECT * FROM hidden_trades
                WHERE user_id = ? AND canonical_event_id = ?
                  AND canonical_market_id = ? AND market_line = ?
                  AND canonical_outcome_id = ?
                """,
                values[:5],
            ).fetchone()
        return dict(row)

    def get_hidden_trades(self, user_id: str) -> list[dict]:
        if self.user_store:
            return self.user_store.get_hidden_trades(user_id)
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM hidden_trades
                WHERE user_id = ?
                ORDER BY hidden_at DESC, id DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def restore_hidden_trade(self, user_id: str, hidden_id: int) -> bool:
        if self.user_store:
            return self.user_store.restore_hidden_trade(user_id, hidden_id)
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM hidden_trades WHERE user_id = ? AND id = ?",
                (user_id, hidden_id),
            )
            return cursor.rowcount > 0

    def restore_all_hidden_trades(self, user_id: str) -> int:
        if self.user_store:
            return self.user_store.restore_all_hidden_trades(user_id)
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM hidden_trades WHERE user_id = ?", (user_id,)
            )
            return cursor.rowcount

    def pin_whiteboard_trade(self, user_id: str, pin: dict) -> dict:
        if self.user_store:
            return self.user_store.pin_whiteboard_trade(user_id, pin)
        now = datetime.now(timezone.utc).isoformat()
        values = (
            user_id,
            pin["canonical_event_id"],
            pin["canonical_market_id"],
            pin.get("market_line") or "",
            pin["canonical_outcome_id"],
            pin.get("market_type"),
            pin.get("period"),
            json.dumps(pin["snapshot"], sort_keys=True),
            now,
            now,
            now,
        )
        with self.connection() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO whiteboard_pins (
                        user_id, canonical_event_id, canonical_market_id,
                        market_line, canonical_outcome_id, market_type, period,
                        snapshot_json, pinned_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
            except sqlite3.IntegrityError:
                pass
            row = conn.execute(
                """
                SELECT * FROM whiteboard_pins
                WHERE user_id = ? AND canonical_event_id = ?
                  AND canonical_market_id = ? AND market_line = ?
                  AND canonical_outcome_id = ? AND archived_at IS NULL
                """,
                values[:5],
            ).fetchone()
        result = dict(row)
        result["snapshot"] = json.loads(result.pop("snapshot_json"))
        return result

    def get_whiteboard_pins(self, user_id: str, active_only: bool = True) -> list[dict]:
        if self.user_store:
            return self.user_store.get_whiteboard_pins(user_id, active_only)
        clause = "AND archived_at IS NULL" if active_only else ""
        with self.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM whiteboard_pins
                WHERE user_id = ? {clause}
                ORDER BY pinned_at DESC, id DESC
                """,
                (user_id,),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["snapshot"] = json.loads(item.pop("snapshot_json"))
            results.append(item)
        return results

    def get_all_active_whiteboard_pins(self) -> list[dict]:
        if self.user_store:
            return self.user_store.get_all_active_whiteboard_pins()
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM whiteboard_pins WHERE archived_at IS NULL"
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["snapshot"] = json.loads(item.pop("snapshot_json"))
            results.append(item)
        return results

    def archive_whiteboard_pin(
        self, user_id: str, pin_id: int, reason: str
    ) -> bool:
        if self.user_store:
            return self.user_store.archive_whiteboard_pin(user_id, pin_id, reason)
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE whiteboard_pins
                SET archived_at = ?, archive_reason = ?, updated_at = ?
                WHERE user_id = ? AND id = ? AND archived_at IS NULL
                """,
                (now, reason, now, user_id, pin_id),
            )
            return cursor.rowcount > 0

    def insert_personal_bet_fill(
        self, user_id: str, fill: dict, status: str = "scheduled"
    ) -> dict:
        if self.user_store:
            return self.user_store.insert_personal_bet_fill(user_id, fill, status)
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO personal_bet_fills (
                    fill_id, user_id, canonical_event_id, canonical_event_slug,
                    canonical_market_id, canonical_market_slug, market_line,
                    canonical_outcome_id, event_title, market_title, selection,
                    event_start_time, market_url, entry_price, shares,
                    position_cost, fees, total_paid, status, result, settled_at,
                    sportsbook, tags_json, sharp_snapshot_json, created_at, updated_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    NULL, NULL, ?, ?, ?, ?, ?
                )
                """,
                (
                    fill["fill_id"],
                    user_id,
                    fill["canonical_event_id"],
                    fill.get("canonical_event_slug"),
                    fill["canonical_market_id"],
                    fill.get("canonical_market_slug"),
                    fill.get("market_line") or "",
                    fill["canonical_outcome_id"],
                    fill.get("event_title"),
                    fill.get("market_title"),
                    fill.get("selection"),
                    fill.get("event_start_time"),
                    fill.get("market_url"),
                    fill["entry_price"],
                    fill["shares"],
                    fill["position_cost"],
                    fill.get("fees") or 0,
                    fill["total_paid"],
                    status,
                    fill.get("sportsbook") or "Polymarket",
                    json.dumps(fill.get("tags") or []),
                    json.dumps(fill.get("sharp_snapshot") or {}),
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM personal_bet_fills WHERE fill_id = ? AND user_id = ?",
                (fill["fill_id"], user_id),
            ).fetchone()
        return dict(row)

    def get_personal_bet_fills(
        self, user_id: str, *, active_only: bool = False
    ) -> list[dict]:
        if self.user_store:
            return self.user_store.get_personal_bet_fills(
                user_id, active_only=active_only
            )
        where = (
            "AND status IN ('scheduled', 'live', 'unresolved')" if active_only else ""
        )
        with self.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM personal_bet_fills
                WHERE user_id = ? {where}
                ORDER BY created_at ASC, fill_id ASC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def insert_personal_position_exit(self, user_id: str, record: dict) -> dict:
        if self.user_store:
            return self.user_store.insert_personal_position_exit(user_id, record)
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO personal_position_exits (
                        exit_id, user_id, idempotency_key, canonical_event_id,
                        canonical_market_id, market_line, canonical_outcome_id,
                        sportsbook, shares_sold, sell_price, gross_proceeds,
                        fees, net_proceeds, sold_at, mode, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["exit_id"], user_id, record["idempotency_key"],
                        record["canonical_event_id"], record["canonical_market_id"],
                        record.get("market_line") or "", record["canonical_outcome_id"],
                        record["sportsbook"], record["shares_sold"], record["sell_price"],
                        record["gross_proceeds"], record.get("fees") or 0,
                        record["net_proceeds"], record["sold_at"],
                        record.get("mode") or "tracker_only", now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("This exit was already recorded.") from exc
            row = conn.execute(
                "SELECT * FROM personal_position_exits WHERE exit_id = ? AND user_id = ?",
                (record["exit_id"], user_id),
            ).fetchone()
        return dict(row)

    def get_personal_position_exits(self, user_id: str) -> list[dict]:
        if self.user_store:
            return self.user_store.get_personal_position_exits(user_id)
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT * FROM personal_position_exits
                   WHERE user_id = ? ORDER BY sold_at ASC, exit_id ASC""",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_all_active_personal_bet_fills(self) -> list[dict]:
        if self.user_store:
            return self.user_store.get_all_active_personal_bet_fills()
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM personal_bet_fills
                WHERE status IN ('scheduled', 'live', 'unresolved')
                ORDER BY created_at ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def cancel_personal_bet_fill(self, user_id: str, fill_id: str) -> bool:
        if self.user_store:
            return self.user_store.cancel_personal_bet_fill(user_id, fill_id)
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE personal_bet_fills
                SET status = 'canceled', result = 'Canceled', settled_at = ?,
                    updated_at = ?
                WHERE user_id = ? AND fill_id = ?
                  AND status IN ('scheduled', 'live', 'unresolved')
                """,
                (now, now, user_id, fill_id),
            )
            return cursor.rowcount > 0

    def update_personal_bet_status(
        self,
        fill_id: str,
        status: str,
        result: str | None,
        settled_at: str | None,
    ) -> None:
        if self.user_store:
            self.user_store.update_personal_bet_status(
                fill_id, status, result, settled_at
            )
            return
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE personal_bet_fills
                SET status = ?, result = ?, settled_at = ?, updated_at = ?
                WHERE fill_id = ?
                """,
                (
                    status,
                    result,
                    settled_at,
                    datetime.now(timezone.utc).isoformat(),
                    fill_id,
                ),
            )

    def insert_clv_quote(self, quote: dict) -> bool:
        if self.user_store:
            return self.user_store.insert_clv_quote(quote)
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO clv_quote_snapshots (
                    provider, provider_event_id, provider_market_id,
                    provider_selection_id, quote_timestamp, provider_status,
                    best_bid, best_ask, midpoint, last_trade, depth_json,
                    source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    quote["provider"], quote["provider_event_id"],
                    quote["provider_market_id"], quote["provider_selection_id"],
                    quote["quote_timestamp"], quote.get("provider_status"),
                    quote.get("best_bid"), quote.get("best_ask"),
                    quote.get("midpoint"), quote.get("last_trade"),
                    json.dumps(quote.get("depth") or []), quote["source"],
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return cursor.rowcount > 0

    def get_clv_quotes(
        self, provider: str, market_id: str, selection_id: str
    ) -> list[dict]:
        if self.user_store:
            return self.user_store.get_clv_quotes(provider, market_id, selection_id)
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT * FROM clv_quote_snapshots
                   WHERE provider = ? AND provider_market_id = ?
                     AND provider_selection_id = ?
                   ORDER BY quote_timestamp ASC""",
                (provider, market_id, selection_id),
            ).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row["depth"] = json.loads(row.pop("depth_json"))
        return result

    def insert_closing_line(self, snapshot: dict) -> bool:
        if self.user_store:
            return self.user_store.insert_closing_line(snapshot)
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO closing_line_snapshots (
                    tracker_type, tracker_record_id, user_id, provider,
                    provider_event_id, provider_market_id, provider_selection_id,
                    entry_price, entry_native_odds, entry_implied_probability,
                    entry_stake, closing_snapshot_timestamp,
                    official_event_start_timestamp, closing_effective_price,
                    closing_midpoint, clv_cents, clv_probability_points, clv_pct,
                    midpoint_clv_pct, clv_status, clv_unavailable_reason,
                    snapshot_json, calculation_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._closing_line_values(snapshot),
            )
        return cursor.rowcount > 0

    def get_closing_lines(self, tracker_type: str, user_id: str) -> list[dict]:
        if self.user_store:
            return self.user_store.get_closing_lines(tracker_type, user_id)
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT * FROM closing_line_snapshots
                   WHERE tracker_type = ? AND user_id = ?
                   ORDER BY created_at ASC""",
                (tracker_type, user_id),
            ).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row.update(json.loads(row.pop("snapshot_json")))
        return result

    def clv_diagnostics(self) -> dict:
        if self.user_store:
            return self.user_store.clv_diagnostics()
        with self.connection() as conn:
            monitored = conn.execute(
                """SELECT COUNT(*) AS count FROM bet_tracker
                   WHERE status IN ('scheduled', 'live', 'unresolved')"""
            ).fetchone()["count"] + conn.execute(
                """SELECT COUNT(*) AS count FROM personal_bet_fills
                   WHERE status IN ('scheduled', 'live', 'unresolved')"""
            ).fetchone()["count"]
            quote = conn.execute(
                "SELECT MAX(quote_timestamp) AS timestamp FROM clv_quote_snapshots"
            ).fetchone()["timestamp"]
            counts = conn.execute(
                """SELECT clv_status, COUNT(*) AS count
                   FROM closing_line_snapshots GROUP BY clv_status"""
            ).fetchall()
        by_status = {row["clv_status"]: row["count"] for row in counts}
        return {
            "markets_currently_monitored": monitored,
            "last_snapshot_time": quote,
            "closing_snapshots_captured": by_status.get("captured", 0),
            "failed_captures": sum(value for key, value in by_status.items() if key not in {"captured", "pending"}),
            "stale_quotes": by_status.get("stale_quote", 0),
            "missing_provider_mappings": by_status.get("market_mapping_error", 0),
        }

    @staticmethod
    def _closing_line_values(snapshot: dict) -> tuple:
        return (
            snapshot["tracker_type"], snapshot["tracker_record_id"],
            snapshot["user_id"], snapshot["provider"],
            snapshot["provider_event_id"], snapshot["provider_market_id"],
            snapshot["provider_selection_id"], snapshot.get("entry_price"),
            snapshot.get("entry_native_odds"), snapshot.get("entry_implied_probability"),
            snapshot.get("entry_stake"), snapshot.get("closing_snapshot_timestamp"),
            snapshot.get("official_event_start_timestamp"),
            snapshot.get("closing_effective_price"), snapshot.get("closing_midpoint"),
            snapshot.get("clv_cents"), snapshot.get("clv_probability_points"),
            snapshot.get("clv_pct"), snapshot.get("midpoint_clv_pct"),
            snapshot["clv_status"], snapshot.get("clv_unavailable_reason"),
            json.dumps(snapshot), snapshot["calculation_version"],
            datetime.now(timezone.utc).isoformat(),
        )

    def record_candidate(self, record: dict) -> dict:
        if self.user_store:
            return self.user_store.record_candidate(record)
        now = record["detected_at"]
        versions = record["versions"]
        reasons_json = json.dumps(record["reason_codes"], sort_keys=True)
        decision_snapshot = {
            "candidate_id": record["candidate_id"],
            "correlation_id": record["correlation_id"],
            "decision": record["decision"],
            "reason_codes": record["reason_codes"],
            "execution_snapshot": record["execution_snapshot"],
            "versions": versions,
        }
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO candidate_ledger(
                    candidate_id, correlation_id, canonical_event_id,
                    canonical_market_id, canonical_outcome_id, period,
                    market_line, provider, settlement_scope, settlement_rules,
                    detected_at, first_seen_at, last_seen_at, event_start_time,
                    sport, league, event_title, market_title, selection,
                    current_decision, current_reason_codes_json,
                    execution_snapshot_json, candidate_snapshot_json,
                    trade_scoring_version, recommendation_version,
                    fair_price_version, kelly_version, risk_policy_version,
                    wallet_registry_version, execution_plan_version,
                    composite_price_status, composite_price_missing_reason
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(candidate_id) DO UPDATE SET
                    last_seen_at = excluded.last_seen_at,
                    current_decision = excluded.current_decision,
                    current_reason_codes_json = excluded.current_reason_codes_json
                """,
                (
                    record["candidate_id"], record["correlation_id"],
                    record["canonical_event_id"], record["canonical_market_id"],
                    record["canonical_outcome_id"], record["period"],
                    record["market_line"], record["provider"],
                    record["settlement_scope"], record["settlement_rules"],
                    now, now, now, record.get("event_start_time"),
                    record.get("sport"), record.get("league"),
                    record.get("event_title"), record.get("market_title"),
                    record.get("selection"), record["decision"], reasons_json,
                    json.dumps(record["execution_snapshot"], sort_keys=True),
                    json.dumps(record["candidate_snapshot"], sort_keys=True),
                    versions["trade_scoring"], versions["recommendation"],
                    versions["fair_price"], versions["kelly"],
                    versions["risk_policy"], versions["wallet_registry"],
                    versions["execution_plan"], record["composite_price_status"],
                    record.get("composite_price_missing_reason"),
                ),
            )
            did = decision_id(record)
            conn.execute(
                """
                INSERT OR IGNORE INTO candidate_decisions(
                    decision_id, candidate_id, correlation_id, decision,
                    reason_codes_json, primary_reason_code, decided_at,
                    decision_snapshot_json, recommendation_version,
                    calculation_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    did, record["candidate_id"], record["correlation_id"],
                    record["decision"], reasons_json,
                    record["reason_codes"][0] if record["reason_codes"] else None,
                    now, json.dumps(decision_snapshot, sort_keys=True),
                    versions["recommendation"], versions["candidate_ledger"],
                ),
            )
            if record["decision"] in {"PASSED", "RESEARCH_ONLY"}:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO candidate_monitoring(
                        candidate_id, monitoring_status, exchange_clv_status,
                        composite_clv_status, hypothetical_stake, missing_reason,
                        snapshot_json, updated_at
                    ) VALUES (?, 'MONITORING', 'PENDING', 'UNAVAILABLE', ?, ?, '{}', ?)
                    """,
                    (
                        record["candidate_id"], 100.0,
                        "NO_CONNECTED_INDEPENDENT_COMPOSITE_PROVIDER", now,
                    ),
                )
        return self.get_candidate(record["candidate_id"]) or {}

    def upsert_dual_clv(self, measurement: dict) -> None:
        if self.user_store:
            self.user_store.upsert_dual_clv(measurement)
            return
        now = datetime.now(timezone.utc).isoformat()
        measurement_id = stable_hash(
            measurement["tracker_type"], measurement["tracker_record_id"]
        )
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO dual_clv_measurements(
                    measurement_id, tracker_type, tracker_record_id, user_id,
                    candidate_id, entry_price, exchange_closing_price,
                    composite_closing_probability,
                    exchange_probability_point_clv,
                    exchange_stake_return_clv,
                    composite_probability_point_clv,
                    composite_stake_return_clv, execution_loss,
                    fee_adjusted_clv, exchange_clv_status,
                    composite_clv_status, exchange_missing_reason,
                    composite_missing_reason, closing_timestamp,
                    exchange_calculation_version,
                    composite_calculation_version, snapshot_json,
                    created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(tracker_type, tracker_record_id) DO UPDATE SET
                    exchange_closing_price = excluded.exchange_closing_price,
                    composite_closing_probability = excluded.composite_closing_probability,
                    exchange_probability_point_clv = excluded.exchange_probability_point_clv,
                    exchange_stake_return_clv = excluded.exchange_stake_return_clv,
                    composite_probability_point_clv = excluded.composite_probability_point_clv,
                    composite_stake_return_clv = excluded.composite_stake_return_clv,
                    execution_loss = excluded.execution_loss,
                    fee_adjusted_clv = excluded.fee_adjusted_clv,
                    exchange_clv_status = excluded.exchange_clv_status,
                    composite_clv_status = excluded.composite_clv_status,
                    exchange_missing_reason = excluded.exchange_missing_reason,
                    composite_missing_reason = excluded.composite_missing_reason,
                    closing_timestamp = excluded.closing_timestamp,
                    snapshot_json = excluded.snapshot_json,
                    updated_at = excluded.updated_at
                """,
                (
                    measurement_id, measurement["tracker_type"],
                    measurement["tracker_record_id"], measurement["user_id"],
                    measurement.get("candidate_id"), measurement.get("entry_price"),
                    measurement.get("exchange_closing_price"),
                    measurement.get("composite_closing_probability"),
                    measurement.get("exchange_probability_point_clv"),
                    measurement.get("exchange_stake_return_clv"),
                    measurement.get("composite_probability_point_clv"),
                    measurement.get("composite_stake_return_clv"),
                    measurement.get("execution_loss"), measurement.get("fee_adjusted_clv"),
                    measurement.get("exchange_clv_status", "PENDING"),
                    measurement.get("composite_clv_status", "UNAVAILABLE"),
                    measurement.get("exchange_missing_reason"),
                    measurement.get("composite_missing_reason", "NO_CONNECTED_INDEPENDENT_COMPOSITE_PROVIDER"),
                    measurement.get("closing_timestamp"),
                    measurement.get("exchange_calculation_version", "clv-v1"),
                    measurement.get("composite_calculation_version", COMPOSITE_CLV_VERSION),
                    json.dumps(measurement.get("snapshot") or {}, sort_keys=True),
                    now, now,
                ),
            )

    def get_dual_clv_measurements(self, tracker_type: str, user_id: str) -> list[dict]:
        if self.user_store:
            return self.user_store.get_dual_clv_measurements(tracker_type, user_id)
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT * FROM dual_clv_measurements
                   WHERE tracker_type = ? AND user_id = ?
                   ORDER BY created_at ASC""",
                (tracker_type, user_id),
            ).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row["snapshot"] = json.loads(row.pop("snapshot_json") or "{}")
        return result

    def record_candidate_price_observation(
        self,
        candidate_id: str,
        entry_price: float | None,
        observed_price: float | None,
    ) -> None:
        if self.user_store:
            self.user_store.record_candidate_price_observation(
                candidate_id, entry_price, observed_price
            )
            return
        try:
            entry = float(entry_price)
            observed = float(observed_price)
        except (TypeError, ValueError):
            return
        if not (0 < entry < 1 and 0 < observed < 1):
            return
        movement = observed - entry
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT maximum_favorable_movement, maximum_adverse_movement
                FROM candidate_monitoring WHERE candidate_id = ?
                """,
                (candidate_id,),
            ).fetchone()
            if row is None:
                return
            favorable = max(
                0.0,
                float(row["maximum_favorable_movement"] or 0.0),
                movement,
            )
            adverse = min(
                0.0,
                float(row["maximum_adverse_movement"] or 0.0),
                movement,
            )
            conn.execute(
                """
                UPDATE candidate_monitoring
                SET maximum_favorable_movement = ?,
                    maximum_adverse_movement = ?, updated_at = ?
                WHERE candidate_id = ?
                """,
                (
                    favorable,
                    adverse,
                    datetime.now(timezone.utc).isoformat(),
                    candidate_id,
                ),
            )

    def get_candidate(self, candidate_id: str) -> dict | None:
        if self.user_store:
            return self.user_store.get_candidate(candidate_id)
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM candidate_ledger WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        return self._candidate_row(dict(row)) if row else None

    def insert_composite_price_snapshot(self, snapshot: dict) -> bool:
        if self.user_store:
            return self.user_store.insert_composite_price_snapshot(snapshot)
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO composite_price_snapshots(
                    snapshot_id, candidate_id, correlation_id, quote_timestamp,
                    composite_fair_probability, source_count, source_dispersion,
                    mapping_confidence, status, missing_reason,
                    calculation_version, snapshot_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot["snapshot_id"], snapshot.get("candidate_id"),
                    snapshot["correlation_id"], snapshot["quote_timestamp"],
                    snapshot.get("composite_fair_probability"),
                    snapshot.get("source_count", 0), snapshot.get("source_dispersion"),
                    snapshot["mapping_confidence"], snapshot["status"],
                    snapshot.get("missing_reason"), snapshot["calculation_version"],
                    json.dumps(snapshot.get("snapshot") or {}, sort_keys=True),
                    snapshot["created_at"],
                ),
            )
            inserted = cursor.rowcount > 0
            conn.executemany(
                """
                INSERT OR IGNORE INTO composite_source_contributions(
                    snapshot_id, provider, provider_event_id, provider_market_id,
                    provider_selection_id, native_odds, decimal_odds,
                    raw_implied_probability, no_vig_probability,
                    contribution_weight, quote_timestamp, quote_freshness,
                    included, exclusion_reason, source_snapshot_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        snapshot["snapshot_id"], item["provider"],
                        item.get("provider_event_id"), item.get("provider_market_id"),
                        item.get("provider_selection_id"), item.get("native_odds"),
                        item.get("decimal_odds"), item.get("raw_implied_probability"),
                        item.get("no_vig_probability"), item.get("contribution_weight"),
                        item.get("quote_timestamp"), item.get("quote_freshness"),
                        int(bool(item.get("included"))), item.get("exclusion_reason"),
                        json.dumps(item.get("source_snapshot") or {}, sort_keys=True),
                    )
                    for item in snapshot.get("contributions") or []
                ],
            )
        return inserted

    def record_decision_engine_snapshot(
        self, candidate_id: str, correlation_id: str, play: dict, created_at: str
    ) -> None:
        if self.user_store:
            self.user_store.record_decision_engine_snapshot(
                candidate_id, correlation_id, play, created_at
            )
            return
        quality = play.get("trade_quality") or {}
        components = quality.get("components") or {}
        liquidity = play.get("liquidity_quality") or {}
        opposition = play.get("weighted_opposition") or {}
        independence = play.get("independent_sharp_signal") or {}
        quality_id = stable_hash(candidate_id, quality.get("calculation_version"), created_at)
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO trade_quality_snapshots(
                    snapshot_id, candidate_id, correlation_id, score, grade,
                    uncapped_grade, signal_points, price_points, liquidity_points,
                    context_points, fair_price_status, calculation_version,
                    snapshot_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    quality_id, candidate_id, correlation_id, quality.get("score", 0),
                    quality.get("grade", "PASS"), quality.get("uncapped_grade", "PASS"),
                    components.get("signal", 0), components.get("price", 0),
                    components.get("liquidity", 0), components.get("context", 0),
                    (play.get("fair_price") or {}).get("status", "UNAVAILABLE"),
                    quality.get("calculation_version", "trade-quality-v2"),
                    json.dumps(quality, sort_keys=True), created_at,
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO liquidity_quality_snapshots(
                    snapshot_id, candidate_id, status, score, spread,
                    top_depth_dollars, ladder_depth_dollars, calculation_version,
                    snapshot_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stable_hash(quality_id, "liquidity"), candidate_id,
                    liquidity.get("status", "UNAVAILABLE"), liquidity.get("score", 0),
                    liquidity.get("spread"), liquidity.get("top_depth_dollars"),
                    liquidity.get("ladder_depth_dollars"),
                    liquidity.get("calculation_version", "liquidity-quality-v2"),
                    json.dumps(liquidity, sort_keys=True), created_at,
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO opposition_snapshots(
                    snapshot_id, candidate_id, raw_count, weighted_opposition,
                    penalty, action, calculation_version, snapshot_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stable_hash(quality_id, "opposition"), candidate_id,
                    opposition.get("raw_count", 0), opposition.get("weighted_opposition", 0),
                    opposition.get("penalty", 0), opposition.get("action", "NOTE_ONLY"),
                    opposition.get("calculation_version", "weighted-opposition-v2"),
                    json.dumps(opposition, sort_keys=True), created_at,
                ),
            )
            for detail in independence.get("details") or []:
                dependency = detail.get("dependency") or {}
                conn.execute(
                    """
                    INSERT OR IGNORE INTO wallet_dependency_edges(
                        edge_id, candidate_id, source_wallet_id, target_wallet_id,
                        dependency_type, dependency_weight, evidence_json,
                        calculation_version, observed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stable_hash(quality_id, detail.get("wallet_id"), dependency),
                        candidate_id, detail.get("wallet_id"), dependency.get("target_wallet_id"),
                        dependency.get("type") or ("INDEPENDENT" if not dependency else "OBSERVED_DEPENDENCY"),
                        detail.get("weight", 0), json.dumps(dependency, sort_keys=True),
                        independence.get("calculation_version", "sharp-independence-v2"), created_at,
                    ),
                )

    def decision_engine_diagnostics(self) -> dict:
        if self.user_store:
            return self.user_store.decision_engine_diagnostics()
        tables = (
            "trade_quality_snapshots", "liquidity_quality_snapshots",
            "wallet_dependency_edges", "opposition_snapshots",
        )
        with self.connection() as conn:
            counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
            grades = [dict(row) for row in conn.execute(
                "SELECT grade, COUNT(*) count FROM trade_quality_snapshots GROUP BY grade"
            )]
            migrations = [dict(row) for row in conn.execute(
                "SELECT version, applied_at FROM schema_migrations ORDER BY version"
            )]
        return {
            "table_counts": counts,
            "grade_counts": grades,
            "migrations": migrations,
            "fabricated_provider_data": False,
        }

    def get_bankroll_bucket_config(self, user_id: str) -> dict:
        if self.user_store:
            return self.user_store.get_bankroll_bucket_config(user_id)
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO bankroll_bucket_configs(
                    user_id, core_allocation, discovery_allocation,
                    liquidity_reserve_allocation, operational_buffer_allocation,
                    combine_model_and_personal, config_version, updated_at
                ) VALUES (?, 0.70, 0.10, 0.15, 0.05, 1, 'bankroll-buckets-v3', ?)
                """,
                (user_id, now),
            )
            row = conn.execute(
                "SELECT * FROM bankroll_bucket_configs WHERE user_id = ?", (user_id,)
            ).fetchone()
        result = dict(row)
        result["combine_model_and_personal"] = bool(result["combine_model_and_personal"])
        return result

    def update_bankroll_bucket_config(self, user_id: str, values: dict) -> dict:
        if self.user_store:
            return self.user_store.update_bankroll_bucket_config(user_id, values)
        keys = (
            "core_allocation", "discovery_allocation",
            "liquidity_reserve_allocation", "operational_buffer_allocation",
        )
        allocations = {key: float(values[key]) for key in keys}
        if any(value < 0 or value > 1 for value in allocations.values()) or abs(sum(allocations.values()) - 1.0) > 1e-6:
            raise ValueError("Bankroll bucket allocations must be between zero and one and total 1.0.")
        self.get_bankroll_bucket_config(user_id)
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE bankroll_bucket_configs
                SET core_allocation = ?, discovery_allocation = ?,
                    liquidity_reserve_allocation = ?, operational_buffer_allocation = ?,
                    combine_model_and_personal = ?, config_version = 'bankroll-buckets-v3',
                    updated_at = ? WHERE user_id = ?
                """,
                (
                    allocations["core_allocation"], allocations["discovery_allocation"],
                    allocations["liquidity_reserve_allocation"], allocations["operational_buffer_allocation"],
                    int(bool(values.get("combine_model_and_personal", True))), now, user_id,
                ),
            )
        return self.get_bankroll_bucket_config(user_id)

    def get_risk_account_state(self, user_id: str, bankroll: float) -> dict:
        if self.user_store:
            return self.user_store.get_risk_account_state(user_id, bankroll)
        bankroll = max(0.0, float(bankroll))
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO risk_account_state(
                    user_id, current_bankroll, high_water_mark, state_version, updated_at
                ) VALUES (?, ?, ?, 'drawdown-protocol-v3', ?)
                """,
                (user_id, bankroll, bankroll, now),
            )
            row = conn.execute(
                "SELECT * FROM risk_account_state WHERE user_id = ?", (user_id,)
            ).fetchone()
        result = dict(row)
        for key in ("wallet_data_invalid", "provider_unreliable", "manual_kill_switch"):
            result[key] = bool(result[key])
        return result

    def update_risk_account_state(self, user_id: str, bankroll: float, values: dict) -> dict:
        if self.user_store:
            return self.user_store.update_risk_account_state(user_id, bankroll, values)
        current = self.get_risk_account_state(user_id, bankroll)
        current_bankroll = max(0.0, float(values.get("current_bankroll", current["current_bankroll"])))
        high_water = max(current_bankroll, float(values.get("high_water_mark", current["high_water_mark"])))
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE risk_account_state SET current_bankroll = ?, high_water_mark = ?,
                    recent_stake_weighted_composite_clv = ?, recent_valid_trade_count = ?,
                    material_error_count_7d = ?, wallet_data_invalid = ?, provider_unreliable = ?,
                    state_version = 'drawdown-protocol-v3', updated_at = ? WHERE user_id = ?
                """,
                (
                    current_bankroll, high_water,
                    values.get("recent_stake_weighted_composite_clv", current.get("recent_stake_weighted_composite_clv")),
                    int(values.get("recent_valid_trade_count", current.get("recent_valid_trade_count") or 0)),
                    int(values.get("material_error_count_7d", current.get("material_error_count_7d") or 0)),
                    int(bool(values.get("wallet_data_invalid", current.get("wallet_data_invalid")))),
                    int(bool(values.get("provider_unreliable", current.get("provider_unreliable")))),
                    now, user_id,
                ),
            )
        return self.get_risk_account_state(user_id, bankroll)

    def set_manual_kill_switch(
        self, user_id: str, enabled: bool, reason: str, actor: str, override: bool = False
    ) -> dict:
        if self.user_store:
            return self.user_store.set_manual_kill_switch(user_id, enabled, reason, actor, override)
        current = self.get_risk_account_state(user_id, 0)
        now = datetime.now(timezone.utc).isoformat()
        new_state = {**current, "manual_kill_switch": bool(enabled), "manual_reason": reason if enabled else None}
        audit_id = stable_hash(user_id, enabled, reason, actor, now)
        with self.connection() as conn:
            conn.execute(
                "UPDATE risk_account_state SET manual_kill_switch = ?, manual_reason = ?, updated_at = ? WHERE user_id = ?",
                (int(bool(enabled)), reason if enabled else None, now, user_id),
            )
            conn.execute(
                """
                INSERT INTO kill_switch_audit(
                    audit_id, user_id, enabled, reason_code, actor, override,
                    prior_state_json, new_state_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (audit_id, user_id, int(bool(enabled)), reason, actor, int(bool(override)), json.dumps(current, sort_keys=True), json.dumps(new_state, sort_keys=True), now),
            )
        return self.get_risk_account_state(user_id, current["current_bankroll"])

    def record_release3_snapshots(
        self, user_id: str, candidate_id: str | None, correlation_id: str | None,
        recommendation_snapshot_id: str | None, execution: dict, risk: dict, created_at: str,
    ) -> None:
        if self.user_store:
            self.user_store.record_release3_snapshots(user_id, candidate_id, correlation_id, recommendation_snapshot_id, execution, risk, created_at)
            return
        execution_id = stable_hash(candidate_id, recommendation_snapshot_id, execution.get("calculation_version"), created_at)
        risk_id = stable_hash(user_id, candidate_id, recommendation_snapshot_id, risk.get("calculation_version"), created_at)
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO execution_plan_snapshots(
                    snapshot_id, candidate_id, correlation_id, recommendation_snapshot_id,
                    recommended_stake, maximum_average_price, effective_price,
                    amount_executable_below_max, unfilled_amount, execution_method,
                    reason_code, quote_timestamp, quote_fresh, calculation_version,
                    snapshot_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    execution_id, candidate_id, correlation_id, recommendation_snapshot_id,
                    execution.get("recommended_stake", 0), execution.get("maximum_average_price"),
                    execution.get("effective_price_for_executable_amount"), execution.get("amount_executable_below_max", 0),
                    execution.get("unfilled_amount", 0), execution.get("recommended_execution_method", "PASS"),
                    execution.get("execution_reason_code", "UNKNOWN"), execution.get("quote_timestamp"),
                    int(bool(execution.get("quote_fresh"))), execution.get("calculation_version", "execution-engine-v3"),
                    json.dumps(execution, sort_keys=True), created_at,
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO portfolio_risk_snapshots(
                    snapshot_id, user_id, candidate_id, recommendation_snapshot_id,
                    bucket, risk_state, proposed_stake, final_capped_stake,
                    correlation_multiplier, reason_codes_json, calculation_version,
                    snapshot_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    risk_id, user_id, candidate_id, recommendation_snapshot_id,
                    risk.get("bucket", "CORE"), (risk.get("risk_state") or {}).get("state", "NORMAL"),
                    risk.get("recommended_before_risk", 0), risk.get("final_capped_stake", 0),
                    risk.get("correlation_multiplier", 0), json.dumps(risk.get("reason_codes") or []),
                    risk.get("calculation_version", "portfolio-risk-v3"), json.dumps(risk, sort_keys=True), created_at,
                ),
            )

    def release3_diagnostics(self) -> dict:
        if self.user_store:
            return self.user_store.release3_diagnostics()
        tables = ("execution_plan_snapshots", "portfolio_risk_snapshots", "bankroll_bucket_configs", "risk_account_state", "kill_switch_audit")
        with self.connection() as conn:
            counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
            methods = [dict(row) for row in conn.execute("SELECT execution_method, COUNT(*) count FROM execution_plan_snapshots GROUP BY execution_method")]
            states = [dict(row) for row in conn.execute("SELECT risk_state, COUNT(*) count FROM portfolio_risk_snapshots GROUP BY risk_state")]
            migrations = [dict(row) for row in conn.execute("SELECT version, applied_at FROM schema_migrations ORDER BY version")]
        return {"table_counts": counts, "execution_method_counts": methods, "risk_state_counts": states, "migrations": migrations, "fabricated_data": False}

    def list_candidates(
        self, decision: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        if self.user_store:
            return self.user_store.list_candidates(decision, limit, offset)
        query = "SELECT * FROM candidate_ledger"
        params: list[object] = []
        if decision:
            query += " WHERE current_decision = ?"
            params.append(decision)
        query += " ORDER BY last_seen_at DESC LIMIT ? OFFSET ?"
        params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._candidate_row(dict(row)) for row in rows]

    def learning_candidate_rows(self) -> list[dict]:
        if self.user_store:
            return self.user_store.learning_candidate_rows()
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT c.*, m.result, m.hypothetical_stake AS stake,
                       m.hypothetical_profit_loss AS profit_loss,
                       d.exchange_probability_point_clv AS exchange_clv,
                       d.composite_probability_point_clv AS composite_clv,
                       d.execution_loss,
                       e.execution_method, e.snapshot_json AS execution_plan_json,
                       q.grade AS trade_grade, l.status AS liquidity_grade
                FROM candidate_ledger c
                LEFT JOIN candidate_monitoring m ON m.candidate_id = c.candidate_id
                LEFT JOIN dual_clv_measurements d ON d.candidate_id = c.candidate_id
                LEFT JOIN execution_plan_snapshots e ON e.snapshot_id = (
                    SELECT e2.snapshot_id FROM execution_plan_snapshots e2
                    WHERE e2.candidate_id = c.candidate_id ORDER BY e2.created_at DESC LIMIT 1
                )
                LEFT JOIN trade_quality_snapshots q ON q.snapshot_id = (
                    SELECT q2.snapshot_id FROM trade_quality_snapshots q2
                    WHERE q2.candidate_id = c.candidate_id ORDER BY q2.created_at DESC LIMIT 1
                )
                LEFT JOIN liquidity_quality_snapshots l ON l.snapshot_id = (
                    SELECT l2.snapshot_id FROM liquidity_quality_snapshots l2
                    WHERE l2.candidate_id = c.candidate_id ORDER BY l2.created_at DESC LIMIT 1
                )
                ORDER BY c.detected_at
                """
            ).fetchall()
        output = []
        for source in rows:
            row = self._candidate_row(dict(source))
            execution = json.loads(row.pop("execution_plan_json") or "{}")
            row["execution_plan"] = execution
            row["fees"] = execution.get("expected_fees")
            row["entry_price"] = execution.get("effective_price_for_executable_amount")
            output.append(row)
        return output

    def record_edge_map(self, run: dict, segments: list[dict]) -> None:
        if self.user_store:
            self.user_store.record_edge_map(run, segments)
            return
        with self.connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO edge_map_runs(run_id, window_start, window_end, candidate_count, config_json, calculation_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run["run_id"], run.get("window_start"), run.get("window_end"), run["candidate_count"], json.dumps(run["config"], sort_keys=True), run["calculation_version"], run["created_at"]),
            )
            for row in segments:
                snapshot_id = stable_hash(run["run_id"], row["dimension"], row["segment_value"])
                conn.execute(
                    """INSERT OR REPLACE INTO edge_map_segment_snapshots(
                    snapshot_id, run_id, dimension, segment_value, candidate_count, played_count,
                    passed_count, settled_count, stake, roi, stake_weighted_exchange_clv,
                    stake_weighted_composite_clv, positive_composite_clv_rate, median_clv,
                    execution_loss, average_fees, maximum_drawdown, statistical_reliability,
                    status, snapshot_json, calculation_version, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (snapshot_id, run["run_id"], row["dimension"], row["segment_value"], row["candidate_count"], row["played_count"], row["passed_count"], row["settled_count"], row["stake"], row.get("roi"), row.get("stake_weighted_exchange_clv"), row.get("stake_weighted_composite_clv"), row.get("positive_composite_clv_rate"), row.get("median_clv"), row["execution_loss"], row.get("average_fees"), row.get("maximum_drawdown"), row["statistical_reliability"], row["status"], json.dumps(row, sort_keys=True), row["calculation_version"], run["created_at"]),
                )

    def latest_edge_map(self, dimension: str | None = None) -> dict:
        if self.user_store:
            return self.user_store.latest_edge_map(dimension)
        with self.connection() as conn:
            run = conn.execute("SELECT * FROM edge_map_runs ORDER BY created_at DESC LIMIT 1").fetchone()
            if not run:
                return {"run": None, "segments": []}
            query = "SELECT * FROM edge_map_segment_snapshots WHERE run_id = ?"
            params: list[object] = [run["run_id"]]
            if dimension:
                query += " AND dimension = ?"
                params.append(dimension)
            query += " ORDER BY candidate_count DESC, dimension, segment_value"
            segments = [dict(row) for row in conn.execute(query, params).fetchall()]
        run_row = dict(run)
        run_row["config"] = json.loads(run_row.pop("config_json") or "{}")
        for row in segments:
            row["snapshot"] = json.loads(row.pop("snapshot_json") or "{}")
        return {"run": run_row, "segments": segments}

    def create_configuration_proposal(self, values: dict, actor: str) -> dict:
        if self.user_store:
            return self.user_store.create_configuration_proposal(values, actor)
        now = datetime.now(timezone.utc).isoformat()
        proposal_id = stable_hash(
            values["segment_dimension"],
            values["segment_value"],
            values["proposal_type"],
            json.dumps(values.get("proposed_config") or {}, sort_keys=True),
            now,
        )
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO configuration_proposals(proposal_id, segment_dimension, segment_value,
                proposal_type, old_config_json, proposed_config_json, evidence_snapshot_json,
                status, created_by, created_at, updated_at, config_version_before)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'PROPOSED', ?, ?, ?, ?)""",
                (proposal_id, values["segment_dimension"], values["segment_value"], values["proposal_type"], json.dumps(values.get("old_config") or {}, sort_keys=True), json.dumps(values.get("proposed_config") or {}, sort_keys=True), json.dumps(values.get("evidence") or {}, sort_keys=True), actor, now, now, values.get("config_version_before")),
            )
        return self.get_configuration_proposal(proposal_id)

    def get_configuration_proposal(self, proposal_id: str) -> dict | None:
        if self.user_store:
            return self.user_store.get_configuration_proposal(proposal_id)
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM configuration_proposals WHERE proposal_id = ?", (proposal_id,)).fetchone()
        return self._proposal_row(dict(row)) if row else None

    def list_configuration_proposals(self) -> list[dict]:
        if self.user_store:
            return self.user_store.list_configuration_proposals()
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM configuration_proposals ORDER BY created_at DESC").fetchall()
        return [self._proposal_row(dict(row)) for row in rows]

    def review_configuration_proposal(self, proposal_id: str, status: str, actor: str, reason: str | None = None) -> dict:
        if self.user_store:
            return self.user_store.review_configuration_proposal(proposal_id, status, actor, reason)
        allowed = {"APPROVED", "REJECTED", "HOLDOUT_PENDING", "HOLDOUT_PASSED", "HOLDOUT_FAILED"}
        if status not in allowed:
            raise ValueError("Invalid proposal status.")
        current = self.get_configuration_proposal(proposal_id)
        if not current:
            raise KeyError("Proposal not found.")
        if status == "APPROVED" and current["status"] != "HOLDOUT_PASSED":
            raise ValueError("A proposal requires a passed holdout before approval.")
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            next_version = stable_hash(proposal_id, current.get("config_version_before"), "approved") if status == "APPROVED" else current.get("config_version_after")
            conn.execute("UPDATE configuration_proposals SET status = ?, approved_by = ?, rejection_reason = ?, approved_at = ?, config_version_after = ?, updated_at = ? WHERE proposal_id = ?", (status, actor if status == "APPROVED" else None, reason, now if status == "APPROVED" else None, next_version, now, proposal_id))
        return self.get_configuration_proposal(proposal_id)

    def record_holdout(self, proposal_id: str, dimension: str, value: str, baseline: dict, holdout: dict, evaluation: dict, window: dict) -> dict:
        if self.user_store:
            return self.user_store.record_holdout(proposal_id, dimension, value, baseline, holdout, evaluation, window)
        now = datetime.now(timezone.utc).isoformat()
        evaluation_id = stable_hash(proposal_id, window["holdout_start"], window["holdout_end"])
        with self.connection() as conn:
            conn.execute("""INSERT OR REPLACE INTO holdout_evaluations(evaluation_id, proposal_id, segment_dimension, segment_value, baseline_start, baseline_end, holdout_start, holdout_end, baseline_metrics_json, holdout_metrics_json, status, sample_sufficient, calculation_version, evaluated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (evaluation_id, proposal_id, dimension, value, window.get("baseline_start"), window.get("baseline_end"), window["holdout_start"], window["holdout_end"], json.dumps(baseline, sort_keys=True), json.dumps(holdout, sort_keys=True), evaluation["status"], int(evaluation["sample_sufficient"]), evaluation["calculation_version"], now))
        self.review_configuration_proposal(proposal_id, evaluation["status"], "holdout-engine")
        return {"evaluation_id": evaluation_id, **evaluation}

    def record_rule_violation(self, user_id: str, values: dict) -> dict:
        if self.user_store:
            return self.user_store.record_rule_violation(user_id, values)
        now = datetime.now(timezone.utc).isoformat()
        violation_id = stable_hash(user_id, values["trade_id"], values["warning_code"], now)
        with self.connection() as conn:
            conn.execute("""INSERT INTO rule_violations(violation_id, user_id, trade_id, candidate_id, warning_code, confirmed_action, confirmation_text, entry_price, outcome, profit_loss, exchange_clv, composite_clv, context_json, calculation_version, created_at, settled_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (violation_id, user_id, values["trade_id"], values.get("candidate_id"), values["warning_code"], values["confirmed_action"], values["confirmation_text"], values.get("entry_price"), values.get("outcome"), values.get("profit_loss"), values.get("exchange_clv"), values.get("composite_clv"), json.dumps(values.get("context") or {}, sort_keys=True), values["calculation_version"], now, now if values.get("profit_loss") is not None else None))
        return {"violation_id": violation_id, "user_id": user_id, **values, "created_at": now}

    def list_rule_violations(self, user_id: str | None = None) -> list[dict]:
        if self.user_store:
            return self.user_store.list_rule_violations(user_id)
        query, params = "SELECT * FROM rule_violations", []
        if user_id:
            query, params = query + " WHERE user_id = ?", [user_id]
        query += " ORDER BY created_at DESC"
        with self.connection() as conn:
            rows = [dict(row) for row in conn.execute(query, params).fetchall()]
        for row in rows:
            row["context"] = json.loads(row.pop("context_json") or "{}")
        return rows

    def settle_rule_violation(self, violation_id: str, values: dict) -> dict:
        if self.user_store:
            return self.user_store.settle_rule_violation(violation_id, values)
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute("UPDATE rule_violations SET outcome = ?, profit_loss = ?, exchange_clv = ?, composite_clv = ?, settled_at = ? WHERE violation_id = ?", (values.get("outcome"), values.get("profit_loss"), values.get("exchange_clv"), values.get("composite_clv"), now, violation_id))
            row = conn.execute("SELECT * FROM rule_violations WHERE violation_id = ?", (violation_id,)).fetchone()
        if not row:
            raise KeyError("Violation not found.")
        result = dict(row); result["context"] = json.loads(result.pop("context_json") or "{}")
        return result

    def release4_diagnostics(self) -> dict:
        if self.user_store:
            return self.user_store.release4_diagnostics()
        tables = ("edge_map_runs", "edge_map_segment_snapshots", "holdout_evaluations", "configuration_proposals", "rule_violations")
        with self.connection() as conn:
            counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
            statuses = [dict(row) for row in conn.execute("SELECT status, COUNT(*) count FROM edge_map_segment_snapshots GROUP BY status")]
            proposals = [dict(row) for row in conn.execute("SELECT status, COUNT(*) count FROM configuration_proposals GROUP BY status")]
        return {"table_counts": counts, "segment_status_counts": statuses, "proposal_status_counts": proposals, "production_weights_auto_changed": False, "fabricated_data": False}

    def active_segment_policies(self) -> list[dict]:
        if self.user_store: return self.user_store.active_segment_policies()
        with self.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM segment_policy_assignments WHERE status = 'ACTIVE' ORDER BY created_at")]

    def apply_configuration_proposal(self, proposal_id: str, actor: str) -> dict:
        if self.user_store: return self.user_store.apply_configuration_proposal(proposal_id, actor)
        proposal = self.get_configuration_proposal(proposal_id)
        if not proposal: raise KeyError("Proposal not found.")
        if proposal["status"] != "APPROVED": raise ValueError("Only an approved proposal can be applied.")
        multiplier = float((proposal.get("proposed_config") or {}).get("stake_multiplier", -1))
        if not 0 <= multiplier <= 1:
            raise ValueError("Applied stake_multiplier must be between 0 and 1; Release 5 cannot increase risk.")
        now = datetime.now(timezone.utc).isoformat()
        version = proposal.get("config_version_after") or stable_hash(proposal_id, "applied")
        policy_id = stable_hash(version, proposal["segment_dimension"], proposal["segment_value"])
        with self.connection() as conn:
            conn.execute("UPDATE segment_policy_assignments SET status = 'SUPERSEDED' WHERE status = 'ACTIVE' AND segment_dimension = ? AND segment_value = ?", (proposal["segment_dimension"], proposal["segment_value"]))
            conn.execute("INSERT OR REPLACE INTO production_configuration_versions(config_version, proposal_id, config_json, activated_by, activated_at, status, calculation_version) VALUES (?, ?, ?, ?, ?, 'ACTIVE', 'segment-policy-v5')", (version, proposal_id, json.dumps(proposal["proposed_config"], sort_keys=True), actor, now))
            conn.execute("INSERT OR REPLACE INTO segment_policy_assignments(policy_id, config_version, segment_dimension, segment_value, stake_multiplier, status, rationale, created_at) VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, ?)", (policy_id, version, proposal["segment_dimension"], proposal["segment_value"], multiplier, json.dumps(proposal.get("evidence") or {}, sort_keys=True), now))
            conn.execute("UPDATE configuration_proposals SET status = 'APPLIED', applied_at = ?, updated_at = ? WHERE proposal_id = ?", (now, now, proposal_id))
        return {"config_version": version, "policy_id": policy_id, "stake_multiplier": multiplier, "status": "ACTIVE", "activated_at": now}

    def record_post_change_monitoring(self, edge_map_run_id: str | None, segments: list[dict]) -> int:
        if self.user_store: return self.user_store.record_post_change_monitoring(edge_map_run_id, segments)
        policies = self.active_segment_policies(); now = datetime.now(timezone.utc).isoformat(); count = 0
        by_key = {(row["dimension"], row["segment_value"]): row for row in segments}
        with self.connection() as conn:
            for policy in policies:
                metrics = by_key.get((policy["segment_dimension"], policy["segment_value"]), {"candidate_count": 0})
                monitoring_id = stable_hash(policy["config_version"], edge_map_run_id, now)
                conn.execute("INSERT OR IGNORE INTO post_change_monitoring_runs(monitoring_id, config_version, edge_map_run_id, segment_dimension, segment_value, metrics_json, status, calculation_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'post-change-monitor-v5', ?)", (monitoring_id, policy["config_version"], edge_map_run_id, policy["segment_dimension"], policy["segment_value"], json.dumps(metrics, sort_keys=True), metrics.get("status", "INSUFFICIENT_SAMPLE"), now)); count += 1
        return count

    def completion_diagnostics(self) -> dict:
        if self.user_store: return self.user_store.completion_diagnostics()
        with self.connection() as conn:
            tables = ("production_configuration_versions", "segment_policy_assignments", "post_change_monitoring_runs")
            counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
        return {"table_counts": counts, "active_policies": self.active_segment_policies(), "risk_increasing_policies_allowed": False, "fabricated_data": False}

    @staticmethod
    def _proposal_row(row: dict) -> dict:
        for source, target in (("old_config_json", "old_config"), ("proposed_config_json", "proposed_config"), ("evidence_snapshot_json", "evidence")):
            row[target] = json.loads(row.pop(source) or "{}")
        return row

    def get_monitorable_candidates(self) -> list[dict]:
        if self.user_store:
            return self.user_store.get_monitorable_candidates()
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT c.*, m.monitoring_status
                FROM candidate_ledger c
                JOIN candidate_monitoring m ON m.candidate_id = c.candidate_id
                WHERE m.monitoring_status = 'MONITORING'
                ORDER BY c.event_start_time
                """
            ).fetchall()
        return [self._candidate_row(dict(row)) for row in rows]

    def update_candidate_monitoring(self, candidate_id: str, values: dict) -> None:
        if self.user_store:
            self.user_store.update_candidate_monitoring(candidate_id, values)
            return
        allowed = {
            "monitoring_status", "exchange_clv_status", "composite_clv_status",
            "exchange_closing_price", "composite_closing_probability",
            "exchange_probability_point_clv", "exchange_stake_return_clv",
            "composite_probability_point_clv", "composite_stake_return_clv",
            "execution_loss", "fee_adjusted_clv", "closing_timestamp", "result",
            "hypothetical_profit_loss", "maximum_favorable_movement",
            "maximum_adverse_movement", "pass_reason_justified", "missing_reason",
        }
        selected = {key: value for key, value in values.items() if key in allowed}
        if not selected:
            return
        selected["updated_at"] = datetime.now(timezone.utc).isoformat()
        assignments = ", ".join(f"{key} = ?" for key in selected)
        with self.connection() as conn:
            conn.execute(
                f"UPDATE candidate_monitoring SET {assignments} WHERE candidate_id = ?",
                [*selected.values(), candidate_id],
            )

    def measurement_diagnostics(self) -> dict:
        if self.user_store:
            return self.user_store.measurement_diagnostics()
        with self.connection() as conn:
            decisions = conn.execute(
                "SELECT current_decision, COUNT(*) count FROM candidate_ledger GROUP BY current_decision"
            ).fetchall()
            reasons = conn.execute(
                "SELECT primary_reason_code, COUNT(*) count FROM candidate_decisions GROUP BY primary_reason_code ORDER BY count DESC"
            ).fetchall()
            monitoring = conn.execute(
                "SELECT monitoring_status, exchange_clv_status, composite_clv_status, COUNT(*) count FROM candidate_monitoring GROUP BY monitoring_status, exchange_clv_status, composite_clv_status"
            ).fetchall()
            versions = conn.execute(
                "SELECT component, version, status FROM model_versions ORDER BY component"
            ).fetchall()
            migrations = conn.execute(
                "SELECT version, applied_at FROM schema_migrations ORDER BY version"
            ).fetchall()
            dual_clv = conn.execute(
                """
                SELECT tracker_type, exchange_clv_status, composite_clv_status,
                       COUNT(*) count
                FROM dual_clv_measurements
                GROUP BY tracker_type, exchange_clv_status, composite_clv_status
                """
            ).fetchall()
            composite = conn.execute(
                """
                SELECT status, missing_reason, COUNT(*) count
                FROM composite_price_snapshots
                GROUP BY status, missing_reason
                """
            ).fetchall()
            table_counts = {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "candidate_ledger", "candidate_decisions",
                    "candidate_monitoring", "dual_clv_measurements",
                    "composite_price_snapshots",
                    "composite_source_contributions",
                )
            }
        return {
            "candidate_counts": {row["current_decision"]: row["count"] for row in decisions},
            "reason_counts": {row["primary_reason_code"]: row["count"] for row in reasons},
            "monitoring": [dict(row) for row in monitoring],
            "versions": [dict(row) for row in versions],
            "migrations": [dict(row) for row in migrations],
            "dual_clv": [dict(row) for row in dual_clv],
            "composite_prices": [dict(row) for row in composite],
            "table_counts": table_counts,
        }

    def get_candidate_measurements(self, candidate_id: str) -> dict | None:
        if self.user_store:
            return self.user_store.get_candidate_measurements(candidate_id)
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            return None
        with self.connection() as conn:
            decisions = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT * FROM candidate_decisions
                    WHERE candidate_id = ? ORDER BY decided_at, decision_id
                    """,
                    (candidate_id,),
                ).fetchall()
            ]
            monitoring_row = conn.execute(
                "SELECT * FROM candidate_monitoring WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            dual_clv_row = conn.execute(
                "SELECT * FROM dual_clv_measurements WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            snapshots = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT * FROM composite_price_snapshots
                    WHERE candidate_id = ? ORDER BY quote_timestamp
                    """,
                    (candidate_id,),
                ).fetchall()
            ]
            contributions = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT sc.* FROM composite_source_contributions sc
                    JOIN composite_price_snapshots ps
                      ON ps.snapshot_id = sc.snapshot_id
                    WHERE ps.candidate_id = ?
                    ORDER BY ps.quote_timestamp, sc.provider
                    """,
                    (candidate_id,),
                ).fetchall()
            ]
        for row in decisions:
            row["reason_codes"] = json.loads(row.pop("reason_codes_json") or "[]")
            row["decision_snapshot"] = json.loads(
                row.pop("decision_snapshot_json") or "{}"
            )
        monitoring = dict(monitoring_row) if monitoring_row else None
        if monitoring:
            monitoring["snapshot"] = json.loads(
                monitoring.pop("snapshot_json") or "{}"
            )
        dual_clv = dict(dual_clv_row) if dual_clv_row else None
        if dual_clv:
            dual_clv["snapshot"] = json.loads(
                dual_clv.pop("snapshot_json") or "{}"
            )
        for row in snapshots:
            row["snapshot"] = json.loads(row.pop("snapshot_json") or "{}")
        for row in contributions:
            row["source_snapshot"] = json.loads(
                row.pop("source_snapshot_json") or "{}"
            )
        return {
            "candidate": candidate,
            "decisions": decisions,
            "monitoring": monitoring,
            "dual_clv": dual_clv,
            "composite_price_snapshots": snapshots,
            "composite_source_contributions": contributions,
        }

    @staticmethod
    def _candidate_row(row: dict) -> dict:
        for source, target in (
            ("current_reason_codes_json", "reason_codes"),
            ("execution_snapshot_json", "execution_snapshot"),
            ("candidate_snapshot_json", "snapshot"),
        ):
            try:
                row[target] = json.loads(row.get(source) or "{}")
            except (TypeError, json.JSONDecodeError):
                row[target] = [] if target == "reason_codes" else {}
        return row

    def health(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "database_exists": self.path.exists(),
            "database_path": str(self.path),
            "status": "ok" if self.path.exists() else "initializing",
            "user_data_persistent": bool(self.user_store),
        }
        if self.user_store:
            durable_health = self.user_store.health()
            payload["durable_user_store"] = durable_health
            if durable_health.get("status") != "ok":
                payload["status"] = "degraded"
        return payload
