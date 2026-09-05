from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from middles import MIDDLES_CALCULATION_VERSION, build_middles_board
from middles_preview import temporary_middle_events


NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def _outcome(name: str, price: int, point: float, description: str = "") -> dict:
    return {"name": name, "price": price, "point": point, "description": description}


def _book(key: str, outcomes: list[dict], market: str = "alternate_totals") -> dict:
    return {
        "key": key,
        "title": key.title(),
        "last_update": NOW.isoformat(),
        "markets": [{"key": market, "last_update": NOW.isoformat(), "outcomes": outcomes}],
    }


def _event(*books: dict) -> dict:
    return {
        "id": "middle-event",
        "sport_key": "americanfootball_nfl",
        "sport_title": "NFL",
        "commence_time": (NOW + timedelta(hours=5)).isoformat(),
        "away_team": "Away",
        "home_team": "Home",
        "bookmakers": list(books),
    }


def test_total_middle_equalizes_outside_risk_and_prices_break_even() -> None:
    event = _event(
        _book("draftkings", [_outcome("Over", -110, 42.5)]),
        _book("fanduel", [_outcome("Under", -110, 47.5)]),
    )

    board = build_middles_board(
        [event],
        selected_books=("draftkings", "fanduel"),
        allowed_markets=("alternate_totals",),
        total_stake=100,
        now=NOW,
    )

    row = board["data"][0]
    assert [leg["stake"] for leg in row["legs"]] == [50.0, 50.0]
    assert row["worstCaseProfit"] == pytest.approx(-4.55, abs=0.01)
    assert row["costPercent"] == pytest.approx(4.55, abs=0.01)
    assert row["middleProfit"] == pytest.approx(90.91, abs=0.01)
    assert row["breakEvenMiddleProbability"] == pytest.approx(4.76, abs=0.01)
    assert row["window"]["label"] == "43–47"
    assert row["middleOutcomeCount"] == 5
    assert row["calculationVersion"] == MIDDLES_CALCULATION_VERSION
    assert row["awayTeam"] == "Away"
    assert row["homeTeam"] == "Home"


def test_required_sportsbook_reprices_the_middle_with_that_book() -> None:
    event = _event(
        _book("draftkings", [_outcome("Over", 150, 42.5)]),
        _book("fanduel", [_outcome("Under", 150, 47.5)]),
        _book("betmgm", [_outcome("Over", -110, 42.5)]),
    )

    unrestricted = build_middles_board(
        [event],
        selected_books=("draftkings", "fanduel", "betmgm"),
        allowed_markets=("alternate_totals",),
        max_cost_percent=100,
        now=NOW,
    )["data"][0]
    required = build_middles_board(
        [event],
        selected_books=("draftkings", "fanduel", "betmgm"),
        required_book="betmgm",
        allowed_markets=("alternate_totals",),
        max_cost_percent=100,
        now=NOW,
    )["data"][0]

    assert "betmgm" not in unrestricted["booksUsed"]
    assert "betmgm" in required["booksUsed"]


def test_baseline_middle_locks_the_first_leg_and_sizes_the_hedge() -> None:
    event = _event(
        _book("draftkings", [_outcome("Over", -110, 42.5)]),
        _book("fanduel", [_outcome("Under", -110, 47.5)]),
    )

    row = build_middles_board(
        [event],
        selected_books=("draftkings", "fanduel"),
        allowed_markets=("alternate_totals",),
        total_stake=100,
        stake_mode="first-leg",
        now=NOW,
    )["data"][0]

    assert row["stakeMode"] == "first-leg"
    assert row["stakeInputAmount"] == 100
    assert row["baselineLegIndex"] == 0
    assert row["baselineStake"] == 100
    assert row["legs"][0]["stake"] == 100
    assert row["legs"][1]["stake"] == pytest.approx(100, abs=0.01)
    assert row["totalStake"] == pytest.approx(200, abs=0.01)


def test_spread_middle_reports_the_exact_margin_window() -> None:
    event = _event(
        _book(
            "fanatics",
            [_outcome("Away", -105, 6.5)],
            market="alternate_spreads",
        ),
        _book(
            "bet365",
            [_outcome("Home", -110, -2.5)],
            market="alternate_spreads",
        ),
    )

    row = build_middles_board(
        [event],
        selected_books=("fanatics", "bet365"),
        allowed_markets=("alternate_spreads",),
        now=NOW,
    )["data"][0]

    assert row["middleWidth"] == 4.0
    assert row["middleOutcomeCount"] == 4
    assert row["window"]["low"] == -6.5
    assert row["window"]["high"] == -2.5
    assert "Away margin" in row["window"]["label"]


def test_total_middle_estimates_probability_only_from_paired_market_ladder() -> None:
    outcomes = [
        _outcome("Over", -160, 42.5),
        _outcome("Under", 130, 42.5),
        _outcome("Over", 130, 47.5),
        _outcome("Under", -160, 47.5),
    ]
    event = _event(
        _book("draftkings", outcomes),
        _book("fanduel", outcomes),
    )

    row = build_middles_board(
        [event],
        selected_books=("draftkings", "fanduel"),
        allowed_markets=("alternate_totals",),
        max_cost_percent=30.0,
        now=NOW,
    )["data"][0]

    assert row["probabilityModel"]["status"] == "AVAILABLE"
    assert row["probabilityModel"]["method"] == "DEVIGGED_MARKET_LADDER_CDF"
    assert row["estimatedMiddleProbability"] is not None
    assert row["estimatedEvPercent"] is not None


