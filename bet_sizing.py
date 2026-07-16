from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from config import MAX_UNFAVORABLE_SLIPPAGE_PCT
from decision_engine import uncertainty_adjusted_kelly
from execution_engine import ExecutionConfig, build_execution_plan
from risk_engine import RiskConfig, evaluate_portfolio_risk
from trade_research import POLICIES, RESEARCH_CLASSIFICATIONS, STANDARD


SLIPPAGE_ABOVE_MAX = "SLIPPAGE_ABOVE_MAX"
MISSING_EXECUTABLE_PRICE = "MISSING_EXECUTABLE_PRICE"
MISSING_SHARP_REFERENCE_PRICE = "MISSING_SHARP_REFERENCE_PRICE"


@dataclass(frozen=True)
class SizingConfig:
    unit_percentage: float = 0.01
    neutral_threshold: float = 0.50
    global_risk_cap: float = 0.02
    consensus_weight: float = 0.45
    combined_amount_weight: float = 0.20
    relative_size_weight: float = 0.15
    top_category_weight: float = 0.08
    category_hit_rate_weight: float = 0.08
    category_sample_weight: float = 0.04
    consensus_count_target: int = 4
    consensus_count_weight: float = 0.60
    consensus_percentage_weight: float = 0.40
    recommendation_version: str = "v4"


DEFAULT_SIZING_CONFIG = SizingConfig()
GRADE_RISK_CAPS = {
    "PASS": 0.0,
    "DISCOVERY": 0.0025,
    "B": 0.006,
    "A": 0.01,
    "A_PLUS": 0.015,
}
GRADE_EDGE_RELIABILITY = {
    "PASS": 0.0,
    "DISCOVERY": 0.25,
    "B": 0.35,
    "A": 0.50,
    "A_PLUS": 0.60,
}


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _interpolated_cap(
    weighted_sharps: float, points: tuple[tuple[float, float], ...]
) -> float:
    weighted_sharps = max(points[0][0], float(weighted_sharps))
    for index in range(1, len(points)):
        lower_count, lower_cap = points[index - 1]
        upper_count, upper_cap = points[index]
        if weighted_sharps <= upper_count:
            progress = (weighted_sharps - lower_count) / (
                upper_count - lower_count
            )
            return lower_cap + ((upper_cap - lower_cap) * progress)
    return points[-1][1]


def probability_adjustment_cap(sharps: float, unanimous: bool) -> float:
    if unanimous:
        return 0.12
    return _interpolated_cap(
        sharps, ((1.0, 0.02), (2.0, 0.04), (3.0, 0.07), (4.0, 0.10))
    )


def stake_risk_cap(sharps: float, unanimous: bool) -> float:
    if unanimous:
        return 0.05
    return _interpolated_cap(
        sharps, ((1.0, 0.01), (2.0, 0.02), (3.0, 0.03), (4.0, 0.04))
    )


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _component(value: Any) -> float:
    if value is None:
        return 0.5
    return clamp(_safe_float(value, 0.5), 0.0, 1.0)


