"""Deterministic sportsbook middle detection and two-leg stake sizing.

The scanner consumes the normalized SportsGameOdds event shape used by the
Positive EV and Arbitrage tools.  It pairs lower Overs with higher Unders and
overlapping opposing spreads, then sizes both legs so the two non-middle
outcomes return as close to the same payout as cent rounding permits.

No hit probability is invented.  Instead, each opportunity reports the exact
middle payoff, worst outside payoff, and the conservative middle probability
needed to break even.
"""

from __future__ import annotations

import hashlib
import json
import math
from statistics import median
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Iterable

from arbitrage import MARKET_LABELS, effective_decimal_odds, equalized_stakes
from ev_optimizer import american_to_decimal
from opportunity_execution import evaluate_execution_gates, quote_execution_metadata
from sports_game_odds import (
    SPORTS_GAME_ODDS_BOOKMAKERS,
    SPORTS_GAME_ODDS_DEFAULT_EXECUTION_BOOKS,
    SPORTS_GAME_ODDS_DFS_BOOKS,
    SPORTS_GAME_ODDS_EXCHANGE_BOOKS,
    SPORTS_GAME_ODDS_LOGOS,
)


MIDDLES_CALCULATION_VERSION = "iconlabs-middles-v3-probability-execution-gates"
MIN_AMERICAN_ODDS = -5_000
MAX_AMERICAN_ODDS = 5_000
SPREAD_MARKETS = {"spreads", "alternate_spreads"}
GAME_TOTAL_MARKETS = {"totals", "alternate_totals"}


def _parse_time(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _quote_age_seconds(value: object, now: datetime) -> float | None:
    parsed = _parse_time(value)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds())


def _valid_american(value: object) -> bool:
    try:
        odds = float(value)
    except (TypeError, ValueError):
        return False
    return (
        math.isfinite(odds)
        and odds != 0
        and MIN_AMERICAN_ODDS <= odds <= MAX_AMERICAN_ODDS
    )


