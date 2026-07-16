from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


TRADE_QUALITY_VERSION = "trade-quality-v2"
INDEPENDENCE_VERSION = "sharp-independence-v2"
OPPOSITION_VERSION = "weighted-opposition-v2"
LIQUIDITY_VERSION = "liquidity-quality-v2"
KELLY_VERSION = "uncertainty-kelly-v2"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def grade_for_score(score: Any) -> str:
    value = _number(score)
    if value < 55:
        return "PASS"
    if value < 65:
        return "DISCOVERY"
    if value < 75:
        return "B"
    if value < 85:
        return "A"
    return "A_PLUS"


def independent_sharp_signal(play: dict[str, Any]) -> dict[str, Any]:
    wallet_ids = {
        str(item).strip().lower()
        for item in (play.get("agreeingWalletIds") or [])
        if str(item).strip()
    }
    raw = max(len(wallet_ids), int(_number(play.get("rawAgreeingSharpCount"))))
    lead_ids = {str(item).strip().lower() for item in (play.get("lead_wallet_ids") or [])}
    supporting_ids = {str(item).strip().lower() for item in (play.get("supporting_wallet_ids") or [])}
    dependencies = dict(play.get("wallet_dependencies") or {})
    wallet_rows = {
        str(row.get("wallet_address") or "").strip().lower(): row
        for row in (play.get("supporting_wallets") or [])
        if str(row.get("wallet_address") or "").strip()
    }
    timed_rows = []
    for wallet, row in wallet_rows.items():
        timestamp = _timestamp(row.get("last_changed_at"))
        if timestamp is not None:
            timed_rows.append((timestamp, wallet, row))
    timed_rows.sort()
    for position in range(1, len(timed_rows)):
        previous_time, previous_wallet, previous_row = timed_rows[position - 1]
        current_time, current_wallet, current_row = timed_rows[position]
        same_price = abs(
            _number(current_row.get("average_entry_price"), -1.0)
            - _number(previous_row.get("average_entry_price"), -2.0)
        ) <= 0.0025
        if (
            current_wallet not in dependencies
            and same_price
            and (current_time - previous_time).total_seconds() <= 60
        ):
            dependencies[current_wallet] = {
                "type": "TIMING_CLUSTER",
                "synchronized_entry": True,
                "target_wallet_id": previous_wallet,
                "observed_time_gap_seconds": (current_time - previous_time).total_seconds(),
            }
    equivalent = 0.0
    details = []
    for wallet in sorted(wallet_ids or lead_ids | supporting_ids):
        dependency = dependencies.get(wallet) or {}
        copied = bool(dependency.get("copy_trading") or dependency.get("shared_funding"))
        synchronized = bool(dependency.get("synchronized_entry"))
        base = 1.0 if wallet in lead_ids else 0.5
        weight = base * (0.25 if copied else (0.5 if synchronized else 1.0))
        equivalent += weight
        details.append({"wallet_id": wallet, "weight": weight, "dependency": dependency})
    if not details:
        lead_count = int(_number(play.get("lead_sharp_count")))
        supporting_count = int(_number(play.get("supporting_sharp_count")))
        equivalent = lead_count + (supporting_count * 0.5)
    points = min(10.0, equivalent * 3.0)
    return {
        "raw_count": raw,
        "independent_equivalent_count": round(equivalent, 3),
        "points": round(points, 2),
        "dependencies_observed": bool(dependencies),
        "details": details,
        "calculation_version": INDEPENDENCE_VERSION,
    }


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def weighted_opposition(play: dict[str, Any]) -> dict[str, Any]:
    agreeing = max(_number(play.get("agreeingExposureDollars")), 1.0)
    opposing_rows = play.get("contradicting_wallets") or []
    raw_count = max(len(opposing_rows), int(_number(play.get("rawContradictingSharpCount"))))
    weighted = 0.0
    details = []
    for row in opposing_rows:
        amount = max(0.0, _number(row.get("amount")))
        relative_units = max(0.0, _number(row.get("relative_units")))
        sample = max(0.0, _number((row.get("category_metrics") or {}).get("sample_size")))
        relevant = bool(row.get("category_match", True))
        hedge = bool(row.get("is_hedge"))
        independence = _clamp(_number(row.get("independence_weight"), 1.0), 0.0, 1.0)
        relevance_weight = 1.0 if relevant else 0.35
        sample_weight = _clamp(sample / 30.0, 0.25, 1.0)
        size_weight = _clamp(max(amount / agreeing, relative_units / 3.0), 0.1, 1.5)
        hedge_weight = 0.25 if hedge else 1.0
        value = relevance_weight * sample_weight * size_weight * independence * hedge_weight
        weighted += value
        details.append({"wallet_id": row.get("wallet_address"), "weight": round(value, 4)})
    if not opposing_rows and raw_count:
        weighted = min(float(raw_count), _number(play.get("weightedContradictingConsensus"), raw_count))
    penalty = min(15.0, weighted * 5.0)
    if penalty >= 10:
        action = "PASS"
    elif penalty >= 6:
        action = "REDUCE"
    elif penalty >= 2:
        action = "REVIEW"
    else:
        action = "NOTE_ONLY"
    return {
        "raw_count": raw_count,
        "weighted_opposition": round(weighted, 4),
        "penalty": round(penalty, 2),
        "action": action,
        "details": details,
        "calculation_version": OPPOSITION_VERSION,
    }


