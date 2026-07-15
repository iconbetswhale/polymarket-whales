from __future__ import annotations

import json
from typing import Any


def _short_address(value: Any) -> str:
    address = str(value or "").strip()
    if len(address) <= 10:
        return address or "Unknown Sharp"
    return f"{address[:6]}...{address[-4:]}"


def _wallet_detail(
    entry: dict[str, Any], *, role_override: str | None = None
) -> dict[str, Any]:
    address = str(entry.get("wallet_address") or entry.get("address") or "").strip()
    label = str(entry.get("wallet_label") or entry.get("display_name") or "").strip()
    category_metrics = entry.get("category_metrics") or {}
    top_categories = entry.get("top_category_ids") or []
    role = role_override or entry.get("sharp_role") or entry.get("role")
    if not role:
        if entry.get("is_research_anchor"):
            role = "Research Anchor"
        else:
            role = "Lead Sharp" if entry.get("is_lead_sharp") else "Supporting Sharp"
    amount = entry.get("amount_dollars", entry.get("amount"))
    return {
        "wallet_id": entry.get("wallet_id") or address or None,
        "display_name": label or _short_address(address),
        "wallet_address": address,
        "role": role,
        "is_lead_sharp": bool(entry.get("is_lead_sharp")),
        "top_category": entry.get("top_category")
        or entry.get("primary_top_category_id")
        or (top_categories[0] if top_categories else None),
        "sub_top_categories": entry.get("sub_top_categories") or [],
        "amount": amount,
        "amount_dollars": amount,
        "units": entry.get("relative_units"),
        "average_entry": entry.get("average_entry_price"),
        "relative_bet_size": entry.get("relative_units"),
        "category_record": category_metrics.get("adjusted_hit_rate")
        or category_metrics.get("hit_rate"),
    }


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _authority_order(entry: dict[str, Any]) -> tuple[bool, float, float, float, str]:
    category_metrics = entry.get("category_metrics") or {}
    return (
        not bool(entry.get("is_lead_sharp")),
        -_number(entry.get("amount")),
        -_number(entry.get("relative_units")),
        -_number(
            category_metrics.get("adjusted_hit_rate")
            or category_metrics.get("hit_rate")
        ),
        str(entry.get("wallet_label") or entry.get("wallet_address") or "").lower(),
    )


def sharp_snapshot_from_trade(trade: dict[str, Any]) -> dict[str, Any]:
    source_wallets = sorted(
        trade.get("supporting_wallets") or [], key=_authority_order
    )
    wallets = [_wallet_detail(entry) for entry in source_wallets]
    authoritative_primary = trade.get("primary_trader") or {}
    primary_id = str(
        trade.get("primary_lead_wallet_id")
        or authoritative_primary.get("wallet_address")
        or ""
    ).lower()
    primary = next(
        (
            wallet
            for wallet in wallets
            if primary_id and str(wallet.get("wallet_address") or "").lower() == primary_id
        ),
        wallets[0] if wallets else None,
    )
    if primary:
        wallets = [primary, *(wallet for wallet in wallets if wallet is not primary)]
        if trade.get("isResearchOnly") and not trade.get("primary_lead_wallet_id"):
            primary["role"] = "Research Anchor"
    contradicting = [
        _wallet_detail(entry, role_override="Contradicting Sharp")
        for entry in trade.get("contradicting_wallets") or []
    ]
    lead_ids = [
        wallet["wallet_id"] for wallet in wallets if wallet.get("is_lead_sharp")
    ]
    supporting_ids = [
        wallet["wallet_id"] for wallet in wallets if not wallet.get("is_lead_sharp")
    ]
    source_status = "recommendation_snapshot" if wallets else str(
        trade.get("sharp_source_status")
        or ("manual_entry" if trade.get("entry_source") == "manual" else "unavailable")
    )
    return {
        "primary_sharp": primary,
        "agreeing_sharps": wallets,
        "contradicting_sharps": contradicting,
        "primary_sharp_wallet_id": primary.get("wallet_id") if primary else None,
        "lead_sharp_wallet_ids": lead_ids,
        "supporting_sharp_wallet_ids": supporting_ids,
        "sharp_count_snapshot": len(wallets),
        "sharp_source_status": source_status,
        "trade_classification": trade.get("tradeClassification")
        or trade.get("trade_classification")
        or "STANDARD",
        "confidence_score_snapshot": trade.get("confidence_score")
        if trade.get("confidence_score") is not None
        else trade.get("confidenceScore"),
        "is_research_only": bool(trade.get("isResearchOnly")),
        "is_non_category_consensus": bool(trade.get("isNonCategoryConsensus")),
        "primary_selection_source": (
            "recommendation_primary_lead_wallet_id"
            if trade.get("primary_lead_wallet_id")
            else "recommendation_research_anchor"
        ),
    }