def test_non_overlapping_lines_are_not_false_middles() -> None:
    event = _event(
        _book("draftkings", [_outcome("Over", -110, 47.5)]),
        _book("fanduel", [_outcome("Under", -110, 42.5)]),
    )

    board = build_middles_board(
        [event],
        selected_books=("draftkings", "fanduel"),
        allowed_markets=("alternate_totals",),
        now=NOW,
    )

    assert board["data"] == []
    assert board["diagnostics"]["rejectionReasons"]["no_middle_pair"] == 1


def test_maximum_cost_and_minimum_width_are_hard_filters() -> None:
    event = _event(
        _book("draftkings", [_outcome("Over", -110, 42.5)]),
        _book("fanduel", [_outcome("Under", -110, 47.5)]),
    )
    books = ("draftkings", "fanduel")

    expensive = build_middles_board(
        [event], selected_books=books, max_cost_percent=4.0, now=NOW
    )
    narrow = build_middles_board(
        [event], selected_books=books, min_middle_width=5.5, now=NOW
    )

    assert expensive["data"] == []
    assert expensive["diagnostics"]["rejectionReasons"]["above_maximum_cost"] == 1
    assert narrow["data"] == []
    assert narrow["diagnostics"]["rejectionReasons"]["below_minimum_width"] == 1


def test_distinct_book_mode_rejects_same_book_pair() -> None:
    event = _event(
        _book(
            "draftkings",
            [_outcome("Over", -110, 42.5), _outcome("Under", -110, 47.5)],
        )
    )

    unrestricted = build_middles_board(
        [event], selected_books=("draftkings",),
        require_distinct_books=False, now=NOW
    )
    distinct = build_middles_board(
        [event], selected_books=("draftkings",), require_distinct_books=True, now=NOW
    )

    assert len(unrestricted["data"]) == 1
    assert distinct["data"] == []
    assert distinct["diagnostics"]["rejectionReasons"]["same_book"] == 1


def test_stale_quote_cannot_form_a_middle() -> None:
    stale = _book("draftkings", [_outcome("Over", -110, 42.5)])
    stale["last_update"] = (NOW - timedelta(minutes=10)).isoformat()
    stale["markets"][0]["last_update"] = stale["last_update"]
    event = _event(stale, _book("fanduel", [_outcome("Under", -110, 47.5)]))

    board = build_middles_board(
        [event],
        selected_books=("draftkings", "fanduel"),
        max_quote_age_seconds=180,
        now=NOW,
    )

    assert board["data"] == []
    assert board["diagnostics"]["rejectionReasons"]["stale_quote"] == 1


def test_preview_fixture_covers_totals_spreads_props_and_an_arb_middle() -> None:
    events = temporary_middle_events(NOW)
    books = {book["key"] for event in events for book in event["bookmakers"]}
    board = build_middles_board(
        events,
        selected_books=books,
        allowed_markets=("alternate_totals", "alternate_spreads", "player_points"),
        now=NOW,
    )

    assert len(board["data"]) >= 12
    assert {row["kind"] for row in board["data"]} == {"spread", "total"}
    assert any(row["marketKey"] == "player_points" for row in board["data"])
    assert any(row["guaranteedOutsideProfit"] for row in board["data"])


def test_middles_preview_parameter_cannot_enable_fixture_rows(app_client) -> None:
    live = app_client.get("/api/middles")
    attempted_preview = app_client.get("/api/middles?preview=1&stake=1000")

    assert attempted_preview.status_code == 200
    assert attempted_preview.get_json() == live.get_json()
    assert attempted_preview.get_json()["data"] == []
    assert "previewOnly" not in attempted_preview.get_json()


def test_middles_preview_parameter_renders_live_workspace(app_client) -> None:
    response = app_client.get("/middles?preview=1")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'data-page="middles"' in body
    assert "data-mid-preview" not in body
    assert "temporary middle opportunities" not in body
    assert 'id="mid-feed"' in body
    assert 'id="mid-detail"' in body
    assert "middles.js" in body


def test_middles_live_api_is_paused_before_provider_request(app_client) -> None:
    response = app_client.get("/api/middles")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["paused"] is True
    assert payload["data"] == []
    assert payload["refreshSeconds"] == 0


def test_middles_api_rejects_an_unknown_stake_mode(app_client) -> None:
    response = app_client.get("/api/middles?stake_mode=unknown")

    assert response.status_code == 400
    assert response.get_json()["error"] == "INVALID_MIDDLE_STAKE_MODE"


def test_middles_api_rejects_required_book_outside_selected_books(app_client) -> None:
    response = app_client.get(
        "/api/middles?books=draftkings,fanduel&required_book=betmgm"
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "REQUIRED_MIDDLE_BOOK_NOT_SELECTED"
