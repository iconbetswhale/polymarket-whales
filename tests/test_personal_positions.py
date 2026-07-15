from __future__ import annotations

from datetime import datetime, timezone

import pytest

from database import TrackerDatabase
from personal_positions import (
    aggregate_personal_positions,
    executable_sell_quote,
    personal_realized_pnl_summary,
)


def _fill(
    fill_id="fill-1",
    *,
    provider="Polymarket",
    price=0.4,
    shares=100,
    fees=1,
    status="unresolved",
    outcome="token-a",
    settled_at=None,
):
    return {
        "fill_id": fill_id,
        "canonical_event_id": "event-1",
        "canonical_market_id": "market-1",
        "market_line": "",
        "canonical_outcome_id": outcome,
        "event_title": "Spain vs France",
        "market_title": "To Advance",
        "selection": "Spain",
        "event_start_time": "2026-07-16T20:00:00+00:00",
        "market_url": "https://polymarket.com/event/example",
        "entry_price": price,
        "shares": shares,
        "position_cost": price * shares,
        "fees": fees,
        "total_paid": price * shares + fees,
        "sportsbook": provider,
        "status": status,
        "result": status.title() if status in {"won", "lost", "void"} else None,
        "settled_at": settled_at,
        "created_at": "2026-07-15T12:00:00+00:00",
    }


def _exit(exit_id="exit-1", *, shares=25, price=0.5, fees=0.5, provider="Polymarket"):
    return {
        "exit_id": exit_id,
        "canonical_event_id": "event-1",
        "canonical_market_id": "market-1",
        "market_line": "",
        "canonical_outcome_id": "token-a",
        "sportsbook": provider,
        "shares_sold": shares,
        "sell_price": price,
        "gross_proceeds": shares * price,
        "fees": fees,
        "net_proceeds": shares * price - fees,
        "sold_at": "2026-07-15T16:00:00+00:00",
    }


def test_executable_quote_walks_bid_depth_and_reports_unfilled_shares():
    quote = executable_sell_quote(
        [{"price": 0.5, "size": 20}, {"price": 0.4, "size": 30}], 60
    )
    assert quote["bestBid"] == 0.5
    assert quote["executableShares"] == 50
    assert quote["effectiveSellPrice"] == pytest.approx(0.44)
    assert quote["estimatedGrossProceeds"] == 22
    assert quote["unfilledShares"] == 10


def test_multiple_buys_aggregate_with_weighted_average_and_provider_separation():
    fills = [
        _fill(price=0.4, shares=100, fees=1),
        _fill("fill-2", price=0.6, shares=50, fees=2),
        _fill("fill-3", provider="NoVIG", price=0.5, shares=20, fees=0),
    ]
    positions = aggregate_personal_positions(fills, [])
    assert len(positions) == 2
    poly = next(item for item in positions if item["provider"] == "Polymarket")
    assert poly["totalPurchasedShares"] == 150
    assert poly["grossPurchaseCost"] == 70
    assert poly["buyFees"] == 3
    assert poly["averageBuyEntry"] == pytest.approx(70 / 150)


def test_partial_sale_allocates_weighted_cost_and_preserves_open_position():
    position = aggregate_personal_positions([_fill()], [_exit()])[0]
    assert position["remainingShares"] == 75
    assert position["status"] == "partially_sold"
    assert position["remainingCostBasis"] == pytest.approx(30.75)
    assert position["realizedPnl"] == pytest.approx(1.75)
    assert position["isClosed"] is False


def test_full_sale_moves_to_closed_and_includes_each_fee_once():
    position = aggregate_personal_positions(
        [_fill()], [_exit(shares=100, price=0.5, fees=2)]
    )[0]
    assert position["isClosed"] is True
    assert position["closureMethod"] == "sold"
    assert position["realizedPnl"] == 7
    assert position["returnPct"] == pytest.approx(7 / 41)


@pytest.mark.parametrize(
    ("status", "expected"), [("won", 59), ("lost", -41), ("void", 0)]
)
def test_resolved_cashflows(status, expected):
    position = aggregate_personal_positions(
        [_fill(status=status, settled_at="2026-07-15T18:00:00+00:00")], []
    )[0]
    assert position["isClosed"] is True
    assert position["closureMethod"] == "resolved"
    assert position["realizedPnl"] == expected


def test_partial_sale_then_winning_settlement_combines_cashflows():
    position = aggregate_personal_positions(
        [_fill(status="won", settled_at="2026-07-15T18:00:00+00:00")],
        [_exit(shares=25, price=0.5, fees=0.5)],
    )[0]
    assert position["settlementProceeds"] == 75
    assert position["realizedPnl"] == 46


def test_realized_summary_excludes_open_unrealized_and_uses_eastern_dates():
    closed_today = {
        "isClosed": True,
        "closureTimestamp": "2026-07-15T04:30:00+00:00",
        "realizedPnl": 10,
    }
    closed_yesterday = {
        "isClosed": True,
        "closureTimestamp": "2026-07-15T03:30:00+00:00",
        "realizedPnl": -4,
    }
    open_position = {
        "isClosed": False,
        "closureTimestamp": None,
        "realizedPnl": 500,
        "unrealizedPnl": 1000,
    }
    now = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)
    summary = personal_realized_pnl_summary(
        [closed_today, closed_yesterday, open_position], "week", now
    )
    assert summary["realizedPnl"] == 6
    assert summary["todayPnl"] == 10
    assert summary["yesterdayPnl"] == -4
    assert summary["timezone"] == "America/New_York"


def test_partial_sale_enters_realized_summary_before_position_closes():
    position = aggregate_personal_positions([_fill()], [_exit()])[0]
    summary = personal_realized_pnl_summary(
        [position], "all", datetime(2026, 7, 15, 20, tzinfo=timezone.utc)
    )
    assert position["isClosed"] is False
    assert summary["realizedPnl"] == pytest.approx(1.75)
    assert summary["todayPnl"] == pytest.approx(1.75)


def test_exit_ledger_is_user_scoped_and_idempotent(tmp_path):
    database = TrackerDatabase(tmp_path / "positions.db")
    record = {
        **_exit(),
        "idempotency_key": "request-1",
        "mode": "tracker_only",
    }
    database.insert_personal_position_exit("user-a", record)
    assert len(database.get_personal_position_exits("user-a")) == 1
    assert database.get_personal_position_exits("user-b") == []
    with pytest.raises(ValueError, match="already recorded"):
        database.insert_personal_position_exit(
            "user-a", {**record, "exit_id": "exit-duplicate"}
        )
