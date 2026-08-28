from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import requests

from execution_providers import (
    ExecutionOption,
    ExecutionProviderRegistry,
    MatchConfidence,
    canonicalize_trade,
)
from the_odds_api_provider import DEFAULT_REGIONS, TheOddsAPIProvider


class FakeResponse:
    def __init__(
        self,
        payload,
        *,
        status_code: int = 200,
        headers: dict | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


class FakeSession:
    def __init__(self, payload, *, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.calls: list[dict] = []

    def get(self, url, *, params=None, timeout=None):
        self.calls.append(
            {"url": url, "params": dict(params or {}), "timeout": timeout}
        )
        return FakeResponse(
            self.payload,
            status_code=self.status_code,
            headers={
                "x-requests-remaining": "99991",
                "x-requests-used": "9",
                "x-requests-last": "3",
            },
        )


def test_scores_uses_recent_completed_event_endpoint() -> None:
    session = FakeSession(
        [
            {
                "id": "mlb-event-1",
                "completed": True,
                "scores": [
                    {"name": "Boston Red Sox", "score": "4"},
                    {"name": "New York Yankees", "score": "5"},
                ],
            }
        ]
    )
    provider = TheOddsAPIProvider("secret", session=session)

    rows = provider.scores(sport_keys=("baseball_mlb",), days_from=9)

    assert rows[0]["completed"] is True
    assert session.calls[0]["url"].endswith("/sports/baseball_mlb/scores/")
    assert session.calls[0]["params"]["daysFrom"] == 3


def _event(start: datetime) -> dict:
    updated = datetime.now(timezone.utc).isoformat()
    return {
        "id": "mlb-event-1",
        "sport_key": "baseball_mlb",
        "sport_title": "MLB",
        "commence_time": start.isoformat(),
        "home_team": "Boston Red Sox",
        "away_team": "New York Yankees",
        "bookmakers": [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "last_update": updated,
                "link": "https://sportsbook.draftkings.com/event/mlb-event-1",
                "markets": [
                    {
                        "key": "h2h",
                        "last_update": updated,
                        "outcomes": [
                            {
                                "name": "Boston Red Sox",
                                "price": -105,
                                "sid": "dk-red-sox",
                                "link": "https://sportsbook.draftkings.com/betslip/dk-red-sox",
                                "bet_limit": 500,
                            },
                            {
                                "name": "New York Yankees",
                                "price": -115,
                                "sid": "dk-yankees",
                                "link": "https://sportsbook.draftkings.com/betslip/dk-yankees",
                            },
                        ],
                    }
                ],
            },
            {
                "key": "fanduel",
                "title": "FanDuel",
                "last_update": updated,
                "link": "https://sportsbook.fanduel.com/event/mlb-event-1",
                "markets": [
                    {
                        "key": "h2h",
                        "last_update": updated,
                        "outcomes": [
                            {
                                "name": "Boston Red Sox",
                                "price": 110,
                                "sid": "fd-red-sox",
                                "link": "https://sportsbook.fanduel.com/betslip/fd-red-sox",
                            },
                            {
                                "name": "New York Yankees",
                                "price": -120,
                                "sid": "fd-yankees",
                                "link": "https://sportsbook.fanduel.com/betslip/fd-yankees",
                            },
                        ],
                    }
                ],
            },
        ],
    }


def _alternate_event(
    start: datetime, *, sport_key: str = "basketball_wnba"
) -> dict:
    updated = datetime.now(timezone.utc).isoformat()
    return {
        "id": "alternate-event-1",
        "sport_key": sport_key,
        "sport_title": "WNBA" if sport_key == "basketball_wnba" else "MLB",
        "commence_time": start.isoformat(),
        "home_team": "New York Liberty",
        "away_team": "Chicago Sky",
        "bookmakers": [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "last_update": updated,
                "link": "https://sportsbook.draftkings.com/event/alternate-event-1",
                "markets": [
                    {
                        "key": "alternate_spreads",
                        "last_update": updated,
                        "outcomes": [
                            {
                                "name": "New York Liberty",
                                "price": -115,
                                "point": -7.5,
                                "sid": "nyl-minus-7-5",
                            },
                            {
                                "name": "Chicago Sky",
                                "price": -105,
                                "point": 7.5,
                                "sid": "chi-plus-7-5",
                            },
                            {
                                "name": "New York Liberty",
                                "price": 120,
                                "point": -9.5,
                                "sid": "nyl-minus-9-5",
                            },
                            {
                                "name": "Chicago Sky",
                                "price": -140,
                                "point": 9.5,
                                "sid": "chi-plus-9-5",
                            },
                        ],
                    },
                    {
                        "key": "alternate_totals",
                        "last_update": updated,
                        "outcomes": [
                            {
                                "name": "Over",
                                "price": -110,
                                "point": 161.5,
                                "sid": "over-161-5",
                            },
                            {
                                "name": "Under",
                                "price": -110,
                                "point": 161.5,
                                "sid": "under-161-5",
                            },
                        ],
                    },
                ],
            }
        ],
    }


