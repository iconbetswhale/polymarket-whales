from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
import requests

from sharp_money_live import (
    OddsComparisonFallback,
    SharpMoneyCollector,
    _crossed_market_liquidity,
    _net_exchange_liquidity,
    build_sharp_money_collector,
)


class FakeProphetX:
    def __init__(self):
        self.calls = 0
        self.price = 2.0
        self.liquidity = 1200

    def diagnostics(self):
        return {
            "provider": "prophetx",
            "configured": True,
            "health": "authenticated",
            "metrics": {"requests": self.calls},
        }

    def live_market_snapshot(self):
        self.calls += 1
        self.price -= 0.02
        self.liquidity -= 100
        return {
            "observedAt": "2026-07-29T18:00:00+00:00",
            "tournaments": [
                {"id": "mlb", "name": "MLB", "sport": "Baseball"}
            ],
            "events": [
                {
                    "event_id": "event-1",
                    "tournament_id": "mlb",
                    "home_team": "Philadelphia Phillies",
                    "away_team": "New York Mets",
                    "start_time": "2026-07-30T23:10:00+00:00",
                }
            ],
            "markets": {
                "event-1": [
                    {
                        "market_id": "market-1",
                        "name": "Moneyline",
                        "selections": [
                            {
                                "outcome_id": "phillies",
                                "name": "Philadelphia Phillies",
                                "price": self.price,
                                "quantity": self.liquidity,
                            },
                            {
                                "outcome_id": "mets",
                                "name": "New York Mets",
                                "price": 1.85,
                                "quantity": 900,
                            },
                        ],
                    }
                ]
            },
        }


class FakeComparisonProvider:
    def __init__(self, provider_key: str, result=None, *, fails: bool = False):
        self.provider_key = provider_key
        self.api_key = "configured"
        self.result = result or {}
        self.fails = fails
        self.calls = 0

    def diagnostics(self):
        return {"provider": self.provider_key, "configured": True}

    def screen_options_for_trades(self, _trades):
        self.calls += 1
        if self.fails:
            raise ConnectionError("synthetic outage")
        return self.result


class FakeExecutionOption:
    def __init__(
        self,
        provider_key: str,
        american_odds: int,
        *,
        liquidity: float | None = None,
    ) -> None:
        self.provider_key = provider_key
        self.provider_name = (
            "NoVIG" if provider_key == "novig" else "FanDuel"
        )
        self.american_odds = american_odds
        self.display_odds = (
            f"+{american_odds}" if american_odds > 0 else str(american_odds)
        )
        self.is_available = True
        self.top_price_liquidity = liquidity
        self.deep_link = f"https://{provider_key}.test/market"
        self.logo_url = f"/{provider_key}.png"
        self.order_book = {
            "asks": [
                {
                    "americanOdds": american_odds,
                    "liquidityDollars": liquidity,
                }
            ]
            if liquidity
            else []
        }

    def to_dict(self) -> dict:
        return {
            "providerName": self.provider_name,
            "providerKey": self.provider_key,
            "americanOdds": self.american_odds,
            "displayOdds": self.display_odds,
            "isAvailable": True,
            "deepLink": self.deep_link,
            "logoUrl": self.logo_url,
        }


class FakeDirectNoVIG:
    configured = True

    def __init__(self) -> None:
        self.calls = 0

    def options_for_trades(self, trades):
        self.calls += 1
        result = {}
        for trade in trades:
            if "Philadelphia Phillies" in trade["outcome"]:
                result[trade["id"]] = FakeExecutionOption(
                    "novig", 125, liquidity=900
                )
            elif "New York Mets" in trade["outcome"]:
                result[trade["id"]] = FakeExecutionOption(
                    "novig", -115, liquidity=300
                )
        return result


