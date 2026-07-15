from __future__ import annotations

import json

from database import TrackerDatabase
from personal_tracker import (
    canonical_trade_identity,
    identity_key,
    normalize_personal_tags,
    normalize_sportsbook,
    personal_exposure_for_trade,
    personal_fill_snapshot,
    personal_tags_from_fill,
    replay_personal_tracker,
)


def _trade(
    *,
    event_id: str = "event-1",
    market_id: str = "market-1",
    outcome_id: str = "outcome-a",
    line: float | None = 2.5,
    selection: str = "Spain",
) -> dict:
    return {
        "id": f"{market_id}::{outcome_id}",
        "event_slug": event_id,
        "event_title": "Spain vs France",
        "market_title": "To Advance",
        "market_line": line,
        "outcome": selection,
        "clob_token_id": outcome_id,
        "event_date_et": "2026-07-14T15:00:00-04:00",
        "market_url": "https://polymarket.com/event/example",
        "validation_ids": {
            "event_id": event_id,
            "condition_id": market_id,
            "outcome_token_id": outcome_id,
            "event_slug": event_id,
            "market_slug": market_id,
        },
    }


def _fill(
    trade: dict,
    fill_id: str,
    *,
    entry_price: float = 0.4,
    shares: float = 100,
    fees: float = 1,
    status: str = "scheduled",
    user_id: str = "user-1",
) -> dict:
    fill = personal_fill_snapshot(
        trade,
        fill_id=fill_id,
        entry_price=entry_price,
        shares=shares,
        fees=fees,
    )
    return {
        **fill,
        "user_id": user_id,
        "status": status,
        "created_at": f"2026-07-13T12:0{fill_id[-1]}:00+00:00",
    }


def test_canonical_identity_includes_event_market_line_and_outcome():
    trade = _trade(line=2.50)

    assert canonical_trade_identity(trade) == {
        "canonical_event_id": "event-1",
        "canonical_market_id": "market-1",
        "market_line": "2.5",
        "canonical_outcome_id": "outcome-a",
    }


def test_personal_book_and_tags_are_normalized_without_losing_display_case():
    assert normalize_sportsbook("  Hard   Rock Bet  ") == "Hard Rock Bet"
    assert normalize_personal_tags([" Tennis ", "#Value", "tennis", ""]) == [
        "Tennis",
        "Value",
    ]
    assert personal_tags_from_fill({"tags_json": '["Live", "Favorites"]'}) == [
        "Live",
        "Favorites",
    ]


def test_exposure_priority_is_opposing_then_exact_then_same_event():
    recommended = _trade()
    exact = _fill(recommended, "fill-1")
    opposing = _fill(_trade(outcome_id="outcome-b", selection="France"), "fill-2")
    other_market = _fill(
        _trade(market_id="market-total", outcome_id="under", selection="Under"),
        "fill-3",
    )

    exposure = personal_exposure_for_trade(recommended, [exact, opposing, other_market])

    assert exposure["type"] == "opposing"
    assert exposure["hasOpposingPersonalPosition"] is True
    assert exposure["hasExactPersonalPosition"] is True
    assert exposure["hasSameEventDifferentMarketPosition"] is True
    assert exposure["personalEntryCount"] == 1


def test_same_team_text_on_another_event_does_not_trigger_warning():
    recommended = _trade(event_id="event-current")
    historical = _fill(_trade(event_id="event-old", market_id="market-1"), "fill-1")

    exposure = personal_exposure_for_trade(recommended, [historical])

    assert exposure["type"] == "none"


def test_multiple_exact_fills_remain_separate_and_aggregate_vwap():
    trade = _trade()
    first = _fill(trade, "fill-1", entry_price=0.4, shares=100, fees=1)
    second = _fill(trade, "fill-2", entry_price=0.6, shares=50, fees=2)

    exposure = personal_exposure_for_trade(trade, [first, second], include_entries=True)

    aggregate = exposure["groups"]["exact"]["aggregate"]
    assert exposure["type"] == "exact"
    assert len(exposure["groups"]["exact"]["entries"]) == 2
    assert aggregate["totalShares"] == 150
    assert aggregate["totalPositionCost"] == 70
    assert aggregate["averageEntry"] == 70 / 150
    assert aggregate["totalFees"] == 3


def test_personal_tracker_replays_actual_shares_entries_fees_and_results():
    won = {
        **_fill(_trade(), "fill-1", entry_price=0.4, shares=100, fees=1, status="won"),
        "result": "Won",
        "settled_at": "2026-07-14T20:00:00+00:00",
    }
    lost = {
        **_fill(_trade(), "fill-2", entry_price=0.6, shares=50, fees=2, status="lost"),
        "result": "Lost",
        "settled_at": "2026-07-14T21:00:00+00:00",
    }
    open_fill = _fill(
        _trade(), "fill-3", entry_price=0.5, shares=20, fees=0, status="live"
    )

    replay = replay_personal_tracker([won, lost, open_fill], starting_bankroll=1000)

    assert replay["summary"]["realized_profit_loss"] == 27
    assert replay["summary"]["starting_bankroll"] == 1000
    assert replay["summary"]["current_bankroll"] == 1027
    assert replay["summary"]["roi"] == 27 / 1000
    assert replay["summary"]["wins"] == 1
    assert replay["summary"]["losses"] == 1
    assert replay["summary"]["open_exposure"] == 10
    assert replay["summary"]["potential_payout"] == 20
    assert replay["summary"]["total_wagered"] == 83
    assert replay["graph"][-1]["profit_loss"] == 27
    assert replay["graph"][-1]["bankroll"] == 1027
    assert replay["summary"]["maximum_drawdown"] == 32 / 1059
    assert replay["rows"][0]["profit_loss"] == 59
    assert replay["rows"][1]["profit_loss"] == -32
    assert replay["rows"][2]["profit_loss"] is None


