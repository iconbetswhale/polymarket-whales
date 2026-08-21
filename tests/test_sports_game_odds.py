from __future__ import annotations

from config import get_settings
from execution_providers import NoVIGProvider
from sports_game_odds import (
    POSITIVE_EV_DEVIG_BOOKS,
    SPORTS_GAME_ODDS_BOOKMAKERS,
    SPORTS_GAME_ODDS_DEFAULT_EXECUTION_BOOKS,
    SPORTS_GAME_ODDS_DEFAULT_SOURCE_WEIGHTS,
    SPORTS_GAME_ODDS_DFS_BOOKS,
    normalize_sports_game_odds_ev_events,
    positive_ev_catalog_payload,
    sports_game_odds_request_params,
)


EXPECTED_ALL_LINES_BOOK_KEYS = {
    "1xbet",
    "888sport",
    "ballybet",
    "barstool",
    "bet365",
    "betanysports",
    "betclic",
    "betfairexchange",
    "betfairsportsbook",
    "betfred",
    "betmgm",
    "betonline",
    "betparx",
    "betrivers",
    "betrsportsbook",
    "betsafe",
    "betsson",
    "betus",
    "betvictor",
    "betway",
    "bluebet",
    "bodog",
    "bookmakereu",
    "boombet",
    "bovada",
    "boylesports",
    "caesars",
    "casumo",
    "circa",
    "coolbet",
    "coral",
    "draftkings",
    "espnbet",
    "everygame",
    "fanatics",
    "fanduel",
    "fliff",
    "fourwinds",
    "foxbet",
    "grosvenor",
    "gtbets",
    "hardrockbet",
    "hotstreak",
    "kalshi",
    "ladbrokes",
    "leovegas",
    "livescorebet",
    "lowvig",
    "marathonbet",
    "matchbook",
    "mrgreen",
    "mybookie",
    "neds",
    "nordicbet",
    "northstarbets",
    "novig",
    "paddypower",
    "parlayplay",
    "pinnacle",
    "playup",
    "pointsbet",
    "polymarket",
    "primesports",
    "prizepicks",
    "prophetexchange",
    "si",
    "skybet",
    "sleeper",
    "sportsbet",
    "sportsbetting_ag",
    "sporttrade",
    "stake",
    "superbook",
    "suprabets",
    "tab",
    "tabtouch",
    "thescorebet",
    "tipico",
    "topsport",
    "underdog",
    "unibet",
    "virginbet",
    "williamhill",
    "windcreek",
    "wynnbet",
}


