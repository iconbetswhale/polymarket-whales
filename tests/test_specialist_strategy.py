from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bet_sizing import SizingConfig, build_recommendation
from specialist_strategy import (
    BAGWELL,
    BREAK_THE_BANK,
    DABOSSHOGG,
    EVHUNTER,
    FORMAL_CUPCAKE,
    LILYBAEUM,
    PORTLY_DERIVATION,
    SINENOONEEI,
    STRATEGY_ID,
    confidence_score,
    recommendation_units,
    specialist_strategy_positions,
)
from trade_scoring import build_trades_to_play


def _position(
    wallet: str,
    outcome: str,
    *,
    category: str = "Tennis",
    market_type: str = "Moneyline",
    units: float = 1.0,
    price: float = 0.45,
    condition: str = "tennis-main",
    volume: float = 10_000,
) -> dict:
    now = datetime.now(timezone.utc)
    label = {
        BAGWELL: "Bagwell306",
        LILYBAEUM: "Lilybaeum",
        DABOSSHOGG: "DaBossHogg",
        FORMAL_CUPCAKE: "Formal-Cupcake",
        BREAK_THE_BANK: "BreakTheBank",
        PORTLY_DERIVATION: "Portly-Derivation",
        EVHUNTER: "EVhunter69",
        SINENOONEEI: "SineNooneEI",
    }[wallet]
    base = {
        BAGWELL: 875.0,
        LILYBAEUM: 575.0,
        DABOSSHOGG: 5050.0,
        FORMAL_CUPCAKE: 1300.0,
        BREAK_THE_BANK: 116150.0,
        PORTLY_DERIVATION: 9450.0,
        EVHUNTER: 575.0,
        SINENOONEEI: 10475.0,
    }[wallet]
    event_slug = (
        "tennis-player-a-player-b"
        if category == "Tennis"
        else "fifwc-usa-par-2026-08-10"
        if category == "Soccer"
        else "wnba-ny-las"
    )
    return {
        "wallet_address": wallet,
        "wallet_label": label,
        "position_size_usd": units * base,
        "signal_position_size_usd": units * base,
        "signal_units": units,
        "estimated_units": units,
        "estimated_base_unit": base,
        "minimum_position_units": 1.0,
        "actionable_position_units": 1.0,
        "status": "open",
        "lifecycle_status": "upcoming",
        "market_open": True,
        "resolution_time": (now + timedelta(hours=4)).isoformat(),
        "event_slug": event_slug,
        "market_slug": event_slug if market_type == "Moneyline" else condition,
        "condition_id": condition,
        "clob_token_id": f"{condition}-{outcome}",
        "event_title": (
            "Player A vs. Player B"
            if category == "Tennis"
            else "Boston Celtics vs. New York Knicks"
            if category == "NBA"
            else "Fighter A vs. Fighter B"
            if category == "MMA"
            else "New York Liberty vs. Los Angeles Sparks"
        ),
        "market_title": (
            f"{category} Moneyline"
            if market_type == "Moneyline"
            else f"{market_type} {outcome}"
        ),
        "sports_market_type": market_type,
        "outcome": outcome,
        "league": category,
        "category": category,
        "canonical_category_id": category.lower(),
        "canonical_league_id": category.lower(),
        "configured_top_categories": [category],
        "configured_top_category_ids": [category.lower()],
        "category_signal_role": "CONDITIONAL_ORIGINATOR",
        "category_consensus_role": "DIRECTIONAL_CORE",
        "category_signal_quality_weight": 1.0,
        "category_signal_minimum_originator_units": 1.0,
        "category_signal_requires_clean_directional": True,
        "two_sided_status": "CLEAN_DIRECTIONAL",
        "opposing_exposure_ratio": 0.0,
        "average_entry_price": price,
        "current_price": price,
        "volume": volume,
    }


