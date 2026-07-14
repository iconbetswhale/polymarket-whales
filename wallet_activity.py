from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any


ZERO = Decimal("0")


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except (InvalidOperation, TypeError, ValueError):
        return ZERO


def stable_fill_id(wallet_address: str, fill: dict[str, Any]) -> str:
    """Build a deterministic identity for public trade rows without order IDs."""
    identity = {
        "wallet": str(wallet_address or "").strip().lower(),
        "transaction_hash": str(fill.get("transactionHash") or "").strip().lower(),
        "condition_id": str(fill.get("conditionId") or "").strip().lower(),
        "outcome_id": str(fill.get("asset") or "").strip(),
        "side": str(fill.get("side") or "").strip().upper(),
        "shares": str(fill.get("size") or "0"),
        "price": str(fill.get("price") or "0"),
        "timestamp": int(_decimal(fill.get("timestamp"))),
        "outcome": str(fill.get("outcome") or "").strip(),
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_trade_fills(
    wallet_address: str, raw_fills: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    wallet = str(wallet_address or "").strip().lower()
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicate_count = 0

    for raw in raw_fills:
        if not isinstance(raw, dict):
            continue
        side = str(raw.get("side") or "").strip().upper()
        shares = _decimal(raw.get("size"))
        price = _decimal(raw.get("price"))
        condition_id = str(raw.get("conditionId") or "").strip().lower()
        outcome_id = str(raw.get("asset") or "").strip()
        if side not in {"BUY", "SELL"} or shares <= 0 or price < 0:
            continue
        if not condition_id or not outcome_id:
            continue

        fill_id = stable_fill_id(wallet, raw)
        if fill_id in seen:
            duplicate_count += 1
            continue
        seen.add(fill_id)
        normalized.append(
            {
                "fill_id": fill_id,
                "wallet_address": wallet,
                "transaction_hash": str(raw.get("transactionHash") or "").lower(),
                "condition_id": condition_id,
                "outcome_id": outcome_id,
                "side": side,
                "shares": float(shares),
                "price": float(price),
                "usd_amount": float(shares * price),
                "timestamp": int(_decimal(raw.get("timestamp"))),
                "event_slug": str(raw.get("eventSlug") or ""),
                "market_slug": str(raw.get("slug") or ""),
                "market_title": str(raw.get("title") or ""),
                "outcome": str(raw.get("outcome") or ""),
                "raw_fill": raw,
            }
        )

    normalized.sort(
        key=lambda fill: (
            fill["timestamp"],
            0 if fill["side"] == "BUY" else 1,
            fill["fill_id"],
        )
    )
    return normalized, duplicate_count


def aggregate_trade_fills(
    fills: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Aggregate fills with average-cost accounting and retain audit metrics."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for fill in fills:
        key = (
            str(fill.get("condition_id") or "").lower(),
            str(fill.get("outcome_id") or ""),
        )
        if key[0] and key[1]:
            groups.setdefault(key, []).append(fill)

    output: dict[tuple[str, str], dict[str, Any]] = {}
    for key, group in groups.items():
        remaining_shares = ZERO
        remaining_cost = ZERO
        bought_shares = ZERO
        bought_cost = ZERO
        sold_shares = ZERO
        sold_proceeds = ZERO
        buy_fill_count = 0
        sell_fill_count = 0
        first_entry_at: int | None = None
        last_addition_at: int | None = None

        for fill in sorted(
            group,
            key=lambda item: (
                int(item.get("timestamp") or 0),
                0 if item.get("side") == "BUY" else 1,
                str(item.get("fill_id") or ""),
            ),
        ):
            shares = _decimal(fill.get("shares"))
            price = _decimal(fill.get("price"))
            timestamp = int(fill.get("timestamp") or 0)
            if fill.get("side") == "BUY":
                remaining_shares += shares
                remaining_cost += shares * price
                bought_shares += shares
                bought_cost += shares * price
                buy_fill_count += 1
                first_entry_at = timestamp if first_entry_at is None else first_entry_at
                last_addition_at = timestamp
                continue

            sell_fill_count += 1
            sold_shares += shares
            sold_proceeds += shares * price
            if remaining_shares <= 0:
                continue
            average_cost = remaining_cost / remaining_shares
            reduced_shares = min(shares, remaining_shares)
            remaining_shares -= reduced_shares
            remaining_cost -= reduced_shares * average_cost
            if remaining_shares <= Decimal("0.000000001"):
                remaining_shares = ZERO
                remaining_cost = ZERO

        average_entry = remaining_cost / remaining_shares if remaining_shares > 0 else ZERO
        output[key] = {
            "wallet_address": group[0].get("wallet_address"),
            "condition_id": key[0],
            "outcome_id": key[1],
            "event_slug": group[-1].get("event_slug"),
            "market_slug": group[-1].get("market_slug"),
            "market_title": group[-1].get("market_title"),
            "outcome": group[-1].get("outcome"),
            "fill_count": len(group),
            "buy_fill_count": buy_fill_count,
            "sell_fill_count": sell_fill_count,
            "total_bought_shares": float(bought_shares),
            "total_bought_cost": float(bought_cost),
            "total_sold_shares": float(sold_shares),
            "total_sell_proceeds": float(sold_proceeds),
            "remaining_shares": float(remaining_shares),
            "remaining_cost_basis": float(remaining_cost),
            "volume_weighted_average_entry": float(average_entry),
            "first_entry_at": first_entry_at,
            "last_addition_at": last_addition_at,
            "last_activity_at": max(int(fill.get("timestamp") or 0) for fill in group),
            "fully_exited": remaining_shares <= 0,
        }
    return output