class AlternateSession:
    def __init__(self, start: datetime) -> None:
        self.event = _alternate_event(start)
        self.calls: list[dict] = []

    def get(self, url, *, params=None, timeout=None):
        self.calls.append(
            {"url": url, "params": dict(params or {}), "timeout": timeout}
        )
        if url.endswith("/events"):
            payload = [
                {
                    key: self.event[key]
                    for key in (
                        "id",
                        "sport_key",
                        "sport_title",
                        "commence_time",
                        "home_team",
                        "away_team",
                    )
                }
            ]
        else:
            payload = self.event
        return FakeResponse(
            payload,
            headers={
                "x-requests-remaining": "99970",
                "x-requests-used": "30",
                "x-requests-last": "2",
            },
        )


class TennisSession:
    def __init__(self, start: datetime) -> None:
        self.start = start
        self.calls: list[dict] = []

    def get(self, url, *, params=None, timeout=None):
        self.calls.append(
            {"url": url, "params": dict(params or {}), "timeout": timeout}
        )
        updated = datetime.now(timezone.utc).isoformat()
        event = {
            "id": "atp-event-1",
            "sport_key": "tennis_atp_cincinnati",
            "sport_title": "ATP Cincinnati",
            "commence_time": self.start.isoformat(),
            "home_team": "Arthur Fils",
            "away_team": "Alexander Zverev",
        }
        if url.endswith("/sports/"):
            payload = [
                {
                    "key": "tennis_atp_cincinnati",
                    "group": "Tennis",
                    "title": "ATP Cincinnati",
                    "active": True,
                },
                {
                    "key": "tennis_wta_cincinnati",
                    "group": "Tennis",
                    "title": "WTA Cincinnati",
                    "active": True,
                },
            ]
        elif url.endswith("/sports/tennis_atp_cincinnati/events"):
            payload = [event]
        elif url.endswith("/sports/tennis_wta_cincinnati/events"):
            payload = []
        else:
            event["bookmakers"] = [
                {
                    "key": "novig",
                    "title": "NoVIG",
                    "last_update": updated,
                    "link": "https://novig.us/market/atp-event-1",
                    "markets": [
                        {
                            "key": "h2h",
                            "last_update": updated,
                            "outcomes": [
                                {
                                    "name": "Arthur Fils",
                                    "price": 125,
                                    "sid": "fils-ml",
                                    "link": "https://novig.us/market/atp-event-1/fils",
                                },
                                {
                                    "name": "Alexander Zverev",
                                    "price": -145,
                                    "sid": "zverev-ml",
                                },
                            ],
                        }
                    ],
                }
            ]
            payload = [event]
        return FakeResponse(
            payload,
            headers={
                "x-requests-remaining": "99970",
                "x-requests-used": "30",
                "x-requests-last": "1",
            },
        )


def _trade(start: datetime, *, stake: float = 100) -> dict:
    return {
        "id": "trade-1",
        "category": "Baseball",
        "canonical_sport_id": "BASEBALL",
        "league": "MLB",
        "canonical_league_id": "MLB",
        "event_title": "New York Yankees vs Boston Red Sox",
        "market_title": "Moneyline",
        "sports_market_type": "Moneyline",
        "outcome": "Boston Red Sox",
        "event_date_et": start.isoformat(),
        "resolution_time": start.isoformat(),
        "card": {"recommended_amount": stake},
        "recommendation": {"recommended_amount": stake},
    }


def _provider(start: datetime) -> tuple[TheOddsAPIProvider, FakeSession]:
    session = FakeSession([_event(start)])
    return (
        TheOddsAPIProvider(
            "server-side-test-key",
            regions=("us",),
            markets=("h2h",),
            cache_ttl_seconds=300,
            max_quote_age_seconds=180,
            session=session,
        ),
        session,
    )


