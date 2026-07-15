from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from clv import (
    CAPTURED,
    VOID,
    book_effective_ask,
    calculate_clv,
    clv_aggregate,
    clv_period_analytics,
    probability_from_native_odds,
    select_last_fresh_quote,
)
from database import TrackerDatabase
from position_tracker import TrackerService


def test_required_positive_clv_example() -> None:
    result = calculate_clv(0.343, 0.43)
    assert result["clv_cents"] == pytest.approx(8.7)
    assert result["clv_probability_points"] == pytest.approx(8.7)
    assert result["clv_pct"] == pytest.approx(25.3644314869)


@pytest.mark.parametrize(
    ("entry", "close", "expected"),
    [(0.5, 0.46, -8.0), (0.5, 0.5, 0.0)],
)
def test_negative_and_zero_clv(entry: float, close: float, expected: float) -> None:
    assert calculate_clv(entry, close)["clv_pct"] == pytest.approx(expected)


@pytest.mark.parametrize("entry", [0, None, -0.1, 1.0])
def test_invalid_entry_is_rejected(entry: float | None) -> None:
    with pytest.raises(ValueError):
        calculate_clv(entry, 0.43)


def test_last_fresh_prestart_quote_excludes_poststart_and_rejects_stale() -> None:
    start = datetime.now(timezone.utc) - timedelta(seconds=1)
    fresh = {"quote_timestamp": (start - timedelta(seconds=90)).isoformat(), "best_ask": 0.43}
    stale = {"quote_timestamp": (start - timedelta(minutes=8)).isoformat(), "best_ask": 0.4}
    post = {"quote_timestamp": (start + timedelta(seconds=1)).isoformat(), "best_ask": 0.99}
    selected, reason = select_last_fresh_quote([stale, fresh, post], start.isoformat())
    assert selected == fresh
    assert reason is None
    selected, reason = select_last_fresh_quote([stale, post], start.isoformat())
    assert selected is None
    assert reason == "NO_FRESH_CLOSING_QUOTE"


def test_depth_weighted_effective_ask_reports_partial_liquidity() -> None:
    quote = book_effective_ask(
        [{"price": "0.40", "size": "10"}, {"price": "0.50", "size": "4"}],
        10,
    )
    assert quote["effective_price"] == pytest.approx(6 / 14)
    assert quote["executable_amount"] == pytest.approx(6)
    assert quote["unfilled_amount"] == pytest.approx(4)
    assert quote["liquidity_quality"] == "partial"


def test_native_odds_are_normalized_to_selected_side_probability() -> None:
    assert probability_from_native_odds(+100, "american") == pytest.approx(0.5)
    assert probability_from_native_odds(-125, "american") == pytest.approx(125 / 225)
    assert probability_from_native_odds(2.5, "decimal") == pytest.approx(0.4)


def test_stake_weighted_aggregate_excludes_missing_and_void() -> None:
    rows = [
        {"clv_status": CAPTURED, "clv_pct": 10, "clv_cents": 4, "entry_stake": 500},
        {"clv_status": CAPTURED, "clv_pct": -20, "clv_cents": -5, "entry_stake": 5},
        {"clv_status": "unavailable", "entry_stake": 100},
        {"clv_status": VOID, "entry_stake": 100},
    ]
    result = clv_aggregate(rows)
    assert result["stake_weighted_clv_pct"] == pytest.approx((5000 - 100) / 505)
    assert result["average_clv_pct"] == pytest.approx(-5)
    assert result["bets_measured"] == 2
    assert result["missing_clv_count"] == 1
    assert result["total_stake_represented"] == pytest.approx(505)


def test_monthly_clv_is_calculated_directly_from_all_bets() -> None:
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    rows = [
        {"clv_status": CAPTURED, "clv_pct": 20, "clv_cents": 8, "entry_stake": 10, "closing_snapshot_timestamp": "2026-07-01T12:00:00+00:00"},
        {"clv_status": CAPTURED, "clv_pct": -5, "clv_cents": -2, "entry_stake": 90, "closing_snapshot_timestamp": "2026-07-14T12:00:00+00:00"},
    ]
    result = clv_period_analytics(rows, now)["month"]
    assert result["stake_weighted_clv_pct"] == pytest.approx(-2.5)


