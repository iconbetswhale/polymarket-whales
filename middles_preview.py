"""Deterministic, provider-free fixtures for the IconLabs Middles preview."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sports_game_odds import SPORTS_GAME_ODDS_BOOKMAKERS, SPORTS_GAME_ODDS_LOGOS


def _outcome(name: str, price: int, point: float, description: str = "") -> dict:
    return {
        "name": name,
        "price": price,
        "point": point,
        "description": description,
    }


def _book(key: str, markets: list[tuple[str, list[dict]]], updated_at: str) -> dict:
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


def temporary_middle_events(now: datetime | None = None) -> list[dict]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    updated = now.isoformat()

    events = [
        {
            "id": "middle-preview-nfl-bills-ravens",
            "sport_key": "americanfootball_nfl",
            "sport_title": "NFL",
            "commence_time": (now + timedelta(hours=5)).isoformat(),
            "away_team": "Buffalo Bills",
            "home_team": "Baltimore Ravens",
            "bookmakers": [
                _book(
                    "draftkings",
                    [("alternate_totals", [_outcome("Over", -110, 42.5), _outcome("Under", -118, 42.5)])],
                    updated,
                ),
                _book(
                    "fanduel",
                    [("alternate_totals", [_outcome("Over", -122, 47.5), _outcome("Under", -110, 47.5)])],
                    updated,
                ),
                _book(
                    "betmgm",
                    [("alternate_totals", [_outcome("Over", -106, 43.5), _outcome("Under", -115, 46.5)])],
                    updated,
                ),
                _book(
                    "caesars",
                    [("alternate_totals", [_outcome("Over", -108, 42.5), _outcome("Under", -112, 47.5)])],
                    updated,
                ),
            ],
        },
        {
            "id": "middle-preview-nba-knicks-celtics",
            "sport_key": "basketball_nba",
            "sport_title": "NBA",
            "commence_time": (now + timedelta(hours=8, minutes=30)).isoformat(),
            "away_team": "New York Knicks",
            "home_team": "Boston Celtics",
            "bookmakers": [
                _book(
                    "fanatics",
                    [("alternate_spreads", [_outcome("New York Knicks", -105, 6.5), _outcome("Boston Celtics", -128, -6.5)])],
                    updated,
                ),
                _book(
                    "bet365",
                    [("alternate_spreads", [_outcome("New York Knicks", -130, 2.5), _outcome("Boston Celtics", -110, -2.5)])],
                    updated,
                ),
                _book(
                    "fanduel",
                    [("alternate_spreads", [_outcome("New York Knicks", -108, 5.5), _outcome("Boston Celtics", -112, -5.5)])],
                    updated,
                ),
                _book(
                    "draftkings",
                    [("alternate_spreads", [_outcome("New York Knicks", -115, 3.5), _outcome("Boston Celtics", -105, -3.5)])],
                    updated,
                ),
            ],
        },
        {
            "id": "middle-preview-wnba-liberty-aces",
            "sport_key": "basketball_wnba",
            "sport_title": "WNBA",
            "commence_time": (now + timedelta(days=1, hours=1)).isoformat(),
            "away_team": "New York Liberty",
            "home_team": "Las Vegas Aces",
            "bookmakers": [
                _book(
                    "hardrockbet",
                    [("player_points", [_outcome("Over", -115, 20.5, "Breanna Stewart"), _outcome("Under", -125, 20.5, "Breanna Stewart")])],
                    updated,
                ),
                _book(
                    "betonline",
                    [("player_points", [_outcome("Over", -130, 23.5, "Breanna Stewart"), _outcome("Under", 100, 23.5, "Breanna Stewart")])],
                    updated,
                ),
                _book(
                    "fanduel",
                    [("player_points", [_outcome("Over", -118, 21.5, "Breanna Stewart"), _outcome("Under", -108, 22.5, "Breanna Stewart")])],
                    updated,
                ),
            ],
        },
        {
            "id": "middle-preview-mlb-yankees-red-sox",
            "sport_key": "baseball_mlb",
            "sport_title": "MLB",
            "commence_time": (now + timedelta(days=1, hours=4)).isoformat(),
            "away_team": "New York Yankees",
            "home_team": "Boston Red Sox",
            "bookmakers": [
                _book(
                    "betrivers",
                    [("alternate_spreads", [_outcome("New York Yankees", -120, 2.5), _outcome("Boston Red Sox", -150, -2.5)])],
                    updated,
                ),
                _book(
                    "betonline",
                    [("alternate_spreads", [_outcome("New York Yankees", -145, 0.5), _outcome("Boston Red Sox", -105, -0.5)])],
                    updated,
                ),
                _book(
                    "fanatics",
                    [("alternate_spreads", [_outcome("New York Yankees", -112, 1.5), _outcome("Boston Red Sox", -118, -1.5)])],
                    updated,
                ),
            ],
        },
        {
            "id": "middle-preview-nfl-eagles-cowboys",
            "sport_key": "americanfootball_nfl",
            "sport_title": "NFL",
            "commence_time": (now + timedelta(days=2, hours=3)).isoformat(),
            "away_team": "Philadelphia Eagles",
            "home_team": "Dallas Cowboys",
            "bookmakers": [
                _book(
                    "draftkings",
                    [("alternate_totals", [_outcome("Over", 104, 51.5), _outcome("Under", -125, 51.5)])],
                    updated,
                ),
                _book(
                    "fanduel",
                    [("alternate_totals", [_outcome("Over", -125, 52.5), _outcome("Under", 101, 52.5)])],
                    updated,
                ),
                _book(
                    "caesars",
                    [("alternate_totals", [_outcome("Over", 100, 51.5), _outcome("Under", -102, 52.5)])],
                    updated,
                ),
            ],
        },
    ]
    return events