def test_historical_close_uses_last_snapshot_before_provider_commence() -> None:
    official = datetime(2026, 8, 3, 22, 40, tzinfo=timezone.utc)
    provider_commence = official + timedelta(minutes=1)
    payload = {
        "timestamp": (official + timedelta(seconds=38)).isoformat(),
        "data": {
            "id": "event-1",
            "sport_key": "baseball_mlb",
            "commence_time": provider_commence.isoformat(),
            "bookmakers": [
                {
                    "key": "novig",
                    "title": "NoVIG",
                    "markets": [
                        {
                            "key": "h2h",
                            "last_update": (official + timedelta(seconds=18)).isoformat(),
                            "outcomes": [
                                {"name": "Philadelphia Phillies", "price": -147},
                                {"name": "Washington Nationals", "price": 138},
                            ],
                        }
                    ],
                }
            ],
        },
    }
    session = FakeSession(payload)
    provider = TheOddsAPIProvider("key", session=session)

    quote = provider.historical_pregame_quote(
        league="MLB",
        event_id="event-1",
        bookmaker="novig",
        market_kind="moneyline",
        selection="Washington Nationals",
        official_start=official.isoformat(),
    )

    assert quote is not None
    option = quote["execution_option"]
    assert option["providerKey"] == "oddsapi__novig"
    assert option["displayOdds"] == "+138"
    assert option["bestExecutablePrice"] == pytest.approx(100 / 238)
    assert datetime.fromisoformat(quote["quote_timestamp"]) < provider_commence
    assert session.calls[0]["params"]["date"] == "2026-08-03T22:41:00Z"


def test_returns_every_exact_bookmaker_and_ranks_best_american_price() -> None:
    start = datetime.now(timezone.utc) + timedelta(hours=4)
    provider, _session = _provider(start)
    registry = ExecutionProviderRegistry(
        (provider,), comparison_provider_keys=("the_odds_api",)
    )
    trade = _trade(start)

    registry.attach_options([trade], compare_all=True)

    options = trade["executionOptions"]
    assert {item["providerName"] for item in options} == {
        "DraftKings",
        "FanDuel",
    }
    assert {item["providerKey"] for item in options} == {
        "oddsapi__draftkings",
        "oddsapi__fanduel",
    }
    assert next(item for item in options if item["isBestPrice"])[
        "providerName"
    ] == "FanDuel"
    assert next(
        item for item in options if item["providerName"] == "FanDuel"
    )["americanOdds"] == 110


def test_resolves_active_atp_tournament_before_requesting_tennis_odds() -> None:
    start = datetime.now(timezone.utc) + timedelta(hours=3)
    session = TennisSession(start)
    provider = TheOddsAPIProvider(
        "server-side-test-key",
        markets=("h2h",),
        trade_bookmakers=("novig",),
        session=session,
    )
    trade = {
        "id": "tennis-trade-1",
        "category": "Tennis",
        "canonical_sport_id": "TENNIS",
        "league": "ATP",
        "canonical_league_id": "ATP",
        "event_title": "Arthur Fils vs Alexander Zverev",
        "market_title": "Moneyline",
        "sports_market_type": "Moneyline",
        "outcome": "Arthur Fils",
        "event_date_et": start.isoformat(),
        "resolution_time": start.isoformat(),
        "card": {"recommended_amount": 100},
        "recommendation": {"recommended_amount": 100},
    }

    options = provider.options_for_trades([trade])["tennis-trade-1"]

    assert len(options) == 1
    assert options[0].provider_key == "oddsapi__novig"
    assert options[0].american_odds == 125
    paid_calls = [
        call for call in session.calls
        if call["url"].endswith("/odds/")
    ]
    assert len(paid_calls) == 1
    assert "/tennis_atp_cincinnati/odds/" in paid_calls[0]["url"]


