from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from bet_sizing import (
    SLIPPAGE_ABOVE_MAX,
    SizingConfig,
    build_recommendation,
    entry_movement_stake_multiplier,
)
from decision_engine import enrich_trade_decision
from recommendation_service import evaluate_trade_recommendation
from three_sharp_strategy import (
    BREAK_THE_BANK,
    DINGWIN,
    EVHUNTER,
    FERRARI,
    FORMAL_CUPCAKE,
    ONE_WIN_STREAK,
    OX4F2,
    PHONE_SCULPTOR,
    SHARPS,
    SOARIN,
    SPORTSMASTER,
    STRATEGY_ID,
    confidence_score,
    conviction_multiplier,
    main_mlb_strategy_positions,
    recommendation_units,
)
from trade_scoring import (
    _is_three_sharp_actionable_wallet_position,
    _mlb_hybrid_decision,
    build_trades_to_play,
)


FORMAL = FORMAL_CUPCAKE
PHONE = PHONE_SCULPTOR


def test_approved_simulation_sizing_is_precise_by_wallet_and_consensus():
    assert recommendation_units([FORMAL])["units"] == 1.0
    assert recommendation_units([SOARIN])["units"] == 0.0
    assert recommendation_units([PHONE])["units"] == 0.85
    assert recommendation_units([FORMAL, PHONE])["units"] == 1.15625
    assert recommendation_units([FORMAL, SOARIN, PHONE])["units"] == 1.295


def test_confidence_uses_approved_high_trust_bands():
    assert confidence_score([FORMAL])[0] == 91
    assert confidence_score([SOARIN])[0] == 0
    assert confidence_score([PHONE])[0] == 87
    assert confidence_score([FORMAL, SOARIN])[0] == 93
    assert confidence_score([FORMAL, SOARIN, PHONE])[0] == 98


def test_evhunter_is_a_half_weight_mlb_originator_without_core_score_inflation():
    assert recommendation_units([EVHUNTER], {EVHUNTER: 1.0})["units"] == 0.5
    assert confidence_score([EVHUNTER], {EVHUNTER: 1.0})[0] == 82

    formal_only = recommendation_units([FORMAL], {FORMAL: 1.0})
    supported = recommendation_units(
        [FORMAL, EVHUNTER],
        {FORMAL: 1.0, EVHUNTER: 1.0},
    )
    assert supported["units"] > formal_only["units"]
    assert confidence_score(
        [FORMAL, EVHUNTER],
        {FORMAL: 1.0, EVHUNTER: 1.0},
    )[0] == 91


def test_capped_conviction_tiers_scale_each_wallet_against_its_own_unit():
    assert conviction_multiplier(1.49) == 1.0
    assert conviction_multiplier(1.5) == 1.1
    assert conviction_multiplier(2.5) == 1.25
    assert conviction_multiplier(5.0) == 1.4
    assert conviction_multiplier(10.0) == 1.55
    sizing = recommendation_units(
        [FORMAL, PHONE],
        {FORMAL: 10.0, PHONE: 2.5},
    )
    assert sizing["units"] == 1.6328125
    assert sizing["conviction_multipliers"] == {
        FORMAL: 1.55,
        PHONE: 1.25,
    }
    assert sizing["sizing_mode"] == "WEIGHTED_DIRECTIONAL_CONVICTION_UNITS"
    assert confidence_score([FORMAL], {FORMAL: 10.0})[0] == 91


def test_live_recommendation_amount_uses_scaled_units_not_flat_fallback():
    sizing = recommendation_units([FORMAL], {FORMAL: 10.0})
    play = {
        **_play(),
        "strategy_target_units": sizing["units"],
        "strategy_sizing": sizing,
        "strategy_sizing_mode": sizing["sizing_mode"],
    }
    recommendation = build_recommendation(play, 10_000, SizingConfig())
    assert sizing["units"] == 1.55
    assert recommendation["recommended_amount"] == 155.0
    assert recommendation["raw_recommended_units"] == 1.55
    assert (
        recommendation["strategy_sizing_mode"]
        == "WEIGHTED_DIRECTIONAL_CONVICTION_UNITS"
    )


@pytest.mark.parametrize(
    ("movement_pct", "expected"),
    [
        (3.0, 1.0),
        (4.0, 0.75),
        (5.0, 0.50),
        (5.01, 0.0),
        (-6.2, 1.062),
        (-7.5, 1.075),
        (-20.0, 1.10),
    ],
)
def test_entry_movement_adjustment_is_tapered_and_capped(movement_pct, expected):
    assert entry_movement_stake_multiplier(movement_pct) == pytest.approx(expected)


