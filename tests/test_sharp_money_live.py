from __future__ import annotations

import time

import requests

from sharp_money_live import OddsComparisonFallback, SharpMoneyCollector


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
                                "selection_id": "phillies",
                                "name": "Philadelphia Phillies",
                                "odds": self.price,
                                "liquidity": self.liquidity,
                            },
                            {
                                "selection_id": "mets",
                                "name": "New York Mets",
                                "odds": 1.85,
                                "liquidity": 900,
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
                    "odds_american": 105,
                    "odds_decimal": 2.05,
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
    assert "local-only" in message
    assert provider.calls == 0


def test_oddsengine_advanced_orderbook_runs_automatically_with_full_depth():
    provider = FakeOddsEngineOrderBook()
    collector = SharpMoneyCollector(
        provider,
        local_control=False,
        automatic_refresh_seconds=30,
    )

    payload = collector.payload(refresh_if_stale=True)
    cached = collector.payload(refresh_if_stale=True)

    assert provider.calls == 1
    assert payload["automatic"] is True
    assert payload["running"] is True
    assert payload["paused"] is False
    assert cached["signalCount"] == 1
    signal = payload["signals"][0]
    assert signal["provider"] == "ProphetX"
    assert signal["transport"] == "OddsEngine ProphetX full order book"
    assert signal["selection"] == "Philadelphia Phillies"
    assert signal["edgePercent"] == 4.2
    assert signal["whaleVolume"] == 8400
    assert signal["pressure"] == 0.042
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


def test_oddsengine_advanced_plan_error_reports_safe_http_status():
    provider = FakeOddsEngineOrderBook()

    class BrokenFallback:
        provider_key = "prophetx"

        @staticmethod
        def diagnostics():
            return {"provider": "prophetx", "configured": True}

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
    )

    payload = collector.payload(refresh_if_stale=True)

    assert payload["signals"] == []
    assert payload["lastError"] == (
        "OddsEngine rejected Advanced order-book access (HTTP 403). "
        "Confirm this API key includes the Advanced plan."
    )
