"""Isolated, realistic fixture prices for the Low Hold product preview."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sports_game_odds import SPORTS_GAME_ODDS_BOOKMAKERS


def _outcome(name: str, price: int, point=None, description: str = "") -> dict:
    return {
        "name": name,
        "price": price,
        "point": point,
        "description": description,
    }


def _market(key: str, outcomes: list[dict], stamp: str) -> dict:
    return {"key": key, "last_update": stamp, "outcomes": outcomes}


def _book(key: str, markets: list[dict], stamp: str) -> dict:
    return {
        "key": key,
        "title": SPORTS_GAME_ODDS_BOOKMAKERS[key]["name"],
        "last_update": stamp,
        "link": f"https://example.com/{key}",
        "markets": markets,
    }


def temporary_low_hold_events(now: datetime | None = None) -> list[dict]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = (now - timedelta(seconds=12)).isoformat()

    return [
        {
            "id": "low-hold-mlb-moneyline",
            "sport_key": "baseball_mlb",
            "sport_title": "MLB",
            "commence_time": (now + timedelta(hours=2, minutes=15)).isoformat(),
            "away_team": "Boston Red Sox",
            "home_team": "New York Yankees",
            "bookmakers": [
                _book("draftkings", [_market("h2h", [_outcome("Boston Red Sox", 104), _outcome("New York Yankees", -110)], stamp)], stamp),
                _book("fanduel", [_market("h2h", [_outcome("Boston Red Sox", 100), _outcome("New York Yankees", -105)], stamp)], stamp),
                _book("caesars", [_market("h2h", [_outcome("Boston Red Sox", 102), _outcome("New York Yankees", -108)], stamp)], stamp),
            ],
        },
        {
            "id": "low-hold-wnba-spread",
            "sport_key": "basketball_wnba",
            "sport_title": "WNBA",
            "commence_time": (now + timedelta(hours=4, minutes=40)).isoformat(),
            "away_team": "Las Vegas Aces",
            "home_team": "New York Liberty",
            "bookmakers": [
                _book("betmgm", [_market("spreads", [_outcome("Las Vegas Aces", -108, 3.5), _outcome("New York Liberty", -112, -3.5)], stamp)], stamp),
                _book("fanatics", [_market("spreads", [_outcome("Las Vegas Aces", -112, 3.5), _outcome("New York Liberty", 106, -3.5)], stamp)], stamp),
                _book("fanduel", [_market("spreads", [_outcome("Las Vegas Aces", -110, 3.5), _outcome("New York Liberty", 102, -3.5)], stamp)], stamp),
            ],
        },
        {
            "id": "low-hold-mlb-total",
            "sport_key": "baseball_mlb",
            "sport_title": "MLB",
            "commence_time": (now + timedelta(hours=5, minutes=10)).isoformat(),
            "away_team": "Chicago Cubs",
            "home_team": "Milwaukee Brewers",
            "bookmakers": [
                _book("bet365", [_market("totals", [_outcome("Over", 102, 8.5), _outcome("Under", -110, 8.5)], stamp)], stamp),
                _book("pinnacle", [_market("totals", [_outcome("Over", -104, 8.5), _outcome("Under", -104, 8.5)], stamp)], stamp),
                _book("hardrockbet", [_market("totals", [_outcome("Over", -108, 8.5), _outcome("Under", 101, 8.5)], stamp)], stamp),
            ],
        },
        {
            "id": "low-hold-mlb-middle",
            "sport_key": "baseball_mlb",
            "sport_title": "MLB",
            "commence_time": (now + timedelta(hours=6, minutes=5)).isoformat(),
            "away_team": "Los Angeles Dodgers",
            "home_team": "San Diego Padres",
            "bookmakers": [
                _book("draftkings", [_market("alternate_totals", [_outcome("Over", 110, 7.5), _outcome("Under", -132, 7.5), _outcome("Over", -130, 8.5), _outcome("Under", 105, 8.5)], stamp)], stamp),
                _book("fanduel", [_market("alternate_totals", [_outcome("Over", 106, 7.5), _outcome("Under", -128, 7.5), _outcome("Over", -126, 8.5), _outcome("Under", 102, 8.5)], stamp)], stamp),
                _book("caesars", [_market("alternate_totals", [_outcome("Over", 104, 7.5), _outcome("Under", -125, 7.5), _outcome("Over", -125, 8.5), _outcome("Under", 100, 8.5)], stamp)], stamp),
            ],
        },
        {
            "id": "low-hold-player-middle",
            "sport_key": "baseball_mlb",
            "sport_title": "MLB",
            "commence_time": (now + timedelta(hours=7, minutes=30)).isoformat(),
            "away_team": "Seattle Mariners",
            "home_team": "Texas Rangers",
            "bookmakers": [
                _book("betonline", [_market("batter_hits", [_outcome("Over", 125, 0.5, "Julio Rodríguez"), _outcome("Under", -155, 0.5, "Julio Rodríguez"), _outcome("Over", -145, 1.5, "Julio Rodríguez"), _outcome("Under", -118, 1.5, "Julio Rodríguez")], stamp)], stamp),
                _book("fanatics", [_market("batter_hits", [_outcome("Over", 120, 0.5, "Julio Rodríguez"), _outcome("Under", -150, 0.5, "Julio Rodríguez"), _outcome("Over", -140, 1.5, "Julio Rodríguez"), _outcome("Under", -115, 1.5, "Julio Rodríguez")], stamp)], stamp),
                _book("novig", [_market("batter_hits", [_outcome("Over", 122, 0.5, "Julio Rodríguez"), _outcome("Under", -152, 0.5, "Julio Rodríguez"), _outcome("Over", -142, 1.5, "Julio Rodríguez"), _outcome("Under", -116, 1.5, "Julio Rodríguez")], stamp)], stamp),
            ],
        },
        {
            "id": "low-hold-pitcher-push",
            "sport_key": "baseball_mlb",
            "sport_title": "MLB",
            "commence_time": (now + timedelta(hours=8, minutes=20)).isoformat(),
            "away_team": "Philadelphia Phillies",
            "home_team": "Atlanta Braves",
            "bookmakers": [
                _book("bet365", [_market("pitcher_strikeouts", [_outcome("Over", 112, 5.5, "Zack Wheeler"), _outcome("Under", -138, 5.5, "Zack Wheeler"), _outcome("Over", -126, 6.0, "Zack Wheeler"), _outcome("Under", -108, 6.0, "Zack Wheeler")], stamp)], stamp),
                _book("pinnacle", [_market("pitcher_strikeouts", [_outcome("Over", 108, 5.5, "Zack Wheeler"), _outcome("Under", -134, 5.5, "Zack Wheeler"), _outcome("Over", -122, 6.0, "Zack Wheeler"), _outcome("Under", -105, 6.0, "Zack Wheeler")], stamp)], stamp),
            ],
        },
        {
            "id": "low-hold-mlb-orioles-blue-jays",
            "sport_key": "baseball_mlb",
            "sport_title": "MLB",
            "commence_time": (now + timedelta(hours=9, minutes=10)).isoformat(),
            "away_team": "Baltimore Orioles",
            "home_team": "Toronto Blue Jays",
            "bookmakers": [
                _book("draftkings", [_market("h2h", [_outcome("Baltimore Orioles", 102), _outcome("Toronto Blue Jays", -108)], stamp)], stamp),
                _book("fanduel", [_market("h2h", [_outcome("Baltimore Orioles", -105), _outcome("Toronto Blue Jays", 101)], stamp)], stamp),
                _book("caesars", [_market("h2h", [_outcome("Baltimore Orioles", 100), _outcome("Toronto Blue Jays", -106)], stamp)], stamp),
            ],
        },
    ]
