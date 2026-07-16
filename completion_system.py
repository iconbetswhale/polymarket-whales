from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from learning_system import segment_values

COMPLETION_SYSTEM_VERSION = "completion-system-v5"
APPLIED_POLICY_VERSION = "segment-policy-v5"
EXPLAINABILITY_VERSION = "explainability-trace-v5"


def play_segment_values(play: dict[str, Any]) -> dict[str, str]:
    return segment_values({
        "provider": play.get("provider") or "polymarket",
        "sport": play.get("category"), "league": play.get("league"),
        "market_title": play.get("market_title"), "event_start_time": play.get("event_date_et"),
        "detected_at": play.get("detected_at") or datetime.now(timezone.utc).isoformat(),
        "entry_price": play.get("current_price"), "trade_grade": (play.get("trade_quality") or {}).get("grade"),
        "liquidity_grade": (play.get("liquidity_quality") or {}).get("status"),
        "execution_method": ((play.get("recommendation") or {}).get("execution_plan") or {}).get("recommended_execution_method"),
        "snapshot": play,
    })


def matching_policy(play: dict[str, Any], policies: list[dict[str, Any]]) -> dict[str, Any]:
    values = play_segment_values(play)
    matches = [row for row in policies if values.get(row.get("segment_dimension")) == row.get("segment_value")]
    multiplier = min([float(row.get("stake_multiplier", 1.0)) for row in matches] or [1.0])
    return {
        "stake_multiplier": max(0.0, min(1.0, multiplier)),
        "matched_policies": matches,
        "segment_values": values,
        "calculation_version": APPLIED_POLICY_VERSION,
    }


def explainability_trace(measurements: dict[str, Any]) -> dict[str, Any]:
    candidate = measurements.get("candidate") or {}
    snapshot = candidate.get("snapshot") or {}
    execution = candidate.get("execution_snapshot") or {}
    decisions = measurements.get("decisions") or []
    fair = measurements.get("composite_price_snapshots") or []
    contributions = measurements.get("composite_source_contributions") or []
    monitoring = measurements.get("monitoring") or {}
    dual = measurements.get("dual_clv") or {}
    stages = [
        ("wallet_fills", snapshot.get("supporting_wallets") or snapshot.get("agreeing_wallets"), "AVAILABLE" if snapshot.get("supporting_wallets") or snapshot.get("agreeing_wallets") else "UNAVAILABLE"),
        ("aggregated_wallet_positions", snapshot.get("primary_trader") or snapshot.get("primary_sharp"), "AVAILABLE" if snapshot.get("primary_trader") or snapshot.get("primary_sharp") else "UNAVAILABLE"),
        ("canonical_market", {key: candidate.get(key) for key in ("canonical_event_id", "canonical_market_id", "canonical_outcome_id")}, "AVAILABLE" if any(candidate.get(key) for key in ("canonical_event_id", "canonical_market_id", "canonical_outcome_id")) else "UNAVAILABLE"),
        ("sharp_roles", {"lead": snapshot.get("lead_sharp_count"), "supporting": snapshot.get("supporting_sharp_count")}, "AVAILABLE" if snapshot.get("lead_sharp_count") is not None or snapshot.get("supporting_sharp_count") is not None else "UNAVAILABLE"),
        ("independence_weighting", snapshot.get("weighted_sharp_count"), "AVAILABLE" if snapshot.get("weighted_sharp_count") is not None else "UNAVAILABLE"),
        ("opposition_weighting", snapshot.get("opposition") or snapshot.get("contradicting_wallets"), "AVAILABLE" if snapshot.get("opposition") or snapshot.get("contradicting_wallets") else "UNAVAILABLE"),
        ("fair_price_sources", contributions, "AVAILABLE" if contributions else "UNAVAILABLE"),
        ("composite_probability", fair[-1] if fair else None, "AVAILABLE" if fair and fair[-1].get("status") == "AVAILABLE" else "UNAVAILABLE"),
        ("executable_depth_walk", execution.get("execution_plan") or execution, "AVAILABLE" if execution else "UNAVAILABLE"),
        ("liquidity_score", snapshot.get("liquidity_quality"), "AVAILABLE" if snapshot.get("liquidity_quality") else "UNAVAILABLE"),
        ("context_score", (snapshot.get("trade_quality") or {}).get("components", {}).get("context"), "AVAILABLE" if snapshot.get("trade_quality") else "UNAVAILABLE"),
        ("correlation_adjustment", execution.get("portfolio_risk"), "AVAILABLE" if execution.get("portfolio_risk") else "UNAVAILABLE"),
        ("kelly", execution.get("kelly") or {key: execution.get(key) for key in ("full_kelly_fraction", "half_kelly_fraction")}, "AVAILABLE" if execution.get("kelly") or any(execution.get(key) is not None for key in ("full_kelly_fraction", "half_kelly_fraction")) else "UNAVAILABLE"),
        ("risk_caps", execution.get("portfolio_risk"), "AVAILABLE" if execution.get("portfolio_risk") else "UNAVAILABLE"),
        ("final_recommendation", execution.get("recommendation") or execution, "AVAILABLE" if execution.get("recommendation") or execution.get("execution_plan") or execution.get("recommended_amount") is not None else "UNAVAILABLE"),
        ("model_tracker_eligibility", decisions[-1] if decisions else None, "AVAILABLE" if decisions else "UNAVAILABLE"),
    ]
    return {
        "candidate_id": candidate.get("candidate_id"),
        "correlation_id": candidate.get("correlation_id"),
        "stages": [{"stage": name, "status": status, "data": data} for name, data, status in stages],
        "monitoring": monitoring, "dual_clv": dual,
        "versions": {key: candidate.get(key) for key in ("trade_scoring_version", "recommendation_version", "fair_price_version", "kelly_version", "risk_policy_version", "wallet_registry_version", "execution_plan_version")},
        "calculation_version": EXPLAINABILITY_VERSION,
        "fabricated_data": False,
    }
