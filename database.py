from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from durable_user_store import PostgresUserStore


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

                CREATE TABLE IF NOT EXISTS refresh_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id TEXT PRIMARY KEY,
                    starting_bankroll REAL NOT NULL,
                    unit_percentage REAL NOT NULL,
                    updated_at TEXT NOT NULL
                );

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
                INSERT OR IGNORE INTO user_settings (user_id, starting_bankroll, unit_percentage, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, default_bankroll, unit_percentage, now),
            )
            row = conn.execute(
                """
                SELECT user_id, starting_bankroll, unit_percentage, updated_at
                FROM user_settings
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        return dict(row)

    def update_user_settings(
        self, user_id: str, starting_bankroll: float, unit_percentage: float
    ) -> dict:
        if self.user_store:
            return self.user_store.update_user_settings(
                user_id, starting_bankroll, unit_percentage
            )
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO user_settings (user_id, starting_bankroll, unit_percentage, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    starting_bankroll = excluded.starting_bankroll,
                    unit_percentage = excluded.unit_percentage,
                    updated_at = excluded.updated_at
                """,
                (user_id, starting_bankroll, unit_percentage, now),
            )
        return self.get_or_create_user_settings(
            user_id, starting_bankroll, unit_percentage
        )

    def list_user_settings(self) -> list[dict]:
        if self.user_store:
            return self.user_store.list_user_settings()
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT user_id, starting_bankroll, unit_percentage, updated_at FROM user_settings"
            ).fetchall()
        return [dict(row) for row in rows]

    def insert_tracker_snapshot(
        self, user_id: str, snapshot: dict, status: str = "scheduled"
    ) -> bool:
        if self.user_store:
            return self.user_store.insert_tracker_snapshot(user_id, snapshot, status)
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
            return cursor.rowcount > 0

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
                    created_at, updated_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    NULL, NULL, ?, ?
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
