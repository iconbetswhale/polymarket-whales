from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest
import requests

from arbitrage import build_arbitrage_board
from config import get_settings
from ev_optimizer import build_ev_board
from execution_providers import ProviderHealthStatus
from low_hold import build_low_hold_board
from middles import build_middles_board
from odds_engine_provider import (
    OddsEngineProvider,
    normalize_odds_engine_event,
    oddsengine_filter_catalog_payload,
    oddsengine_provider_catalog,
)


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
        response = self.routes[path]
        if isinstance(response, list):
            return response.pop(0)
        return response


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


@pytest.mark.parametrize(
    ("raw_book", "expected_key"),
    (
        ("prizepicks", "prizepicks"),
        ("underdog", "underdog"),
        ("dkpick6", "pick6"),
        ("betr", "betr_picks"),
        ("dabble", "dabble"),
        ("betrsportsbook", "betrsportsbook"),
    ),
)
def test_provider_keeps_official_dfs_book_ids_separate_from_sportsbooks(
    raw_book: str,
    expected_key: str,
) -> None:
    observed_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "event_id": "mlb-dfs-books",
        "event_start": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
        "home_team": "Boston Red Sox",
        "away_team": "New York Yankees",
        "league": "MLB",
        "market_categories": [
            {
                "category": "player",
                "offers": [
                    {
                        "market_key": "batter_hits",
                        "market": "Batter Hits",
                        "entity_name": "Aaron Judge",
                        "books": [
                            {
                                "book": raw_book,
                                "selections": [
                                    {
                                        "selection_id": f"{raw_book}-over",
                                        "entity_name": "Aaron Judge",
                                        "side": "over",
                                        "line": 1.5,
                                        "odds_american": (
                                            -110
                                            if expected_key == "betrsportsbook"
                                            else None
                                        ),
                                        "last_fetched": observed_at,
                                        "is_alt": False,
                                    },
                                    {
                                        "selection_id": f"{raw_book}-under",
                                        "entity_name": "Aaron Judge",
                                        "side": "under",
                                        "line": 1.5,
                                        "odds_american": (
                                            -110
                                            if expected_key == "betrsportsbook"
                                            else None
                                        ),
                                        "last_fetched": observed_at,
                                        "is_alt": False,
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }

    normalized = normalize_odds_engine_event(
        payload,
        sport_key="baseball_mlb",
        requested_markets=("batter_hits",),
    )

    assert normalized is not None
    assert [book["key"] for book in normalized["bookmakers"]] == [expected_key]
    outcomes = normalized["bookmakers"][0]["markets"][0]["outcomes"]
    assert {outcome["name"] for outcome in outcomes} == {"Over", "Under"}
    assert all(outcome["is_alt"] is False for outcome in outcomes)


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


def test_provider_returns_partial_snapshot_when_rate_limit_is_reached() -> None:
    fixture = _fixture_session()
    first_event = fixture.routes["/events"]._payload["data"][0]
    second_event = {
        **first_event,
        "event_id": "mlb-lad-sd",
        "event_start": (
            datetime.now(timezone.utc) + timedelta(hours=10)
        ).isoformat(),
    }
    first_odds = fixture.routes["/odds"]._payload
    session = FakeSession(
        {
            "/events": FakeResponse(
                {"data": [first_event, second_event]},
                headers={
                    "X-RateLimit-Limit": "60",
                    "X-RateLimit-Remaining": "2",
                    "X-RateLimit-Reset": "30",
                },
            ),
            "/odds": [
                FakeResponse(
                    first_odds,
                    headers={
                        "X-RateLimit-Limit": "60",
                        "X-RateLimit-Remaining": "1",
                        "X-RateLimit-Reset": "30",
                    },
                ),
                FakeResponse(
                    {"error": "rate limit exceeded"},
                    status_code=429,
                    headers={
                        "X-RateLimit-Limit": "60",
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": "30",
                    },
                ),
            ],
        }
    )
    provider = OddsEngineProvider("key", session=session)

    events = provider.ev_events(
        sport_keys=("baseball_mlb",), market_keys=("h2h",)
    )

    assert len(events) == 1
    assert len(session.calls) == 3
    assert provider.diagnostics()["quota"] == {
        "limit": "60",
        "remaining": "0",
        "reset": "30",
    }


def test_provider_fetches_independent_event_odds_concurrently(monkeypatch) -> None:
    fixture = _fixture_session()
    source_event = fixture.routes["/events"]._payload["data"][0]
    source_odds = fixture.routes["/odds"]._payload["data"]
    events = [
        {
            **source_event,
            "event_id": f"event-{index}",
            "event_start": (
                datetime.now(timezone.utc) + timedelta(hours=8 + index)
            ).isoformat(),
        }
        for index in range(2)
    ]
    barrier = threading.Barrier(2)
    active = 0
    maximum_active = 0
    active_lock = threading.Lock()

    provider = OddsEngineProvider(
        "key",
        session=fixture,
        max_parallel_requests=2,
    )
    monkeypatch.setattr(provider, "_league_events", lambda _league: events)

    def event_odds(event_id: str) -> dict:
        nonlocal active, maximum_active
        with active_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        barrier.wait(timeout=1)
        with active_lock:
            active -= 1
        return {**source_odds, "event_id": event_id}

    monkeypatch.setattr(provider, "_event_odds", event_odds)

    rows = provider.ev_events(
        sport_keys=("baseball_mlb",),
        market_keys=("h2h",),
    )

    assert [row["id"] for row in rows] == ["event-0", "event-1"]
    assert maximum_active == 2


def test_provider_fetches_independent_league_schedules_concurrently(monkeypatch) -> None:
    fixture = _fixture_session()
    source_event = fixture.routes["/events"]._payload["data"][0]
    source_odds = fixture.routes["/odds"]._payload["data"]
    barrier = threading.Barrier(2)
    active = 0
    maximum_active = 0
    active_lock = threading.Lock()

    provider = OddsEngineProvider(
        "key",
        session=fixture,
        max_parallel_requests=2,
    )

    def league_events(league: str) -> list[dict]:
        nonlocal active, maximum_active
        with active_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        barrier.wait(timeout=1)
        with active_lock:
            active -= 1
        return [
            {
                **source_event,
                "event_id": f"{league}-event",
                "league": league.upper(),
            }
        ]

    monkeypatch.setattr(provider, "_league_events", league_events)
    monkeypatch.setattr(
        provider,
        "_event_odds",
        lambda event_id: {**source_odds, "event_id": event_id},
    )

    rows = provider.ev_events(
        sport_keys=("baseball_mlb", "basketball_wnba"),
        market_keys=("h2h",),
    )

    assert {row["id"] for row in rows} == {"mlb-event", "wnba-event"}
    assert maximum_active == 2


def test_odds_screen_loads_full_slate_and_reuses_it_for_exact_options(
    monkeypatch,
) -> None:
    fixture = _fixture_session()
    source_event = fixture.routes["/events"]._payload["data"][0]
    source_odds = fixture.routes["/odds"]._payload["data"]
    events = [
        {
            **source_event,
            "event_id": f"full-slate-{index}",
            "event_start": (
                datetime.now(timezone.utc) + timedelta(hours=4 + index)
            ).isoformat(),
        }
        for index in range(3)
    ]
    starts_by_id = {event["event_id"]: event["event_start"] for event in events}
    provider = OddsEngineProvider(
        "key",
        session=fixture,
        max_events_per_league=1,
        max_total_events=1,
    )
    monkeypatch.setattr(provider, "_league_events", lambda _league: events)
    monkeypatch.setattr(
        provider,
        "_event_odds",
        lambda event_id: {
            **source_odds,
            "event_id": event_id,
            "event_start": starts_by_id[event_id],
        },
    )

    rows = provider.odds_screen_rows(league="MLB", market_kind="moneyline")
    options = provider.screen_options_for_trades(rows)

    assert {row["event_id"] for row in rows} == {
        "full-slate-0",
        "full-slate-1",
        "full-slate-2",
    }
    assert all(options.get(row["id"]) for row in rows)


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


def test_provider_reads_and_caches_advanced_prophetx_orderbook() -> None:
    payload = {
        "meta": {"format": "whale", "returned": 1},
        "opportunities": [{"best_book": "prophetx", "best_odds": 105}],
    }
    session = FakeSession(
        {
            "/orderbook/top": FakeResponse(
                payload,
                headers={"X-RateLimit-Remaining": "59"},
            )
        }
    )
    provider = OddsEngineProvider("advanced-key", session=session)

    first = provider.sharp_money_snapshot(limit=40)
    second = provider.sharp_money_snapshot(limit=40)

    assert first == second == payload
    assert len(session.calls) == 1
    assert session.calls[0]["url"].endswith("/v1/orderbook/top")
    assert session.calls[0]["params"] == {
        "sort": "whale",
        "limit": 40,
    }
    assert provider.diagnostics()["supportsOrderBook"] is True


def test_provider_builds_standard_sharp_money_quote_snapshot() -> None:
    session = _fixture_session()
    provider = OddsEngineProvider("standard-key", session=session)

    snapshot = provider.sharp_money_quote_snapshot(limit=40)

    assert snapshot["transport"] == "rest_snapshot"
    assert snapshot["limit"] == 40
    assert snapshot["events"]
    assert all(event["bookmakers"] for event in snapshot["events"])


def test_provider_records_advanced_entitlement_rejection() -> None:
    session = FakeSession(
        {"/orderbook/top": FakeResponse({"error": "plan required"}, status_code=403)}
    )
    provider = OddsEngineProvider("standard-key", session=session)

    with pytest.raises(requests.HTTPError):
        provider.sharp_money_snapshot()

    diagnostics = provider.diagnostics()
    assert diagnostics["advancedAccess"] is False
    assert diagnostics["supportsOrderBook"] is False
    assert diagnostics["supportsWebSocket"] is False


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


def test_oddsengine_catalog_helpers_expose_all_subscribed_books() -> None:
    filter_catalog = oddsengine_filter_catalog_payload()
    provider_catalog = oddsengine_provider_catalog()

    assert filter_catalog["catalogVersion"] == 4
    assert filter_catalog["catalogSource"] == "odds_engine"
    assert filter_catalog["bookCount"] == 88
    assert len(filter_catalog["books"]) == 88
    assert {"pick6", "betr_picks", "dabble"} <= {
        item["key"] for item in filter_catalog["books"]
    }
    assert len(provider_catalog) == 88
    assert all(item["key"].startswith("oddsengine__") for item in provider_catalog)


def test_settings_read_oddsengine_values_without_repr_leak(monkeypatch) -> None:
    monkeypatch.setenv("ODDSENGINE_API_KEY", "settings-secret")
    monkeypatch.setenv("ODDSENGINE_API_BASE_URL", "https://odds.example.test/v1")
    monkeypatch.setenv("ODDSENGINE_CACHE_TTL_SECONDS", "75")
    monkeypatch.setenv("ODDSENGINE_MAX_EVENTS_PER_LEAGUE", "9")
    monkeypatch.setenv("ODDSENGINE_MAX_TOTAL_EVENTS", "31")
    monkeypatch.setenv("SHARP_MONEY_ADVANCED_ORDERBOOK_ENABLED", "true")

    settings = get_settings()

    assert settings.oddsengine_api_key == "settings-secret"
    assert settings.oddsengine_api_base_url == "https://odds.example.test/v1"
    assert settings.oddsengine_cache_ttl_seconds == 75
    assert settings.oddsengine_max_events_per_league == 9
    assert settings.oddsengine_max_total_events == 31
    assert settings.sharp_money_advanced_orderbook_enabled is True
    assert "settings-secret" not in repr(settings)
