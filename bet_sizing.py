from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SizingConfig:
    unit_percentage: float = 0.01
    neutral_threshold: float = 0.50
    global_risk_cap: float = 0.05
    consensus_weight: float = 0.45
    combined_amount_weight: float = 0.20
    relative_size_weight: float = 0.15
    top_category_weight: float = 0.08
    category_hit_rate_weight: float = 0.08
    category_sample_weight: float = 0.04
    recommendation_version: str = "v1"


DEFAULT_SIZING_CONFIG = SizingConfig()


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def probability_adjustment_cap(sharps: int, unanimous: bool) -> float:
    if unanimous:
        return 0.12
    if sharps >= 4:
        return 0.10
    if sharps == 3:
        return 0.07
    if sharps == 2:
        return 0.04
    return 0.02


def stake_risk_cap(sharps: int, unanimous: bool) -> float:
    if unanimous:
        return 0.05
    if sharps >= 4:
        return 0.04
    if sharps == 3:
        return 0.03
    if sharps == 2:
        return 0.02
    return 0.01


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
    tracked = max(sharps, int(play.get("tracked_wallet_count") or sharps))
    count_score = clamp(sharps / 4.0, 0.0, 1.0)
    percentage_score = clamp(sharps / tracked, 0.0, 1.0)
    consensus = (count_score * 0.60) + (percentage_score * 0.40)

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
        "formula": "sum(component * configured_weight)",
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
    reason: str, config: SizingConfig = DEFAULT_SIZING_CONFIG
) -> dict[str, Any]:
    return {
        "available": False,
        "reason": reason,
        "message": "Bet size unavailable - insufficient verified data",
        "recommendation_version": config.recommendation_version,
        "config": asdict(config),
    }


def build_recommendation(
    play: dict[str, Any],
    bankroll: float,
    config: SizingConfig = DEFAULT_SIZING_CONFIG,
) -> dict[str, Any]:
    bankroll = _safe_float(bankroll)
    if bankroll <= 0:
        return unavailable_recommendation("Bankroll must be greater than zero.", config)

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
            "A live executable ask is unavailable for this outcome.", config
        )

    evidence = calculate_evidence_score(play, config)
    sharps = max(1, int(play.get("agreeing_wallet_count") or 1))
    tracked = max(sharps, int(play.get("tracked_wallet_count") or sharps))
    unanimous = sharps == tracked
    adjustment_cap = probability_adjustment_cap(sharps, unanimous)
    evidence_strength = clamp(
        (evidence["score"] - config.neutral_threshold)
        / (1.0 - config.neutral_threshold),
        0.0,
        1.0,
    )
    evidence_adjustment = evidence_strength * adjustment_cap
    sharp_cap = stake_risk_cap(sharps, unanimous)

    entry_price = _safe_float(valid_asks[0].get("price"))
    minimum_order_shares = max(0.0, _safe_float(orderbook.get("min_order_size")))
    fill: dict[str, Any] | None = None
    final_fraction = 0.0
    full_kelly = 0.0
    half_kelly = 0.0
    odds_b = 0.0
    estimated_probability = entry_price

    for _ in range(8):
        baseline_probability = entry_price
        estimated_probability = clamp(
            baseline_probability + evidence_adjustment, 0.01, 0.99
        )
        odds_b, full_kelly, half_kelly = _kelly(entry_price, estimated_probability)
        final_fraction = min(half_kelly, sharp_cap, config.global_risk_cap)
        if final_fraction <= 0:
            break
        requested_stake = bankroll * final_fraction
        fill = volume_weighted_entry(valid_asks, requested_stake)
        if not fill:
            return unavailable_recommendation(
                "Order-book depth could not be verified.", config
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
    else:
        fill = volume_weighted_entry(valid_asks, bankroll * final_fraction)
        if not fill:
            return unavailable_recommendation(
                "Order-book depth could not be verified.", config
            )
        final_amount = fill["executable_amount"]
        final_fraction = min(final_fraction, final_amount / bankroll)
        entry_price = fill["effective_entry_price"]
        estimated_probability = clamp(entry_price + evidence_adjustment, 0.01, 0.99)
        odds_b, full_kelly, half_kelly = _kelly(entry_price, estimated_probability)
        final_fraction = min(
            final_fraction, half_kelly, sharp_cap, config.global_risk_cap
        )
        final_amount = bankroll * final_fraction
        fill = volume_weighted_entry(valid_asks, final_amount)
        if fill:
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

    baseline_probability = entry_price
    estimated_probability = clamp(
        baseline_probability + evidence_adjustment, 0.01, 0.99
    )
    edge = max(0.0, estimated_probability - baseline_probability)
    price_movement = entry_price - _safe_float(play.get("average_entry_price"))
    units = (
        final_fraction / config.unit_percentage if config.unit_percentage > 0 else 0.0
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
        "evidence_strength": evidence_strength,
        "evidence_adjustment": evidence_adjustment,
        "maximum_adjustment": adjustment_cap,
        "estimated_win_probability": estimated_probability,
        "calculated_edge": edge,
        "decimal_odds": 1.0 / entry_price if entry_price > 0 else None,
        "net_odds_b": odds_b,
        "full_kelly_fraction": full_kelly,
        "half_kelly_fraction": half_kelly,
        "sharp_risk_cap": sharp_cap,
        "global_risk_cap": config.global_risk_cap,
        "risk_cap_applied": min(sharp_cap, config.global_risk_cap),
        "final_recommended_fraction": final_fraction,
        "recommended_amount": final_amount,
        "recommended_units": units,
        "sharp_average_entry_price": _safe_float(play.get("average_entry_price")),
        "price_movement": price_movement,
        "price_movement_quality": "better"
        if price_movement < 0
        else ("worse" if price_movement > 0 else "same"),
        "orderbook_levels_used": (fill or {}).get("levels_used", 0),
        "liquidity_limited": bool((fill or {}).get("liquidity_limited")),
        "unfilled_amount": (fill or {}).get("unfilled_amount", 0.0),
        "minimum_order_shares": minimum_order_shares,
        "minimum_executable_amount": max(0.01, minimum_order_shares * entry_price),
        "fees_included": False,
        "config": asdict(config),
    }