def test_fixed_unit_strategy_rejects_more_than_five_percent_adverse_movement():
    play = {
        **_play(),
        "average_entry_price": 0.40,
        "sharp_reference_entry_price": 0.40,
        "orderbook": {
            "asks": [{"price": 0.421, "size": 10_000}],
            "bids": [{"price": 0.42, "size": 10_000}],
        },
    }
    recommendation = build_recommendation(play, 10_000, SizingConfig())
    evaluation = evaluate_trade_recommendation(
        play, 10_000, SizingConfig(), now=datetime.now(timezone.utc)
    )

    assert recommendation["unfavorable_slippage_pct"] == pytest.approx(5.25)
    assert recommendation["passes_slippage_rule"] is False
    assert recommendation["slippage_rejection_reason"] == SLIPPAGE_ABOVE_MAX
    assert evaluation["model_tracker_eligible"] is False
    assert evaluation["model_tracker_rejection_reason"] == SLIPPAGE_ABOVE_MAX


def test_fixed_unit_strategy_tapers_adverse_and_modestly_boosts_favorable_prices():
    adverse = {
        **_play(),
        "strategy_target_units": 1.0,
        "average_entry_price": 0.40,
        "sharp_reference_entry_price": 0.40,
        "orderbook": {"asks": [{"price": 0.416, "size": 10_000}]},
    }
    favorable = {
        **_play(),
        "strategy_target_units": 1.0,
        "average_entry_price": 0.48,
        "sharp_reference_entry_price": 0.48,
        "orderbook": {"asks": [{"price": 0.45, "size": 10_000}]},
    }

    adverse_recommendation = build_recommendation(adverse, 10_000, SizingConfig())
    favorable_recommendation = build_recommendation(favorable, 10_000, SizingConfig())

    assert adverse_recommendation["unfavorable_slippage_pct"] == pytest.approx(4.0)
    assert adverse_recommendation["entry_movement_stake_multiplier"] == pytest.approx(0.75)
    assert adverse_recommendation["recommended_amount"] == 75.0
    assert favorable_recommendation["unfavorable_slippage_pct"] == pytest.approx(-6.25)
    assert favorable_recommendation["entry_movement_stake_multiplier"] == pytest.approx(1.0625)
    assert favorable_recommendation["recommended_amount"] == 106.0


def test_one_cent_rounding_does_not_hide_formal_cupcake_full_unit():
    position = {
        "wallet_address": FORMAL,
        "position_size_usd": 1299.99,
        "estimated_base_unit": 1300.0,
        "actionable_position_units": 1.0,
    }
    assert _is_three_sharp_actionable_wallet_position(position, {}, {}) is True


def test_formal_cupcake_rounded_full_unit_builds_a_standard_live_play():
    now = datetime.now(timezone.utc)
    position = {
        "wallet_address": FORMAL,
        "wallet_label": "Formal-Cupcake",
        "position_size_usd": 1299.99,
        "signal_position_size_usd": 1299.99,
        "estimated_base_unit": 1300.0,
        "minimum_position_units": 0.5,
        "actionable_position_units": 1.0,
        "status": "open",
        "lifecycle_status": "upcoming",
        "market_open": True,
        "resolution_time": (now + timedelta(hours=4)).isoformat(),
        "event_slug": "mlb-wsh-phi-2026-08-03",
        "market_slug": "mlb-wsh-phi-2026-08-03",
        "condition_id": "formal-nationals-condition",
        "clob_token_id": "formal-nationals-token",
        "event_title": "Washington Nationals vs. Philadelphia Phillies",
        "market_title": "Washington Nationals vs. Philadelphia Phillies",
        "outcome": "Washington Nationals",
        "league": "MLB",
        "category": "MLB",
        "canonical_category_id": "mlb",
        "canonical_league_id": "mlb",
        "average_entry_price": 0.40,
        "current_price": 0.41,
    }
    plays = build_trades_to_play(
        [position],
        unit_map={FORMAL: {"estimated_base_unit": 1300.0}},
        now=now,
        tracked_wallet_count=3,
        strategy_mode=STRATEGY_ID,
    )
    assert len(plays) == 1
    assert plays[0]["outcome"] == "Washington Nationals"
    assert plays[0]["tradeClassification"] == "STANDARD"
    assert plays[0]["confidence_score"] == 91
    assert plays[0]["strategy_target_units"] == 1.0


def test_decision_quality_does_not_overwrite_three_sharp_trust_score():
    play = {
        **_play(),
        "confidence_score": 85,
        "confidenceScore": 85,
        "score_breakdown": {"architecture": "mlb_weighted_directional_v1"},
        "orderbook": {"asks": [], "bids": []},
        "category_metrics": [],
    }
    enriched = enrich_trade_decision(
        play,
        {
            "status": "UNAVAILABLE",
            "composite_probability": None,
            "provider_quotes": [],
        },
    )
    assert enriched["confidence_score"] == 85
    assert enriched["confidenceScore"] == 85
    assert enriched["score_breakdown"]["architecture"] == "mlb_weighted_directional_v1"
    assert enriched["market_quality_score"] >= 0


