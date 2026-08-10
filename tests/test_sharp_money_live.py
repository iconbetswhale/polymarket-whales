from __future__ import annotations

import time

from sharp_money_live import SharpMoneyCollector


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