def _point(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return round(result, 6) if math.isfinite(result) else None


def _book_logo(book_key: str, book: dict) -> str:
    return str(
        SPORTS_GAME_ODDS_LOGOS.get(book_key)
        or book.get("logo")
        or book.get("logo_url")
        or ""
    )


def _is_total_market(market_key: str) -> bool:
    return market_key in GAME_TOTAL_MARKETS or market_key.startswith(
        ("batter_", "pitcher_", "player_")
    )


def _market_family(market_key: str, outcome: dict) -> tuple | None:
    name = str(outcome.get("name") or "").strip().casefold()
    description = " ".join(str(outcome.get("description") or "").split()).casefold()
    if market_key in SPREAD_MARKETS:
        return (market_key,)
    if _is_total_market(market_key) and name in {"over", "under"}:
        return market_key, description
    return None


def _selection_label(quote: dict) -> str:
    name = quote["name"]
    point = quote["point"]
    description = quote.get("description") or ""
    if name.casefold() in {"over", "under"}:
        prefix = f"{description} · " if description else ""
        return f"{prefix}{name} {point:g}"
    return f"{name} {point:+g}"


def _middle_integer_window(low: float, high: float) -> tuple[int | None, int | None, int]:
    first = math.floor(low) + 1
    last = math.ceil(high) - 1
    count = max(0, last - first + 1)
    if count == 0:
        return None, None, 0
    return first, last, count


def _window_payload(kind: str, first: dict, second: dict) -> dict:
    if kind == "total":
        low = first["point"]
        high = second["point"]
        first_integer, last_integer, count = _middle_integer_window(low, high)
        if count == 1:
            label = str(first_integer)
        elif count > 1:
            label = f"{first_integer}–{last_integer}"
        else:
            label = f"{low:g}–{high:g}"
        subject = first.get("description") or "Combined score"
        return {
            "kind": kind,
            "low": low,
            "high": high,
            "width": round(high - low, 4),
            "label": label,
            "condition": f"Both bets win when {subject.lower()} is above {low:g} and below {high:g}.",
            "integerOutcomeCount": count,
        }

    # Relative to the first selected team/player, its margin must be greater
    # than -pointA and less than pointB for both opposing spreads to win.
    low = -first["point"]
    high = second["point"]
    first_integer, last_integer, count = _middle_integer_window(low, high)
    if count == 1:
        label = f"{first['name']} margin {first_integer:+d}"
    elif count > 1:
        label = f"{first['name']} margin {first_integer:+d} to {last_integer:+d}"
    else:
        label = f"{first['name']} margin {low:g}–{high:g}"
    possessive = f"{first['name']}'" if first["name"].lower().endswith("s") else f"{first['name']}'s"
    return {
        "kind": kind,
        "low": low,
        "high": high,
        "width": round(high - low, 4),
        "label": label,
        "condition": (
            f"Both bets win when {possessive} margin is above {low:g} "
            f"and below {high:g}."
        ),
        "integerOutcomeCount": count,
    }


def _push_scenarios(kind: str, first: dict, second: dict, stakes: list[float]) -> list[dict]:
    scenarios: list[dict] = []
    total_stake = round(sum(stakes), 2)
    boundaries = (
        (
            first["point"] if kind == "total" else -first["point"],
            1,
            f"Exactly {first['point']:g}" if kind == "total" else f"{first['name']} spread pushes",
        ),
        (
            second["point"],
            0,
            f"Exactly {second['point']:g}" if kind == "total" else f"{second['name']} spread pushes",
        ),
    )
    for boundary, winning_index, label in boundaries:
        if not float(boundary).is_integer():
            continue
        pushed_index = 1 - winning_index
        profit = (
            stakes[pushed_index]
            + stakes[winning_index] * [first, second][winning_index]["effectiveDecimalOdds"]
            - total_stake
        )
        scenarios.append(
            {
                "label": label,
                "profit": round(profit, 2),
                "pushedLeg": pushed_index + 1,
                "winningLeg": winning_index + 1,
            }
        )
    return scenarios


def _candidate_key(event_id: str, market_key: str, family: tuple, first: dict, second: dict) -> tuple:
    if _is_total_market(market_key):
        return event_id, market_key, family, first["point"], second["point"]
    selections = sorted(
        ((first["name"].casefold(), first["point"]), (second["name"].casefold(), second["point"]))
    )
    return event_id, market_key, family, tuple(selections)


def _market_ladder_middle_probability(
    market_key: str,
    first: dict,
    second: dict,
    family_quotes: list[dict],
) -> dict:
    """Estimate a total/prop middle only from paired market-ladder prices.

    A same-book Over/Under pair at a line is de-vigged into a CDF point. The
    difference between median CDF values at the two boundaries estimates the
    window probability. Spreads remain unavailable until an equivalent
    settlement-aligned ladder is present; no sport-level distribution is
    fabricated.
    """
    if not _is_total_market(market_key):
        return {"status": "UNAVAILABLE", "reason": "SPREAD_LADDER_MODEL_NOT_AVAILABLE"}
    by_book_line: dict[tuple[str, float], dict[str, dict]] = defaultdict(dict)
    for quote in family_quotes:
        name = str(quote.get("name") or "").strip().lower()
        point = _point(quote.get("point"))
        if name not in {"over", "under"} or point is None:
            continue
        by_book_line[(str(quote.get("bookKey") or ""), point)][name] = quote

    under_probabilities: dict[float, list[float]] = defaultdict(list)
    for (_book_key, point), sides in by_book_line.items():
        if not {"over", "under"}.issubset(sides):
            continue
        over_probability = 1.0 / float(sides["over"]["decimalOdds"])
        under_probability = 1.0 / float(sides["under"]["decimalOdds"])
        total = over_probability + under_probability
        if total > 0:
            under_probabilities[point].append(under_probability / total)

    low = min(float(first["point"]), float(second["point"]))
    high = max(float(first["point"]), float(second["point"]))
    low_values = under_probabilities.get(low) or []
    high_values = under_probabilities.get(high) or []
    if not low_values or not high_values:
        return {"status": "UNAVAILABLE", "reason": "INSUFFICIENT_PAIRED_LADDER_QUOTES"}
    low_cdf = median(low_values)
    high_cdf = median(high_values)
    probability = max(0.0, min(1.0, high_cdf - low_cdf))
    return {
        "status": "AVAILABLE",
        "method": "DEVIGGED_MARKET_LADDER_CDF",
        "probability": probability,
        "lowBoundary": low,
        "highBoundary": high,
        "lowSourceCount": len(low_values),
        "highSourceCount": len(high_values),
        "lowUnderProbability": low_cdf,
        "highUnderProbability": high_cdf,
    }


def _pair_payload(
    event: dict,
    market_key: str,
    family: tuple,
    first: dict,
    second: dict,
    *,
    family_quotes: list[dict],
    total_stake: float,
    stake_mode: str,
    commission_bps: float,
    require_distinct_books: bool,
    now: datetime,
) -> dict | None:
    decimals = [first["effectiveDecimalOdds"], second["effectiveDecimalOdds"]]
    normalized_stake_mode = "first-leg" if stake_mode == "first-leg" else "total"
    try:
        if normalized_stake_mode == "first-leg":
            locked_stake = round(float(total_stake), 2)
            target_payout = locked_stake * decimals[0]
            raw_second_cents = target_payout / decimals[1] * 100.0
            second_cents = min(
                {max(1, math.floor(raw_second_cents)), max(1, math.ceil(raw_second_cents))},
                key=lambda cents: (
                    abs((cents / 100.0) * decimals[1] - target_payout),
                    cents,
                ),
            )
            stakes = [locked_stake, second_cents / 100.0]
        else:
            stakes = equalized_stakes(total_stake, decimals)
    except ValueError:
        return None

    actual_total = round(sum(stakes), 2)
    outside_payouts = [stakes[index] * decimals[index] for index in range(2)]
    outside_profits = [payout - actual_total for payout in outside_payouts]
    worst_profit = min(outside_profits)
    middle_payout = sum(outside_payouts)
    middle_profit = middle_payout - actual_total
    if middle_profit <= 0:
        return None
    cost_percent = max(0.0, (-worst_profit / actual_total) * 100.0)
    middle_profit_percent = (middle_profit / actual_total) * 100.0
    break_even = (
        (-worst_profit) / (middle_profit - worst_profit)
        if worst_profit < 0
        else 0.0
    )
    probability_model = _market_ladder_middle_probability(
        market_key, first, second, family_quotes
    )
    estimated_probability = probability_model.get("probability")
    estimated_ev_percent = None
    edge_vs_break_even = None
    if estimated_probability is not None:
        estimated_profit = (
            float(estimated_probability) * middle_profit
            + (1.0 - float(estimated_probability))
            * (sum(outside_profits) / 2.0)
        )
        estimated_ev_percent = (estimated_profit / actual_total) * 100.0
        edge_vs_break_even = float(estimated_probability) - break_even

    kind = "total" if _is_total_market(market_key) else "spread"
    window = _window_payload(kind, first, second)
    legs = []
    for index, quote in enumerate((first, second)):
        legs.append(
            {
                **quote,
                "selection": _selection_label(quote),
                "stake": round(stakes[index], 2),
                "outsidePayout": round(outside_payouts[index], 2),
                "outsideProfit": round(outside_profits[index], 2),
            }
        )

    away = str(event.get("away_team") or "")
    home = str(event.get("home_team") or "")
    title = (
        f"{away} vs {home}"
        if away and home
        else away or home or str(event.get("title") or event.get("id") or "Event")
    )
    digest = hashlib.sha256(
        json.dumps(
            [event.get("id"), market_key, family, first["name"], first["point"], second["name"], second["point"]],
            default=str,
        ).encode()
    ).hexdigest()[:18]
    warnings = []
    if any(leg["quoteAgeSeconds"] is None for leg in legs):
        warnings.append("One or more books did not provide a quote timestamp.")
    if commission_bps > 0 and any(
        leg["bookKey"] in SPORTS_GAME_ODDS_EXCHANGE_BOOKS for leg in legs
    ):
        warnings.append(
            f"A {commission_bps / 100:.2f}% commission buffer is included on exchange winnings."
        )

    all_quotes = []
    for selected in (first, second):
        alternatives = [
            quote
            for quote in family_quotes
            if quote["name"].casefold() == selected["name"].casefold()
            and quote["point"] == selected["point"]
        ]
        alternatives.sort(key=lambda quote: quote["effectiveDecimalOdds"], reverse=True)
        all_quotes.append(
            {
                "selection": _selection_label(selected),
                "bestBookKey": selected["bookKey"],
                "quotes": alternatives,
            }
        )

    return {
        "id": f"middle::{digest}",
        "eventId": str(event.get("id") or ""),
        "sportKey": str(event.get("sport_key") or ""),
        "league": str(event.get("sport_title") or event.get("sport_key") or ""),
        "eventTitle": title,
        "awayTeam": " ".join(away.split()),
        "homeTeam": " ".join(home.split()),
        "participantLogos": (
            event.get("participantLogos")
            or event.get("participant_logos")
            or event.get("teamLogos")
            or event.get("team_logos")
            or {}
        ),
        "commenceTime": str(event.get("commence_time") or ""),
        "marketKey": market_key,
        "marketLabel": MARKET_LABELS.get(market_key, market_key.replace("_", " ").title()),
        "marketContext": first.get("description") or "",
        "kind": kind,
        "legs": legs,
        "allQuotes": all_quotes,
        "booksUsed": list(dict.fromkeys(leg["bookKey"] for leg in legs)),
        "bookCount": len(set(leg["bookKey"] for leg in legs)),
        "window": window,
        "middleWidth": window["width"],
        "middleOutcomeCount": window["integerOutcomeCount"],
        "stakeMode": normalized_stake_mode,
        "stakeInputAmount": round(float(total_stake), 2),
        "baselineLegIndex": 0 if normalized_stake_mode == "first-leg" else None,
        "baselineStake": round(stakes[0], 2) if normalized_stake_mode == "first-leg" else None,
        "totalStake": actual_total,
        "worstCaseProfit": round(worst_profit, 2),
        "averageOutsideProfit": round(sum(outside_profits) / 2.0, 2),
        "costPercent": round(cost_percent, 2),
        "middlePayout": round(middle_payout, 2),
        "middleProfit": round(middle_profit, 2),
        "middleProfitPercent": round(middle_profit_percent, 2),
        "breakEvenMiddleProbability": round(break_even * 100.0, 2),
        "estimatedMiddleProbability": (
            round(float(estimated_probability) * 100.0, 2)
            if estimated_probability is not None
            else None
        ),
        "estimatedEvPercent": (
            round(estimated_ev_percent, 2)
            if estimated_ev_percent is not None
            else None
        ),
        "edgeVsBreakEvenProbabilityPoints": (
            round(edge_vs_break_even * 100.0, 2)
            if edge_vs_break_even is not None
            else None
        ),
        "probabilityModel": probability_model,
        "guaranteedOutsideProfit": worst_profit >= 0,
        "pushScenarios": _push_scenarios(kind, first, second, stakes),
        "commissionBps": float(commission_bps),
        "requireDistinctBooks": bool(require_distinct_books),
        "warnings": warnings,
        "calculatedAt": now.isoformat(),
        "calculationVersion": MIDDLES_CALCULATION_VERSION,
    }


def build_middles_board(
    events: Iterable[dict],
    *,
    selected_books: Iterable[str] = SPORTS_GAME_ODDS_DEFAULT_EXECUTION_BOOKS,
    allowed_markets: Iterable[str] = (),
    total_stake: float = 1_000.0,
    stake_mode: str = "total",
    min_middle_width: float = 0.5,
    max_cost_percent: float = 12.0,
    max_quote_age_seconds: int = 90,
    max_cross_leg_skew_seconds: int = 3,
    commission_bps: float = 0.0,
    require_distinct_books: bool = True,
    required_book: str = "",
    now: datetime | None = None,
) -> dict:
    """Build a ranked board of executable two-leg middle opportunities."""

    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    requested_books = {
        str(value).strip().lower()
        for value in selected_books
        if str(value).strip().lower() in SPORTS_GAME_ODDS_BOOKMAKERS
        and str(value).strip().lower() not in SPORTS_GAME_ODDS_DFS_BOOKS
    }
    requested_markets = {
        str(value).strip().lower() for value in allowed_markets if str(value).strip()
    }
    required_book_key = str(required_book or "").strip().lower()
    rejected: Counter[str] = Counter()
    best_by_window: dict[tuple, dict] = {}
    event_count = 0
    market_count = 0

    for event in events:
        if not isinstance(event, dict):
            continue
        event_count += 1
        event_id = str(event.get("id") or "").strip()
        commence_at = _parse_time(event.get("commence_time"))
        if not event_id or commence_at is None:
            rejected["invalid_event"] += 1
            continue
        if commence_at <= now:
            rejected["event_started"] += 1
            continue

        families: dict[tuple, list[dict]] = defaultdict(list)
        seen_quotes: set[tuple] = set()
        for book in event.get("bookmakers") or []:
            if not isinstance(book, dict):
                continue
            book_key = str(book.get("key") or "").strip().lower()
            if book_key not in requested_books:
                continue
            for market in book.get("markets") or []:
                market_key = str(market.get("key") or "").strip().lower()
                if requested_markets and market_key not in requested_markets:
                    continue
                age = _quote_age_seconds(
                    market.get("last_update") or book.get("last_update"), now
                )
                if age is None:
                    rejected["missing_quote_timestamp"] += 1
                    continue
                if age > max_quote_age_seconds:
                    rejected["stale_quote"] += 1
                    continue
                for outcome in market.get("outcomes") or []:
                    if not isinstance(outcome, dict) or not _valid_american(outcome.get("price")):
                        rejected["invalid_quote"] += 1
                        continue
                    point = _point(outcome.get("point"))
                    family = _market_family(market_key, outcome)
                    if point is None or family is None:
                        rejected["unsupported_outcome"] += 1
                        continue
                    name = " ".join(str(outcome.get("name") or "").split())
                    description = " ".join(str(outcome.get("description") or "").split())
                    unique = (book_key, market_key, family, name.casefold(), point)
                    if unique in seen_quotes:
                        continue
                    seen_quotes.add(unique)
                    american = int(round(float(outcome["price"])))
                    applied_commission = (
                        commission_bps if book_key in SPORTS_GAME_ODDS_EXCHANGE_BOOKS else 0.0
                    )
                    quote = {
                        "bookKey": book_key,
                        "bookName": str(
                            book.get("title")
                            or SPORTS_GAME_ODDS_BOOKMAKERS.get(book_key, {}).get("name")
                            or book_key
                        ),
                        "logoUrl": _book_logo(book_key, book),
                        "name": name,
                        "description": description,
                        "point": point,
                        "americanOdds": american,
                        "decimalOdds": round(american_to_decimal(american), 6),
                        "effectiveDecimalOdds": round(
                            effective_decimal_odds(american, commission_bps=applied_commission), 6
                        ),
                        "commissionBps": applied_commission,
                        "lastUpdated": str(
                            market.get("last_update") or book.get("last_update") or ""
                        ),
                        "quoteAgeSeconds": round(age, 1) if age is not None else None,
                        "deepLink": str(
                            outcome.get("link") or market.get("link") or book.get("link") or ""
                        ),
                        **quote_execution_metadata(
                            book_key=book_key,
                            book=book,
                            market=market,
                            outcome=outcome,
                        ),
                    }
                    families[family].append(quote)

        for family, quotes in families.items():
            market_count += 1
            market_key = family[0]
            if _is_total_market(market_key):
                first_quotes = [row for row in quotes if row["name"].casefold() == "over"]
                second_quotes = [row for row in quotes if row["name"].casefold() == "under"]
                pairs = (
                    (first, second)
                    for first in first_quotes
                    for second in second_quotes
                    if first["point"] < second["point"]
                )
            else:
                pairs = (
                    (quotes[left], quotes[right])
                    for left in range(len(quotes))
                    for right in range(left + 1, len(quotes))
                    if quotes[left]["name"].casefold() != quotes[right]["name"].casefold()
                    and quotes[left]["point"] + quotes[right]["point"] > 0
                )

            found_pair = False
            for first, second in pairs:
                if require_distinct_books and first["bookKey"] == second["bookKey"]:
                    rejected["same_book"] += 1
                    continue
                if required_book_key and required_book_key not in {
                    first["bookKey"], second["bookKey"]
                }:
                    rejected["required_book_missing"] += 1
                    continue
                quote_skew = abs(
                    float(first["quoteAgeSeconds"])
                    - float(second["quoteAgeSeconds"])
                )
                if quote_skew > max(0, int(max_cross_leg_skew_seconds)):
                    rejected["cross_leg_quote_skew"] += 1
                    continue
                found_pair = True
                if market_key in SPREAD_MARKETS:
                    # Orient the pair so window math is consistently relative
                    # to the first selection.
                    if first["name"].casefold() > second["name"].casefold():
                        first, second = second, first
                window = _window_payload(
                    "total" if _is_total_market(market_key) else "spread", first, second
                )
                if window["width"] + 1e-9 < min_middle_width:
                    rejected["below_minimum_width"] += 1
                    continue
                payload = _pair_payload(
                    event,
                    market_key,
                    family,
                    first,
                    second,
                    family_quotes=quotes,
                    total_stake=total_stake,
                    stake_mode=stake_mode,
                    commission_bps=commission_bps,
                    require_distinct_books=require_distinct_books,
                    now=now,
                )
                if payload is None:
                    rejected["invalid_stake"] += 1
                    continue
                payload["crossLegQuoteSkewSeconds"] = round(quote_skew, 1)
                payload["maxCrossLegQuoteSkewSeconds"] = max(
                    0, int(max_cross_leg_skew_seconds)
                )
                execution = evaluate_execution_gates(
                    payload["legs"],
                    [float(leg["stake"]) for leg in payload["legs"]],
                    require_distinct_books=require_distinct_books,
                    quote_skew_seconds=quote_skew,
                    max_quote_skew_seconds=max(
                        0, int(max_cross_leg_skew_seconds)
                    ),
                )
                if execution["hardFailure"]:
                    for reason in execution["failureReasons"]:
                        rejected[f"execution_{str(reason).lower()}"] += 1
                    continue
                payload["executionStatus"] = execution["status"]
                payload["isExecutable"] = execution["isExecutable"]
                payload["executionGates"] = execution["gates"]
                payload["maximumExecutableTotalStake"] = execution[
                    "maximumExecutableTotalStake"
                ]
                payload["warnings"].extend(execution["warnings"])
                if payload["costPercent"] > max_cost_percent + 1e-9:
                    rejected["above_maximum_cost"] += 1
                    continue
                key = _candidate_key(event_id, market_key, family, first, second)
                current = best_by_window.get(key)
                rank = (
                    payload["guaranteedOutsideProfit"],
                    -payload["costPercent"],
                    payload["middleProfitPercent"],
                )
                current_rank = (
                    current["guaranteedOutsideProfit"],
                    -current["costPercent"],
                    current["middleProfitPercent"],
                ) if current else None
                if current is None or rank > current_rank:
                    best_by_window[key] = payload
            if not found_pair:
                rejected["no_middle_pair"] += 1

    opportunities = list(best_by_window.values())
    opportunities.sort(
        key=lambda row: (
            row["guaranteedOutsideProfit"],
            -row["breakEvenMiddleProbability"],
            row["middleWidth"],
            row["middleProfitPercent"],
        ),
        reverse=True,
    )
    return {
        "data": opportunities,
        "diagnostics": {
            "eventsScanned": event_count,
            "marketsCompared": market_count,
            "qualified": len(opportunities),
            "rejected": sum(rejected.values()),
            "rejectionReasons": dict(sorted(rejected.items())),
            "selectedBookCount": len(requested_books),
            "requiredBook": required_book_key or None,
            "calculationVersion": MIDDLES_CALCULATION_VERSION,
        },
    }
