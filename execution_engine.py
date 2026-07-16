from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


EXECUTION_ENGINE_VERSION = "execution-engine-v3"
TAKE_NOW = "TAKE_NOW"
POST_LIMIT = "POST_LIMIT"
SPLIT_ORDER = "SPLIT_ORDER"
WAIT = "WAIT"
PASS = "PASS"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class ExecutionConfig:
    max_quote_age_seconds: int = 60
    wide_spread_fraction: float = 0.03
    default_tick_size: float = 0.001
    minimum_edge_discovery: float = 0.01
    minimum_edge_b: float = 0.015
    minimum_edge_a: float = 0.02
    minimum_edge_a_plus: float = 0.025

    def minimum_edge(self, grade: str) -> float:
        return {
            "DISCOVERY": self.minimum_edge_discovery,
            "B": self.minimum_edge_b,
            "A": self.minimum_edge_a,
            "A_PLUS": self.minimum_edge_a_plus,
        }.get(str(grade or "").upper(), self.minimum_edge_b)


def maximum_average_price(
    adjusted_probability: Any,
    grade: str,
    *,
    expected_fee_fraction: Any = 0.0,
    execution_risk_fraction: Any = 0.0,
    config: ExecutionConfig = ExecutionConfig(),
) -> float | None:
    probability = _number(adjusted_probability, -1.0)
    if not 0 < probability < 1:
        return None
    maximum = (
        probability
        - config.minimum_edge(grade)
        - max(0.0, _number(expected_fee_fraction))
        - max(0.0, _number(execution_risk_fraction))
    )
    return round(maximum, 6) if 0 < maximum < 1 else None


def walk_ask_depth(
    asks: list[dict[str, Any]],
    intended_amount: Any,
    maximum_average: Any,
) -> dict[str, Any]:
    intended = max(0.0, _number(intended_amount))
    max_average = _number(maximum_average, -1.0)
    levels = sorted(
        (
            {"price": _number(row.get("price"), -1.0), "size": max(0.0, _number(row.get("size")))}
            for row in asks
        ),
        key=lambda row: row["price"],
    )
    levels = [row for row in levels if 0 < row["price"] < 1 and row["size"] > 0]
    cost = shares = 0.0
    fills: list[dict[str, Any]] = []
    breached_price = None
    for level in levels:
        if cost >= intended - 1e-9:
            break
        price = level["price"]
        available_shares = level["size"]
        desired_shares = min(available_shares, (intended - cost) / price)
        allowed_shares = desired_shares
        if not 0 < max_average < 1:
            allowed_shares = 0.0
        elif price > max_average:
            numerator = max_average * shares - cost
            allowed_shares = min(desired_shares, max(0.0, numerator / (price - max_average)))
        if allowed_shares <= 1e-12:
            breached_price = price
            break
        level_cost = allowed_shares * price
        cost += level_cost
        shares += allowed_shares
        fills.append(
            {
                "price": price,
                "shares": round(allowed_shares, 8),
                "cost": round(level_cost, 8),
            }
        )
        if allowed_shares + 1e-9 < desired_shares:
            breached_price = price
            break
    effective = cost / shares if shares > 0 else None
    unfilled = max(0.0, intended - cost)
    return {
        "intended_amount": intended,
        "executable_amount": round(cost, 8),
        "amount_executable_below_max": round(cost, 8),
        "shares": round(shares, 8),
        "effective_price": round(effective, 8) if effective is not None else None,
        "unfilled_amount": round(unfilled, 8),
        "levels_used": len(fills),
        "fills": fills,
        "breached_price": breached_price,
        "fully_executable": unfilled <= 0.01,
    }