def liquidity_quality(
    play: dict[str, Any], fair_price: dict[str, Any] | None = None
) -> dict[str, Any]:
    book = play.get("orderbook") or {}
    bids = sorted((book.get("bids") or []), key=lambda x: -_number(x.get("price")))
    asks = sorted((book.get("asks") or []), key=lambda x: _number(x.get("price")))
    if not asks:
        return {
            "status": "UNAVAILABLE", "score": 0, "trade_quality_points": 0,
            "grade": "POOR",
            "components": {"top_of_book": 0, "depth_ladder": 0, "behavioral_stability": 0, "cross_market_confirmation": 0},
            "warnings": ["NO_EXECUTABLE_ASK"], "data_quality": "UNAVAILABLE",
            "behavioral_history_available": False,
            "missing_reason": "NO_EXECUTABLE_ASK", "calculation_version": LIQUIDITY_VERSION,
        }
    best_ask = _number(asks[0].get("price"))
    best_bid = _number(bids[0].get("price")) if bids else 0.0
    spread = best_ask - best_bid if best_bid > 0 else None
    top_depth = best_ask * max(0.0, _number(asks[0].get("size")))
    total_depth = sum(_number(level.get("price")) * max(0.0, _number(level.get("size"))) for level in asks[:5])
    spread_quality = 0.0 if spread is None else _clamp(1.0 - spread / 0.10, 0.0, 1.0)
    top_quality = _clamp(top_depth / 500.0, 0.0, 1.0)
    component_top = 30.0 * ((spread_quality * 0.6) + (top_quality * 0.4))
    ladder = 25.0 * _clamp(total_depth / 2000.0, 0.0, 1.0)
    stability_input = play.get("orderbook_stability")
    stability = 8.0 if stability_input is None else 25.0 * _clamp(_number(stability_input), 0.0, 1.0)
    source_count = int(_number((fair_price or play.get("fair_price") or {}).get("source_count")))
    cross_market = 20.0 * _clamp(source_count / 3.0, 0.0, 1.0)
    score = component_top + ladder + stability + cross_market
    grade = "STRONG" if score >= 80 else ("ACCEPTABLE" if score >= 65 else ("WEAK" if score >= 50 else "POOR"))
    warnings = []
    if stability_input is None:
        warnings.append("BEHAVIORAL_HISTORY_UNAVAILABLE")
    if source_count < 2:
        warnings.append("LIMITED_CROSS_MARKET_CONFIRMATION")
    return {
        "status": "AVAILABLE", "score": round(score, 2), "grade": grade,
        "trade_quality_points": round(score / 100.0 * 23.0, 2),
        "components": {"top_of_book": round(component_top, 2), "depth_ladder": round(ladder, 2), "behavioral_stability": round(stability, 2), "cross_market_confirmation": round(cross_market, 2)},
        "best_bid": best_bid or None, "best_ask": best_ask, "spread": spread,
        "top_depth_dollars": round(top_depth, 2), "ladder_depth_dollars": round(total_depth, 2),
        "warnings": warnings,
        "data_quality": "FULL" if stability_input is not None and source_count >= 2 else "PARTIAL",
        "behavioral_history_available": stability_input is not None,
        "missing_reason": None, "calculation_version": LIQUIDITY_VERSION,
    }


def uncertainty_adjusted_kelly(
    fair_probability: Any,
    entry_price: Any,
    *,
    reliability: float = 1.0,
    source_dispersion: float = 0.0,
    liquidity_score: float = 100.0,
) -> dict[str, Any]:
    probability = _number(fair_probability, -1.0)
    price = _number(entry_price, -1.0)
    if not 0 < probability < 1 or not 0 < price < 1:
        return {"available": False, "missing_reason": "NO_INDEPENDENT_FAIR_PRICE", "calculation_version": KELLY_VERSION}
    haircut = _clamp(_number(reliability, 1.0), 0.0, 1.0)
    haircut *= _clamp(1.0 - (_number(source_dispersion) * 5.0), 0.25, 1.0)
    haircut *= _clamp(_number(liquidity_score) / 100.0, 0.25, 1.0)
    adjusted = price + max(0.0, probability - price) * haircut
    b = (1.0 - price) / price
    full = max(0.0, (b * adjusted - (1.0 - adjusted)) / b)
    return {
        "available": True, "raw_fair_probability": probability,
        "adjusted_probability": round(adjusted, 8), "uncertainty_haircut": round(haircut, 6),
        "raw_edge": round(probability - price, 8), "adjusted_edge": round(adjusted - price, 8),
        "full_kelly_fraction": round(full, 8), "half_kelly_fraction": round(full / 2.0, 8),
        "calculation_version": KELLY_VERSION,
    }


