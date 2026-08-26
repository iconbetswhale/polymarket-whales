from __future__ import annotations

import requests


def _provider(application, provider_key: str):
    registry = application.extensions["execution_providers"]
    return next(
        provider for provider in registry.providers if provider.provider_key == provider_key
    )


def test_live_calculator_routes_prefer_odds_engine(app_client, monkeypatch) -> None:
    application = app_client.application
    odds_engine = _provider(application, "odds_engine")
    odds_engine.api_key = "configured-in-test"
    calls = []

    def empty_events(*, sport_keys, market_keys):
        calls.append((tuple(sport_keys), tuple(market_keys)))
        return []

    monkeypatch.setattr(odds_engine, "ev_events", empty_events)

    for endpoint in (
        "/api/arbitrage?active=1",
        "/api/middles?active=1",
        "/api/low-hold?active=1",
    ):
        response = app_client.get(endpoint)
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["configured"] is True
        assert payload["dataSource"] == "odds_engine"

    object.__setattr__(application.config["SETTINGS"], "positive_ev_enabled", True)
    response = app_client.get("/api/positive-ev")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["configured"] is True
    assert payload["dataSource"] == "odds_engine"
    assert len(calls) == 4


def test_live_scan_falls_back_after_odds_engine_error(app_client, monkeypatch) -> None:
    application = app_client.application
    odds_engine = _provider(application, "odds_engine")
    sports_game_odds = _provider(application, "novig")
    odds_engine.api_key = "configured-in-test"
    sports_game_odds.api_key = "fallback-in-test"
    fallback_calls = []

    def odds_engine_failure(*, sport_keys, market_keys):
        raise requests.ConnectionError("synthetic outage")

    def fallback_events(*, sport_keys, market_keys):
        fallback_calls.append((tuple(sport_keys), tuple(market_keys)))
        return []

    monkeypatch.setattr(odds_engine, "ev_events", odds_engine_failure)
    monkeypatch.setattr(sports_game_odds, "ev_events", fallback_events)

    response = app_client.get("/api/arbitrage?active=1")

    assert response.status_code == 200
    assert response.get_json()["dataSource"] == "sports_game_odds"
    assert len(fallback_calls) == 1


def test_odds_engine_health_is_protected(app_client) -> None:
    response = app_client.get("/api/provider-health/odds-engine")

    assert response.status_code == 401
    assert response.get_json() == {"status": "UNAUTHORIZED"}


def test_odds_screen_prefers_odds_engine(app_client, monkeypatch) -> None:
    application = app_client.application
    odds_engine = _provider(application, "odds_engine")
    odds_engine.api_key = "configured-in-test"
    calls = []
    monkeypatch.setattr(
        application.extensions["polymarket_schedule_feed"],
        "today_and_tomorrow",
        lambda _now: [],
    )
    monkeypatch.setattr(
        odds_engine,
        "odds_screen_rows",
        lambda **kwargs: calls.append(kwargs) or [],
    )
    monkeypatch.setattr(
        odds_engine, "screen_options_for_trades", lambda _trades: {}
    )
    monkeypatch.setattr(odds_engine, "provider_catalog", lambda _trades: [])

    response = app_client.get(
        "/api/odds-screen?active=1&league=MLB&market=moneyline"
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["source"].endswith(
        "odds_engine_read_only_feeds"
    )
    assert "s-maxage=15" in response.headers["Cache-Control"]
    assert not response.headers.getlist("Set-Cookie")
    assert payload["refreshSeconds"] == 15
    assert payload["transport"] == {
        "mode": "rest_snapshot",
        "provider": "odds_engine",
        "websocketConnected": False,
        "websocketRequiresAdvanced": True,
    }
    assert len(calls) == 1
