from datetime import datetime, timedelta, timezone

import pytest

from database import TrackerDatabase
from trade_research import (
    CONTRADICTING_NON_CATEGORY,
    CONTRADICTING_SHARPS,
    POLICIES,
    SHARP_NON_CATEGORY,
    STANDARD,
    classification_fields,
    classify_trade,
    research_confidence,
)
from whiteboard import dynamic_whiteboard_state


@pytest.mark.parametrize(
    ("agreeing", "opposing"), [(2, 1), (3, 2), (4, 3), (4, 2), (3, 1)]
)
def test_strict_agreeing_majority_creates_contradicting_research(agreeing, opposing):
    assert classify_trade(agreeing, opposing, 1) == CONTRADICTING_SHARPS


@pytest.mark.parametrize(("agreeing", "opposing"), [(1, 1), (2, 2), (2, 3)])
def test_tied_or_opposing_majority_is_excluded(agreeing, opposing):
    assert classify_trade(agreeing, opposing, 1) is None


def test_non_category_requires_two_unique_agreeing_wallets():
    assert classify_trade(1, 0, 0) is None
    assert classify_trade(2, 0, 0) == SHARP_NON_CATEGORY
    assert classify_trade(3, 0, 0) == SHARP_NON_CATEGORY


def test_lead_prevents_non_category_label():
    assert classify_trade(2, 0, 1) == STANDARD


def test_combined_warning_is_research_only_and_tracker_excluded():
    classification = classify_trade(3, 1, 0)
    fields = classification_fields(classification, 3, 1)
    assert classification == CONTRADICTING_NON_CATEGORY
    assert fields["hasContradictingSharps"] is True
    assert fields["isNonCategoryConsensus"] is True
    assert fields["modelTrackerEligible"] is False
    assert fields["modelTrackerRejectionReason"] == "CONTRADICTING_NON_CATEGORY_RESEARCH_ONLY"


@pytest.mark.parametrize(
    ("classification", "maximum"),
    [(CONTRADICTING_SHARPS, 69), (SHARP_NON_CATEGORY, 59), (CONTRADICTING_NON_CATEGORY, 54)],
)
def test_research_confidence_caps(classification, maximum):
    score = research_confidence(classification, 4, 1, 1.0)
    assert POLICIES[classification].score_min <= score <= maximum


def test_stronger_majority_scores_higher():
    assert research_confidence(CONTRADICTING_SHARPS, 4, 1, 0.7) > research_confidence(
        CONTRADICTING_SHARPS, 3, 2, 0.7
    )


def test_research_probability_and_stake_caps_are_centralized():
    assert POLICIES[CONTRADICTING_SHARPS].probability_adjustment_cap == 0.02
    assert POLICIES[CONTRADICTING_SHARPS].risk_cap == 0.0075
    assert POLICIES[SHARP_NON_CATEGORY].probability_adjustment_cap == 0.01
    assert POLICIES[SHARP_NON_CATEGORY].risk_cap == 0.005
    assert POLICIES[CONTRADICTING_NON_CATEGORY].probability_adjustment_cap == 0.005
    assert POLICIES[CONTRADICTING_NON_CATEGORY].risk_cap == 0.0025


def _pin(snapshot=None):
    return {
        "canonical_event_id": "event-1",
        "canonical_market_id": "market-1",
        "market_line": "8.5",
        "canonical_outcome_id": "over",
        "market_type": "total",
        "period": "game",
        "snapshot": snapshot or {
            "event_title": "Yankees vs Red Sox",
            "event_start_time": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
            "sharp_reference_entry": 0.4,
            "entry_when_pinned": 0.42,
            "confidence_score": 55,
            "recommended_units": 0.5,
        },
    }


def test_whiteboard_pin_is_immutable_unique_and_user_owned(tmp_path):
    database = TrackerDatabase(tmp_path / "whiteboard.db")
    original = database.pin_whiteboard_trade("user-a", _pin())
    duplicate = database.pin_whiteboard_trade("user-a", _pin({"confidence_score": 99}))
    other = database.pin_whiteboard_trade("user-b", _pin())
    assert original["id"] == duplicate["id"]
    assert duplicate["snapshot"]["confidence_score"] == 55
    assert other["id"] != original["id"]
    assert len(database.get_whiteboard_pins("user-a")) == 1
    assert len(database.get_whiteboard_pins("user-b")) == 1
    assert database.archive_whiteboard_pin("user-b", original["id"], "USER_UNPINNED") is False
    assert database.archive_whiteboard_pin("user-a", original["id"], "USER_UNPINNED") is True
    assert database.get_whiteboard_pins("user-a") == []
    assert database.get_whiteboard_pins("user-a", active_only=False)[0]["archive_reason"] == "USER_UNPINNED"


def test_whiteboard_dynamic_slippage_does_not_mutate_snapshot():
    frozen = _pin()["snapshot"]
    current = {
        "recommendation": {
            "effective_entry_price": 0.51,
            "current_top_ask_price": 0.51,
        },
        "market_open": True,
        "lifecycle_status": "upcoming",
    }
    dynamic = dynamic_whiteboard_state(frozen, current)
    assert dynamic["above_max_slippage"] is True
    assert frozen["entry_when_pinned"] == 0.42
    assert frozen["confidence_score"] == 55