@dataclass(frozen=True)
class TradeQualityResult:
    score: int
    grade: str
    uncapped_grade: str
    components: dict[str, Any]
    caps: tuple[str, ...]
    pass_reasons: tuple[str, ...]
    calculation_version: str = TRADE_QUALITY_VERSION

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["caps"] = list(self.caps)
        result["pass_reasons"] = list(self.pass_reasons)
        return result


def score_trade_quality(play: dict[str, Any], fair_price: dict[str, Any]) -> TradeQualityResult:
    independence = independent_sharp_signal(play)
    opposition = weighted_opposition(play)
    liquidity = liquidity_quality(play, fair_price)
    metrics = (play.get("evidence_inputs") or {}).get("category_details") or play.get("category_details") or []
    history, history_detail = _category_performance_points(metrics)
    size = 8.0 * _clamp(_number(play.get("strongest_relative_units")) / 3.0, 0.0, 1.0)
    signal = max(0.0, history + size + independence["points"] - opposition["penalty"])
    probability = _number(fair_price.get("fair_probability"), -1.0)
    provisional_amount = max(0.0, _number(play.get("decision_bankroll"))) * 0.02
    walked_entry = _effective_book_entry(play, provisional_amount)
    entry = walked_entry if walked_entry is not None else _number(play.get("current_price"), -1.0)
    raw_edge = probability - entry if 0 < probability < 1 and 0 < entry < 1 else None
    fee_input = play.get("expected_fee_fraction")
    fees_considered = fee_input is not None
    fee_adjusted_edge = (
        raw_edge - max(0.0, _number(fee_input))
        if raw_edge is not None and fees_considered
        else None
    )
    edge_points = 15.0 * _clamp((fee_adjusted_edge or 0.0) / 0.08, 0.0, 1.0)
    sharp_reference = _number(play.get("sharp_reference_entry_price"), -1.0)
    slippage = ((entry - sharp_reference) / sharp_reference) if 0 < sharp_reference < 1 and 0 < entry < 1 else None
    slip_points = 0.0 if slippage is None else 10.0 * _clamp(1.0 - max(slippage, 0.0) / 0.05, 0.0, 1.0)
    cross = 5.0 * _clamp((_number(fair_price.get("source_count")) - 1.0) / 2.0, 0.0, 1.0)
    price = edge_points + slip_points + cross
    mapping = 5.0 if fair_price.get("mapping_confidence") == "EXACT" else 0.0
    timing = 3.0 * _clamp(_number(play.get("timing_suitability_score")), 0.0, 1.0)
    news = 4.0 * _clamp(_number(play.get("news_certainty_score")), 0.0, 1.0)
    correlation = 5.0 * _clamp(_number(play.get("correlation_quality_score")), 0.0, 1.0)
    context = news + timing + correlation + mapping
    total = int(round(_clamp(signal + price + liquidity["trade_quality_points"] + context, 0.0, 100.0)))
    uncapped = grade_for_score(total)
    caps: list[str] = []
    grade = uncapped
    classification = str(play.get("tradeClassification") or "STANDARD")
    if fair_price.get("status") != "AVAILABLE":
        caps.append("NO_INDEPENDENT_FAIR_PRICE")
    if not fees_considered:
        caps.append("EXPECTED_FEES_UNAVAILABLE")
    if classification != "STANDARD":
        caps.append("RESEARCH_CLASSIFICATION")
    if caps and grade not in {"PASS", "DISCOVERY"}:
        grade = "DISCOVERY"
    pass_reasons = []
    if fee_adjusted_edge is not None and fee_adjusted_edge <= 0:
        pass_reasons.append("NO_POSITIVE_COMPOSITE_EDGE")
    if slippage is not None and slippage > 0.05:
        pass_reasons.append("SLIPPAGE_ABOVE_LIMIT")
    if opposition["action"] == "PASS":
        pass_reasons.append("STRONG_OPPOSING_SPECIALIST")
    return TradeQualityResult(
        score=total, grade=grade, uncapped_grade=uncapped,
        components={
            "signal": round(signal, 2), "price": round(price, 2),
            "liquidity": liquidity["trade_quality_points"], "context": round(context, 2),
            "signal_detail": {"category_performance": round(history, 2), "category_performance_detail": history_detail, "relative_size": round(size, 2), "independence": independence, "opposition": opposition},
            "price_detail": {"effective_executable_entry": entry if 0 < entry < 1 else None, "entry_method": "MAX_RISK_DEPTH_WALK" if walked_entry is not None else "CURRENT_ACTIONABLE_PRICE", "provisional_amount": provisional_amount or None, "raw_edge": raw_edge, "expected_fee_fraction": fee_input, "fees_considered": fees_considered, "fee_adjusted_edge": fee_adjusted_edge, "expected_roi": (fee_adjusted_edge / entry if fee_adjusted_edge is not None and entry > 0 else None), "edge_points": round(edge_points, 2), "slippage": slippage, "slippage_points": round(slip_points, 2), "cross_market": round(cross, 2)},
            "liquidity_detail": liquidity,
            "context_detail": {"news": news, "timing": timing, "correlation": correlation, "mapping_and_settlement": mapping},
        },
        caps=tuple(caps), pass_reasons=tuple(pass_reasons),
    )


