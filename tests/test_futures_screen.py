from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from odds_engine_provider import (
    OddsEngineProvider,
    normalize_odds_engine_future_event,
)


ROOT = Path(__file__).resolve().parents[1]


def future_event_payload() -> tuple[dict, dict]:
    schedule = {
        "event_id": "mlb-world-series-2026",
        "event": "2026 World Series Winner",
        "event_start": "2026-11-05T00:00:00Z",
        "league": "mlb",
        "sport": "baseball",
        "is_future": True,
        "future_type": "championship_winner",
        "outrights": [{"market": "World Series Winner"}],
    }
    odds = {
        **schedule,
        "market_categories": [
            {
                "category": "future",
                "offers": [
                    {
                        "market_id": "world-series-winner",
                        "market": "World Series Winner",
                        "books": [
                            {
                                "book": "draftkings",
                                "selections": [
                                    {
                                        "selection_id": "dk-lad",
                                        "entity_name": "Los Angeles Dodgers",
                                        "entity_name_std": "los_angeles_dodgers",
                                        "odds_american": 210,
                                        "limit": 1000,
                                        "bet_link": "https://sportsbook.test/dk-lad",
                                    },
                                    {
                                        "selection_id": "dk-nyy",
                                        "entity_name": "New York Yankees",
                                        "entity_name_std": "new_york_yankees",
                                        "odds_american": 850,
                                    },
                                ],
                            },
                            {
                                "book": "brand_new_book",
                                "selections": [
                                    {
                                        "selection_id": "new-lad",
                                        "entity_name": "Los Angeles Dodgers",
                                        "entity_name_std": "los_angeles_dodgers",
                                        "odds_american": 225,
                                    }
                                ],
                            },
                        ],
                    }
                ],
            }
        ],
    }
    return schedule, odds


def test_future_normalizer_preserves_every_market_and_new_book() -> None:
    schedule, odds = future_event_payload()

    normalized = normalize_odds_engine_future_event(
        odds, schedule_event=schedule
    )

    assert {row["outcome"] for row in normalized["rows"]} == {
        "Los Angeles Dodgers",
        "New York Yankees",
    }
    dodgers = next(
        row for row in normalized["rows"] if row["outcome"] == "Los Angeles Dodgers"
    )
    assert dodgers["market_title"] == "World Series Winner"
    assert dodgers["future_type"] == "championship_winner"
    assert dodgers["canonical_league_id"] == "MLB"
    assert {option["providerKey"] for option in dodgers["executionOptions"]} == {
        "oddsengine__draftkings",
        "oddsengine__brandnewbook",
    }
    assert any(
        provider["key"] == "oddsengine__brandnewbook"
        and provider["name"] == "Brand New Book"
        for provider in normalized["providers"]
    )


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.status_code = 200
        self.headers = {"X-RateLimit-Remaining": "40"}

    def json(self) -> dict:
        return self.payload

    def raise_for_status(self) -> None:
        return None


class FuturesSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.schedule, self.odds = future_event_payload()

    def get(self, url, *, params=None, headers=None, timeout=None):
        path = url.removeprefix("https://api.oddsengine.dev/v1")
        query = dict(params or {})
        self.calls.append((path, query))
        if path == "/leagues":
            return FakeResponse({"data": [{"league": "mlb"}, {"league": "nba"}]})
        if path == "/events":
            if query.get("league") == "mlb":
                return FakeResponse(
                    {
                        "data": [
                            self.schedule,
                            {
                                "event_id": "regular-game",
                                "event": "Cubs vs Cardinals",
                                "league": "mlb",
                                "event_start": "2026-09-01T00:00:00Z",
                            },
                        ]
                    }
                )
            return FakeResponse({"data": []})
        if path == "/odds":
            return FakeResponse({"data": self.odds})
        raise AssertionError(f"unexpected path {path}")


def test_provider_discovers_future_flags_across_all_active_leagues_and_caches() -> None:
    session = FuturesSession()
    provider = OddsEngineProvider("test-key", session=session)

    first = provider.futures_screen_snapshot()
    calls_after_first = len(session.calls)
    second = provider.futures_screen_snapshot()

    assert first == second
    assert len(session.calls) == calls_after_first
    assert first["complete"] is True
    assert first["leagues"] == ["MLB"]
    assert first["markets"] == ["World Series Winner"]
    assert first["futureTypes"] == ["championship_winner"]
    assert first["meta"]["activeLeagueCount"] == 2
    assert first["meta"]["futureEventCount"] == 1
    assert first["meta"]["selectionCount"] == 2
    assert sum(path == "/events" for path, _ in session.calls) == 2
    assert sum(path == "/odds" for path, _ in session.calls) == 1

    provider.futures_screen_snapshot(force=True)
    assert len(session.calls) > calls_after_first


