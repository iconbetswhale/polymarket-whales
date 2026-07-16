from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from market_lifecycle import classify_lifecycle
from sharp_tracking import sharp_snapshot_from_trade


OPEN_TRACKER_STATUSES = {"scheduled", "live", "unresolved"}
SETTLED_TRACKER_STATUSES = {"won", "lost", "push", "void", "canceled"}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def recommendation_snapshot(
    play: dict[str, Any],
    recommendation: dict[str, Any],
    bankroll: float,
    now: datetime | None = None,
) -> dict[str, Any]:
    validation = play.get("validation_ids") or {}
    event_id = str(validation.get("event_id") or play.get("event_slug") or "")
    market_id = str(
        validation.get("condition_id") or play.get("canonical_market_key") or ""
    )
    outcome_id = str(
        play.get("clob_token_id")
        or validation.get("outcome")
        or play.get("canonical_side_key")
        or ""
    )
    line = play.get("market_line")
    version = str(recommendation.get("recommendation_version") or "v1")
    dedupe_key = "::".join([event_id, market_id, str(line or ""), outcome_id, version])
    snapshot_id = hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    sharp_snapshot = sharp_snapshot_from_trade(play)
    return {
        "snapshot_id": snapshot_id,
        "dedupe_key": dedupe_key,
        "recommendation_version": version,
        "canonical_event_id": event_id,
        "canonical_event_slug": play.get("event_slug"),
        "canonical_market_id": market_id,
        "canonical_market_slug": validation.get("market_slug"),
        "outcome_id": outcome_id,
        "market_line": line,
        "recommended_side": play.get("outcome"),
        "event_title": play.get("event_title"),
        "market_title": play.get("market_title"),
        "category": play.get("category"),
        "league": play.get("league"),
        "canonical_sport_id": play.get("canonical_sport_id"),
        "canonical_league_id": play.get("canonical_league_id"),
        "canonical_category_id": play.get("canonical_category_id"),
        "market_url": play.get("market_url"),
        "current_executable_entry_price": recommendation.get(
            "current_user_entry_price"
        ),
        "effective_entry_price": recommendation.get("effective_entry_price"),
        "entry_price_source": recommendation.get("entry_price_source"),
        "sharp_average_entry_price": recommendation.get("sharp_average_entry_price"),
        "sharp_reference_entry_price": recommendation.get(
            "sharp_reference_entry_price"
        ),
        "current_top_ask_price": recommendation.get("current_top_ask_price"),
        "slippage_cents": recommendation.get("slippage_cents"),
        "price_slippage_fraction": recommendation.get(
            "price_slippage_fraction"
        ),
        "unfavorable_slippage_pct": recommendation.get(
            "unfavorable_slippage_pct"
        ),
        "passes_slippage_rule": recommendation.get("passes_slippage_rule"),
        "slippage_rejection_reason": recommendation.get(
            "slippage_rejection_reason"
        ),
        "baseline_probability": recommendation.get("baseline_probability"),
        "evidence_score": recommendation.get("evidence_score"),
        "evidence_components": recommendation.get("evidence_components"),
        "evidence_weights": recommendation.get("evidence_weights"),
        "evidence_adjustment": recommendation.get("evidence_adjustment"),
        "estimated_win_probability": recommendation.get("estimated_win_probability"),
        "calculated_edge": recommendation.get("calculated_edge"),
        "full_kelly_fraction": recommendation.get("full_kelly_fraction"),
        "half_kelly_fraction": recommendation.get("half_kelly_fraction"),
        "final_recommended_fraction": recommendation.get("final_recommended_fraction"),
        "risk_cap_applied": recommendation.get("risk_cap_applied"),
        "confidence_score": play.get("confidence_score"),
        "score_breakdown": play.get("score_breakdown"),
        "sharps_count": play.get("agreeing_wallet_count"),
        "raw_sharp_count": play.get("raw_sharp_count"),
        "lead_sharp_count": play.get("lead_sharp_count"),
        "supporting_sharp_count": play.get("supporting_sharp_count"),
        "weighted_sharp_count": play.get("weighted_sharp_count"),
        "has_lead_sharp": play.get("has_lead_sharp"),
        "lead_wallet_ids": play.get("lead_wallet_ids"),
        "supporting_wallet_ids": play.get("supporting_wallet_ids"),
        "primary_lead_wallet_id": play.get("primary_lead_wallet_id"),
        "primary_sharp": sharp_snapshot.get("primary_sharp"),
        "agreeing_sharps": sharp_snapshot.get("agreeing_sharps"),
        "contradicting_sharps": sharp_snapshot.get("contradicting_sharps"),
        "sharp_count_snapshot": sharp_snapshot.get("sharp_count_snapshot"),
        "sharp_source_status": sharp_snapshot.get("sharp_source_status"),
        "trade_classification": sharp_snapshot.get("trade_classification"),
        "primary_sharp_selection_source": sharp_snapshot.get(
            "primary_selection_source"
        ),
        "sharp_snapshot": sharp_snapshot,
        "category_match_by_wallet": play.get("category_match_by_wallet"),
        "category_weight_by_wallet": play.get("category_weight_by_wallet"),
        "weighted_consensus_score": play.get("weighted_consensus_score"),
        "weighted_amount_signal": play.get("weighted_amount_signal"),
        "weighted_relative_size_signal": play.get(
            "weighted_relative_size_signal"
        ),
        "consensus_details": recommendation.get("consensus_details"),
        "category_weighting": recommendation.get("category_weighting"),
        "agreeing_wallet_ids": [
            entry.get("wallet_address") for entry in play.get("supporting_wallets", [])
        ],
        "agreeing_wallet_labels": [
            entry.get("wallet_label") for entry in play.get("supporting_wallets", [])
        ],
        "combined_active_amount": play.get("combined_exposure_exact"),
        "relative_size_metrics": play.get("evidence_inputs", {}).get(
            "relative_size_details"
        ),
        "category_metrics": play.get("evidence_inputs", {}).get("category_details"),
        "event_start_time": play.get("event_date_et"),
        "recommendation_timestamp": timestamp,
        "original_displayed_bankroll": bankroll,
        "original_displayed_amount": recommendation.get("recommended_amount"),
        "original_recommended_units": recommendation.get("recommended_units"),
        "orderbook_levels_used": recommendation.get("orderbook_levels_used"),
        "liquidity_limited": recommendation.get("liquidity_limited"),
        "fees_included": recommendation.get("fees_included"),
        "execution_plan": recommendation.get("execution_plan"),
        "portfolio_risk": recommendation.get("portfolio_risk"),
        "maximum_average_price": (recommendation.get("execution_plan") or {}).get("maximum_average_price"),
        "execution_method": (recommendation.get("execution_plan") or {}).get("recommended_execution_method"),
        "correlation_multiplier": (recommendation.get("portfolio_risk") or {}).get("correlation_multiplier"),
        "bankroll_bucket": (recommendation.get("portfolio_risk") or {}).get("bucket"),
        "risk_state": ((recommendation.get("portfolio_risk") or {}).get("risk_state") or {}).get("state"),
    }


