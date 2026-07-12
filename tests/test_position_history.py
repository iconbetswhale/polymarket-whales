from __future__ import annotations

import json

from config import Settings
from database import TrackerDatabase
from position_tracker import TrackerService


class StubClient:
    def __init__(self, open_payloads, closed_payloads=None):
        self.open_payloads = open_payloads
        self.closed_payloads = closed_payloads or {}

    def get_current_positions(self, wallet_address: str):
        return self.open_payloads.get(wallet_address, [])

    def get_closed_positions(self, wallet_address: str, limit: int = 50):
        return self.closed_payloads.get(wallet_address, [])

    def get_events(self, event_slugs, max_workers: int = 8):
        return {}

    def get_public_profile(self, wallet_address: str):
        return None


def _settings(tmp_path) -> Settings:
    wallets_file = tmp_path / "wallets.json"
    wallets_file.write_text(
        json.dumps(
            [
                {
                    "address": "0x204f72f35326db932158cba6adff0b9a1da95e14",
                    "label": "Swiss Tony",
                    "enabled": True,
                    "base_unit": None,
                    "notes": "",
                }
            ]
        ),
        encoding="utf-8",
    )
    return Settings(
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


def sample_position(size=1000, current_value=1100, avg=0.5, cur=0.55):
    return {
        "conditionId": "0x1111111111111111111111111111111111111111111111111111111111111111",
        "size": 2000,
        "avgPrice": avg,
        "initialValue": size,
        "currentValue": current_value,
        "cashPnl": current_value - size,
        "realizedPnl": 0,
        "curPrice": cur,
        "title": "Will France win on 2026-07-14?",
        "slug": "fifwc-fra-esp-2026-07-14-fra",
        "eventSlug": "fifwc-fra-esp-2026-07-14",
        "eventId": "691040",
        "outcome": "No",
        "oppositeOutcome": "Yes",
        "endDate": "2099-07-14T19:00:00Z",
    }


def test_position_change_detection(tmp_path):
    settings = _settings(tmp_path)
    database = TrackerDatabase(settings.database_path)
    first_client = StubClient({"0x204f72f35326db932158cba6adff0b9a1da95e14": [sample_position()]})
    service = TrackerService(settings, client=first_client, database=database, auto_start=False)
    service.refresh()

    second_client = StubClient({"0x204f72f35326db932158cba6adff0b9a1da95e14": [sample_position(size=1300, current_value=1450, avg=0.52, cur=0.6)]})
    service.client = second_client
    service.refresh()
    events = database.get_recent_events()
    event_types = [event["event_type"] for event in events]
    assert "new_entry" in event_types
    assert "size_increase" in event_types
    assert "avg_price_change" in event_types
    assert "price_change" in event_types


def test_exit_detection(tmp_path):
    settings = _settings(tmp_path)
    database = TrackerDatabase(settings.database_path)
    open_client = StubClient({"0x204f72f35326db932158cba6adff0b9a1da95e14": [sample_position()]})
    service = TrackerService(settings, client=open_client, database=database, auto_start=False)
    service.refresh()

    closed_client = StubClient(
        {"0x204f72f35326db932158cba6adff0b9a1da95e14": []},
        {
            "0x204f72f35326db932158cba6adff0b9a1da95e14": [
                {
                    "conditionId": "0x1111111111111111111111111111111111111111111111111111111111111111",
                    "outcome": "No",
                    "realizedPnl": 200,
                    "curPrice": 1,
                    "title": "Will France win on 2026-07-14?",
                    "eventSlug": "fifwc-fra-esp-2026-07-14",
                }
            ]
        },
    )
    service.client = closed_client
    service.refresh()

    events = database.get_recent_events()
    assert "full_exit" in [event["event_type"] for event in events]


def test_duplicate_event_prevention(tmp_path):
    settings = _settings(tmp_path)
    database = TrackerDatabase(settings.database_path)
    client = StubClient({"0x204f72f35326db932158cba6adff0b9a1da95e14": [sample_position()]})
    service = TrackerService(settings, client=client, database=database, auto_start=False)
    service.refresh()
    service.refresh()
    events = database.get_recent_events()
    assert len([event for event in events if event["event_type"] == "new_entry"]) == 1
