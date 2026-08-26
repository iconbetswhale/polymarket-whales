from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

from arbitrage import build_arbitrage_board
from config import get_settings
from ev_optimizer import build_ev_board
from execution_providers import ProviderHealthStatus
from low_hold import build_low_hold_board
from middles import build_middles_board
from odds_engine_provider import OddsEngineProvider


class FakeResponse:
    def __init__(self, payload, *, status_code: int = 200, headers: dict | None = None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


class FakeSession:
    def __init__(self, routes: dict[str, FakeResponse]):
        self.routes = routes
        self.calls: list[dict] = []

    def get(self, url, *, params=None, headers=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "params": dict(params or {}),
                "headers": dict(headers or {}),
                "timeout": timeout,
            }
        )
        path = url.removeprefix("https://api.oddsengine.dev/v1")
        return self.routes[path]


def _fixture_session() -> FakeSession:
    event_start = (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat()
    observed_at = datetime.now(timezone.utc).isoformat()
    event = {
        "event_id": "mlb-bos-nyy",
        "event_start": event_start,
        "home_team": "Boston Red Sox",
        "away_team": "New York Yankees",
        "league": "MLB",
        "sport": "Baseball",
    }

    def selection(
        selection_id: str,
        entity_name: str,
        side: str,
        odds: int,
        *,
        line: float | None = None,
        is_alt: bool = False,
    ) -> dict:
        return {
            "selection_id": selection_id,
            "entity_name": entity_name,
            "side": side,
            "odds_american": odds,
            "odds_decimal": 2.05,
            "line": line,
            "is_alt": is_alt,
            "odds_changed_at": observed_at,
            "bet_link": f"https://book.test/betslip/{selection_id}",
            "liquidity": 2500,
            "limit": 500,
        }

    odds = {
        **event,
        "market_categories": [
            {
                "offers": [
                    {
                        "market_id": "moneyline",
                        "market_key": "moneyline",
                        "market": "Moneyline",
                        "books": [
                            {
                                "book": "FanDuel",
                                "selections": [
                                    selection(
                                        "fd-bos", "Boston Red Sox", "home", 105
                                    ),
                                    selection(
                                        "fd-nyy", "New York Yankees", "away", -110
                                    ),
                                ],
                            },
                            {
                                "book": "Pinnacle",
                                "selections": [
                                    selection(
                                        "pin-bos", "Boston Red Sox", "home", 102
                                    ),
                                    selection(
                                        "pin-nyy", "New York Yankees", "away", -108
                                    ),
                                ],
                            },
                        ],
                    },
                    {
                        "market_id": "spread-main",
                        "market_key": "point_spread",
                        "market": "Point Spread",
                        "books": [
                            {
                                "book": "DraftKings",
                                "selections": [
                                    selection(
                                        "dk-bos-spread",
                                        "Boston Red Sox",
                                        "home",
                                        -105,
                                        line=-1.5,
                                    ),
                                    selection(
                                        "dk-nyy-spread",
                                        "New York Yankees",
                                        "away",
                                        -105,
                                        line=1.5,
                                    ),
                                ],
                            }
                        ],
                    },
                    {
                        "market_id": "spread-alt",
                        "market_key": "point_spread",
                        "market": "Point Spread",
                        "books": [
                            {
                                "book": "Hard Rock",
                                "selections": [
                                    selection(
                                        "hr-bos-alt",
                                        "Boston Red Sox",
                                        "home",
                                        115,
                                        line=-2.5,
                                        is_alt=True,
                                    ),
                                    selection(
                                        "hr-nyy-alt",
                                        "New York Yankees",
                                        "away",
                                        -135,
                                        line=2.5,
                                        is_alt=True,
                                    ),
                                ],
                            }
                        ],
                    },
                    {
                        "market_id": "total-main",
                        "market_key": "game_total",
                        "market": "Game Total",
                        "books": [
                            {
                                "book": "Pinnacle",
                                "selections": [
                                    selection(
                                        "pin-over", "", "over", -104, line=8.5
                                    ),
                                    selection(
                                        "pin-under", "", "under", -106, line=8.5
                                    ),
                                ],
                            }
                        ],
                    },
                    {
                        "entity_name": "Aaron Judge",
                        "market_id": "player-points",
                        "market_key": "player_points",
                        "market": "Player Points",
                        "books": [
                            {
                                "book": "Bet365",
                                "selections": [
                                    selection(
                                        "b365-over",
                                        "Aaron Judge",
                                        "over",
                                        -115,
                                        line=1.5,
                                    ),
                                    selection(
                                        "b365-under",
                                        "Aaron Judge",
                                        "under",
                                        -105,
                                        line=1.5,
                                    ),
                                ],
                            }
                        ],
                    },
                ]
            }
        ],
    }
    rate_headers = {
        "X-RateLimit-Limit": "60",
        "X-RateLimit-Remaining": "58",
        "X-RateLimit-Reset": "42",
    }
    return FakeSession(
        {
            "/events": FakeResponse({"data": [event]}, headers=rate_headers),
            "/odds": FakeResponse({"data": odds}, headers=rate_headers),
            "/leagues": FakeResponse({"data": [{"league": "mlb"}]}),
        }
    )


def test_provider_normalizes_documented_event_odds_and_caches_requests() -> None:
    session = _fixture_session()
    provider = OddsEngineProvider("server-side-test-key", session=session)
    markets = (
        "h2h",
        "spreads",
        "alternate_spreads",
        "totals",
        "player_points",
    )

    first = provider.ev_events(sport_keys=("baseball_mlb",), market_keys=markets)
    second = provider.ev_events(sport_keys=("baseball_mlb",), market_keys=markets)

    assert first == second
    assert len(session.calls) == 2
    assert session.calls[0]["url"].endswith("/v1/events")
    assert session.calls[0]["params"] == {"league": "mlb"}
    assert session.calls[1]["url"].endswith("/v1/odds")
    assert session.calls[1]["params"] == {"event_id": "mlb-bos-nyy"}
    assert all(
        call["headers"] == {"X-API-Key": "server-side-test-key"}
        for call in session.calls
    )

    event = first[0]
    assert event["sport_key"] == "baseball_mlb"
    assert event["home_team"] == "Boston Red Sox"
    books = {book["key"]: book for book in event["bookmakers"]}
    assert set(books) == {
        "bet365",
        "draftkings",
        "fanduel",
        "hardrockbet",
        "pinnacle",
    }
    assert {market["key"] for market in books["hardrockbet"]["markets"]} == {
        "alternate_spreads"
    }
    moneyline = books["fanduel"]["markets"][0]
    assert {outcome["name"] for outcome in moneyline["outcomes"]} == {
        "Boston Red Sox",
        "New York Yankees",
    }
    player_points = books["bet365"]["markets"][0]
    assert {outcome["description"] for outcome in player_points["outcomes"]} == {
        "Aaron Judge"
    }
    assert all(outcome["link"].startswith("https://book.test/") for outcome in moneyline["outcomes"])


def test_provider_filter_missing_key_and_safe_diagnostics() -> None:
    session = _fixture_session()
    provider = OddsEngineProvider("do-not-expose-this", session=session)

    events = provider.ev_events(
        sport_keys=("baseball_mlb",), market_keys=("totals",)
    )
    diagnostics = provider.diagnostics(authenticate=False)

    assert {
        market["key"]
        for book in events[0]["bookmakers"]
        for market in book["markets"]
    } == {"totals"}
    assert diagnostics["provider"] == "odds_engine"
    assert diagnostics["quota"]["remaining"] == "58"
    assert diagnostics["credentials_exposed"] is False
    assert "do-not-expose-this" not in repr(diagnostics)
    assert OddsEngineProvider(None, session=session).ev_events(
        sport_keys=("baseball_mlb",), market_keys=("h2h",)
    ) == []
    assert len(session.calls) == 2


def test_provider_health_authenticates_without_exposing_credentials() -> None:
    session = _fixture_session()
    provider = OddsEngineProvider("health-key", session=session)

    assert provider.health_status(authenticate=False) is ProviderHealthStatus.CONFIGURED
    assert provider.health_status(authenticate=True) is ProviderHealthStatus.AUTHENTICATED
    assert session.calls[-1]["url"].endswith("/v1/leagues")

    unauthorized = FakeSession(
        {"/leagues": FakeResponse({}, status_code=401)}
    )
    assert OddsEngineProvider(
        "bad-key", session=unauthorized
    ).health_status(authenticate=True) is ProviderHealthStatus.UNAUTHORIZED


def test_normalized_feed_is_accepted_by_all_four_existing_calculators() -> None:
    provider = OddsEngineProvider("key", session=_fixture_session())
    events = provider.ev_events(
        sport_keys=("baseball_mlb",),
        market_keys=(
            "h2h",
            "spreads",
            "alternate_spreads",
            "totals",
            "player_points",
        ),
    )
    books = tuple(
        sorted({book["key"] for event in events for book in event["bookmakers"]})
    )

    assert "data" in build_arbitrage_board(
        events,
        selected_books=books,
        allowed_markets=("h2h", "spreads", "totals"),
    )
    assert "data" in build_middles_board(
        events,
        selected_books=books,
        allowed_markets=("spreads", "alternate_spreads", "totals"),
    )
    assert "data" in build_low_hold_board(
        events,
        selected_books=books,
        allowed_markets=("h2h", "spreads", "totals"),
    )
    assert "data" in build_ev_board(
        events,
        execution_books=books,
        min_source_books=1,
    )


def test_provider_supplies_exact_line_shopping_and_odds_screen_rows() -> None:
    provider = OddsEngineProvider("key", session=_fixture_session())
    events = provider.ev_events(
        sport_keys=("baseball_mlb",), market_keys=("h2h",)
    )
    start = events[0]["commence_time"]
    trade = {
        "id": "model-trade-1",
        "category": "Baseball",
        "canonical_sport_id": "BASEBALL",
        "league": "MLB",
        "canonical_league_id": "MLB",
        "event_title": "New York Yankees vs Boston Red Sox",
        "market_title": "Moneyline",
        "sports_market_type": "Moneyline",
        "outcome": "Boston Red Sox",
        "event_date_et": start,
        "resolution_time": start,
        "card": {"recommended_amount": 100},
        "recommendation": {"recommended_amount": 100},
    }

    options = provider.options_for_trades([trade])["model-trade-1"]
    screen_rows = provider.odds_screen_rows(
        league="MLB", market_kind="moneyline"
    )

    assert {option.provider_key for option in options} == {
        "oddsengine__fanduel",
        "oddsengine__pinnacle",
    }
    fanduel = next(
        option for option in options if option.provider_key == "oddsengine__fanduel"
    )
    assert fanduel.american_odds == 105
    assert fanduel.deep_link.endswith("/fd-bos")
    fair_quotes = provider.fair_price_quotes([trade])
    assert fair_quotes["model-trade-1"][0]["provider"] == "pinnacle"
    assert {
        row["outcome"] for row in screen_rows
    } == {"Boston Red Sox", "New York Yankees"}
    assert all(row["odds_engine_event"] for row in screen_rows)
    assert any(
        item["key"] == "oddsengine__fanduel"
        and item["source"] == "odds_engine"
        for item in provider.provider_catalog([])
    )


def test_settings_read_oddsengine_values_without_repr_leak(monkeypatch) -> None:
    monkeypatch.setenv("ODDSENGINE_API_KEY", "settings-secret")
    monkeypatch.setenv("ODDSENGINE_API_BASE_URL", "https://odds.example.test/v1")
    monkeypatch.setenv("ODDSENGINE_CACHE_TTL_SECONDS", "75")
    monkeypatch.setenv("ODDSENGINE_MAX_EVENTS_PER_LEAGUE", "9")
    monkeypatch.setenv("ODDSENGINE_MAX_TOTAL_EVENTS", "31")

    settings = get_settings()

    assert settings.oddsengine_api_key == "settings-secret"
    assert settings.oddsengine_api_base_url == "https://odds.example.test/v1"
    assert settings.oddsengine_cache_ttl_seconds == 75
    assert settings.oddsengine_max_events_per_league == 9
    assert settings.oddsengine_max_total_events == 31
    assert "settings-secret" not in repr(settings)
