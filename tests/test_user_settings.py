from __future__ import annotations

import sqlite3

import pytest

from database import SettingsVersionConflict, TrackerDatabase


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
    assert settings["trades_to_play_bankroll"] == 12500
    assert settings["sizing_bankroll_configured"] == 1
    assert settings["tracker_bankroll"] == 12500
    assert settings["personal_tracker_bankroll"] == 12500


def test_trade_and_tracker_bankroll_updates_preserve_each_other(tmp_path):
    database = TrackerDatabase(tmp_path / "tracker.db")
    created = database.get_or_create_user_settings("user-1", 10000, 0.01)
    assert created["trades_to_play_bankroll"] == 10000
    assert created["sizing_bankroll_configured"] == 0
    assert created["tracker_bankroll"] == 10000

    tracker_updated = database.update_tracker_bankroll("user-1", 25000)
    assert tracker_updated["starting_bankroll"] == 10000
    assert tracker_updated["tracker_bankroll"] == 25000

    trade_updated = database.update_user_settings("user-1", 15000, 0.01)
    assert trade_updated["starting_bankroll"] == 15000
    assert trade_updated["trades_to_play_bankroll"] == 15000
    assert trade_updated["sizing_bankroll_configured"] == 1
    assert trade_updated["tracker_bankroll"] == 25000

    tracker_updated_again = database.update_tracker_bankroll("user-1", 30000)
    assert tracker_updated_again["starting_bankroll"] == 15000
    assert tracker_updated_again["tracker_bankroll"] == 30000


def test_versioned_trade_bankroll_update_rejects_stale_session(tmp_path):
    database = TrackerDatabase(tmp_path / "tracker.db")
    original = database.get_or_create_user_settings("user-1", 10000, 0.01)

    saved = database.update_user_settings(
        "user-1", 25000, 0.01, original["settings_version"]
    )
    assert saved["trades_to_play_bankroll"] == 25000

    with pytest.raises(SettingsVersionConflict) as conflict:
        database.update_user_settings(
            "user-1", 5000, 0.01, original["settings_version"]
        )

    assert conflict.value.current["trades_to_play_bankroll"] == 25000
    assert database.get_or_create_user_settings("user-1", 1, 0.01)[
        "trades_to_play_bankroll"
    ] == 25000


def test_all_bankroll_concepts_and_tracker_view_are_independent(tmp_path):
    database = TrackerDatabase(tmp_path / "tracker.db")
    original = database.get_or_create_user_settings("user-1", 10000, 0.01)

    database.update_user_settings("user-1", 25000, 0.01)
    database.update_tracker_bankroll("user-1", 50000)
    database.update_personal_tracker_bankroll("user-1", 7500)
    final = database.update_tracker_view("user-1", "personal")

    assert final["trades_to_play_bankroll"] == 25000
    assert final["tracker_bankroll"] == 50000
    assert final["personal_tracker_bankroll"] == 7500
    assert final["tracker_view"] == "personal"
    assert final["settings_version"] > original["settings_version"]