def _find_market(event: dict[str, Any], condition_id: str) -> dict[str, Any]:
    for market in event.get("markets") or []:
        if str(market.get("conditionId") or "").lower() == condition_id.lower():
            return market
    return {}


def tracker_status_from_event(
    snapshot: dict[str, Any], event: dict[str, Any], now: datetime | None = None
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    market = _find_market(event, str(snapshot.get("canonical_market_id") or ""))
    status_text = " ".join(
        str(value or "").lower()
        for value in (
            event.get("gameStatus"),
            market.get("umaResolutionStatus"),
            market.get("marketStatus"),
        )
    )
    settled_at = (
        market.get("closedTime")
        or event.get("finishedTimestamp")
        or event.get("closedTime")
    )
    if "cancel" in status_text:
        return {"status": "canceled", "result": "Canceled", "settled_at": settled_at}
    if "void" in status_text:
        return {"status": "void", "result": "Void", "settled_at": settled_at}

    lifecycle = classify_lifecycle(
        {
            "resolution_time": snapshot.get("event_start_time"),
            "event_closed": event.get("closed"),
            "event_ended": event.get("ended"),
            "event_live": event.get("live"),
            "game_status": event.get("gameStatus"),
            "market_closed": market.get("closed"),
            "market_active": market.get("active"),
            "accepting_orders": market.get("acceptingOrders"),
            "market_resolution_status": market.get("umaResolutionStatus"),
        },
        now,
    )
    if lifecycle.state == "upcoming":
        return {"status": "scheduled", "result": None, "settled_at": None}
    if lifecycle.state == "live":
        return {"status": "live", "result": None, "settled_at": None}
    if lifecycle.state != "completed":
        return {"status": "unresolved", "result": None, "settled_at": None}

    outcomes = [str(value) for value in _json_list(market.get("outcomes"))]
    prices = [
        _safe_float(value, -1.0) for value in _json_list(market.get("outcomePrices"))
    ]
    selected = str(snapshot.get("recommended_side") or "").strip().lower()
    selected_price = None
    for index, outcome in enumerate(outcomes):
        if outcome.strip().lower() == selected and index < len(prices):
            selected_price = prices[index]
            break

    if selected_price is not None and selected_price >= 0.99:
        return {"status": "won", "result": "Won", "settled_at": settled_at}
    if (
        selected_price is not None
        and selected_price <= 0.01
        and max(prices or [-1]) >= 0.99
    ):
        return {"status": "lost", "result": "Lost", "settled_at": settled_at}
    if selected_price is not None and abs(selected_price - 0.5) <= 0.001:
        return {"status": "push", "result": "Push", "settled_at": settled_at}
    return {"status": "unresolved", "result": None, "settled_at": settled_at}


def replay_tracker(
    records: list[dict[str, Any]], starting_bankroll: float
) -> dict[str, Any]:
    starting_bankroll = max(0.0, _safe_float(starting_bankroll))
    bankroll = starting_bankroll
    peak = starting_bankroll
    maximum_drawdown = 0.0
    realized_profit = 0.0
    open_exposure = 0.0
    potential_payout = 0.0
    rows: list[dict[str, Any]] = []
    graph = [{"timestamp": None, "bankroll": bankroll, "realized_profit": 0.0}]
    wins = losses = pushes_voids = 0

    ordered = sorted(
        records,
        key=lambda record: str(
            (record.get("snapshot") or {}).get("recommendation_timestamp") or ""
        ),
    )
    stakes: list[float] = []
    for record in ordered:
        snapshot = record.get("snapshot") or {}
        fraction = max(0.0, _safe_float(snapshot.get("final_recommended_fraction")))
        entry = _safe_float(snapshot.get("effective_entry_price"))
        stake = bankroll * fraction
        stakes.append(stake)
        status = str(record.get("status") or "unresolved").lower()
        profit = 0.0

        if status == "won" and 0 < entry < 1:
            profit = stake * ((1.0 / entry) - 1.0)
            wins += 1
        elif status == "lost":
            profit = -stake
            losses += 1
        elif status in {"push", "void", "canceled"}:
            pushes_voids += 1
        elif status in OPEN_TRACKER_STATUSES:
            open_exposure += stake
            if 0 < entry < 1:
                potential_payout += stake / entry

        if status in SETTLED_TRACKER_STATUSES:
            bankroll += profit
            realized_profit += profit
            peak = max(peak, bankroll)
            drawdown = (peak - bankroll) / peak if peak > 0 else 0.0
            maximum_drawdown = max(maximum_drawdown, drawdown)
            graph.append(
                {
                    "timestamp": record.get("settled_at")
                    or snapshot.get("event_start_time"),
                    "bankroll": bankroll,
                    "realized_profit": realized_profit,
                }
            )

        rows.append(
            {
                **record,
                "recommended_amount": stake,
                "recommended_units": fraction / 0.01,
                "profit_loss": profit if status in SETTLED_TRACKER_STATUSES else None,
                "running_bankroll": bankroll,
            }
        )

    settled_decisions = wins + losses
    return {
        "rows": rows,
        "graph": graph,
        "summary": {
            "starting_bankroll": starting_bankroll,
            "current_bankroll": bankroll,
            "realized_profit_loss": realized_profit,
            "roi": realized_profit / starting_bankroll
            if starting_bankroll > 0
            else 0.0,
            "total_tracked_bets": len(records),
            "wins": wins,
            "losses": losses,
            "pushes_voids": pushes_voids,
            "win_rate": wins / settled_decisions if settled_decisions else None,
            "average_recommended_stake": sum(stakes) / len(stakes) if stakes else 0.0,
            "open_exposure": open_exposure,
            "potential_payout": potential_payout,
            "maximum_drawdown": maximum_drawdown,
        },
    }
