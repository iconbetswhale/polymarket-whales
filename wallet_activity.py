from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from statistics import median
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
        first_exit_at: int | None = None
        last_exit_at: int | None = None
        realized_pnl = ZERO

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
            first_exit_at = timestamp if first_exit_at is None else first_exit_at
            last_exit_at = timestamp
            if remaining_shares <= 0:
                continue
            average_cost = remaining_cost / remaining_shares
            reduced_shares = min(shares, remaining_shares)
            realized_pnl += reduced_shares * (price - average_cost)
            remaining_shares -= reduced_shares
            remaining_cost -= reduced_shares * average_cost
            if remaining_shares <= Decimal("0.000000001"):
                remaining_shares = ZERO
                remaining_cost = ZERO

        average_entry = remaining_cost / remaining_shares if remaining_shares > 0 else ZERO
        average_exit = sold_proceeds / sold_shares if sold_shares > 0 else ZERO
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
            "gross_amount_purchased": float(bought_cost),
            "gross_amount_sold": float(sold_proceeds),
            "remaining_shares": float(remaining_shares),
            "remaining_cost_basis": float(remaining_cost),
            "current_amount": float(remaining_cost),
            "net_cost": float(bought_cost - sold_proceeds),
            "net_shares": float(remaining_shares),
            "volume_weighted_average_entry": float(average_entry),
            "average_entry": float(average_entry),
            "average_exit": float(average_exit) if sold_shares > 0 else None,
            "first_entry_at": first_entry_at,
            "last_addition_at": last_addition_at,
            "last_entry_at": last_addition_at,
            "first_exit_at": first_exit_at,
            "last_exit_at": last_exit_at,
            "realized_pnl": float(realized_pnl),
            "unrealized_pnl": None,
            "final_settlement_result": None,
            "last_activity_at": max(int(fill.get("timestamp") or 0) for fill in group),
            "fully_exited": remaining_shares <= 0,
        }
    return output


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * max(0.0, min(1.0, fraction))
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * weight)


def summarize_aggregated_positions(
    aggregates: dict[tuple[str, str], dict[str, Any]],
    *,
    unit_baseline: float,
) -> dict[str, Any]:
    """Summarize exact-market aggregates without treating opposing sides as signals."""
    markets: dict[str, list[dict[str, Any]]] = {}
    for aggregate in aggregates.values():
        condition_id = str(aggregate.get("condition_id") or "").lower()
        if condition_id:
            markets.setdefault(condition_id, []).append(aggregate)

    positions: list[dict[str, Any]] = []
    for condition_id, sides in markets.items():
        ranked = sorted(
            sides,
            key=lambda row: float(
                row.get("current_amount")
                or row.get("gross_amount_purchased")
                or 0
            ),
            reverse=True,
        )
        side_a = float(
            ranked[0].get("current_amount")
            or ranked[0].get("gross_amount_purchased")
            or 0
        )
        side_b = sum(
            float(row.get("current_amount") or row.get("gross_amount_purchased") or 0)
            for row in ranked[1:]
        )
        larger = max(side_a, side_b)
        smaller = min(side_a, side_b)
        ratio = smaller / larger if larger > 0 else 0.0
        frequent_two_way = (
            sum(int(row.get("fill_count") or 0) for row in ranked) >= 6
            and sum(int(row.get("sell_fill_count") or 0) for row in ranked) >= 2
        )
        if frequent_two_way and ratio > 0.2:
            status = "MARKET_MAKING_OR_UNCERTAIN"
        elif ratio > 0.5:
            status = "TWO_SIDED"
        elif ratio > 0.2:
            status = "MATERIAL_HEDGE"
        elif ratio >= 0.1:
            status = "MINOR_HEDGE"
        else:
            status = "CLEAN_DIRECTIONAL"
        directional = max(0.0, larger - smaller)
        tier = (
            "DUST_OR_TEST"
            if directional < 500
            else "VERY_SMALL"
            if directional < 1000
            else "SMALL_RESEARCH"
            if directional < 2500
            else "MEANINGFUL_POSITION"
        )
        positions.append(
            {
                "condition_id": condition_id,
                "event_slug": ranked[0].get("event_slug"),
                "market_title": ranked[0].get("market_title"),
                "gross_side_a_exposure": side_a,
                "gross_side_b_exposure": side_b,
                "net_directional_exposure": directional,
                "opposing_exposure_ratio": ratio,
                "hedge_probability": min(
                    1.0, ratio * (1.25 if frequent_two_way else 1.0)
                ),
                "two_sided_status": status,
                "size_tier": tier,
                "relative_units": (
                    directional / unit_baseline if unit_baseline > 0 else None
                ),
                "fill_count": sum(int(row.get("fill_count") or 0) for row in ranked),
                "first_entry_at": min(
                    (
                        int(row.get("first_entry_at"))
                        for row in ranked
                        if row.get("first_entry_at") is not None
                    ),
                    default=None,
                ),
                "last_entry_at": max(
                    (
                        int(row.get("last_entry_at"))
                        for row in ranked
                        if row.get("last_entry_at") is not None
                    ),
                    default=None,
                ),
                "realized_pnl": sum(
                    float(row.get("realized_pnl") or 0) for row in ranked
                ),
            }
        )

    clean = [
        row for row in positions if row["two_sided_status"] == "CLEAN_DIRECTIONAL"
    ]
    hedged = [
        row
        for row in positions
        if row["two_sided_status"] in {"MINOR_HEDGE", "MATERIAL_HEDGE"}
    ]
    two_sided = [
        row
        for row in positions
        if row["two_sided_status"]
        in {"TWO_SIDED", "MARKET_MAKING_OR_UNCERTAIN"}
    ]
    meaningful = [
        row["net_directional_exposure"]
        for row in positions
        if row["size_tier"] == "MEANINGFUL_POSITION"
    ]
    eligible = [
        row["net_directional_exposure"]
        for row in clean
        if row["size_tier"] == "MEANINGFUL_POSITION"
    ]
    recent_30 = eligible[-30:]
    proposal_ready = len(eligible) >= 25
    return {
        "aggregated_positions": positions,
        "aggregated_position_count": len(positions),
        "eligible_directional_sample": len(eligible),
        "clean_directional_sample": len(clean),
        "hedged_sample": len(hedged),
        "two_sided_sample": len(two_sided),
        "dust_test_sample": sum(
            1 for row in positions if row["size_tier"] == "DUST_OR_TEST"
        ),
        "very_small_sample": sum(
            1 for row in positions if row["size_tier"] == "VERY_SMALL"
        ),
        "small_research_sample": sum(
            1 for row in positions if row["size_tier"] == "SMALL_RESEARCH"
        ),
        "meaningful_sample": len(meaningful),
        "median_meaningful_position": median(meaningful) if meaningful else None,
        "relative_size_distribution": {
            "p25": _percentile(eligible, 0.25),
            "median": median(eligible) if eligible else None,
            "p75": _percentile(eligible, 0.75),
            "p90": _percentile(eligible, 0.90),
        },
        "proposed_baseline": {
            "status": "REVIEW_READY" if proposal_ready else "INSUFFICIENT_SAMPLE",
            "eligible_sample": len(eligible),
            "required_sample": 25,
            "rolling_30_median": median(recent_30) if recent_30 else None,
            "rolling_90_day_median": None,
            "requires_admin_approval": True,
            "production_baseline_unchanged": True,
        },
    }
