"""Deterministic low-hold and middle-opportunity calculations.

The scanner compares independently executable sportsbook prices.  It does not
estimate a fair probability: hold is the sum of the displayed implied
probabilities minus 100 percent.  Stakes are rounded to cents and rebalanced to
maximize the smallest after-fee payout.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Iterable

from arbitrage import (
    MARKET_LABELS,
    _best_assignment,
    _book_logo,
    _market_context,
    _market_group_key,
    _parse_time,
    _quote_age_seconds,
    _selection_key,
    _selection_label,
    _valid_american,
    effective_decimal_odds,
    equalized_stakes,
)
from ev_optimizer import american_to_decimal
from opportunity_execution import evaluate_execution_gates, quote_execution_metadata
from sports_game_odds import (
    SPORTS_GAME_ODDS_BOOKMAKERS,
    SPORTS_GAME_ODDS_DEFAULT_EXECUTION_BOOKS,
    SPORTS_GAME_ODDS_DFS_BOOKS,
    SPORTS_GAME_ODDS_EXCHANGE_BOOKS,
)


LOW_HOLD_CALCULATION_VERSION = "iconlabs-low-hold-v5-required-book"
MIDDLE_MARKETS = {"totals", "alternate_totals"}


def _is_middle_market(market_key: str) -> bool:
    return market_key in MIDDLE_MARKETS or market_key.startswith(
        ("batter_", "pitcher_", "player_")
    )


def _event_title(event: dict) -> str:
    away = " ".join(str(event.get("away_team") or "").split())
    home = " ".join(str(event.get("home_team") or "").split())
    if away and home:
        return f"{away} vs {home}"
    return away or home or str(event.get("title") or event.get("id") or "Event")


def _american_in_range(value: object, low: int, high: int) -> bool:
    if not _valid_american(value):
        return False
    number = int(round(float(value)))
    return low <= number <= high


def _quote(
    *,
    book_key: str,
    book: dict,
    market: dict,
    outcome: dict,
    market_key: str,
    age: float | None,
    commission_bps: float,
) -> dict:
    american = int(round(float(outcome["price"])))
    decimal = american_to_decimal(american)
    applied_commission = (
        commission_bps if book_key in SPORTS_GAME_ODDS_EXCHANGE_BOOKS else 0.0
    )
    effective_decimal = effective_decimal_odds(
        american, commission_bps=applied_commission
    )
    player_team = ""
    for key in ("team", "team_name", "teamName", "player_team", "playerTeam"):
        value = outcome.get(key)
        if isinstance(value, dict):
            names = value.get("names") or {}
            value = (
                names.get("long") if isinstance(names, dict) else None
            ) or value.get("name") or value.get("teamID") or value.get("id")
        player_team = " ".join(str(value or "").split())
        if player_team:
            break
    return {
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
        "selection": _selection_label(market_key, outcome),
        "selectionName": str(outcome.get("name") or "").strip(),
        "description": str(outcome.get("description") or "").strip(),
        "playerTeam": player_team,
        **quote_execution_metadata(
            book_key=book_key,
            book=book,
            market=market,
            outcome=outcome,
        ),
    }


def _pair_assignment(
    left: list[dict],
    right: list[dict],
    *,
    require_distinct_books: bool,
    required_book: str = "",
) -> list[dict] | None:
    """Choose the two quotes with the smallest combined implied probability."""

    if not left or not right:
        return None
    best: tuple[tuple[float, float], list[dict]] | None = None
    for first in left:
        for second in right:
            if require_distinct_books and first["bookKey"] == second["bookKey"]:
                continue
            if required_book and required_book not in {
                first["bookKey"],
                second["bookKey"],
            }:
                continue
            implied = (
                1.0 / first["effectiveDecimalOdds"]
                + 1.0 / second["effectiveDecimalOdds"]
            )
            freshness = max(
                first.get("quoteAgeSeconds") or 0,
                second.get("quoteAgeSeconds") or 0,
            )
            rank = (implied, freshness)
            if best is None or rank < best[0]:
                best = (rank, [first, second])
    return best[1] if best else None


def _best_assignment_with_required_book(
    quote_groups: list[list[dict]],
    *,
    require_distinct_books: bool,
    required_book: str = "",
) -> list[dict] | None:
    """Return the lowest-hold assignment that includes the requested book."""

    if not required_book:
        return _best_assignment(
            quote_groups,
            require_distinct_books=require_distinct_books,
        )

    best: tuple[tuple[float, float], list[dict]] | None = None
    for group_index, quotes in enumerate(quote_groups):
        for required_quote in quotes:
            if required_quote.get("bookKey") != required_book:
                continue
            constrained_groups = [list(group) for group in quote_groups]
            constrained_groups[group_index] = [required_quote]
            assignment = _best_assignment(
                constrained_groups,
                require_distinct_books=require_distinct_books,
            )
            if assignment is None or not any(
                quote.get("bookKey") == required_book for quote in assignment
            ):
                continue
            implied = sum(
                1.0 / float(quote["effectiveDecimalOdds"])
                for quote in assignment
            )
            freshness = max(
                float(quote.get("quoteAgeSeconds") or 0)
                for quote in assignment
            )
            rank = (implied, freshness)
            if best is None or rank < best[0]:
                best = (rank, assignment)
    return best[1] if best else None


def _locked_leg_stakes(
    locked_stake: float,
    decimals: list[float],
    locked_index: int,
) -> tuple[list[float], int]:
    """Lock one stake and round every hedge to the closest equal payout."""

    if not decimals or any(value <= 1.0 or not math.isfinite(value) for value in decimals):
        raise ValueError("Decimal odds must be finite and greater than one.")
    if not math.isfinite(locked_stake) or locked_stake <= 0:
        raise ValueError("Locked stake must be positive.")

    index = min(max(int(locked_index), 0), len(decimals) - 1)
    stakes = [0.0] * len(decimals)
    stakes[index] = round(locked_stake, 2)
    target_payout = stakes[index] * decimals[index]
    for outcome_index, decimal in enumerate(decimals):
        if outcome_index == index:
            continue
        raw_cents = target_payout / decimal * 100.0
        candidates = {
            max(1, math.floor(raw_cents)),
            max(1, math.ceil(raw_cents)),
        }
        best_cents = min(
            candidates,
            key=lambda cents: (abs((cents / 100.0) * decimal - target_payout), cents),
        )
        stakes[outcome_index] = best_cents / 100.0
    return stakes, index


def _middle_scenario(
    low_point: float,
    high_point: float,
    stakes: list[float],
    decimals: list[float],
) -> dict | None:
    """Return the best attainable integer-score outcome inside the middle."""

    if high_point <= low_point:
        return None
    candidates = range(math.ceil(low_point), math.floor(high_point) + 1)
    total_stake = round(sum(stakes), 2)
    scenarios = []
    for result in candidates:
        over_state = "win" if result > low_point else "push" if result == low_point else "loss"
        under_state = "win" if result < high_point else "push" if result == high_point else "loss"
        returns = 0.0
        for index, state in enumerate((over_state, under_state)):
            if state == "win":
                returns += stakes[index] * decimals[index]
            elif state == "push":
                returns += stakes[index]
        states = {over_state, under_state}
        if over_state == under_state == "win":
            label = "Both bets win"
        elif "push" in states and "win" in states:
            label = "One wins, one pushes"
        else:
            label = "Middle result"
        scenarios.append(
            {
                "result": result,
                "label": label,
                "overState": over_state,
                "underState": under_state,
                "profit": round(returns - total_stake, 2),
                "returnPercent": round(((returns - total_stake) / total_stake) * 100.0, 2),
            }
        )
    return max(scenarios, key=lambda row: row["profit"]) if scenarios else None


def _build_row(
    *,
    event: dict,
    market_key: str,
    context: object,
    pair_kind: str,
    assignment: list[dict],
    quote_groups: list[list[dict]],
    total_stake: float,
    max_hold_percent: float,
    commission_bps: float,
    require_distinct_books: bool,
    now: datetime,
    stake_mode: str = "total",
    locked_outcome_index: int = 0,
    line_distance: float = 0.0,
    middle_scenario: dict | None = None,
) -> dict | None:
    effective_decimals = [row["effectiveDecimalOdds"] for row in assignment]
    inverse_sum = sum(1.0 / value for value in effective_decimals)
    hold_percent = (inverse_sum - 1.0) * 100.0
    # Any negative hold guarantees a positive outside return, including when
    # the lines also create a middle. Those opportunities belong off this board.
    if hold_percent < 0:
        return None
    if hold_percent > max_hold_percent + 1e-9:
        return None

    normalized_stake_mode = "first-leg" if stake_mode == "first-leg" else "total"
    locked_index = 0
    try:
        if normalized_stake_mode == "first-leg":
            stakes, locked_index = _locked_leg_stakes(
                total_stake,
                effective_decimals,
                locked_outcome_index,
            )
        else:
            stakes = equalized_stakes(total_stake, effective_decimals)
    except ValueError:
        return None
    actual_total = round(sum(stakes), 2)
    payouts = [stakes[index] * effective_decimals[index] for index in range(len(stakes))]
    outside_profits = [payout - actual_total for payout in payouts]
    min_payout = min(payouts)
    min_profit = min(outside_profits)
    raw_inverse_sum = sum(1.0 / row["decimalOdds"] for row in assignment)

    outcomes = []
    for index, selected in enumerate(assignment):
        outcomes.append(
            {
                **selected,
                "stake": round(stakes[index], 2),
                "payout": round(payouts[index], 2),
                "profit": round(outside_profits[index], 2),
            }
        )
    all_quotes = []
    for index, quotes in enumerate(quote_groups):
        all_quotes.append(
            {
                "selection": assignment[index]["selection"],
                "quotes": sorted(
                    quotes,
                    key=lambda item: item["effectiveDecimalOdds"],
                    reverse=True,
                ),
            }
        )

    scenario = middle_scenario
    if pair_kind == "middle" and scenario is None:
        points = [float(row["point"]) for row in assignment]
        scenario = _middle_scenario(
            points[0], points[1], stakes, effective_decimals
        )

    event_id = str(event.get("id") or "").strip()
    digest = hashlib.sha256(
        json.dumps(
            [
                event_id,
                market_key,
                context,
                pair_kind,
                [(row["selection"], row["bookKey"]) for row in assignment],
            ],
            default=str,
        ).encode()
    ).hexdigest()[:18]
    books_used = list(dict.fromkeys(row["bookKey"] for row in outcomes))
    warnings = []
    if commission_bps > 0 and any(
        row["bookKey"] in SPORTS_GAME_ODDS_EXCHANGE_BOOKS for row in outcomes
    ):
        warnings.append(
            f"A {commission_bps / 100:.2f}% commission buffer is included on exchange winnings."
        )
    if pair_kind == "middle":
        warnings.append(
            "Middle profit depends on the final result landing inside the displayed line window."
        )

    return {
        "id": f"low-hold::{digest}",
        "eventId": event_id,
        "sportKey": str(event.get("sport_key") or ""),
        "league": str(event.get("sport_title") or event.get("sport_key") or ""),
        "eventTitle": _event_title(event),
        "awayTeam": " ".join(str(event.get("away_team") or "").split()),
        "homeTeam": " ".join(str(event.get("home_team") or "").split()),
        "commenceTime": str(event.get("commence_time") or ""),
        "marketKey": market_key,
        "marketLabel": MARKET_LABELS.get(
            market_key, market_key.replace("_", " ").title()
        ),
        "marketContext": context,
        "pairKind": pair_kind,
        "lineDistance": round(line_distance, 3),
        "outcomeCount": len(outcomes),
        "bookCount": len(books_used),
        "booksUsed": books_used,
        "outcomes": outcomes,
        "allQuotes": all_quotes,
        "inverseProbabilitySum": round(inverse_sum, 8),
        "impliedProbabilityPercent": round(inverse_sum * 100.0, 4),
        "holdPercent": round(hold_percent, 4),
        "rawHoldPercent": round((raw_inverse_sum - 1.0) * 100.0, 4),
        "retainedPercent": round((min_payout / actual_total) * 100.0, 2),
        "outsideReturnPercent": round((min_profit / actual_total) * 100.0, 2),
        "outsideNet": round(min_profit, 2),
        "holdCost": round(max(0.0, -min_profit), 2),
        "guaranteedProfit": round(max(0.0, min_profit), 2),
        "bestOutsideProfit": round(max(outside_profits), 2),
        "totalStake": actual_total,
        "stakeMode": normalized_stake_mode,
        "stakeInputAmount": round(float(total_stake), 2),
        "lockedOutcomeIndex": locked_index if normalized_stake_mode == "first-leg" else None,
        "lockedStake": (
            round(stakes[locked_index], 2)
            if normalized_stake_mode == "first-leg"
            else None
        ),
        "minPayout": round(min_payout, 2),
        "middleScenario": scenario,
        "middleProfit": scenario["profit"] if scenario else None,
        "middleReturnPercent": scenario["returnPercent"] if scenario else None,
        "commissionBps": float(commission_bps),
        "requireDistinctBooks": bool(require_distinct_books),
        "warnings": warnings,
        "calculatedAt": now.isoformat(),
        "calculationVersion": LOW_HOLD_CALCULATION_VERSION,
    }


def build_low_hold_board(
    events: Iterable[dict],
    *,
    selected_books: Iterable[str] = SPORTS_GAME_ODDS_DEFAULT_EXECUTION_BOOKS,
    allowed_markets: Iterable[str] = (),
    total_stake: float = 1_000.0,
    max_hold_percent: float = 5.0,
    min_american_odds: int = -5_000,
    max_american_odds: int = 5_000,
    max_quote_age_seconds: int = 90,
    max_cross_leg_skew_seconds: int = 3,
    commission_bps: float = 0.0,
    require_distinct_books: bool = True,
    include_exact: bool = True,
    include_middles: bool = True,
    stake_mode: str = "total",
    locked_outcome_index: int = 0,
    required_book: str = "",
    now: datetime | None = None,
) -> dict:
    """Build a ranked feed of exact-line low holds and total/prop middles."""

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
    low_odds = min(min_american_odds, max_american_odds)
    high_odds = max(min_american_odds, max_american_odds)
    rejected: Counter[str] = Counter()
    opportunities: list[dict] = []
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

        exact_groups: dict[tuple[str, tuple], dict[str, dict]] = defaultdict(dict)
        middle_groups: dict[tuple[str, str], dict[str, dict[float, list[dict]]]] = defaultdict(
            lambda: {"over": defaultdict(list), "under": defaultdict(list)}
        )

        for book in event.get("bookmakers") or []:
            if not isinstance(book, dict):
                continue
            book_key = str(book.get("key") or "").strip().lower()
            if book_key not in requested_books:
                continue
            for market in book.get("markets") or []:
                if not isinstance(market, dict):
                    continue
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

                outcomes_by_group: dict[tuple, dict[tuple, dict]] = defaultdict(dict)
                for outcome in market.get("outcomes") or []:
                    if not isinstance(outcome, dict) or not _american_in_range(
                        outcome.get("price"), low_odds, high_odds
                    ):
                        continue
                    group_key = _market_group_key(market_key, outcome)
                    outcomes_by_group[group_key][_selection_key(outcome)] = outcome
                    if _is_middle_market(market_key):
                        direction = str(outcome.get("name") or "").strip().lower()
                        try:
                            point = float(outcome.get("point"))
                        except (TypeError, ValueError):
                            point = math.nan
                        if direction in {"over", "under"} and math.isfinite(point):
                            description = str(outcome.get("description") or "").strip().casefold()
                            middle_groups[(market_key, description)][direction][point].append(
                                _quote(
                                    book_key=book_key,
                                    book=book,
                                    market=market,
                                    outcome=outcome,
                                    market_key=market_key,
                                    age=age,
                                    commission_bps=commission_bps,
                                )
                            )
                for group_key, outcomes in outcomes_by_group.items():
                    if not outcomes:
                        continue
                    existing = exact_groups[(market_key, group_key)].get(book_key)
                    candidate = {
                        "book": book,
                        "market": market,
                        "outcomes": outcomes,
                        "age": age,
                    }
                    if existing is None or len(outcomes) > len(existing["outcomes"]):
                        exact_groups[(market_key, group_key)][book_key] = candidate

        if include_exact:
            for (market_key, group_key), book_markets in exact_groups.items():
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
                    key=lambda item: (
                        signatures[item],
                        len(item),
                        sorted(map(str, item)),
                    ),
                )
                labels: dict[tuple, dict] = {}
                quotes_by_selection: dict[tuple, list[dict]] = defaultdict(list)
                for book_key, payload in book_markets.items():
                    if frozenset(payload["outcomes"].keys()) != signature:
                        continue
                    for selection, outcome in payload["outcomes"].items():
                        labels[selection] = outcome
                        quotes_by_selection[selection].append(
                            _quote(
                                book_key=book_key,
                                book=payload["book"],
                                market=payload["market"],
                                outcome=outcome,
                                market_key=market_key,
                                age=payload["age"],
                                commission_bps=commission_bps,
                            )
                        )
                ordered = sorted(
                    signature, key=lambda value: tuple(str(part) for part in value)
                )
                quote_groups = [quotes_by_selection.get(selection, []) for selection in ordered]
                assignment = _best_assignment_with_required_book(
                    quote_groups,
                    require_distinct_books=require_distinct_books,
                    required_book=required_book_key,
                )
                if assignment is None:
                    rejected["no_valid_book_assignment"] += 1
                    continue
                quote_skew = max(
                    float(item["quoteAgeSeconds"]) for item in assignment
                ) - min(float(item["quoteAgeSeconds"]) for item in assignment)
                if quote_skew > max(0, int(max_cross_leg_skew_seconds)):
                    rejected["cross_leg_quote_skew"] += 1
                    continue
                for index, selection in enumerate(ordered):
                    assignment[index]["selection"] = _selection_label(
                        market_key, labels[selection]
                    )
                row = _build_row(
                    event=event,
                    market_key=market_key,
                    context=_market_context(group_key),
                    pair_kind="exact",
                    assignment=assignment,
                    quote_groups=quote_groups,
                    total_stake=total_stake,
                    max_hold_percent=max_hold_percent,
                    commission_bps=commission_bps,
                    require_distinct_books=require_distinct_books,
                    now=now,
                    stake_mode=stake_mode,
                    locked_outcome_index=locked_outcome_index,
                )
                if row is None:
                    rejected["routed_to_arbitrage_or_above_maximum_hold"] += 1
                else:
                    row["crossLegQuoteSkewSeconds"] = round(quote_skew, 1)
                    row["maxCrossLegQuoteSkewSeconds"] = max(
                        0, int(max_cross_leg_skew_seconds)
                    )
                    execution = evaluate_execution_gates(
                        row["outcomes"],
                        [float(outcome["stake"]) for outcome in row["outcomes"]],
                        require_distinct_books=require_distinct_books,
                        quote_skew_seconds=quote_skew,
                        max_quote_skew_seconds=max(
                            0, int(max_cross_leg_skew_seconds)
                        ),
                    )
                    if execution["hardFailure"]:
                        for reason in execution["failureReasons"]:
                            rejected[f"execution_{str(reason).lower()}"] += 1
                    else:
                        row["executionStatus"] = execution["status"]
                        row["isExecutable"] = execution["isExecutable"]
                        row["executionGates"] = execution["gates"]
                        row["maximumExecutableTotalStake"] = execution[
                            "maximumExecutableTotalStake"
                        ]
                        row["warnings"].extend(execution["warnings"])
                        opportunities.append(row)

        if include_middles:
            for (market_key, description), directions in middle_groups.items():
                for low_point, over_quotes in directions["over"].items():
                    for high_point, under_quotes in directions["under"].items():
                        distance = high_point - low_point
                        if distance + 1e-9 < 0.5:
                            continue
                        market_count += 1
                        assignment = _pair_assignment(
                            over_quotes,
                            under_quotes,
                            require_distinct_books=require_distinct_books,
                            required_book=required_book_key,
                        )
                        if assignment is None:
                            rejected["no_valid_book_assignment"] += 1
                            continue
                        quote_skew = abs(
                            float(assignment[0]["quoteAgeSeconds"])
                            - float(assignment[1]["quoteAgeSeconds"])
                        )
                        if quote_skew > max(0, int(max_cross_leg_skew_seconds)):
                            rejected["cross_leg_quote_skew"] += 1
                            continue
                        context_parts = []
                        if description:
                            context_parts.append(assignment[0]["description"])
                        context_parts.append(f"{low_point:g}–{high_point:g}")
                        row = _build_row(
                            event=event,
                            market_key=market_key,
                            context=" · ".join(context_parts),
                            pair_kind="middle",
                            assignment=assignment,
                            quote_groups=[over_quotes, under_quotes],
                            total_stake=total_stake,
                            max_hold_percent=max_hold_percent,
                            commission_bps=commission_bps,
                            require_distinct_books=require_distinct_books,
                            now=now,
                            stake_mode=stake_mode,
                            locked_outcome_index=locked_outcome_index,
                            line_distance=distance,
                        )
                        if row is None:
                            rejected["routed_to_arbitrage_or_above_maximum_hold"] += 1
                        else:
                            row["crossLegQuoteSkewSeconds"] = round(quote_skew, 1)
                            row["maxCrossLegQuoteSkewSeconds"] = max(
                                0, int(max_cross_leg_skew_seconds)
                            )
                            execution = evaluate_execution_gates(
                                row["outcomes"],
                                [
                                    float(outcome["stake"])
                                    for outcome in row["outcomes"]
                                ],
                                require_distinct_books=require_distinct_books,
                                quote_skew_seconds=quote_skew,
                                max_quote_skew_seconds=max(
                                    0, int(max_cross_leg_skew_seconds)
                                ),
                            )
                            if execution["hardFailure"]:
                                for reason in execution["failureReasons"]:
                                    rejected[f"execution_{str(reason).lower()}"] += 1
                            else:
                                row["executionStatus"] = execution["status"]
                                row["isExecutable"] = execution["isExecutable"]
                                row["executionGates"] = execution["gates"]
                                row["maximumExecutableTotalStake"] = execution[
                                    "maximumExecutableTotalStake"
                                ]
                                row["warnings"].extend(execution["warnings"])
                                opportunities.append(row)

    opportunities.sort(
        key=lambda row: (
            row["holdPercent"],
            -(row.get("middleProfit") or row.get("guaranteedProfit") or 0.0),
            row["commenceTime"],
        )
    )
    return {
        "data": opportunities,
        "diagnostics": {
            "eventsScanned": event_count,
            "marketsCompared": market_count,
            "qualified": len(opportunities),
            "exactQualified": sum(row["pairKind"] == "exact" for row in opportunities),
            "middleQualified": sum(row["pairKind"] == "middle" for row in opportunities),
            "rejected": sum(rejected.values()),
            "rejectionReasons": dict(sorted(rejected.items())),
            "selectedBookCount": len(requested_books),
            "requiredBook": required_book_key or None,
            "calculationVersion": LOW_HOLD_CALCULATION_VERSION,
        },
    }
