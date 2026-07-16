from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from bet_sizing import SLIPPAGE_ABOVE_MAX
from position_tracker import MODEL_TRACKER_USER_ID, TrackerService
from recommendation_service import (
    EVENT_ALREADY_STARTED,
    MISSING_BANKROLL,
    MISSING_EXECUTABLE_PRICE,
    MISSING_LEAD_SHARP,
    NOT_TODAY,
    ZERO_KELLY,
    evaluate_trade_recommendation,
)


EASTERN = ZoneInfo("America/New_York")
NOW = datetime(2026, 7, 13, 16, 0, tzinfo=timezone.utc)


def _play(
    start: datetime | None = None,
    *,
    event_id: str = "event-1",
    market_id: str = "market-1",
    outcome_id: str = "outcome-1",
    asks: list[dict] | None = None,
    strong_evidence: bool = True,
) -> dict:
    start = start or NOW + timedelta(hours=3)
    evidence_value = 1.0 if strong_evidence else 0.5
    return {
        "id": f"{market_id}::{outcome_id}",
        "event_slug": event_id,
        "event_title": "Spain vs France",
        "market_title": "To Advance",
        "market_line": None,
        "outcome": "Spain",
        "clob_token_id": outcome_id,
        "event_date_et": start.astimezone(EASTERN).isoformat(),
        "market_url": "https://polymarket.com/event/example",
        "category": "Soccer",
        "league": "World Cup",
        "market_open": True,
        "lifecycle_status": "upcoming",
        "agreeing_wallet_count": 1,
        "raw_sharp_count": 1,
        "lead_sharp_count": 1,
        "supporting_sharp_count": 0,
        "weighted_sharp_count": 1.0,
        "has_lead_sharp": True,
        "tracked_wallet_count": 2,
        "confidence_score": 82,
        "fair_price": {
            "status": "AVAILABLE",
            "fair_probability": 0.41 if strong_evidence else 0.4,
            "source_count": 2,
            "source_dispersion": 0.01,
        },
        "trade_quality": {"score": 72, "grade": "B"},
        "liquidity_quality": {"score": 100},
        "combined_exposure_exact": 2000.0,
        "expected_fee_fraction": 0.0,
        "average_entry_price": 0.4,
        "supporting_wallets": [],
        "evidence_inputs": {
            "combined_amount": evidence_value,
            "relative_size": evidence_value,
            "top_category": evidence_value,
            "adjusted_category_hit_rate": evidence_value,
            "category_sample_size": evidence_value,
        },
        "validation_ids": {
            "event_id": event_id,
            "condition_id": market_id,
            "outcome_token_id": outcome_id,
            "event_slug": event_id,
            "market_slug": market_id,
        },
        "orderbook": {
            "asks": asks if asks is not None else [{"price": 0.4, "size": 10000}],
            "bids": [{"price": 0.39, "size": 10000}],
            "min_order_size": 1,
            "timestamp": (
                NOW if abs((start - NOW).total_seconds()) < 86400
                else start - timedelta(minutes=5)
            ).isoformat(),
        },
    }


def test_positive_full_precision_today_recommendation_is_tracker_eligible(
    temp_settings,
):
    evaluation = evaluate_trade_recommendation(
        _play(), 10000, TrackerService(temp_settings, auto_start=False).sizing_config, NOW
    )

    recommendation = evaluation["recommendation"]
    assert evaluation["model_tracker_eligible"] is True
    assert evaluation["model_tracker_rejection_reason"] is None
    assert 0 < recommendation["final_recommended_fraction"] < 0.01
    assert recommendation["recommended_amount"] > 0
    assert evaluation["qualifies_today"] is True


def test_model_tracker_rejects_supporting_only_trade(temp_settings):
    play = _play()
    play.update(
        {
            "lead_sharp_count": 0,
            "supporting_sharp_count": 1,
            "weighted_sharp_count": 0.5,
            "has_lead_sharp": False,
        }
    )

    evaluation = evaluate_trade_recommendation(
        play, 10000, TrackerService(temp_settings, auto_start=False).sizing_config, NOW
    )

    assert evaluation["model_tracker_eligible"] is False
    assert evaluation["model_tracker_rejection_reason"] == MISSING_LEAD_SHARP


@pytest.mark.parametrize(
    ("start", "reason"),
    [
        (NOW + timedelta(hours=2), None),
        (NOW + timedelta(days=1), NOT_TODAY),
        (NOW - timedelta(minutes=1), EVENT_ALREADY_STARTED),
    ],
)
def test_today_classification_uses_eastern(start, reason, temp_settings):
    evaluation = evaluate_trade_recommendation(
        _play(start),
        10000,
        TrackerService(temp_settings, auto_start=False).sizing_config,
        NOW,
    )
    assert evaluation["model_tracker_rejection_reason"] == reason


def test_midnight_and_dst_boundaries_use_new_york_calendar(temp_settings):
    config = TrackerService(temp_settings, auto_start=False).sizing_config
    before_spring_midnight = datetime(2026, 3, 8, 4, 55, tzinfo=timezone.utc)
    after_spring_midnight = datetime(2026, 3, 8, 5, 5, tzinfo=timezone.utc)
    spring_event = datetime(2026, 3, 8, 5, 10, tzinfo=timezone.utc)

    assert evaluate_trade_recommendation(
        _play(spring_event), 10000, config, before_spring_midnight
    )["model_tracker_rejection_reason"] == NOT_TODAY
    assert evaluate_trade_recommendation(
        _play(spring_event), 10000, config, after_spring_midnight
    )["model_tracker_eligible"] is True

    before_fall_midnight = datetime(2026, 11, 1, 3, 55, tzinfo=timezone.utc)
    after_fall_midnight = datetime(2026, 11, 1, 4, 5, tzinfo=timezone.utc)
    fall_event = datetime(2026, 11, 1, 4, 10, tzinfo=timezone.utc)
    assert evaluate_trade_recommendation(
        _play(fall_event), 10000, config, before_fall_midnight
    )["model_tracker_rejection_reason"] == NOT_TODAY
    assert evaluate_trade_recommendation(
        _play(fall_event), 10000, config, after_fall_midnight
    )["model_tracker_eligible"] is True


