from __future__ import annotations

from copy import deepcopy

import pytest
import requests

from config import get_settings
from execution_providers import (
    ExecutionProviderRegistry,
    MatchConfidence,
    NoVIGProvider,
    PolymarketProvider,
    ProphetXProvider,
    ProviderHealthStatus,
)


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return deepcopy(self.payload)


class FakeSession:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = []
        self.error: Exception | None = None

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return FakeResponse(self.payload)

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return FakeResponse(self.payload)


def trade(**overrides) -> dict:
    value = {
        "id": "trade-1",
        "event_title": "New York Yankees vs Boston Red Sox",
        "market_title": "Moneyline",
        "outcome": "New York Yankees",
        "sports_market_type": "moneyline",
        "market_line": None,
        "event_date_et": "2026-07-14T19:00:00-04:00",
        "canonical_sport_id": "baseball",
        "canonical_league_id": "mlb",
        "market_url": "https://polymarket.com/event/yankees-red-sox",
        "clob_token_id": "polymarket-yankees",
        "validation_ids": {"condition_id": "polymarket-market-1"},
        "recommendation": {"current_user_entry_price": 0.507},
        "card": {"current_actionable_price": 0.507},
        "orderbook_summary": {"timestamp": "2026-07-14T20:00:00Z"},
    }
    value.update(overrides)
    return value


def event(*, odds: dict | None = None, **overrides) -> dict:
    value = {
        "eventID": "novig-event-1",
        "sportID": "BASEBALL",
        "leagueID": "MLB",
        "type": "match",
        "teams": {
            "home": {
                "teamID": "NEW_YORK_YANKEES_MLB",
                "names": {
                    "long": "New York Yankees",
                    "medium": "Yankees",
                    "short": "NYY",
                },
            },
            "away": {
                "teamID": "BOSTON_RED_SOX_MLB",
                "names": {
                    "long": "Boston Red Sox",
                    "medium": "Red Sox",
                    "short": "BOS",
                },
            },
        },
        "status": {"startsAt": "2026-07-14T23:00:00Z"},
        "links": {"bookmakers": {"novig": "https://app.novig.us/event/1"}},
        "odds": odds or {"points-home-game-ml-home": odd()},
    }
    value.update(overrides)
    return value


def odd(**overrides) -> dict:
    value = {
        "oddID": "points-home-game-ml-home",
        "marketName": "Moneyline",
        "statID": "points",
        "statEntityID": "home",
        "periodID": "game",
        "betTypeID": "ml",
        "sideID": "home",
        "byBookmaker": {
            "novig": {
                "odds": "+108",
                "available": True,
                "lastUpdatedAt": "2026-07-14T20:00:00Z",
                "deeplink": "https://app.novig.us/event/1/market/yankees",
            }
        },
    }
    value.update(overrides)
    return value


def provider_for(provider_event: dict) -> tuple[NoVIGProvider, FakeSession]:
    session = FakeSession({"success": True, "data": [provider_event]})
    return NoVIGProvider("test-key", session=session), session


def test_polymarket_provider_preserves_existing_price_and_link() -> None:
    option = PolymarketProvider().options_for_trades([trade()])["trade-1"]

    assert option.provider_name == "Polymarket"
    assert option.display_odds == "50.7\u00a2"
    assert option.deep_link == "https://polymarket.com/event/yankees-red-sox"
    assert option.matching_confidence is MatchConfidence.EXACT


def test_registry_returns_ordered_generic_provider_contract() -> None:
    novig, _session = provider_for(event())
    value = trade()

    ExecutionProviderRegistry((PolymarketProvider(), novig)).attach_options([value])

    assert [item["providerName"] for item in value["executionOptions"]] == [
        "Polymarket",
        "NoVIG",
    ]
    novig_option = value["executionOptions"][1]
    assert {key: novig_option[key] for key in (
        "marketId",
        "selectionId",
        "displayOdds",
        "deepLink",
        "isAvailable",
        "matchingConfidence",
    )} == {
        "marketId": "novig-event-1",
        "selectionId": "points-home-game-ml-home",
        "displayOdds": "+108",
        "deepLink": "https://app.novig.us/event/1/market/yankees",
        "isAvailable": True,
        "matchingConfidence": "Exact",
    }


def test_one_cached_feed_matches_multiple_trades_without_n_plus_one_requests() -> None:
    novig, session = provider_for(event())
    first = trade()
    second = trade(id="trade-2")

    options = novig.options_for_trades([first, second])
    again = novig.options_for_trades([first])

    assert set(options) == {"trade-1", "trade-2"}
    assert again["trade-1"].display_odds == "+108"
    assert len(session.calls) == 1
    assert session.calls[0][1]["params"]["bookmakerID"] == "novig"
    assert session.calls[0][1]["headers"] == {"x-api-key": "test-key"}


