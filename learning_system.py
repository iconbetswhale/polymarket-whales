from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable


LEARNING_SYSTEM_VERSION = "learning-system-v4"
EDGE_MAP_VERSION = "reece-edge-map-v4"
HOLDOUT_VERSION = "holdout-workflow-v4"
RULE_VIOLATION_VERSION = "rule-violation-analytics-v4"

SEGMENT_DIMENSIONS = (
    "wallet", "wallet_type", "sport", "league", "market_type", "provider",
    "entry_price_range", "time_to_event_bucket", "relative_size_bucket",
    "sharp_count", "independent_sharp_equivalents", "trade_grade",
    "liquidity_grade", "execution_method", "decision_class",
)

VIOLATION_WARNINGS = {
    "ABOVE_MAXIMUM_PRICE", "ABOVE_FIVE_PERCENT_SLIPPAGE",
    "CORRELATION_CAP_EXCEEDED", "DAILY_EXPOSURE_CAP_EXCEEDED",
    "STRONG_OPPOSING_SPECIALIST", "MAPPING_UNCERTAINTY",
    "NO_FAIR_PRICE_CONFIRMATION", "POOR_LIQUIDITY", "STRATEGY_STOP_ACTIVE",
}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _bucket(value: Any, bounds: tuple[float, ...], labels: tuple[str, ...]) -> str:
    number = _number(value)
    if number is None:
        return "UNAVAILABLE"
    for boundary, label in zip(bounds, labels):
        if number < boundary:
            return label
    return labels[-1]


@dataclass(frozen=True)
class LearningConfig:
    insufficient_sample_count: int = 25
    moderate_sample_count: int = 100
    strong_sample_count: int = 250
    minimum_holdout_count: int = 50
    promising_composite_clv: float = 0.0
    weak_composite_clv: float = 0.0


def segment_values(row: dict[str, Any]) -> dict[str, str]:
    snapshot = row.get("snapshot") or {}
    quality = row.get("trade_quality") or snapshot.get("trade_quality") or {}
    liquidity = row.get("liquidity_quality") or snapshot.get("liquidity_quality") or {}
    execution = row.get("execution_plan") or snapshot.get("execution_plan") or {}
    wallets = snapshot.get("agreeing_wallets") or snapshot.get("supporting_wallets") or []
    primary = snapshot.get("primary_sharp") or snapshot.get("primarySharp") or {}
    if isinstance(primary, str):
        wallet = primary
        wallet_type = "UNAVAILABLE"
    else:
        wallet = primary.get("address") or primary.get("name") or (wallets[0] if wallets else "UNAVAILABLE")
        wallet_type = primary.get("wallet_type") or primary.get("role") or "UNAVAILABLE"
    event_start = row.get("event_start_time") or snapshot.get("event_date_et")
    detected = row.get("detected_at")
    hours = None
    try:
        start = datetime.fromisoformat(str(event_start).replace("Z", "+00:00"))
        seen = datetime.fromisoformat(str(detected).replace("Z", "+00:00"))
        hours = (start - seen).total_seconds() / 3600
    except (TypeError, ValueError):
        pass
    classification = snapshot.get("tradeClassification") or snapshot.get("trade_classification") or "STANDARD"
    decision = str(row.get("current_decision") or "")
    decision_class = "RESEARCH_ONLY" if decision == "RESEARCH_ONLY" or classification != "STANDARD" else "STANDARD"
    return {
        "wallet": str(wallet),
        "wallet_type": str(wallet_type),
        "sport": str(row.get("sport") or snapshot.get("category") or "UNAVAILABLE"),
        "league": str(row.get("league") or snapshot.get("league") or "UNAVAILABLE"),
        "market_type": str(snapshot.get("canonical_market_type") or snapshot.get("market_type") or row.get("market_title") or "UNAVAILABLE"),
        "provider": str(row.get("provider") or "UNAVAILABLE"),
        "entry_price_range": _bucket(row.get("entry_price") or snapshot.get("current_price"), (0.25, 0.50, 0.75, 1.01), ("0-24c", "25-49c", "50-74c", "75-100c")),
        "time_to_event_bucket": _bucket(hours, (1, 6, 24, 72, math.inf), ("<1h", "1-6h", "6-24h", "1-3d", "3d+")),
        "relative_size_bucket": _bucket(snapshot.get("relative_size") or (snapshot.get("evidence_inputs") or {}).get("relative_size"), (0.5, 1.0, 2.0, math.inf), ("<0.5x", "0.5-1x", "1-2x", "2x+")),
        "sharp_count": _bucket(snapshot.get("rawAgreeingSharpCount") or snapshot.get("agreeing_wallet_count"), (2, 3, 5, math.inf), ("1", "2", "3-4", "5+")),
        "independent_sharp_equivalents": _bucket(snapshot.get("independent_sharp_equivalents") or snapshot.get("weighted_sharp_count"), (1, 2, 3, math.inf), ("<1", "1-2", "2-3", "3+")),
        "trade_grade": str(quality.get("grade") or row.get("trade_grade") or "UNAVAILABLE"),
        "liquidity_grade": str(liquidity.get("grade") or liquidity.get("status") or row.get("liquidity_grade") or "UNAVAILABLE"),
        "execution_method": str(execution.get("recommended_execution_method") or row.get("execution_method") or "UNAVAILABLE"),
        "decision_class": decision_class,
    }


def _maximum_drawdown(values: Iterable[float], starting_capital: float) -> float | None:
    equity = peak = max(1.0, starting_capital)
    worst = 0.0
    found = False
    for value in values:
        equity += value
        peak = max(peak, equity)
        if peak > 0:
            worst = max(worst, (peak - equity) / peak)
        found = True
    return round(worst, 8) if found else None


