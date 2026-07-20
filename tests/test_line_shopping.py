from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from execution_providers import (
    ExecutionOption,
    ExecutionProvider,
    ExecutionProviderRegistry,
    MatchConfidence,
    _finalize_execution_option,
    american_to_probability,
)
from kalshi_provider import _effective_price as kalshi_effective_price
from line_shop_foundation import LINE_SHOP_MIGRATION_VERSION


NOW = datetime.now(timezone.utc)


def trade() -> dict:
    return {
        "id": "trade-1",
        "outcome": "Philadelphia Phillies",
        "recommendationSnapshotId": "recommendation-1",
        "recommendation": {"recommended_amount": 100.0, "kelly_fraction": 0.0125},
        "card": {"recommended_amount": 100.0},
    }


def option(
    provider: str,
    price: float,
    *,
    american: int | None = None,
    effective: float | None = None,
    age: int = 0,
    liquidity: float = 1000.0,
    fillable: bool = True,
    status: str = "OPEN",
    fee_rate: float | None = None,
) -> ExecutionOption:
    return ExecutionOption(
        provider_name={"polymarket": "Polymarket", "kalshi": "Kalshi", "fourcx": "4CX"}[provider],
        provider_key=provider,
        market_id=f"{provider}-market",
        selection_id=f"{provider}-outcome",
        display_odds="pending",
        deep_link=f"https://example.com/{provider}/exact-market",
        is_available=True,
        last_updated=(NOW - timedelta(seconds=age)).isoformat(),
        matching_confidence=MatchConfidence.EXACT,
        logo_url=f"/{provider}.png",
        tooltip="Executable quote",
        american_odds=american,
        contract_price=price,
        effective_price=effective if effective is not None else price,
        available_liquidity=liquidity,
        can_fill_recommended_stake=fillable,
        fee_rate=fee_rate,
        quote_status=status,
    )


class Provider(ExecutionProvider):
    def __init__(self, value: ExecutionOption | Exception):
        self.value = value
        self.provider_key = value.provider_key if isinstance(value, ExecutionOption) else "broken"
        self.provider_name = self.provider_key

    def options_for_trades(self, trades):
        if isinstance(self.value, Exception):
            raise self.value
        return {trades[0]["id"]: self.value}


def finalized(value: ExecutionOption, **kwargs) -> ExecutionOption:
    return _finalize_execution_option(
        value,
        trade(),
        max_quote_age_seconds=kwargs.pop("max_quote_age_seconds", 60),
        min_liquidity=kwargs.pop("min_liquidity", 0),
        include_fees=kwargs.pop("include_fees", True),
        now=NOW,
    )


def test_native_formats_and_normalized_prices_are_preserved():
    polymarket = finalized(option("polymarket", 0.49))
    kalshi = finalized(option("kalshi", 0.47))
    fourcx = finalized(option("fourcx", 0.50, american=100))

    assert (polymarket.display_odds, polymarket.native_price_format) == ("49\u00a2", "CENTS")
    assert (kalshi.display_odds, kalshi.native_price_format) == ("47\u00a2", "CENTS")
    assert (fourcx.display_odds, fourcx.native_price_format) == ("+100", "AMERICAN")
    assert kalshi.implied_probability == pytest.approx(0.47)
    assert kalshi.decimal_odds == pytest.approx(1 / 0.47)
    assert american_to_probability(120) == pytest.approx(100 / 220)
    assert american_to_probability(-110) == pytest.approx(110 / 210)


def test_lowest_same_selection_executable_price_wins_for_cents_and_american_odds():
    value = trade()
    registry = ExecutionProviderRegistry((
        Provider(option("polymarket", 0.49)),
        Provider(option("kalshi", 0.47)),
        Provider(option("fourcx", american_to_probability(100), american=100)),
    ))
    registry.attach_options([value])

    best = next(row for row in value["executionOptions"] if row["isBestPrice"])
    assert best["providerKey"] == "kalshi"
    assert best["nativePrice"] == "47\u00a2"


def test_positive_and_negative_american_odds_rank_in_probability_order():
    value = trade()
    registry = ExecutionProviderRegistry((
        Provider(option("fourcx", american_to_probability(120), american=120)),
        Provider(ExecutionOption(**{**option("fourcx", american_to_probability(-110), american=-110).__dict__, "provider_key": "polymarket", "provider_name": "Polymarket"})),
    ), comparison_provider_keys=("fourcx", "polymarket"))
    registry.attach_options([value])
    best = next(row for row in value["executionOptions"] if row["isBestPrice"])
    assert best["americanOdds"] == 120


