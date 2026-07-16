from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from measurement_foundation import (
    COMPOSITE_CLV_VERSION,
    RELEASE1_MIGRATION_VERSION,
    decision_id,
    migration_sql,
    model_version_rows,
    stable_hash,
)


class PostgresUserStore:
    """Durable storage for user-owned state in serverless deployments."""

    def __init__(self, database_url: str) -> None:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "PostgreSQL persistence requires psycopg[binary]."
            ) from exc

        self.database_url = database_url
        self._psycopg = psycopg
        self._dict_row = dict_row
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[Any]:
        conn = self._psycopg.connect(
            self.database_url,
            row_factory=self._dict_row,
            connect_timeout=10,
        )
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id TEXT PRIMARY KEY,
                starting_bankroll DOUBLE PRECISION NOT NULL,
                trades_to_play_bankroll DOUBLE PRECISION NOT NULL,
                sizing_bankroll_configured BOOLEAN NOT NULL DEFAULT FALSE,
                tracker_bankroll DOUBLE PRECISION NOT NULL,
                personal_tracker_bankroll DOUBLE PRECISION NOT NULL,
                tracker_view TEXT NOT NULL DEFAULT 'model',
                settings_version INTEGER NOT NULL DEFAULT 1,
                unit_percentage DOUBLE PRECISION NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS user_accounts (
                user_id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                password_iterations INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS auth_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_auth_sessions_user
                ON auth_sessions(user_id, expires_at)
            """,
            """
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
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_bet_tracker_user_created
                ON bet_tracker(user_id, created_at DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_bet_tracker_status
                ON bet_tracker(status, updated_at DESC)
            """,
            """
            CREATE TABLE IF NOT EXISTS discord_trade_notifications (
                id BIGSERIAL PRIMARY KEY,
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
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_discord_notifications_delivery
                ON discord_trade_notifications(status, next_attempt_at, created_at)
            """,
            """
            CREATE TABLE IF NOT EXISTS tracking_job_state (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS tracking_rejections (
                user_id TEXT NOT NULL,
                dedupe_key TEXT NOT NULL,
                rejection_reason TEXT NOT NULL,
                last_evaluated_at TEXT NOT NULL,
                evaluation_json TEXT NOT NULL,
                PRIMARY KEY (user_id, dedupe_key)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_tracking_rejections_user_evaluated
                ON tracking_rejections(user_id, last_evaluated_at DESC)
            """,
            """
            CREATE TABLE IF NOT EXISTS hidden_trades (
                id BIGSERIAL PRIMARY KEY,
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
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_hidden_trades_user_hidden
                ON hidden_trades(user_id, hidden_at DESC)
            """,
            """
            CREATE TABLE IF NOT EXISTS whiteboard_pins (
                id BIGSERIAL PRIMARY KEY,
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
            )
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_whiteboard_active_unique
                ON whiteboard_pins(
                    user_id, canonical_event_id, canonical_market_id,
                    market_line, canonical_outcome_id
                ) WHERE archived_at IS NULL
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_whiteboard_user_active
                ON whiteboard_pins(user_id, archived_at, pinned_at DESC)
            """,
            """
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
                entry_price DOUBLE PRECISION NOT NULL,
                shares DOUBLE PRECISION NOT NULL,
                position_cost DOUBLE PRECISION NOT NULL,
                fees DOUBLE PRECISION NOT NULL DEFAULT 0,
                total_paid DOUBLE PRECISION NOT NULL,
                status TEXT NOT NULL,
                result TEXT,
                settled_at TEXT,
                sportsbook TEXT NOT NULL DEFAULT 'Polymarket',
                tags_json TEXT NOT NULL DEFAULT '[]',
                sharp_snapshot_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_personal_fills_user_event
                ON personal_bet_fills(user_id, canonical_event_id, status)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_personal_fills_user_market
                ON personal_bet_fills(
                    user_id,
                    canonical_event_id,
                    canonical_market_id,
                    market_line,
                    canonical_outcome_id,
                    status
                )
            """,
            """
            CREATE TABLE IF NOT EXISTS personal_position_exits (
                exit_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                canonical_event_id TEXT NOT NULL,
                canonical_market_id TEXT NOT NULL,
                market_line TEXT NOT NULL DEFAULT '',
                canonical_outcome_id TEXT NOT NULL,
                sportsbook TEXT NOT NULL,
                shares_sold DOUBLE PRECISION NOT NULL,
                sell_price DOUBLE PRECISION NOT NULL,
                gross_proceeds DOUBLE PRECISION NOT NULL,
                fees DOUBLE PRECISION NOT NULL DEFAULT 0,
                net_proceeds DOUBLE PRECISION NOT NULL,
                sold_at TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'tracker_only',
                created_at TEXT NOT NULL,
                UNIQUE(user_id, idempotency_key)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_personal_exits_user_position
                ON personal_position_exits(
                    user_id, canonical_event_id, canonical_market_id,
                    market_line, canonical_outcome_id, sportsbook
                )
            """,
            """
            CREATE TABLE IF NOT EXISTS clv_quote_snapshots (
                id BIGSERIAL PRIMARY KEY,
                provider TEXT NOT NULL,
                provider_event_id TEXT NOT NULL,
                provider_market_id TEXT NOT NULL,
                provider_selection_id TEXT NOT NULL,
                quote_timestamp TEXT NOT NULL,
                provider_status TEXT,
                best_bid DOUBLE PRECISION,
                best_ask DOUBLE PRECISION,
                midpoint DOUBLE PRECISION,
                last_trade DOUBLE PRECISION,
                depth_json TEXT NOT NULL DEFAULT '[]',
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(provider, provider_market_id, provider_selection_id, quote_timestamp)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_clv_quotes_selection_time
                ON clv_quote_snapshots(
                    provider, provider_market_id, provider_selection_id,
                    quote_timestamp DESC
                )
            """,
            """
            CREATE TABLE IF NOT EXISTS closing_line_snapshots (
                id BIGSERIAL PRIMARY KEY,
                tracker_type TEXT NOT NULL,
                tracker_record_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                provider_event_id TEXT NOT NULL,
                provider_market_id TEXT NOT NULL,
                provider_selection_id TEXT NOT NULL,
                entry_price DOUBLE PRECISION,
                entry_native_odds TEXT,
                entry_implied_probability DOUBLE PRECISION,
                entry_stake DOUBLE PRECISION,
                closing_snapshot_timestamp TEXT,
                official_event_start_timestamp TEXT,
                closing_effective_price DOUBLE PRECISION,
                closing_midpoint DOUBLE PRECISION,
                clv_cents DOUBLE PRECISION,
                clv_probability_points DOUBLE PRECISION,
                clv_pct DOUBLE PRECISION,
                midpoint_clv_pct DOUBLE PRECISION,
                clv_status TEXT NOT NULL,
                clv_unavailable_reason TEXT,
                snapshot_json TEXT NOT NULL,
                calculation_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(tracker_type, tracker_record_id)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_closing_lines_tracker_time
                ON closing_line_snapshots(
                    tracker_type, user_id, closing_snapshot_timestamp DESC
                )
            """,
        )
        with self.connection() as conn:
            for statement in statements:
                conn.execute(statement)
            conn.execute(
                """
                ALTER TABLE user_settings
                ADD COLUMN IF NOT EXISTS tracker_bankroll DOUBLE PRECISION
                """
            )
            conn.execute(
                """
                ALTER TABLE personal_bet_fills
                ADD COLUMN IF NOT EXISTS sportsbook TEXT NOT NULL DEFAULT 'Polymarket'
                """
            )
            conn.execute(
                """
                ALTER TABLE personal_bet_fills
                ADD COLUMN IF NOT EXISTS tags_json TEXT NOT NULL DEFAULT '[]'
                """
            )
            conn.execute(
                """
                ALTER TABLE personal_bet_fills
                ADD COLUMN IF NOT EXISTS sharp_snapshot_json TEXT NOT NULL DEFAULT '{}'
                """
            )
            conn.execute(
                """
                ALTER TABLE user_settings
                ADD COLUMN IF NOT EXISTS trades_to_play_bankroll DOUBLE PRECISION
                """
            )
            conn.execute(
                """
                ALTER TABLE user_settings
                ADD COLUMN IF NOT EXISTS sizing_bankroll_configured BOOLEAN
                """
            )
            conn.execute(
                """
                ALTER TABLE user_settings
                ADD COLUMN IF NOT EXISTS personal_tracker_bankroll DOUBLE PRECISION
                """
            )
            conn.execute(
                """
                ALTER TABLE user_settings
                ADD COLUMN IF NOT EXISTS tracker_view TEXT
                """
            )
            conn.execute(
                """
                ALTER TABLE user_settings
                ADD COLUMN IF NOT EXISTS settings_version INTEGER
                """
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
                SET trades_to_play_bankroll = starting_bankroll,
                    sizing_bankroll_configured = TRUE,
                    personal_tracker_bankroll = COALESCE(
                        personal_tracker_bankroll, starting_bankroll
                    ),
                    tracker_view = COALESCE(tracker_view, 'model'),
                    settings_version = COALESCE(settings_version, 1)
                WHERE trades_to_play_bankroll IS NULL
                   OR sizing_bankroll_configured IS NULL
                   OR personal_tracker_bankroll IS NULL
                   OR tracker_view IS NULL
                   OR settings_version IS NULL
                """
            )
            for statement in (
                "ALTER TABLE user_settings ALTER COLUMN trades_to_play_bankroll SET NOT NULL",
                "ALTER TABLE user_settings ALTER COLUMN sizing_bankroll_configured SET NOT NULL",
                "ALTER TABLE user_settings ALTER COLUMN personal_tracker_bankroll SET NOT NULL",
                "ALTER TABLE user_settings ALTER COLUMN tracker_view SET NOT NULL",
                "ALTER TABLE user_settings ALTER COLUMN settings_version SET NOT NULL",
            ):
                conn.execute(statement)
            invalid_rows: list[tuple[str, str]] = []
            rows = conn.execute(
                "SELECT user_id, dedupe_key, snapshot_json FROM bet_tracker"
            ).fetchall()
            for row in rows:
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
            if invalid_rows:
                conn.executemany(
                    "DELETE FROM bet_tracker WHERE user_id = %s AND dedupe_key = %s",
                    invalid_rows,
                )
            for statement in migration_sql("postgres").split(";"):
                if statement.strip():
                    conn.execute(statement)
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                INSERT INTO schema_migrations(version, applied_at) VALUES (%s, %s)
                ON CONFLICT(version) DO NOTHING
                """,
                (RELEASE1_MIGRATION_VERSION, now),
            )
            for row in model_version_rows():
                conn.execute(
                    """
                    INSERT INTO model_versions(
                        version_key, component, version, status, description, registered_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT(version_key) DO NOTHING
                    """,
                    (
                        row["version_key"], row["component"], row["version"],
                        row["status"], row["description"], row["registered_at"],
                    ),
                )

    def get_or_create_user_settings(
        self, user_id: str, default_bankroll: float, unit_percentage: float
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO user_settings (
                    user_id, starting_bankroll, trades_to_play_bankroll,
                    sizing_bankroll_configured, tracker_bankroll,
                    personal_tracker_bankroll, tracker_view, settings_version,
                    unit_percentage, updated_at
                )
                VALUES (%s, %s, %s, FALSE, %s, %s, 'model', 1, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
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
                WHERE user_id = %s
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
        from database import SettingsVersionConflict

        self.get_or_create_user_settings(user_id, starting_bankroll, unit_percentage)
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            version_sql = " AND settings_version = %s" if expected_version is not None else ""
            values: list[Any] = [
                starting_bankroll,
                starting_bankroll,
                unit_percentage,
                now,
                user_id,
            ]
            if expected_version is not None:
                values.append(expected_version)
            row = conn.execute(
                f"""
                UPDATE user_settings
                SET starting_bankroll = %s, trades_to_play_bankroll = %s,
                    sizing_bankroll_configured = TRUE,
                    unit_percentage = %s, updated_at = %s,
                    settings_version = settings_version + 1
                WHERE user_id = %s{version_sql}
                RETURNING user_id, starting_bankroll, trades_to_play_bankroll,
                          sizing_bankroll_configured, tracker_bankroll,
                          personal_tracker_bankroll, tracker_view,
                          settings_version, unit_percentage, updated_at
                """,
                values,
            ).fetchone()
            if row is None:
                current = conn.execute(
                    "SELECT * FROM user_settings WHERE user_id = %s", (user_id,)
                ).fetchone()
                raise SettingsVersionConflict(dict(current))
        return dict(row)

    def update_tracker_bankroll(self, user_id: str, tracker_bankroll: float) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            row = conn.execute(
                """
                UPDATE user_settings
                SET tracker_bankroll = %s, updated_at = %s,
                    settings_version = settings_version + 1
                WHERE user_id = %s
                RETURNING user_id, starting_bankroll, trades_to_play_bankroll,
                          sizing_bankroll_configured, tracker_bankroll,
                          personal_tracker_bankroll, tracker_view,
                          settings_version, unit_percentage, updated_at
                """,
                (tracker_bankroll, now, user_id),
            ).fetchone()
        if row is None:
            raise LookupError(f"User settings not found for {user_id}")
        return dict(row)

    def update_personal_tracker_bankroll(
        self, user_id: str, personal_tracker_bankroll: float
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            row = conn.execute(
                """
                UPDATE user_settings
                SET personal_tracker_bankroll = %s, updated_at = %s,
                    settings_version = settings_version + 1
                WHERE user_id = %s
                RETURNING user_id, starting_bankroll, trades_to_play_bankroll,
                          sizing_bankroll_configured, tracker_bankroll,
                          personal_tracker_bankroll, tracker_view,
                          settings_version, unit_percentage, updated_at
                """,
                (personal_tracker_bankroll, now, user_id),
            ).fetchone()
        if row is None:
            raise LookupError(f"User settings not found for {user_id}")
        return dict(row)

    def update_tracker_view(self, user_id: str, tracker_view: str) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            row = conn.execute(
                """
                UPDATE user_settings
                SET tracker_view = %s, updated_at = %s,
                    settings_version = settings_version + 1
                WHERE user_id = %s
                RETURNING user_id, starting_bankroll, trades_to_play_bankroll,
                          sizing_bankroll_configured, tracker_bankroll,
                          personal_tracker_bankroll, tracker_view,
                          settings_version, unit_percentage, updated_at
                """,
                (tracker_view, now, user_id),
            ).fetchone()
        if row is None:
            raise LookupError(f"User settings not found for {user_id}")
        return dict(row)

    def list_user_settings(self) -> list[dict]:
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
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self.connection() as conn:
                row = conn.execute(
                    """
                    INSERT INTO user_accounts (
                        user_id, email, password_salt, password_hash,
                        password_iterations, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
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
                ).fetchone()
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                raise ValueError("An account already exists for that email.") from exc
            raise
        return dict(row)

    def get_account_by_email(self, email: str) -> dict | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM user_accounts WHERE LOWER(email) = LOWER(%s)",
                (email,),
            ).fetchone()
        return dict(row) if row else None

    def create_auth_session(
        self, user_id: str, token_hash: str, expires_at: str
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO auth_sessions (token_hash, user_id, expires_at, created_at)
                VALUES (%s, %s, %s, %s)
                """,
                (token_hash, user_id, expires_at, now),
            )

    def get_auth_session(self, token_hash: str) -> dict | None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT a.user_id, a.email, s.expires_at
                FROM auth_sessions s
                JOIN user_accounts a ON a.user_id = s.user_id
                WHERE s.token_hash = %s AND s.expires_at > %s
                """,
                (token_hash, now),
            ).fetchone()
        return dict(row) if row else None

    def delete_auth_session(self, token_hash: str) -> None:
        with self.connection() as conn:
            conn.execute("DELETE FROM auth_sessions WHERE token_hash = %s", (token_hash,))

    def promote_tracker_records_to_global(self, global_user_id: str) -> int:
        with self.connection() as conn:
            rows = conn.execute(
                """
                WITH ranked AS (
                    SELECT dedupe_key, snapshot_id, status, result, settled_at,
                           created_at, updated_at, snapshot_json,
                           ROW_NUMBER() OVER (
                               PARTITION BY dedupe_key
                               ORDER BY created_at ASC, user_id ASC
                           ) AS source_rank
                    FROM bet_tracker
                    WHERE user_id <> %s
                )
                INSERT INTO bet_tracker (
                    user_id, dedupe_key, snapshot_id, status, result, settled_at,
                    created_at, updated_at, snapshot_json
                )
                SELECT %s, dedupe_key, snapshot_id, status, result, settled_at,
                       created_at, updated_at, snapshot_json
                FROM ranked
                WHERE source_rank = 1
                ON CONFLICT (user_id, dedupe_key) DO NOTHING
                RETURNING dedupe_key
                """,
                (global_user_id, global_user_id),
            ).fetchall()
        return len(rows)

    def insert_tracker_snapshot(
        self,
        user_id: str,
        snapshot: dict,
        status: str = "scheduled",
        discord_payload: dict | None = None,
    ) -> bool:
        fraction = float(snapshot.get("final_recommended_fraction") or 0)
        amount = snapshot.get("original_displayed_amount")
        if fraction <= 1e-12 or (amount is not None and float(amount) < 0.01):
            return False
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO bet_tracker (
                    user_id, dedupe_key, snapshot_id, status, result, settled_at,
                    created_at, updated_at, snapshot_json
                )
                VALUES (%s, %s, %s, %s, NULL, NULL, %s, %s, %s)
                ON CONFLICT (user_id, dedupe_key) DO NOTHING
                RETURNING dedupe_key
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
            ).fetchone()
            if row is not None and discord_payload is not None:
                conn.execute(
                    """
                    INSERT INTO discord_trade_notifications (
                        user_id, dedupe_key, snapshot_id, notification_type,
                        status, attempts, payload_json, created_at, updated_at
                    ) VALUES (%s, %s, %s, 'model_tracker_insert', 'pending', 0, %s, %s, %s)
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
        return row is not None

    def claim_discord_notifications(self, limit: int = 10) -> list[dict]:
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        stale_iso = (now - timedelta(minutes=10)).isoformat()
        with self.connection() as conn:
            rows = conn.execute(
                """
                WITH candidates AS (
                    SELECT id
                    FROM discord_trade_notifications
                    WHERE (
                        status IN ('pending', 'retry')
                        AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
                    ) OR (status = 'sending' AND updated_at <= %s)
                    ORDER BY created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s
                )
                UPDATE discord_trade_notifications AS notification
                SET status = 'sending', attempts = notification.attempts + 1,
                    updated_at = %s, next_attempt_at = NULL
                FROM candidates
                WHERE notification.id = candidates.id
                RETURNING notification.id, notification.attempts,
                          notification.payload_json
                """,
                (now_iso, stale_iso, max(int(limit), 1), now_iso),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "attempts": row["attempts"],
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        ]

    def mark_discord_notification_delivered(
        self, notification_id: int, message_id: str | None, response_status: int | None
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE discord_trade_notifications
                SET status = 'delivered', discord_message_id = %s,
                    response_status = %s, last_error = NULL,
                    delivered_at = %s, updated_at = %s, next_attempt_at = NULL
                WHERE id = %s
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
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE discord_trade_notifications
                SET status = %s, response_status = %s, last_error = %s,
                    next_attempt_at = %s, updated_at = %s
                WHERE id = %s
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
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT id, status, attempts, payload_json, discord_message_id,
                       response_status, last_error, next_attempt_at,
                       created_at, updated_at, delivered_at
                FROM discord_trade_notifications
                WHERE user_id = %s AND dedupe_key = %s
                """,
                (user_id, dedupe_key),
            ).fetchone()
        if row is None:
            return None
        payload = dict(row)
        payload["payload"] = json.loads(payload.pop("payload_json"))
        return payload

    def get_tracker_records(self, user_id: str) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT dedupe_key, snapshot_id, status, result, settled_at,
                       created_at, updated_at, snapshot_json
                FROM bet_tracker
                WHERE user_id = %s
                ORDER BY created_at ASC
                """,
                (user_id,),
            ).fetchall()
        return [self._tracker_row(row) for row in rows]

    def get_tracker_record(self, user_id: str, dedupe_key: str) -> dict | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT dedupe_key, snapshot_id, status, result, settled_at,
                       created_at, updated_at, snapshot_json
                FROM bet_tracker
                WHERE user_id = %s AND dedupe_key = %s
                """,
                (user_id, dedupe_key),
            ).fetchone()
        return self._tracker_row(row) if row else None

    def set_tracking_job_state(self, state: dict) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO tracking_job_state (key, value_json, updated_at)
                VALUES ('model_tracker', %s, %s)
                ON CONFLICT (key) DO UPDATE SET
                    value_json = EXCLUDED.value_json,
                    updated_at = EXCLUDED.updated_at
                """,
                (json.dumps(state), now),
            )

    def get_tracking_job_state(self) -> dict:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT value_json FROM tracking_job_state WHERE key = 'model_tracker'"
            ).fetchone()
        return json.loads(row["value_json"]) if row else {}

    def replace_tracking_rejections(self, user_id: str, rows: list[dict]) -> None:
        with self.connection() as conn:
            conn.execute(
                "DELETE FROM tracking_rejections WHERE user_id = %s", (user_id,)
            )
            if rows:
                with conn.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO tracking_rejections (
                            user_id, dedupe_key, rejection_reason,
                            last_evaluated_at, evaluation_json
                        ) VALUES (%s, %s, %s, %s, %s)
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
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT evaluation_json
                FROM tracking_rejections
                WHERE user_id = %s
                ORDER BY last_evaluated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [json.loads(row["evaluation_json"]) for row in rows]

    def get_active_tracker_records(self) -> list[dict]:
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
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE bet_tracker
                SET status = %s, result = %s, settled_at = %s, updated_at = %s
                WHERE user_id = %s AND dedupe_key = %s
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
            row = conn.execute(
                """
                INSERT INTO hidden_trades (
                    user_id, canonical_event_id, canonical_market_id,
                    market_line, canonical_outcome_id, event_title, market_title,
                    selection, event_start_time, hidden_at, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (
                    user_id, canonical_event_id, canonical_market_id,
                    market_line, canonical_outcome_id
                ) DO UPDATE SET
                    event_title = EXCLUDED.event_title,
                    market_title = EXCLUDED.market_title,
                    selection = EXCLUDED.selection,
                    event_start_time = EXCLUDED.event_start_time,
                    updated_at = EXCLUDED.updated_at
                RETURNING *
                """,
                values,
            ).fetchone()
        return dict(row)

    def get_hidden_trades(self, user_id: str) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM hidden_trades
                WHERE user_id = %s
                ORDER BY hidden_at DESC, id DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def restore_hidden_trade(self, user_id: str, hidden_id: int) -> bool:
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM hidden_trades WHERE user_id = %s AND id = %s",
                (user_id, hidden_id),
            )
            return cursor.rowcount > 0

    def restore_all_hidden_trades(self, user_id: str) -> int:
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM hidden_trades WHERE user_id = %s", (user_id,)
            )
            return cursor.rowcount

    def pin_whiteboard_trade(self, user_id: str, pin: dict) -> dict:
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
            row = conn.execute(
                """
                INSERT INTO whiteboard_pins (
                    user_id, canonical_event_id, canonical_market_id,
                    market_line, canonical_outcome_id, market_type, period,
                    snapshot_json, pinned_at, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (
                    user_id, canonical_event_id, canonical_market_id,
                    market_line, canonical_outcome_id
                ) WHERE archived_at IS NULL DO NOTHING
                RETURNING *
                """,
                values,
            ).fetchone()
            if row is None:
                row = conn.execute(
                    """
                    SELECT * FROM whiteboard_pins
                    WHERE user_id = %s AND canonical_event_id = %s
                      AND canonical_market_id = %s AND market_line = %s
                      AND canonical_outcome_id = %s AND archived_at IS NULL
                    """,
                    values[:5],
                ).fetchone()
        result = dict(row)
        result["snapshot"] = json.loads(result.pop("snapshot_json"))
        return result

    def get_whiteboard_pins(self, user_id: str, active_only: bool = True) -> list[dict]:
        clause = "AND archived_at IS NULL" if active_only else ""
        with self.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM whiteboard_pins
                WHERE user_id = %s {clause}
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

    def archive_whiteboard_pin(self, user_id: str, pin_id: int, reason: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE whiteboard_pins
                SET archived_at = %s, archive_reason = %s, updated_at = %s
                WHERE user_id = %s AND id = %s AND archived_at IS NULL
                """,
                (now, reason, now, user_id, pin_id),
            )
            return cursor.rowcount > 0

    def insert_personal_bet_fill(
        self, user_id: str, fill: dict, status: str = "scheduled"
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            row = conn.execute(
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
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, NULL, NULL, %s, %s, %s, %s, %s
                )
                RETURNING *
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
            ).fetchone()
        return dict(row)

    def get_personal_bet_fills(
        self, user_id: str, *, active_only: bool = False
    ) -> list[dict]:
        active_sql = (
            "AND status IN ('scheduled', 'live', 'unresolved')"
            if active_only
            else ""
        )
        with self.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM personal_bet_fills
                WHERE user_id = %s {active_sql}
                ORDER BY created_at ASC, fill_id ASC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def insert_personal_position_exit(self, user_id: str, record: dict) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO personal_position_exits (
                    exit_id, user_id, idempotency_key, canonical_event_id,
                    canonical_market_id, market_line, canonical_outcome_id,
                    sportsbook, shares_sold, sell_price, gross_proceeds,
                    fees, net_proceeds, sold_at, mode, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, idempotency_key) DO NOTHING
                RETURNING *
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
            ).fetchone()
        if row is None:
            raise ValueError("This exit was already recorded.")
        return dict(row)

    def get_personal_position_exits(self, user_id: str) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT * FROM personal_position_exits
                   WHERE user_id = %s ORDER BY sold_at ASC, exit_id ASC""",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_all_active_personal_bet_fills(self) -> list[dict]:
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
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE personal_bet_fills
                SET status = 'canceled', result = 'Canceled', settled_at = %s,
                    updated_at = %s
                WHERE user_id = %s AND fill_id = %s
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
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE personal_bet_fills
                SET status = %s, result = %s, settled_at = %s, updated_at = %s
                WHERE fill_id = %s
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
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO clv_quote_snapshots (
                    provider, provider_event_id, provider_market_id,
                    provider_selection_id, quote_timestamp, provider_status,
                    best_bid, best_ask, midpoint, last_trade, depth_json,
                    source, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
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

    def get_clv_quotes(self, provider: str, market_id: str, selection_id: str) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT * FROM clv_quote_snapshots
                   WHERE provider = %s AND provider_market_id = %s
                     AND provider_selection_id = %s
                   ORDER BY quote_timestamp ASC""",
                (provider, market_id, selection_id),
            ).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row["depth"] = json.loads(row.pop("depth_json"))
        return result

    def insert_closing_line(self, snapshot: dict) -> bool:
        values = (
            snapshot["tracker_type"], snapshot["tracker_record_id"], snapshot["user_id"],
            snapshot["provider"], snapshot["provider_event_id"], snapshot["provider_market_id"],
            snapshot["provider_selection_id"], snapshot.get("entry_price"),
            snapshot.get("entry_native_odds"), snapshot.get("entry_implied_probability"),
            snapshot.get("entry_stake"), snapshot.get("closing_snapshot_timestamp"),
            snapshot.get("official_event_start_timestamp"), snapshot.get("closing_effective_price"),
            snapshot.get("closing_midpoint"), snapshot.get("clv_cents"),
            snapshot.get("clv_probability_points"), snapshot.get("clv_pct"),
            snapshot.get("midpoint_clv_pct"), snapshot["clv_status"],
            snapshot.get("clv_unavailable_reason"), json.dumps(snapshot),
            snapshot["calculation_version"], datetime.now(timezone.utc).isoformat(),
        )
        with self.connection() as conn:
            cursor = conn.execute(
                """INSERT INTO closing_line_snapshots (
                    tracker_type, tracker_record_id, user_id, provider,
                    provider_event_id, provider_market_id, provider_selection_id,
                    entry_price, entry_native_odds, entry_implied_probability,
                    entry_stake, closing_snapshot_timestamp,
                    official_event_start_timestamp, closing_effective_price,
                    closing_midpoint, clv_cents, clv_probability_points, clv_pct,
                    midpoint_clv_pct, clv_status, clv_unavailable_reason,
                    snapshot_json, calculation_version, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING""",
                values,
            )
        return cursor.rowcount > 0

    def get_closing_lines(self, tracker_type: str, user_id: str) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT * FROM closing_line_snapshots
                   WHERE tracker_type = %s AND user_id = %s
                   ORDER BY created_at ASC""",
                (tracker_type, user_id),
            ).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row.update(json.loads(row.pop("snapshot_json")))
        return result

    def clv_diagnostics(self) -> dict:
        with self.connection() as conn:
            monitored = conn.execute(
                """SELECT
                    (SELECT COUNT(*) FROM bet_tracker WHERE status IN ('scheduled','live','unresolved')) +
                    (SELECT COUNT(*) FROM personal_bet_fills WHERE status IN ('scheduled','live','unresolved')) AS count"""
            ).fetchone()["count"]
            quote = conn.execute("SELECT MAX(quote_timestamp) AS timestamp FROM clv_quote_snapshots").fetchone()["timestamp"]
            counts = conn.execute(
                "SELECT clv_status, COUNT(*) AS count FROM closing_line_snapshots GROUP BY clv_status"
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

    def record_candidate(self, record: dict) -> dict:
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
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT(candidate_id) DO UPDATE SET
                    last_seen_at = EXCLUDED.last_seen_at,
                    current_decision = EXCLUDED.current_decision,
                    current_reason_codes_json = EXCLUDED.current_reason_codes_json
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
            conn.execute(
                """
                INSERT INTO candidate_decisions(
                    decision_id, candidate_id, correlation_id, decision,
                    reason_codes_json, primary_reason_code, decided_at,
                    decision_snapshot_json, recommendation_version,
                    calculation_version
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(decision_id) DO NOTHING
                """,
                (
                    decision_id(record), record["candidate_id"],
                    record["correlation_id"], record["decision"], reasons_json,
                    record["reason_codes"][0] if record["reason_codes"] else None,
                    now, json.dumps(decision_snapshot, sort_keys=True),
                    versions["recommendation"], versions["candidate_ledger"],
                ),
            )
            if record["decision"] in {"PASSED", "RESEARCH_ONLY"}:
                conn.execute(
                    """
                    INSERT INTO candidate_monitoring(
                        candidate_id, monitoring_status, exchange_clv_status,
                        composite_clv_status, hypothetical_stake, missing_reason,
                        snapshot_json, updated_at
                    ) VALUES (%s, 'MONITORING', 'PENDING', 'UNAVAILABLE', %s, %s, '{}', %s)
                    ON CONFLICT(candidate_id) DO NOTHING
                    """,
                    (
                        record["candidate_id"], 100.0,
                        "NO_CONNECTED_INDEPENDENT_COMPOSITE_PROVIDER", now,
                    ),
                )
        return self.get_candidate(record["candidate_id"]) or {}

    def upsert_dual_clv(self, measurement: dict) -> None:
        now = datetime.now(timezone.utc).isoformat()
        measurement_id = stable_hash(measurement["tracker_type"], measurement["tracker_record_id"])
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO dual_clv_measurements(
                    measurement_id, tracker_type, tracker_record_id, user_id,
                    candidate_id, entry_price, exchange_closing_price,
                    composite_closing_probability, exchange_probability_point_clv,
                    exchange_stake_return_clv, composite_probability_point_clv,
                    composite_stake_return_clv, execution_loss, fee_adjusted_clv,
                    exchange_clv_status, composite_clv_status,
                    exchange_missing_reason, composite_missing_reason,
                    closing_timestamp, exchange_calculation_version,
                    composite_calculation_version, snapshot_json, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT(tracker_type, tracker_record_id) DO UPDATE SET
                    exchange_closing_price = EXCLUDED.exchange_closing_price,
                    composite_closing_probability = EXCLUDED.composite_closing_probability,
                    exchange_probability_point_clv = EXCLUDED.exchange_probability_point_clv,
                    exchange_stake_return_clv = EXCLUDED.exchange_stake_return_clv,
                    composite_probability_point_clv = EXCLUDED.composite_probability_point_clv,
                    composite_stake_return_clv = EXCLUDED.composite_stake_return_clv,
                    execution_loss = EXCLUDED.execution_loss,
                    fee_adjusted_clv = EXCLUDED.fee_adjusted_clv,
                    exchange_clv_status = EXCLUDED.exchange_clv_status,
                    composite_clv_status = EXCLUDED.composite_clv_status,
                    exchange_missing_reason = EXCLUDED.exchange_missing_reason,
                    composite_missing_reason = EXCLUDED.composite_missing_reason,
                    closing_timestamp = EXCLUDED.closing_timestamp,
                    snapshot_json = EXCLUDED.snapshot_json,
                    updated_at = EXCLUDED.updated_at
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
                    json.dumps(measurement.get("snapshot") or {}, sort_keys=True), now, now,
                ),
            )

    def record_candidate_price_observation(
        self,
        candidate_id: str,
        entry_price: float | None,
        observed_price: float | None,
    ) -> None:
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
                FROM candidate_monitoring WHERE candidate_id = %s
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
                SET maximum_favorable_movement = %s,
                    maximum_adverse_movement = %s, updated_at = %s
                WHERE candidate_id = %s
                """,
                (
                    favorable,
                    adverse,
                    datetime.now(timezone.utc).isoformat(),
                    candidate_id,
                ),
            )

    def get_candidate(self, candidate_id: str) -> dict | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM candidate_ledger WHERE candidate_id = %s",
                (candidate_id,),
            ).fetchone()
        return self._candidate_row(dict(row)) if row else None

    def insert_composite_price_snapshot(self, snapshot: dict) -> bool:
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO composite_price_snapshots(
                    snapshot_id, candidate_id, correlation_id, quote_timestamp,
                    composite_fair_probability, source_count, source_dispersion,
                    mapping_confidence, status, missing_reason,
                    calculation_version, snapshot_json, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(snapshot_id) DO NOTHING
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
            for item in snapshot.get("contributions") or []:
                conn.execute(
                    """
                    INSERT INTO composite_source_contributions(
                        snapshot_id, provider, provider_event_id, provider_market_id,
                        provider_selection_id, native_odds, decimal_odds,
                        raw_implied_probability, no_vig_probability,
                        contribution_weight, quote_timestamp, quote_freshness,
                        included, exclusion_reason, source_snapshot_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(snapshot_id, provider) DO NOTHING
                    """,
                    (
                        snapshot["snapshot_id"], item["provider"],
                        item.get("provider_event_id"), item.get("provider_market_id"),
                        item.get("provider_selection_id"), item.get("native_odds"),
                        item.get("decimal_odds"), item.get("raw_implied_probability"),
                        item.get("no_vig_probability"), item.get("contribution_weight"),
                        item.get("quote_timestamp"), item.get("quote_freshness"),
                        bool(item.get("included")), item.get("exclusion_reason"),
                        json.dumps(item.get("source_snapshot") or {}, sort_keys=True),
                    ),
                )
        return inserted

    def list_candidates(self, decision: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        query = "SELECT * FROM candidate_ledger"
        params: list[object] = []
        if decision:
            query += " WHERE current_decision = %s"
            params.append(decision)
        query += " ORDER BY last_seen_at DESC LIMIT %s OFFSET %s"
        params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._candidate_row(dict(row)) for row in rows]

    def get_monitorable_candidates(self) -> list[dict]:
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
        assignments = ", ".join(f"{key} = %s" for key in selected)
        with self.connection() as conn:
            conn.execute(
                f"UPDATE candidate_monitoring SET {assignments} WHERE candidate_id = %s",
                [*selected.values(), candidate_id],
            )

    def measurement_diagnostics(self) -> dict:
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
                table: conn.execute(f"SELECT COUNT(*) count FROM {table}").fetchone()["count"]
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
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            return None
        with self.connection() as conn:
            decisions = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT * FROM candidate_decisions
                    WHERE candidate_id = %s ORDER BY decided_at, decision_id
                    """,
                    (candidate_id,),
                ).fetchall()
            ]
            monitoring_row = conn.execute(
                "SELECT * FROM candidate_monitoring WHERE candidate_id = %s",
                (candidate_id,),
            ).fetchone()
            dual_clv_row = conn.execute(
                "SELECT * FROM dual_clv_measurements WHERE candidate_id = %s",
                (candidate_id,),
            ).fetchone()
            snapshots = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT * FROM composite_price_snapshots
                    WHERE candidate_id = %s ORDER BY quote_timestamp
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
                    WHERE ps.candidate_id = %s
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

    def health(self) -> dict[str, str | bool]:
        try:
            with self.connection() as conn:
                conn.execute("SELECT 1").fetchone()
        except Exception as exc:
            return {
                "backend": "postgresql",
                "persistent": True,
                "status": "error",
                "error": str(exc),
            }
        return {
            "backend": "postgresql",
            "persistent": True,
            "status": "ok",
        }

    @staticmethod
    def _tracker_row(row: dict) -> dict:
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