def test_exact_game_total_matches_only_the_identical_line() -> None:
    total_odd = odd(
        oddID="points-all-game-ou-over",
        marketName="Over/Under",
        statEntityID="all",
        betTypeID="ou",
        sideID="over",
        byBookmaker={
            "novig": {
                "odds": "-112",
                "overUnder": "8.5",
                "available": True,
                "deeplink": "https://app.novig.us/event/1/market/over-8-5",
            }
        },
    )
    novig, _session = provider_for(
        event(odds={"points-all-game-ou-over": total_odd})
    )
    exact = trade(
        market_title="Over 8.5 Runs",
        outcome="Over 8.5",
        sports_market_type="total",
        market_line=8.5,
    )
    wrong_line = trade(
        id="trade-2",
        market_title="Over 8 Runs",
        outcome="Over 8",
        sports_market_type="total",
        market_line=8,
    )

    options = novig.options_for_trades([exact, wrong_line])

    assert options["trade-1"].display_odds == "-112"
    assert "trade-2" not in options


@pytest.mark.parametrize(
    ("source_overrides", "provider_odd"),
    [
        (
            {
                "canonical_sport_id": "soccer",
                "canonical_league_id": "world-cup",
                "event_title": "Spain vs France",
                "market_title": "Spain To Advance",
                "outcome": "Spain",
                "sports_market_type": "to_advance",
            },
            odd(),
        ),
        (
            {"market_title": "First Half Moneyline"},
            odd(periodID="game"),
        ),
        (
            {
                "market_title": "Yankees Team Total Over 4.5",
                "outcome": "Over 4.5",
                "sports_market_type": "team_total",
                "market_line": 4.5,
            },
            odd(
                oddID="points-all-game-ou-over",
                marketName="Over/Under",
                statEntityID="all",
                betTypeID="ou",
                sideID="over",
                byBookmaker={
                    "novig": {
                        "odds": "-110",
                        "overUnder": "4.5",
                        "available": True,
                        "deeplink": "https://app.novig.us/event/1/market/total",
                    }
                },
            ),
        ),
        (
            {
                "market_title": "Alternative Over 8.5 Runs",
                "outcome": "Over 8.5",
                "sports_market_type": "total",
                "market_line": 8.5,
            },
            odd(
                oddID="points-all-game-ou-over",
                marketName="Over/Under",
                statEntityID="all",
                betTypeID="ou",
                sideID="over",
                byBookmaker={
                    "novig": {
                        "odds": "-110",
                        "overUnder": "8.5",
                        "available": True,
                        "deeplink": "https://app.novig.us/event/1/market/total",
                    }
                },
            ),
        ),
    ],
)
def test_dangerous_near_matches_are_never_returned(
    source_overrides: dict, provider_odd: dict
) -> None:
    provider_event = event(odds={provider_odd["oddID"]: provider_odd})
    if source_overrides.get("canonical_sport_id") == "soccer":
        provider_event.update(
            {
                "sportID": "SOCCER",
                "leagueID": "FIFA_WORLD_CUP",
                "teams": {
                    "home": {"teamID": "SPAIN", "names": {"long": "Spain"}},
                    "away": {"teamID": "FRANCE", "names": {"long": "France"}},
                },
            }
        )
    novig, _session = provider_for(provider_event)

    assert novig.options_for_trades([trade(**source_overrides)]) == {}


def test_exact_to_advance_requires_an_explicit_advance_market() -> None:
    advance = odd(
        oddID="points-home-game-yn-yes",
        marketName="Spain To Advance",
        statEntityID="home",
        betTypeID="yn",
        sideID="yes",
        byBookmaker={
            "novig": {
                "odds": "+120",
                "available": True,
                "deeplink": "https://app.novig.us/event/1/market/spain-advance",
            }
        },
    )
    provider_event = event(
        odds={"points-home-game-yn-yes": advance},
        sportID="SOCCER",
        leagueID="FIFA_WORLD_CUP",
        teams={
            "home": {"teamID": "SPAIN", "names": {"long": "Spain"}},
            "away": {"teamID": "FRANCE", "names": {"long": "France"}},
        },
    )
    novig, _session = provider_for(provider_event)
    source = trade(
        canonical_sport_id="soccer",
        canonical_league_id="world-cup",
        event_title="Spain vs France",
        market_title="Spain To Advance",
        outcome="Spain",
        sports_market_type="to_advance",
    )

    assert novig.options_for_trades([source])["trade-1"].display_odds == "+120"


