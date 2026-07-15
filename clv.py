from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


CLV_CALCULATION_VERSION = "clv-v1"
CLV_FRESHNESS_SECONDS = 300
CAPTURED = "captured"
PENDING = "pending"
UNAVAILABLE = "unavailable"
VOID = "void"
STALE_QUOTE = "stale_quote"
MARKET_MAPPING_ERROR = "market_mapping_error"


def safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalized_provider(value: Any) -> str:
    compact = "".join(character for character in str(value or "").lower() if character.isalnum())
    aliases = {
        "": "polymarket",
        "poly": "polymarket",
        "polymarket": "polymarket",
        "novig": "novig",
        "prophetx": "prophetx",
        "kalshi": "kalshi",
        "4cx": "4cx",
    }
    return aliases.get(compact, compact)


def probability_from_native_odds(value: Any, odds_format: str = "probability") -> float | None:
    odds = safe_float(value)
    if odds is None:
        return None
    if odds_format == "american":
        if odds == 0:
            return None
        return abs(odds) / (abs(odds) + 100) if odds < 0 else 100 / (odds + 100)
    if odds_format == "decimal":
        return 1 / odds if odds > 1 else None
    return odds if 0 < odds < 1 else None


def calculate_clv(entry_price: Any, closing_price: Any) -> dict[str, float]:
    entry = safe_float(entry_price)
    close = safe_float(closing_price)
    if entry is None or close is None or not 0 < entry < 1 or not 0 < close < 1:
        raise ValueError("Entry and closing probabilities must be between zero and one.")
    probability_points = (close - entry) * 100
    return {
        "clv_cents": probability_points,
        "clv_probability_points": probability_points,
        "clv_pct": ((close / entry) - 1) * 100,
    }


def book_effective_ask(asks: Iterable[dict[str, Any]], comparison_stake: Any) -> dict[str, Any]:
    target = safe_float(comparison_stake)
    if target is None or target <= 0:
        return {
            "effective_price": None,
            "executable_amount": 0.0,
            "unfilled_amount": max(target or 0.0, 0.0),
            "shares": 0.0,
            "levels_used": [],
            "liquidity_quality": "unavailable",
        }
    remaining = target
    cost = shares = 0.0
    levels_used: list[dict[str, float]] = []
    levels = sorted(
        (
            (safe_float(level.get("price")), safe_float(level.get("size")))
            for level in asks
        ),
        key=lambda level: level[0] if level[0] is not None else math.inf,
    )
    for price, size in levels:
        if price is None or size is None or not 0 < price < 1 or size <= 0 or remaining <= 0:
            continue
        available_cost = price * size
        used_cost = min(remaining, available_cost)
        used_shares = used_cost / price
        cost += used_cost
        shares += used_shares
        remaining -= used_cost
        levels_used.append({"price": price, "shares": used_shares, "cost": used_cost})
    return {
        "effective_price": cost / shares if shares else None,
        "executable_amount": cost,
        "unfilled_amount": max(remaining, 0.0),
        "shares": shares,
        "levels_used": levels_used,
        "liquidity_quality": "full" if remaining <= 1e-8 else ("partial" if cost else "unavailable"),
    }


def select_last_fresh_quote(
    quotes: Iterable[dict[str, Any]],
    official_start: Any,
    freshness_seconds: int = CLV_FRESHNESS_SECONDS,
) -> tuple[dict[str, Any] | None, str | None]:
    start = parse_timestamp(official_start)
    if start is None:
        return None, "MISSING_OFFICIAL_EVENT_START"
    eligible: list[tuple[datetime, dict[str, Any]]] = []
    for quote in quotes:
        timestamp = parse_timestamp(quote.get("quote_timestamp"))
        if timestamp is not None and timestamp <= start:
            eligible.append((timestamp, quote))
    if not eligible:
        return None, "NO_PRESTART_QUOTE"
    timestamp, quote = max(eligible, key=lambda item: item[0])
    if (start - timestamp).total_seconds() > freshness_seconds:
        return None, "NO_FRESH_CLOSING_QUOTE"
    return quote, None


def clv_aggregate(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    values: list[tuple[float, float, float]] = []
    missing = 0
    for row in rows:
        if str(row.get("clv_status") or "").lower() != CAPTURED:
            if str(row.get("clv_status") or "").lower() != VOID:
                missing += 1
            continue
        pct = safe_float(row.get("clv_pct"))
        cents = safe_float(row.get("clv_cents"))
        stake = safe_float(row.get("entry_stake"))
        if pct is None or cents is None or stake is None or stake <= 0:
            missing += 1
            continue
        values.append((pct, cents, stake))
    represented = sum(value[2] for value in values)
    positive = sum(1 for value in values if value[0] > 0)
    negative = sum(1 for value in values if value[0] < 0)
    return {
        "stake_weighted_clv_pct": (
            sum(pct * stake for pct, _cents, stake in values) / represented
            if represented
            else None
        ),
        "average_clv_pct": statistics.fmean(value[0] for value in values) if values else None,
        "median_clv_pct": statistics.median(value[0] for value in values) if values else None,
        "average_clv_cents": statistics.fmean(value[1] for value in values) if values else None,
        "bets_measured": len(values),
        "positive_clv_count": positive,
        "negative_clv_count": negative,
        "positive_clv_rate": positive / len(values) if values else None,
        "negative_clv_rate": negative / len(values) if values else None,
        "total_stake_represented": represented,
        "missing_clv_count": missing,
    }


def period_start(period: str, now: datetime | None = None) -> datetime | None:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if period == "today":
        return current.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        return (current - timedelta(days=current.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "7d":
        return current - timedelta(days=7)
    if period == "month":
        return current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if period == "year":
        return current.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return None


def clv_period_analytics(rows: list[dict[str, Any]], now: datetime | None = None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for period in ("today", "7d", "week", "month", "year", "all"):
        cutoff = period_start(period, now)
        selected = [
            row
            for row in rows
            if cutoff is None
            or ((parse_timestamp(row.get("closing_snapshot_timestamp")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff)
        ]
        result[period] = clv_aggregate(selected)
    return result


def clv_trend(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        captured = parse_timestamp(row.get("closing_snapshot_timestamp"))
        if captured is not None:
            groups.setdefault(captured.date().isoformat(), []).append(row)
    return [
        {"date": date, **clv_aggregate(group)}
        for date, group in sorted(groups.items())
    ]