def _units() -> dict:
    return {
        BAGWELL: {"estimated_base_unit": 875.0},
        LILYBAEUM: {"estimated_base_unit": 575.0},
        DABOSSHOGG: {"estimated_base_unit": 5050.0},
        FORMAL_CUPCAKE: {"estimated_base_unit": 1300.0},
        BREAK_THE_BANK: {"estimated_base_unit": 116150.0},
        PORTLY_DERIVATION: {"estimated_base_unit": 9450.0},
        EVHUNTER: {"estimated_base_unit": 575.0},
        SINENOONEEI: {"estimated_base_unit": 10475.0},
    }


def test_validated_specialist_sizing_and_confidence():
    assert recommendation_units([BAGWELL], {BAGWELL: 1.0}, "Tennis")["units"] == 1.0
    assert recommendation_units([LILYBAEUM], {LILYBAEUM: 1.0}, "Tennis")["units"] == 0.75
    assert recommendation_units([DABOSSHOGG], {DABOSSHOGG: 1.0}, "Tennis")["units"] == 1.0
    assert recommendation_units([EVHUNTER], {EVHUNTER: 1.0}, "Tennis")["units"] == 0.5
    assert recommendation_units([SINENOONEEI], {SINENOONEEI: 1.0}, "Tennis")["units"] == 1.0
    assert recommendation_units(
        [BAGWELL, LILYBAEUM], {BAGWELL: 3.0, LILYBAEUM: 2.0}, "Tennis"
    )["units"] == 2.0
    assert recommendation_units(
        [BAGWELL, LILYBAEUM, DABOSSHOGG],
        {BAGWELL: 1.0, LILYBAEUM: 1.0, DABOSSHOGG: 1.0},
        "Tennis",
    )["units"] == 3.0
    assert recommendation_units(
        [FORMAL_CUPCAKE], {FORMAL_CUPCAKE: 1.4}, "WNBA"
    )["units"] == 1.25
    assert confidence_score([BAGWELL], "Tennis")[0] == 90
    assert confidence_score([LILYBAEUM], "Tennis")[0] == 84
    assert confidence_score([DABOSSHOGG], "Tennis")[0] == 88
    assert confidence_score([EVHUNTER], "Tennis")[0] == 82
    assert confidence_score([SINENOONEEI], "Tennis")[0] == 88
    assert confidence_score([BAGWELL, LILYBAEUM], "Tennis")[0] == 97
    assert confidence_score([BAGWELL, LILYBAEUM, DABOSSHOGG], "Tennis")[0] == 99
    assert confidence_score([FORMAL_CUPCAKE], "WNBA")[0] == 90
    assert recommendation_units(
        [BREAK_THE_BANK], {BREAK_THE_BANK: 1.0}, "Soccer"
    )["units"] == 0.5
    assert recommendation_units(
        [BREAK_THE_BANK], {BREAK_THE_BANK: 2.0}, "Soccer"
    )["units"] == 1.0
    assert confidence_score([BREAK_THE_BANK], "Soccer")[0] == 84
    assert recommendation_units(
        [PORTLY_DERIVATION], {PORTLY_DERIVATION: 1.0}, "NBA", "Spread"
    )["units"] == 1.0
    assert recommendation_units(
        [PORTLY_DERIVATION], {PORTLY_DERIVATION: 1.0}, "NBA", "Moneyline"
    )["units"] == 0.75
    assert recommendation_units(
        [PORTLY_DERIVATION], {PORTLY_DERIVATION: 1.0}, "MMA", "Moneyline"
    )["units"] == 1.0
    assert confidence_score([PORTLY_DERIVATION], "NBA", "Spread")[0] == 92
    assert confidence_score([PORTLY_DERIVATION], "NBA", "Moneyline")[0] == 87
    assert confidence_score([PORTLY_DERIVATION], "MMA", "Moneyline")[0] == 91