def test_participant_or_start_time_mismatch_never_matches() -> None:
    novig, _session = provider_for(event())
    wrong_participant = trade(event_title="New York Yankees vs Toronto Blue Jays")
    wrong_time = trade(id="trade-2", event_date_et="2026-07-14T20:00:00-04:00")

    assert novig.options_for_trades([wrong_participant, wrong_time]) == {}


def test_provider_outage_disables_known_match_without_showing_stale_odds() -> None:
    novig, session = provider_for(event())
    source = trade()
    first = novig.options_for_trades([source])["trade-1"]
    session.error = requests.ConnectionError("provider unavailable")
    novig.cache_ttl_seconds = 0

    unavailable = novig.options_for_trades([source])["trade-1"]

    assert first.display_odds == "+108"
    assert unavailable.display_odds == "Unavailable"
    assert unavailable.american_odds is None
    assert unavailable.deep_link is None
    assert unavailable.is_available is False


def test_unconfigured_provider_is_hidden_without_network_access() -> None:
    session = FakeSession({"success": True, "data": [event()]})
    novig = NoVIGProvider(None, session=session)

    assert novig.options_for_trades([trade()]) == {}
    assert session.calls == []


def test_prophetx_configuration_is_redacted_and_does_not_make_a_request() -> None:
    session = FakeSession({})
    provider = ProphetXProvider("test-access", "test-secret", session=session)

    assert provider.health_status() is ProviderHealthStatus.CONFIGURED
    assert session.calls == []
    assert "test-access" not in repr(provider)
    assert "test-secret" not in repr(provider)


def test_prophetx_settings_use_only_the_exact_environment_names(monkeypatch) -> None:
    monkeypatch.setenv("PROPHETX_ACCESS_KEY", "exact-access")
    monkeypatch.setenv("PROPHETX_SECRET_KEY", "exact-secret")
    monkeypatch.setenv("PROPHETX_API_KEY", "wrong-access")
    monkeypatch.setenv("PROPHETX_API_SECRET", "wrong-secret")

    settings = get_settings()

    assert settings.prophetx_access_key == "exact-access"
    assert settings.prophetx_secret_key == "exact-secret"
    assert "exact-access" not in repr(settings)
    assert "exact-secret" not in repr(settings)


def test_prophetx_authentication_uses_the_sandbox_contract() -> None:
    session = FakeSession({"data": {"access_token": "temporary-session-token"}})
    provider = ProphetXProvider("test-access", "test-secret", session=session)

    status = provider.health_status(authenticate=True)

    assert status is ProviderHealthStatus.AUTHENTICATED
    assert session.calls == [
        (
            "https://api-ss-sandbox.betprophet.co/partner/auth/login",
            {
                "json": {
                    "access_key": "test-access",
                    "secret_key": "test-secret",
                },
                "headers": {
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                "timeout": 15,
            },
        )
    ]

    assert provider.health_status(authenticate=True) is ProviderHealthStatus.AUTHENTICATED
    assert len(session.calls) == 1


@pytest.mark.parametrize("status_code", [400, 401, 403])
def test_prophetx_rejects_invalid_credentials_without_error_details(
    status_code: int,
) -> None:
    session = FakeSession({"message": "sensitive upstream detail"})
    provider = ProphetXProvider("test-access", "test-secret", session=session)
    session.post = lambda *_args, **_kwargs: FakeResponse({}, status_code=status_code)

    assert (
        provider.health_status(authenticate=True)
        is ProviderHealthStatus.UNAUTHORIZED
    )


@pytest.mark.parametrize(
    "session",
    [
        FakeSession({"data": {}}),
        FakeSession({"data": {"access_token": ""}}),
    ],
)
def test_prophetx_malformed_success_is_a_redacted_connection_failure(
    session: FakeSession,
) -> None:
    provider = ProphetXProvider("test-access", "test-secret", session=session)

    assert (
        provider.health_status(authenticate=True)
        is ProviderHealthStatus.CONNECTION_FAILED
    )


def test_prophetx_connection_error_is_redacted() -> None:
    session = FakeSession({})
    session.error = requests.ConnectionError("do not return this detail")
    provider = ProphetXProvider("test-access", "test-secret", session=session)

    assert (
        provider.health_status(authenticate=True)
        is ProviderHealthStatus.CONNECTION_FAILED
    )


def test_novig_homepage_is_never_used_as_an_execution_link() -> None:
    no_market_link = event(
        links={"bookmakers": {"novig": "https://novig.us/"}},
        odds={
            "points-home-game-ml-home": odd(
                byBookmaker={
                    "novig": {
                        "odds": "+108",
                        "available": True,
                    }
                }
            )
        },
    )
    novig, _session = provider_for(no_market_link)

    option = novig.options_for_trades([trade()])["trade-1"]

    assert option.display_odds == "Unavailable"
    assert option.deep_link is None
    assert option.is_available is False
