from __future__ import annotations

from pathlib import Path

import pytest

from app import create_app
from config import Settings
from database import TrackerDatabase
from position_tracker import TrackerService


class DummyClient:
    def __init__(self, current=None, closed=None) -> None:
        self.current = current or {}
        self.closed = closed or {}
        self.current_calls = []
        self.closed_calls = []

    def get_current_positions(self, wallet_address: str):
        self.current_calls.append(wallet_address)
        return self.current.get(wallet_address, [])

    def get_closed_positions(self, wallet_address: str, limit: int = 50):
        self.closed_calls.append(wallet_address)
        return self.closed.get(wallet_address, [])

    def get_events(self, event_slugs, max_workers: int = 8):
        return {}

    def get_public_profile(self, wallet_address: str):
        return None


@pytest.fixture()
def temp_settings(tmp_path: Path) -> Settings:
    return Settings(
        dashboard_refresh=120,
        dashboard_port=5000,
        wallets_file=tmp_path / "wallets.json",
        database_path=tmp_path / "tracker.db",
        sports_only=True,
        resolve_hours=168,
        min_american_odds=None,
        max_american_odds=None,
        request_timeout=15,
        max_retries=1,
        admin_password=None,
    )


@pytest.fixture()
def db(temp_settings: Settings) -> TrackerDatabase:
    return TrackerDatabase(temp_settings.database_path)


@pytest.fixture()
def sample_wallet_file(temp_settings: Settings):
    temp_settings.wallets_file.write_text(
        """
[
  {
    "address": "0x204f72f35326db932158cba6adff0b9a1da95e14",
    "label": "Swiss Tony",
    "enabled": true,
    "base_unit": null,
    "notes": "sample"
  }
]
        """.strip(),
        encoding="utf-8",
    )
    return temp_settings.wallets_file


@pytest.fixture()
def app_client(monkeypatch, temp_settings: Settings, db: TrackerDatabase, sample_wallet_file: Path):
    from app import Flask, jsonify
    import app as app_module

    monkeypatch.setattr(app_module, "get_settings", lambda: temp_settings)
    dummy = DummyClient()
    monkeypatch.setattr(app_module, "TrackerService", lambda settings, auto_start=True: TrackerService(settings, client=dummy, database=db, auto_start=False))
    flask_app = create_app(start_background=False)
    return flask_app.test_client()
