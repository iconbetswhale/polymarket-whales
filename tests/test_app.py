from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from config import Settings
from database import TrackerDatabase
from position_tracker import TrackerService
from app import _format_event_start, _has_positive_recommendation, _trade_card_view


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


def _actionable_trade() -> dict:
    event_time = datetime.now(timezone.utc) + timedelta(days=1)
    return {
        "id": "market-1::outcome-a",
        "event_slug": "event-1",
        "event_title": "Spain vs France",
        "market_title": "To Advance",
        "market_line": None,
        "outcome": "Spain",
        "clob_token_id": "outcome-a",
        "event_date_et": event_time.isoformat(),
        "event_time_et": "Tomorrow, 3:00 PM ET",
        "market_url": "https://polymarket.com/event/example",
        "category": "Soccer",
        "league": "World Cup",
        "sports_market_type": "to_advance",
        "agreeing_wallet_count": 1,
        "confidence_score": 90,
        "combined_exposure_exact": 2000,
        "average_entry_price": 0.4,
        "primary_trader": {
            "amount": 2000,
            "relative_units": 2,
            "wallet_label": "Sharp",
        },
        "supporting_wallets": [],
        "evidence_inputs": {"adjusted_category_hit_rate": 0.6},
        "validation_ids": {
            "event_id": "event-1",
            "condition_id": "market-1",
            "outcome_token_id": "outcome-a",
            "event_slug": "event-1",
            "market_slug": "market-1",
        },
        "orderbook": {},
    }


def _positive_recommendation(*_args, **_kwargs) -> dict:
    return {
        "available": True,
        "final_recommended_fraction": 0.01,
        "recommended_amount": 100,
        "recommended_units": 1,
        "recommended_shares": 250,
        "current_user_entry_price": 0.4,
        "sharp_average_entry_price": 0.4,
    }


def _positive_evaluation(play: dict, *_args, **_kwargs) -> dict:
    return {
        "play": play,
        "recommendation": _positive_recommendation(),
        "model_tracker_eligible": False,
        "model_tracker_rejection_reason": "NOT_TODAY",
        "recommendation_snapshot_id": "snapshot-id",
        "recommendation_idempotency_key": "dedupe-key",
    }


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
    service = TrackerService(
        settings,
        client=client,
        database=TrackerDatabase(settings.database_path),
        auto_start=False,
    )
    service.refresh()
    snapshot = service.get_snapshot()
    assert snapshot["status"]["enabled_wallet_count"] == 0
    assert client.current_calls == []


def test_status_endpoints(app_client):
    assert app_client.get("/api/positions").status_code == 200
    assert app_client.get("/api/wallets").status_code == 200
    assert app_client.get("/api/trades").status_code == 200
    assert app_client.get("/api/trades-to-play").status_code == 200
    assert app_client.get("/api/history?page=1&per_page=25").status_code == 200
    assert app_client.get("/api/consensus").status_code == 200
    assert app_client.get("/api/unit-analysis").status_code == 404
    assert app_client.get("/api/status").status_code == 200
    assert app_client.get("/api/user-settings").status_code == 200
    assert app_client.get("/api/bet-tracker").status_code == 200


def test_tracker_page_contains_real_job_status_and_admin_controls(app_client):
    html = app_client.get("/bet-tracker").get_data(as_text=True)

    assert 'id="tracker-job-state"' in html
    assert 'id="tracker-reconcile"' in html
    assert 'id="tracker-pause-job"' in html
    assert 'id="tracker-rejection-body"' in html
    assert "/static/app.js?v=local" in html
    assert "/static/style.css?v=local" in html


def test_scheduled_tracker_record_appears_after_api_revalidation(app_client):
    service = app_client.application.extensions["tracker_service"]
    app_client.set_cookie("iconbets_user", "render-user")
    assert app_client.get("/api/bet-tracker").get_json()["pagination"]["total"] == 0
    snapshot = {
        "snapshot_id": "render-snapshot",
        "dedupe_key": "event::market::::outcome::v2",
        "recommendation_version": "v2",
        "recommendation_timestamp": datetime.now(timezone.utc).isoformat(),
        "event_title": "Spain vs France",
        "market_title": "To Advance",
        "recommended_side": "Spain",
        "event_start_time": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "effective_entry_price": 0.4,
        "final_recommended_fraction": 0.005,
        "original_displayed_amount": 50,
        "original_recommended_units": 0.5,
        "estimated_win_probability": 0.42,
        "sharps_count": 1,
    }
    assert service.database.insert_tracker_snapshot("render-user", snapshot) is True

    payload = app_client.get("/api/bet-tracker").get_json()
    assert payload["pagination"]["total"] == 1
    assert payload["data"][0]["status"] == "scheduled"


