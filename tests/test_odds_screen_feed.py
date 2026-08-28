from __future__ import annotations

from datetime import datetime, timezone

from odds_screen_feed import build_all_book_odds_screen_rows


def _book(key: str, over_odds: int, under_odds: int) -> dict:
    return {
        "key": key,
        "title": {"fanduel": "FanDuel", "draftkings": "DraftKings"}[key],
        "last_update": "2026-08-28T14:59:00Z",
        "markets": [
            {
                "key": "totals",
                "outcomes": [
                    {"name": "Over", "price": over_odds, "point": 8.5},
                    {"name": "Under", "price": under_odds, "point": 8.5},
                ],
            },
            {
                "key": "player_points",
                "outcomes": [
                    {
                        "name": "Over",
                        "description": "Jalen Brunson",
                        "price": over_odds,
                        "point": 25.5,
                    },
                    {
                        "name": "Under",
                        "description": "Jalen Brunson",
                        "price": under_odds,
                        "point": 25.5,
                    },
                ],
            },
        ],
    }


def test_all_book_rows_preserve_every_exact_quote_and_prop_identity() -> None:
    rows = build_all_book_odds_screen_rows(
        [
            {
                "id": "nba-screen-1",
                "sport_key": "basketball_nba",
                "sport_title": "NBA",
                "commence_time": "2026-08-28T23:30:00Z",
                "home_team": "New York Knicks",
                "away_team": "Boston Celtics",
                "bookmakers": [
                    _book("fanduel", -110, -105),
                    _book("draftkings", 100, -115),
                ],
            }
        ],
        now=datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc),
    )

    assert len(rows) == 4
    total_over = next(
        row
        for row in rows
        if row["odds_market_key"] == "totals" and row["outcome"] == "Over"
    )
    prop_over = next(
        row
        for row in rows
        if row["odds_market_key"] == "player_points" and row["outcome"] == "Over"
    )
    assert {option["providerName"] for option in total_over["executionOptions"]} == {
        "DraftKings",
        "FanDuel",
    }
    assert sum(option["isBestPrice"] for option in total_over["executionOptions"]) == 1
    assert next(
        option for option in total_over["executionOptions"] if option["isBestPrice"]
    )["americanOdds"] == 100
    assert prop_over["player_name"] == "Jalen Brunson"
    assert prop_over["market_line"] == 25.5


def test_all_book_rows_keep_different_players_and_lines_separate() -> None:
    event = {
        "id": "nba-screen-2",
        "sport_key": "basketball_nba",
        "sport_title": "NBA",
        "commence_time": "2026-08-28T23:30:00Z",
        "home_team": "New York Knicks",
        "away_team": "Boston Celtics",
        "bookmakers": [
            {
                "key": "fanduel",
                "title": "FanDuel",
                "markets": [
                    {
                        "key": "player_points",
                        "outcomes": [
                            {"name": "Over", "description": "Player A", "point": 20.5, "price": -110},
                            {"name": "Over", "description": "Player A", "point": 21.5, "price": 105},
                            {"name": "Over", "description": "Player B", "point": 20.5, "price": -105},
                        ],
                    }
                ],
            }
        ],
    }

    rows = build_all_book_odds_screen_rows(
        [event],
        now=datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc),
    )

    assert {(row["player_name"], row["market_line"]) for row in rows} == {
        ("Player A", 20.5),
        ("Player A", 21.5),
        ("Player B", 20.5),
    }
