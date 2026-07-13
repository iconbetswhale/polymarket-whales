from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from config import Settings
from database import TrackerDatabase
from position_tracker import (
    TrackerService,
    event_start_time,
    market_for_position,
    outcome_token_id,
)


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


class StubNotifier:
    def __init__(self):
        self.events = []

    def notify(self, event: dict):
        self.events.append(event)
        return True


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
        "endDate": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }


def test_real_game_time_and_exact_outcome_token_are_mapped_from_gamma_market():
    position = sample_position()
    position["outcome"] = "No"
    event = {
        "startDate": "2026-07-10T00:00:00Z",
        "startTime": "2026-07-14T19:00:00Z",
        "markets": [
            {
                "conditionId": position["conditionId"],
                "gameStartTime": "2026-07-14 19:30:00+00",
                "outcomes": '["Yes", "No"]',
                "clobTokenIds": '["token-yes", "token-no"]',
            }
        ],
    }

    market = market_for_position(position, event)
    start, source = event_start_time(position, event, market)

    assert start == "2026-07-14 19:30:00+00"
    assert source == "market.gameStartTime"
    assert outcome_token_id(position, market) == "token-no"


def test_position_change_detection(tmp_path):
    settings = _settings(tmp_path)
    database = TrackerDatabase(settings.database_path)
    first_client = StubClient(
        {"0x204f72f35326db932158cba6adff0b9a1da95e14": [sample_position()]}
    )
    service = TrackerService(
        settings, client=first_client, database=database, auto_start=False
    )
    service.refresh()

    second_client = StubClient(
        {
            "0x204f72f35326db932158cba6adff0b9a1da95e14": [
                sample_position(size=1300, current_value=1450, avg=0.52, cur=0.6)
            ]
        }
    )
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
    open_client = StubClient(
        {"0x204f72f35326db932158cba6adff0b9a1da95e14": [sample_position()]}
    )
    service = TrackerService(
        settings, client=open_client, database=database, auto_start=False
    )
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


def test_position_outside_analysis_window_is_not_recorded_as_exit(tmp_path):
    settings = _settings(tmp_path)
    database = TrackerDatabase(settings.database_path)
    address = "0x204f72f35326db932158cba6adff0b9a1da95e14"
    candidate = sample_position()
    candidate["endDate"] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    service = TrackerService(
        settings,
        client=StubClient({address: [candidate]}),
        database=database,
        auto_start=False,
    )
    service.refresh()

    outside_window = sample_position()
    outside_window["endDate"] = (
        datetime.now(timezone.utc) + timedelta(days=30)
    ).isoformat()
    service.client = StubClient({address: [outside_window]})
    service.refresh()

    events = database.get_recent_events()
    assert "full_exit" not in [event["event_type"] for event in events]
    assert database.get_open_positions_for_wallet(address)


def test_duplicate_event_prevention(tmp_path):
    settings = _settings(tmp_path)
    database = TrackerDatabase(settings.database_path)
    client = StubClient(
        {"0x204f72f35326db932158cba6adff0b9a1da95e14": [sample_position()]}
    )
    service = TrackerService(
        settings, client=client, database=database, auto_start=False
    )
    service.refresh()
    service.refresh()
    events = database.get_recent_events()
    assert len([event for event in events if event["event_type"] == "new_entry"]) == 1


def test_discord_notifications_skip_initial_scan_but_send_later_changes(tmp_path):
    settings = _settings(tmp_path)
    database = TrackerDatabase(settings.database_path)
    notifier = StubNotifier()
    first_client = StubClient(
        {"0x204f72f35326db932158cba6adff0b9a1da95e14": [sample_position()]}
    )
    service = TrackerService(
        settings,
        client=first_client,
        database=database,
        notifier=notifier,
        auto_start=False,
    )

    service.refresh()
    assert notifier.events == []

    second_client = StubClient(
        {
            "0x204f72f35326db932158cba6adff0b9a1da95e14": [
                sample_position(size=1300, current_value=1450, avg=0.52, cur=0.6)
            ]
        }
    )
    service.client = second_client
    service.refresh()

    notified_types = [event["event_type"] for event in notifier.events]
    assert "size_increase" in notified_types
    assert "new_entry" not in notified_types