class FakeDirectNoVIGSlate:
    configured = True
    provider_key = "novig_nbx"

    def __init__(self) -> None:
        self.calls = 0

    def diagnostics(self):
        return {"provider": self.provider_key, "configured": True}

    @staticmethod
    def options_for_trades(_trades):
        return {}

    def sharp_money_direct_snapshot(self, *, limit=40):
        self.calls += 1
        assert limit == 40
        return {
            "observedAt": "2026-08-27T05:30:00+00:00",
            "snapshots": [
                {
                    "marketId": "novig-market-1",
                    "eventId": "novig-event-1",
                    "timestamp": "2026-08-27T05:30:00+00:00",
                    "stale": False,
                    "market": {
                        "id": "novig-market-1",
                        "eventId": "novig-event-1",
                        "league": "MLB",
                        "type": "MONEY",
                        "status": "OPEN",
                        "outcomes": [
                            {
                                "id": "yankees",
                                "index": 0,
                                "description": "New York Yankees",
                            },
                            {
                                "id": "red-sox",
                                "index": 1,
                                "description": "Boston Red Sox",
                            },
                        ],
                        "event": {
                            "id": "novig-event-1",
                            "scheduledStart": "2026-08-28T23:05:00+00:00",
                            "game": {
                                "homeTeam": {"name": "New York Yankees"},
                                "awayTeam": {"name": "Boston Red Sox"},
                            },
                        },
                    },
                    "outcomes": [
                        {
                            "outcomeId": "yankees",
                            "bestAsk": 0.5122,
                            "asks": [
                                {
                                    "price": 0.5122,
                                    "liquidityDollars": 10000,
                                }
                            ],
                        },
                        {
                            "outcomeId": "red-sox",
                            "bestAsk": 0.4878,
                            "asks": [
                                {
                                    "price": 0.4878,
                                    "liquidityDollars": 7000,
                                }
                            ],
                        },
                    ],
                }
            ],
        }


class FakeOddsEngineOrderBook:
    provider_key = "odds_engine"

    def __init__(self):
        self.api_key = "advanced-key"
        self.calls = 0

    def diagnostics(self):
        return {
            "provider": self.provider_key,
            "configured": True,
            "supportsOrderBook": True,
            "metrics": {"requests": self.calls},
        }

    def sharp_money_snapshot(self, *, limit=40):
        self.calls += 1
        assert limit == 40
        recommended = {
            "side": "HOME",
            "line": -1.5,
            "books": {
                "prophetx": {
                    "odds_american": 115,
                    "odds_decimal": 2.15,
                    "liquidity": 1500,
                    "total_liquidity": 2500,
                    "bet_link": "https://prophetx.test/market-1",
                    "order_book": [
                        {"odds": 115, "liquidity": 1000},
                        {"odds": 120, "liquidity": 1500},
                    ],
                },
                "novig": {
                    "odds_american": 110,
                    "odds_decimal": 2.1,
                    "liquidity": 800,
                    "order_book": [{"odds": 110, "liquidity": 800}],
                },
                "fanduel": {
                    "odds_american": 130,
                    "odds_decimal": 2.3,
                    "limit": 500,
                    "bet_link": "https://fanduel.test/market-1",
                },
            },
            "peers": [
                {
                    "book": "pinnacle",
                    "odds_american": 108,
                    "opp_odds_american": -112,
                    "limit": 5000,
                    "bet_link": "https://pinnacle.test/market-1",
                }
            ],
        }
        opposite = {
            "side": "AWAY",
            "line": 1.5,
            "books": {
                "prophetx": {
                    "odds_american": -125,
                    "odds_decimal": 1.8,
                    "liquidity": 1400,
                    "total_liquidity": 2100,
                    "order_book": [
                        {"odds": -125, "liquidity": 1400},
                        {"odds": -120, "liquidity": 700},
                    ],
                },
                "novig": {
                    "odds_american": -120,
                    "odds_decimal": 1.8333,
                    "liquidity": 700,
                    "order_book": [{"odds": -120, "liquidity": 700}],
                },
                "fanduel": {
                    "odds_american": -125,
                    "odds_decimal": 1.8,
                },
            },
        }
        return {
            "meta": {
                "format": "whale",
                "returned": 1,
                "updated_at": "2026-08-26T18:00:00+00:00",
            },
            "opportunities": [
                {
                    "best_book": "prophetx",
                    "best_odds": 115,
                    "edge_percent": 4.2,
                    "edge_supporting_liquidity": 2500,
                    "fair_odds": 105,
                    "same_side_conviction_liquidity": 3200,
                    "whale_volume": 8400,
                    "whale_volume_mode": "same_side_conviction",
                    "recommended_side": recommended,
                    "opposite_side": opposite,
                    "market_data": {
                        "id": "market-1",
                        "event_id": "event-1",
                        "event": "New York Mets vs Philadelphia Phillies",
                        "event_start": "2026-08-27T23:10:00+00:00",
                        "sport": "Baseball",
                        "league": "MLB",
                        "market": "Run Line",
                        "market_type": "game",
                        "line": -1.5,
                        "home_team": "Philadelphia Phillies",
                        "away_team": "New York Mets",
                        "side_a": recommended,
                        "side_b": opposite,
                        "total_liquidity": 7400,
                    },
                }
            ],
        }


