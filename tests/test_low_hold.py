from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from low_hold import (
    LOW_HOLD_CALCULATION_VERSION,
    _locked_leg_stakes,
    build_low_hold_board,
)


NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def _outcome(
    name: str,
    price: int,
    *,
    point=None,
    description: str = "",
    team: str = "",
) -> dict:
    outcome = {"name": name, "price": price, "point": point, "description": description}
    if team:
        outcome["team"] = team
    return outcome


def _book(key: str, outcomes: list[dict], *, market: str = "h2h", age=0) -> dict:
    stamp = (NOW - timedelta(seconds=age)).isoformat()
    return {
        "key": key,
        "title": key.title(),
        "last_update": stamp,
        "link": f"https://example.com/{key}",
        "markets": [{"key": market, "last_update": stamp, "outcomes": outcomes}],
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


def test_standard_low_hold_formula_matches_implied_probability_sum() -> None:
    event = _event(
        _book("draftkings", [_outcome("Over", 125, point=22.5), _outcome("Under", -135, point=22.5)], market="totals"),
        _book("fanduel", [_outcome("Over", 115, point=22.5), _outcome("Under", -126, point=22.5)], market="totals"),
    )

    row = build_low_hold_board(
        [event],
        selected_books=("draftkings", "fanduel"),
        allowed_markets=("totals",),
        include_middles=False,
        total_stake=1000,
        now=NOW,
    )["data"][0]

    expected = ((100 / 225) + (126 / 226) - 1) * 100
    assert row["holdPercent"] == pytest.approx(expected, abs=0.0001)
    assert row["outsideNet"] < 0
    assert row["holdCost"] == pytest.approx(-row["outsideNet"])
    assert sum(leg["stake"] for leg in row["outcomes"]) == pytest.approx(1000)
    assert row["calculationVersion"] == LOW_HOLD_CALCULATION_VERSION
    assert row["awayTeam"] == "Away"
    assert row["homeTeam"] == "Home"


def test_locked_first_leg_matches_the_public_low_hold_hedge_example() -> None:
    decimals = [2.25, 1 + (100 / 126)]
    stakes, locked_index = _locked_leg_stakes(100, decimals, 0)

    assert locked_index == 0
    assert stakes == [100, 125.44]
    payouts = [stake * decimal for stake, decimal in zip(stakes, decimals)]
    assert min(payouts) - sum(stakes) == pytest.approx(-0.44, abs=0.01)


def test_first_leg_mode_keeps_the_selected_bet_fixed_and_reports_actual_total() -> None:
    event = _event(
        _book("draftkings", [_outcome("Over", 125, point=22.5), _outcome("Under", -135, point=22.5)], market="totals"),
        _book("fanduel", [_outcome("Over", 115, point=22.5), _outcome("Under", -126, point=22.5)], market="totals"),
    )

    row = build_low_hold_board(
        [event],
        selected_books=("draftkings", "fanduel"),
        allowed_markets=("totals",),
        include_middles=False,
        total_stake=100,
        stake_mode="first-leg",
        locked_outcome_index=0,
        now=NOW,
    )["data"][0]

    assert row["stakeMode"] == "first-leg"
    assert row["lockedOutcomeIndex"] == 0
    assert row["lockedStake"] == 100
    assert row["outcomes"][0]["stake"] == 100
    assert row["outcomes"][1]["stake"] == pytest.approx(125.44)
    assert row["totalStake"] == pytest.approx(225.44)
    assert row["outsideNet"] == pytest.approx(-0.44, abs=0.01)


def test_first_leg_mode_can_lock_the_second_outcome() -> None:
    event = _event(
        _book("draftkings", [_outcome("Over", 125, point=22.5), _outcome("Under", -135, point=22.5)], market="totals"),
        _book("fanduel", [_outcome("Over", 115, point=22.5), _outcome("Under", -126, point=22.5)], market="totals"),
    )

    row = build_low_hold_board(
        [event],
        selected_books=("draftkings", "fanduel"),
        allowed_markets=("totals",),
        include_middles=False,
        total_stake=100,
        stake_mode="first-leg",
        locked_outcome_index=1,
        now=NOW,
    )["data"][0]

    assert row["lockedOutcomeIndex"] == 1
    assert row["outcomes"][1]["stake"] == 100
    assert row["outcomes"][0]["stake"] == pytest.approx(79.72)


def test_negative_hold_is_routed_to_arbitrage_instead_of_duplicated() -> None:
    event = _event(
        _book("draftkings", [_outcome("Away", 110), _outcome("Home", -120)]),
        _book("fanduel", [_outcome("Away", -120), _outcome("Home", 110)]),
    )

    board = build_low_hold_board(
        [event], selected_books=("draftkings", "fanduel"), now=NOW
    )

    assert board["data"] == []
    assert (
        board["diagnostics"]["rejectionReasons"]
        ["routed_to_arbitrage_or_above_maximum_hold"]
        == 1
    )


def test_required_book_is_always_present_in_the_selected_equation() -> None:
    event = _event(
        _book("draftkings", [_outcome("Away", 100), _outcome("Home", -120)]),
        _book("fanduel", [_outcome("Away", -120), _outcome("Home", 100)]),
        _book("caesars", [_outcome("Away", -110), _outcome("Home", -110)]),
    )

    unrestricted = build_low_hold_board(
        [event],
        selected_books=("draftkings", "fanduel", "caesars"),
        include_middles=False,
        now=NOW,
    )["data"][0]
    required = build_low_hold_board(
        [event],
        selected_books=("draftkings", "fanduel", "caesars"),
        required_book="caesars",
        include_middles=False,
        now=NOW,
    )["data"][0]

    assert "caesars" not in unrestricted["booksUsed"]
    assert "caesars" in required["booksUsed"]
    assert required["holdPercent"] == pytest.approx(2.381, abs=0.001)


def test_true_total_middle_models_both_legs_winning() -> None:
    event = _event(
        _book("draftkings", [_outcome("Over", -105, point=39.5), _outcome("Under", -115, point=39.5)], market="alternate_totals"),
        _book("fanduel", [_outcome("Over", -115, point=40.5), _outcome("Under", -105, point=40.5)], market="alternate_totals"),
    )

    rows = build_low_hold_board(
        [event],
        selected_books=("draftkings", "fanduel"),
        allowed_markets=("alternate_totals",),
        include_exact=False,
        include_middles=True,
        total_stake=200,
        now=NOW,
    )["data"]

    row = rows[0]
    assert row["pairKind"] == "middle"
    assert row["lineDistance"] == 1
    assert row["middleScenario"]["result"] == 40
    assert row["middleScenario"]["label"] == "Both bets win"
    assert row["middleProfit"] > 190


def test_negative_middle_hold_is_routed_off_the_low_hold_board() -> None:
    event = _event(
        _book("draftkings", [_outcome("Over", 104, point=39.5), _outcome("Under", -120, point=39.5)], market="alternate_totals"),
        _book("fanduel", [_outcome("Over", -118, point=40.5), _outcome("Under", 101, point=40.5)], market="alternate_totals"),
    )

    board = build_low_hold_board(
        [event],
        selected_books=("draftkings", "fanduel"),
        allowed_markets=("alternate_totals",),
        include_exact=False,
        include_middles=True,
        total_stake=200,
        now=NOW,
    )

    assert board["data"] == []
    assert board["diagnostics"]["rejectionReasons"]["routed_to_arbitrage_or_above_maximum_hold"] >= 1


def test_player_prop_outcomes_preserve_the_players_team_for_logo_rendering() -> None:
    player = "Julio Rodríguez"
    team = "Seattle Mariners"
    event = _event(
        _book(
            "draftkings",
            [
                _outcome("Over", 100, point=0.5, description=player, team=team),
                _outcome("Under", -120, point=0.5, description=player, team=team),
            ],
            market="batter_hits",
        ),
        _book(
            "fanduel",
            [
                _outcome("Over", -120, point=0.5, description=player, team=team),
                _outcome("Under", 100, point=0.5, description=player, team=team),
            ],
            market="batter_hits",
        ),
    )
    event["away_team"] = team
    event["home_team"] = "Texas Rangers"

    row = build_low_hold_board(
        [event],
        selected_books=("draftkings", "fanduel"),
        allowed_markets=("batter_hits",),
        include_middles=False,
        now=NOW,
    )["data"][0]

    assert {outcome["playerTeam"] for outcome in row["outcomes"]} == {team}


def test_half_point_middle_models_win_and_push() -> None:
    event = _event(
        _book("draftkings", [_outcome("Over", 3300, point=6.5), _outcome("Under", -5000, point=6.5)], market="alternate_totals"),
        _book("fanduel", [_outcome("Over", -400, point=7), _outcome("Under", -5000, point=7)], market="alternate_totals"),
    )

    row = build_low_hold_board(
        [event],
        selected_books=("draftkings", "fanduel"),
        allowed_markets=("alternate_totals",),
        include_exact=False,
        max_hold_percent=5,
        total_stake=30,
        now=NOW,
    )["data"][0]

    assert row["middleScenario"]["result"] == 7
    assert row["middleScenario"]["label"] == "One wins, one pushes"
    assert row["middleProfit"] > 25


def test_exchange_commission_increases_the_effective_hold() -> None:
    event = _event(
        _book("novig", [_outcome("Away", 100), _outcome("Home", -120)]),
        _book("draftkings", [_outcome("Away", -120), _outcome("Home", 100)]),
    )

    raw = build_low_hold_board(
        [event], selected_books=("novig", "draftkings"), now=NOW
    )["data"][0]
    buffered = build_low_hold_board(
        [event],
        selected_books=("novig", "draftkings"),
        commission_bps=500,
        now=NOW,
    )["data"][0]

    assert buffered["holdPercent"] > raw["holdPercent"]
    assert buffered["outsideNet"] < raw["outsideNet"]


def test_stale_quotes_are_removed_before_pairing() -> None:
    event = _event(
        _book("draftkings", [_outcome("Away", 105), _outcome("Home", -110)], age=600),
        _book("fanduel", [_outcome("Away", -110), _outcome("Home", 105)]),
    )

    board = build_low_hold_board(
        [event],
        selected_books=("draftkings", "fanduel"),
        max_quote_age_seconds=180,
        now=NOW,
    )

    assert board["data"] == []
    assert board["diagnostics"]["rejectionReasons"]["stale_quote"] == 1


def test_preview_parameter_cannot_enable_low_hold_fixture_rows(app_client) -> None:
    live = app_client.get("/api/low-hold")
    attempted_preview = app_client.get(
        "/api/low-hold?preview=1&stake=1000&stake_mode=total"
    )

    assert attempted_preview.status_code == 200
    assert attempted_preview.get_json() == live.get_json()
    assert attempted_preview.get_json()["data"] == []
    assert "previewOnly" not in attempted_preview.get_json()


def test_low_hold_api_rejects_an_unknown_stake_mode(app_client) -> None:
    response = app_client.get("/api/low-hold?preview=1&stake_mode=unknown")

    assert response.status_code == 400
    assert response.get_json()["error"] == "INVALID_LOW_HOLD_STAKE_MODE"


def test_low_hold_api_rejects_required_book_outside_selected_filters(app_client) -> None:
    response = app_client.get(
        "/api/low-hold?books=draftkings&required_book=fanduel"
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "REQUIRED_LOW_HOLD_BOOK_NOT_SELECTED"


def test_live_api_is_paused_before_paid_provider_request(app_client) -> None:
    response = app_client.get("/api/low-hold")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["paused"] is True
    assert payload["data"] == []
    assert payload["refreshSeconds"] == 0