def test_fair_price_quotes_expose_pinnacle_and_betonline_no_vig_sources() -> None:
    start = datetime.now(timezone.utc) + timedelta(hours=4)
    event = _event(start)
    event["bookmakers"][0]["key"] = "pinnacle"
    event["bookmakers"][0]["title"] = "Pinnacle"
    event["bookmakers"][1]["key"] = "betonlineag"
    event["bookmakers"][1]["title"] = "BetOnline.ag"
    session = FakeSession([event])
    provider = TheOddsAPIProvider(
        "server-side-test-key",
        regions=("us",),
        markets=("h2h",),
        session=session,
    )

    quotes = provider.fair_price_quotes([_trade(start)])

    by_provider = {
        row["provider"]: row
        for row in quotes["trade-1"]
    }
    assert set(by_provider) == {"pinnacle", "betonline"}
    assert all(row["mapping_confidence"] == "EXACT" for row in by_provider.values())
    assert all(0 < row["no_vig_probability"] < 1 for row in by_provider.values())
    assert all(row["fabricated_data"] is False for row in by_provider.values())


def test_cache_prevents_frontend_polling_from_spending_more_credits() -> None:
    start = datetime.now(timezone.utc) + timedelta(hours=4)
    provider, session = _provider(start)
    trade = _trade(start)

    provider.options_for_trades([trade])
    provider.options_for_trades([trade])

    assert len(session.calls) == 1
    assert session.calls[0]["params"]["bookmakers"] == (
        "kalshi,novig,polymarket,prophetx"
    )
    assert "regions" not in session.calls[0]["params"]
    assert session.calls[0]["params"]["markets"] == "h2h"
    assert session.calls[0]["params"]["includeLinks"] == "true"
    assert session.calls[0]["params"]["includeSids"] == "true"
    assert session.calls[0]["params"]["includeBetLimits"] == "true"


def test_known_bet_limit_prevents_best_price_when_stake_is_too_large() -> None:
    start = datetime.now(timezone.utc) + timedelta(hours=4)
    provider, _session = _provider(start)
    registry = ExecutionProviderRegistry(
        (provider,), comparison_provider_keys=("the_odds_api",)
    )
    trade = _trade(start, stake=600)

    registry.attach_options([trade], compare_all=True)

    draftkings = next(
        item
        for item in trade["executionOptions"]
        if item["providerName"] == "DraftKings"
    )
    assert draftkings["canFillRecommendedStake"] is False
    assert draftkings["isBestPrice"] is False


def test_odds_screen_rows_include_both_sides_and_today_tomorrow_only() -> None:
    now = datetime.now(timezone.utc)
    start = now + timedelta(hours=4)
    provider, _session = _provider(start)

    rows = provider.odds_screen_rows(
        sport="Baseball", league="MLB", market_kind="moneyline", now=now
    )

    assert {row["outcome"] for row in rows} == {
        "Boston Red Sox",
        "New York Yankees",
    }
    assert {row["market_id"] for row in rows} == {
        "oddsapi::mlb-event-1::moneyline::None"
    }
    assert all(row["odds_api_event"] is True for row in rows)


def test_wnba_alternate_spreads_and_totals_use_event_level_endpoints() -> None:
    now = datetime.now(timezone.utc)
    session = AlternateSession(now + timedelta(hours=4))
    provider = TheOddsAPIProvider(
        "server-side-test-key",
        regions=("us", "us2"),
        default_sports=("basketball_wnba",),
        cache_ttl_seconds=300,
        alternate_cache_ttl_seconds=600,
        session=session,
    )

    spread_rows = provider.odds_screen_rows(
        sport="Basketball",
        league="WNBA",
        market_kind="alternate_spread",
        now=now,
    )
    total_rows = provider.odds_screen_rows(
        sport="Basketball",
        league="WNBA",
        market_kind="alternate_total",
        now=now,
    )

    assert len(spread_rows) == 4
    assert {row["market_line"] for row in spread_rows} == {
        -9.5,
        -7.5,
        7.5,
        9.5,
    }
    assert all(row["is_alternative"] is True for row in spread_rows)
    assert all(
        row["sports_market_type"] == "Alternate Spread"
        for row in spread_rows
    )
    assert {row["outcome"] for row in total_rows} == {"Over", "Under"}
    assert all(
        row["sports_market_type"] == "Alternate Total"
        for row in total_rows
    )
    assert all(
        (canonical := canonicalize_trade(row))
        and canonical.is_alternative
        and canonical.market_kind == "spread"
        for row in spread_rows
    )
    assert all(
        (canonical := canonicalize_trade(row))
        and canonical.is_alternative
        and canonical.market_kind == "game_total"
        for row in total_rows
    )
    event_calls = [
        call
        for call in session.calls
        if "/events/alternate-event-1/odds" in call["url"]
    ]
    assert {
        call["params"]["markets"] for call in event_calls
    } == {"alternate_spreads", "alternate_totals"}
    assert all(call["params"]["regions"] == "us,us2" for call in event_calls)


