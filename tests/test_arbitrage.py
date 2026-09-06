from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest

from arbitrage import (
    ARBITRAGE_CALCULATION_VERSION,
    build_arbitrage_board,
    equalized_stakes,
)
from arbitrage_preview import temporary_arbitrage_events


NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def _outcome(name: str, price: int, *, point=None, description: str = "") -> dict:
    return {
        "name": name,
        "price": price,
        "point": point,
        "description": description,
    }


def _book(key: str, outcomes: list[dict], *, market: str = "h2h") -> dict:
    return {
        "key": key,
        "title": key.title(),
        "last_update": NOW.isoformat(),
        "link": f"https://example.com/{key}",
        "markets": [
            {
                "key": market,
                "last_update": NOW.isoformat(),
                "outcomes": outcomes,
            }
        ],
    }


def _event(*books: dict) -> dict:
    return {
        "id": "event-1",
        "sport_key": "baseball_mlb",
        "sport_title": "MLB",
        "commence_time": (NOW + timedelta(hours=6)).isoformat(),
        "away_team": "Away",
        "home_team": "Home",
        "participant_logos": {
            "Away": "/static/assets/teams/mlb/away.png",
            "home": "/static/assets/teams/mlb/home.png",
        },
        "bookmakers": list(books),
    }


def test_equalized_stakes_preserve_total_and_equalize_payouts() -> None:
    stakes = equalized_stakes(1000, [2.5, 1.9523809524])

    assert sum(stakes) == pytest.approx(1000)
    payouts = [stakes[0] * 2.5, stakes[1] * 1.9523809524]
    assert max(payouts) - min(payouts) < 0.03


def test_two_way_arbitrage_returns_guaranteed_profit_after_cent_rounding() -> None:
    event = _event(
        _book("fanduel", [_outcome("Away", 110), _outcome("Home", -120)]),
        _book("draftkings", [_outcome("Away", -120), _outcome("Home", 110)]),
    )

    board = build_arbitrage_board(
        [event], selected_books=("fanduel", "draftkings"), total_stake=1000, now=NOW
    )

    assert board["diagnostics"]["qualified"] == 1
    row = board["data"][0]
    assert row["profitPercent"] == pytest.approx(5.0)
    assert row["guaranteedProfit"] == pytest.approx(50.0)
    assert row["minPayout"] == pytest.approx(1050.0)
    assert {leg["stake"] for leg in row["outcomes"]} == {500.0}
    assert row["calculationVersion"] == ARBITRAGE_CALCULATION_VERSION
    assert row["awayTeam"] == "Away"
    assert row["homeTeam"] == "Home"
    assert row["participantLogos"] == {
        "Away": "/static/assets/teams/mlb/away.png",
        "home": "/static/assets/teams/mlb/home.png",
    }


def test_first_leg_mode_locks_the_requested_side_and_sizes_every_hedge() -> None:
    event = _event(
        _book("fanduel", [_outcome("Away", 150), _outcome("Home", -120)]),
        _book("draftkings", [_outcome("Away", -120), _outcome("Home", 110)]),
    )

    row = build_arbitrage_board(
        [event],
        selected_books=("fanduel", "draftkings"),
        total_stake=100,
        stake_mode="first-leg",
        locked_outcome_index=1,
        now=NOW,
    )["data"][0]

    assert row["stakeMode"] == "first-leg"
    assert row["stakeInputAmount"] == 100
    assert row["lockedOutcomeIndex"] == 1
    assert row["lockedStake"] == 100
    assert row["outcomes"][1]["stake"] == 100
    assert row["totalStake"] != 100
    payouts = [leg["payout"] for leg in row["outcomes"]]
    assert max(payouts) - min(payouts) < 0.03


def test_required_book_filter_uses_the_best_arbitrage_containing_that_book() -> None:
    event = _event(
        _book("fanduel", [_outcome("Away", 150), _outcome("Home", -150)]),
        _book("draftkings", [_outcome("Away", -150), _outcome("Home", 150)]),
        _book("caesars", [_outcome("Away", 120), _outcome("Home", 120)]),
    )

    unrestricted = build_arbitrage_board(
        [event],
        selected_books=("fanduel", "draftkings", "caesars"),
        now=NOW,
    )["data"][0]
    required = build_arbitrage_board(
        [event],
        selected_books=("fanduel", "draftkings", "caesars"),
        required_book="caesars",
        now=NOW,
    )["data"][0]

    assert "caesars" not in unrestricted["booksUsed"]
    assert "caesars" in required["booksUsed"]
    assert required["profitPercent"] < unrestricted["profitPercent"]
    assert required["stakeMode"] == "total"


