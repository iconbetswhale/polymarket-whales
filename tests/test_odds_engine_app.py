from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _provider(application, provider_key: str):
    registry = application.extensions["execution_providers"]
    return next(
        provider for provider in registry.providers if provider.provider_key == provider_key
    )


def test_live_calculator_routes_use_the_configured_all_book_feed(app_client, monkeypatch) -> None:
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


def test_live_scan_uses_only_odds_engine_for_aggregated_odds(
    app_client, monkeypatch
) -> None:
    application = app_client.application
    odds_engine = _provider(application, "odds_engine")
    sports_game_odds = _provider(application, "novig")
    the_odds_api = _provider(application, "the_odds_api")
    odds_engine.api_key = "configured-in-test"
    sports_game_odds.api_key = "must-not-be-used"
    the_odds_api.api_key = "must-not-be-used"
    odds_engine_calls = []

    def odds_engine_events(*, sport_keys, market_keys):
        odds_engine_calls.append((tuple(sport_keys), tuple(market_keys)))
        return []

    def unapproved_events(**_kwargs):
        raise AssertionError("unapproved aggregated odds provider was called")

    monkeypatch.setattr(odds_engine, "ev_events", odds_engine_events)
    monkeypatch.setattr(sports_game_odds, "ev_events", unapproved_events)
    monkeypatch.setattr(the_odds_api, "ev_events", unapproved_events)

    response = app_client.get("/api/arbitrage?active=1")

    assert response.status_code == 200
    assert response.get_json()["dataSource"] == "odds_engine"
    assert len(odds_engine_calls) == 1


def test_odds_engine_health_is_protected(app_client) -> None:
    response = app_client.get("/api/provider-health/odds-engine")

    assert response.status_code == 401
    assert response.get_json() == {"status": "UNAUTHORIZED"}


def test_odds_screen_uses_all_book_events_without_a_second_event_scan(app_client, monkeypatch) -> None:
    application = app_client.application
    odds_engine = _provider(application, "odds_engine")
    odds_engine.api_key = "configured-in-test"
    calls = []
    monkeypatch.setattr(
        application.extensions["polymarket_schedule_feed"],
        "today_and_tomorrow",
        lambda _now: [],
    )
    starts_at = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
    observed_at = datetime.now(timezone.utc).isoformat()

    def events(*, sport_keys, market_keys):
        calls.append({"sport_keys": tuple(sport_keys), "market_keys": tuple(market_keys)})
        return [
            {
                "id": "mlb-screen",
                "sport_key": "baseball_mlb",
                "sport_title": "MLB",
                "commence_time": starts_at,
                "home_team": "Boston Red Sox",
                "away_team": "New York Yankees",
                "bookmakers": [
                    {
                        "key": "fanduel",
                        "title": "FanDuel",
                        "markets": [
                            {
                                "key": "h2h",
                                "last_update": observed_at,
                                "outcomes": [
                                    {"name": "Boston Red Sox", "price": 105},
                                    {"name": "New York Yankees", "price": -110},
                                ],
                            }
                        ],
                    }
                ],
            }
        ]

    monkeypatch.setattr(odds_engine, "ev_events", events)

    response = app_client.get(
        "/api/odds-screen?active=1&league=MLB&market=moneyline"
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["source"].endswith(
        "odds_engine_read_only_feeds"
    )
    assert "s-maxage=60" in response.headers["Cache-Control"]
    assert not response.headers.getlist("Set-Cookie")
    assert payload["refreshSeconds"] == 60
    assert payload["transport"] == {
        "mode": "rest_snapshot",
        "provider": "odds_engine",
        "websocketConnected": False,
        "websocketRequiresAdvanced": True,
    }
    assert len(calls) == 1
    assert calls[0] == {
        "sport_keys": ("baseball_mlb",),
        "market_keys": ("h2h",),
    }
    assert {
        option["providerName"]
        for row in payload["data"]
        for option in row["executionOptions"]
    } == {"FanDuel"}


def test_odds_screen_league_and_prop_filters_keep_direct_all_book_rows(
    app_client, monkeypatch
) -> None:
    application = app_client.application
    odds_engine = _provider(application, "odds_engine")
    odds_engine.api_key = "configured-in-test"
    starts_at = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
    observed_at = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(
        application.extensions["polymarket_schedule_feed"],
        "today_and_tomorrow",
        lambda _now: [],
    )
    monkeypatch.setattr(
        odds_engine,
        "ev_events",
        lambda **_kwargs: [
            {
                "id": "mlb-prop-screen",
                "sport_key": "baseball_mlb",
                "sport_title": "MLB",
                "commence_time": starts_at,
                "home_team": "Boston Red Sox",
                "away_team": "New York Yankees",
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "title": "DraftKings",
                        "markets": [
                            {
                                "key": "batter_hits",
                                "last_update": observed_at,
                                "outcomes": [
                                    {
                                        "name": "Over",
                                        "description": "Aaron Judge",
                                        "point": 1.5,
                                        "price": 115,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    )

    response = app_client.get(
        "/api/odds-screen?active=1&league=MLB&market=batter_hits"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload["data"]) == 1
    assert payload["data"][0]["player_name"] == "Aaron Judge"
    assert payload["data"][0]["odds_market_key"] == "batter_hits"


def test_fast_odds_screen_scan_bounds_the_first_pass(app_client, monkeypatch) -> None:
    application = app_client.application
    odds_engine = _provider(application, "odds_engine")
    odds_engine.api_key = "configured-in-test"
    calls = []

    def events(**kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(odds_engine, "ev_events", events)

    response = app_client.get("/api/odds-screen?active=1&fast=1")

    assert response.status_code == 200
    assert response.get_json()["partial"] is True
    assert calls[0]["max_events_per_league"] == 1
    assert calls[0]["max_total_events"] == 6


def test_fast_positive_ev_scan_bounds_the_first_pass(app_client, monkeypatch) -> None:
    application = app_client.application
    object.__setattr__(application.config["SETTINGS"], "positive_ev_enabled", True)
    odds_engine = _provider(application, "odds_engine")
    odds_engine.api_key = "configured-in-test"
    calls = []

    def events(**kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(odds_engine, "ev_events", events)
    monkeypatch.setattr(
        odds_engine,
        "diagnostics",
        lambda authenticate=False: {"provider": "odds_engine", "quota": {}},
    )

    response = app_client.get("/api/positive-ev/live?fast=1")

    assert response.status_code == 200
    assert response.get_json()["partial"] is True
    assert calls[0]["max_events_per_league"] == 1
    assert calls[0]["max_total_events"] == 8
