from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from config import Settings
from database import TrackerDatabase
from position_tracker import MODEL_TRACKER_USER_ID, TrackerService
from app import (
    _format_event_start,
    _has_positive_recommendation,
    _slippage_fraction,
    _trade_card_view,
)


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
        "canonical_category_id": "soccer",
        "canonical_sport_id": "soccer",
        "league": "World Cup",
        "sports_market_type": "to_advance",
        "search_blob": "spain france to-advance soccer world-cup sharp",
        "agreeing_wallet_count": 1,
        "raw_sharp_count": 1,
        "lead_sharp_count": 1,
        "supporting_sharp_count": 0,
        "weighted_sharp_count": 1.0,
        "has_lead_sharp": True,
        "confidence_score": 90,
        "combined_exposure_exact": 2000,
        "average_entry_price": 0.4,
        "primary_trader": {
            "amount": 2000,
            "relative_units": 2,
            "wallet_label": "Sharp",
            "is_lead_sharp": True,
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
        "effective_entry_price": 0.4,
        "current_top_ask_price": 0.4,
        "sharp_average_entry_price": 0.4,
        "sharp_reference_entry_price": 0.4,
        "slippage_cents": 0,
        "price_slippage_fraction": 0,
        "unfavorable_slippage_pct": 0,
        "passes_slippage_rule": True,
        "slippage_rejection_reason": None,
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


def _evaluation_at(entry: float, *, passes: bool = True, reason: str | None = None):
    def evaluate(play: dict, *_args, **_kwargs) -> dict:
        recommendation = {
            **_positive_recommendation(),
            "current_user_entry_price": entry,
            "effective_entry_price": entry,
            "current_top_ask_price": entry,
            "unfavorable_slippage_pct": ((entry - 0.4) / 0.4) * 100,
            "passes_slippage_rule": passes,
            "slippage_rejection_reason": reason,
        }
        return {
            "play": play,
            "recommendation": recommendation,
            "model_tracker_eligible": False,
            "model_tracker_rejection_reason": "NOT_TODAY",
            "recommendation_snapshot_id": "snapshot-id",
            "recommendation_idempotency_key": f"dedupe-{entry}",
        }

    return evaluate


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
    assert app_client.get("/api/model-tracker").status_code == 200
    assert app_client.get("/api/personal-tracker").status_code == 200


def test_tracker_page_contains_real_job_status_and_admin_controls(app_client):
    html = app_client.get("/tracker?view=model").get_data(as_text=True)

    assert "Model Tracker" in html
    assert "Personal Tracker" in html
    assert 'id="tracker-view-toggle"' in html
    assert 'id="tracker-job-state"' in html
    assert 'id="tracker-bankroll-edit"' in html
    assert 'id="tracker-bankroll-dialog"' in html
    assert 'id="tracker-bankroll-form"' in html
    assert "Tracker profile" not in html
    assert 'id="tracker-reconcile"' in html
    assert 'id="tracker-pause-job"' in html
    assert 'id="tracker-rejection-body"' in html
    assert 'id="tracker-admin-form"' in html
    assert 'id="tracker-admin-password"' in html
    assert "/static/app.js?v=local" in html
    assert "/static/style.css?v=local" in html


def test_tracker_page_uses_one_shared_shell_for_both_trackers(app_client):
    html = app_client.get("/tracker?view=personal").get_data(as_text=True)

    assert html.count('href="/tracker"') == 1
    assert 'id="tracker-metrics"' in html
    assert 'id="tracker-chart"' in html
    assert 'id="tracker-body"' in html
    assert 'id="personal-bankroll-control"' in html
    assert 'id="model-bankroll-control"' in html
    assert 'href="/model-tracker"' not in html
    assert 'href="/personal-tracking"' not in html


def test_model_tracker_history_is_shared_across_browser_users(app_client):
    service = app_client.application.extensions["tracker_service"]
    assert service.database.insert_tracker_snapshot(
        MODEL_TRACKER_USER_ID,
        {
            "snapshot_id": "shared-snapshot",
            "dedupe_key": "shared-event::shared-market::::shared-outcome::v2",
            "recommendation_version": "v2",
            "recommendation_timestamp": datetime.now(timezone.utc).isoformat(),
            "event_title": "Shared tennis match",
            "market_title": "Match winner",
            "recommended_side": "Player A",
            "effective_entry_price": 0.5,
            "final_recommended_fraction": 0.005,
            "original_displayed_amount": 50,
            "original_recommended_units": 0.5,
            "estimated_win_probability": 0.55,
            "sharps_count": 1,
        },
    )
    first_user = app_client.application.test_client()
    first_user.set_cookie("iconbets_user", "first-browser")
    second_user = app_client.application.test_client()
    second_user.set_cookie("iconbets_user", "second-browser")

    first_payload = first_user.get("/api/model-tracker").get_json()
    second_payload = second_user.get("/api/model-tracker").get_json()

    assert first_payload["pagination"]["total"] == 1
    assert second_payload["pagination"]["total"] == 1
    assert first_payload["data"][0]["snapshot"]["event_title"] == "Shared tennis match"
    assert second_payload["data"][0]["snapshot_id"] == "shared-snapshot"


def test_tracker_bankroll_api_is_independent_from_trade_bankroll(app_client):
    app_client.set_cookie("iconbets_user", "bankroll-user")
    trade_settings = app_client.get("/api/user-settings").get_json()["data"]

    response = app_client.put(
        "/api/model-tracker/settings",
        json={"tracker_bankroll": 25000},
    )

    assert response.status_code == 200
    tracker_settings = response.get_json()["data"]
    assert tracker_settings["tracker_bankroll"] == 25000
    assert tracker_settings["starting_bankroll"] == trade_settings["starting_bankroll"]

    tracker_payload = app_client.get("/api/model-tracker").get_json()
    assert tracker_payload["summary"]["starting_bankroll"] == 25000
    assert (
        app_client.get("/api/user-settings").get_json()["data"]["starting_bankroll"]
        == trade_settings["starting_bankroll"]
    )


def test_tracker_bankroll_api_rejects_non_positive_values(app_client):
    response = app_client.put(
        "/api/model-tracker/settings",
        json={"tracker_bankroll": 0},
    )

    assert response.status_code == 400
    assert "greater than zero" in response.get_json()["error"]


def test_account_bankroll_persists_across_login_and_is_user_owned(app_client):
    default_bankroll = app_client.application.config["SETTINGS"].default_bankroll
    owner = app_client.application.test_client()
    initial = owner.get("/api/user-settings").get_json()["data"]
    saved = owner.put(
        "/api/user-settings",
        json={
            "trades_to_play_bankroll": 25000,
            "expected_version": initial["settings_version"],
        },
    )
    assert saved.status_code == 200
    assert saved.get_json()["data"]["unit_value"] == 250

    registered = owner.post(
        "/api/auth/register",
        json={"email": "owner@example.com", "password": "strong-pass-1"},
    )
    assert registered.status_code == 201

    another_device = app_client.application.test_client()
    assert another_device.post(
        "/api/auth/login",
        json={"email": "owner@example.com", "password": "strong-pass-1"},
    ).status_code == 200
    synced = another_device.get("/api/user-settings").get_json()["data"]
    assert synced["trades_to_play_bankroll"] == 25000
    assert synced["sizing_bankroll_configured"] is True

    other_account = app_client.application.test_client()
    other_account.get("/api/user-settings")
    assert other_account.post(
        "/api/auth/register",
        json={"email": "other@example.com", "password": "strong-pass-2"},
    ).status_code == 201
    other_settings = other_account.get("/api/user-settings").get_json()["data"]
    assert other_settings["trades_to_play_bankroll"] == default_bankroll
    assert other_settings["trades_to_play_bankroll"] != synced["trades_to_play_bankroll"]

    assert another_device.post("/api/auth/logout").status_code == 200
    signed_out_settings = another_device.get("/api/user-settings").get_json()["data"]
    assert signed_out_settings["trades_to_play_bankroll"] == default_bankroll


def test_failed_and_stale_bankroll_saves_preserve_confirmed_value(app_client):
    app_client.set_cookie("iconbets_user", "versioned-user")
    initial = app_client.get("/api/user-settings").get_json()["data"]
    first = app_client.put(
        "/api/user-settings",
        json={
            "trades_to_play_bankroll": 1000,
            "expected_version": initial["settings_version"],
        },
    )
    assert first.status_code == 200
    assert first.get_json()["data"]["unit_value"] == 10

    invalid = app_client.put(
        "/api/user-settings", json={"trades_to_play_bankroll": 0}
    )
    stale = app_client.put(
        "/api/user-settings",
        json={
            "trades_to_play_bankroll": 50000,
            "expected_version": initial["settings_version"],
        },
    )

    assert invalid.status_code == 400
    assert stale.status_code == 409
    assert stale.get_json()["data"]["trades_to_play_bankroll"] == 1000
    current = app_client.get("/api/user-settings").get_json()["data"]
    assert current["trades_to_play_bankroll"] == 1000


def test_personal_bankroll_and_view_preference_are_separate_per_user(app_client):
    first = app_client.application.test_client()
    second = app_client.application.test_client()
    first.set_cookie("iconbets_user", "first-preferences")
    second.set_cookie("iconbets_user", "second-preferences")
    first.get("/api/user-settings")
    second.get("/api/user-settings")

    assert first.put(
        "/api/personal-tracker/settings",
        json={"personal_tracker_bankroll": 5000},
    ).status_code == 200
    assert first.put(
        "/api/tracker-preference", json={"view": "personal"}
    ).status_code == 200

    first_settings = first.get("/api/user-settings").get_json()["data"]
    second_settings = second.get("/api/user-settings").get_json()["data"]
    assert first_settings["personal_tracker_bankroll"] == 5000
    assert first_settings["tracker_view"] == "personal"
    assert second_settings["personal_tracker_bankroll"] != 5000
    assert second_settings["tracker_view"] == "model"
    assert first.get("/api/personal-tracker").get_json()["summary"][
        "starting_bankroll"
    ] == 5000


def test_tracker_shell_script_supports_query_memory_and_keyboard_navigation():
    script = (Path(__file__).parents[1] / "static" / "app.js").read_text()

    assert 'params.get("view")' in script
    assert 'fetchJson("/api/tracker-preference"' in script
    assert '"ArrowLeft", "ArrowRight", "Home", "End"' in script
    assert 'appState.trackerCache = ' not in script
    assert 'trackerCache: { model: null, personal: null }' in script


def test_scheduled_tracker_record_appears_after_api_revalidation(app_client):
    service = app_client.application.extensions["tracker_service"]
    app_client.set_cookie("iconbets_user", "render-user")
    assert app_client.get("/api/model-tracker").get_json()["pagination"]["total"] == 0
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
    assert service.database.insert_tracker_snapshot(MODEL_TRACKER_USER_ID, snapshot) is True

    payload = app_client.get("/api/model-tracker").get_json()
    assert payload["pagination"]["total"] == 1
    assert payload["data"][0]["status"] == "scheduled"


def test_dedicated_pages_and_tracker_redirects(app_client):
    for route in (
        "/overview",
        "/trades",
        "/live-positions",
        "/wallets",
        "/position-history",
        "/tracker",
    ):
        response = app_client.get(route)
        assert response.status_code == 200
        assert response.request.path == route

    assert app_client.get("/").status_code == 302
    assert app_client.get("/history").status_code == 301
    redirects = {
        "/model-tracker": "/tracker?view=model",
        "/bet-tracker": "/tracker?view=model",
        "/personal-tracking": "/tracker?view=personal",
        "/personal-tracker": "/tracker?view=personal",
    }
    for route, target in redirects.items():
        response = app_client.get(route)
        assert response.status_code == 301
        assert response.headers["Location"].endswith(target)


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
        "slippage_fraction": (0.4 - 0.405) / 0.405,
    }


