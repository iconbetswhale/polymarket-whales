from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone


SANDBOX_SIGNALS = [
    {
        "id": "sandbox-mlb-first-inning-total",
        "sport": "Baseball",
        "league": "MLB",
        "event": "Cleveland Guardians vs Tampa Bay Rays",
        "startsAt": "2026-07-26T16:15:00-04:00",
        "market": {"name": "1st Inning Total Runs", "period": "1st inning", "line": 0.5},
        "recommended": {
            "side": "Under 0.5", "book": "Caesars", "americanOdds": -122,
            "fairAmericanOdds": -123, "fairProbability": 0.55180, "edge": 0.0023,
            "bookLimit": 250, "riskCapFraction": 0.015, "referenceLiquidityCap": 82.7,
        },
        "sharpLiquidity": {
            "side": "Over 0.5", "total": 1654, "averageAmericanOdds": 123,
            "bestAmericanOdds": 125, "persistenceSeconds": 184, "confidence": 92,
            "sources": [
                {"provider": "NoVIG", "odds": 125, "liquidity": 952},
                {"provider": "ProphetX", "odds": 120, "liquidity": 702},
            ],
        },
        "prices": [
            {"book": "Pinnacle", "leftOdds": -143, "rightOdds": 120, "limit": 250},
            {"book": "FanDuel", "leftOdds": -136, "rightOdds": 106},
            {"book": "NoVIG", "leftOdds": -141, "rightOdds": 125, "liquidity": 679},
            {"book": "ProphetX", "leftOdds": -157, "rightOdds": 120, "liquidity": 776},
            {"book": "DraftKings", "leftOdds": -125, "rightOdds": 105},
            {"book": "Caesars", "leftOdds": -122, "rightOdds": 103, "recommended": True},
            {"book": "BetOnline", "leftOdds": -140, "rightOdds": 113, "limit": 125},
        ],
        "warnings": ["Low-limit player market", "Price can move quickly"],
    },
    {
        "id": "sandbox-wnba-spread",
        "sport": "Basketball",
        "league": "WNBA",
        "event": "New York Liberty vs Atlanta Dream",
        "startsAt": "2026-07-26T18:00:00-04:00",
        "market": {"name": "Full Game Spread", "period": "Full game", "line": -4.5},
        "recommended": {
            "side": "New York Liberty -4.5", "book": "BetOnline", "americanOdds": -110,
            "fairAmericanOdds": -118, "fairProbability": 0.54128, "edge": 0.0334,
            "bookLimit": 1000, "riskCapFraction": 0.015, "referenceLiquidityCap": 210,
        },
        "sharpLiquidity": {
            "side": "Atlanta Dream +4.5", "total": 4280, "averageAmericanOdds": 117,
            "bestAmericanOdds": 121, "persistenceSeconds": 311, "confidence": 96,
            "sources": [
                {"provider": "ProphetX", "odds": 121, "liquidity": 2430},
                {"provider": "NoVIG", "odds": 114, "liquidity": 1850},
            ],
        },
        "prices": [
            {"book": "Pinnacle", "leftOdds": -116, "rightOdds": 104, "limit": 2500},
            {"book": "Circa", "leftOdds": -115, "rightOdds": 105, "limit": 2000},
            {"book": "FanDuel", "leftOdds": -112, "rightOdds": -108},
            {"book": "DraftKings", "leftOdds": -112, "rightOdds": -108},
            {"book": "BetOnline", "leftOdds": -110, "rightOdds": -110, "recommended": True},
            {"book": "NoVIG", "leftOdds": -119, "rightOdds": 114, "liquidity": 1850},
            {"book": "ProphetX", "leftOdds": -121, "rightOdds": 121, "liquidity": 2430},
        ],
        "warnings": [],
    },
    {
        "id": "sandbox-tennis-player-prop",
        "sport": "Tennis",
        "league": "ATP",
        "event": "Toronto Masters: Ben Shelton vs Alex de Minaur",
        "startsAt": "2026-07-26T19:30:00-04:00",
        "market": {"name": "Ben Shelton Total Aces", "period": "Full match", "line": 9.5},
        "recommended": {
            "side": "Over 9.5", "book": "DraftKings", "americanOdds": 105,
            "fairAmericanOdds": -105, "fairProbability": 0.51220, "edge": 0.0490,
            "bookLimit": 150, "riskCapFraction": 0.015, "referenceLiquidityCap": 145,
        },
        "sharpLiquidity": {
            "side": "Under 9.5", "total": 2890, "averageAmericanOdds": 104,
            "bestAmericanOdds": 108, "persistenceSeconds": 97, "confidence": 87,
            "sources": [
                {"provider": "NoVIG", "odds": 108, "liquidity": 1710},
                {"provider": "ProphetX", "odds": 101, "liquidity": 1180},
            ],
        },
        "prices": [
            {"book": "Pinnacle", "leftOdds": -112, "rightOdds": -102, "limit": 250},
            {"book": "FanDuel", "leftOdds": 100, "rightOdds": -130},
            {"book": "DraftKings", "leftOdds": 105, "rightOdds": -135, "recommended": True},
            {"book": "BetOnline", "leftOdds": -102, "rightOdds": -128, "limit": 150},
            {"book": "NoVIG", "leftOdds": -108, "rightOdds": 108, "liquidity": 1710},
            {"book": "ProphetX", "leftOdds": -101, "rightOdds": 101, "liquidity": 1180},
        ],
        "warnings": ["Player-prop model", "Lower market limits"],
    },
    {
        "id": "sandbox-soccer-total",
        "sport": "Soccer",
        "league": "MLS",
        "event": "Inter Miami CF vs New York City FC",
        "startsAt": "2026-07-26T20:30:00-04:00",
        "market": {"name": "Full Game Total Goals", "period": "Full game", "line": 2.5},
        "recommended": {
            "side": "Over 2.5", "book": "FanDuel", "americanOdds": -108,
            "fairAmericanOdds": -115, "fairProbability": 0.53488, "edge": 0.0307,
            "bookLimit": 750, "riskCapFraction": 0.015, "referenceLiquidityCap": 190,
        },
        "sharpLiquidity": {
            "side": "Under 2.5", "total": 3760, "averageAmericanOdds": 114,
            "bestAmericanOdds": 118, "persistenceSeconds": 226, "confidence": 91,
            "sources": [
                {"provider": "ProphetX", "odds": 118, "liquidity": 2110},
                {"provider": "NoVIG", "odds": 110, "liquidity": 1650},
            ],
        },
        "prices": [
            {"book": "Pinnacle", "leftOdds": -114, "rightOdds": 102, "limit": 1500},
            {"book": "FanDuel", "leftOdds": -108, "rightOdds": -112, "recommended": True},
            {"book": "DraftKings", "leftOdds": -110, "rightOdds": -110},
            {"book": "BetOnline", "leftOdds": -112, "rightOdds": -108, "limit": 750},
            {"book": "NoVIG", "leftOdds": -110, "rightOdds": 110, "liquidity": 1650},
            {"book": "ProphetX", "leftOdds": -118, "rightOdds": 118, "liquidity": 2110},
        ],
        "warnings": [],
    },
]


def sandbox_payload() -> dict:
    """Return provider-shaped sample data without touching any live feed."""
    return {
        "schemaVersion": "sharp-money-signal-v1",
        "mode": "sandbox",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "executionEnabled": False,
        "externalLinksEnabled": False,
        "notificationsEnabled": False,
        "fabricatedData": True,
        "creditUsage": 0,
        "settings": {
            "bankroll": 10000,
            "kellyMultiplier": 0.5,
            "maximumBetFraction": 0.015,
        },
        "providers": [
            {"key": "novig", "name": "NoVIG", "status": "simulated"},
            {"key": "prophetx", "name": "ProphetX", "status": "simulated"},
            {"key": "sportsbooks", "name": "Sportsbook consensus", "status": "simulated"},
        ],
        "signals": deepcopy(SANDBOX_SIGNALS),
    }