def test_dedicated_pages_are_real_routes(app_client):
    for route in (
        "/overview",
        "/trades",
        "/live-positions",
        "/wallets",
        "/position-history",
        "/bet-tracker",
    ):
        response = app_client.get(route)
        assert response.status_code == 200
        assert response.request.path == route

    assert app_client.get("/").status_code == 302
    assert app_client.get("/history").status_code == 301


def test_trade_date_presets_reject_removed_modes(app_client):
    for mode in ("tomorrow", "next48", "week", "all"):
        assert (
            app_client.get(f"/api/trades-to-play?date_range={mode}").status_code == 400
        )


def test_only_positive_executable_recommendations_are_actionable():
    positive = {
        "recommendation": {
            "available": True,
            "final_recommended_fraction": 0.001,
            "recommended_amount": 10,
        }
    }
    zero_stake = {
        "recommendation": {
            "available": True,
            "final_recommended_fraction": 0,
            "recommended_amount": 0,
        }
    }
    unavailable = {
        "recommendation": {
            "available": False,
            "final_recommended_fraction": 0.001,
            "recommended_amount": 10,
        }
    }

    assert _has_positive_recommendation(positive) is True
    assert _has_positive_recommendation(zero_stake) is False
    assert _has_positive_recommendation(unavailable) is False


def test_event_start_display_uses_eastern_today_tomorrow_and_future_dates():
    now = datetime(2026, 7, 13, 16, 0, tzinfo=timezone.utc)

    assert _format_event_start("2026-07-13T19:10:00-04:00", now) == "Today, 7:10 PM"
    assert _format_event_start("2026-07-14T15:00:00-04:00", now) == "Tomorrow, 3:00 PM"
    assert _format_event_start("2026-07-19T23:59:00-04:00", now) == "Jul 19, 11:59 PM"
    assert (
        _format_event_start("2027-01-03T14:00:00-05:00", now)
        == "Jan 3, 2027 \u00b7 2:00 PM"
    )
    assert _format_event_start(None, now) == "Time unavailable"


def test_trade_card_view_uses_real_metric_and_recommendation_values():
    play = {
        "event_date_et": "2026-07-14T15:00:00-04:00",
        "average_entry_price": 0.405,
        "primary_trader": {"amount": 2036.42, "relative_units": 3.5},
        "evidence_inputs": {"adjusted_category_hit_rate": 0.5908},
    }
    recommendation = {
        "sharp_average_entry_price": 0.405,
        "current_user_entry_price": 0.4,
        "recommended_shares": 385,
        "recommended_amount": 154,
        "recommended_units": 1.54,
    }
    now = datetime(2026, 7, 13, 16, 0, tzinfo=timezone.utc)

    card = _trade_card_view(play, recommendation, now)

    assert card == {
        "event_time": "Tomorrow, 3:00 PM",
        "trader_bet_amount": 2036.42,
        "trader_average_entry_price": 0.405,
        "relative_bet_size": 3.5,
        "category_hit_rate": 0.5908,
        "recommended_shares": 385,
        "recommended_amount": 154,
        "recommended_units": 1.54,
        "current_actionable_price": 0.4,
    }


def test_trade_feed_bulk_loads_personal_exposure_once(app_client, monkeypatch):
    import app as app_module

    service = app_client.application.extensions["tracker_service"]
    service._cache["trades_to_play"] = [
        _actionable_trade(),
        {
            **_actionable_trade(),
            "id": "market-2::outcome-b",
            "market_title": "Moneyline",
            "clob_token_id": "outcome-b",
            "validation_ids": {
                **_actionable_trade()["validation_ids"],
                "condition_id": "market-2",
                "outcome_token_id": "outcome-b",
            },
        },
    ]
    monkeypatch.setattr(service, "evaluate_recommendation", _positive_evaluation)
    monkeypatch.setattr(service, "track_recommendations_for_user", lambda *_args: 0)
    calls = 0
    original = service.database.get_personal_bet_fills

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(service.database, "get_personal_bet_fills", counted)

    response = app_client.get("/api/trades-to-play?date_range=next7")

    assert response.status_code == 200
    assert response.get_json()["pagination"]["total"] == 2
    assert calls == 1


