from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


RISK_ENGINE_VERSION = "portfolio-risk-v3"
BANKROLL_BUCKET_VERSION = "bankroll-buckets-v3"
DRAWDOWN_VERSION = "drawdown-protocol-v3"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


@dataclass(frozen=True)
class RiskConfig:
    max_single_position_fraction: float = 0.02
    max_game_exposure_fraction: float = 0.025
    max_team_day_exposure_fraction: float = 0.04
    max_daily_exposure_fraction: float = 0.06
    max_correlated_cluster_fraction: float = 0.04
    max_provider_exposure_fraction: float = 0.10
    core_allocation: float = 0.70
    discovery_allocation: float = 0.10
    liquidity_reserve_allocation: float = 0.15
    operational_buffer_allocation: float = 0.05
    combine_model_and_personal: bool = True


def risk_state(
    current_bankroll: Any,
    high_water_mark: Any,
    *,
    recent_stake_weighted_composite_clv: Any = None,
    recent_valid_trade_count: int = 0,
    material_error_count_7d: int = 0,
    wallet_data_invalid: bool = False,
    provider_unreliable: bool = False,
    manual_kill_switch: bool = False,
    manual_reason: str | None = None,
) -> dict[str, Any]:
    current = max(0.0, _number(current_bankroll))
    high = max(current, _number(high_water_mark, current))
    drawdown = (high - current) / high if high > 0 else 0.0
    stop_reasons = []
    clv = _number(recent_stake_weighted_composite_clv, math.nan)
    if recent_valid_trade_count >= 100 and math.isfinite(clv) and clv < 0:
        stop_reasons.append("NEGATIVE_RECENT_STAKE_WEIGHTED_COMPOSITE_CLV")
    if material_error_count_7d >= 3:
        stop_reasons.append("MATERIAL_ERROR_LIMIT_REACHED")
    if wallet_data_invalid:
        stop_reasons.append("WALLET_DATA_INVALID")
    if provider_unreliable:
        stop_reasons.append("PROVIDER_UNRELIABLE")
    if manual_kill_switch:
        stop_reasons.append(manual_reason or "MANUAL_ADMIN_KILL_SWITCH")
    if stop_reasons:
        state, multiplier = "STRATEGY_STOP", 0.0
    elif drawdown >= 0.15:
        state, multiplier = "DEFENSIVE", 0.50
    elif drawdown >= 0.10:
        state, multiplier = "REDUCED", 0.75
    elif drawdown >= 0.05:
        state, multiplier = "REVIEW", 1.0
    else:
        state, multiplier = "NORMAL", 1.0
    return {
        "state": state,
        "current_bankroll": current,
        "high_water_mark": high,
        "drawdown_fraction": round(drawdown, 8),
        "stake_multiplier": multiplier,
        "freeze_experiments": state in {"REDUCED", "DEFENSIVE", "STRATEGY_STOP"},
        "automatic_recommendations_allowed": state != "STRATEGY_STOP",
        "stop_reasons": stop_reasons,
        "calculation_version": DRAWDOWN_VERSION,
    }


def _participants(value: Any) -> set[str]:
    parts = re.split(r"\s+(?:vs\.?|v\.?|at|@)\s+", str(value or ""), flags=re.I)
    return {re.sub(r"\W+", " ", part.lower()).strip() for part in parts if part.strip()}


def correlation_keys(source: dict[str, Any]) -> dict[str, Any]:
    validation = source.get("validation_ids") or {}
    event_id = str(
        source.get("canonical_event_id")
        or validation.get("event_id")
        or source.get("event_slug")
        or ""
    ).lower()
    event_time = str(source.get("event_start_time") or source.get("event_date_et") or "")
    day = event_time[:10]
    sport = str(source.get("canonical_sport_id") or source.get("category") or "").lower()
    teams = _participants(source.get("event_title"))
    explicit = {str(item).lower() for item in source.get("correlation_keys") or [] if str(item)}
    cluster = explicit or ({f"event:{event_id}"} if event_id else set())
    provider = str(source.get("sportsbook") or source.get("provider") or "polymarket").lower()
    return {
        "event": event_id,
        "day": day,
        "sport": sport,
        "teams": teams,
        "clusters": cluster,
        "provider": provider,
    }