def test_three_way_market_requires_and_sizes_every_outcome() -> None:
    event = _event(
        _book(
            "fanduel",
            [_outcome("Away", 245), _outcome("Home", 125), _outcome("Draw", 300)],
        ),
        _book(
            "draftkings",
            [_outcome("Away", 225), _outcome("Home", 138), _outcome("Draw", 305)],
        ),
        _book(
            "caesars",
            [_outcome("Away", 230), _outcome("Home", 128), _outcome("Draw", 330)],
        ),
    )

    row = build_arbitrage_board(
        [event],
        selected_books=("fanduel", "draftkings", "caesars"),
        total_stake=1500,
        now=NOW,
    )["data"][0]

    assert row["outcomeCount"] == 3
    assert {leg["bookKey"] for leg in row["outcomes"]} == {
        "fanduel",
        "draftkings",
        "caesars",
    }
    assert sum(leg["stake"] for leg in row["outcomes"]) == pytest.approx(1500)
    assert min(leg["profit"] for leg in row["outcomes"]) > 0


def test_incomplete_market_cannot_create_a_false_arbitrage() -> None:
    event = _event(
        _book("fanduel", [_outcome("Away", 500)]),
        _book("draftkings", [_outcome("Away", -110), _outcome("Home", -110)]),
    )

    board = build_arbitrage_board(
        [event], selected_books=("fanduel", "draftkings"),
        require_distinct_books=False, now=NOW
    )

    assert board["data"] == []
    assert board["diagnostics"]["rejectionReasons"]["not_arbitrage"] == 1


def test_distinct_book_mode_never_assigns_two_legs_to_one_book() -> None:
    event = _event(
        _book("fanduel", [_outcome("Away", 150), _outcome("Home", 150)]),
        _book("draftkings", [_outcome("Away", 110), _outcome("Home", 110)]),
    )

    unrestricted = build_arbitrage_board(
        [event], selected_books=("fanduel", "draftkings"),
        require_distinct_books=False, now=NOW
    )["data"][0]
    distinct = build_arbitrage_board(
        [event],
        selected_books=("fanduel", "draftkings"),
        require_distinct_books=True,
        now=NOW,
    )["data"][0]

    assert {leg["bookKey"] for leg in unrestricted["outcomes"]} == {"fanduel"}
    assert {leg["bookKey"] for leg in distinct["outcomes"]} == {
        "fanduel",
        "draftkings",
    }
    assert distinct["profitPercent"] < unrestricted["profitPercent"]


def test_exchange_commission_buffer_can_remove_a_nominal_edge() -> None:
    event = _event(
        _book("novig", [_outcome("Away", 105), _outcome("Home", -120)]),
        _book("draftkings", [_outcome("Away", -120), _outcome("Home", 105)]),
    )

    raw = build_arbitrage_board(
        [event], selected_books=("novig", "draftkings"), now=NOW
    )
    buffered = build_arbitrage_board(
        [event],
        selected_books=("novig", "draftkings"),
        commission_bps=1000,
        now=NOW,
    )

    assert len(raw["data"]) == 1
    assert buffered["data"] == []
    assert buffered["diagnostics"]["rejectionReasons"]["not_arbitrage"] == 1


def test_missing_timestamp_and_cross_leg_skew_fail_closed() -> None:
    missing = _book("fanduel", [_outcome("Away", 150), _outcome("Home", 150)])
    missing.pop("last_update")
    missing["markets"][0].pop("last_update")
    board = build_arbitrage_board(
        [_event(missing, _book("draftkings", [_outcome("Away", 110), _outcome("Home", 110)]))],
        selected_books=("fanduel", "draftkings"),
        now=NOW,
    )
    assert board["data"] == []
    assert board["diagnostics"]["rejectionReasons"]["missing_quote_timestamp"] == 1

    old = _book("draftkings", [_outcome("Away", 110), _outcome("Home", 110)])
    old_stamp = (NOW - timedelta(seconds=11)).isoformat()
    old["last_update"] = old_stamp
    old["markets"][0]["last_update"] = old_stamp
    skewed = build_arbitrage_board(
        [_event(_book("fanduel", [_outcome("Away", 150), _outcome("Home", 150)]), old)],
        selected_books=("fanduel", "draftkings"),
        max_cross_leg_skew_seconds=10,
        now=NOW,
    )
    assert skewed["data"] == []
    assert skewed["diagnostics"]["rejectionReasons"]["cross_leg_quote_skew"] >= 1


