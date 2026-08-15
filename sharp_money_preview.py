"""Isolated, non-production fixtures for Sharp Money visual review.

The preview payload is exposed only behind an explicit ``preview=1`` request.
It never starts a provider collector, consumes credits, writes tracker records,
or emits notifications.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


_LOGOS = {
    "prophetx": "/static/assets/providers/prophetx.ico",
    "novig": "/static/assets/providers/novig.png",
    "fourcx": "/static/assets/providers/4cx.png",
    "pinnacle": "https://www.pinnacle.com/favicon.ico",
    "betonlineag": "https://sports.betonline.ag/favicon.ico",
}

_NAMES = {
    "prophetx": "ProphetX",
    "novig": "NoVIG",
    "fourcx": "4CX",
    "pinnacle": "Pinnacle",
    "betonlineag": "BetOnline",
}


def _comparison(
    provider: str,
    american_odds: int,
    liquidity: float | None,
    market_limit: float | None = None,
) -> dict:
    return {
        "providerName": _NAMES[provider],
        "providerKey": provider,
        "americanOdds": american_odds,
        "availableLiquidity": liquidity,
        "marketLimit": market_limit,
        "logoUrl": _LOGOS[provider],
        "isAvailable": True,
        "matchingConfidence": "Exact",
        "deepLink": "",
    }


def _history(anchor: datetime, prices: tuple[int, ...]) -> list[dict]:
    return [
        {
            "observedAt": (anchor - timedelta(minutes=(len(prices) - index) * 7)).isoformat(),
            "americanOdds": price,
            "liquidity": 14000 + index * 2300,
            "pressure": 0.008 + index * 0.004,
        }
        for index, price in enumerate(prices)
    ]


def temporary_sharp_money_preview_payload(now: datetime | None = None) -> dict:
    """Return five synthetic signals shaped like the live collector response."""

    anchor = (now or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
    fixtures = (
        {
            "league": "MLB",
            "event": "New York Yankees vs. Boston Red Sox",
            "selection": "New York Yankees",
            "market": ("Moneyline", "moneyline", None),
            "odds": 128,
            "liquidity": 18400,
            "total": 73600,
            "delta": 6100,
            "probability_delta": 0.021,
            "pressure": 0.084,
            "confidence": 91,
            "prices": (112, 116, 121, 124, 128),
            "comparisons": (("novig", 131, 12600, None), ("prophetx", 128, 18400, None), ("fourcx", 125, 9200, None), ("pinnacle", 120, None, 150), ("betonlineag", 118, None, None)),
        },
        {
            "league": "WNBA",
            "event": "New York Liberty vs. Las Vegas Aces",
            "selection": "New York Liberty -4.5",
            "market": ("Game Spread", "spread", -4.5),
            "odds": -108,
            "liquidity": 22700,
            "total": 88400,
            "delta": -8400,
            "probability_delta": 0.016,
            "pressure": 0.067,
            "confidence": 87,
            "prices": (-115, -113, -111, -110, -108),
            "comparisons": (("prophetx", -108, 22700, None), ("novig", -110, 16800, None), ("fourcx", -112, 7500, None), ("pinnacle", -114, None, 500), ("betonlineag", -115, None, None)),
        },
        {
            "league": "MLB",
            "event": "Los Angeles Dodgers vs. San Francisco Giants",
            "selection": "Under 8.5",
            "market": ("Game Total", "game_total", 8.5),
            "odds": 102,
            "liquidity": 31500,
            "total": 121900,
            "delta": 11200,
            "probability_delta": 0.013,
            "pressure": 0.052,
            "confidence": 83,
            "prices": (-105, -103, -101, 100, 102),
            "comparisons": (("fourcx", 104, 9800, None), ("prophetx", 102, 31500, None), ("novig", 100, 24300, None), ("pinnacle", -103, None, 250), ("betonlineag", -105, None, None)),
        },
        {
            "league": "Tennis",
            "event": "Jannik Sinner vs. Frances Tiafoe",
            "selection": "Jannik Sinner -2.5",
            "market": ("Game Spread", "spread", -2.5),
            "odds": -115,
            "liquidity": 8900,
            "total": 34200,
            "delta": -1700,
            "probability_delta": 0.008,
            "pressure": 0.031,
            "confidence": 74,
            "prices": (-121, -120, -118, -117, -115),
            "comparisons": (("novig", -112, 6400, None), ("prophetx", -115, 8900, None), ("fourcx", -117, 3100, None), ("pinnacle", -118, None, 100), ("betonlineag", -120, None, None)),
        },
        {
            "league": "MLB",
            "event": "Cleveland Guardians vs. Detroit Tigers",
            "selection": "Detroit Tigers",
            "market": ("Moneyline", "moneyline", None),
            "odds": 136,
            "liquidity": 12700,
            "total": 51300,
            "delta": 900,
            "probability_delta": 0.002,
            "pressure": 0.006,
            "confidence": 62,
            "prices": (132, 134, 133, 135, 136),
            "comparisons": (("prophetx", 136, 12700, None), ("novig", 134, 10100, None), ("fourcx", 131, 4200, None), ("pinnacle", 128, None, 300), ("betonlineag", 125, None, None)),
        },
    )

    signals: list[dict] = []
    for index, fixture in enumerate(fixtures, start=1):
        market_name, market_kind, line = fixture["market"]
        starts_at = anchor + timedelta(hours=index + 1)
        opposing_selection = (
            "Over 8.5"
            if market_kind == "game_total"
            else fixture["event"].split(" vs. ")[0]
        )
        comparisons = [
            _comparison(provider, odds, liquidity, market_limit)
            for provider, odds, liquidity, market_limit in fixture["comparisons"]
        ]
        signals.append(
            {
                "id": f"sharp-money-preview-{index}",
                "provider": "ProphetX",
                "providerKey": "prophetx",
                "providerLogo": _LOGOS["prophetx"],
                "sport": fixture["league"],
                "league": fixture["league"],
                "event": fixture["event"],
                "homeTeam": fixture["event"].split(" vs. ")[-1],
                "awayTeam": opposing_selection,
                "startsAt": starts_at.isoformat(),
                "market": {
                    "id": f"preview-market-{index}",
                    "name": market_name,
                    "kind": market_kind,
                    "line": line,
                },
                "selection": fixture["selection"],
                "americanOdds": fixture["odds"],
                "liquidity": fixture["liquidity"],
                "totalLiquidity": fixture["total"],
                "liquidityDelta": fixture["delta"],
                "probabilityDelta": fixture["probability_delta"],
                "pressure": fixture["pressure"],
                "pressureLabel": "Flow detected" if fixture["pressure"] >= 0.01 else "Monitoring",
                "confidence": fixture["confidence"],
                "inferenceOnly": True,
                "previewOnly": True,
                "transport": "Visual preview fixture",
                "outcomes": [
                    {
                        "name": fixture["selection"],
                        "americanOdds": fixture["odds"],
                        "liquidity": fixture["liquidity"],
                    },
                    {
                        "name": opposing_selection,
                        "americanOdds": -110 if fixture["odds"] > 0 else 105,
                        "liquidity": max(2500, fixture["total"] - fixture["liquidity"]),
                    },
                ],
                "history": _history(anchor, fixture["prices"]),
                "comparisonLines": comparisons,
            }
        )

    return {
        "schemaVersion": "sharp-money-visual-preview-v1",
        "mode": "preview",
        "running": False,
        "paused": True,
        "previewOnly": True,
        "localControl": False,
        "readOnly": True,
        "executionEnabled": False,
        "notificationsEnabled": False,
        "trackerWritesEnabled": False,
        "fabricatedData": True,
        "startedAt": None,
        "lastSnapshotAt": anchor.isoformat(),
        "lastComparisonAt": anchor.isoformat(),
        "lastError": None,
        "cycles": 0,
        "pollSeconds": 0,
        "comparisonSeconds": 0,
        "signalCount": len(signals),
        "provider": {"provider": "prophetx", "configured": False},
        "comparisonProvider": {"provider": "preview", "configured": False},
        "signals": signals,
    }
