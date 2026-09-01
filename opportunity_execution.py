"""Execution-integrity gates shared by opportunity scanners.

The mathematical edge and the ability to place every leg are different facts.
This module keeps them separate.  Unknown limits or settlement metadata never
become an "executable" claim, while explicit conflicts fail closed.
"""

from __future__ import annotations

import math
from typing import Iterable

from sports_game_odds import SPORTS_GAME_ODDS_EXCHANGE_BOOKS


def _nonnegative_number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return parsed


def _first_number(*values: object) -> float | None:
    for value in values:
        parsed = _nonnegative_number(value)
        if parsed is not None:
            return parsed
    return None


def _first_text(*values: object) -> str:
    for value in values:
        text = " ".join(str(value or "").split())
        if text:
            return text
    return ""


def quote_execution_metadata(
    *,
    book_key: str,
    book: dict,
    market: dict,
    outcome: dict,
) -> dict:
    """Return typed capacity, eligibility, and settlement fields for a quote."""

    market_limit = _first_number(
        outcome.get("bet_limit"),
        outcome.get("max_bet"),
        market.get("bet_limit"),
        market.get("max_bet"),
        book.get("bet_limit"),
        book.get("max_bet"),
    )
    top_price_liquidity = _first_number(
        outcome.get("liquidity"),
        outcome.get("top_price_liquidity"),
        market.get("liquidity"),
        market.get("top_price_liquidity"),
    )
    is_exchange = book_key in SPORTS_GAME_ODDS_EXCHANGE_BOOKS
    execution_capacity = top_price_liquidity if is_exchange else market_limit
    settlement_rule_key = _first_text(
        outcome.get("settlement_rule_key"),
        outcome.get("settlementRuleKey"),
        market.get("settlement_rule_key"),
        market.get("settlementRuleKey"),
        book.get("settlement_rule_key"),
        book.get("settlementRuleKey"),
    )
    eligibility = outcome.get("account_eligible")
    if eligibility is None:
        eligibility = market.get("account_eligible")
    if eligibility is None:
        eligibility = book.get("account_eligible")
    return {
        "marketLimit": market_limit,
        "topPriceLiquidity": top_price_liquidity,
        "executionCapacity": execution_capacity,
        "capacityType": "TOP_PRICE_LIQUIDITY" if is_exchange else "MARKET_LIMIT",
        "capacityKnown": execution_capacity is not None,
        "settlementRuleKey": settlement_rule_key or None,
        "settlementRuleKnown": bool(settlement_rule_key),
        "accountEligible": eligibility if isinstance(eligibility, bool) else None,
    }


def evaluate_execution_gates(
    legs: Iterable[dict],
    stakes: Iterable[float],
    *,
    require_distinct_books: bool,
    quote_skew_seconds: float,
    max_quote_skew_seconds: float,
) -> dict:
    """Classify an opportunity without overstating theoretical math as executable."""

    leg_rows = list(legs)
    stake_rows = [float(value) for value in stakes]
    books = [str(leg.get("bookKey") or "") for leg in leg_rows]
    capacities = [leg.get("executionCapacity") for leg in leg_rows]
    settlement_keys = [
        str(leg.get("settlementRuleKey") or "").strip() for leg in leg_rows
    ]
    known_settlement_keys = [value for value in settlement_keys if value]

    distinct_passed = not require_distinct_books or len(set(books)) == len(books)
    freshness_passed = quote_skew_seconds <= max_quote_skew_seconds + 1e-9
    eligibility_passed = all(leg.get("accountEligible") is not False for leg in leg_rows)
    capacity_sufficient = all(
        capacity is None or float(capacity) + 1e-9 >= stake
        for capacity, stake in zip(capacities, stake_rows)
    )
    settlement_compatible = len(set(known_settlement_keys)) <= 1
    capacity_verified = bool(leg_rows) and all(value is not None for value in capacities)
    settlement_verified = bool(leg_rows) and len(known_settlement_keys) == len(leg_rows)
    eligibility_verified = bool(leg_rows) and all(
        leg.get("accountEligible") is True for leg in leg_rows
    )

    hard_failures = []
    if not distinct_passed:
        hard_failures.append("SAME_BOOK_LEGS")
    if not freshness_passed:
        hard_failures.append("QUOTE_SKEW_EXCEEDED")
    if not eligibility_passed:
        hard_failures.append("ACCOUNT_INELIGIBLE")
    if not capacity_sufficient:
        hard_failures.append("INSUFFICIENT_CAPACITY")
    if not settlement_compatible:
        hard_failures.append("SETTLEMENT_MISMATCH")

    warnings = []
    if not capacity_verified:
        warnings.append("One or more legs do not report a verified limit or top-price liquidity.")
    if not settlement_verified:
        warnings.append("Provider settlement-rule identifiers are unavailable for one or more legs.")
    if not eligibility_verified:
        warnings.append("Account, state, and region eligibility has not been verified for every leg.")

    all_verified = (
        not hard_failures
        and capacity_verified
        and settlement_verified
        and eligibility_verified
        and distinct_passed
        and freshness_passed
    )
    maximum_total = None
    if capacity_verified and stake_rows and all(stake > 0 for stake in stake_rows):
        total = sum(stake_rows)
        maximum_total = total * min(
            float(capacity) / stake
            for capacity, stake in zip(capacities, stake_rows)
        )

    return {
        "status": "EXECUTABLE" if all_verified else "BLOCKED" if hard_failures else "THEORETICAL",
        "isExecutable": all_verified,
        "hardFailure": bool(hard_failures),
        "failureReasons": hard_failures,
        "warnings": warnings,
        "maximumExecutableTotalStake": (
            round(maximum_total, 2) if maximum_total is not None else None
        ),
        "gates": {
            "distinctBooks": {"passed": distinct_passed, "verified": True},
            "quoteSkew": {
                "passed": freshness_passed,
                "verified": True,
                "actualSeconds": round(float(quote_skew_seconds), 3),
                "maximumSeconds": round(float(max_quote_skew_seconds), 3),
            },
            "capacity": {
                "passed": capacity_sufficient,
                "verified": capacity_verified,
            },
            "settlement": {
                "passed": settlement_compatible,
                "verified": settlement_verified,
            },
            "eligibility": {
                "passed": eligibility_passed,
                "verified": eligibility_verified,
            },
        },
    }