def test_standard_labeled_trade_can_match_exact_alternate_book_line() -> None:
    start = datetime.now(timezone.utc) + timedelta(hours=4)
    session = AlternateSession(start)
    provider = TheOddsAPIProvider(
        "server-side-test-key",
        regions=("us",),
        markets=("h2h",),
        default_sports=("basketball_wnba",),
        session=session,
    )
    trade = {
        "id": "trade-wnba-spread",
        "canonical_sport_id": "BASKETBALL",
        "canonical_league_id": "WNBA",
        "event_title": "Chicago Sky vs New York Liberty",
        "market_title": "Spread: New York Liberty (-7.5)",
        "sports_market_type": "Spread",
        "market_line": -7.5,
        "outcome": "Chicago Sky",
        "event_date_et": start.isoformat(),
    }

    options = provider.options_for_trades([trade])

    assert options["trade-wnba-spread"][0].american_odds == -105
    assert any(
        call["params"].get("markets") == "alternate_spreads"
        for call in session.calls
    )


def test_alternate_event_level_results_are_cached() -> None:
    now = datetime.now(timezone.utc)
    session = AlternateSession(now + timedelta(hours=4))
    provider = TheOddsAPIProvider(
        "server-side-test-key",
        regions=("us",),
        default_sports=("basketball_wnba",),
        cache_ttl_seconds=300,
        alternate_cache_ttl_seconds=600,
        session=session,
    )

    for _ in range(2):
        provider.odds_screen_rows(
            league="WNBA",
            market_kind="alternate_spread",
            now=now,
        )

    assert len(
        [
            call
            for call in session.calls
            if "/events/alternate-event-1/odds" in call["url"]
        ]
    ) == 1


def test_quota_diagnostics_do_not_expose_api_key() -> None:
    start = datetime.now(timezone.utc) + timedelta(hours=4)
    provider, _session = _provider(start)
    provider.options_for_trades([_trade(start)])

    diagnostics = provider.diagnostics()

    assert diagnostics["quota"]["remaining"] == "99991"
    assert diagnostics["quota"]["used"] == "9"
    assert diagnostics["quota"]["last"] == "3"
    assert diagnostics["credentials_exposed"] is False
    assert "api_key" not in diagnostics


def test_default_catalog_covers_every_configured_region() -> None:
    provider = TheOddsAPIProvider(
        "server-side-test-key",
        session=FakeSession([]),
    )

    catalog = {
        item["key"]: item
        for item in provider.provider_catalog([])
    }

    assert tuple(provider.diagnostics()["regions"]) == DEFAULT_REGIONS
    assert len(catalog) >= 78
    assert catalog["oddsapi__kalshi"]["region"] == "us_ex"
    assert catalog["oddsapi__prizepicks"]["region"] == "us_dfs"
    assert catalog["oddsapi__williamhill"]["region"] == "uk"
    assert catalog["oddsapi__sportsbet"]["region"] == "au"
    assert catalog["oddsapi__svenskaspel_se"]["region"] == "se"
    assert catalog["oddsapi__winamax_fr"]["region"] == "fr"
    assert catalog["oddsapi__polymarket"]["name"] == "Polymarket (Odds API)"
    assert all(item["logoUrl"] for item in catalog.values())


def test_featured_markets_exclude_dfs_region() -> None:
    now = datetime.now(timezone.utc)
    session = FakeSession([_event(now + timedelta(hours=4))])
    provider = TheOddsAPIProvider(
        "server-side-test-key",
        regions=DEFAULT_REGIONS,
        markets=("h2h",),
        session=session,
    )

    provider.odds_screen_rows(
        league="MLB",
        market_kind="moneyline",
        now=now,
    )

    assert session.calls[0]["params"]["regions"] == (
        "us,us2,us_ex,uk,au,se,fr"
    )


def test_alternate_markets_only_query_supported_us_book_regions() -> None:
    now = datetime.now(timezone.utc)
    session = AlternateSession(now + timedelta(hours=4))
    provider = TheOddsAPIProvider(
        "server-side-test-key",
        regions=DEFAULT_REGIONS,
        default_sports=("basketball_wnba",),
        session=session,
    )

    provider.odds_screen_rows(
        league="WNBA",
        market_kind="alternate_spread",
        now=now,
    )

    event_call = next(
        call
        for call in session.calls
        if "/events/alternate-event-1/odds" in call["url"]
    )
    assert event_call["params"]["regions"] == "us,us2"