def test_slippage_fraction_uses_whale_entry_as_the_percentage_baseline():
    worse = _slippage_fraction(0.4, 0.389)
    better = _slippage_fraction(0.389, 0.4)

    assert round(worse * 100, 1) == 2.8
    assert round(better * 100, 1) == -2.8
    assert _slippage_fraction(0.4, 0) is None


def test_trade_feed_bulk_loads_personal_exposure_once(app_client, monkeypatch):
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


def test_trade_feed_includes_polymarket_execution_option(app_client, monkeypatch):
    service = app_client.application.extensions["tracker_service"]
    service._cache["trades_to_play"] = [_actionable_trade()]
    monkeypatch.setattr(service, "evaluate_recommendation", _positive_evaluation)

    response = app_client.get("/api/trades-to-play?date_range=next7")

    assert response.status_code == 200
    options = response.get_json()["data"][0]["executionOptions"]
    assert [option["providerName"] for option in options] == ["Polymarket"]
    assert options[0]["matchingConfidence"] == "Exact"
    assert options[0]["deepLink"] == "https://polymarket.com/event/example"


@pytest.mark.parametrize(
    ("query", "entry", "expected_total"),
    [
        ("minEntryCents=20", 0.2, 1),
        ("minEntryCents=20", 0.199, 0),
        ("maxEntryCents=80", 0.8, 1),
        ("maxEntryCents=80", 0.801, 0),
        ("minEntryCents=20&maxEntryCents=80", 0.507, 1),
    ],
)
def test_entry_cents_filters_are_inclusive_and_backend_enforced(
    app_client, monkeypatch, query, entry, expected_total
):
    service = app_client.application.extensions["tracker_service"]
    service._cache["trades_to_play"] = [_actionable_trade()]
    monkeypatch.setattr(service, "evaluate_recommendation", _evaluation_at(entry))

    response = app_client.get(f"/api/trades-to-play?date_range=next7&{query}")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["pagination"]["total"] == expected_total
    if expected_total:
        trade = payload["data"][0]
        assert trade["effectiveEntryCents"] == pytest.approx(entry * 100)
        assert {
            "sharpReferenceEntryCents",
            "currentTopAskCents",
            "effectiveEntryCents",
            "slippageCents",
            "unfavorableSlippagePct",
            "passesSlippageRule",
            "slippageRejectionReason",
        } <= trade.keys()


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ("minEntryCents=80&maxEntryCents=20", "cannot exceed"),
        ("minEntryCents=0", "greater than 0"),
        ("maxEntryCents=100", "less than 100"),
        ("minEntryCents=20.11", "one decimal"),
        ("maxEntryCents=not-a-price", "must be a number"),
    ],
)
def test_entry_cents_filter_validation_returns_clear_backend_error(
    app_client, query, message
):
    response = app_client.get(f"/api/trades-to-play?date_range=next7&{query}")

    assert response.status_code == 400
    assert message in response.get_json()["error"]