def build_execution_plan(
    play: dict[str, Any],
    recommended_stake: Any,
    adjusted_probability: Any,
    grade: str,
    *,
    expected_fee_fraction: Any,
    now: datetime | None = None,
    config: ExecutionConfig = ExecutionConfig(),
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    orderbook = play.get("orderbook") or {}
    asks = orderbook.get("asks") or []
    bids = orderbook.get("bids") or []
    valid_asks = sorted(
        [row for row in asks if 0 < _number(row.get("price"), -1) < 1 and _number(row.get("size")) > 0],
        key=lambda row: _number(row.get("price")),
    )
    valid_bids = sorted(
        [row for row in bids if 0 < _number(row.get("price"), -1) < 1 and _number(row.get("size")) > 0],
        key=lambda row: -_number(row.get("price")),
    )
    best_ask = _number(valid_asks[0].get("price"), -1) if valid_asks else None
    best_bid = _number(valid_bids[0].get("price"), -1) if valid_bids else None
    spread = best_ask - best_bid if best_ask is not None and best_bid is not None else None
    quote_time = _timestamp(orderbook.get("timestamp") or play.get("orderbook_timestamp"))
    quote_age = (now - quote_time).total_seconds() if quote_time else None
    quote_fresh = quote_age is not None and 0 <= quote_age <= config.max_quote_age_seconds
    maximum = maximum_average_price(
        adjusted_probability,
        grade,
        expected_fee_fraction=expected_fee_fraction,
        execution_risk_fraction=_number(play.get("execution_risk_fraction")),
        config=config,
    )
    walk = walk_ask_depth(valid_asks, recommended_stake, maximum)
    stake = max(0.0, _number(recommended_stake))
    tick = max(config.default_tick_size, _number(orderbook.get("tick_size"), config.default_tick_size))
    suggested_limit = None
    if best_bid is not None and maximum is not None:
        suggested_limit = round(min(maximum, best_bid + tick), 6)
    elif maximum is not None:
        suggested_limit = maximum

    if stake <= 0:
        method, reason = PASS, "ZERO_RECOMMENDED_STAKE"
        explanation = "No order should be placed because the approved stake is zero."
    elif maximum is None:
        method, reason = PASS, "MAXIMUM_AVERAGE_PRICE_UNAVAILABLE"
        explanation = "Execution is blocked because a verified maximum average price is unavailable."
    elif not valid_asks:
        method, reason = PASS, "NO_EXECUTABLE_ASK"
        explanation = "Execution is blocked because the ask-side order book is unavailable."
    elif quote_time is None:
        method, reason = WAIT, "QUOTE_TIMESTAMP_UNAVAILABLE"
        explanation = "Wait for a timestamped order-book quote before submitting an order."
    elif not quote_fresh:
        method, reason = WAIT, "STALE_ORDER_BOOK"
        explanation = "Wait for a fresh order book before submitting an order."
    elif best_ask is not None and best_ask > maximum:
        method, reason = POST_LIMIT, "BEST_ASK_ABOVE_MAXIMUM"
        explanation = "Post a limit order rather than crossing above the maximum approved average price."
    elif walk["executable_amount"] <= 0:
        method, reason = POST_LIMIT, "NO_DEPTH_BELOW_MAXIMUM"
        explanation = "Post at the suggested limit because no displayed ask depth is executable below the approved maximum."
    elif not walk["fully_executable"]:
        method, reason = SPLIT_ORDER, "PARTIAL_DEPTH_BELOW_MAXIMUM"
        explanation = "Take the verified amount below the maximum price and post the remainder as a limit order."
    elif spread is not None and spread > config.wide_spread_fraction and str(play.get("execution_urgency") or "").upper() != "URGENT":
        method, reason = POST_LIMIT, "WIDE_SPREAD"
        explanation = "Post a limit order because the spread is wide and the signal is not marked urgent."
    else:
        method, reason = TAKE_NOW, "FULL_DEPTH_VERIFIED"
        explanation = "The full stake is executable on fresh displayed depth below the maximum approved average price."

    top_depth = (
        best_ask * _number(valid_asks[0].get("size")) if best_ask is not None else 0.0
    )
    effective = walk.get("effective_price")
    reference = _number(play.get("sharp_reference_entry_price"), -1.0)
    slippage = effective - reference if effective is not None and 0 < reference < 1 else None
    return {
        "recommended_stake": stake,
        "recommended_shares": walk["shares"],
        "current_best_ask": best_ask,
        "current_best_bid": best_bid,
        "spread": spread,
        "top_level_depth": round(top_depth, 8),
        "effective_price_for_full_stake": effective if walk["fully_executable"] else None,
        "effective_price_for_executable_amount": effective,
        "maximum_average_price": maximum,
        "amount_executable_below_max": walk["amount_executable_below_max"],
        "expected_fee_fraction": max(0.0, _number(expected_fee_fraction)),
        "expected_fees": round(stake * max(0.0, _number(expected_fee_fraction)), 8),
        "expected_execution_slippage": slippage,
        "unfilled_amount": walk["unfilled_amount"],
        "recommended_execution_method": method,
        "execution_reason_code": reason,
        "execution_explanation": explanation,
        "suggested_limit_price": suggested_limit,
        "quote_timestamp": quote_time.isoformat() if quote_time else None,
        "quote_age_seconds": quote_age,
        "quote_fresh": quote_fresh,
        "depth_walk": walk,
        "calculation_version": EXECUTION_ENGINE_VERSION,
        "config": asdict(config),
    }