def test_portly_derivation_only_selects_approved_nba_and_mma_main_markets():
    nba_spread = _position(
        PORTLY_DERIVATION,
        "Boston Celtics -4.5",
        category="NBA",
        market_type="Spread",
        condition="nba-main-spread",
        volume=20_000,
    )
    nba_alt_spread = _position(
        PORTLY_DERIVATION,
        "Boston Celtics -8.5",
        category="NBA",
        market_type="Spread",
        condition="nba-alt-spread",
        volume=500,
    )
    nba_moneyline = _position(
        PORTLY_DERIVATION,
        "Boston Celtics",
        category="NBA",
        market_type="Moneyline",
        condition="nba-moneyline",
    )
    nba_total = _position(
        PORTLY_DERIVATION,
        "Over 220.5",
        category="NBA",
        market_type="Total",
        condition="nba-total",
    )
    mma_moneyline = _position(
        PORTLY_DERIVATION,
        "Fighter A",
        category="MMA",
        market_type="Moneyline",
        condition="mma-moneyline",
    )
    mma_method = _position(
        PORTLY_DERIVATION,
        "Fighter A by decision",
        category="MMA",
        market_type="Method of Victory",
        condition="mma-method",
    )
    tennis = _position(
        PORTLY_DERIVATION,
        "Player A",
        category="Tennis",
        market_type="Moneyline",
        condition="portly-tennis",
    )

    selected = specialist_strategy_positions(
        [
            nba_spread,
            nba_alt_spread,
            nba_moneyline,
            nba_total,
            mma_moneyline,
            mma_method,
            tennis,
        ]
    )
    assert {row["condition_id"] for row in selected} == {
        "nba-main-spread",
        "nba-moneyline",
        "mma-moneyline",
    }


def test_breakthebank_only_selects_large_clean_soccer_moneylines():
    moneyline = _position(
        BREAK_THE_BANK,
        "United States",
        category="Soccer",
        market_type="Moneyline",
        units=1.0,
        condition="soccer-moneyline",
    )
    below_unit = _position(
        BREAK_THE_BANK,
        "United States",
        category="Soccer",
        market_type="Moneyline",
        units=0.99,
        condition="soccer-below-unit",
    )
    spread = _position(
        BREAK_THE_BANK,
        "United States -1.5",
        category="Soccer",
        market_type="Spread",
        units=2.0,
        condition="soccer-spread",
    )
    selected = specialist_strategy_positions([moneyline, below_unit, spread])
    assert [row["condition_id"] for row in selected] == ["soccer-moneyline"]


def test_tennis_selector_enforces_one_unit_price_cleanliness_and_main_market():
    rows = [
        _position(BAGWELL, "Player A"),
        _position(LILYBAEUM, "Player A", units=0.99, condition="below-unit"),
        _position(LILYBAEUM, "Player A", price=0.34, condition="below-price"),
        _position(LILYBAEUM, "Player A", market_type="First Set Moneyline", condition="first-set"),
        _position(LILYBAEUM, "Player A", market_type="Tennis Match Totals", condition="total-main", volume=5000),
        _position(LILYBAEUM, "Player A", market_type="Tennis Match Totals", condition="total-alt", volume=100),
    ]
    selected = specialist_strategy_positions(rows)
    assert {row["condition_id"] for row in selected} == {"tennis-main", "total-main"}


def test_sinenooneei_originates_only_tennis_match_moneylines():
    moneyline = _position(SINENOONEEI, "Player A", condition="sine-tennis-ml")
    spread = _position(
        SINENOONEEI,
        "Player A -2.5",
        market_type="Spread",
        condition="sine-tennis-spread",
    )
    total = _position(
        SINENOONEEI,
        "Over 22.5",
        market_type="Tennis Match Totals",
        condition="sine-tennis-total",
    )
    esports = _position(
        SINENOONEEI,
        "Team A",
        category="League of Legends",
        market_type="Moneyline",
        condition="sine-lol-ml",
    )
    below_unit = _position(
        SINENOONEEI,
        "Player A",
        units=0.99,
        condition="sine-below-unit",
    )
    below_price = _position(
        SINENOONEEI,
        "Player A",
        price=0.34,
        condition="sine-below-price",
    )

    selected = specialist_strategy_positions(
        [moneyline, spread, total, esports, below_unit, below_price]
    )
    assert [row["condition_id"] for row in selected] == ["sine-tennis-ml"]