def test_excess_slippage_is_absent_from_backend_feed(app_client, monkeypatch):
    service = app_client.application.extensions["tracker_service"]
    service._cache["trades_to_play"] = [_actionable_trade()]
    monkeypatch.setattr(
        service,
        "evaluate_recommendation",
        _evaluation_at(0.421, passes=False, reason="SLIPPAGE_ABOVE_MAX"),
    )

    response = app_client.get("/api/trades-to-play?date_range=next7")

    assert response.status_code == 200
    assert response.get_json()["pagination"]["total"] == 0


def test_search_date_sharps_and_entry_price_filters_compose(app_client, monkeypatch):
    service = app_client.application.extensions["tracker_service"]
    service._cache["trades_to_play"] = [_actionable_trade()]
    monkeypatch.setattr(service, "evaluate_recommendation", _evaluation_at(0.507))

    matching = app_client.get(
        "/api/trades-to-play?date_range=next7&q=Spain&min_sharps=1"
        "&minEntryCents=20&maxEntryCents=80"
    )
    too_many_sharps = app_client.get(
        "/api/trades-to-play?date_range=next7&q=Spain&min_sharps=2"
        "&minEntryCents=20&maxEntryCents=80"
    )
    unrestricted = app_client.get("/api/trades-to-play?date_range=next7")

    assert matching.get_json()["pagination"]["total"] == 1
    assert too_many_sharps.get_json()["pagination"]["total"] == 0
    assert unrestricted.get_json()["pagination"]["total"] == 1