def calculate_evidence_score(
    play: dict[str, Any], config: SizingConfig = DEFAULT_SIZING_CONFIG
) -> dict[str, Any]:
    inputs = play.get("evidence_inputs") or {}
    sharps = max(1, int(play.get("agreeing_wallet_count") or 1))
    lead_sharps = max(0, int(play.get("lead_sharp_count") or 0))
    supporting_sharps = max(
        0, int(play.get("supporting_sharp_count") or (sharps - lead_sharps))
    )
    weighted_sharps = max(
        0.0,
        _safe_float(
            play.get("weighted_sharp_count"),
            lead_sharps + (supporting_sharps * 0.5),
        ),
    )
    tracked = max(sharps, int(play.get("tracked_wallet_count") or sharps))
    additional_sharps = max(0.0, weighted_sharps - 1.0)
    count_target = max(2, int(config.consensus_count_target))
    count_strength = clamp(additional_sharps / (count_target - 1), 0.0, 1.0)
    percentage_strength = clamp(additional_sharps / max(1, tracked - 1), 0.0, 1.0)
    unanimous = sharps == tracked
    full_weight_unanimous = unanimous and abs(weighted_sharps - sharps) < 1e-9
    consensus = (
        1.0
        if full_weight_unanimous
        else 0.5
        + 0.5
        * (
            count_strength * config.consensus_count_weight
            + percentage_strength * config.consensus_percentage_weight
        )
    )

    components = {
        "sharps_consensus": consensus,
        "combined_amount": _component(inputs.get("combined_amount")),
        "relative_size": _component(inputs.get("relative_size")),
        "top_category": _component(inputs.get("top_category")),
        "adjusted_category_hit_rate": _component(
            inputs.get("adjusted_category_hit_rate")
        ),
        "category_sample_size": _component(inputs.get("category_sample_size")),
    }
    weights = {
        "sharps_consensus": config.consensus_weight,
        "combined_amount": config.combined_amount_weight,
        "relative_size": config.relative_size_weight,
        "top_category": config.top_category_weight,
        "adjusted_category_hit_rate": config.category_hit_rate_weight,
        "category_sample_size": config.category_sample_weight,
    }
    score = sum(components[name] * weights[name] for name in weights)
    return {
        "score": clamp(score, 0.0, 1.0),
        "components": components,
        "weights": weights,
        "consensus_details": {
            "agreeing_sharps": sharps,
            "raw_sharps": sharps,
            "lead_sharps": lead_sharps,
            "supporting_sharps": supporting_sharps,
            "weighted_sharps": weighted_sharps,
            "tracked_wallets": tracked,
            "count_strength": count_strength,
            "percentage_strength": percentage_strength,
            "component": consensus,
            "unanimous": unanimous,
            "full_weight_unanimous": full_weight_unanimous,
            "supporting_weight": 0.5,
        },
        "formula": "sum(component * configured_weight); Lead Sharps count 1.0 and Supporting Sharps count 0.5 before probability and Kelly sizing",
    }


def volume_weighted_entry(
    asks: list[dict[str, Any]], dollar_amount: float
) -> dict[str, Any] | None:
    if dollar_amount <= 0:
        return None
    levels = sorted(
        (
            (_safe_float(level.get("price")), _safe_float(level.get("size")))
            for level in asks
            if _safe_float(level.get("price")) > 0
            and _safe_float(level.get("size")) > 0
        ),
        key=lambda item: item[0],
    )
    if not levels:
        return None

    remaining = float(dollar_amount)
    total_cost = 0.0
    total_shares = 0.0
    levels_used = 0
    for price, shares_available in levels:
        level_cost = price * shares_available
        cost = min(remaining, level_cost)
        shares = cost / price
        total_cost += cost
        total_shares += shares
        remaining -= cost
        levels_used += 1
        if remaining <= 1e-9:
            break

    if total_shares <= 0:
        return None
    return {
        "effective_entry_price": total_cost / total_shares,
        "requested_amount": dollar_amount,
        "executable_amount": total_cost,
        "shares": total_shares,
        "levels_used": levels_used,
        "liquidity_limited": remaining > 1e-9,
        "unfilled_amount": max(0.0, remaining),
    }


def _kelly(
    entry_price: float, estimated_probability: float
) -> tuple[float, float, float]:
    if entry_price <= 0 or entry_price >= 1:
        return 0.0, 0.0, 0.0
    b = (1.0 - entry_price) / entry_price
    q = 1.0 - estimated_probability
    full = ((b * estimated_probability) - q) / b if b > 0 else 0.0
    full = max(0.0, full)
    return b, full, full * 0.5


def unavailable_recommendation(
    reason: str,
    config: SizingConfig = DEFAULT_SIZING_CONFIG,
    **details: Any,
) -> dict[str, Any]:
    return {
        "available": False,
        "reason": reason,
        "message": "Bet size unavailable - insufficient verified data",
        "recommendation_version": config.recommendation_version,
        "config": asdict(config),
        **details,
    }


