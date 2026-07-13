from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


ACTIVE_PERSONAL_STATUSES = {"scheduled", "live", "unresolved"}


def normalize_market_line(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        normalized = Decimal(str(value)).normalize()
    except (InvalidOperation, TypeError, ValueError):
        return str(value).strip().lower()
    return format(normalized, "f")


def canonical_trade_identity(trade: dict[str, Any]) -> dict[str, str]:
    validation = trade.get("validation_ids") or {}
    return {
        "canonical_event_id": str(
            validation.get("event_id") or trade.get("event_slug") or ""
        )
        .strip()
        .lower(),
        "canonical_market_id": str(
            validation.get("condition_id") or trade.get("canonical_market_key") or ""
        )
        .strip()
        .lower(),
        "market_line": normalize_market_line(trade.get("market_line")),
        "canonical_outcome_id": str(
            validation.get("outcome_token_id")
            or trade.get("clob_token_id")
            or trade.get("canonical_side_key")
            or ""
        )
        .strip()
        .lower(),
    }


def identity_key(identity: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(identity.get("canonical_event_id") or "").strip().lower(),
        str(identity.get("canonical_market_id") or "").strip().lower(),
        normalize_market_line(identity.get("market_line")),
        str(identity.get("canonical_outcome_id") or "").strip().lower(),
    )


def has_complete_identity(identity: dict[str, Any]) -> bool:
    event_id, market_id, _line, outcome_id = identity_key(identity)
    return bool(event_id and market_id and outcome_id)


def hidden_trade_snapshot(trade: dict[str, Any]) -> dict[str, Any]:
    identity = canonical_trade_identity(trade)
    return {
        **identity,
        "event_title": trade.get("event_title") or trade.get("market_title"),
        "market_title": trade.get("market_title"),
        "selection": trade.get("outcome"),
        "event_start_time": trade.get("event_date_et"),
    }


def personal_fill_snapshot(
    trade: dict[str, Any],
    *,
    fill_id: str,
    entry_price: float,
    shares: float,
    fees: float,
) -> dict[str, Any]:
    identity = canonical_trade_identity(trade)
    position_cost = entry_price * shares
    validation = trade.get("validation_ids") or {}
    return {
        "fill_id": fill_id,
        **identity,
        "canonical_event_slug": trade.get("event_slug") or validation.get("event_slug"),
        "canonical_market_slug": validation.get("market_slug"),
        "event_title": trade.get("event_title") or trade.get("market_title"),
        "market_title": trade.get("market_title"),
        "selection": trade.get("outcome"),
        "recommended_side": trade.get("outcome"),
        "event_start_time": trade.get("event_date_et"),
        "market_url": trade.get("market_url"),
        "entry_price": entry_price,
        "shares": shares,
        "position_cost": position_cost,
        "fees": fees,
        "total_paid": position_cost + fees,
    }


def _aggregate(entries: list[dict[str, Any]]) -> dict[str, Any]:
    total_shares = sum(float(entry.get("shares") or 0) for entry in entries)
    total_cost = sum(float(entry.get("position_cost") or 0) for entry in entries)
    total_fees = sum(float(entry.get("fees") or 0) for entry in entries)
    total_paid = sum(float(entry.get("total_paid") or 0) for entry in entries)
    return {
        "entryCount": len(entries),
        "totalShares": total_shares,
        "totalPositionCost": total_cost,
        "averageEntry": total_cost / total_shares if total_shares > 0 else None,
        "totalFees": total_fees,
        "totalPaid": total_paid,
        "latestTrackedAt": max(
            (str(entry.get("created_at") or "") for entry in entries), default=""
        )
        or None,
        "statuses": sorted(
            {str(entry.get("status") or "unresolved").lower() for entry in entries}
        ),
    }


def _public_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "fillId": entry.get("fill_id"),
        "eventTitle": entry.get("event_title"),
        "marketTitle": entry.get("market_title"),
        "selection": entry.get("selection"),
        "marketLine": entry.get("market_line"),
        "entryPrice": entry.get("entry_price"),
        "shares": entry.get("shares"),
        "positionCost": entry.get("position_cost"),
        "fees": entry.get("fees"),
        "totalPaid": entry.get("total_paid"),
        "status": entry.get("status"),
        "trackedAt": entry.get("created_at"),
    }


def personal_exposure_for_trade(
    trade: dict[str, Any],
    active_fills: list[dict[str, Any]],
    *,
    include_entries: bool = False,
) -> dict[str, Any]:
    event_id, market_id, line, outcome_id = identity_key(
        canonical_trade_identity(trade)
    )
    same_event = [
        fill
        for fill in active_fills
        if str(fill.get("canonical_event_id") or "").lower() == event_id
    ]
    exact: list[dict[str, Any]] = []
    opposing: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []

    for fill in same_event:
        fill_market = str(fill.get("canonical_market_id") or "").lower()
        fill_line = normalize_market_line(fill.get("market_line"))
        fill_outcome = str(fill.get("canonical_outcome_id") or "").lower()
        if fill_market == market_id and fill_line == line:
            if fill_outcome == outcome_id:
                exact.append(fill)
            else:
                opposing.append(fill)
        else:
            other.append(fill)

    if opposing:
        exposure_type = "opposing"
        title = "Conflicting personal bet"
        message = (
            "You already have a personal position on the opposing outcome of "
            "this market."
        )
        primary = opposing
    elif exact:
        exposure_type = "exact"
        title = "Already tracked"
        message = (
            "You have already placed a personal bet on this exact market and selection."
        )
        primary = exact
    elif other:
        exposure_type = "same_event"
        title = "Same event, different market"
        message = "You already have another personal bet connected to this event."
        primary = other
    else:
        exposure_type = "none"
        title = None
        message = None
        primary = []

    payload: dict[str, Any] = {
        "type": exposure_type,
        "title": title,
        "message": message,
        "hasExactPersonalPosition": bool(exact),
        "hasOpposingPersonalPosition": bool(opposing),
        "hasSameEventDifferentMarketPosition": bool(other),
        "personalEntryCount": len(primary),
        "exactEntryCount": len(exact),
        "opposingEntryCount": len(opposing),
        "sameEventDifferentMarketEntryCount": len(other),
        "aggregate": _aggregate(primary),
    }
    if include_entries:
        payload["groups"] = {
            "exact": {
                "aggregate": _aggregate(exact),
                "entries": [_public_entry(entry) for entry in exact],
            },
            "opposing": {
                "aggregate": _aggregate(opposing),
                "entries": [_public_entry(entry) for entry in opposing],
            },
            "other": {
                "aggregate": _aggregate(other),
                "entries": [_public_entry(entry) for entry in other],
            },
        }
    return payload
