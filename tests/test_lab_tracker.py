import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database import TrackerDatabase
from lab_tracker import (
    DEMO_SPORTSBOOKS,
    LAB_TRACKER_GLOBAL_USER_ID,
    PREDICTION_TRADER_PROVIDERS,
    LabTrackerService,
    demo_dashboard,
)


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


def prediction_snapshot(provider_key: str, sportsbook: str, suffix: str) -> dict:
    return {
        "snapshot_id": f"prediction-snapshot-{suffix}",
        "dedupe_key": f"event-{suffix}::market-{suffix}::yes::v1",
        "recommendation_timestamp": "2026-08-14T12:00:00+00:00",
        "event_start_time": "2026-08-14T20:00:00+00:00",
        "final_recommended_fraction": 0.01,
        "original_displayed_amount": 100.0,
        "provider_entry_price": 0.4,
        "effective_entry_price": 0.4,
        "provider_display_odds": "+150",
        "provider_key": provider_key,
        "sportsbook": sportsbook,
        "canonical_event_id": f"event-{suffix}",
        "canonical_market_id": f"market-{suffix}",
        "event_title": f"Prediction event {suffix}",
        "market_title": "To Win",
        "sports_market_type": "moneyline",
        "recommended_side": "Yes",
        "category": "Soccer",
        "league": "World Cup",
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


def test_prediction_traders_mirrors_every_real_model_tracker_provider(tmp_path):
    database = TrackerDatabase(tmp_path / "lab.db")
    service = LabTrackerService(database, model_tracker_user_id="model-ledger")
    allowed = (
        ("oddsapi__novig", "NoVIG", "novig"),
        ("prophetx", "ProphetX", "prophetx"),
        ("polymarket", "Polymarket", "polymarket"),
        ("kalshi", "Kalshi", "kalshi"),
        ("fourcx", "4CX", "4cx"),
    )
    for provider_key, sportsbook, suffix in allowed:
        assert database.insert_tracker_snapshot(
            "model-ledger",
            prediction_snapshot(provider_key, sportsbook, suffix),
            status="won",
        )
    assert database.insert_tracker_snapshot(
        "model-ledger",
        prediction_snapshot("oddsapi__fanduel", "FanDuel", "fanduel"),
        status="won",
    )

    prediction = service.dashboard(
        scope="signal",
        user_id=LAB_TRACKER_GLOBAL_USER_ID,
        source="prediction_traders",
        window="all",
    )
    all_signals = service.dashboard(
        scope="signal",
        user_id=LAB_TRACKER_GLOBAL_USER_ID,
        source=None,
        window="all",
    )
    positive_ev = service.dashboard(
        scope="signal",
        user_id=LAB_TRACKER_GLOBAL_USER_ID,
        source="positive_ev",
        window="all",
    )

    assert prediction["summary"]["tracked"] == 6
    assert prediction["summary"]["profit"] == 900.0
    assert {row["name"] for row in prediction["sportsbooks"]} == {
        "NoVIG",
        "ProphetX",
        "Polymarket",
        "Kalshi",
        "4CX",
        "FanDuel",
    }
    assert prediction["lastGraded"][0]["source"] == "prediction_traders"
    assert {item["name"] for item in prediction["markets"]} == {"Moneyline"}
    assert all_signals["summary"]["tracked"] == 6
    assert positive_ev["summary"]["tracked"] == 0


def test_prediction_traders_reads_future_inserts_and_grades_from_shared_ledger(tmp_path):
    database = TrackerDatabase(tmp_path / "lab.db")
    service = LabTrackerService(database, model_tracker_user_id="model-ledger")
    legacy = prediction_snapshot("", "", "legacy")
    future = prediction_snapshot("futureexchange", "Future Exchange", "future")

    assert database.insert_tracker_snapshot("model-ledger", legacy)
    first = service.dashboard(
        scope="signal",
        user_id=LAB_TRACKER_GLOBAL_USER_ID,
        source="prediction_traders",
        window="all",
    )
    assert first["summary"]["tracked"] == 1
    assert first["summary"]["open"] == 1
    assert first["openBets"][0]["sportsbook_name"] == "Polymarket"

    assert database.insert_tracker_snapshot("model-ledger", future)
    database.update_tracker_status(
        "model-ledger",
        future["dedupe_key"],
        "won",
        "Won",
        "2026-08-14T21:00:00+00:00",
    )
    refreshed = service.dashboard(
        scope="signal",
        user_id=LAB_TRACKER_GLOBAL_USER_ID,
        source="prediction_traders",
        window="all",
    )
    assert refreshed["summary"]["tracked"] == 2
    assert refreshed["summary"]["open"] == 1
    assert refreshed["summary"]["wins"] == 1
    assert {row["name"] for row in refreshed["sportsbooks"]} == {"Future Exchange"}
    assert refreshed["openBets"][0]["sportsbook_name"] == "Polymarket"
    assert refreshed["lastGraded"][0]["candidate_id"] == future["dedupe_key"]


def test_my_bets_reads_existing_manual_personal_fills(tmp_path):
    database = TrackerDatabase(tmp_path / "lab.db")
    service = LabTrackerService(database)
    database.insert_personal_bet_fill(
        "user-1",
        {
            "fill_id": "manual-fill-1",
            "canonical_event_id": "manual-event-1",
            "canonical_market_id": "manual-market-1",
            "canonical_outcome_id": "manual-outcome-1",
            "event_title": "Manual event",
            "market_title": "Moneyline",
            "selection": "Home",
            "entry_price": 0.4,
            "shares": 250.0,
            "position_cost": 100.0,
            "fees": 0.0,
            "total_paid": 100.0,
            "sportsbook": "DraftKings",
            "tags": ["Test"],
        },
        status="scheduled",
    )
    database.update_personal_bet_status(
        "manual-fill-1", "won", "Won", "2026-08-14T23:00:00+00:00"
    )

    personal = service.dashboard(
        scope="personal", user_id="user-1", source=None, window="all"
    )
    signals = service.dashboard(
        scope="signal",
        user_id=LAB_TRACKER_GLOBAL_USER_ID,
        source=None,
        window="all",
    )

    assert personal["summary"]["tracked"] == 1
    assert personal["summary"]["profit"] == 150.0
    assert personal["sportsbooks"][0]["name"] == "DraftKings"
    assert personal["lastGraded"][0]["source"] == "personal"
    assert signals["summary"]["tracked"] == 0


def test_lab_tracker_page_and_empty_api_are_separate_from_bet_tracker(app_client):
    page = app_client.get("/lab-tracker")
    assert page.status_code == 200
    assert b"LabTracker" in page.data
    assert b"Bet Tracker" in page.data
    assert b"Demo View" not in page.data
    assert b"Prediction Traders" in page.data
    assert b"5-second verification" not in page.data
    assert b"Open plays" not in page.data

    response = app_client.get("/api/lab-tracker?window=all")
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["summary"]["tracked"] == 0
    assert payload["unitValue"] == 100.0

    prediction = app_client.get(
        "/api/lab-tracker?source=prediction_traders&window=all"
    ).get_json()["data"]
    assert prediction["source"] == "prediction_traders"


def test_demo_parameter_cannot_enable_lab_tracker_fixture(app_client):
    attempted_demo = app_client.get("/api/lab-tracker?window=7d&demo=1")
    live = app_client.get("/api/lab-tracker?window=7d")

    assert attempted_demo.status_code == 200
    assert live.status_code == 200
    assert attempted_demo.get_json() == live.get_json()
    assert attempted_demo.get_json()["data"]["demoOnly"] is False
    assert attempted_demo.get_json()["data"]["summary"]["tracked"] == 0


def test_demo_dashboard_filters_sources_and_keeps_prediction_records_real(tmp_path):
    database = TrackerDatabase(tmp_path / "demo.db")
    database.insert_tracker_snapshot(
        "model-ledger",
        prediction_snapshot("prophetx", "ProphetX", "real-preview"),
        status="won",
    )
    prediction_records = database.get_tracker_records("model-ledger")
    positive_ev = demo_dashboard(
        scope="signal", source="positive_ev", window="7d"
    )
    personal = demo_dashboard(scope="personal", source=None, window="7d")
    prediction = demo_dashboard(
        scope="signal",
        source="prediction_traders",
        window="all",
        prediction_records=prediction_records,
    )
    all_signals = demo_dashboard(
        scope="signal",
        source=None,
        window="all",
        prediction_records=prediction_records,
    )
    assert positive_ev["summary"]["tracked"] > 0
    assert all(row["source"] == "positive_ev" for row in positive_ev["openBets"])
    assert prediction["summary"]["tracked"] == 1
    assert prediction["lastGraded"][0]["sportsbook_key"] == "prophetx"
    assert prediction["demoOnly"] is False
    assert all_signals["summary"]["tracked"] > prediction["summary"]["tracked"]
    assert all_signals["demoOnly"] is True
    assert personal["demoOnly"] is True
    assert 0 < personal["summary"]["tracked"] < positive_ev["summary"]["tracked"] * 2


def test_demo_sportsbook_logos_are_local_and_served(app_client):
    assert len(DEMO_SPORTSBOOKS) == 19
    for _, book_name, logo_path in DEMO_SPORTSBOOKS:
        assert logo_path.startswith(
            ("/static/assets/sportsbooks/", "/static/assets/providers/")
        )
        response = app_client.get(logo_path.split("?", 1)[0])
        assert response.status_code == 200, book_name
        assert response.content_type.startswith("image/"), book_name


def test_lab_tracker_league_logos_are_local_and_served(app_client):
    league_assets = (
        "nba.png", "mlb.png", "mls.png", "wnba.png", "wta.png", "nhl.png",
        "atp.png", "ncaa.png", "nfl.png", "fifa.png", "uefa.png", "epl.png",
    )
    for filename in league_assets:
        response = app_client.get(f"/static/assets/leagues/{filename}")
        assert response.status_code == 200, filename
        assert response.content_type.startswith("image/"), filename


def test_lab_tracker_maps_tennis_and_colors_negative_charts_red():
    script = Path("static/lab-tracker.js").read_text(encoding="utf-8")
    assert 'tennis: "/static/assets/leagues/atp.png"' in script
    assert 'Number(state.data.summary.profit || 0) < 0 ? "#ff4d5e"' in script


def test_vercel_runs_lab_tracker_reconciliation_every_minute():
    config = json.loads(Path("vercel.json").read_text(encoding="utf-8"))
    schedules = {
        item["path"]: item["schedule"] for item in config.get("crons", [])
    }
    assert schedules["/api/admin/lab-tracker/reconcile"] == "* * * * *"
