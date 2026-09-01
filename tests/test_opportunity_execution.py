from __future__ import annotations

from opportunity_execution import (
    evaluate_execution_gates,
    quote_execution_metadata,
)


def test_exchange_liquidity_and_sportsbook_limit_remain_distinct() -> None:
    exchange = quote_execution_metadata(
        book_key="novig",
        book={},
        market={},
        outcome={"liquidity": 80, "bet_limit": 900},
    )
    sportsbook = quote_execution_metadata(
        book_key="fanduel",
        book={},
        market={},
        outcome={"liquidity": 80, "bet_limit": 900},
    )

    assert exchange["executionCapacity"] == 80
    assert exchange["capacityType"] == "TOP_PRICE_LIQUIDITY"
    assert sportsbook["executionCapacity"] == 900
    assert sportsbook["capacityType"] == "MARKET_LIMIT"


def test_known_capacity_shortfall_and_settlement_conflict_fail_closed() -> None:
    result = evaluate_execution_gates(
        [
            {
                "bookKey": "fanduel",
                "executionCapacity": 10,
                "settlementRuleKey": "rule-a",
                "accountEligible": True,
            },
            {
                "bookKey": "draftkings",
                "executionCapacity": 100,
                "settlementRuleKey": "rule-b",
                "accountEligible": True,
            },
        ],
        [50, 50],
        require_distinct_books=True,
        quote_skew_seconds=0,
        max_quote_skew_seconds=10,
    )

    assert result["status"] == "BLOCKED"
    assert result["failureReasons"] == [
        "INSUFFICIENT_CAPACITY",
        "SETTLEMENT_MISMATCH",
    ]


def test_unknown_capacity_is_theoretical_never_executable() -> None:
    result = evaluate_execution_gates(
        [
            {"bookKey": "fanduel", "executionCapacity": None},
            {"bookKey": "draftkings", "executionCapacity": None},
        ],
        [50, 50],
        require_distinct_books=True,
        quote_skew_seconds=0,
        max_quote_skew_seconds=10,
    )

    assert result["status"] == "THEORETICAL"
    assert result["isExecutable"] is False
    assert result["gates"]["capacity"]["verified"] is False
