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
        "key": "oddsapi__betmgm",
        "name": "BetMGM",
        "logoUrl": "/static/assets/sportsbooks/betmgm.png",
        "source": "preview",
    },
    {
        "key": "oddsapi__draftkings",
        "name": "DraftKings",
        "logoUrl": "/static/assets/sportsbooks/draftkings.png",
        "source": "preview",
    },
    {
        "key": "oddsapi__fanduel",
        "name": "FanDuel",
        "logoUrl": "/static/assets/sportsbooks/fanduel.png",
        "source": "preview",
    },
    {
        "key": "oddsapi__novig",
        "name": "NoVIG",
        "logoUrl": "/static/assets/providers/novig.png",
        "source": "preview",
    },
    {
        "key": "oddsapi__caesars",
        "name": "Caesars",
        "logoUrl": "/static/assets/sportsbooks/caesars-sportsbook.png",
        "source": "preview",
    },
    {
        "key": "oddsapi__pinnacle",
        "name": "Pinnacle",
        "logoUrl": "/static/assets/providers/pinnacle.png",
        "source": "preview",
    },
)

PARTICIPANT_LOGOS = {
    "Atlanta Braves": "https://a.espncdn.com/i/teamlogos/mlb/500/atl.png",
    "Milwaukee Brewers": "https://a.espncdn.com/i/teamlogos/mlb/500/mil.png",
    "St. Louis Cardinals": "https://a.espncdn.com/i/teamlogos/mlb/500/stl.png",
    "Philadelphia Phillies": "https://a.espncdn.com/i/teamlogos/mlb/500/phi.png",
    "Toronto Blue Jays": "https://a.espncdn.com/i/teamlogos/mlb/500/tor.png",
    "New York Yankees": "https://a.espncdn.com/i/teamlogos/mlb/500/nyy.png",
    "Washington Nationals": "https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png",
    "Miami Marlins": "https://a.espncdn.com/i/teamlogos/mlb/500/mia.png",
    "San Francisco Giants": "https://a.espncdn.com/i/teamlogos/mlb/500/sf.png",
    "Boston Red Sox": "https://a.espncdn.com/i/teamlogos/mlb/500/bos.png",
    "Tampa Bay Rays": "https://a.espncdn.com/i/teamlogos/mlb/500/tb.png",
    "Baltimore Orioles": "https://a.espncdn.com/i/teamlogos/mlb/500/bal.png",
    "Los Angeles Dodgers": "https://a.espncdn.com/i/teamlogos/mlb/500/lad.png",
    "Chicago Cubs": "https://a.espncdn.com/i/teamlogos/mlb/500/chc.png",
    "New York Mets": "https://a.espncdn.com/i/teamlogos/mlb/500/nym.png",
    "Seattle Mariners": "https://a.espncdn.com/i/teamlogos/mlb/500/sea.png",
    "Houston Astros": "https://a.espncdn.com/i/teamlogos/mlb/500/hou.png",
    "Texas Rangers": "https://a.espncdn.com/i/teamlogos/mlb/500/tex.png",
    "Cleveland Guardians": "https://a.espncdn.com/i/teamlogos/mlb/500/cle.png",
    "Detroit Tigers": "https://a.espncdn.com/i/teamlogos/mlb/500/det.png",
    "Cincinnati Reds": "https://a.espncdn.com/i/teamlogos/mlb/500/cin.png",
    "Pittsburgh Pirates": "https://a.espncdn.com/i/teamlogos/mlb/500/pit.png",
    "San Diego Padres": "https://a.espncdn.com/i/teamlogos/mlb/500/sd.png",
    "Minnesota Twins": "https://a.espncdn.com/i/teamlogos/mlb/500/min.png",
    "Athletics": "https://a.espncdn.com/i/teamlogos/mlb/500/oak.png",
    "Kansas City Royals": "https://a.espncdn.com/i/teamlogos/mlb/500/kc.png",
    "Arizona Diamondbacks": "https://a.espncdn.com/i/teamlogos/mlb/500/ari.png",
    "Colorado Rockies": "https://a.espncdn.com/i/teamlogos/mlb/500/col.png",
    "Chicago White Sox": "https://a.espncdn.com/i/teamlogos/mlb/500/chw.png",
    "Los Angeles Angels": "https://a.espncdn.com/i/teamlogos/mlb/500/laa.png",
}


def _implied_probability(american_odds: int) -> float:
    if american_odds > 0:
        return round(100 / (american_odds + 100), 4)
    return round(abs(american_odds) / (abs(american_odds) + 100), 4)


def _display_odds(american_odds: int) -> str:
    return f"+{american_odds}" if american_odds > 0 else str(american_odds)


def _options(base_odds: int, liquidity: int, seed: int) -> list[dict]:
    adjustments = (2, 0, -2, 4, -1, 3, -3, 1, -4)
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
    player_name: str = "",
    seed: int = 0,
) -> list[dict]:
    market_id = f"{event_id}-{kind}-{str(line).replace('.', '-') if line is not None else 'main'}"
    event_participants = tuple(part.strip() for part in event_title.split(" vs ", 1))
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
                "participant_logos": {
                    participant: PARTICIPANT_LOGOS[participant]
                    for participant in (*event_participants, *outcomes)
                    if participant in PARTICIPANT_LOGOS
                },
                "card": {"recommended_amount": 0},
                "recommendation": {"recommended_amount": 0},
                "executionOptions": _options(
                    odds[index], liquidity + (index * 1700), seed + index
                ),
            }
        )
        if player_name:
            rows[-1]["player_name"] = player_name
    return rows


