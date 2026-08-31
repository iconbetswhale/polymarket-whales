from datetime import datetime, timedelta, timezone

import pytest

from dfs_probability_engine import (
    DfsProbabilityEngine,
    ICONLABS_DFS_WEIGHTS,
    american_to_probability,
    devig_two_way,
    probability_to_american,
)


NOW = datetime(2026, 8, 24, 16, 0, tzinfo=timezone.utc)


def test_iconlabs_default_weights_are_ranked_and_total_one_hundred():
    assert list(ICONLABS_DFS_WEIGHTS) == [
        "fanduel", "novig", "prophetx", "draftkings",
        "pinnacle", "circa", "kalshi", "polymarket",
    ]
    assert sum(ICONLABS_DFS_WEIGHTS.values()) == 100


def quote(provider, over, under, *, line=6.5, age=0, liquidity=None):
    payload = {
        "provider": provider,
        "line": line,
        "over_odds": over,
        "under_odds": under,
        "quote_timestamp": (NOW - timedelta(seconds=age)).isoformat(),
    }
    if liquidity is not None:
        payload["over_liquidity"] = liquidity
        payload["under_liquidity"] = liquidity
    return payload


def test_american_probability_round_trip():
    assert american_to_probability(-119) == pytest.approx(119 / 219)
    assert american_to_probability(120) == pytest.approx(100 / 220)
    assert probability_to_american(119 / 219) == pytest.approx(-119)


@pytest.mark.parametrize("method", ["multiplicative", "additive", "power", "shin"])
def test_devig_methods_return_a_valid_two_way_market(method):
    over, under = devig_two_way(-130, 110, method)
    assert over + under == pytest.approx(1)
    assert 0 < under < over < 1


def test_weighted_consensus_returns_hit_rate_fair_odds_and_edge():
    engine = DfsProbabilityEngine(
        {"fanduel": 60, "pinnacle": 40},
        devig_method="multiplicative",
        freshness_half_life_seconds=3600,
        minimum_sources=2,
    )
    result = engine.calculate(
        target_line=6.5,
        side="Over",
        quotes=[quote("fanduel", -130, 110), quote("pinnacle", -120, 100)],
        dfs_breakeven_odds=-119,
        now=NOW,
    )
    fanduel = devig_two_way(-130, 110, "multiplicative")[0]
    pinnacle = devig_two_way(-120, 100, "multiplicative")[0]
    expected = fanduel * 0.6 + pinnacle * 0.4
    assert result.status == "AVAILABLE"
    assert result.hit_probability == pytest.approx(expected)
    assert result.hit_rate_percent == pytest.approx(round(expected * 100, 2))
    assert result.fair_american_odds == pytest.approx(probability_to_american(expected))
    assert result.edge_probability == pytest.approx(expected - 119 / 219)


def test_alternate_lines_are_not_misrepresented_as_target_probability():
    engine = DfsProbabilityEngine({"fanduel": 50, "pinnacle": 50}, minimum_sources=1)
    result = engine.calculate(
        target_line=6.5,
        side="under",
        quotes=[quote("fanduel", -110, -110, line=5.5), quote("pinnacle", 105, -125)],
        now=NOW,
    )
    assert result.status == "AVAILABLE"
    assert result.source_count == 1
    excluded = next(item for item in result.contributions if item["provider"] == "fanduel")
    assert excluded["exclusion_reason"] == "LINE_MISMATCH"


def test_stale_quotes_and_insufficient_sources_return_unavailable():
    engine = DfsProbabilityEngine({"fanduel": 1}, max_quote_age_seconds=60)
    result = engine.calculate(
        target_line=6.5,
        side="over",
        quotes=[quote("fanduel", -110, -110, age=61)],
        now=NOW,
    )
    assert result.status == "UNAVAILABLE"
    assert result.hit_probability is None
    assert result.missing_reason == "INSUFFICIENT_EXACT_LINE_SOURCES"


