from datetime import datetime, timedelta, timezone

from database import TrackerDatabase
from lab_tracker import LAB_TRACKER_GLOBAL_USER_ID, LabTrackerService, demo_dashboard


def positive_ev_row() -> dict:
    return {
        "id": "ev::event-1::totals::selection-1",
        "eventId": "event-1",
        "sportKey": "baseball_mlb",
        "league": "MLB",
        "eventTitle": "Boston Red Sox vs New York Yankees",
        "homeTeam": "New York Yankees",
        "awayTeam": "Boston Red Sox",
        "commenceTime": "2026-08-14T23:00:00+00:00",
        "marketKey": "totals",
        "marketLabel": "Game Total",
        "selection": "Over 8.5",
        "evPercent": 4.2,
        "bestQuote": {
            "bookKey": "fanduel",
            "bookName": "FanDuel",
            "logoUrl": "https://sportsbook.fanduel.com/favicon.ico",
            "topPriceAmericanOdds": 110,
            "effectiveDecimal": 2.1,
            "point": 8.5,
        },
    }


def test_requires_two_observations_spanning_five_seconds(tmp_path):
    service = LabTrackerService(TrackerDatabase(tmp_path / "lab.db"))
    first_at = datetime(2026, 8, 14, 20, 0, tzinfo=timezone.utc)

    first = service.observe_positive_ev([positive_ev_row()], first_at)
    assert first == {"observed": 1, "qualified": 0}
    assert service.dashboard(
        scope="signal", user_id=LAB_TRACKER_GLOBAL_USER_ID, source=None, window="all"
    )["summary"]["tracked"] == 0

    second = service.observe_positive_ev(
        [positive_ev_row()], first_at + timedelta(seconds=6)
    )
    duplicate = service.observe_positive_ev(
        [positive_ev_row()], first_at + timedelta(seconds=12)
    )
    assert second == {"observed": 1, "qualified": 1}
    assert duplicate == {"observed": 1, "qualified": 0}
    dashboard = service.dashboard(
        scope="signal", user_id=LAB_TRACKER_GLOBAL_USER_ID, source="positive_ev", window="all"
    )
    assert dashboard["summary"]["tracked"] == 1
    assert dashboard["summary"]["open"] == 1
    assert dashboard["openBets"][0]["sportsbook_name"] == "FanDuel"
    assert dashboard["openBets"][0]["market_line"] == 8.5


def test_grades_supported_market_and_copies_to_personal_scope(tmp_path):
    service = LabTrackerService(TrackerDatabase(tmp_path / "lab.db"))
    first_at = datetime(2026, 8, 14, 20, 0, tzinfo=timezone.utc)
    service.observe_positive_ev([positive_ev_row()], first_at)
    service.observe_positive_ev([positive_ev_row()], first_at + timedelta(seconds=6))
    signal = service.dashboard(
        scope="signal", user_id=LAB_TRACKER_GLOBAL_USER_ID, source=None, window="all"
    )["openBets"][0]

    personal = service.add_personal("user-1", signal["bet_id"])
    assert personal is not None
    result = service.settle(
        [
            {
                "id": "event-1",
                "completed": True,
                "home_team": "New York Yankees",
                "away_team": "Boston Red Sox",
                "commence_time": "2026-08-14T23:00:00Z",
                "scores": [
                    {"name": "New York Yankees", "score": "6"},
                    {"name": "Boston Red Sox", "score": "4"},
                ],
            }
        ]
    )
    assert result["settled"] == 2
    signal_dashboard = service.dashboard(
        scope="signal", user_id=LAB_TRACKER_GLOBAL_USER_ID, source=None, window="all"
    )
    personal_dashboard = service.dashboard(
        scope="personal", user_id="user-1", source=None, window="all"
    )
    assert signal_dashboard["summary"]["profit"] == 110.0
    assert signal_dashboard["summary"]["units"] == 1.1
    assert signal_dashboard["lastGraded"][0]["result"] == "won"
    assert personal_dashboard["summary"]["tracked"] == 1
    assert personal_dashboard["summary"]["profit"] == 110.0


def test_positive_ev_never_falls_back_to_a_different_event_id(tmp_path):
    service = LabTrackerService(TrackerDatabase(tmp_path / "lab.db"))
    first_at = datetime(2026, 8, 14, 20, 0, tzinfo=timezone.utc)
    service.observe_positive_ev([positive_ev_row()], first_at)
    service.observe_positive_ev([positive_ev_row()], first_at + timedelta(seconds=6))

    result = service.settle(
        [
            {
                "id": "different-event",
                "completed": True,
                "home_team": "New York Yankees",
                "away_team": "Boston Red Sox",
                "commence_time": "2026-08-14T23:00:00Z",
                "scores": [
                    {"name": "New York Yankees", "score": "10"},
                    {"name": "Boston Red Sox", "score": "0"},
                ],
            }
        ]
    )
    assert result["settled"] == 0
    dashboard = service.dashboard(
        scope="signal", user_id=LAB_TRACKER_GLOBAL_USER_ID, source=None, window="all"
    )
    assert dashboard["summary"]["open"] == 1


def test_lab_tracker_page_and_empty_api_are_separate_from_bet_tracker(app_client):
    page = app_client.get("/lab-tracker")
    assert page.status_code == 200
    assert b"LabTracker" in page.data
    assert b"Bet Tracker" in page.data
    assert b"Demo View" in page.data
    assert b"5-second verification" not in page.data

    response = app_client.get("/api/lab-tracker?window=all")
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["summary"]["tracked"] == 0
    assert payload["unitValue"] == 100.0


def test_demo_dashboard_is_populated_and_never_changes_real_tracker(app_client):
    demo = app_client.get("/api/lab-tracker?window=7d&demo=1")
    assert demo.status_code == 200
    payload = demo.get_json()["data"]
    assert payload["demoOnly"] is True
    assert payload["summary"]["tracked"] >= 50
    assert len(payload["sportsbooks"]) == 18
    assert len(payload["leagues"]) >= 10
    assert len(payload["markets"]) >= 15
    assert len(payload["lastGraded"]) == 5
    assert payload["openBets"]

    real = app_client.get("/api/lab-tracker?window=all")
    assert real.status_code == 200
    real_payload = real.get_json()["data"]
    assert real_payload["demoOnly"] is False
    assert real_payload["summary"]["tracked"] == 0


def test_demo_dashboard_filters_sources_and_personal_preview():
    positive_ev = demo_dashboard(
        scope="signal", source="positive_ev", window="7d"
    )
    personal = demo_dashboard(scope="personal", source=None, window="7d")
    assert positive_ev["summary"]["tracked"] > 0
    assert all(row["source"] == "positive_ev" for row in positive_ev["openBets"])
    assert personal["demoOnly"] is True
    assert 0 < personal["summary"]["tracked"] < positive_ev["summary"]["tracked"] * 2