def _category_performance_points(metrics: list[dict[str, Any]]) -> tuple[float, dict[str, Any]]:
    if not metrics:
        return 0.0, {"status": "UNAVAILABLE", "missing_fields": ["category_performance"]}
    sample = sum(max(0.0, _number(item.get("sample_size"))) for item in metrics)
    reliability = 0.15 if sample < 25 else (0.35 if sample < 100 else (0.60 if sample < 250 else (0.80 if sample < 500 else 1.0)))
    signals: list[float] = []
    available_fields: list[str] = []
    for field, scale in (
        ("composite_clv", 0.05),
        ("exchange_clv", 0.05),
        ("roi", 0.10),
    ):
        values = [_number(item.get(field), math.nan) for item in metrics if item.get(field) is not None]
        values = [value for value in values if math.isfinite(value)]
        if values:
            signals.append(_clamp((sum(values) / len(values)) / scale, 0.0, 1.0))
            available_fields.append(field)
    positive_rates = [
        _number(item.get("positive_clv_rate"), math.nan)
        for item in metrics
        if item.get("positive_clv_rate") is not None
    ]
    positive_rates = [value for value in positive_rates if math.isfinite(value)]
    if positive_rates:
        signals.append(_clamp(((sum(positive_rates) / len(positive_rates)) - 0.5) / 0.20, 0.0, 1.0))
        available_fields.append("positive_clv_rate")
    drawdowns = [
        abs(_number(item.get("drawdown"))) for item in metrics if item.get("drawdown") is not None
    ]
    drawdown_factor = _clamp(1.0 - ((sum(drawdowns) / len(drawdowns)) / 0.25), 0.0, 1.0) if drawdowns else 0.75
    if drawdowns:
        available_fields.append("drawdown")
    if not signals:
        return 0.0, {
            "status": "UNAVAILABLE", "sample_size": sample,
            "sample_reliability": reliability,
            "missing_fields": ["composite_clv", "exchange_clv", "roi", "positive_clv_rate"],
        }
    quality = sum(signals) / len(signals)
    points = 12.0 * reliability * quality * drawdown_factor
    return round(points, 2), {
        "status": "AVAILABLE", "sample_size": sample,
        "sample_reliability": reliability, "performance_quality": round(quality, 4),
        "drawdown_factor": round(drawdown_factor, 4), "available_fields": available_fields,
    }


def _effective_book_entry(play: dict[str, Any], amount: float) -> float | None:
    if amount <= 0:
        return None
    asks = sorted(
        (play.get("orderbook") or {}).get("asks") or [],
        key=lambda row: _number(row.get("price"), 2.0),
    )
    remaining = amount
    cost = 0.0
    shares = 0.0
    for row in asks:
        price = _number(row.get("price"), -1.0)
        size = max(0.0, _number(row.get("size")))
        if not 0 < price < 1 or size <= 0:
            continue
        level_cost = price * size
        consumed = min(remaining, level_cost)
        cost += consumed
        shares += consumed / price
        remaining -= consumed
        if remaining <= 1e-9:
            break
    return cost / shares if shares > 0 and remaining <= 1e-9 else None


def enrich_trade_decision(play: dict[str, Any], fair_price: dict[str, Any]) -> dict[str, Any]:
    quality = score_trade_quality(play, fair_price).to_dict()
    play["fair_price"] = fair_price
    play["trade_quality"] = quality
    play["trade_quality_score"] = quality["score"]
    play["trade_quality_grade"] = quality["grade"]
    play["confidence_score"] = quality["score"]
    play["confidenceScore"] = quality["score"]
    play["score_breakdown"] = quality["components"]
    play["liquidity_quality"] = quality["components"]["liquidity_detail"]
    play["independent_sharp_signal"] = quality["components"]["signal_detail"]["independence"]
    play["weighted_opposition"] = quality["components"]["signal_detail"]["opposition"]
    return play
