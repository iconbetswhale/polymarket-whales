from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