def test_main_market_scope_keeps_only_full_game_moneyline():
    def row(address, condition, market_type, line=None, volume=0):
        return {
            "wallet_address": address,
            "league": "MLB",
            "event_slug": "mlb-a-b-2026-08-02",
            "condition_id": condition,
            "market_slug": condition,
            "sports_market_type": market_type,
            "market_line": line,
            "volume": volume,
        }

    rows = [
        row(FORMAL, "ml", "Moneyline"),
        row(SOARIN, "spread-main", "Spread", 1.5),
        row(PHONE, "spread-alt", "Spread", 2.5),
        row(FORMAL, "total-main", "Total", 8.5, 5000),
        row(SOARIN, "total-main", "Total", 8.5, 5000),
        row(PHONE, "total-alt", "Total", 9.5, 500),
        row("0xnot-approved", "other", "Moneyline"),
    ]

    selected = main_mlb_strategy_positions(rows)
    assert {row["condition_id"] for row in selected} == {"ml"}


def test_event_winner_slug_is_recognized_as_moneyline_when_provider_omits_label():
    event_slug = "mlb-phillies-mets-2026-08-02"
    selected = main_mlb_strategy_positions(
        [
            {
                "wallet_address": FORMAL,
                "league": "MLB",
                "event_slug": event_slug,
                "market_slug": event_slug,
                "condition_id": "winner-condition",
            }
        ]
    )
    assert len(selected) == 1


def test_opposing_primary_is_a_strict_veto():
    group = [{"wallet_address": FORMAL}]
    opposing = [{"wallet_address": PHONE}]
    profiles = [{"trade_category_id": "mlb"}]
    decision = _mlb_hybrid_decision(
        group,
        opposing,
        profiles,
        profiles,
        {},
        {},
        STRATEGY_ID,
    )
    assert decision["qualified"] is False
    assert decision["reason"] == "MLB_WEIGHTED_PRIMARY_CONFLICT"


def test_shadow_overlays_cannot_originate_or_veto_a_live_play():
    assert recommendation_units([DINGWIN], {DINGWIN: 10.0})["qualified"] is False
    assert recommendation_units([BREAK_THE_BANK], {BREAK_THE_BANK: 10.0})["qualified"] is False

    baseline = recommendation_units([FORMAL], {FORMAL: 1.0})
    opposed = recommendation_units(
        [FORMAL],
        {FORMAL: 1.0},
        [DINGWIN, BREAK_THE_BANK],
        {DINGWIN: 10.0, BREAK_THE_BANK: 10.0},
    )
    assert opposed["qualified"] is True
    assert opposed["units"] < baseline["units"]
    assert opposed["veto_opposing_portfolio_weight"] == 0.0


def test_shadow_overlays_resize_in_the_direction_requested():
    baseline = recommendation_units([FORMAL], {FORMAL: 1.0})
    supported = recommendation_units(
        [FORMAL, DINGWIN, BREAK_THE_BANK],
        {FORMAL: 1.0, DINGWIN: 1.0, BREAK_THE_BANK: 1.0},
    )
    opposed = recommendation_units(
        [FORMAL],
        {FORMAL: 1.0},
        [DINGWIN, BREAK_THE_BANK],
        {DINGWIN: 1.0, BREAK_THE_BANK: 1.0},
    )
    assert supported["units"] > baseline["units"] > opposed["units"]


def _play() -> dict:
    now = datetime.now(timezone.utc)
    return {
        "id": "test-play",
        "model_strategy": STRATEGY_ID,
        "strategy_target_units": 0.95,
        "tradeClassification": "STANDARD",
        "mlb_hybrid_strategy": {"qualified": True, "execution_window_minutes": 30},
        "event_date_et": (now + timedelta(hours=1)).isoformat(),
        "market_open": True,
        "lifecycle_status": "upcoming",
        "orderbook_timestamp": now.isoformat(),
        "orderbook": {
            "asks": [{"price": 0.45, "size": 1000}],
            "bids": [{"price": 0.44, "size": 1000}],
        },
        "average_entry_price": 0.45,
        "sharp_reference_entry_price": 0.45,
        "agreeing_wallet_count": 1,
        "lead_sharp_count": 1,
        "has_lead_sharp": True,
        "selectedExecutionOption": {"sportsbook": "NoVIG"},
        "validation_ids": {},
    }


def test_strategy_sizing_does_not_require_fabricated_fair_price_or_kelly():
    recommendation = build_recommendation(_play(), 10_000, SizingConfig())
    assert recommendation["available"] is True
    assert recommendation["recommended_amount"] == 95.0
    assert recommendation["raw_recommended_units"] == 0.95
    assert recommendation["estimated_win_probability"] is None
    assert recommendation["fair_price_status"] == "NOT_REQUIRED_BY_WEIGHTED_MLB_STRATEGY"


def test_strategy_is_tracker_eligible_without_old_fair_price_gate():
    result = evaluate_trade_recommendation(
        _play(), 10_000, SizingConfig(), now=datetime.now(timezone.utc)
    )
    assert result["model_tracker_eligible"] is True
    assert result["model_tracker_rejection_reason"] is None
