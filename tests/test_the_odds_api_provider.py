from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

from execution_providers import (
    ExecutionOption,
    ExecutionProviderRegistry,
    MatchConfidence,
    canonicalize_trade,
)
from the_odds_api_provider import TheOddsAPIProvider


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


def test_returns_every_exact_bookmaker_and_ranks_best_american_price() -> None:
    start = datetime.now(timezone.utc) + timedelta(hours=4)
    provider, _session = _provider(start)
    registry = ExecutionProviderRegistry(
        (provider,), comparison_provider_keys=("the_odds_api",)
    )
    trade = _trade(start)

    registry.attach_options([trade])

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


def test_cache_prevents_frontend_polling_from_spending_more_credits() -> None:
    start = datetime.now(timezone.utc) + timedelta(hours=4)
    provider, session = _provider(start)
    trade = _trade(start)

    provider.options_for_trades([trade])
    provider.options_for_trades([trade])

    assert len(session.calls) == 1
    assert session.calls[0]["params"]["regions"] == "us"
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

    registry.attach_options([trade])

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


def test_missing_key_is_fail_closed_without_network_call() -> None:
    session = FakeSession([])
    provider = TheOddsAPIProvider(None, session=session)
    trade = _trade(datetime.now(timezone.utc) + timedelta(hours=4))

    assert provider.options_for_trades([trade]) == {}
    assert provider.failure_reasons["trade-1"] == "PROVIDER_NOT_CONFIGURED"
    assert session.calls == []


def test_odds_screen_api_exposes_dynamic_sportsbook_catalog(
    app_client, monkeypatch
) -> None:
    registry = app_client.application.extensions["execution_providers"]
    provider = next(
        item
        for item in registry.providers
        if item.provider_key == "the_odds_api"
    )
    start = datetime.now(timezone.utc) + timedelta(hours=4)
    row = {
        **_trade(start, stake=0),
        "id": "screen-trade-1",
        "market_id": "screen-market-1",
        "schedule_date_et": start.astimezone().date().isoformat(),
        "is_sports": True,
    }
    option = ExecutionOption(
        provider_name="FanDuel",
        provider_key="oddsapi__fanduel",
        market_id="mlb-event-1:moneyline",
        selection_id="fanduel:selection",
        display_odds="+110",
        deep_link="https://sportsbook.fanduel.com/betslip/selection",
        is_available=True,
        last_updated=datetime.now(timezone.utc).isoformat(),
        matching_confidence=MatchConfidence.EXACT,
        logo_url="https://sportsbook.fanduel.com/favicon.ico",
        tooltip="FanDuel sportsbook quote via The Odds API",
        american_odds=110,
        can_fill_recommended_stake=True,
        quote_status="OPEN",
        native_price_format="AMERICAN",
        quote_max_age_seconds=180,
    )
    monkeypatch.setattr(
        provider, "odds_screen_rows", lambda **_kwargs: [dict(row)]
    )
    monkeypatch.setattr(
        provider,
        "options_for_trades",
        lambda trades: {
            str(item["id"]): [option]
            for item in trades
            if str(item.get("id") or "") == "screen-trade-1"
        },
    )

    response = app_client.get(
        "/api/odds-screen?league=MLB&market=moneyline"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["filters"] == {
        "sport": "",
        "league": "MLB",
        "market": "moneyline",
    }
    assert any(
        item["key"] == "oddsapi__fanduel"
        and item["name"] == "FanDuel"
        and item["source"] == "the_odds_api"
        for item in payload["providers"]
    )
    assert any(
        option["providerKey"] == "oddsapi__fanduel"
        for item in payload["data"]
        for option in item["executionOptions"]
    )