def test_only_freshest_quote_per_provider_is_used():
    engine = DfsProbabilityEngine({"pinnacle": 1})
    result = engine.calculate(
        target_line=6.5,
        side="over",
        quotes=[
            quote("pinnacle", -200, 160, age=30),
            quote("pinnacle", -110, -110, age=0),
        ],
        now=NOW,
    )
    assert result.source_count == 1
    assert result.hit_probability == pytest.approx(0.5)


def test_zero_weight_source_keeps_devig_probability_for_instant_reweighting():
    engine = DfsProbabilityEngine({"fanduel": 100, "pinnacle": 0})
    result = engine.calculate(
        target_line=6.5,
        side="over",
        quotes=[quote("fanduel", -110, -110), quote("pinnacle", -130, 110)],
        now=NOW,
    )

    pinnacle = next(
        item for item in result.contributions if item["provider"] == "pinnacle"
    )
    assert pinnacle["included"] is False
    assert pinnacle["exclusion_reason"] == "PROVIDER_WEIGHT_NOT_CONFIGURED"
    assert pinnacle["no_vig_probability"] == pytest.approx(
        devig_two_way(-130, 110, "power")[0]
    )
    assert pinnacle["freshness_factor"] == pytest.approx(1)


def test_fake_novig_minus_9900_quote_is_excluded_from_consensus():
    engine = DfsProbabilityEngine(
        {"fanduel": 50, "novig": 50},
        minimum_sources=1,
    )
    result = engine.calculate(
        target_line=6.5,
        side="under",
        quotes=[
            quote("fanduel", -106, -114),
            quote("novig", -110, -9900, liquidity=9),
        ],
        now=NOW,
    )

    novig = next(item for item in result.contributions if item["provider"] == "novig")
    assert novig["included"] is False
    assert novig["exclusion_reason"] == "EXCESSIVE_TWO_WAY_OVERROUND"
    assert result.source_count == 1
    assert result.fair_american_odds != -9900


def test_low_liquidity_exchange_favorite_is_not_weighted():
    engine = DfsProbabilityEngine(
        {"fanduel": 50, "prophetx": 50},
        minimum_sources=1,
    )
    result = engine.calculate(
        target_line=6.5,
        side="over",
        quotes=[
            quote("fanduel", -110, -110),
            quote("prophetx", -185, 155, liquidity=2),
        ],
        now=NOW,
    )

    prophetx = next(
        item for item in result.contributions if item["provider"] == "prophetx"
    )
    assert prophetx["included"] is False
    assert prophetx["exclusion_reason"] == "LOW_LIQUIDITY_EXTREME_QUOTE"
    assert prophetx["minimum_liquidity"] == 2


def test_low_liquidity_exchange_quote_near_reference_market_is_weighted():
    engine = DfsProbabilityEngine(
        {"fanduel": 50, "prophetx": 50},
        minimum_sources=1,
    )
    result = engine.calculate(
        target_line=36.5,
        side="under",
        quotes=[
            quote("fanduel", 120, -150, line=36.5),
            quote("prophetx", 123, -153, line=36.5, liquidity=9),
        ],
        now=NOW,
    )

    prophetx = next(
        item for item in result.contributions if item["provider"] == "prophetx"
    )
    assert prophetx["included"] is True
    assert prophetx["exclusion_reason"] is None
    assert prophetx["minimum_liquidity"] == 9
    assert result.source_count == 2


def test_liquid_extreme_exchange_outlier_is_checked_against_reference_books():
    engine = DfsProbabilityEngine(
        {"fanduel": 40, "draftkings": 40, "polymarket": 20},
        minimum_sources=2,
    )
    result = engine.calculate(
        target_line=6.5,
        side="over",
        quotes=[
            quote("fanduel", -110, -110),
            quote("draftkings", -105, -115),
            quote("polymarket", -400, 260, liquidity=500),
        ],
        now=NOW,
    )

    polymarket = next(
        item for item in result.contributions if item["provider"] == "polymarket"
    )
    assert polymarket["included"] is False
    assert polymarket["exclusion_reason"] == "MARKET_OUTLIER_AGAINST_REFERENCE"
    assert polymarket["reference_divergence"] > 0.10
    assert result.source_count == 2