def _normalized_snapshot(
    value: dict[str, Any], *, default_status: str
) -> dict[str, Any]:
    primary = value.get("primary_sharp")
    agreeing = value.get("agreeing_sharps") or []
    contradicting = value.get("contradicting_sharps") or []
    lead_ids = value.get("lead_sharp_wallet_ids") or [
        wallet.get("wallet_id") or wallet.get("wallet_address")
        for wallet in agreeing
        if wallet.get("is_lead_sharp") or wallet.get("role") == "Lead Sharp"
    ]
    supporting_ids = value.get("supporting_sharp_wallet_ids") or [
        wallet.get("wallet_id") or wallet.get("wallet_address")
        for wallet in agreeing
        if not (wallet.get("is_lead_sharp") or wallet.get("role") == "Lead Sharp")
    ]
    return {
        **value,
        "primary_sharp": primary,
        "agreeing_sharps": agreeing,
        "contradicting_sharps": contradicting,
        "primary_sharp_wallet_id": value.get("primary_sharp_wallet_id")
        or ((primary or {}).get("wallet_id") or (primary or {}).get("wallet_address")),
        "lead_sharp_wallet_ids": lead_ids,
        "supporting_sharp_wallet_ids": supporting_ids,
        "sharp_count_snapshot": value.get("sharp_count_snapshot", len(agreeing)),
        "sharp_source_status": value.get("sharp_source_status")
        or (default_status if agreeing or primary else "unavailable"),
    }


def sharp_snapshot_from_model(snapshot: dict[str, Any]) -> dict[str, Any]:
    if snapshot.get("sharp_snapshot"):
        return _normalized_snapshot(
            dict(snapshot["sharp_snapshot"]), default_status="recommendation_snapshot"
        )
    if snapshot.get("primary_sharp") or snapshot.get("agreeing_sharps"):
        return _normalized_snapshot({
            "primary_sharp": snapshot.get("primary_sharp"),
            "agreeing_sharps": snapshot.get("agreeing_sharps") or [],
            "contradicting_sharps": snapshot.get("contradicting_sharps") or [],
            "primary_selection_source": snapshot.get("primary_sharp_selection_source"),
            "trade_classification": snapshot.get("trade_classification"),
        }, default_status="legacy_immutable_model_snapshot")
    ids = snapshot.get("agreeing_wallet_ids") or []
    labels = snapshot.get("agreeing_wallet_labels") or []
    lead_ids = {str(value or "").lower() for value in snapshot.get("lead_wallet_ids") or []}
    primary_id = str(snapshot.get("primary_lead_wallet_id") or "").lower()
    wallets = []
    for index, address in enumerate(ids):
        is_lead = str(address or "").lower() in lead_ids
        wallets.append(
            _wallet_detail(
                {
                    "wallet_address": address,
                    "wallet_label": labels[index] if index < len(labels) else None,
                    "is_lead_sharp": is_lead,
                }
            )
        )
    primary = next(
        (
            wallet
            for wallet in wallets
            if primary_id and str(wallet.get("wallet_address") or "").lower() == primary_id
        ),
        wallets[0] if wallets else None,
    )
    return _normalized_snapshot({
        "primary_sharp": primary,
        "agreeing_sharps": wallets,
        "primary_selection_source": "legacy_immutable_model_snapshot",
    }, default_status="legacy_immutable_model_snapshot")


def sharp_snapshot_from_fill(fill: dict[str, Any]) -> dict[str, Any]:
    default_status = (
        "manual_entry"
        if fill.get("sharp_source_status") == "manual_entry"
        or fill.get("entry_source") == "manual"
        else "recommendation_snapshot"
    )
    value = fill.get("sharp_snapshot") or fill.get("sharp_snapshot_json")
    if isinstance(value, dict):
        normalized = _normalized_snapshot(value, default_status=default_status)
        if default_status == "manual_entry" and not normalized.get("primary_sharp"):
            normalized["sharp_source_status"] = "manual_entry"
        return normalized
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return _normalized_snapshot({}, default_status="unavailable")
        if isinstance(parsed, dict):
            normalized = _normalized_snapshot(parsed, default_status=default_status)
            if default_status == "manual_entry" and not normalized.get("primary_sharp"):
                normalized["sharp_source_status"] = "manual_entry"
            return normalized
    if default_status == "manual_entry":
        return _normalized_snapshot(
            {"sharp_source_status": "manual_entry"}, default_status="manual_entry"
        )
    return _normalized_snapshot({}, default_status="unavailable")


def tracker_identity(record: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(record.get("canonical_event_id") or "").lower(),
        str(record.get("canonical_market_id") or "").lower(),
        str(record.get("market_line") or "").lower(),
        str(record.get("canonical_outcome_id") or record.get("outcome_id") or "").lower(),
    )