def test_missing_key_is_fail_closed_without_network_call() -> None:
    session = FakeSession([])
    provider = TheOddsAPIProvider(None, session=session)
    trade = _trade(datetime.now(timezone.utc) + timedelta(hours=4))

    assert provider.options_for_trades([trade]) == {}
    assert provider.failure_reasons["trade-1"] == "PROVIDER_NOT_CONFIGURED"
    assert session.calls == []


def test_odds_screen_api_exposes_odds_engine_sportsbook_catalog(
    app_client, monkeypatch
) -> None:
    registry = app_client.application.extensions["execution_providers"]
    provider = next(
        item
        for item in registry.providers
        if item.provider_key == "odds_engine"
    )
    start = datetime.now(timezone.utc) + timedelta(hours=4)
    provider.api_key = "configured-in-test"
    observed_at = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(
        provider,
        "ev_events",
        lambda **_kwargs: [
            {
                "id": "screen-trade-1",
                "sport_key": "baseball_mlb",
                "sport_title": "MLB",
                "commence_time": start.isoformat(),
                "home_team": "Miami Marlins",
                "away_team": "San Diego Padres",
                "bookmakers": [
                    {
                        "key": "fanduel",
                        "title": "FanDuel",
                        "logo": "https://sportsbook.fanduel.com/favicon.ico",
                        "markets": [
                            {
                                "key": "h2h",
                                "last_update": observed_at,
                                "outcomes": [
                                    {
                                        "name": "Miami Marlins",
                                        "price": 110,
                                        "link": "https://sportsbook.fanduel.com/betslip/selection",
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
        "/api/odds-screen?active=1&league=MLB&market=moneyline"
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == (
        "public, max-age=10, s-maxage=60, stale-while-revalidate=120"
    )
    payload = response.get_json()
    assert payload["filters"] == {
        "sport": "",
        "league": "MLB",
        "market": "moneyline",
    }
    assert any(
        item["key"] == "oddsengine__fanduel"
        and item["name"] == "FanDuel"
        and item["source"] == "odds_engine"
        for item in payload["providers"]
    )
    assert any(
        item["key"] == "oddsengine__prizepicks"
        for item in payload["providers"]
    )
    assert any(
        option["providerKey"] == "oddsengine__fanduel"
        for item in payload["data"]
        for option in item["executionOptions"]
    )
    fanduel_option = next(
        option
        for item in payload["data"]
        for option in item["executionOptions"]
        if option["providerKey"] == "oddsengine__fanduel"
    )
    assert fanduel_option["bestExecutablePrice"] == pytest.approx(100 / 210)
    assert fanduel_option["isStale"] is False
    assert fanduel_option["marketStatus"] == "OPEN"


def test_odds_screen_preserves_both_moneyline_sides(
    app_client, monkeypatch
) -> None:
    registry = app_client.application.extensions["execution_providers"]
    provider = next(
        item
        for item in registry.providers
        if item.provider_key == "odds_engine"
    )
    start = datetime.now(timezone.utc) + timedelta(hours=4)
    provider.api_key = "configured-in-test"
    monkeypatch.setattr(
        provider,
        "ev_events",
        lambda **_kwargs: [
            {
                "id": "two-sided-event",
                "sport_key": "baseball_mlb",
                "sport_title": "MLB",
                "commence_time": start.isoformat(),
                "home_team": "Miami Marlins",
                "away_team": "San Diego Padres",
                "bookmakers": [
                    {
                        "key": "fanduel",
                        "title": "FanDuel",
                        "markets": [
                            {
                                "key": "h2h",
                                "last_update": datetime.now(timezone.utc).isoformat(),
                                "outcomes": [
                                    {"name": "San Diego Padres", "price": -105},
                                    {"name": "Miami Marlins", "price": -105},
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    )

    response = app_client.get("/api/odds-screen?active=1&league=MLB")

    assert response.status_code == 200
    assert {
        row["outcome"]
        for row in response.get_json()["data"]
        if row.get("event_id") == "two-sided-event"
    } == {"San Diego Padres", "Miami Marlins"}
