from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class TrackerDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.initialize()

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
                """
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

    def insert_event(self, event: dict) -> None:
        with self.connection() as conn:
            conn.execute(
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

    def get_events_for_wallet(self, wallet_address: str, limit: int = 200) -> list[dict]:
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

    def health(self) -> dict[str, str | bool]:
        return {
            "database_exists": self.path.exists(),
            "database_path": str(self.path),
            "status": "ok" if self.path.exists() else "initializing",
        }