def temporary_odds_screen_preview_payload(now: datetime | None = None) -> dict:
    base = (now or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
    base_matchups = (
        ("braves-brewers", "Atlanta Braves", "Milwaukee Brewers", (133, -134), 8.5, "Ronald Acuña Jr."),
        ("cardinals-phillies", "St. Louis Cardinals", "Philadelphia Phillies", (233, -239), 8.0, "Bryce Harper"),
        ("blue-jays-yankees", "Toronto Blue Jays", "New York Yankees", (187, -190), 8.5, "Aaron Judge"),
        ("nationals-marlins", "Washington Nationals", "Miami Marlins", (140, -138), 7.5, "James Wood"),
        ("giants-red-sox", "San Francisco Giants", "Boston Red Sox", (163, -166), 9.0, "Rafael Devers"),
        ("rays-orioles", "Tampa Bay Rays", "Baltimore Orioles", (118, -118), 8.0, "Gunnar Henderson"),
        ("dodgers-cubs", "Los Angeles Dodgers", "Chicago Cubs", (-146, 132), 9.5, "Shohei Ohtani"),
        ("mets-mariners", "New York Mets", "Seattle Mariners", (-122, 108), 7.5, "Francisco Lindor"),
        ("astros-rangers", "Houston Astros", "Texas Rangers", (115, -129), 8.5, "Corey Seager"),
        ("guardians-tigers", "Cleveland Guardians", "Detroit Tigers", (104, -116), 7.0, "José Ramírez"),
        ("reds-pirates", "Cincinnati Reds", "Pittsburgh Pirates", (-108, -102), 9.0, "Elly De La Cruz"),
        ("padres-twins", "San Diego Padres", "Minnesota Twins", (-132, 119), 8.0, "Fernando Tatis Jr."),
        ("athletics-royals", "Athletics", "Kansas City Royals", (124, -138), 8.5, "Bobby Witt Jr."),
        ("diamondbacks-rockies", "Arizona Diamondbacks", "Colorado Rockies", (-135, 121), 10.5, "Corbin Carroll"),
        ("white-sox-angels", "Chicago White Sox", "Los Angeles Angels", (142, -157), 8.0, "Mike Trout"),
    )
    events = tuple(
        {
            "event_id": f"preview-{slug}-slate-{slate_index + 1}",
            "event_title": f"{away} vs {home}",
            "sport": "Baseball",
            "league": "MLB",
            "starts_at": base
            + timedelta(
                days=slate_index,
                hours=2 + game_index,
                minutes=(game_index % 3) * 10,
            ),
            "teams": (away, home),
            "moneyline_odds": (
                moneyline_odds[0] + (3 * slate_index),
                moneyline_odds[1] - (3 * slate_index),
            ),
            "total_line": total_line + (0.5 * slate_index),
            "player_name": player_name,
        }
        for slate_index in range(2)
        for game_index, (
            slug,
            away,
            home,
            moneyline_odds,
            total_line,
            player_name,
        ) in enumerate(base_matchups)
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
        rows.extend(
            _market_rows(
                **common,
                kind="moneyline",
                market_title="Moneyline",
                outcomes=event["teams"],
                odds=event["moneyline_odds"],
                liquidity=12600 + (event_index * 2200),
                seed=event_index,
            )
        )

        # Keep the full 30-game board for the default Moneyline view while
        # limiting the secondary preview markets to a representative slate.
        # This keeps the production fixture response comfortably below the
        # serverless response ceiling without leaving any tab empty.
        if event_index >= 8:
            continue

        spread_line = (1.5, -1.5) if event["moneyline_odds"][0] > 0 else (-1.5, 1.5)
        rows.extend(
            _market_rows(
                **common,
                kind="spread",
                market_title="Run Line / Spread",
                outcomes=event["teams"],
                odds=(-108 - (event_index % 3), -112 + (event_index % 3)),
                liquidity=9800 + (event_index * 1800),
                line=spread_line,
                seed=event_index + 2,
            )
        )
        alternate_spread_line = (2.5, -2.5) if spread_line[0] > 0 else (-2.5, 2.5)
        rows.extend(
            _market_rows(
                **common,
                kind="alternate-spread",
                market_title="Alternate Spread",
                outcomes=event["teams"],
                odds=(-104 - (event_index % 4), -116 + (event_index % 4)),
                liquidity=9100 + (event_index * 1500),
                line=alternate_spread_line,
                seed=event_index + 3,
            )
        )
        rows.extend(
            _market_rows(
                **common,
                kind="game-total",
                market_title="Game Total",
                outcomes=("Over", "Under"),
                odds=(-105 - (event_index % 4), -115 + (event_index % 4)),
                liquidity=8400 + (event_index * 1400),
                line=event["total_line"],
                seed=event_index + 4,
            )
        )
        rows.extend(
            _market_rows(
                **common,
                kind="alternate-total",
                market_title="Alternate Total",
                outcomes=("Over", "Under"),
                odds=(-102 - (event_index % 5), -118 + (event_index % 5)),
                liquidity=7600 + (event_index * 1200),
                line=event["total_line"] + 1.0,
                seed=event_index + 5,
            )
        )
        rows.extend(
            _market_rows(
                **common,
                kind="player-hits",
                market_title="Player Hits",
                outcomes=("Over", "Under"),
                odds=(104 + (event_index % 5), -124 + (event_index % 5)),
                liquidity=6800 + (event_index * 1000),
                line=1.5,
                player_name=event["player_name"],
                seed=event_index + 6,
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