def test_stake_rejections_are_explicit_and_price_units_are_decimal(temp_settings):
    config = TrackerService(temp_settings, auto_start=False).sizing_config
    assert evaluate_trade_recommendation(_play(), 0, config, NOW)[
        "model_tracker_rejection_reason"
    ] == MISSING_BANKROLL
    assert evaluate_trade_recommendation(_play(asks=[]), 10000, config, NOW)[
        "model_tracker_rejection_reason"
    ] == MISSING_EXECUTABLE_PRICE
    assert evaluate_trade_recommendation(
        _play(strong_evidence=False), 10000, config, NOW
    )["model_tracker_rejection_reason"] == ZERO_KELLY
    assert evaluate_trade_recommendation(
        _play(asks=[{"price": 40, "size": 1000}]), 10000, config, NOW
    )["model_tracker_rejection_reason"] == MISSING_EXECUTABLE_PRICE


def test_stable_idempotency_distinguishes_market_and_outcome(temp_settings):
    service = TrackerService(temp_settings, auto_start=False)
    first = service.evaluate_recommendation(_play(), 10000, NOW)
    repeated = service.evaluate_recommendation(_play(), 10000, NOW)
    outcome = service.evaluate_recommendation(
        _play(outcome_id="outcome-2"), 10000, NOW
    )
    market = service.evaluate_recommendation(
        _play(market_id="market-2"), 10000, NOW
    )

    assert first["recommendation_idempotency_key"] == repeated[
        "recommendation_idempotency_key"
    ]
    assert len(
        {
            first["recommendation_idempotency_key"],
            outcome["recommendation_idempotency_key"],
            market["recommendation_idempotency_key"],
        }
    ) == 3


def test_repeated_backend_runs_insert_once_without_opening_a_page(
    temp_settings, db
):
    service = TrackerService(temp_settings, database=db, auto_start=False)

    first = service.reconcile_model_tracker([_play()], NOW)
    second = service.reconcile_model_tracker([_play()], NOW + timedelta(seconds=5))

    assert first["records_inserted"] == 1
    assert second["records_inserted"] == 0
    assert second["records_skipped_duplicates"] == 1
    records = db.get_tracker_records(MODEL_TRACKER_USER_ID)
    assert len(records) == 1
    assert records[0]["status"] == "scheduled"


def test_recommendation_version_upgrade_does_not_duplicate_same_market(
    temp_settings, db
):
    service = TrackerService(temp_settings, database=db, auto_start=False)
    service.sizing_config = replace(service.sizing_config, recommendation_version="v2")
    first = service.reconcile_model_tracker([_play()], NOW)
    service.sizing_config = replace(service.sizing_config, recommendation_version="v3")
    second = service.reconcile_model_tracker([_play()], NOW + timedelta(seconds=5))
    assert first["records_inserted"] == 1
    assert second["records_inserted"] == 0
    assert second["records_skipped_duplicates"] == 1
    assert len(db.get_tracker_records(MODEL_TRACKER_USER_ID)) == 1


def test_model_tracker_rejects_excess_slippage_without_deleting_history(
    temp_settings, db
):
    service = TrackerService(temp_settings, database=db, auto_start=False)
    accepted = service.reconcile_model_tracker([_play()], NOW)
    excessive = _play(asks=[{"price": 0.421, "size": 10000}])
    rejected = service.reconcile_model_tracker(
        [excessive], NOW + timedelta(seconds=5)
    )

    assert accepted["records_inserted"] == 1
    assert rejected["records_rejected"] == 1
    assert db.get_tracking_rejections(MODEL_TRACKER_USER_ID)[0][
        "rejection_reason"
    ] == SLIPPAGE_ABOVE_MAX
    assert len(db.get_tracker_records(MODEL_TRACKER_USER_ID)) == 1


def test_one_failed_trade_does_not_stop_the_batch(temp_settings, db, monkeypatch):
    service = TrackerService(temp_settings, database=db, auto_start=False)
    original = service.evaluate_recommendation

    def sometimes_fails(play, bankroll, now=None):
        if play["id"].startswith("broken"):
            raise RuntimeError("isolated test failure")
        return original(play, bankroll, now)

    monkeypatch.setattr(service, "evaluate_recommendation", sometimes_fails)
    result = service.reconcile_user_tracker(
        "server-user",
        10000,
        [_play(market_id="broken"), _play(market_id="healthy")],
        NOW,
    )

    assert result["errors"] == 1
    assert result["inserted"] == 1
    assert len(db.get_tracker_records("server-user")) == 1


def test_rejection_reasons_are_persisted_for_diagnostics(temp_settings, db):
    service = TrackerService(temp_settings, database=db, auto_start=False)
    result = service.reconcile_user_tracker(
        "server-user", 10000, [_play(asks=[])], NOW
    )

    assert result["rejected"] == 1
    persisted = db.get_tracking_rejections("server-user")
    assert persisted[0]["rejection_reason"] == MISSING_EXECUTABLE_PRICE
    assert persisted[0]["recommendation_idempotency_key"]
