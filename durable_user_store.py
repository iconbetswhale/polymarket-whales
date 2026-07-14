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
                tracker_bankroll DOUBLE PRECISION NOT NULL,
                unit_percentage DOUBLE PRECISION NOT NULL,
                updated_at TEXT NOT NULL
            )
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
                UPDATE user_settings
                SET tracker_bankroll = starting_bankroll
                WHERE tracker_bankroll IS NULL
                """
            )
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
                    user_id, starting_bankroll, tracker_bankroll,
                    unit_percentage, updated_at
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
                """,
                (
                    user_id,
                    default_bankroll,
                    default_bankroll,
                    unit_percentage,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT user_id, starting_bankroll, tracker_bankroll,
                       unit_percentage, updated_at
                FROM user_settings
                WHERE user_id = %s
                """,
                (user_id,),
            ).fetchone()
        return dict(row)

    def update_user_settings(
        self, user_id: str, starting_bankroll: float, unit_percentage: float
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO user_settings (
                    user_id, starting_bankroll, tracker_bankroll,
                    unit_percentage, updated_at
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    starting_bankroll = EXCLUDED.starting_bankroll,
                    unit_percentage = EXCLUDED.unit_percentage,
                    updated_at = EXCLUDED.updated_at
                RETURNING user_id, starting_bankroll, tracker_bankroll,
                          unit_percentage, updated_at
                """,
                (
                    user_id,
                    starting_bankroll,
                    starting_bankroll,
                    unit_percentage,
                    now,
                ),
            ).fetchone()
        return dict(row)

    def update_tracker_bankroll(self, user_id: str, tracker_bankroll: float) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            row = conn.execute(
                """
                UPDATE user_settings
                SET tracker_bankroll = %s, updated_at = %s
                WHERE user_id = %s
                RETURNING user_id, starting_bankroll, tracker_bankroll,
                          unit_percentage, updated_at
                """,
                (tracker_bankroll, now, user_id),
            ).fetchone()
        if row is None:
            raise LookupError(f"User settings not found for {user_id}")
        return dict(row)

    def list_user_settings(self) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT user_id, starting_bankroll, tracker_bankroll,
                       unit_percentage, updated_at
                FROM user_settings
                """
            ).fetchall()
        return [dict(row) for row in rows]

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