def test_closing_snapshot_is_immutable_and_provider_scoped(tmp_path) -> None:
    database = TrackerDatabase(tmp_path / "clv.db")
    base = {
        "tracker_type": "personal",
        "tracker_record_id": "fill-1",
        "user_id": "user-1",
        "provider": "polymarket",
        "provider_event_id": "event-1",
        "provider_market_id": "market-1",
        "provider_selection_id": "token-yes",
        "entry_price": 0.343,
        "entry_implied_probability": 0.343,
        "entry_stake": 100,
        "closing_snapshot_timestamp": "2026-07-15T22:59:00+00:00",
        "official_event_start_timestamp": "2026-07-15T23:00:00+00:00",
        "closing_effective_price": 0.43,
        "closing_midpoint": 0.426,
        "clv_cents": 8.7,
        "clv_probability_points": 8.7,
        "clv_pct": 25.3644314869,
        "midpoint_clv_pct": 24.1982507289,
        "clv_status": CAPTURED,
        "clv_unavailable_reason": None,
        "calculation_version": "clv-v1",
    }
    assert database.insert_closing_line(base) is True
    assert database.insert_closing_line({**base, "provider": "prophetx", "clv_pct": -99}) is False
    stored = database.get_closing_lines("personal", "user-1")
    assert len(stored) == 1
    assert stored[0]["provider"] == "polymarket"
    assert stored[0]["provider_selection_id"] == "token-yes"
    assert stored[0]["clv_pct"] == pytest.approx(25.3644314869)


def test_backend_freezes_exact_polymarket_book_without_cross_provider_fallback(tmp_path) -> None:
    start = datetime.now(timezone.utc) - timedelta(seconds=1)

    class Client:
        def get_order_books(self, token_ids):
            assert token_ids == ["token-yes"]
            return {
                "token-yes": {
                    "timestamp": int((start - timedelta(seconds=30)).timestamp() * 1000),
                    "bids": [{"price": "0.42", "size": "500"}],
                    "asks": [{"price": "0.43", "size": "500"}],
                    "last_trade_price": "0.425",
                }
            }

    service = TrackerService.__new__(TrackerService)
    service.database = TrackerDatabase(tmp_path / "capture.db")
    service.client = Client()
    model = {
        "user_id": "model-user",
        "dedupe_key": "model-record",
        "status": "scheduled",
        "snapshot": {
            "canonical_event_id": "event-1",
            "canonical_event_slug": "event-slug",
            "canonical_market_id": "market-1",
            "outcome_id": "token-yes",
            "recommended_side": "Yes",
            "event_start_time": start.isoformat(),
            "effective_entry_price": 0.343,
            "original_displayed_amount": 100,
            "recommendation_timestamp": (start - timedelta(hours=1)).isoformat(),
        },
    }
    prophetx_fill = {
        "fill_id": "prophetx-fill",
        "user_id": "personal-user",
        "canonical_event_id": "event-1",
        "canonical_event_slug": "event-slug",
        "canonical_market_id": "market-1",
        "canonical_outcome_id": "prophetx-selection",
        "selection": "Yes",
        "event_start_time": start.isoformat(),
        "entry_price": 0.35,
        "position_cost": 50,
        "created_at": (start - timedelta(hours=1)).isoformat(),
        "sportsbook": "ProphetX",
    }
    event = {
        "startTime": start.isoformat(),
        "gameStatus": "in progress",
        "markets": [{"conditionId": "market-1", "active": True}],
    }
    service._capture_closing_lines([model], [prophetx_fill], {"event-slug": event})

    model_close = service.database.get_closing_lines("model", "model-user")[0]
    personal_close = service.database.get_closing_lines("personal", "personal-user")[0]
    assert model_close["clv_status"] == CAPTURED
    assert model_close["closing_effective_price"] == pytest.approx(0.43)
    assert model_close["clv_pct"] == pytest.approx(25.3644314869)
    assert personal_close["clv_status"] == "market_mapping_error"
    assert personal_close["clv_unavailable_reason"] == "CLV_MARKET_MAPPING_ERROR"

    delayed = {
        **model,
        "dedupe_key": "delayed-record",
        "snapshot": {**model["snapshot"], "event_start_time": (start - timedelta(hours=1)).isoformat()},
    }
    delayed_event = {
        **event,
        "startTime": (start - timedelta(hours=1)).isoformat(),
        "gameStatus": "postponed",
    }
    service._capture_closing_lines([delayed], [], {"event-slug": delayed_event})
    assert service.database.get_closing_lines("model", "model-user") == [model_close]

    early_close = {**model, "dedupe_key": "early-close-record"}
    early_event = {
        **event,
        "markets": [
            {
                "conditionId": "market-1",
                "active": False,
                "closed": True,
                "acceptingOrders": False,
                "closedTime": (start - timedelta(seconds=10)).isoformat(),
            }
        ],
    }
    service._capture_closing_lines([early_close], [], {"event-slug": early_event})
    early_snapshot = next(
        row
        for row in service.database.get_closing_lines("model", "model-user")
        if row["tracker_record_id"] == "early-close-record"
    )
    assert early_snapshot["provider_close_source"] == "MARKET_CLOSED_PRE_EVENT"
    assert early_snapshot["provider_market_close_timestamp"] == (start - timedelta(seconds=10)).isoformat()
