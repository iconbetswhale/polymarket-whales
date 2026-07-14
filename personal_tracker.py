from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


ACTIVE_PERSONAL_STATUSES = {"scheduled", "live", "unresolved"}
SETTLED_PERSONAL_STATUSES = {"won", "lost", "push", "void", "canceled"}


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


def replay_personal_tracker(
    fills: list[dict[str, Any]], starting_bankroll: float = 10_000.0
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    realized_profit = 0.0
    open_exposure = 0.0
    potential_payout = 0.0
    total_wagered = 0.0
    settled_wagered = 0.0
    wins = losses = pushes_voids = 0

    for fill in fills:
        entry = float(fill.get("entry_price") or 0)
        shares = float(fill.get("shares") or 0)
        fees = float(fill.get("fees") or 0)
        position_cost = float(fill.get("position_cost") or (entry * shares))
        total_paid = float(fill.get("total_paid") or (position_cost + fees))
        status = str(fill.get("status") or "unresolved").lower()
        profit: float | None = None
        payout: float | None = None
        total_wagered += total_paid

        if status == "won":
            payout = shares
            profit = payout - total_paid
            wins += 1
        elif status == "lost":
            payout = 0.0
            profit = -total_paid
            losses += 1
        elif status in {"push", "void", "canceled"}:
            payout = position_cost
            profit = 0.0
            pushes_voids += 1
        elif status in ACTIVE_PERSONAL_STATUSES:
            open_exposure += total_paid
            potential_payout += shares

        if status in SETTLED_PERSONAL_STATUSES and profit is not None:
            realized_profit += profit
            settled_wagered += total_paid

        rows.append(
            {
                "fill_id": fill.get("fill_id"),
                "event_title": fill.get("event_title"),
                "market_title": fill.get("market_title"),
                "selection": fill.get("selection"),
                "event_start_time": fill.get("event_start_time"),
                "market_url": fill.get("market_url"),
                "entry_price": entry,
                "shares": shares,
                "position_cost": position_cost,
                "fees": fees,
                "total_paid": total_paid,
                "status": status,
                "result": fill.get("result"),
                "created_at": fill.get("created_at"),
                "settled_at": fill.get("settled_at"),
                "profit_loss": profit,
                "payout": payout,
            }
        )

    settled_rows = sorted(
        (
            row
            for row in rows
            if row["status"] in SETTLED_PERSONAL_STATUSES
            and row["profit_loss"] is not None
        ),
        key=lambda row: str(row.get("settled_at") or row.get("event_start_time") or ""),
    )
    running_profit = 0.0
    starting_bankroll = max(float(starting_bankroll), 0.01)
    graph = [
        {
            "timestamp": None,
            "profit_loss": 0.0,
            "bankroll": starting_bankroll,
        }
    ]
    for row in settled_rows:
        running_profit += float(row["profit_loss"] or 0)
        graph.append(
            {
                "timestamp": row.get("settled_at") or row.get("event_start_time"),
                "profit_loss": running_profit,
                "bankroll": starting_bankroll + running_profit,
            }
        )

    peak_bankroll = starting_bankroll
    maximum_drawdown = 0.0
    for point in graph:
        bankroll = float(point["bankroll"])
        peak_bankroll = max(peak_bankroll, bankroll)
        if peak_bankroll > 0:
            maximum_drawdown = max(
                maximum_drawdown, (peak_bankroll - bankroll) / peak_bankroll
            )

    decisions = wins + losses
    return {
        "rows": rows,
        "graph": graph,
        "summary": {
            "starting_bankroll": starting_bankroll,
            "current_bankroll": starting_bankroll + realized_profit,
            "realized_profit_loss": realized_profit,
            "roi": realized_profit / starting_bankroll,
            "total_tracked_bets": len(fills),
            "wins": wins,
            "losses": losses,
            "pushes_voids": pushes_voids,
            "win_rate": wins / decisions if decisions else None,
            "open_exposure": open_exposure,
            "potential_payout": potential_payout,
            "total_wagered": total_wagered,
            "settled_wagered": settled_wagered,
            "maximum_drawdown": maximum_drawdown,
        },
    }