def test_stale_quotes_are_rejected_before_price_selection() -> None:
    stale_book = _book("fanduel", [_outcome("Away", 150), _outcome("Home", 150)])
    stale_book["last_update"] = (NOW - timedelta(minutes=10)).isoformat()
    stale_book["markets"][0]["last_update"] = stale_book["last_update"]
    event = _event(
        stale_book,
        _book("draftkings", [_outcome("Away", -110), _outcome("Home", -110)]),
    )

    board = build_arbitrage_board(
        [event],
        selected_books=("fanduel", "draftkings"),
        max_quote_age_seconds=180,
        now=NOW,
    )

    assert board["data"] == []
    assert board["diagnostics"]["rejectionReasons"]["stale_quote"] == 1


def test_preview_events_produce_multiple_main_market_opportunities() -> None:
    events = temporary_arbitrage_events(NOW)
    books = {
        book["key"] for event in events for book in event["bookmakers"]
    }
    board = build_arbitrage_board(
        events,
        selected_books=books,
        allowed_markets=("h2h", "spreads", "totals"),
        total_stake=1000,
        now=NOW,
    )

    assert len(board["data"]) == 10
    assert {row["outcomeCount"] for row in board["data"]} == {2, 3}
    assert all(row["guaranteedProfit"] > 0 for row in board["data"])


def test_preview_events_link_to_real_sportsbook_destinations() -> None:
    events = temporary_arbitrage_events(NOW)
    links = [
        link
        for event in events
        for book in event["bookmakers"]
        for link in [book["link"], *(market["link"] for market in book["markets"])]
    ]

    assert links
    assert all(urlsplit(link).scheme == "https" for link in links)
    assert all(urlsplit(link).hostname not in {None, "example.com"} for link in links)


def test_arbitrage_preview_parameter_cannot_enable_fixture_rows(app_client) -> None:
    live = app_client.get("/api/arbitrage")
    attempted_preview = app_client.get("/api/arbitrage?preview=1&stake=1000")

    assert attempted_preview.status_code == 200
    assert attempted_preview.get_json() == live.get_json()
    assert attempted_preview.get_json()["data"] == []
    assert "previewOnly" not in attempted_preview.get_json()


def test_arbitrage_live_api_is_paused_before_paid_provider_request(app_client) -> None:
    response = app_client.get("/api/arbitrage")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["paused"] is True
    assert payload["data"] == []
    assert payload["refreshSeconds"] == 0


def test_arbitrage_api_rejects_an_unknown_stake_mode(app_client) -> None:
    response = app_client.get("/api/arbitrage?stake_mode=one-side")

    assert response.status_code == 400
    assert response.get_json()["error"] == "INVALID_ARBITRAGE_STAKE_MODE"


def test_arbitrage_leg_can_be_saved_to_the_personal_tracker(app_client) -> None:
    app_client.set_cookie("iconbets_user", "arbitrage-personal-user")
    response = app_client.post(
        "/api/arbitrage/personal-bets",
        json={
            "source_id": "arb::strategy-1:0",
            "event_title": "New York Mets vs Philadelphia Phillies",
            "market_title": "Game Total",
            "selection": "Over 7.5",
            "event_start_time": "2026-09-08T23:10:00+00:00",
            "sport_key": "baseball_mlb",
            "league": "MLB",
            "market_key": "totals",
            "market_line": 7.5,
            "canonical_event_id": "mlb-nym-phi-2026-09-08",
            "canonical_market_id": "arb::strategy-1",
            "canonical_outcome_id": "arb::strategy-1:outcome:0",
            "american_odds": 115,
            "stake": 250,
            "fees": 0,
            "sportsbook": "Bet365",
            "sportsbook_logo": "/static/assets/sportsbooks/bet365.png",
            "market_url": "https://www.bet365.com/",
            "ev_percent": 7.5,
            "tags": ["Arbitrage", "2-way arbitrage"],
            "confirm_conflict": True,
            "confirm_duplicate": True,
        },
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["source"] == "arbitrage"
    tracker = app_client.get("/api/personal-tracker?tracker_range=all").get_json()
    assert tracker["pagination"]["total"] == 1
    assert tracker["data"][0]["selection"] == "Over 7.5"
    assert tracker["data"][0]["sportsbook"] == "Bet365"
