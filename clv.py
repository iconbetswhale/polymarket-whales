from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


CLV_CALCULATION_VERSION = "clv-v2-multi-exchange"
COMPOSITE_CLOSE_VERSION = "composite-clv-v2-exact-sources"
CLV_PREFERENCE_VERSION = "clv-preferences-v2-six-source-sharp-core"
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
    if compact.startswith("oddsapi"):
        compact = compact[len("oddsapi") :]
    aliases = {
        "": "polymarket",
        "poly": "polymarket",
        "polymarket": "polymarket",
        "novig": "novig",
        "prophetx": "prophetx",
        "betonline": "betonline",
        "betonlineag": "betonline",
        "circa": "circa",
        "circasports": "circa",
        "bookmaker": "bookmaker",
        "bookmakerag": "bookmaker",
        "bookmakereu": "bookmaker",
        "kalshi": "kalshi",
        "4cx": "4cx",
    }
    return aliases.get(compact, compact)


CLV_NO_VIG_PROVIDER_WEIGHTS = {
    "pinnacle": 0.25,
    "circa": 0.20,
    "bookmaker": 0.20,
    "betonline": 0.15,
    "novig": 0.10,
    "prophetx": 0.10,
}

CLV_NO_VIG_REQUIRED_SPORTSBOOKS = ("pinnacle", "circa", "bookmaker", "betonline")
CLV_NO_VIG_EXCHANGES = ("novig", "prophetx")
CLV_NO_VIG_REQUIRED_SOURCES = [
    *CLV_NO_VIG_REQUIRED_SPORTSBOOKS,
    "novig_or_prophetx",
]


def _preference_result(
    entry_price: Any,
    closing_probability: Any,
    *,
    providers: list[str],
    method: str,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    try:
        metrics = calculate_clv(entry_price, closing_probability)
    except ValueError:
        return {
            "status": UNAVAILABLE,
            "missing_reason": "INVALID_ENTRY_OR_CLOSING_PROBABILITY",
            "method": method,
            "calculation_version": CLV_PREFERENCE_VERSION,
        }
    return {
        "status": CAPTURED,
        "missing_reason": None,
        "method": method,
        "closing_probability": float(closing_probability),
        "clv_cents": metrics["clv_cents"],
        "clv_probability_points": metrics["clv_probability_points"],
        "clv_pct": metrics["clv_pct"],
        "providers": providers,
        "weights": weights or {},
        "calculation_version": CLV_PREFERENCE_VERSION,
    }


def _verified_provider_closes(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    verified: dict[str, dict[str, Any]] = {}
    for close in snapshot.get("provider_closes") or []:
        provider = normalized_provider(close.get("provider") or close.get("provider_name"))
        probability = safe_float(close.get("closing_probability"))
        mapping = str(close.get("mapping_confidence") or "EXACT").upper()
        if not provider or probability is None or not 0 < probability < 1 or mapping != "EXACT":
            continue
        verified[provider] = {**close, "closing_probability": probability}
    return verified


def _verified_no_vig_sources(snapshot: dict[str, Any]) -> dict[str, float]:
    sources: dict[str, float] = {}
    composite = snapshot.get("composite_close") or {}
    for contribution in composite.get("contributions") or []:
        source = contribution.get("source_snapshot") or {}
        provider = normalized_provider(contribution.get("provider") or source.get("provider"))
        probability = safe_float(
            contribution.get("no_vig_probability")
            if contribution.get("no_vig_probability") is not None
            else source.get("no_vig_probability")
        )
        mapping = str(source.get("mapping_confidence") or "").upper()
        status = str(source.get("status") or "").upper()
        tracker_eligible = contribution.get("included") is True or str(
            contribution.get("exclusion_reason") or ""
        ).upper() == "PROVIDER_WEIGHT_NOT_CONFIGURED"
        if (
            provider
            and tracker_eligible
            and probability is not None
            and 0 < probability < 1
            and mapping == "EXACT"
            and status == "AVAILABLE"
        ):
            sources[provider] = probability
    return sources


def calculate_clv_preferences(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Calculate immutable CLV views from exact closes already stored on a bet.

    Best available uses the most favorable verified close. The no-vig view is
    deliberately unavailable unless Pinnacle, Circa, BookMaker, BetOnline,
    and at least one of NoVIG or ProphetX contributed an exact, complete
    no-vig price.
    """
    entry = snapshot.get("entry_price")
    respective = {
        "status": str(snapshot.get("clv_status") or PENDING).lower(),
        "missing_reason": snapshot.get("clv_unavailable_reason"),
        "method": "respective",
        "closing_probability": safe_float(snapshot.get("closing_effective_price")),
        "clv_cents": safe_float(snapshot.get("clv_cents")),
        "clv_probability_points": safe_float(snapshot.get("clv_probability_points")),
        "clv_pct": safe_float(snapshot.get("clv_pct")),
        "providers": [normalized_provider(snapshot.get("provider"))],
        "weights": {},
        "calculation_version": CLV_PREFERENCE_VERSION,
    }

    closes = _verified_provider_closes(snapshot)
    if closes:
        best_provider, best_close = min(
            closes.items(), key=lambda item: item[1]["closing_probability"]
        )
        best = _preference_result(
            entry,
            best_close["closing_probability"],
            providers=[best_provider],
            method="best",
        )
    else:
        best = {
            "status": UNAVAILABLE,
            "missing_reason": "NO_VERIFIED_PROVIDER_CLOSES",
            "method": "best",
            "calculation_version": CLV_PREFERENCE_VERSION,
        }

    fair_sources = _verified_no_vig_sources(snapshot)
    missing = []
    for provider in CLV_NO_VIG_REQUIRED_SPORTSBOOKS:
        if provider not in fair_sources:
            missing.append(provider.upper())
    exchanges = [provider for provider in CLV_NO_VIG_EXCHANGES if provider in fair_sources]
    if not exchanges:
        missing.append("NOVIG_OR_PROPHETX")
    if missing:
        no_vig = {
            "status": UNAVAILABLE,
            "missing_reason": "MISSING_REQUIRED_NO_VIG_SOURCES:" + ",".join(missing),
            "method": "novig",
            "required_sources": CLV_NO_VIG_REQUIRED_SOURCES,
            "available_sources": sorted(fair_sources),
            "calculation_version": CLV_PREFERENCE_VERSION,
        }
    else:
        eligible = [*CLV_NO_VIG_REQUIRED_SPORTSBOOKS, *exchanges]
        total_weight = sum(CLV_NO_VIG_PROVIDER_WEIGHTS[provider] for provider in eligible)
        normalized_weights = {
            provider: CLV_NO_VIG_PROVIDER_WEIGHTS[provider] / total_weight
            for provider in eligible
        }
        fair_probability = sum(
            fair_sources[provider] * normalized_weights[provider]
            for provider in eligible
        )
        no_vig = _preference_result(
            entry,
            fair_probability,
            providers=eligible,
            method="novig",
            weights=normalized_weights,
        )
        no_vig["required_sources"] = CLV_NO_VIG_REQUIRED_SOURCES

    return {"respective": respective, "best": best, "novig": no_vig}


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
