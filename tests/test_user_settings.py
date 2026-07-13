from __future__ import annotations

import sqlite3

from database import TrackerDatabase


def test_existing_settings_migrate_tracker_bankroll_from_trade_bankroll(tmp_path):
    database_path = tmp_path / "legacy.db"
    with sqlite3.connect(database_path) as conn:
        conn.execute(
            """
            CREATE TABLE user_settings (
                user_id TEXT PRIMARY KEY,
                starting_bankroll REAL NOT NULL,
                unit_percentage REAL NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO user_settings (
                user_id, starting_bankroll, unit_percentage, updated_at
            ) VALUES (?, ?, ?, ?)
            """,
            ("legacy-user", 12500, 0.01, "2026-07-13T12:00:00+00:00"),
        )

    database = TrackerDatabase(database_path)
    settings = database.get_or_create_user_settings("legacy-user", 10000, 0.01)

    assert settings["starting_bankroll"] == 12500
    assert settings["tracker_bankroll"] == 12500


def test_trade_and_tracker_bankroll_updates_preserve_each_other(tmp_path):
    database = TrackerDatabase(tmp_path / "tracker.db")
    created = database.get_or_create_user_settings("user-1", 10000, 0.01)
    assert created["tracker_bankroll"] == 10000

    tracker_updated = database.update_tracker_bankroll("user-1", 25000)
    assert tracker_updated["starting_bankroll"] == 10000
    assert tracker_updated["tracker_bankroll"] == 25000

    trade_updated = database.update_user_settings("user-1", 15000, 0.01)
    assert trade_updated["starting_bankroll"] == 15000
    assert trade_updated["tracker_bankroll"] == 25000

    tracker_updated_again = database.update_tracker_bankroll("user-1", 30000)
    assert tracker_updated_again["starting_bankroll"] == 15000
    assert tracker_updated_again["tracker_bankroll"] == 30000