def test_standard_plan_prioritizes_oddsengine_quotes_over_prophetx_login() -> None:
    odds_engine = FakeOddsEngineOrderBook()
    prophetx = FakeProphetX()
    prophetx.provider_key = "prophetx"
    registry = SimpleNamespace(providers=(prophetx, odds_engine))
    settings = SimpleNamespace(sharp_money_advanced_orderbook_enabled=False)

    collector = build_sharp_money_collector(registry, settings)

    assert collector.prophetx is odds_engine
    assert collector.fallback_source is prophetx
    assert collector.advanced_orderbook_enabled is False


def test_oddsengine_rate_limit_falls_back_to_direct_novig_slate() -> None:
    odds_engine = FakeOddsEngineOrderBook()

    def rate_limited(*, limit=40):
        response = requests.Response()
        response.status_code = 429
        raise requests.HTTPError(response=response)

    odds_engine.sharp_money_quote_snapshot = rate_limited
    novig = FakeDirectNoVIGSlate()
    collector = SharpMoneyCollector(
        odds_engine,
        novig_provider=novig,
        local_control=False,
        advanced_orderbook_enabled=False,
    )

    payload = collector.payload(refresh_if_stale=True)

    assert novig.calls == 1
    assert payload["lastError"] is None
    assert payload["signalMode"] == "direct_order_book"
    assert payload["depthProviders"] == ["NoVIG"]
    assert payload["signalCount"] == 1
    signal = payload["signals"][0]
    assert signal["selection"] == "New York Yankees"
    assert signal["selectedLiquidity"] == 10000
    assert signal["oppositeLiquidity"] == 7000
    assert signal["crossedLiquidity"] == 3000
    assert signal["liquiditySources"] == {"novig": 3000}
    assert signal["transport"] == "Direct NoVIG net order book"


def test_crossed_liquidity_is_not_opposing_book_balance() -> None:
    crossed = _crossed_market_liquidity(
        [
            {
                "providerKey": "fanduel",
                "americanOdds": 110,
            },
            {
                "providerKey": "novig",
                "americanOdds": 105,
                "availableLiquidity": 7000,
                "oppositeAmericanOdds": -105,
                "oppositeAvailableLiquidity": 10000,
            },
        ]
    )

    assert crossed is not None
    assert crossed["liquidity"] == 10000
    assert crossed["sources"] == {"novig": 10000}
    assert crossed["retailBook"] == "fanduel"
    assert crossed["retailOdds"] == 110
    assert crossed["roiPercent"] > 0


def test_net_exchange_liquidity_subtracts_opposite_sides() -> None:
    net = _net_exchange_liquidity(
        [
            {
                "providerKey": "fanduel",
                "americanOdds": -105,
            },
            {
                "providerKey": "novig",
                "americanOdds": -105,
                "availableLiquidity": 6000,
                "oppositeAmericanOdds": 105,
                "oppositeAvailableLiquidity": 4000,
            },
            {
                "providerKey": "prophetx",
                "americanOdds": -105,
                "availableLiquidity": 4000,
                "oppositeAmericanOdds": 105,
                "oppositeAvailableLiquidity": 3000,
            },
        ]
    )

    assert net is not None
    assert net["selectedLiquidity"] == 10000
    assert net["oppositeLiquidity"] == 7000
    assert net["liquidity"] == 3000
    assert net["sources"] == {"novig": 2000, "prophetx": 1000}


