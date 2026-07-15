from __future__ import annotations

import json
from typing import Any


def _short_address(value: Any) -> str:
    address = str(value or "").strip()
    if len(address) <= 10:
        return address or "Unknown Sharp"
    return f"{address[:6]}...{address[-4:]}"


def _wallet_detail(entry: dict[str, Any]) -> dict[str, Any]:
    address = str(entry.get("wallet_address") or entry.get("address") or "").strip()
    label = str(entry.get("wallet_label") or entry.get("display_name") or "").strip()
    category_metrics = entry.get("category_metrics") or {}
    top_categories = entry.get("top_category_ids") or []
    return {
        "display_name": label or _short_address(address),
        "wallet_address": address,
        "role": "Lead Sharp" if entry.get("is_lead_sharp") else "Supporting Sharp",
        "is_lead_sharp": bool(entry.get("is_lead_sharp")),
        "top_category": entry.get("top_category")
        or entry.get("primary_top_category_id")
        or (top_categories[0] if top_categories else None),
        "sub_top_categories": entry.get("sub_top_categories") or [],
        "amount": entry.get("amount"),
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
    primary_id = str(trade.get("primary_lead_wallet_id") or "").lower()
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
    return {
        "primary_sharp": primary,
        "agreeing_sharps": wallets,
        "primary_selection_source": "recommendation_primary_lead_wallet_id",
    }


def sharp_snapshot_from_model(snapshot: dict[str, Any]) -> dict[str, Any]:
    if snapshot.get("sharp_snapshot"):
        return dict(snapshot["sharp_snapshot"])
    if snapshot.get("primary_sharp") or snapshot.get("agreeing_sharps"):
        return {
            "primary_sharp": snapshot.get("primary_sharp"),
            "agreeing_sharps": snapshot.get("agreeing_sharps") or [],
            "primary_selection_source": snapshot.get("primary_sharp_selection_source"),
        }
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
    return {
        "primary_sharp": primary,
        "agreeing_sharps": wallets,
        "primary_selection_source": "legacy_immutable_model_snapshot",
    }


def sharp_snapshot_from_fill(fill: dict[str, Any]) -> dict[str, Any]:
    value = fill.get("sharp_snapshot") or fill.get("sharp_snapshot_json")
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {"primary_sharp": None, "agreeing_sharps": []}
        if isinstance(parsed, dict):
            return parsed
    return {"primary_sharp": None, "agreeing_sharps": []}


def tracker_identity(record: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(record.get("canonical_event_id") or "").lower(),
        str(record.get("canonical_market_id") or "").lower(),
        str(record.get("market_line") or "").lower(),
        str(record.get("canonical_outcome_id") or record.get("outcome_id") or "").lower(),
    )