def slippage_status(
    sharp_reference_entry_price: Any,
    current_top_ask_price: Any,
    effective_entry_price: Any,
) -> dict[str, Any]:
    sharp_reference = _safe_float(sharp_reference_entry_price, -1.0)
    top_ask = _safe_float(current_top_ask_price, -1.0)
    effective_entry = _safe_float(effective_entry_price, -1.0)
    if not 0 < effective_entry < 1:
        return {
            "sharp_reference_entry_price": sharp_reference
            if 0 < sharp_reference < 1
            else None,
            "current_top_ask_price": top_ask if 0 < top_ask < 1 else None,
            "effective_entry_price": None,
            "slippage_cents": None,
            "price_slippage_fraction": None,
            "unfavorable_slippage_pct": None,
            "passes_slippage_rule": False,
            "slippage_rejection_reason": MISSING_EXECUTABLE_PRICE,
        }
    if not 0 < sharp_reference < 1:
        return {
            "sharp_reference_entry_price": None,
            "current_top_ask_price": top_ask if 0 < top_ask < 1 else None,
            "effective_entry_price": effective_entry,
            "slippage_cents": None,
            "price_slippage_fraction": None,
            "unfavorable_slippage_pct": None,
            "passes_slippage_rule": False,
            "slippage_rejection_reason": MISSING_SHARP_REFERENCE_PRICE,
        }
    movement = effective_entry - sharp_reference
    fraction = movement / sharp_reference
    unfavorable_pct = fraction * 100.0
    passes = unfavorable_pct <= MAX_UNFAVORABLE_SLIPPAGE_PCT + 1e-9
    return {
        "sharp_reference_entry_price": sharp_reference,
        "current_top_ask_price": top_ask if 0 < top_ask < 1 else None,
        "effective_entry_price": effective_entry,
        "slippage_cents": movement * 100.0,
        "price_slippage_fraction": fraction,
        "unfavorable_slippage_pct": unfavorable_pct,
        "passes_slippage_rule": passes,
        "slippage_rejection_reason": None if passes else SLIPPAGE_ABOVE_MAX,
    }