def test_advanced_rejection_uses_direct_combined_exchange_order_books() -> None:
    odds_engine = FakeOddsEngineOrderBook()
    quote_fallback_calls = 0

    def reject_advanced(*, limit=40):
        response = requests.Response()
        response.status_code = 403
        raise requests.HTTPError(response=response)

    def reject_quote_fallback(*, limit=40):
        nonlocal quote_fallback_calls
        quote_fallback_calls += 1
        raise AssertionError("Direct order books must run before price fallback")

    odds_engine.sharp_money_snapshot = reject_advanced
    odds_engine.sharp_money_quote_snapshot = reject_quote_fallback
    comparisons = FakeComparisonProvider(
        "odds_engine",
        {
            "px:event-1:market-1:phillies": [
                FakeExecutionOption("fanduel", 130)
            ]
        },
    )
    novig = FakeDirectNoVIG()
    collector = SharpMoneyCollector(
        odds_engine,
        comparisons,
        fallback_source=FakeProphetX(),
        novig_provider=novig,
        local_control=False,
        automatic_refresh_seconds=30,
        advanced_orderbook_enabled=True,
    )

    payload = collector.payload(refresh_if_stale=True)

    assert quote_fallback_calls == 0
    assert novig.calls == 1
    assert payload["signalMode"] == "direct_order_book"
    assert payload["lastError"] is None
    assert payload["signalCount"] == 1
    signal = payload["signals"][0]
    assert signal["selection"] == "Philadelphia Phillies"
    assert signal["provider"] == "NoVIG + ProphetX"
    assert signal["crossedLiquidity"] == 800
    assert signal["selectedLiquidity"] == 2000
    assert signal["oppositeLiquidity"] == 1200
    assert signal["liquiditySources"] == {
        "prophetx": 200,
        "novig": 600,
    }
    assert signal["crossedSharpOdds"] == {
        "prophetx": -102,
        "novig": 125,
    }
    assert signal["crossedRetailOdds"] == 130
    assert signal["bestBook"] == "fanduel"
    assert signal["depthAvailable"] is True
    assert signal["transport"] == "Direct NoVIG + ProphetX net order books"


def test_odds_comparison_prefers_odds_engine_and_falls_back() -> None:
    primary = FakeComparisonProvider("odds_engine", fails=True)
    fallback = FakeComparisonProvider(
        "the_odds_api", {"signal-1": ["fallback-option"]}
    )
    provider = OddsComparisonFallback((primary, fallback))

    result = provider.screen_options_for_trades([{"id": "signal-1"}])

    assert result == {"signal-1": ["fallback-option"]}
    assert primary.calls == 1
    assert fallback.calls == 1
    assert provider.diagnostics()["provider"] == "odds_engine"
    assert provider.diagnostics()["fallbacks"] == ["the_odds_api"]


def test_collector_is_paused_without_any_provider_calls():
    provider = FakeProphetX()
    collector = SharpMoneyCollector(
        provider, poll_seconds=1, local_control=True
    )

    assert collector.status()["paused"] is True
    assert collector.payload()["signals"] == []
    assert provider.calls == 0


def test_play_collects_real_snapshot_and_pause_closes_request_gate():
    provider = FakeProphetX()
    collector = SharpMoneyCollector(
        provider, poll_seconds=1, local_control=True
    )
    accepted, _ = collector.play()
    assert accepted is True
    deadline = time.time() + 2
    while provider.calls < 1 and time.time() < deadline:
        time.sleep(0.01)
    collector.pause()
    calls_after_pause = provider.calls
    time.sleep(0.08)
    payload = collector.payload()
    collector.close()

    assert calls_after_pause >= 1
    assert provider.calls == calls_after_pause
    assert payload["paused"] is True
    assert payload["fabricatedData"] is False
    assert payload["executionEnabled"] is False
    assert payload["signals"][0]["event"] == (
        "New York Mets vs. Philadelphia Phillies"
    )
    assert payload["signals"][0]["provider"] == "ProphetX"


def test_local_control_is_disabled_in_serverless_mode():
    provider = FakeProphetX()
    collector = SharpMoneyCollector(provider, local_control=False)

    accepted, message = collector.play()

    assert accepted is False
    assert "refresh is automatic" in message
    assert provider.calls == 0


