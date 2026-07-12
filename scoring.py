from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from unit_analysis import amount_to_units


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class ConvictionResult:
    status: str
    score: int | None
    breakdown: dict


def score_position(
    position: dict,
    wallet_unit: dict,
    consensus_count: int,
    increase_count: int,
) -> ConvictionResult:
    portfolio_total = float(position.get("wallet_total_visible_value") or 0)
    size_usd = float(position.get("position_size_usd") or 0)
    current_value = float(position.get("current_value") or 0)
    avg_price = float(position.get("avg_entry_price") or 0)
    current_price = float(position.get("current_price") or 0)
    hours_to_resolution = position.get("hours_to_resolution")

    unit_size = wallet_unit.get("estimated_base_unit")
    estimated_units = amount_to_units(size_usd, unit_size)
    metrics_available = 0

    size_component = 0
    if estimated_units is not None:
        metrics_available += 1
        size_component = round(_clamp(estimated_units / 4, 0, 1) * 35)

    portfolio_component = 0
    if portfolio_total > 0:
        metrics_available += 1
        portfolio_component = round(_clamp(current_value / max(portfolio_total * 0.25, 1), 0, 1) * 20)

    consensus_component = 0
    if consensus_count > 0:
        metrics_available += 1
        consensus_component = round(_clamp((consensus_count - 1) / 3, 0, 1) * 15)

    increase_component = 0
    if increase_count >= 0:
        metrics_available += 1
        increase_component = round(_clamp(increase_count / 2, 0, 1) * 10)

    price_component = 0
    if avg_price > 0 and current_price > 0:
        metrics_available += 1
        price_delta_pct = (current_price - avg_price) / avg_price
        price_component = round(_clamp((price_delta_pct + 0.15) / 0.3, 0, 1) * 10)

    time_component = 0
    if isinstance(hours_to_resolution, (int, float)):
        metrics_available += 1
        time_component = round(_clamp((168 - min(hours_to_resolution, 168)) / 168, 0, 1) * 10)

    sport_focus_component = 0
    sports_value = float(position.get("wallet_sports_visible_value") or 0)
    if sports_value > 0 and portfolio_total > 0:
        metrics_available += 1
        sport_focus_component = round(_clamp(sports_value / portfolio_total, 0, 1) * 10)

    if metrics_available < 3:
        return ConvictionResult(
            status="neutral",
            score=None,
            breakdown={
                "reason": "Not enough verified history or sizing data yet",
                "size_component": size_component,
                "portfolio_component": portfolio_component,
                "consensus_component": consensus_component,
                "increase_component": increase_component,
                "price_component": price_component,
                "time_component": time_component,
                "sport_focus_component": sport_focus_component,
                "estimated_units": estimated_units,
            },
        )

    score = size_component + portfolio_component + consensus_component + increase_component + price_component + time_component + sport_focus_component
    score = max(0, min(100, score))
    return ConvictionResult(
        status="scored",
        score=score,
        breakdown={
            "size_component": size_component,
            "portfolio_component": portfolio_component,
            "consensus_component": consensus_component,
            "increase_component": increase_component,
            "price_component": price_component,
            "time_component": time_component,
            "sport_focus_component": sport_focus_component,
            "estimated_units": estimated_units,
        },
    )


def hours_until_resolution(resolution_time: str | None) -> float | None:
    if not resolution_time:
        return None
    try:
        timestamp = datetime.fromisoformat(str(resolution_time).replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    delta = timestamp - datetime.now(timezone.utc)
    return round(delta.total_seconds() / 3600, 2)
