from __future__ import annotations

import pytest

from bet_sizing import (
    MISSING_EXECUTABLE_PRICE,
    SLIPPAGE_ABOVE_MAX,
    build_recommendation,
    calculate_evidence_score,
    volume_weighted_entry,
)


def _play(*, entry=0.5, reference=0.44, sharps=3, tracked=7, evidence=1.0, fair=0.54):
    return {
        "id": "event::market::yes",
        "agreeing_wallet_count": sharps,
        "raw_sharp_count": sharps,
        "lead_sharp_count": sharps,
        "supporting_sharp_count": 0,
        "weighted_sharp_count": float(sharps),
        "has_lead_sharp": True,
        "tracked_wallet_count": tracked,
        "current_price": 0.91,
        "expected_fee_fraction": 0.0,
        "average_entry_price": reference,
        "sharp_reference_entry_price": reference,
        "orderbook": {
            "asks": [{"price": str(entry), "size": "100000"}],
            "bids": [{"price": str(entry - 0.01), "size": "100000"}],
        },
        "fair_price": {
            "status": "AVAILABLE",
            "fair_probability": fair,
            "source_count": 2,
            "source_dispersion": 0.01,
        },
        "liquidity_quality": {"score": 100},
        "evidence_inputs": {
            "combined_amount": evidence,
            "relative_size": evidence,
            "top_category": evidence,
            "adjusted_category_hit_rate": evidence,
            "category_sample_size": evidence,
        },
    }


def test_independent_fair_price_is_probability_baseline_not_entry_or_snapshot_price():
    recommendation = build_recommendation(_play(entry=0.42), 10000)

    assert recommendation["available"] is True
    assert recommendation["current_user_entry_price"] == pytest.approx(0.42)
    assert recommendation["baseline_probability"] == pytest.approx(0.54)
    assert recommendation["baseline_probability"] != pytest.approx(0.91)
    assert recommendation["price_slippage_fraction"] == pytest.approx(
        (0.42 - 0.44) / 0.44
    )


def test_weak_evidence_produces_zero_kelly_and_no_forced_bet():
    recommendation = build_recommendation(_play(sharps=1, evidence=0.0, fair=0.5), 10000)

    assert recommendation["calculated_edge"] == 0
    assert recommendation["full_kelly_fraction"] == 0
    assert recommendation["final_recommended_fraction"] == 0
    assert recommendation["recommended_amount"] == 0


def test_one_verified_sharp_is_neutral_before_other_real_evidence():
    play = _play(sharps=1, tracked=7, evidence=0.5)

    evidence = calculate_evidence_score(play)
    recommendation = build_recommendation(play, 10000)

    assert evidence["components"]["sharps_consensus"] == pytest.approx(0.5)
    assert evidence["score"] == pytest.approx(0.5)
    assert recommendation["raw_fair_probability"] == pytest.approx(0.54)


def test_realistic_one_sharp_evidence_produces_bounded_positive_size():
    play = _play(entry=0.469, sharps=1, tracked=7)
    play["evidence_inputs"] = {
        "combined_amount": 0.754529,
        "relative_size": 0.398361,
        "top_category": None,
        "adjusted_category_hit_rate": 0.518868,
        "category_sample_size": 0.313018,
    }

    recommendation = build_recommendation(play, 10000)

    assert recommendation["recommendation_version"] == "v3"
    assert recommendation["evidence_score"] > 0.5
    assert recommendation["uncertainty_haircut"] < 1
    assert recommendation["estimated_win_probability"] > 0.469
    assert recommendation["recommended_amount"] > 0
    assert recommendation["recommended_shares"] == pytest.approx(
        recommendation["recommended_amount"]
        / recommendation["current_user_entry_price"]
    )


def test_half_kelly_and_three_sharp_cap_are_applied():
    recommendation = build_recommendation(
        _play(entry=0.5, sharps=3, evidence=1.0), 10000
    )

    assert recommendation["half_kelly_fraction"] == pytest.approx(
        recommendation["full_kelly_fraction"] * 0.5
    )
    assert recommendation["final_recommended_fraction"] <= 0.03
    assert recommendation["global_risk_cap"] == 0.02


def test_volume_weighted_entry_walks_multiple_ask_levels():
    fill = volume_weighted_entry(
        [{"price": "0.50", "size": "100"}, {"price": "0.60", "size": "100"}],
        100,
    )

    assert fill is not None
    assert fill["levels_used"] == 2
    assert fill["effective_entry_price"] == pytest.approx(100 / (100 + (50 / 0.6)))
    assert fill["liquidity_limited"] is False


def test_insufficient_depth_reduces_the_recommendation_and_remains_explicit():
    play = _play(entry=0.4, reference=0.4)
    play["orderbook"]["asks"] = [{"price": "0.40", "size": "20"}]

    recommendation = build_recommendation(play, 10000)

    assert 0 < recommendation["recommended_amount"] <= 8
    assert recommendation["liquidity_limited"] is True
    assert recommendation["unfilled_amount"] > 0


