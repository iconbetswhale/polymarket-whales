"""Deterministic sportsbook arbitrage detection and stake equalization.

The scanner consumes the same normalized event shape as ``ev_optimizer`` but
does not estimate a fair probability.  It only compares complete, identical
markets and reports an opportunity when the best executable prices across all
outcomes imply less than 100% probability after the configured fee buffer.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Iterable

from ev_optimizer import american_to_decimal
from opportunity_execution import evaluate_execution_gates, quote_execution_metadata
from sports_game_odds import (
    SPORTS_GAME_ODDS_BOOKMAKERS,
    SPORTS_GAME_ODDS_DEFAULT_EXECUTION_BOOKS,
    SPORTS_GAME_ODDS_DFS_BOOKS,
    SPORTS_GAME_ODDS_EXCHANGE_BOOKS,
    SPORTS_GAME_ODDS_LOGOS,
)


ARBITRAGE_CALCULATION_VERSION = "iconlabs-arbitrage-v2-execution-gates"
MIN_AMERICAN_ODDS = -5_000
MAX_AMERICAN_ODDS = 5_000

MARKET_LABELS = {
    "h2h": "Moneyline",
    "spreads": "Spread",
    "totals": "Game Total",
    "alternate_spreads": "Alt Spread",
    "alternate_totals": "Alt Total",
    "batter_hits": "Hits",
    "batter_total_bases": "Total Bases",
    "batter_home_runs": "Home Runs",
    "batter_rbis": "RBIs",
    "batter_runs_scored": "Runs",
    "batter_hits_runs_rbis": "Hits + Runs + RBIs",
    "pitcher_strikeouts": "Pitcher Strikeouts",
    "pitcher_hits_allowed": "Hits Allowed",
    "pitcher_walks": "Pitcher Walks",
    "pitcher_earned_runs": "Earned Runs",
    "player_points": "Points",
    "player_rebounds": "Rebounds",
    "player_assists": "Assists",
    "player_threes": "3-Pointers",
    "player_points_rebounds_assists": "Pts + Reb + Ast",
}


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


def _normalized_point(value: object) -> float | str | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value).strip().casefold()
    return round(number, 6)


def _market_group_key(market_key: str, outcome: dict) -> tuple:
    point = _normalized_point(outcome.get("point"))
    description = str(outcome.get("description") or "").strip().casefold()
    if market_key in {"spreads", "alternate_spreads"}:
        try:
            point = abs(float(point)) if point is not None else None
        except (TypeError, ValueError):
            pass
        return market_key, point
    if market_key in {"totals", "alternate_totals"}:
        return market_key, point
    if market_key.startswith(("batter_", "pitcher_", "player_")):
        return market_key, description, point
    if description:
        return market_key, description, point
    return (market_key,)


def _selection_key(outcome: dict) -> tuple:
    return (
        str(outcome.get("name") or "").strip().casefold(),
        str(outcome.get("description") or "").strip().casefold(),
        _normalized_point(outcome.get("point")),
    )


def _selection_label(market_key: str, outcome: dict) -> str:
    name = " ".join(str(outcome.get("name") or "").split())
    description = " ".join(str(outcome.get("description") or "").split())
    point = _normalized_point(outcome.get("point"))
    lowered = name.casefold()
    if lowered in {"over", "under"}:
        return f"{description + ' · ' if description else ''}{name} {point:g}".strip()
    if lowered in {"yes", "no"} and description:
        return f"{description} · {name}"
    if point is not None and market_key != "h2h":
        try:
            return f"{name} {float(point):+g}".strip()
        except (TypeError, ValueError):
            return f"{name} {point}".strip()
    return description or name or "Outcome"


def _market_context(group_key: tuple) -> str | float | None:
    values = [value for value in group_key[1:] if value not in {None, ""}]
    if not values:
        return None
    return " · ".join(str(value) for value in values)


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


def effective_decimal_odds(
    american_odds: int | float,
    *,
    commission_bps: float = 0.0,
) -> float:
    """Return decimal odds after commission on net winnings.

    A 100 bps buffer converts decimal 2.00 to 1.99: the returned stake is not
    charged, while one percent of the 1.00 net win is reserved for fees.
    """

    decimal = american_to_decimal(american_odds)
    rate = min(0.25, max(0.0, float(commission_bps)) / 10_000.0)
    return 1.0 + ((decimal - 1.0) * (1.0 - rate))


def _best_assignment(
    quote_lists: list[list[dict]],
    *,
    require_distinct_books: bool,
) -> list[dict] | None:
    if any(not quotes for quotes in quote_lists):
        return None
    ordered = [
        sorted(quotes, key=lambda row: row["effectiveDecimalOdds"], reverse=True)
        for quotes in quote_lists
    ]
    if not require_distinct_books:
        return [quotes[0] for quotes in ordered]

    best_score = math.inf
    best: list[dict] | None = None
    optimistic = [1.0 / quotes[0]["effectiveDecimalOdds"] for quotes in ordered]

    def visit(index: int, used: set[str], score: float, chosen: list[dict]) -> None:
        nonlocal best, best_score
        if index == len(ordered):
            if score < best_score:
                best_score = score
                best = list(chosen)
            return
        lower_bound = score + sum(optimistic[index:])
        if lower_bound >= best_score:
            return
        for quote in ordered[index]:
            book_key = quote["bookKey"]
            if book_key in used:
                continue
            next_score = score + (1.0 / quote["effectiveDecimalOdds"])
            if next_score + sum(optimistic[index + 1 :]) >= best_score:
                continue
            used.add(book_key)
            chosen.append(quote)
            visit(index + 1, used, next_score, chosen)
            chosen.pop()
            used.remove(book_key)

    visit(0, set(), 0.0, [])
    return best


def equalized_stakes(total_stake: float, decimal_odds: list[float]) -> list[float]:
    """Allocate a fixed total stake to maximize the minimum rounded payout."""

    if total_stake <= 0 or len(decimal_odds) < 2:
        raise ValueError("A positive stake and at least two outcomes are required.")
    if any(not math.isfinite(value) or value <= 1.0 for value in decimal_odds):
        raise ValueError("Decimal odds must be finite and greater than 1.0.")
    total_cents = int(round(total_stake * 100.0))
    if total_cents < len(decimal_odds):
        raise ValueError("The stake is too small to allocate at least one cent per leg.")
    inverse_sum = sum(1.0 / value for value in decimal_odds)
    ideals = [total_cents * ((1.0 / value) / inverse_sum) for value in decimal_odds]
    cents = [max(1, int(math.floor(value))) for value in ideals]
    while sum(cents) > total_cents:
        candidates = [index for index, value in enumerate(cents) if value > 1]
        index = max(candidates, key=lambda item: cents[item] - ideals[item])
        cents[index] -= 1
    while sum(cents) < total_cents:
        payouts = [(cents[index] / 100.0) * decimal_odds[index] for index in range(len(cents))]
        cents[min(range(len(cents)), key=lambda item: payouts[item])] += 1
    return [value / 100.0 for value in cents]


def _book_logo(book_key: str, book: dict) -> str:
    return str(
        SPORTS_GAME_ODDS_LOGOS.get(book_key)
        or book.get("logo")
        or book.get("logo_url")
        or ""
    )


def build_arbitrage_board(
    events: Iterable[dict],
    *,
    selected_books: Iterable[str] = SPORTS_GAME_ODDS_DEFAULT_EXECUTION_BOOKS,
    allowed_markets: Iterable[str] = (),
    total_stake: float = 1_000.0,
    min_profit_percent: float = 0.1,
    max_quote_age_seconds: int = 90,
    max_cross_leg_skew_seconds: int = 3,
    commission_bps: float = 0.0,
    require_distinct_books: bool = True,
    now: datetime | None = None,
) -> dict:
    """Build a ranked, fee-aware board of complete arbitrage opportunities."""

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
    rejected: Counter[str] = Counter()
    opportunities: list[dict] = []
    event_count = 0
    market_count = 0

    for event in events:
        if not isinstance(event, dict):
            continue
        event_count += 1
        event_id = str(event.get("id") or "").strip()
        commence_time = str(event.get("commence_time") or "").strip()
        commence_at = _parse_time(commence_time)
        if not event_id or commence_at is None:
            rejected["invalid_event"] += 1
            continue
        if commence_at <= now:
            rejected["event_started"] += 1
            continue

        grouped: dict[tuple[str, tuple], dict[str, dict]] = defaultdict(dict)
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
                outcomes_by_group: dict[tuple, dict[tuple, dict]] = defaultdict(dict)
                for outcome in market.get("outcomes") or []:
                    if not isinstance(outcome, dict) or not _valid_american(outcome.get("price")):
                        continue
                    group_key = _market_group_key(market_key, outcome)
                    outcomes_by_group[group_key][_selection_key(outcome)] = outcome
                for group_key, outcomes in outcomes_by_group.items():
                    if not outcomes:
                        continue
                    age = _quote_age_seconds(
                        market.get("last_update") or book.get("last_update"), now
                    )
                    existing = grouped[(market_key, group_key)].get(book_key)
                    candidate = {
                        "book": book,
                        "market": market,
                        "outcomes": outcomes,
                        "age": age,
                    }
                    if existing is None or len(outcomes) > len(existing["outcomes"]):
                        grouped[(market_key, group_key)][book_key] = candidate

        for (market_key, group_key), book_markets in grouped.items():
            market_count += 1
            signatures = Counter(
                frozenset(payload["outcomes"].keys())
                for payload in book_markets.values()
                if len(payload["outcomes"]) >= 2
            )
            if not signatures:
                rejected["incomplete_market"] += 1
                continue
            signature = max(
                signatures,
                key=lambda item: (signatures[item], len(item), sorted(map(str, item))),
            )
            if len(signature) < 2:
                rejected["incomplete_market"] += 1
                continue

            labels: dict[tuple, dict] = {}
            quotes_by_selection: dict[tuple, list[dict]] = defaultdict(list)
            for book_key, payload in book_markets.items():
                if frozenset(payload["outcomes"].keys()) != signature:
                    continue
                age = payload["age"]
                if age is None:
                    rejected["missing_quote_timestamp"] += 1
                    continue
                if age > max_quote_age_seconds:
                    rejected["stale_quote"] += 1
                    continue
                book = payload["book"]
                market = payload["market"]
                for selection, outcome in payload["outcomes"].items():
                    labels[selection] = outcome
                    american = int(round(float(outcome["price"])))
                    decimal = american_to_decimal(american)
                    applied_commission = (
                        commission_bps if book_key in SPORTS_GAME_ODDS_EXCHANGE_BOOKS else 0.0
                    )
                    effective_decimal = effective_decimal_odds(
                        american, commission_bps=applied_commission
                    )
                    quotes_by_selection[selection].append(
                        {
                            "bookKey": book_key,
                            "bookName": str(
                                book.get("title")
                                or SPORTS_GAME_ODDS_BOOKMAKERS.get(book_key, {}).get("name")
                                or book_key
                            ),
                            "logoUrl": _book_logo(book_key, book),
                            "americanOdds": american,
                            "decimalOdds": round(decimal, 6),
                            "effectiveDecimalOdds": round(effective_decimal, 6),
                            "commissionBps": applied_commission,
                            "lastUpdated": str(
                                market.get("last_update") or book.get("last_update") or ""
                            ),
                            "quoteAgeSeconds": round(age, 1) if age is not None else None,
                            "deepLink": str(
                                outcome.get("link")
                                or market.get("link")
                                or book.get("link")
                                or ""
                            ),
                            "point": outcome.get("point"),
                            **quote_execution_metadata(
                                book_key=book_key,
                                book=book,
                                market=market,
                                outcome=outcome,
                            ),
                        }
                    )

            ordered_selections = sorted(signature, key=lambda value: tuple(str(part) for part in value))
            quote_lists = [quotes_by_selection.get(selection, []) for selection in ordered_selections]
            assignment = _best_assignment(
                quote_lists, require_distinct_books=require_distinct_books
            )
            if assignment is None:
                rejected["no_valid_book_assignment"] += 1
                continue
            quote_ages = [float(quote["quoteAgeSeconds"]) for quote in assignment]
            quote_skew = max(quote_ages) - min(quote_ages)
            if quote_skew > max(0, int(max_cross_leg_skew_seconds)):
                rejected["cross_leg_quote_skew"] += 1
                continue

            effective_decimals = [quote["effectiveDecimalOdds"] for quote in assignment]
            inverse_sum = sum(1.0 / value for value in effective_decimals)
            if inverse_sum >= 1.0:
                rejected["not_arbitrage"] += 1
                continue
            theoretical_profit_percent = ((1.0 / inverse_sum) - 1.0) * 100.0
            if theoretical_profit_percent + 1e-9 < min_profit_percent:
                rejected["below_minimum_profit"] += 1
                continue

            try:
                stakes = equalized_stakes(total_stake, effective_decimals)
            except ValueError:
                rejected["invalid_stake"] += 1
                continue
            actual_total = round(sum(stakes), 2)
            payouts = [stakes[index] * effective_decimals[index] for index in range(len(stakes))]
            min_payout = min(payouts)
            guaranteed_profit = min_payout - actual_total
            actual_profit_percent = (guaranteed_profit / actual_total) * 100.0
            if guaranteed_profit <= 0 or actual_profit_percent + 1e-9 < min_profit_percent:
                rejected["rounding_removed_profit"] += 1
                continue

            execution = evaluate_execution_gates(
                assignment,
                stakes,
                require_distinct_books=require_distinct_books,
                quote_skew_seconds=quote_skew,
                max_quote_skew_seconds=max(0, int(max_cross_leg_skew_seconds)),
            )
            if execution["hardFailure"]:
                for reason in execution["failureReasons"]:
                    rejected[f"execution_{str(reason).lower()}"] += 1
                continue

            raw_inverse_sum = sum(1.0 / quote["decimalOdds"] for quote in assignment)
            outcome_rows = []
            all_quotes = []
            for index, selection in enumerate(ordered_selections):
                outcome = labels[selection]
                quote = assignment[index]
                raw_payout = stakes[index] * quote["decimalOdds"]
                row = {
                    **quote,
                    "selection": _selection_label(market_key, outcome),
                    "stake": round(stakes[index], 2),
                    "payout": round(payouts[index], 2),
                    "rawPayout": round(raw_payout, 2),
                    "profit": round(payouts[index] - actual_total, 2),
                }
                outcome_rows.append(row)
                selection_quotes = sorted(
                    quotes_by_selection[selection],
                    key=lambda item: item["effectiveDecimalOdds"],
                    reverse=True,
                )
                all_quotes.append(
                    {
                        "selection": row["selection"],
                        "quotes": selection_quotes,
                    }
                )

            away = str(event.get("away_team") or "")
            home = str(event.get("home_team") or "")
            title = (
                f"{away} vs {home}"
                if away and home
                else away or home or str(event.get("title") or event_id)
            )
            context = _market_context(group_key)
            digest = hashlib.sha256(
                json.dumps([event_id, market_key, group_key], default=str).encode()
            ).hexdigest()[:18]
            books_used = list(dict.fromkeys(row["bookKey"] for row in outcome_rows))
            warnings = []
            if commission_bps > 0 and any(
                row["bookKey"] in SPORTS_GAME_ODDS_EXCHANGE_BOOKS for row in outcome_rows
            ):
                warnings.append(
                    f"A {commission_bps / 100:.2f}% commission buffer is included on exchange winnings."
                )
            warnings.extend(execution["warnings"])
            opportunities.append(
                {
                    "id": f"arb::{digest}",
                    "eventId": event_id,
                    "sportKey": str(event.get("sport_key") or ""),
                    "league": str(event.get("sport_title") or event.get("sport_key") or ""),
                    "eventTitle": title,
                    "commenceTime": commence_time,
                    "marketKey": market_key,
                    "marketLabel": MARKET_LABELS.get(
                        market_key, market_key.replace("_", " ").title()
                    ),
                    "marketContext": context,
                    "outcomeCount": len(outcome_rows),
                    "bookCount": len(books_used),
                    "booksUsed": books_used,
                    "outcomes": outcome_rows,
                    "allQuotes": all_quotes,
                    "inverseProbabilitySum": round(inverse_sum, 8),
                    "impliedProbabilityPercent": round(inverse_sum * 100.0, 4),
                    "rawProfitPercent": round(((1.0 / raw_inverse_sum) - 1.0) * 100.0, 4),
                    "profitPercent": round(actual_profit_percent, 2),
                    "theoreticalProfitPercent": round(theoretical_profit_percent, 4),
                    "guaranteedProfit": round(guaranteed_profit, 2),
                    "totalStake": actual_total,
                    "minPayout": round(min_payout, 2),
                    "commissionBps": float(commission_bps),
                    "requireDistinctBooks": bool(require_distinct_books),
                    "crossLegQuoteSkewSeconds": round(quote_skew, 1),
                    "maxCrossLegQuoteSkewSeconds": max(
                        0, int(max_cross_leg_skew_seconds)
                    ),
                    "executionStatus": execution["status"],
                    "isExecutable": execution["isExecutable"],
                    "executionGates": execution["gates"],
                    "maximumExecutableTotalStake": execution[
                        "maximumExecutableTotalStake"
                    ],
                    "warnings": warnings,
                    "calculatedAt": now.isoformat(),
                    "calculationVersion": ARBITRAGE_CALCULATION_VERSION,
                }
            )

    opportunities.sort(
        key=lambda row: (row["profitPercent"], row["guaranteedProfit"]), reverse=True
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
            "calculationVersion": ARBITRAGE_CALCULATION_VERSION,
        },
    }
