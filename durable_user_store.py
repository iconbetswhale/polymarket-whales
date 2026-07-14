from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator


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
        self, user_id: str, snapshot: dict, status: str = "scheduled"
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
        return row is not None

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
                    created_at, updated_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, NULL, NULL, %s, %s
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
