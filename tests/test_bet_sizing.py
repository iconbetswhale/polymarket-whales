from __future__ import annotations

import pytest

from bet_sizing import build_recommendation, volume_weighted_entry


def _play(*, entry=0.5, sharps=3, tracked=7, evidence=1.0):
    return {
        "id": "event::market::yes",
        "agreeing_wallet_count": sharps,
        "tracked_wallet_count": tracked,
        "current_price": 0.91,
        "average_entry_price": 0.44,
        "orderbook": {
            "asks": [{"price": str(entry), "size": "100000"}],
            "bids": [{"price": str(entry - 0.01), "size": "100000"}],
        },
        "evidence_inputs": {
            "combined_amount": evidence,
            "relative_size": evidence,
            "top_category": evidence,
            "adjusted_category_hit_rate": evidence,
            "category_sample_size": evidence,
        },
    }


def test_current_executable_ask_is_probability_baseline_not_confidence_or_snapshot_price():
    recommendation = build_recommendation(_play(entry=0.42), 10000)

    assert recommendation["available"] is True
    assert recommendation["current_user_entry_price"] == pytest.approx(0.42)
    assert recommendation["baseline_probability"] == pytest.approx(0.42)
    assert recommendation["baseline_probability"] != pytest.approx(0.91)


def test_weak_evidence_produces_zero_kelly_and_no_forced_bet():
    recommendation = build_recommendation(_play(sharps=1, evidence=0.0), 10000)

    assert recommendation["evidence_adjustment"] == 0
    assert (
        recommendation["estimated_win_probability"]
        == recommendation["baseline_probability"]
    )
    assert recommendation["full_kelly_fraction"] == 0
    assert recommendation["final_recommended_fraction"] == 0
    assert recommendation["recommended_amount"] == 0


def test_half_kelly_and_three_sharp_cap_are_applied():
    recommendation = build_recommendation(
        _play(entry=0.5, sharps=3, evidence=1.0), 10000
    )

    assert recommendation["half_kelly_fraction"] == pytest.approx(
        recommendation["full_kelly_fraction"] * 0.5
    )
    assert recommendation["final_recommended_fraction"] <= 0.03
    assert recommendation["global_risk_cap"] == 0.05


def test_volume_weighted_entry_walks_multiple_ask_levels():
    fill = volume_weighted_entry(
        [{"price": "0.50", "size": "100"}, {"price": "0.60", "size": "100"}],
        100,
    )

    assert fill is not None
    assert fill["levels_used"] == 2
    assert fill["effective_entry_price"] == pytest.approx(100 / (100 + (50 / 0.6)))
    assert fill["liquidity_limited"] is False


def test_missing_orderbook_never_creates_fake_recommendation():
    play = _play()
    play["orderbook"] = {}

    recommendation = build_recommendation(play, 10000)

    assert recommendation["available"] is False
    assert "executable ask" in recommendation["reason"].lower()


def test_bet_below_clob_minimum_is_not_recommended():
    play = _play(entry=0.94, sharps=1, evidence=0.741)
    play["orderbook"]["min_order_size"] = "5"

    recommendation = build_recommendation(play, 10000)

    assert recommendation["half_kelly_fraction"] > 0
    assert recommendation["final_recommended_fraction"] == 0
    assert recommendation["recommended_amount"] == 0
    assert recommendation["minimum_executable_amount"] == pytest.approx(4.70)