@pytest.mark.parametrize("status", ["SUSPENDED", "MARKET_SUSPENDED"])
def test_suspended_market_cannot_be_best(status):
    value = trade()
    registry = ExecutionProviderRegistry((
        Provider(option("kalshi", 0.40, status=status)),
        Provider(option("polymarket", 0.49)),
    ))
    registry.attach_options([value])
    best = next(row for row in value["executionOptions"] if row["isBestPrice"])
    assert best["providerKey"] == "polymarket"
    suspended = next(row for row in value["executionOptions"] if row["providerKey"] == "kalshi")
    assert suspended["failureReason"] == "MARKET_SUSPENDED"


def test_stale_and_insufficient_quotes_cannot_be_best():
    value = trade()
    registry = ExecutionProviderRegistry((
        Provider(option("kalshi", 0.40, age=61)),
        Provider(option("fourcx", 0.45, american=122, liquidity=20, fillable=False)),
        Provider(option("polymarket", 0.49)),
    ), max_quote_age_seconds=60)
    registry.attach_options([value])
    best = next(row for row in value["executionOptions"] if row["isBestPrice"])
    assert best["providerKey"] == "polymarket"
    failures = {row["providerKey"]: row["failureReason"] for row in value["executionOptions"]}
    assert failures["kalshi"] == "STALE_QUOTE"
    assert failures["fourcx"] == "INSUFFICIENT_LIQUIDITY"


def test_zero_stake_odds_screen_quote_remains_executable_when_liquidity_exists():
    value = trade()
    value["recommendation"]["recommended_amount"] = 0
    value["card"]["recommended_amount"] = 0
    source = option("polymarket", 0.49)
    source = ExecutionOption(**{**source.__dict__, "can_fill_recommended_stake": None})
    result = _finalize_execution_option(
        source, value, max_quote_age_seconds=60, min_liquidity=0,
        include_fees=True, now=NOW,
    )
    assert result.is_available is True
    assert result.can_fill_recommended_stake is True


def test_depth_weighted_effective_price_and_fees_drive_ranking():
    effective, liquidity, fillable = kalshi_effective_price([(0.47, 100), (0.50, 106)], 100)
    assert effective == pytest.approx(100 / 206)
    assert liquidity == pytest.approx(100)
    assert fillable is True

    value = trade()
    registry = ExecutionProviderRegistry((
        Provider(option("kalshi", 0.47, effective=0.47, fee_rate=0.10)),
        Provider(option("polymarket", 0.49)),
    ), include_fees=True)
    registry.attach_options([value])
    best = next(row for row in value["executionOptions"] if row["isBestPrice"])
    assert best["providerKey"] == "polymarket"
    kalshi = next(row for row in value["executionOptions"] if row["providerKey"] == "kalshi")
    assert kalshi["estimatedFees"] == pytest.approx(10.0)
    assert kalshi["bestExecutablePrice"] == pytest.approx(0.517)


def test_provider_failure_is_isolated_and_no_order_method_is_called():
    value = trade()
    working = Provider(option("polymarket", 0.49))
    broken = Provider(RuntimeError("outage"))
    registry = ExecutionProviderRegistry((broken, working))
    registry.attach_options([value])
    assert [row["providerKey"] for row in value["executionOptions"]] == ["polymarket"]
    assert value["lineShopFailures"]["broken"] == "PROVIDER_UNAVAILABLE"
    assert value["executionOptions"][0]["directMarketUrl"].endswith("/polymarket/exact-market")


def test_line_shop_does_not_mutate_recommendation_or_kelly_values():
    value = trade()
    frozen = deepcopy(value["recommendation"])
    ExecutionProviderRegistry((Provider(option("polymarket", 0.49)),)).attach_options([value])
    assert value["recommendation"] == frozen


def test_first_display_snapshot_is_immutable_and_quote_history_is_separate(db):
    with db.connection() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        migration = conn.execute(
            "SELECT version FROM schema_migrations WHERE version = ?", (LINE_SHOP_MIGRATION_VERSION,)
        ).fetchone()
    assert {"line_shop_initial_snapshots", "line_shop_quote_observations"} <= tables
    assert migration[0] == LINE_SHOP_MIGRATION_VERSION

    value = trade()
    ExecutionProviderRegistry((Provider(option("polymarket", 0.49)),)).attach_options([value])
    db.record_line_shop_quotes("user-1", [value])
    first = db.get_line_shop_snapshot("user-1", "recommendation-1")

    ExecutionProviderRegistry((Provider(option("polymarket", 0.45)),)).attach_options([value])
    db.record_line_shop_quotes("user-1", [value])
    unchanged = db.get_line_shop_snapshot("user-1", "recommendation-1")
    with db.connection() as conn:
        history_count = conn.execute("SELECT COUNT(*) FROM line_shop_quote_observations").fetchone()[0]

    assert first["best_executable_price"] == pytest.approx(0.49)
    assert unchanged["best_executable_price"] == pytest.approx(0.49)
    assert history_count == 2
