from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from bet_sizing import slippage_status


ARCHIVE_REASONS = {
    "EVENT_STARTED",
    "EVENT_CANCELED",
    "MARKET_VOIDED",
    "MARKET_SETTLED",
    "USER_UNPINNED",
}


def canonical_trade_identity(trade: dict[str, Any]) -> dict[str, str]:
    validation = trade.get("validation_ids") or {}
    event_id = str(validation.get("event_id") or trade.get("event_slug") or "").strip()
    market_id = str(
        validation.get("condition_id") or trade.get("canonical_market_key") or ""
    ).strip()
    outcome_id = str(
        trade.get("clob_token_id")
        or validation.get("outcome_token_id")
        or trade.get("canonical_side_key")
        or ""
    ).strip()
    if not event_id or not market_id or not outcome_id:
        raise ValueError("Trade is missing canonical identity")
    return {
        "canonical_event_id": event_id,
        "canonical_market_id": market_id,
        "market_line": str(trade.get("market_line") or ""),
        "canonical_outcome_id": outcome_id,
    }


def identity_key(value: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(value.get("canonical_event_id") or ""),
        str(value.get("canonical_market_id") or ""),
        str(value.get("market_line") or ""),
        str(value.get("canonical_outcome_id") or ""),
    )


def whiteboard_snapshot(trade: dict[str, Any], now: datetime | None = None) -> dict:
    identity = canonical_trade_identity(trade)
    pinned_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    recommendation = trade.get("recommendation") or {}
    frozen = {
        **identity,
        "event_title": trade.get("event_title"),
        "market_title": trade.get("market_title"),
        "selection": trade.get("outcome"),
        "market_type": trade.get("sports_market_type"),
        "period": trade.get("period") or "game",
        "settlement_scope": trade.get("settlement_scope"),
        "settlement_rules": trade.get("settlement_rules"),
        "sport": trade.get("category"),
        "league": trade.get("league"),
        "event_start_time": trade.get("event_date_et"),
        "trade_classification": trade.get("tradeClassification"),
        "warning_flags": {
            "has_contradicting_sharps": trade.get("hasContradictingSharps"),
            "is_non_category_consensus": trade.get("isNonCategoryConsensus"),
            "is_research_only": trade.get("isResearchOnly"),
        },
        "primary_trader": trade.get("primary_trader"),
        "supporting_wallets": trade.get("supporting_wallets") or [],
        "contradicting_wallets": trade.get("contradicting_wallets") or [],
        "agreeing_wallet_ids": trade.get("agreeingWalletIds") or [],
        "contradicting_wallet_ids": trade.get("contradictingWalletIds") or [],
        "lead_wallet_ids": trade.get("leadWalletIds") or [],
        "supporting_wallet_ids": trade.get("supportingWalletIds") or [],
        "raw_agreeing_sharp_count": trade.get("rawAgreeingSharpCount"),
        "raw_contradicting_sharp_count": trade.get("rawContradictingSharpCount"),
        "lead_sharp_count": trade.get("lead_sharp_count"),
        "supporting_sharp_count": trade.get("supporting_sharp_count"),
        "weighted_consensus": trade.get("weightedAgreeingConsensus"),
        "confidence_score": trade.get("confidenceScore"),
        "confidence_score_cap": trade.get("confidenceScoreCap"),
        "sharp_reference_entry": recommendation.get("sharp_reference_entry_price"),
        "entry_when_pinned": recommendation.get("effective_entry_price"),
        "agreeing_exposure": trade.get("agreeingExposureDollars"),
        "contradicting_exposure": trade.get("contradictingExposureDollars"),
        "category_statistics": (trade.get("evidence_inputs") or {}).get("category_details"),
        "recommended_bankroll_percentage": recommendation.get("final_recommended_fraction"),
        "recommended_units": recommendation.get("recommended_units"),
        "recommended_dollar_amount": recommendation.get("recommended_amount"),
        "recommended_shares": recommendation.get("recommended_shares"),
        "recommendation_model_version": recommendation.get("recommendation_version"),
        "market_url": trade.get("market_url"),
        "pinned_at": pinned_at,
    }
    digest = hashlib.sha256(repr(identity_key(frozen)).encode("utf-8")).hexdigest()
    return {**frozen, "snapshot_id": digest}


def dynamic_whiteboard_state(snapshot: dict, current: dict | None) -> dict:
    recommendation = (current or {}).get("recommendation") or {}
    sharp_entry = snapshot.get("sharp_reference_entry")
    current_entry = recommendation.get("effective_entry_price")
    status = slippage_status(
        sharp_entry,
        recommendation.get("current_top_ask_price"),
        current_entry,
    )
    return {
        "current_entry": current_entry,
        "current_top_of_book_price": recommendation.get("current_top_ask_price"),
        "current_effective_price": recommendation.get("effective_entry_price"),
        "current_slippage_cents": status.get("slippage_cents"),
        "current_unfavorable_slippage_pct": status.get("unfavorable_slippage_pct"),
        "above_max_slippage": (
            status.get("unfavorable_slippage_pct") is not None
            and status["unfavorable_slippage_pct"] > 5.0
        ),
        "quote_freshness": (current or {}).get("orderbook_timestamp"),
        "market_available": bool(current and current.get("market_open")),
        "official_event_status": (current or {}).get("lifecycle_status") or "unavailable",
        "official_event_start_time": (current or {}).get("event_date_et")
        or snapshot.get("event_start_time"),
        "executionOptions": (current or {}).get("executionOptions") or [],
    }