def test_missing_orderbook_never_creates_fake_recommendation():
    play = _play()
    play["orderbook"] = {}

    recommendation = build_recommendation(play, 10000)

    assert recommendation["available"] is False
    assert "executable ask" in recommendation["reason"].lower()
    assert recommendation["passes_slippage_rule"] is False
    assert recommendation["slippage_rejection_reason"] == MISSING_EXECUTABLE_PRICE


def test_bet_below_clob_minimum_is_not_recommended():
    play = _play(entry=0.94, sharps=1, evidence=0.501, fair=0.94002)
    play["orderbook"]["min_order_size"] = "5"

    recommendation = build_recommendation(play, 10000)

    assert recommendation["half_kelly_fraction"] > 0
    assert recommendation["final_recommended_fraction"] == 0
    assert recommendation["recommended_amount"] == 0
    assert recommendation["recommended_shares"] == 0
    assert recommendation["minimum_executable_amount"] == pytest.approx(4.70)


def test_supporting_sharp_is_half_weighted_for_risk_cap_not_fair_probability():
    single = _play(entry=0.5, sharps=1, tracked=7, evidence=1.0)
    mixed = _play(entry=0.5, sharps=2, tracked=7, evidence=1.0)
    mixed.update(
        {
            "lead_sharp_count": 1,
            "supporting_sharp_count": 1,
            "weighted_sharp_count": 1.5,
        }
    )
    mixed["evidence_inputs"]["top_category"] = 0.75
    full = _play(entry=0.5, sharps=2, tracked=7, evidence=1.0)

    single_evidence = calculate_evidence_score(single)
    mixed_evidence = calculate_evidence_score(mixed)
    full_evidence = calculate_evidence_score(full)
    single_recommendation = build_recommendation(single, 10000)
    mixed_recommendation = build_recommendation(mixed, 10000)
    full_recommendation = build_recommendation(full, 10000)

    assert single_evidence["consensus_details"]["weighted_sharps"] == 1.0
    assert mixed_evidence["consensus_details"]["weighted_sharps"] == 1.5
    assert full_evidence["consensus_details"]["weighted_sharps"] == 2.0
    assert (
        full_evidence["components"]["sharps_consensus"]
        > mixed_evidence["components"]["sharps_consensus"]
        > single_evidence["components"]["sharps_consensus"]
    )
    assert mixed_recommendation["sharp_risk_cap"] == pytest.approx(0.015)
    assert full_recommendation["raw_fair_probability"] == mixed_recommendation["raw_fair_probability"]
    assert mixed_recommendation["recommended_amount"] >= single_recommendation["recommended_amount"]


def test_recommendation_rejects_trade_without_a_lead_sharp():
    play = _play(sharps=2)
    play.update(
        {
            "lead_sharp_count": 0,
            "supporting_sharp_count": 2,
            "weighted_sharp_count": 1.0,
            "has_lead_sharp": False,
        }
    )

    recommendation = build_recommendation(play, 10000)

    assert recommendation["available"] is False
    assert "Lead Sharp" in recommendation["reason"]


def test_exactly_five_percent_unfavorable_slippage_is_allowed():
    recommendation = build_recommendation(
        _play(entry=0.42, reference=0.4), 10000
    )

    assert recommendation["unfavorable_slippage_pct"] == pytest.approx(5.0)
    assert recommendation["passes_slippage_rule"] is True
    assert recommendation["slippage_rejection_reason"] is None


def test_more_than_five_percent_unfavorable_slippage_is_rejected():
    recommendation = build_recommendation(
        _play(entry=0.42004, reference=0.4), 10000
    )

    assert recommendation["unfavorable_slippage_pct"] == pytest.approx(5.01)
    assert recommendation["passes_slippage_rule"] is False
    assert recommendation["slippage_rejection_reason"] == SLIPPAGE_ABOVE_MAX


def test_better_entry_has_negative_slippage_and_remains_allowed():
    recommendation = build_recommendation(
        _play(entry=0.38, reference=0.4), 10000
    )

    assert recommendation["unfavorable_slippage_pct"] == pytest.approx(-5.0)
    assert recommendation["passes_slippage_rule"] is True


def test_slippage_uses_depth_weighted_effective_entry_not_top_ask():
    play = _play(entry=0.4, reference=0.4)
    play["orderbook"]["asks"] = [
        {"price": "0.40", "size": "7.5"},
        {"price": "0.43", "size": "100000"},
    ]

    recommendation = build_recommendation(play, 10000)

    assert recommendation["current_top_ask_price"] == pytest.approx(0.4)
    assert recommendation["effective_entry_price"] > 0.4
    assert recommendation["unfavorable_slippage_pct"] == pytest.approx(
        (
            recommendation["effective_entry_price"]
            - recommendation["sharp_reference_entry_price"]
        )
        / recommendation["sharp_reference_entry_price"]
        * 100
    )