def evaluate_status(candidate_count: int, settled_count: int, weighted_composite_clv: float | None, roi: float | None, config: LearningConfig) -> str:
    if candidate_count < config.insufficient_sample_count:
        return "INSUFFICIENT_SAMPLE"
    if candidate_count < config.moderate_sample_count:
        return "DISCOVERY"
    if candidate_count >= config.strong_sample_count and settled_count >= config.moderate_sample_count and weighted_composite_clv is not None and weighted_composite_clv < config.weak_composite_clv and roi is not None and roi < 0:
        return "SUSPENDED"
    if weighted_composite_clv is not None and weighted_composite_clv < config.weak_composite_clv and (roi is None or roi < 0):
        return "WEAK"
    if candidate_count >= config.strong_sample_count and settled_count >= config.moderate_sample_count and weighted_composite_clv is not None and weighted_composite_clv > 0 and (roi or 0) > 0:
        return "VALIDATED"
    if weighted_composite_clv is not None and weighted_composite_clv > config.promising_composite_clv:
        return "PROMISING"
    return "DISCOVERY"


def build_edge_map(rows: list[dict[str, Any]], config: LearningConfig = LearningConfig()) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for dimension, value in segment_values(row).items():
            groups[(dimension, value)].append(row)
    output = []
    for (dimension, value), members in groups.items():
        played = [r for r in members if str(r.get("current_decision", "")).startswith("APPROVED")]
        passed = [r for r in members if r.get("current_decision") == "PASSED"]
        settled = [r for r in members if r.get("result") not in (None, "", "PENDING")]
        stake = sum(_number(r.get("stake")) or 0 for r in played)
        pnl_values = [_number(r.get("profit_loss")) for r in settled]
        pnl = sum(v for v in pnl_values if v is not None)
        roi = pnl / stake if stake > 0 and settled else None
        exchange = [(_number(r.get("exchange_clv")), _number(r.get("stake")) or 100.0) for r in members]
        composite = [(_number(r.get("composite_clv")), _number(r.get("stake")) or 100.0) for r in members]
        def weighted(values):
            valid = [(v, w) for v, w in values if v is not None and w > 0]
            return sum(v * w for v, w in valid) / sum(w for _, w in valid) if valid else None
        composite_values = [v for v, _ in composite if v is not None]
        execution_loss = [_number(r.get("execution_loss")) for r in members]
        fees = [_number(r.get("fees")) for r in members]
        weighted_composite = weighted(composite)
        completeness = len(composite_values) / len(members) if members else 0
        reliability = min(1.0, len(members) / config.strong_sample_count) * completeness
        status = evaluate_status(len(members), len(settled), weighted_composite, roi, config)
        output.append({
            "dimension": dimension, "segment_value": value,
            "candidate_count": len(members), "played_count": len(played),
            "passed_count": len(passed), "settled_count": len(settled),
            "stake": round(stake, 8), "roi": round(roi, 8) if roi is not None else None,
            "stake_weighted_exchange_clv": weighted(exchange),
            "stake_weighted_composite_clv": weighted_composite,
            "positive_composite_clv_rate": (sum(v > 0 for v in composite_values) / len(composite_values)) if composite_values else None,
            "median_clv": statistics.median(composite_values) if composite_values else None,
            "execution_loss": sum(v for v in execution_loss if v is not None),
            "average_fees": (sum(v for v in fees if v is not None) / sum(v is not None for v in fees)) if any(v is not None for v in fees) else None,
            "maximum_drawdown": _maximum_drawdown((v for v in pnl_values if v is not None), stake),
            "statistical_reliability": round(reliability, 8), "status": status,
            "calculation_version": EDGE_MAP_VERSION,
        })
    return sorted(output, key=lambda x: (-x["candidate_count"], x["dimension"], x["segment_value"]))


def compare_holdout(baseline: dict[str, Any], holdout: dict[str, Any], config: LearningConfig = LearningConfig()) -> dict[str, Any]:
    count = int(holdout.get("candidate_count") or 0)
    clv = _number(holdout.get("stake_weighted_composite_clv"))
    roi = _number(holdout.get("roi"))
    passed = count >= config.minimum_holdout_count and clv is not None and clv > 0 and (roi is None or roi >= 0)
    return {
        "status": "HOLDOUT_PASSED" if passed else "HOLDOUT_FAILED",
        "sample_sufficient": count >= config.minimum_holdout_count,
        "baseline": baseline, "holdout": holdout,
        "calculation_version": HOLDOUT_VERSION,
    }


def violation_analytics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get("warning_code") or "UNKNOWN")].append(row)
    result = []
    for warning, members in groups.items():
        pnl = [_number(r.get("profit_loss")) for r in members]
        exchange = [_number(r.get("exchange_clv")) for r in members]
        composite = [_number(r.get("composite_clv")) for r in members]
        result.append({
            "warning_code": warning, "count": len(members),
            "settled_count": sum(v is not None for v in pnl),
            "total_profit_loss": sum(v for v in pnl if v is not None),
            "average_exchange_clv": statistics.mean(v for v in exchange if v is not None) if any(v is not None for v in exchange) else None,
            "average_composite_clv": statistics.mean(v for v in composite if v is not None) if any(v is not None for v in composite) else None,
            "calculation_version": RULE_VIOLATION_VERSION,
        })
    return sorted(result, key=lambda x: (-x["count"], x["warning_code"]))


def config_dict(config: LearningConfig) -> dict[str, Any]:
    return asdict(config)
