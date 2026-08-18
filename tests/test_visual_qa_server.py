from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.visual_qa_server import (
    QA_TIMEZONE,
    qa_event_time,
    qa_price_history,
    qa_snapshot,
    qa_trades,
)


def test_visual_qa_fixture_keeps_five_credible_trades_in_todays_view():
    frozen_now = datetime(2026, 8, 18, 15, 7, tzinfo=timezone.utc)
    trades = qa_trades(frozen_now)

    assert len(trades) == 5
    assert [trade["event_title"] for trade in trades] == [
        "Cincinnati Reds vs St. Louis Cardinals",
        "New York Yankees vs Boston Red Sox",
        "Spain vs France",
        "New York Liberty vs Las Vegas Aces",
        "New York Rangers vs Boston Bruins",
    ]
    assert [trade["confidence_score"] for trade in trades] == [58, 56, 55, 64, 53]
    assert [trade["agreeing_wallet_count"] for trade in trades] == [3, 3, 2, 2, 2]

    local_now = frozen_now.astimezone(QA_TIMEZONE)
    starts = [datetime.fromisoformat(trade["event_date_et"]) for trade in trades]
    assert starts == sorted(starts)
    assert len(set(starts)) == 5
    assert all(start > local_now for start in starts)
    assert all(start.date() == local_now.date() for start in starts)
    assert all(trade["event_time_et"].startswith("Today, ") for trade in trades)

    strongest = max(trades, key=lambda trade: trade["confidence_score"])
    assert strongest["event_title"] == "New York Liberty vs Las Vegas Aces"
    assert strongest["outcome"] == "Over 167.5"


def test_visual_qa_schedule_stays_future_and_same_day_late_at_night():
    late_now = datetime(2026, 8, 18, 23, 55, tzinfo=QA_TIMEZONE)
    starts = [qa_event_time(index, late_now) for index in range(5)]

    assert starts == sorted(starts)
    assert len(set(starts)) == 5
    assert all(start > late_now for start in starts)
    assert all(start.date() == late_now.date() for start in starts)


def test_visual_qa_snapshot_refreshes_all_five_placeholder_start_times():
    first_now = datetime(2026, 8, 18, 15, 7, tzinfo=timezone.utc)
    later_now = datetime(2026, 8, 18, 18, 7, tzinfo=timezone.utc)

    first = qa_snapshot(first_now)
    later = qa_snapshot(later_now)

    assert len(first["trades_to_play"]) == 5
    assert len(later["trades_to_play"]) == 5
    assert first["status"]["last_successful_refresh"] == first_now.isoformat()
    assert later["status"]["last_successful_refresh"] == later_now.isoformat()
    assert [trade["id"] for trade in first["trades_to_play"]] == [
        trade["id"] for trade in later["trades_to_play"]
    ]
    assert all(
        datetime.fromisoformat(trade["event_date_et"]) > later_now.astimezone(QA_TIMEZONE)
        for trade in later["trades_to_play"]
    )


@pytest.mark.parametrize(
    ("variation_index", "current_price", "expected_direction"),
    [
        (0, 0.420, "up"),
        (1, 0.507, "up"),
        (2, 0.400, "up"),
        (3, 0.455, "down"),
        (4, 0.525, "up"),
    ],
)
def test_visual_qa_price_history_is_varied_bounded_and_ends_live(
    variation_index: int,
    current_price: float,
    expected_direction: str,
):
    frozen_now = datetime(2026, 8, 18, 15, 7, tzinfo=timezone.utc)
    history = qa_price_history(
        current_price,
        now=frozen_now,
        variation_index=variation_index,
    )
    timestamps = [point["t"] for point in history]
    prices = [float(point["p"]) for point in history]

    assert len(history) == 25
    assert timestamps == sorted(timestamps)
    assert all(right - left == 15 * 60 for left, right in zip(timestamps, timestamps[1:]))
    assert prices[-1] == pytest.approx(current_price)
    assert 0.008 <= max(prices) - min(prices) <= 0.035
    assert len(set(prices)) >= 16
    assert len({round(right - left, 4) for left, right in zip(prices, prices[1:])}) >= 4
    if expected_direction == "up":
        assert prices[-1] > prices[0]
    else:
        assert prices[-1] < prices[0]