def normalize_exposure(source: dict[str, Any], source_type: str) -> dict[str, Any]:
    snapshot = source.get("snapshot") or source
    sharp_snapshot = source.get("sharp_snapshot") or source.get("sharp_snapshot_json") or {}
    if isinstance(sharp_snapshot, str):
        try:
            sharp_snapshot = json.loads(sharp_snapshot)
        except (TypeError, ValueError):
            sharp_snapshot = {}
    tags = source.get("tags") or source.get("tags_json") or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (TypeError, ValueError):
            tags = [tags]
    amount = _number(
        source.get("total_paid")
        or source.get("position_cost")
        or snapshot.get("original_displayed_amount")
        or snapshot.get("recommended_amount")
    )
    grade = str(snapshot.get("trade_quality_grade") or snapshot.get("trade_grade") or "B").upper()
    classification = str(
        snapshot.get("trade_classification")
        or (sharp_snapshot if isinstance(sharp_snapshot, dict) else {}).get("trade_classification")
        or "STANDARD"
    ).upper()
    research_tagged = any(
        marker in str(tag).lower()
        for tag in tags
        for marker in ("research", "discovery", "non-category", "contradict")
    )
    bucket = "DISCOVERY" if grade == "DISCOVERY" or classification != "STANDARD" or research_tagged else "CORE"
    return {
        "source_type": source_type,
        "amount": max(0.0, amount),
        "bucket": bucket,
        "keys": correlation_keys(snapshot),
        "record_id": source.get("dedupe_key") or source.get("fill_id"),
    }


def bankroll_buckets(
    bankroll: Any,
    exposures: list[dict[str, Any]],
    config: RiskConfig = RiskConfig(),
) -> dict[str, Any]:
    total = max(0.0, _number(bankroll))
    allocations = {
        "CORE": config.core_allocation,
        "DISCOVERY": config.discovery_allocation,
        "LIQUIDITY_RESERVE": config.liquidity_reserve_allocation,
        "OPERATIONAL_BUFFER": config.operational_buffer_allocation,
    }
    exposure_by_bucket = {key: 0.0 for key in allocations}
    for row in exposures:
        bucket = str(row.get("bucket") or "CORE")
        exposure_by_bucket[bucket] = exposure_by_bucket.get(bucket, 0.0) + max(0.0, _number(row.get("amount")))
    rows = {}
    for key, fraction in allocations.items():
        allocated = total * fraction
        exposed = exposure_by_bucket.get(key, 0.0)
        rows[key] = {
            "allocation_fraction": fraction,
            "allocated_amount": round(allocated, 8),
            "current_exposure": round(exposed, 8),
            "available_amount": round(max(0.0, allocated - exposed), 8),
        }
    return {
        "total_bankroll": total,
        "buckets": rows,
        "allocation_total": sum(allocations.values()),
        "calculation_version": BANKROLL_BUCKET_VERSION,
    }