def test_oddsengine_advanced_orderbook_runs_automatically_with_full_depth():
    provider = FakeOddsEngineOrderBook()
    collector = SharpMoneyCollector(
        provider,
        local_control=False,
        automatic_refresh_seconds=30,
        advanced_orderbook_enabled=True,
    )

    payload = collector.payload(refresh_if_stale=True)
    cached = collector.payload(refresh_if_stale=True)

    assert provider.calls == 1
    assert payload["automatic"] is True
    assert payload["running"] is True
    assert payload["paused"] is False
    assert cached["signalCount"] == 1
    signal = payload["signals"][0]
    assert signal["provider"] == "NoVIG + ProphetX"
    assert signal["transport"] == (
        "OddsEngine NoVIG + ProphetX full order books"
    )
    assert signal["selection"] == "Philadelphia Phillies"
    assert signal["edgePercent"] == 4.2
    assert signal["whaleVolume"] == 8400
    assert signal["pressure"] == 0.042
    # OddsJam-style crossed liquidity is the amount available on the equal-
    # and-opposite sharp side. It is summed across exchanges, not netted
    # against the recommended side's $2,300.
    assert signal["crossedLiquidity"] == 2100
    assert signal["liquidity"] == 2100
    assert signal["counterLiquidity"] == 2300
    assert signal["totalLiquidity"] == 4400
    assert signal["liquiditySources"] == {"prophetx": 1400, "novig": 700}
    assert signal["crossedSharpOdds"] == {"prophetx": -125, "novig": -120}
    assert signal["crossedRetailOdds"] == 130
    assert signal["bestBook"] == "fanduel"
    assert signal["crossedRoiPercent"] > 0
    assert signal["depthAvailable"] is True
    prophetx = next(
        row
        for row in signal["comparisonLines"]
        if row["providerKey"] == "prophetx"
    )
    assert prophetx["americanOdds"] == 115
    assert prophetx["oppositeAmericanOdds"] == -125
    assert len(prophetx["orderBookLevels"]) == 2
    assert len(prophetx["oppositeOrderBookLevels"]) == 2
    assert {row["providerKey"] for row in signal["comparisonLines"]} >= {
        "prophetx",
        "novig",
        "fanduel",
        "pinnacle",
    }


