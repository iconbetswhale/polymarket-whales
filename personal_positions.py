from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from clv import calculate_clv, calculate_clv_preferences, normalized_provider, parse_timestamp, safe_float
from personal_tracker import ACTIVE_PERSONAL_STATUSES, normalize_sportsbook


EASTERN = ZoneInfo("America/New_York")
RESOLVED_STATUSES = {"won", "lost", "push", "void", "canceled"}

PERSONAL_POSITION_SOURCE_LABELS = {
    "traders": "Prediction Traders",
    "prediction_traders": "Prediction Traders",
    "sharp_money": "Sharp Money",
    "positive_ev": "Positive EV",
    "arbitrage": "Arbitrage",
    "middles": "Middles",
    "low_hold": "Low Hold",
    "futures": "Futures",
    "manual": "Manual",
    "manual_entry": "Manual",
}


def _json_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def provider_position_key(record: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(record.get("canonical_event_id") or "").lower(),
        str(record.get("canonical_market_id") or "").lower(),
        str(record.get("market_line") or "").lower(),
        str(record.get("canonical_outcome_id") or "").lower(),
        normalize_sportsbook(record.get("sportsbook")).lower(),
    )


def position_id(key: tuple[str, ...]) -> str:
    return hashlib.sha256("\x1f".join(key).encode()).hexdigest()[:24]