def test_tennis_same_side_agreement_is_two_units_and_conflict_is_skipped():
    now = datetime.now(timezone.utc)
    agreement = specialist_strategy_positions(
        [_position(BAGWELL, "Player A"), _position(LILYBAEUM, "Player A")]
    )
    plays = build_trades_to_play(
        agreement,
        unit_map=_units(),
        now=now,
        tracked_wallet_count=2,
        strategy_mode=STRATEGY_ID,
    )
    assert len(plays) == 1
    assert plays[0]["strategy_target_units"] == 2.0
    assert plays[0]["confidence_score"] == 97

    conflict = specialist_strategy_positions(
        [_position(BAGWELL, "Player A"), _position(LILYBAEUM, "Player B")]
    )
    diagnostics: list[dict] = []
    assert build_trades_to_play(
        conflict,
        unit_map=_units(),
        now=now,
        tracked_wallet_count=2,
        diagnostics=diagnostics,
        strategy_mode=STRATEGY_ID,
    ) == []
    assert {row["reason"] for row in diagnostics} == {"SPECIALIST_DIRECT_CONFLICT"}


def test_dabosshogg_originates_tennis_and_three_sharp_agreement_is_three_units():
    now = datetime.now(timezone.utc)
    agreement = specialist_strategy_positions(
        [
            _position(BAGWELL, "Player A"),
            _position(LILYBAEUM, "Player A"),
            _position(DABOSSHOGG, "Player A"),
        ]
    )
    plays = build_trades_to_play(
        agreement,
        unit_map=_units(),
        now=now,
        tracked_wallet_count=3,
        strategy_mode=STRATEGY_ID,
    )
    assert len(plays) == 1
    assert plays[0]["strategy_target_units"] == 3.0
    assert plays[0]["confidence_score"] == 99

    daboss_total = specialist_strategy_positions(
        [
            _position(
                DABOSSHOGG,
                "Over 22.5",
                market_type="Tennis Match Totals",
                condition="daboss-total",
            )
        ]
    )
    assert [row["condition_id"] for row in daboss_total] == ["daboss-total"]


def test_formal_cupcake_only_originates_wnba_full_game_spreads():
    spread = _position(
        FORMAL_CUPCAKE,
        "New York Liberty +4.5",
        category="WNBA",
        market_type="Spread",
        units=1.1,
        condition="wnba-spread",
    )
    moneyline = _position(
        FORMAL_CUPCAKE,
        "New York Liberty",
        category="WNBA",
        market_type="Moneyline",
        units=1.0,
        condition="wnba-moneyline",
    )
    selected = specialist_strategy_positions([spread, moneyline])
    assert [row["condition_id"] for row in selected] == ["wnba-spread"]
    plays = build_trades_to_play(
        selected,
        unit_map=_units(),
        now=datetime.now(timezone.utc),
        tracked_wallet_count=1,
        strategy_mode=STRATEGY_ID,
    )
    assert len(plays) == 1
    assert plays[0]["strategy_target_units"] == 1.1
    assert plays[0]["confidence_score"] == 90


def test_specialist_fixed_unit_sizing_uses_the_live_execution_path():
    play = {
        "model_strategy": STRATEGY_ID,
        "strategy_target_units": 2.0,
        "strategy_sizing_mode": "VALIDATED_FLAT_COPY_UNITS",
        "lead_sharp_count": 2,
        "has_lead_sharp": True,
        "tradeClassification": "STANDARD",
        "average_entry_price": 0.46,
        "sharp_reference_entry_price": 0.46,
        "orderbook": {"asks": [{"price": 0.46, "size": 10_000}]},
    }
    recommendation = build_recommendation(
        play,
        10_000,
        SizingConfig(unit_percentage=0.01),
    )
    assert recommendation["recommended_amount"] == 200.0
    assert recommendation["raw_recommended_units"] == 2.0
    assert recommendation["trade_grade"] == "SPECIALIST_SIGNAL"
