"""Isolated preview fixtures for the Arbitrage product surface.

The rows deliberately use the live optimizer's normalized event contract while
remaining deterministic, free, and disconnected from provider quotas.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sports_game_odds import SPORTS_GAME_ODDS_BOOKMAKERS, SPORTS_GAME_ODDS_LOGOS


def _outcome(name: str, price: int, *, point=None, description: str = "") -> dict:
    return {
        "name": name,
        "price": price,
        "point": point,
        "description": description,
    }


def _book(
    key: str,
    markets: list[tuple[str, list[dict]]],
    *,
    updated_at: str,
) -> dict:
    return {
        "key": key,
        "title": SPORTS_GAME_ODDS_BOOKMAKERS.get(key, {}).get("name", key.title()),
        "logo": SPORTS_GAME_ODDS_LOGOS.get(key, ""),
        "link": f"https://example.com/{key}",
        "last_update": updated_at,
        "markets": [
            {
                "key": market_key,
                "last_update": updated_at,
                "link": f"https://example.com/{key}/{market_key}",
                "outcomes": outcomes,
            }
            for market_key, outcomes in markets
        ],
    }


def temporary_arbitrage_events(now: datetime | None = None) -> list[dict]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    updated = now.isoformat()

    yankees = "New York Yankees"
    red_sox = "Boston Red Sox"
    event_one_books = [
        _book(
            "fanduel",
            [
                ("h2h", [_outcome(yankees, 120), _outcome(red_sox, -132)]),
                ("totals", [_outcome("Over", 115, point=8.5), _outcome("Under", -125, point=8.5)]),
            ],
            updated_at=updated,
        ),
        _book(
            "draftkings",
            [
                ("h2h", [_outcome(yankees, 125), _outcome(red_sox, -135)]),
                ("totals", [_outcome("Over", 108, point=8.5), _outcome("Under", 105, point=8.5)]),
            ],
            updated_at=updated,
        ),
        _book(
            "caesars",
            [
                ("h2h", [_outcome(yankees, 118), _outcome(red_sox, -125)]),
                ("totals", [_outcome("Over", 110, point=8.5), _outcome("Under", -120, point=8.5)]),
            ],
            updated_at=updated,
        ),
        _book(
            "betmgm",
            [
                ("h2h", [_outcome(yankees, 115), _outcome(red_sox, -130)]),
                ("totals", [_outcome("Over", 105, point=8.5), _outcome("Under", -115, point=8.5)]),
            ],
            updated_at=updated,
        ),
        _book(
            "novig",
            [
                ("h2h", [_outcome(yankees, 121), _outcome(red_sox, -105)]),
                ("totals", [_outcome("Over", 102, point=8.5), _outcome("Under", -110, point=8.5)]),
            ],
            updated_at=updated,
        ),
    ]
    liberty = "New York Liberty"
    aces = "Las Vegas Aces"
    stewart = "Breanna Stewart"
    event_two_books = [
        _book(
            "fanduel",
            [
                ("spreads", [_outcome(liberty, 112, point=-4.5), _outcome(aces, -125, point=4.5)]),
                ("totals", [_outcome("Over", 120, point=166.5), _outcome("Under", -140, point=166.5)]),
                ("player_points", [_outcome("Over", 130, point=23.5, description=stewart), _outcome("Under", -150, point=23.5, description=stewart)]),
            ],
            updated_at=updated,
        ),
        _book(
            "draftkings",
            [
                ("spreads", [_outcome(liberty, 105, point=-4.5), _outcome(aces, 103, point=4.5)]),
                ("totals", [_outcome("Over", 105, point=166.5), _outcome("Under", 110, point=166.5)]),
                ("player_points", [_outcome("Over", 125, point=23.5, description=stewart), _outcome("Under", -105, point=23.5, description=stewart)]),
            ],
            updated_at=updated,
        ),
        _book(
            "caesars",
            [
                ("spreads", [_outcome(liberty, 100, point=-4.5), _outcome(aces, 108, point=4.5)]),
                ("totals", [_outcome("Over", 108, point=166.5), _outcome("Under", -118, point=166.5)]),
                ("player_points", [_outcome("Over", 118, point=23.5, description=stewart), _outcome("Under", -112, point=23.5, description=stewart)]),
            ],
            updated_at=updated,
        ),
        _book(
            "hardrockbet",
            [
                ("spreads", [_outcome(liberty, 102, point=-4.5), _outcome(aces, 101, point=4.5)]),
                ("totals", [_outcome("Over", 100, point=166.5), _outcome("Under", -110, point=166.5)]),
                ("player_points", [_outcome("Over", 120, point=23.5, description=stewart), _outcome("Under", -118, point=23.5, description=stewart)]),
            ],
            updated_at=updated,
        ),
    ]

    mets = "New York Mets"
    phillies = "Philadelphia Phillies"
    wheeler = "Zack Wheeler"
    event_three_books = [
        _book(
            "bet365",
            [
                ("spreads", [_outcome(mets, 106, point=1.5), _outcome(phillies, -118, point=-1.5)]),
                ("totals", [_outcome("Over", 115, point=7.5), _outcome("Under", -130, point=7.5)]),
                ("pitcher_strikeouts", [_outcome("Over", 145, point=6.5, description=wheeler), _outcome("Under", -155, point=6.5, description=wheeler)]),
            ],
            updated_at=updated,
        ),
        _book(
            "betonline",
            [
                ("spreads", [_outcome(mets, 102, point=1.5), _outcome(phillies, 104, point=-1.5)]),
                ("totals", [_outcome("Over", -120, point=7.5), _outcome("Under", 115, point=7.5)]),
                ("pitcher_strikeouts", [_outcome("Over", 138, point=6.5, description=wheeler), _outcome("Under", -110, point=6.5, description=wheeler)]),
            ],
            updated_at=updated,
        ),
        _book(
            "fanatics",
            [
                ("spreads", [_outcome(mets, 112, point=1.5), _outcome(phillies, -122, point=-1.5)]),
                ("totals", [_outcome("Over", 105, point=7.5), _outcome("Under", -120, point=7.5)]),
                ("pitcher_strikeouts", [_outcome("Over", 135, point=6.5, description=wheeler), _outcome("Under", -118, point=6.5, description=wheeler)]),
            ],
            updated_at=updated,
        ),
        _book(
            "betrivers",
            [
                ("spreads", [_outcome(mets, 104, point=1.5), _outcome(phillies, 107, point=-1.5)]),
                ("totals", [_outcome("Over", -110, point=7.5), _outcome("Under", 102, point=7.5)]),
                ("pitcher_strikeouts", [_outcome("Over", 130, point=6.5, description=wheeler), _outcome("Under", -120, point=6.5, description=wheeler)]),
            ],
            updated_at=updated,
        ),
    ]

    city = "Manchester City"
    chelsea = "Chelsea"
    event_four_books = [
        _book(
            "fanduel",
            [("h2h", [_outcome(city, 245), _outcome(chelsea, 125), _outcome("Draw", 300)])],
            updated_at=updated,
        ),
        _book(
            "draftkings",
            [("h2h", [_outcome(city, 225), _outcome(chelsea, 138), _outcome("Draw", 305)])],
            updated_at=updated,
        ),
        _book(
            "caesars",
            [("h2h", [_outcome(city, 230), _outcome(chelsea, 128), _outcome("Draw", 330)])],
            updated_at=updated,
        ),
        _book(
            "bet365",
            [("h2h", [_outcome(city, 235), _outcome(chelsea, 130), _outcome("Draw", 315)])],
            updated_at=updated,
        ),
    ]

    return [
        {
            "id": "preview-mlb-yankees-red-sox",
            "sport_key": "baseball_mlb",
            "sport_title": "MLB",
            "commence_time": (now + timedelta(hours=6)).isoformat(),
            "home_team": red_sox,
            "away_team": yankees,
            "bookmakers": event_one_books,
        },
        {
            "id": "preview-wnba-liberty-aces",
            "sport_key": "basketball_wnba",
            "sport_title": "WNBA",
            "commence_time": (now + timedelta(hours=9)).isoformat(),
            "home_team": aces,
            "away_team": liberty,
            "bookmakers": event_two_books,
        },
        {
            "id": "preview-mlb-mets-phillies",
            "sport_key": "baseball_mlb",
            "sport_title": "MLB",
            "commence_time": (now + timedelta(days=1, hours=2)).isoformat(),
            "home_team": phillies,
            "away_team": mets,
            "bookmakers": event_three_books,
        },
        {
            "id": "preview-epl-city-chelsea",
            "sport_key": "soccer_epl",
            "sport_title": "EPL",
            "commence_time": (now + timedelta(days=2, hours=3)).isoformat(),
            "home_team": chelsea,
            "away_team": city,
            "bookmakers": event_four_books,
        },
    ]