def build_recommendation(
    play: dict[str, Any],
    bankroll: float,
    config: SizingConfig = DEFAULT_SIZING_CONFIG,
    risk_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bankroll = _safe_float(bankroll)
    if bankroll <= 0:
        return unavailable_recommendation("Bankroll must be greater than zero.", config)
    classification = str(play.get("tradeClassification") or STANDARD)
    if classification == STANDARD and (
        int(play.get("lead_sharp_count") or 0) < 1
        or not bool(play.get("has_lead_sharp"))
    ):
        return unavailable_recommendation(
            "At least one verified Lead Sharp is required for this trade.", config
        )

    orderbook = play.get("orderbook") or {}
    asks = orderbook.get("asks") or []
    valid_asks = sorted(
        [
            level
            for level in asks
            if 0 < _safe_float(level.get("price")) < 1
            and _safe_float(level.get("size")) > 0
        ],
        key=lambda level: _safe_float(level.get("price")),
    )
    if not valid_asks:
        return unavailable_recommendation(
            "A live executable ask is unavailable for this outcome.",
            config,
            **slippage_status(
                play.get("sharp_reference_entry_price")
                or play.get("average_entry_price"),
                None,
                None,
            ),
        )

    fair_price = play.get("fair_price") or {}
    fair_probability = _safe_float(fair_price.get("fair_probability"), -1.0)
    if fair_price.get("status") != "AVAILABLE" or not 0 < fair_probability < 1:
        return unavailable_recommendation(
            "An independent fair price is required before Kelly sizing.",
            config,
            fair_price_status=fair_price.get("status", "UNAVAILABLE"),
            fair_price_missing_reason=fair_price.get("missing_reason")
            or "NO_INDEPENDENT_FAIR_PRICE",
            estimated_win_probability=None,
            full_kelly_fraction=None,
            half_kelly_fraction=None,
        )
    if play.get("expected_fee_fraction") is None:
        return unavailable_recommendation(
            "Expected execution fees must be verified before Kelly sizing.",
            config,
            fair_price_status=fair_price.get("status"),
            fair_price_missing_reason="EXPECTED_FEES_UNAVAILABLE",
            estimated_win_probability=None,
            full_kelly_fraction=None,
            half_kelly_fraction=None,
        )
    expected_fee_fraction = max(0.0, _safe_float(play.get("expected_fee_fraction")))
    fee_adjusted_fair_probability = clamp(
        fair_probability - expected_fee_fraction, 0.01, 0.99
    )

    evidence = calculate_evidence_score(play, config)
    sharps = max(1, int(play.get("agreeing_wallet_count") or 1))
    lead_sharps = max(0, int(play.get("lead_sharp_count") or 0))
    supporting_sharps = max(
        0, int(play.get("supporting_sharp_count") or (sharps - lead_sharps))
    )
    weighted_sharps = max(
        0.0,
        _safe_float(
            play.get("weighted_sharp_count"),
            lead_sharps + (supporting_sharps * 0.5),
        ),
    )
    tracked = max(sharps, int(play.get("tracked_wallet_count") or sharps))
    unanimous = sharps == tracked
    full_weight_unanimous = unanimous and abs(weighted_sharps - sharps) < 1e-9
    policy = POLICIES[classification]
    adjustment_cap = (
        policy.probability_adjustment_cap
        if classification in RESEARCH_CLASSIFICATIONS
        else probability_adjustment_cap(weighted_sharps, full_weight_unanimous)
    )
    evidence_strength = clamp(
        (evidence["score"] - config.neutral_threshold)
        / (1.0 - config.neutral_threshold),
        0.0,
        1.0,
    )
    if classification in RESEARCH_CLASSIFICATIONS:
        opposing = max(0, int(play.get("rawContradictingSharpCount") or 0))
        agreeing = max(1, int(play.get("rawAgreeingSharpCount") or sharps))
        agreeing_weight = 0.25 if play.get("isNonCategoryConsensus") else 0.5
        net_research_weight = max(0.0, agreeing * agreeing_weight - opposing)
        evidence_strength *= clamp(net_research_weight / agreeing, 0.0, 1.0)
    evidence_adjustment = evidence_strength * adjustment_cap
    sharp_cap = (
        policy.risk_cap
        if classification in RESEARCH_CLASSIFICATIONS
        else stake_risk_cap(weighted_sharps, full_weight_unanimous)
    )
    trade_grade = str((play.get("trade_quality") or {}).get("grade") or "B")
    grade_risk_cap = GRADE_RISK_CAPS.get(trade_grade, GRADE_RISK_CAPS["B"])
    edge_reliability = GRADE_EDGE_RELIABILITY.get(
        trade_grade, GRADE_EDGE_RELIABILITY["B"]
    ) * clamp(_safe_float(fair_price.get("reliability"), 1.0), 0.0, 1.0)

    current_top_ask_price = _safe_float(valid_asks[0].get("price"))
    entry_price = current_top_ask_price
    minimum_order_shares = max(0.0, _safe_float(orderbook.get("min_order_size")))
    fill: dict[str, Any] | None = None
    liquidity_was_limited = False
    largest_unfilled_amount = 0.0
    final_fraction = 0.0
    full_kelly = 0.0
    half_kelly = 0.0
    odds_b = 0.0
    estimated_probability = fair_probability
    kelly_result: dict[str, Any] = {}

    for _ in range(8):
        kelly_result = uncertainty_adjusted_kelly(
            fee_adjusted_fair_probability,
            entry_price,
            reliability=edge_reliability,
            source_dispersion=_safe_float(fair_price.get("source_dispersion")),
            liquidity_score=_safe_float((play.get("liquidity_quality") or {}).get("score"), 50.0),
        )
        estimated_probability = _safe_float(kelly_result.get("adjusted_probability"))
        odds_b = (1.0 - entry_price) / entry_price
        full_kelly = _safe_float(kelly_result.get("full_kelly_fraction"))
        half_kelly = _safe_float(kelly_result.get("half_kelly_fraction"))
        final_fraction = min(
            half_kelly, sharp_cap, grade_risk_cap, config.global_risk_cap
        )
        if final_fraction <= 0:
            break
        requested_stake = bankroll * final_fraction
        fill = volume_weighted_entry(valid_asks, requested_stake)
        if not fill:
            return unavailable_recommendation(
                "Order-book depth could not be verified.", config
            )
        liquidity_was_limited = liquidity_was_limited or bool(
            fill.get("liquidity_limited")
        )
        largest_unfilled_amount = max(
            largest_unfilled_amount, _safe_float(fill.get("unfilled_amount"))
        )
        new_entry = fill["effective_entry_price"]
        if abs(new_entry - entry_price) < 1e-9:
            break
        entry_price = new_entry

    if final_fraction <= 0:
        message = "No recommended bet at the current entry"
        final_amount = 0.0
        fill = volume_weighted_entry(
            valid_asks, max(minimum_order_shares * entry_price, 0.01)
        )
        if fill:
            liquidity_was_limited = liquidity_was_limited or bool(
                fill.get("liquidity_limited")
            )
            largest_unfilled_amount = max(
                largest_unfilled_amount, _safe_float(fill.get("unfilled_amount"))
            )
    else:
        fill = volume_weighted_entry(valid_asks, bankroll * final_fraction)
        if not fill:
            return unavailable_recommendation(
                "Order-book depth could not be verified.", config
            )
        liquidity_was_limited = liquidity_was_limited or bool(
            fill.get("liquidity_limited")
        )
        largest_unfilled_amount = max(
            largest_unfilled_amount, _safe_float(fill.get("unfilled_amount"))
        )
        final_amount = fill["executable_amount"]
        final_fraction = min(final_fraction, final_amount / bankroll)
        entry_price = fill["effective_entry_price"]
        kelly_result = uncertainty_adjusted_kelly(
            fee_adjusted_fair_probability,
            entry_price,
            reliability=edge_reliability,
            source_dispersion=_safe_float(fair_price.get("source_dispersion")),
            liquidity_score=_safe_float((play.get("liquidity_quality") or {}).get("score"), 50.0),
        )
        estimated_probability = _safe_float(kelly_result.get("adjusted_probability"))
        odds_b = (1.0 - entry_price) / entry_price
        full_kelly = _safe_float(kelly_result.get("full_kelly_fraction"))
        half_kelly = _safe_float(kelly_result.get("half_kelly_fraction"))
        final_fraction = min(
            final_fraction, half_kelly, sharp_cap, grade_risk_cap,
            config.global_risk_cap
        )
        final_amount = bankroll * final_fraction
        fill = volume_weighted_entry(valid_asks, final_amount)
        if fill:
            liquidity_was_limited = liquidity_was_limited or bool(
                fill.get("liquidity_limited")
            )
            largest_unfilled_amount = max(
                largest_unfilled_amount, _safe_float(fill.get("unfilled_amount"))
            )
            final_amount = fill["executable_amount"]
            final_fraction = final_amount / bankroll
            entry_price = fill["effective_entry_price"]
        minimum_executable_amount = max(0.01, minimum_order_shares * entry_price)
        if final_amount + 1e-9 < minimum_executable_amount:
            final_amount = 0.0
            final_fraction = 0.0
        message = (
            "Recommended bet"
            if final_fraction > 0
            else "No recommended bet at the current entry"
        )

    baseline_probability = fair_probability
    edge = max(0.0, estimated_probability - entry_price)
    sharp_average_entry_price = _safe_float(
        play.get("sharp_reference_entry_price") or play.get("average_entry_price")
    )
    status = slippage_status(
        sharp_average_entry_price, current_top_ask_price, entry_price
    )
    price_movement = entry_price - sharp_average_entry_price
    units = (
        final_fraction / config.unit_percentage if config.unit_percentage > 0 else 0.0
    )

    risk_context = risk_context or {}
    risk_config_value = risk_context.get("config")
    risk_config = (
        risk_config_value
        if isinstance(risk_config_value, RiskConfig)
        else RiskConfig(**(risk_config_value or {}))
    )
    portfolio_risk = evaluate_portfolio_risk(
        play,
        final_amount,
        bankroll,
        risk_context.get("exposures") or [],
        risk_context.get("account_state") or {
            "current_bankroll": bankroll,
            "high_water_mark": bankroll,
        },
        risk_config,
    )
    pre_risk_amount = final_amount
    final_amount = portfolio_risk["final_capped_stake"]
    final_fraction = final_amount / bankroll if bankroll > 0 else 0.0
    final_fill = volume_weighted_entry(valid_asks, final_amount) if final_amount > 0 else None
    if final_fill:
        fill = final_fill
        entry_price = final_fill["effective_entry_price"]
    units = final_fraction / config.unit_percentage if config.unit_percentage > 0 else 0.0
    execution_plan = build_execution_plan(
        play,
        final_amount,
        min(0.99, estimated_probability + expected_fee_fraction),
        trade_grade,
        expected_fee_fraction=expected_fee_fraction,
        now=risk_context.get("evaluation_now"),
        config=(
            risk_context.get("execution_config")
            if isinstance(risk_context.get("execution_config"), ExecutionConfig)
            else ExecutionConfig(**(risk_context.get("execution_config") or {}))
        ),
    )

    return {
        "available": True,
        "reason": None,
        "message": message,
        "recommendation_version": config.recommendation_version,
        "bankroll": bankroll,
        "unit_value": bankroll * config.unit_percentage,
        "unit_percentage": config.unit_percentage,
        "current_user_entry_price": entry_price,
        "effective_entry_price": entry_price,
        "entry_price_source": "Polymarket CLOB asks, volume-weighted for the recommended dollar amount",
        "baseline_probability": baseline_probability,
        "evidence_score": evidence["score"],
        "evidence_components": evidence["components"],
        "evidence_weights": evidence["weights"],
        "consensus_details": evidence["consensus_details"],
        "raw_sharp_count": sharps,
        "lead_sharp_count": lead_sharps,
        "supporting_sharp_count": supporting_sharps,
        "weighted_sharp_count": weighted_sharps,
        "category_weighting": "Lead Sharps count 1.0x; Supporting Sharps count 0.5x before probability and Kelly calculations.",
        "trade_classification": classification,
        "is_research_only": classification in RESEARCH_CLASSIFICATIONS,
        "evidence_strength": evidence_strength,
        "evidence_adjustment": evidence_adjustment,
        "maximum_adjustment": adjustment_cap,
        "estimated_win_probability": estimated_probability,
        "raw_fair_probability": fair_probability,
        "fee_adjusted_fair_probability": fee_adjusted_fair_probability,
        "fair_price_status": fair_price.get("status"),
        "fair_price_source_count": fair_price.get("source_count"),
        "uncertainty_haircut": kelly_result.get("uncertainty_haircut"),
        "calculated_edge": edge,
        "decimal_odds": 1.0 / entry_price if entry_price > 0 else None,
        "net_odds_b": odds_b,
        "full_kelly_fraction": full_kelly,
        "half_kelly_fraction": half_kelly,
        "sharp_risk_cap": sharp_cap,
        "trade_grade": trade_grade,
        "trade_grade_risk_cap": grade_risk_cap,
        "edge_reliability_factor": edge_reliability,
        "global_risk_cap": config.global_risk_cap,
        "risk_cap_applied": min(sharp_cap, grade_risk_cap, config.global_risk_cap),
        "final_recommended_fraction": final_fraction,
        "recommended_amount": final_amount,
        "recommended_amount_before_portfolio_risk": pre_risk_amount,
        "recommended_shares": (fill or {}).get("shares", 0.0)
        if final_fraction > 0
        else 0.0,
        "recommended_units": units,
        "sharp_average_entry_price": sharp_average_entry_price,
        "sharp_reference_entry_price": status["sharp_reference_entry_price"],
        "current_top_ask_price": status["current_top_ask_price"],
        "price_movement": price_movement,
        "slippage_cents": status["slippage_cents"],
        "price_slippage_fraction": status["price_slippage_fraction"],
        "unfavorable_slippage_pct": status["unfavorable_slippage_pct"],
        "passes_slippage_rule": status["passes_slippage_rule"],
        "slippage_rejection_reason": status["slippage_rejection_reason"],
        "max_unfavorable_slippage_pct": MAX_UNFAVORABLE_SLIPPAGE_PCT,
        "price_movement_quality": "better"
        if price_movement < 0
        else ("worse" if price_movement > 0 else "same"),
        "orderbook_levels_used": (fill or {}).get("levels_used", 0),
        "liquidity_limited": liquidity_was_limited,
        "unfilled_amount": largest_unfilled_amount,
        "minimum_order_shares": minimum_order_shares,
        "minimum_executable_amount": max(0.01, minimum_order_shares * entry_price),
        "expected_fee_fraction": expected_fee_fraction,
        "fees_included": True,
        "portfolio_risk": portfolio_risk,
        "execution_plan": execution_plan,
        "config": asdict(config),
    }