class ManyFuturesSession:
    def get(self, url, *, params=None, headers=None, timeout=None):
        path = url.removeprefix("https://api.oddsengine.dev/v1")
        query = dict(params or {})
        if path == "/leagues":
            response = FakeResponse({"data": [{"league": "mlb"}]})
        elif path == "/events":
            response = FakeResponse(
                {
                    "data": [
                        {
                            "event_id": f"future-{index}",
                            "event": f"Future {index}",
                            "event_start": "2027-01-01T00:00:00Z",
                            "league": "mlb",
                            "sport": "baseball",
                            "is_future": True,
                        }
                        for index in range(105)
                    ]
                }
            )
        elif path == "/odds":
            event_id = query["event_id"]
            response = FakeResponse(
                {
                    "data": {
                        "event_id": event_id,
                        "event": event_id,
                        "league": "mlb",
                        "sport": "baseball",
                        "market_categories": [
                            {
                                "category": "future",
                                "offers": [
                                    {
                                        "market_id": f"{event_id}-winner",
                                        "market": "Winner",
                                        "books": [
                                            {
                                                "book": "draftkings",
                                                "selections": [
                                                    {
                                                        "selection_id": f"{event_id}-selection",
                                                        "entity_name": "Selection",
                                                        "odds_american": 200,
                                                    }
                                                ],
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                }
            )
        else:
            raise AssertionError(f"unexpected path {path}")
        response.headers["X-RateLimit-Remaining"] = "500"
        return response


def test_provider_does_not_arbitrarily_cap_discovered_future_events() -> None:
    provider = OddsEngineProvider("test-key", session=ManyFuturesSession())

    snapshot = provider.futures_screen_snapshot()

    assert snapshot["complete"] is True
    assert snapshot["meta"]["futureEventCount"] == 105
    assert snapshot["meta"]["fetchedEventCount"] == 105
    assert snapshot["meta"]["selectionCount"] == 105


def test_futures_page_uses_canonical_shell_and_dedicated_assets(app_client) -> None:
    response = app_client.get("/futures")

    assert response.status_code == 200
    assert b'data-page="futures" data-design-system="v2"' in response.data
    assert b"futures.css" in response.data
    assert b"futures.js" in response.data
    assert b'id="futures-table-body"' in response.data
    assert b'id="futures-league"' in response.data
    assert b'id="futures-market"' in response.data
    assert b'id="futures-books-popover"' in response.data
    assert b"legacy-design-system.css" not in response.data
    assert b"stage2-art-direction.css" not in response.data


def test_futures_api_is_paused_without_active_flag(app_client) -> None:
    response = app_client.get("/api/futures")

    assert response.status_code == 200
    assert response.get_json()["paused"] is True
    assert response.get_json()["data"] == []


def test_futures_api_returns_dynamic_provider_snapshot(app_client) -> None:
    payload = {
        "configured": True,
        "complete": True,
        "data": [{"id": "future-1", "market_title": "Super Bowl Winner"}],
        "providers": [{"key": "oddsengine__fanduel", "name": "FanDuel"}],
        "leagues": ["NFL"],
        "markets": ["Super Bowl Winner"],
        "futureTypes": ["championship_winner"],
    }
    app_client.application.extensions["odds_engine_provider"] = SimpleNamespace(
        futures_screen_snapshot=lambda: payload
    )

    response = app_client.get("/api/futures?active=1")

    assert response.status_code == 200
    assert response.get_json() == payload
    assert "s-maxage=60" in response.headers["Cache-Control"]


def test_futures_api_manual_refresh_bypasses_provider_cache(app_client) -> None:
    class ForcedProvider:
        forced = False

        def futures_screen_snapshot(self, *, force=False):
            self.forced = force
            return {"data": [], "providers": [], "leagues": [], "markets": []}

    provider = ForcedProvider()
    app_client.application.extensions["odds_engine_provider"] = provider

    response = app_client.get("/api/futures?active=1&_=refresh")

    assert response.status_code == 200
    assert provider.forced is True


def test_futures_client_discovers_filters_and_does_not_hardcode_market_types() -> None:
    script = (ROOT / "static" / "futures.js").read_text(encoding="utf-8")

    assert 'fetch(`/api/futures?active=1' in script
    assert "payload.leagues" in script
    assert "payload.markets" in script
    assert "payload.providers" in script
    assert "World Series Winner" not in script
    assert "Super Bowl Winner" not in script
    assert "NBA Champion" not in script
    assert "WNBA Champion" not in script


def test_futures_styles_keep_dense_sticky_comparison_board() -> None:
    stylesheet = (ROOT / "static" / "futures.css").read_text(encoding="utf-8")

    assert 'body[data-design-system="v2"][data-page="futures"]' in stylesheet
    assert ".futures-selection-head { position: sticky; left: 0" in stylesheet
    assert ".futures-best-head { position: sticky; left: 270px" in stylesheet
    assert ".futures-table-scroll" in stylesheet
    assert "overflow: auto" in stylesheet
    assert "@media (max-width: 760px)" in stylesheet