class FakeResponse:
    status_code = 200

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeSession:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def get(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return FakeResponse(self.payload)


def _book_quote(odds: str, **overrides) -> dict:
    value = {
        "odds": odds,
        "available": True,
        "lastUpdatedAt": "2099-07-29T20:00:00Z",
    }
    value.update(overrides)
    return value


def _event() -> dict:
    home_books = {
        "pinnacle": _book_quote("-130"),
        "fanduel": _book_quote("-125"),
        "bet365": _book_quote("-128"),
        "prizepicks": _book_quote("-120"),
    }
    away_books = {
        "pinnacle": _book_quote("+120"),
        "fanduel": _book_quote("+115"),
        "bet365": _book_quote("+118"),
        "prizepicks": _book_quote("+110"),
    }
    return {
        "eventID": "sgo-game-1",
        "sportID": "BASEBALL",
        "leagueID": "MLB",
        "status": {"startsAt": "2099-07-29T23:10:00Z"},
        "teams": {
            "home": {
                "teamID": "PHILADELPHIA_PHILLIES_MLB",
                "names": {"long": "Philadelphia Phillies"},
            },
            "away": {
                "teamID": "NEW_YORK_METS_MLB",
                "names": {"long": "New York Mets"},
            },
        },
        "players": {
            "BRYCE_HARPER_1_MLB": {
                "name": "Bryce Harper",
            }
        },
        "links": {
            "bookmakers": {
                "pinnacle": "https://example.test/pinnacle/game",
                "fanduel": "https://example.test/fanduel/game",
                "bet365": "https://example.test/bet365/game",
            }
        },
        "odds": {
            "points-home-game-ml-home": {
                "oddID": "points-home-game-ml-home",
                "statID": "points",
                "statEntityID": "home",
                "periodID": "game",
                "betTypeID": "ml",
                "sideID": "home",
                "byBookmaker": home_books,
            },
            "points-away-game-ml-away": {
                "oddID": "points-away-game-ml-away",
                "statID": "points",
                "statEntityID": "away",
                "periodID": "game",
                "betTypeID": "ml",
                "sideID": "away",
                "byBookmaker": away_books,
            },
            "batting_hits-BRYCE_HARPER_1_MLB-game-ou-over": {
                "oddID": "batting_hits-BRYCE_HARPER_1_MLB-game-ou-over",
                "statID": "batting_hits",
                "statEntityID": "BRYCE_HARPER_1_MLB",
                "periodID": "game",
                "betTypeID": "ou",
                "sideID": "over",
                "byBookmaker": {
                    "pinnacle": _book_quote("-105", overUnder="1.5"),
                    "fanduel": _book_quote("+100", overUnder="1.5"),
                },
            },
            "batting_hits-BRYCE_HARPER_1_MLB-game-ou-under": {
                "oddID": "batting_hits-BRYCE_HARPER_1_MLB-game-ou-under",
                "statID": "batting_hits",
                "statEntityID": "BRYCE_HARPER_1_MLB",
                "periodID": "game",
                "betTypeID": "ou",
                "sideID": "under",
                "byBookmaker": {
                    "pinnacle": _book_quote("-115", overUnder="1.5"),
                    "fanduel": _book_quote("-120", overUnder="1.5"),
                },
            },
        },
    }


def test_catalog_matches_the_full_85_book_all_lines_package() -> None:
    assert set(SPORTS_GAME_ODDS_BOOKMAKERS) == EXPECTED_ALL_LINES_BOOK_KEYS
    assert set(SPORTS_GAME_ODDS_BOOKMAKERS) == {
        row["key"] for row in positive_ev_catalog_payload()["books"]
    }
    assert {
        "bet365",
        "circa",
        "pinnacle",
        "bookmakereu",
        "kalshi",
        "polymarket",
        "thescorebet",
    } <= set(SPORTS_GAME_ODDS_BOOKMAKERS)
    catalog = {
        row["key"]: row for row in positive_ev_catalog_payload()["books"]
    }
    assert all(book["logoUrl"] for book in catalog.values())


def test_dfs_books_are_visible_but_not_treated_as_single_bet_execution() -> None:
    assert SPORTS_GAME_ODDS_DFS_BOOKS == {
        "hotstreak",
        "parlayplay",
        "prizepicks",
        "sleeper",
        "underdog",
    }
    assert SPORTS_GAME_ODDS_DFS_BOOKS.isdisjoint(
        SPORTS_GAME_ODDS_DEFAULT_EXECUTION_BOOKS
    )
    assert SPORTS_GAME_ODDS_DFS_BOOKS.isdisjoint(
        SPORTS_GAME_ODDS_DEFAULT_SOURCE_WEIGHTS
    )


def test_devig_catalog_is_limited_to_five_sources_and_totals_100_percent() -> None:
    assert POSITIVE_EV_DEVIG_BOOKS == (
        "pinnacle",
        "circa",
        "bookmakereu",
        "fanduel",
        "betfairexchange",
    )
    assert set(SPORTS_GAME_ODDS_DEFAULT_SOURCE_WEIGHTS) == set(
        POSITIVE_EV_DEVIG_BOOKS
    )
    assert sum(SPORTS_GAME_ODDS_DEFAULT_SOURCE_WEIGHTS.values()) == 100.0
    payload = positive_ev_catalog_payload()
    assert [book["key"] for book in payload["devigBooks"]] == list(
        POSITIVE_EV_DEVIG_BOOKS
    )
    assert sum(book["weight"] for book in payload["devigBooks"]) == 100.0


def test_request_uses_one_all_book_feed_and_exact_market_filters() -> None:
    params = sports_game_odds_request_params(
        ("baseball_mlb", "basketball_wnba"),
        ("h2h", "spreads", "totals"),
    )

    assert params is not None
    assert params["leagueID"] == "MLB,WNBA"
    assert "bookmakerID" not in params
    assert params["includeOpposingOdds"] == "true"
    assert params["includeAltLines"] == "false"
    assert "points-home-game-ml-home" in str(params["oddID"])


def test_normalizer_preserves_every_returned_book_and_exact_prop_pair() -> None:
    rows = normalize_sports_game_odds_ev_events(
        [_event()], ("h2h", "batter_hits")
    )

    assert len(rows) == 1
    books = {book["key"]: book for book in rows[0]["bookmakers"]}
    assert set(books) == {"pinnacle", "fanduel", "bet365", "prizepicks"}
    pinnacle_markets = books["pinnacle"]["markets"]
    moneyline = next(market for market in pinnacle_markets if market["key"] == "h2h")
    hits = next(market for market in pinnacle_markets if market["key"] == "batter_hits")
    assert {outcome["name"] for outcome in moneyline["outcomes"]} == {
        "New York Mets",
        "Philadelphia Phillies",
    }
    assert {outcome["name"] for outcome in hits["outcomes"]} == {"Over", "Under"}
    assert {outcome["description"] for outcome in hits["outcomes"]} == {
        "Bryce Harper"
    }
    assert {outcome["point"] for outcome in hits["outcomes"]} == {1.5}


def test_provider_fetches_and_caches_all_books_without_bookmaker_filter() -> None:
    session = FakeSession({"success": True, "data": [_event()]})
    provider = NoVIGProvider("test-key", session=session)

    first = provider.ev_events(
        sport_keys=("baseball_mlb",), market_keys=("h2h",)
    )
    second = provider.ev_events(
        sport_keys=("baseball_mlb",), market_keys=("h2h",)
    )

    assert first == second
    assert len(session.calls) == 1
    assert "bookmakerID" not in session.calls[0]["params"]
    assert session.calls[0]["headers"] == {"x-api-key": "test-key"}
    assert {
        book["key"] for book in first[0]["bookmakers"]
    } == {"pinnacle", "fanduel", "bet365", "prizepicks"}


def test_generic_sports_game_odds_environment_names_are_preferred(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SPORTSGAMEODDS_API_KEY", "all-lines-key")
    monkeypatch.setenv("SPORTSGAMEODDS_API_BASE_URL", "https://all-lines.test/v2")
    monkeypatch.setenv("SPORTSGAMEODDS_CACHE_TTL_SECONDS", "73")
    monkeypatch.setenv("NOVIG_ODDS_API_KEY", "legacy-key")
    monkeypatch.setenv("NOVIG_ODDS_API_BASE_URL", "https://legacy.test/v2")
    monkeypatch.setenv("NOVIG_ODDS_CACHE_TTL_SECONDS", "12")

    settings = get_settings()

    assert settings.novig_api_key == "all-lines-key"
    assert settings.novig_api_base_url == "https://all-lines.test/v2"
    assert settings.novig_cache_ttl_seconds == 73
    assert "all-lines-key" not in repr(settings)