def test_hide_restore_and_show_hidden_are_user_specific(app_client, monkeypatch):
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
    personal_tracker = app_client.get("/api/personal-tracker").get_json()

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.get_json()["confirmationRequired"] == "duplicate"
    assert second.status_code == 201
    assert feed["data"][0]["personalExposureType"] == "exact"
    assert feed["data"][0]["personalEntryCount"] == 2
    assert personal_tracker["pagination"]["total"] == 2
    assert personal_tracker["summary"]["total_tracked_bets"] == 2
    assert personal_tracker["data"][0]["selection"] == "Spain"

    other_user = app_client.application.test_client()
    other_user.set_cookie("iconbets_user", "another-user")
    other_feed = other_user.get("/api/trades-to-play?date_range=next7").get_json()
    assert other_feed["data"][0]["personalExposureType"] == "none"
    assert other_user.get("/api/personal-tracker").get_json()["pagination"]["total"] == 0


def test_personal_tracker_filters_books_and_tags_with_separate_stats(
    app_client, monkeypatch
):
    service = app_client.application.extensions["tracker_service"]
    service._cache["trades_to_play"] = [_actionable_trade()]
    monkeypatch.setattr(service, "evaluate_recommendation", _positive_evaluation)
    monkeypatch.setattr(service, "track_recommendations_for_user", lambda *_args: 0)
    app_client.set_cookie("iconbets_user", "metadata-user")
    base = {
        "trade_id": "market-1::outcome-a",
        "entry_price": 0.4,
        "shares": 100,
        "fees": 1,
    }

    first = app_client.post(
        "/api/personal-bets",
        json={**base, "sportsbook": "DraftKings", "tags": ["Tennis", "Value"]},
    )
    second = app_client.post(
        "/api/personal-bets",
        json={
            **base,
            "sportsbook": "FanDuel",
            "tags": ["Tennis", "Live"],
            "confirm_duplicate": True,
        },
    )
    assert first.status_code == 201
    assert second.status_code == 201
    service.database.update_personal_bet_status(
        first.get_json()["data"]["fill_id"], "won", "Won", "2026-07-14T20:00:00+00:00"
    )
    service.database.update_personal_bet_status(
        second.get_json()["data"]["fill_id"], "lost", "Lost", "2026-07-14T21:00:00+00:00"
    )

    combined = app_client.get("/api/personal-tracker").get_json()
    draftkings = app_client.get(
        "/api/personal-tracker?sportsbook=DraftKings"
    ).get_json()
    live_tag = app_client.get("/api/personal-tracker?tag=Live").get_json()
    options = app_client.get("/api/personal-tracker/options").get_json()["data"]

    assert combined["summary"]["total_tracked_bets"] == 2
    assert combined["summary"]["wins"] == 1
    assert combined["summary"]["losses"] == 1
    assert draftkings["pagination"]["total"] == 1
    assert draftkings["summary"]["wins"] == 1
    assert draftkings["summary"]["losses"] == 0
    assert draftkings["data"][0]["sportsbook"] == "DraftKings"
    assert live_tag["pagination"]["total"] == 1
    assert live_tag["summary"]["losses"] == 1
    assert live_tag["data"][0]["tags"] == ["Tennis", "Live"]
    assert options["sportsbooks"] == ["DraftKings", "FanDuel"]
    assert options["tags"] == ["Live", "Tennis", "Value"]


def test_personal_tracker_rejects_invalid_tag_metadata(app_client, monkeypatch):
    service = app_client.application.extensions["tracker_service"]
    service._cache["trades_to_play"] = [_actionable_trade()]
    monkeypatch.setattr(service, "evaluate_recommendation", _positive_evaluation)
    monkeypatch.setattr(service, "track_recommendations_for_user", lambda *_args: 0)

    response = app_client.post(
        "/api/personal-bets",
        json={
            "trade_id": "market-1::outcome-a",
            "entry_price": 0.4,
            "shares": 100,
            "tags": [f"tag-{index}" for index in range(9)],
        },
    )

    assert response.status_code == 400
    assert "no more than 8 tags" in response.get_json()["error"]


def test_opposing_personal_fill_requires_explicit_confirmation(app_client, monkeypatch):
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
