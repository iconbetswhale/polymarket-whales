"""Temporary read-only Sportsbook Screen fixtures for visual QA.

The payload is available only behind an explicit ``preview=1`` request. It
never starts provider collectors, consumes sportsbook credits, or writes to a
tracker.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


PROVIDERS = (
    {
        "key": "polymarket",
        "name": "Polymarket",
        "logoUrl": "https://polymarket.com/icons/favicon-32x32.png",
        "source": "preview",
    },
    {
        "key": "kalshi",
        "name": "Kalshi",
        "logoUrl": "/static/assets/providers/kalshi.png",
        "source": "preview",
    },
    {
        "key": "4cx",
        "name": "4CX",
        "logoUrl": "/static/assets/providers/4cx.png",
        "source": "preview",
    },
    {
        "key": "oddsapi__novig",
        "name": "NoVIG",
        "logoUrl": "/static/assets/providers/novig.png",
        "source": "preview",
    },
)


def _implied_probability(american_odds: int) -> float:
    if american_odds > 0:
        return round(100 / (american_odds + 100), 4)
    return round(abs(american_odds) / (abs(american_odds) + 100), 4)


def _display_odds(american_odds: int) -> str:
    return f"+{american_odds}" if american_odds > 0 else str(american_odds)


def _options(base_odds: int, liquidity: int, seed: int) -> list[dict]:
    adjustments = (2, 0, -2, 4)
    options = []
    for index, provider in enumerate(PROVIDERS):
        american_odds = base_odds + adjustments[(index + seed) % len(adjustments)]
        probability = _implied_probability(american_odds)
        options.append(
            {
                "providerName": provider["name"],
                "providerKey": provider["key"],
                "logoUrl": provider["logoUrl"],
                "displayOdds": _display_odds(american_odds),
                "americanOdds": american_odds,
                "contractPrice": probability,
                "bestExecutablePrice": probability,
                "availableLiquidity": liquidity + (index * 1300) + (seed * 240),
                "deepLink": "",
                "isAvailable": True,
                "matchingConfidence": "Exact",
                "marketStatus": "OPEN",
                "quoteFreshness": "fresh",
                "quoteAgeSeconds": 8 + index,
                "isStale": False,
            }
        )
    return options


def _market_rows(
    *,
    event_id: str,
    event_title: str,
    sport: str,
    league: str,
    starts_at: datetime,
    kind: str,
    market_title: str,
    outcomes: tuple[str, str],
    odds: tuple[int, int],
    liquidity: int,
    line: float | tuple[float, float] | None = None,
    seed: int = 0,
) -> list[dict]:
    market_id = f"{event_id}-{kind}-{str(line).replace('.', '-') if line is not None else 'main'}"
    rows = []
    for index, outcome in enumerate(outcomes):
        row_line = line[index] if isinstance(line, tuple) else line
        rows.append(
            {
                "id": f"{market_id}-{index + 1}",
                "event_id": event_id,
                "event_title": event_title,
                "market_id": market_id,
                "condition_id": market_id,
                "market_title": market_title,
                "sports_market_type": market_title,
                "market_line": row_line,
                "outcome": outcome,
                "event_date_et": starts_at.isoformat(),
                "event_start_time": starts_at.isoformat(),
                "resolution_time": starts_at.isoformat(),
                "schedule_date_et": starts_at.date().isoformat(),
                "category": sport,
                "canonical_sport_id": sport.upper(),
                "league": league,
                "canonical_league_id": league,
                "is_sports": True,
                "previewOnly": True,
                "card": {"recommended_amount": 0},
                "recommendation": {"recommended_amount": 0},
                "executionOptions": _options(
                    odds[index], liquidity + (index * 1700), seed + index
                ),
            }
        )
    return rows


def temporary_odds_screen_preview_payload(now: datetime | None = None) -> dict:
    base = (now or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
    events = (
        {
            "event_id": "preview-yankees-red-sox",
            "event_title": "New York Yankees vs Boston Red Sox",
            "sport": "Baseball",
            "league": "MLB",
            "starts_at": base + timedelta(hours=2),
            "moneyline": (("New York Yankees", "Boston Red Sox"), (118, -126)),
            "spread": (("New York Yankees", "Boston Red Sox"), (-108, -112), (-1.5, 1.5)),
            "total": (("Over", "Under"), (-105, -115), 8.5),
        },
        {
            "event_id": "preview-liberty-aces",
            "event_title": "New York Liberty vs Las Vegas Aces",
            "sport": "Basketball",
            "league": "WNBA",
            "starts_at": base + timedelta(hours=3),
            "moneyline": (("New York Liberty", "Las Vegas Aces"), (-154, 138)),
            "spread": (("New York Liberty", "Las Vegas Aces"), (-110, -110), (-3.5, 3.5)),
            "total": (("Over", "Under"), (-108, -112), 162.5),
        },
        {
            "event_id": "preview-sinner-tiafoe",
            "event_title": "Jannik Sinner vs Frances Tiafoe",
            "sport": "Tennis",
            "league": "ATP",
            "starts_at": base + timedelta(hours=4),
            "moneyline": (("Jannik Sinner", "Frances Tiafoe"), (-158, 142)),
            "spread": (("Jannik Sinner", "Frances Tiafoe"), (-112, -108), (-2.5, 2.5)),
            "total": (("Over", "Under"), (-110, -110), 22.5),
        },
    )

    rows: list[dict] = []
    for event_index, event in enumerate(events):
        common = {
            "event_id": event["event_id"],
            "event_title": event["event_title"],
            "sport": event["sport"],
            "league": event["league"],
            "starts_at": event["starts_at"],
        }
        moneyline_outcomes, moneyline_odds = event["moneyline"]
        rows.extend(
            _market_rows(
                **common,
                kind="moneyline",
                market_title="Moneyline",
                outcomes=moneyline_outcomes,
                odds=moneyline_odds,
                liquidity=12600 + (event_index * 2200),
                seed=event_index,
            )
        )
        spread_outcomes, spread_odds, spread_line = event["spread"]
        rows.extend(
            _market_rows(
                **common,
                kind="spread",
                market_title="Run Line / Spread",
                outcomes=spread_outcomes,
                odds=spread_odds,
                liquidity=9800 + (event_index * 1800),
                line=spread_line,
                seed=event_index + 2,
            )
        )
        total_outcomes, total_odds, total_line = event["total"]
        rows.extend(
            _market_rows(
                **common,
                kind="game-total",
                market_title="Game Total",
                outcomes=total_outcomes,
                odds=total_odds,
                liquidity=8400 + (event_index * 1400),
                line=total_line,
                seed=event_index + 4,
            )
        )

    return {
        "data": rows,
        "providers": list(PROVIDERS),
        "filters": {"sport": "", "league": "", "market": ""},
        "paused": False,
        "previewOnly": True,
        "fabricatedData": True,
        "trackerWritesEnabled": False,
        "providerRequestsEnabled": False,
        "message": "Temporary visual fixtures only.",
    }