def evaluate_portfolio_risk(
    play: dict[str, Any],
    proposed_stake: Any,
    bankroll: Any,
    exposures: list[dict[str, Any]],
    account_state: dict[str, Any],
    config: RiskConfig = RiskConfig(),
) -> dict[str, Any]:
    total = max(0.0, _number(bankroll))
    proposed = max(0.0, _number(proposed_stake))
    keys = correlation_keys(play)
    classification = str(play.get("tradeClassification") or "STANDARD")
    grade = str((play.get("trade_quality") or {}).get("grade") or "B")
    bucket = "DISCOVERY" if grade == "DISCOVERY" or classification != "STANDARD" else "CORE"
    related = {
        "same_game": 0.0,
        "same_team_day": 0.0,
        "same_day": 0.0,
        "correlated_cluster": 0.0,
        "same_provider": 0.0,
    }
    for row in exposures:
        amount = max(0.0, _number(row.get("amount")))
        other = row.get("keys") or {}
        if keys["event"] and keys["event"] == other.get("event"):
            related["same_game"] += amount
        if keys["day"] and keys["day"] == other.get("day"):
            related["same_day"] += amount
            if keys["teams"] & set(other.get("teams") or []):
                related["same_team_day"] += amount
        if keys["clusters"] & set(other.get("clusters") or []):
            related["correlated_cluster"] += amount
        if keys["provider"] and keys["provider"] == other.get("provider"):
            related["same_provider"] += amount
    limits = {
        "single_position": total * config.max_single_position_fraction,
        "same_game": total * config.max_game_exposure_fraction,
        "same_team_day": total * config.max_team_day_exposure_fraction,
        "same_day": total * config.max_daily_exposure_fraction,
        "correlated_cluster": total * config.max_correlated_cluster_fraction,
        "same_provider": total * config.max_provider_exposure_fraction,
    }
    remaining = {
        "single_position": limits["single_position"],
        **{
            key: max(0.0, limits[key] - related[key])
            for key in related
        },
    }
    buckets = bankroll_buckets(total, exposures, config)
    bucket_remaining = buckets["buckets"][bucket]["available_amount"]
    drawdown = risk_state(
        account_state.get("current_bankroll", total),
        account_state.get("high_water_mark", total),
        recent_stake_weighted_composite_clv=account_state.get("recent_stake_weighted_composite_clv"),
        recent_valid_trade_count=int(account_state.get("recent_valid_trade_count") or 0),
        material_error_count_7d=int(account_state.get("material_error_count_7d") or 0),
        wallet_data_invalid=bool(account_state.get("wallet_data_invalid")),
        provider_unreliable=bool(account_state.get("provider_unreliable")),
        manual_kill_switch=bool(account_state.get("manual_kill_switch")),
        manual_reason=account_state.get("manual_reason"),
    )
    before_correlation = proposed * drawdown["stake_multiplier"]
    caps = {**remaining, "bankroll_bucket": bucket_remaining}
    final = min([before_correlation, *caps.values()]) if caps else before_correlation
    reasons = []
    if not drawdown["automatic_recommendations_allowed"]:
        final = 0.0
        reasons.extend(drawdown["stop_reasons"])
    if bucket == "DISCOVERY" and drawdown["freeze_experiments"]:
        final = 0.0
        reasons.append("DISCOVERY_FROZEN_BY_RISK_STATE")
    binding = sorted(key for key, value in caps.items() if value <= final + 1e-9)
    if final + 1e-9 < proposed and not reasons:
        reasons.append("PORTFOLIO_RISK_CAP_REDUCED_STAKE")
    return {
        "recommended_before_risk": proposed,
        "recommended_after_drawdown": round(before_correlation, 8),
        "existing_related_exposure": {key: round(value, 8) for key, value in related.items()},
        "limits": {key: round(value, 8) for key, value in limits.items()},
        "remaining_capacity": {key: round(value, 8) for key, value in caps.items()},
        "correlation_multiplier": round(final / proposed, 8) if proposed > 0 else 0.0,
        "final_capped_stake": round(max(0.0, final), 8),
        "bucket": bucket,
        "bankroll_buckets": buckets,
        "risk_state": drawdown,
        "binding_caps": binding,
        "reason_codes": reasons,
        "correlation_keys": {
            **keys,
            "teams": sorted(keys["teams"]),
            "clusters": sorted(keys["clusters"]),
        },
        "calculation_version": RISK_ENGINE_VERSION,
        "config": asdict(config),
    }
