from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from market_lifecycle import classify_lifecycle
from position_tracker import TrackerService


NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)


def test_upcoming_live_and_completed_are_mutually_exclusive():
    upcoming = classify_lifecycle(
        {
            "resolution_time": "2026-07-13T13:00:00Z",
            "market_active": True,
            "accepting_orders": True,
        },
        NOW,
    )
    live = classify_lifecycle(
        {
            "resolution_time": "2026-07-13T11:00:00Z",
            "market_active": True,
            "accepting_orders": True,
        },
        NOW,
    )
    completed = classify_lifecycle(
        {"resolution_time": "2026-07-13T11:00:00Z", "market_closed": True},
        NOW,
    )

    assert upcoming.state == "upcoming"
    assert live.state == "live"
    assert completed.state == "completed"


def test_postponed_event_uses_updated_future_time():
    lifecycle = classify_lifecycle(
        {
            "resolution_time": "2026-07-14T20:00:00Z",
            "game_status": "postponed",
            "market_active": True,
            "accepting_orders": True,
        },
        NOW,
    )

    assert lifecycle.state == "upcoming"


def test_missing_time_is_uncertain_not_upcoming():
    lifecycle = classify_lifecycle(
        {"market_active": True, "accepting_orders": True}, NOW
    )

    assert lifecycle.state == "uncertain"
    assert lifecycle.uncertain is True


def test_obviously_stale_live_flag_is_uncertain():
    lifecycle = classify_lifecycle(
        {
            "game_status": "live",
            "resolution_time": (NOW - timedelta(days=8)).isoformat(),
        },
        NOW,
    )

    assert lifecycle.state == "uncertain"
    assert lifecycle.uncertain is True


def test_recent_official_live_flag_remains_live():
    lifecycle = classify_lifecycle(
        {
            "game_status": "in progress",
            "resolution_time": (NOW - timedelta(hours=2)).isoformat(),
        },
        NOW,
    )

    assert lifecycle.state == "live"


def test_gamma_publication_flag_does_not_override_future_start():
    lifecycle = classify_lifecycle(
        {
            "event_live": True,
            "resolution_time": (NOW + timedelta(days=2)).isoformat(),
            "market_active": True,
            "accepting_orders": True,
        },
        NOW,
    )

    assert lifecycle.state == "upcoming"


def test_completed_positions_are_not_counted_as_active():
    service = object.__new__(TrackerService)
    service.settings = SimpleNamespace(sports_only=True, resolve_hours=168)

    assert (
        service._position_matches_filters(
            {
                "status": "open",
                "is_sports": True,
                "lifecycle_status": "completed",
                "resolution_time": NOW.isoformat(),
            }
        )
        is False
    )
