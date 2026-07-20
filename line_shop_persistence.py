from __future__ import annotations

import json
from datetime import datetime, timezone

from measurement_foundation import stable_hash


LINE_SHOP_PROVIDERS = frozenset({"polymarket", "kalshi", "fourcx"})


def persistence_records(user_id: str, trades: list[dict], captured_at: str | None = None) -> tuple[list[dict], list[dict]]:
    captured_at = captured_at or datetime.now(timezone.utc).isoformat()
    initials: list[dict] = []
    observations: list[dict] = []
    for trade in trades:
        snapshot_id = str(trade.get("recommendationSnapshotId") or "").strip()
        trade_id = str(trade.get("id") or "").strip()
        if not snapshot_id or not trade_id:
            continue
        options = [
            row for row in trade.get("executionOptions") or []
            if str(row.get("providerKey") or "").lower() in LINE_SHOP_PROVIDERS
        ]
        best = next((row for row in options if row.get("isBestPrice") is True), None)
        if best:
            initials.append({
                "user_id": user_id,
                "recommendation_snapshot_id": snapshot_id,
                "trade_id": trade_id,
                "best_provider": best.get("providerKey"),
                "best_provider_market_id": best.get("providerMarketId"),
                "best_provider_outcome_id": best.get("providerOutcomeId"),
                "best_executable_price": best.get("bestExecutablePrice"),
                "effective_entry_price": best.get("effectiveEntryPrice"),
                "native_price": best.get("nativePrice"),
                "native_price_format": best.get("nativePriceFormat"),
                "quote_timestamp": best.get("quoteTimestamp"),
                "quotes_json": json.dumps(options, sort_keys=True, separators=(",", ":")),
                "created_at": captured_at,
            })
        seen = set()
        failures = trade.get("lineShopFailures") or {}
        for option in options:
            provider = str(option.get("providerKey") or "").lower()
            seen.add(provider)
            observations.append(_observation(user_id, snapshot_id, trade_id, provider, option, captured_at))
        for provider, reason in failures.items():
            provider = str(provider or "").lower()
            if provider in LINE_SHOP_PROVIDERS and provider not in seen:
                observations.append(_observation(
                    user_id, snapshot_id, trade_id, provider,
                    {"failureReason": reason, "isExactMatch": False, "isStale": False, "isBestPrice": False},
                    captured_at,
                ))
    return initials, observations


def _observation(user_id: str, snapshot_id: str, trade_id: str, provider: str, option: dict, captured_at: str) -> dict:
    identity = (
        user_id, snapshot_id, trade_id, provider,
        option.get("providerMarketId"), option.get("providerOutcomeId"),
        option.get("quoteTimestamp"), option.get("bestExecutablePrice"),
        option.get("effectiveEntryPrice"), option.get("availableLiquidity"),
        option.get("marketStatus"), option.get("failureReason"),
    )
    return {
        "observation_id": "line-shop-" + stable_hash(identity)[:32],
        "user_id": user_id,
        "recommendation_snapshot_id": snapshot_id,
        "trade_id": trade_id,
        "provider": provider,
        "provider_event_id": option.get("providerEventId"),
        "provider_market_id": option.get("providerMarketId"),
        "provider_outcome_id": option.get("providerOutcomeId"),
        "selection": option.get("selection"),
        "native_price": option.get("nativePrice"),
        "native_price_format": option.get("nativePriceFormat"),
        "implied_probability": option.get("impliedProbability"),
        "best_executable_price": option.get("bestExecutablePrice"),
        "effective_entry_price": option.get("effectiveEntryPrice"),
        "available_liquidity": option.get("availableLiquidity"),
        "recommended_stake": option.get("recommendedStake"),
        "estimated_fees": option.get("estimatedFees"),
        "quote_timestamp": option.get("quoteTimestamp"),
        "quote_age_seconds": option.get("quoteAgeSeconds"),
        "market_status": option.get("marketStatus"),
        "mapping_confidence": option.get("mappingConfidence"),
        "is_exact_match": bool(option.get("isExactMatch")),
        "is_stale": bool(option.get("isStale")),
        "can_fill_recommended_stake": option.get("canFillRecommendedStake"),
        "is_best_price": bool(option.get("isBestPrice")),
        "failure_reason": option.get("failureReason"),
        "quote_json": json.dumps(option, sort_keys=True, separators=(",", ":")),
        "captured_at": captured_at,
    }