def test_oddsengine_standard_plan_uses_exact_quote_consensus_without_advanced_probe():
    provider = FakeOddsEngineOrderBook()
    advanced_calls = 0

    def reject(*, limit=40):
        nonlocal advanced_calls
        advanced_calls += 1
        raise AssertionError("Standard mode must not call the Advanced endpoint")

    provider.sharp_money_snapshot = reject
    provider.sharp_money_quote_snapshot = lambda *, limit=40: {
        "observedAt": "2026-08-26T18:00:00+00:00",
        "limit": limit,
        "events": [
            {
                "id": "event-1",
                "sport_key": "baseball_mlb",
                "sport_title": "MLB",
                "commence_time": "2026-08-27T23:10:00+00:00",
                "home_team": "Philadelphia Phillies",
                "away_team": "New York Mets",
                "bookmakers": [
                    {
                        "key": "pinnacle",
                        "title": "Pinnacle",
                        "markets": [
                            {
                                "key": "h2h",
                                "last_update": "2026-08-26T17:59:58+00:00",
                                "outcomes": [
                                    {"name": "Philadelphia Phillies", "price": -125, "limit": 5000},
                                    {"name": "New York Mets", "price": 115, "limit": 5000},
                                ],
                            }
                        ],
                    },
                    {
                        "key": "prophetx",
                        "title": "ProphetX",
                        "markets": [
                            {
                                "key": "h2h",
                                "last_update": "2026-08-26T17:59:59+00:00",
                                "outcomes": [
                                    {"name": "Philadelphia Phillies", "price": -120, "limit": 1500},
                                    {"name": "New York Mets", "price": 110, "limit": 1400},
                                ],
                            }
                        ],
                    },
                    {
                        "key": "fanduel",
                        "title": "FanDuel",
                        "markets": [
                            {
                                "key": "h2h",
                                "last_update": "2026-08-26T17:59:57+00:00",
                                "outcomes": [
                                    {"name": "Philadelphia Phillies", "price": 105, "limit": 500},
                                    {"name": "New York Mets", "price": -110, "limit": 500},
                                ],
                            }
                        ],
                    },
                ],
            }
        ],
    }
    collector = SharpMoneyCollector(
        provider,
        local_control=False,
        automatic_refresh_seconds=30,
    )

    payload = collector.payload(refresh_if_stale=True)

    assert advanced_calls == 0
    assert payload["lastError"] is None
    assert payload["advancedOrderBookEnabled"] is False
    assert payload["signalMode"] == "quote_consensus"
    assert payload["signalCount"] == 1
    signal = payload["signals"][0]
    assert signal["transport"] == "OddsEngine REST sharp-consensus snapshot"
    assert signal["depthAvailable"] is False
    assert signal["crossedLiquidity"] is None
    assert signal["liquidity"] is None
    assert signal["inferenceOnly"] is True
    assert signal["selection"].startswith("Philadelphia Phillies")
    assert signal["pressure"] > 0
    assert signal["whaleVolume"] == 0
    assert {row["providerKey"] for row in signal["comparisonLines"]} == {
        "pinnacle",
        "prophetx",
        "fanduel",
    }

    direct_collector = SharpMoneyCollector(
        provider,
        novig_provider=FakeDirectNoVIG(),
        local_control=False,
        automatic_refresh_seconds=30,
    )
    direct_payload = direct_collector.payload(refresh_if_stale=True)

    assert direct_payload["signalMode"] == "direct_order_book"
    assert direct_payload["signalCount"] == 1
    assert direct_payload["depthProviders"] == ["NoVIG"]
    direct_signal = direct_payload["signals"][0]
    assert direct_signal["provider"] == "NoVIG"
    assert direct_signal["selection"].startswith("Philadelphia Phillies")
    assert direct_signal["crossedLiquidity"] == 600
    assert direct_signal["selectedLiquidity"] == 900
    assert direct_signal["oppositeLiquidity"] == 300
    assert direct_signal["bestBook"] == "fanduel"

    unmatched_collector = SharpMoneyCollector(
        provider,
        novig_provider=FakeDirectNoVIGSlate(),
        local_control=False,
        automatic_refresh_seconds=30,
    )
    unmatched_payload = unmatched_collector.payload(refresh_if_stale=True)

    assert unmatched_payload["signalMode"] == "direct_order_book"
    assert unmatched_payload["depthProviders"] == ["NoVIG"]
    assert unmatched_payload["signalCount"] == 1
    assert unmatched_payload["signals"][0]["crossedLiquidity"] == 3000


def test_oddsengine_advanced_plan_error_reports_safe_http_status():
    provider = FakeOddsEngineOrderBook()

    class BrokenFallback:
        provider_key = "prophetx"

        @staticmethod
        def diagnostics():
            raise RuntimeError("direct fallback diagnostics unavailable")

        @staticmethod
        def live_market_snapshot():
            raise ValueError("direct fallback unavailable")

    def reject(*, limit=40):
        response = requests.Response()
        response.status_code = 403
        raise requests.HTTPError(response=response)

    provider.sharp_money_snapshot = reject
    collector = SharpMoneyCollector(
        provider,
        fallback_source=BrokenFallback(),
        local_control=False,
        advanced_orderbook_enabled=True,
    )

    payload = collector.payload(refresh_if_stale=True)

    assert payload["signals"] == []
    assert payload["lastError"] == (
        "OddsEngine rejected Advanced order-book access (HTTP 403). "
        "Confirm this API key includes the Advanced plan."
    )


def test_oddsengine_standard_error_never_reports_an_advanced_upgrade():
    provider = FakeOddsEngineOrderBook()

    def reject(*, limit=40):
        response = requests.Response()
        response.status_code = 403
        raise requests.HTTPError(response=response)

    provider.sharp_money_quote_snapshot = reject
    collector = SharpMoneyCollector(provider, local_control=False)

    payload = collector.payload(refresh_if_stale=True)

    assert payload["advancedOrderBookEnabled"] is False
    assert payload["signals"] == []
    assert payload["lastError"] == (
        "OddsEngine rejected Sharp Money price-feed access (HTTP 403)."
    )
    assert "Advanced" not in payload["lastError"]
    assert "plan" not in payload["lastError"].lower()