def test_hide_restore_and_show_hidden_are_user_specific(app_client, monkeypatch):
    import app as app_module

    service = app_client.application.extensions["tracker_service"]
    service._cache["trades_to_play"] = [_actionable_trade()]
    monkeypatch.setattr(service, "evaluate_recommendation", _positive_evaluation)
    monkeypatch.setattr(service, "track_recommendations_for_user", lambda *_args: 0)
    app_client.set_cookie("iconbets_user", "user-1")

    hidden = app_client.post(
        "/api/hidden-trades", json={"trade_id": "market-1::outcome-a"}
    )
    visible = app_client.get("/api/trades-to-play?date_range=next7")
    shown = app_client.get("/api/trades-to-play?date_range=next7&show_hidden=true")
    other_user = app_client.application.test_client()
    other_user.set_cookie("iconbets_user", "user-2")
    other_visible = other_user.get("/api/trades-to-play?date_range=next7")

    assert hidden.status_code == 201
    assert visible.get_json()["pagination"]["total"] == 0
    assert shown.get_json()["data"][0]["isHidden"] is True
    assert other_visible.get_json()["pagination"]["total"] == 1

    hidden_id = hidden.get_json()["data"]["id"]
    assert other_user.delete(f"/api/hidden-trades/{hidden_id}").status_code == 404
    assert app_client.delete(f"/api/hidden-trades/{hidden_id}").status_code == 200
    assert (
        app_client.get("/api/trades-to-play?date_range=next7").get_json()["pagination"][
            "total"
        ]
        == 1
    )


def test_confirmed_personal_fill_warns_and_duplicate_requires_confirmation(
    app_client, monkeypatch
):
    import app as app_module

    service = app_client.application.extensions["tracker_service"]
    service._cache["trades_to_play"] = [_actionable_trade()]
    monkeypatch.setattr(service, "evaluate_recommendation", _positive_evaluation)
    monkeypatch.setattr(service, "track_recommendations_for_user", lambda *_args: 0)
    app_client.set_cookie("iconbets_user", "personal-user")
    purchase = {
        "trade_id": "market-1::outcome-a",
        "entry_price": 0.4,
        "shares": 100,
        "fees": 1,
    }

    first = app_client.post("/api/personal-bets", json=purchase)
    duplicate = app_client.post("/api/personal-bets", json=purchase)
    second = app_client.post(
        "/api/personal-bets", json={**purchase, "confirm_duplicate": True}
    )
    feed = app_client.get("/api/trades-to-play?date_range=next7").get_json()

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.get_json()["confirmationRequired"] == "duplicate"
    assert second.status_code == 201
    assert feed["data"][0]["personalExposureType"] == "exact"
    assert feed["data"][0]["personalEntryCount"] == 2

    other_user = app_client.application.test_client()
    other_user.set_cookie("iconbets_user", "another-user")
    other_feed = other_user.get("/api/trades-to-play?date_range=next7").get_json()
    assert other_feed["data"][0]["personalExposureType"] == "none"


def test_opposing_personal_fill_requires_explicit_confirmation(app_client, monkeypatch):
    import app as app_module

    service = app_client.application.extensions["tracker_service"]
    recommended = _actionable_trade()
    opposing = {
        **_actionable_trade(),
        "id": "market-1::outcome-b",
        "outcome": "France",
        "clob_token_id": "outcome-b",
        "validation_ids": {
            **_actionable_trade()["validation_ids"],
            "outcome_token_id": "outcome-b",
        },
    }
    service._cache["trades_to_play"] = [recommended, opposing]
    monkeypatch.setattr(service, "evaluate_recommendation", _positive_evaluation)
    monkeypatch.setattr(service, "track_recommendations_for_user", lambda *_args: 0)
    app_client.set_cookie("iconbets_user", "conflict-user")
    payload = {"entry_price": 0.4, "shares": 100, "fees": 0}
    assert (
        app_client.post(
            "/api/personal-bets",
            json={**payload, "trade_id": "market-1::outcome-b"},
        ).status_code
        == 201
    )

    blocked = app_client.post(
        "/api/personal-bets",
        json={**payload, "trade_id": "market-1::outcome-a"},
    )
    confirmed = app_client.post(
        "/api/personal-bets",
        json={
            **payload,
            "trade_id": "market-1::outcome-a",
            "confirm_conflict": True,
        },
    )

    assert blocked.status_code == 409
    assert blocked.get_json()["confirmationRequired"] == "conflict"
    assert confirmed.status_code == 201