def attach_personal_position_clv(
    positions: list[dict[str, Any]], closing_lines: list[dict[str, Any]], *, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Expose saved exact closes; never use in-game sell quotes as a pregame close.

    A position can contain multiple fills. Only comparison sources verified for
    every fill are included, with a share-weighted closing probability. This
    keeps the return metric consistent with the position's weighted entry.
    """
    now = now or datetime.now(timezone.utc)
    by_fill = {str(row.get("tracker_record_id")): row for row in closing_lines}
    for position in positions:
        start = parse_timestamp(position.get("eventStartTime"))
        fills = position.get("fills") or []
        value = {
            "stage": "current" if start and start > now else "closing",
            "status": "unavailable",
            "entryPrice": position.get("averageBuyEntry"),
            "comparisons": [],
            "reason": "An official start time and tracked-at time are required for CLV.",
        }
        position["lineValue"] = value
        if not start or not fills:
            continue
        tracked_times = [parse_timestamp(fill.get("created_at")) for fill in fills]
        in_play = any(
            _json_mapping(fill.get("sharp_snapshot") or fill.get("sharp_snapshot_json")).get("is_live") is True
            or (tracked is not None and tracked >= start)
            for fill, tracked in zip(fills, tracked_times)
        )
        if in_play:
            value.update(status="not_applicable", reason="This position includes a bet tracked after kickoff. Pregame CLV does not apply.")
            continue
        if any(tracked is None for tracked in tracked_times):
            continue
        if start > now:
            value.update(status="pending", reason="Final CLV is saved at kickoff. Current exact-market sportsbook odds are not connected for this bet yet.")
            continue
        per_fill = []
        for fill in fills:
            snapshot = by_fill.get(str(fill.get("fill_id"))) or {}
            sources = {}
            stamp = parse_timestamp(snapshot.get("closing_snapshot_timestamp"))
            if stamp and stamp <= start:
                provider = normalized_provider(position.get("provider"))
                price = safe_float(snapshot.get("closing_effective_price"))
                if snapshot.get("clv_status") == "captured" and price is not None and 0 < price < 1:
                    sources[provider] = {"key": provider, "label": position.get("provider"), "price": price, "timestamp": stamp.isoformat(), "method": "sportsbook_price"}
                for close in snapshot.get("provider_closes") or []:
                    price = safe_float(close.get("closing_probability"))
                    quoted_at = parse_timestamp(close.get("quote_timestamp"))
                    if str(close.get("mapping_confidence") or "").upper() != "EXACT" or price is None or not 0 < price < 1 or not quoted_at or quoted_at > start:
                        continue
                    key = normalized_provider(close.get("provider"))
                    sources[key] = {"key": key, "label": close.get("provider_name") or key, "price": price, "timestamp": quoted_at.isoformat(), "method": "sportsbook_price"}
                fair = calculate_clv_preferences(snapshot).get("novig") or {}
                if fair.get("status") == "captured":
                    sources["sharp_fair"] = {"key": "sharp_fair", "label": "Sharp no-vig benchmark", "price": fair["closing_probability"], "timestamp": stamp.isoformat(), "method": "fair_probability"}
            per_fill.append((safe_float(fill.get("shares")) or 0, sources))
        common_sources = set(per_fill[0][1]).intersection(*(set(sources) for _, sources in per_fill[1:]))
        total_shares = sum(shares for shares, _ in per_fill)
        entry = safe_float(position.get("averageBuyEntry"))
        if not common_sources or total_shares <= 0 or entry is None or not 0 < entry < 1:
            value["reason"] = "No verified pregame close is available for every fill in this position."
            continue
        comparisons = []
        for key in sorted(common_sources):
            close = sum(shares * sources[key]["price"] for shares, sources in per_fill) / total_shares
            meta = per_fill[0][1][key]
            comparisons.append({**meta, "price": close, "timestamp": max(sources[key]["timestamp"] for _, sources in per_fill), "valuePct": calculate_clv(entry, close)["clv_pct"]})
        default = normalized_provider(position.get("provider"))
        comparisons.sort(key=lambda item: (item["key"] != default, item["label"]))
        value.update(status="captured", comparisons=comparisons, reason=None)
    return positions


def executable_sell_quote(
    bids: list[dict[str, Any]], shares: float, *, timestamp: Any = None
) -> dict[str, Any]:
    requested = max(float(shares or 0), 0.0)
    remaining = requested
    gross = 0.0
    executed = 0.0
    best_bid = None
    for level in sorted(
        bids, key=lambda item: float(item.get("price") or 0), reverse=True
    ):
        price = float(level.get("price") or 0)
        size = max(float(level.get("size") or 0), 0.0)
        if not 0 < price <= 1 or size <= 0:
            continue
        if best_bid is None:
            best_bid = price
        take = min(size, remaining)
        gross += take * price
        executed += take
        remaining -= take
        if remaining <= 1e-9:
            break
    effective = gross / executed if executed > 0 else None
    freshness = "unavailable"
    if effective is not None:
        freshness = "live"
        if timestamp:
            try:
                quoted_at = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
                if quoted_at.tzinfo is None:
                    quoted_at = quoted_at.replace(tzinfo=timezone.utc)
                if (datetime.now(timezone.utc) - quoted_at).total_seconds() > 60:
                    freshness = "stale"
            except ValueError:
                freshness = "stale"
    return {
        "bestBid": best_bid,
        "effectiveSellPrice": effective,
        "executableShares": executed,
        "estimatedGrossProceeds": gross,
        "estimatedSellFee": 0.0,
        "estimatedNetProceeds": gross,
        "unfilledShares": max(requested - executed, 0.0),
        "quoteTimestamp": timestamp,
        "expectedSlippagePct": (
            (best_bid - effective) / best_bid
            if best_bid and effective is not None
            else None
        ),
        "quoteFreshness": freshness,
    }


def aggregate_personal_positions(
    fills: list[dict[str, Any]],
    exits: list[dict[str, Any]],
    quotes: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    fills_by_key: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    exits_by_key: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for fill in fills:
        fills_by_key[provider_position_key(fill)].append(fill)
    for exit_record in exits:
        exits_by_key[provider_position_key(exit_record)].append(exit_record)

    positions = []
    for key, purchases in fills_by_key.items():
        sales = sorted(
            exits_by_key.get(key, []), key=lambda item: str(item.get("sold_at") or "")
        )
        first = purchases[0]
        total_shares = sum(float(item.get("shares") or 0) for item in purchases)
        gross_purchase_cost = sum(
            float(item.get("position_cost") or 0) for item in purchases
        )
        buy_fees = sum(float(item.get("fees") or 0) for item in purchases)
        total_paid = gross_purchase_cost + buy_fees
        sold_shares = min(
            sum(float(item.get("shares_sold") or 0) for item in sales), total_shares
        )
        remaining_shares = max(total_shares - sold_shares, 0.0)
        average_buy_entry = gross_purchase_cost / total_shares if total_shares else None
        average_cost_per_share = total_paid / total_shares if total_shares else 0.0
        realized_cost_basis = sold_shares * average_cost_per_share
        remaining_cost_basis = remaining_shares * average_cost_per_share
        gross_sale_proceeds = sum(
            float(item.get("gross_proceeds") or 0) for item in sales
        )
        sell_fees = sum(float(item.get("fees") or 0) for item in sales)
        net_sale_proceeds = gross_sale_proceeds - sell_fees
        average_sell_entry = (
            gross_sale_proceeds / sold_shares if sold_shares > 0 else None
        )

        statuses = {str(item.get("status") or "unresolved").lower() for item in purchases}
        fully_resolved = bool(statuses) and not statuses.intersection(
            ACTIVE_PERSONAL_STATUSES
        )
        settlement_proceeds = 0.0
        settlement_price = None
        refunds = 0.0
        closure_method = None
        closure_timestamp = None
        result = None
        if fully_resolved and remaining_shares > 0:
            result = next(
                (str(item.get("result") or item.get("status") or "") for item in purchases),
                None,
            )
            if "won" in statuses:
                settlement_proceeds = remaining_shares
                settlement_price = 1.0
            elif "lost" in statuses:
                settlement_price = 0.0
            elif statuses.intersection({"push", "void", "canceled"}):
                refunds = remaining_cost_basis
                settlement_price = average_buy_entry
            closure_method = "resolved"
            closure_timestamp = max(
                (str(item.get("settled_at") or "") for item in purchases), default=""
            ) or None

        closed = fully_resolved or remaining_shares <= 1e-9
        if remaining_shares <= 1e-9:
            closure_method = "sold"
            closure_timestamp = max(
                (str(item.get("sold_at") or "") for item in sales), default=""
            ) or closure_timestamp
        if fully_resolved and sales:
            closure_method = "resolved"

        realized_pnl = (
            net_sale_proceeds
            + settlement_proceeds
            + refunds
            - realized_cost_basis
            - (remaining_cost_basis if fully_resolved else 0.0)
        )
        quote = (quotes or {}).get(str(first.get("canonical_outcome_id") or ""), {})
        quote_available = quote.get("effectiveSellPrice") is not None
        current_value = float(quote.get("estimatedNetProceeds") or 0)
        unrealized_pnl = (
            current_value - remaining_cost_basis
            if not closed and quote_available
            else None
        )
        total_pnl = (
            realized_pnl
            if closed
            else realized_pnl + unrealized_pnl
            if unrealized_pnl is not None
            else None
        )
        return_basis = total_paid if closed else remaining_cost_basis
        return_pct = (
            total_pnl / return_basis
            if total_pnl is not None and return_basis > 0
            else None
        )

        provider = normalize_sportsbook(first.get("sportsbook"))
        tracking_snapshot = _json_mapping(
            first.get("sharp_snapshot") or first.get("sharp_snapshot_json")
        )
        tracking_source = str(
            tracking_snapshot.get("tracking_source")
            or tracking_snapshot.get("entry_source")
            or "manual"
        ).strip().lower()
        positions.append(
            {
                "positionId": position_id(key),
                "canonicalEventId": key[0],
                "canonicalMarketId": key[1],
                "marketLine": key[2],
                "canonicalOutcomeId": key[3],
                "provider": provider,
                "trackingSource": tracking_source,
                "sourceLabel": PERSONAL_POSITION_SOURCE_LABELS.get(
                    tracking_source,
                    tracking_source.replace("_", " ").title() or "Manual",
                ),
                "sportKey": tracking_snapshot.get("sport_key"),
                "league": tracking_snapshot.get("league"),
                "entryAmericanOdds": tracking_snapshot.get("entry_american_odds"),
                "evPercent": tracking_snapshot.get("ev_percent"),
                "tags": _json_list(first.get("tags") or first.get("tags_json")),
                "eventTitle": first.get("event_title"),
                "marketTitle": first.get("market_title"),
                "selection": first.get("selection"),
                "eventStartTime": first.get("event_start_time"),
                "marketUrl": first.get("market_url"),
                "totalPurchasedShares": total_shares,
                "soldShares": sold_shares,
                "remainingShares": remaining_shares,
                "grossPurchaseCost": gross_purchase_cost,
                "buyFees": buy_fees,
                "totalPaid": total_paid,
                "remainingCostBasis": remaining_cost_basis,
                "averageBuyEntry": average_buy_entry,
                "averageSellEntry": average_sell_entry,
                "grossSaleProceeds": gross_sale_proceeds,
                "sellFees": sell_fees,
                "netSaleProceeds": net_sale_proceeds,
                "settlementProceeds": settlement_proceeds,
                "settlementPrice": settlement_price,
                "refunds": refunds,
                "realizedPnl": realized_pnl,
                "unrealizedPnl": unrealized_pnl,
                "totalPnl": total_pnl,
                "returnPct": return_pct,
                "currentMarketValue": current_value if quote_available else None,
                "quote": quote,
                "status": (
                    "closed"
                    if closed
                    else "partially_sold"
                    if sold_shares > 0
                    else next(iter(statuses), "unresolved")
                ),
                "isClosed": closed,
                "closureMethod": closure_method,
                "closureTimestamp": closure_timestamp,
                "result": result,
                "fills": purchases,
                "exits": sales,
                "executionMode": "tracker_only",
            }
        )
    return sorted(
        positions,
        key=lambda item: str(item.get("closureTimestamp") or item.get("eventStartTime") or ""),
        reverse=True,
    )


def personal_realized_pnl_summary(
    positions: list[dict[str, Any]], period: str, now: datetime | None = None
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(EASTERN)
    today = now.date()
    period = period if period in {"today", "week", "month", "year", "all"} else "week"
    starts = {
        "today": today,
        "week": today - timedelta(days=6),
        "month": today.replace(day=1),
        "year": today.replace(month=1, day=1),
        "all": None,
    }
    points_by_day: dict[Any, float] = defaultdict(float)
    for item in positions:
        exits = item.get("exits") or []
        total_shares = float(item.get("totalPurchasedShares") or 0)
        average_cost = (
            float(item.get("totalPaid") or 0) / total_shares
            if total_shares > 0
            else 0.0
        )
        exit_profit = 0.0
        for exit_record in exits:
            profit = float(exit_record.get("net_proceeds") or 0) - (
                float(exit_record.get("shares_sold") or 0) * average_cost
            )
            exit_profit += profit
            stamp = _cashflow_timestamp(exit_record.get("sold_at"))
            if stamp:
                points_by_day[stamp.astimezone(EASTERN).date()] += profit
        if item.get("isClosed") and item.get("closureTimestamp"):
            remaining_profit = float(item.get("realizedPnl") or 0) - exit_profit
            stamp = _cashflow_timestamp(item.get("closureTimestamp"))
            if stamp and (not exits or abs(remaining_profit) > 1e-9):
                points_by_day[stamp.astimezone(EASTERN).date()] += remaining_profit
    start = starts[period]
    selected = {
        day: value for day, value in points_by_day.items() if start is None or day >= start
    }
    running = 0.0
    graph = []
    for day in sorted(selected):
        running += selected[day]
        graph.append({"timestamp": day.isoformat(), "profitLoss": running})
    return {
        "period": period,
        "timezone": "America/New_York",
        "realizedPnl": sum(selected.values()),
        "todayPnl": points_by_day.get(today, 0.0),
        "yesterdayPnl": points_by_day.get(today - timedelta(days=1), 0.0),
        "graph": graph,
    }


def _cashflow_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
