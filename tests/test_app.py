from __future__ import annotations

import json

from config import Settings
from database import TrackerDatabase
from position_tracker import TrackerService


class CountingClient:
    def __init__(self):
        self.current_calls = []
        self.closed_calls = []

    def get_current_positions(self, wallet_address: str):
        self.current_calls.append(wallet_address)
        return []

    def get_closed_positions(self, wallet_address: str, limit: int = 50):
        self.closed_calls.append(wallet_address)
        return []

    def get_events(self, event_slugs, max_workers: int = 8):
        return {}

    def get_public_profile(self, wallet_address: str):
        return None


def test_health_endpoint(app_client):
    response = app_client.get("/health")
    assert response.status_code == 200
    payload = response.get_json()
    assert "app_status" in payload
    assert "database_status" in payload


def test_app_starts_with_no_enabled_wallets(tmp_path):
    wallets_file = tmp_path / "wallets.json"
    wallets_file.write_text(
        json.dumps(
            [
                {
                    "address": "REPLACE_WITH_WALLET_ADDRESS",
                    "label": "Trader 1",
                    "enabled": False,
                    "base_unit": None,
                    "notes": "",
                }
            ]
        ),
        encoding="utf-8",
    )
    settings = Settings(
        dashboard_refresh=120,
        dashboard_port=5000,
        wallets_file=wallets_file,
        database_path=tmp_path / "tracker.db",
        sports_only=True,
        resolve_hours=168,
        min_american_odds=None,
        max_american_odds=None,
        request_timeout=15,
        max_retries=1,
        admin_password=None,
    )
    client = CountingClient()
    service = TrackerService(settings, client=client, database=TrackerDatabase(settings.database_path), auto_start=False)
    service.refresh()
    snapshot = service.get_snapshot()
    assert snapshot["status"]["enabled_wallet_count"] == 0
    assert client.current_calls == []


def test_status_endpoints(app_client):
    assert app_client.get("/api/positions").status_code == 200
    assert app_client.get("/api/wallets").status_code == 200
    assert app_client.get("/api/trades").status_code == 200
    assert app_client.get("/api/consensus").status_code == 200
    assert app_client.get("/api/unit-analysis").status_code == 200
    assert app_client.get("/api/status").status_code == 200