def test_canceled_personal_fill_does_not_create_fake_fee_loss():
    canceled = _fill(
        _trade(), "fill-1", entry_price=0.4, shares=100, fees=1, status="canceled"
    )

    replay = replay_personal_tracker([canceled])

    assert replay["summary"]["realized_profit_loss"] == 0
    assert replay["rows"][0]["profit_loss"] == 0


def test_hidden_trade_is_unique_exact_and_user_scoped(tmp_path):
    database = TrackerDatabase(tmp_path / "tracker.db")
    trade = _trade()
    hidden = {
        **canonical_trade_identity(trade),
        "event_title": trade["event_title"],
        "market_title": trade["market_title"],
        "selection": trade["outcome"],
        "event_start_time": trade["event_date_et"],
    }

    first = database.hide_trade("user-1", hidden)
    duplicate = database.hide_trade("user-1", hidden)
    database.hide_trade("user-2", hidden)

    assert first["id"] == duplicate["id"]
    assert len(database.get_hidden_trades("user-1")) == 1
    assert len(database.get_hidden_trades("user-2")) == 1
    assert database.restore_hidden_trade("user-2", first["id"]) is False
    assert len(database.get_hidden_trades("user-1")) == 1
    assert database.restore_hidden_trade("user-1", first["id"]) is True


def test_hiding_one_outcome_does_not_hide_another_market_identity(tmp_path):
    database = TrackerDatabase(tmp_path / "tracker.db")
    first = canonical_trade_identity(_trade(market_id="market-advance"))
    other = canonical_trade_identity(
        _trade(market_id="market-moneyline", outcome_id="outcome-moneyline")
    )

    database.hide_trade("user-1", first)
    hidden_keys = {
        identity_key(record) for record in database.get_hidden_trades("user-1")
    }

    assert identity_key(first) in hidden_keys
    assert identity_key(other) not in hidden_keys


def test_personal_fills_are_user_scoped_and_canceled_fills_are_inactive(tmp_path):
    database = TrackerDatabase(tmp_path / "tracker.db")
    trade = _trade()
    first = database.insert_personal_bet_fill("user-1", _fill(trade, "fill-1"))
    database.insert_personal_bet_fill("user-2", _fill(trade, "fill-2"))

    assert len(database.get_personal_bet_fills("user-1", active_only=True)) == 1
    assert len(database.get_personal_bet_fills("user-2", active_only=True)) == 1
    assert database.cancel_personal_bet_fill("user-2", first["fill_id"]) is False
    assert len(database.get_personal_bet_fills("user-1", active_only=True)) == 1
    assert database.cancel_personal_bet_fill("user-1", first["fill_id"]) is True
    assert database.get_personal_bet_fills("user-1", active_only=True) == []
    assert database.get_personal_bet_fills("user-1")[0]["status"] == "canceled"


def test_personal_fill_sportsbook_and_tags_persist_in_sqlite(tmp_path):
    database = TrackerDatabase(tmp_path / "tracker.db")
    fill = personal_fill_snapshot(
        _trade(),
        fill_id="fill-book-tags",
        entry_price=0.4,
        shares=25,
        fees=0,
        sportsbook="DraftKings",
        tags=["Tennis", "Value"],
    )

    stored = database.insert_personal_bet_fill("user-1", fill)
    replay = replay_personal_tracker(database.get_personal_bet_fills("user-1"))

    assert stored["sportsbook"] == "DraftKings"
    assert stored["tags_json"] == '["Tennis", "Value"]'
    assert replay["rows"][0]["sportsbook"] == "DraftKings"
    assert replay["rows"][0]["tags"] == ["Tennis", "Value"]


def test_personal_fill_persists_authoritative_sharp_snapshot(tmp_path):
    database = TrackerDatabase(tmp_path / "tracker.db")
    trade = {
        **_trade(),
        "primary_lead_wallet_id": "0xlead",
        "supporting_wallets": [
            {
                "wallet_address": "0xsupport",
                "wallet_label": "Large Supporter",
                "is_lead_sharp": False,
                "amount": 9000,
                "relative_units": 3.6,
                "average_entry_price": 0.38,
                "top_category": "Soccer",
            },
            {
                "wallet_address": "0xlead",
                "wallet_label": "Bagwell306",
                "is_lead_sharp": True,
                "amount": 3400,
                "relative_units": 1.36,
                "average_entry_price": 0.4,
                "top_category": "Tennis",
            },
        ],
    }
    fill = personal_fill_snapshot(
        trade, fill_id="fill-sharps", entry_price=0.41, shares=25, fees=0
    )

    stored = database.insert_personal_bet_fill("user-1", fill)
    replay = replay_personal_tracker(database.get_personal_bet_fills("user-1"))
    persisted = json.loads(stored["sharp_snapshot_json"])

    assert persisted["primary_sharp"]["display_name"] == "Bagwell306"
    assert persisted["agreeing_sharps"][0]["display_name"] == "Bagwell306"
    assert replay["rows"][0]["sharp_snapshot"] == persisted
