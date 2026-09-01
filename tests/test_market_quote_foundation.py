from datetime import datetime, timedelta, timezone

import pytest

from database import TrackerDatabase
from icon_weighting import (
    ExecutionSourcePolicy,
    IconWeightingEngine,
    MarketWeightingProfile,
    ProviderRole,
    WeightingContext,
    WeightingProfileRegistry,
)
from market_quote_adapters import normalize_odds_api_events
from market_quotes import NormalizedMarketQuote


def _quote(*, odds=138, received=None, liquidity=75, limit=500, line=None):
    return NormalizedMarketQuote.create(
        provider="novig",
        provider_event_id="provider-event",
        provider_market_id="provider-market",
        provider_selection_id="provider-selection",
        sport="baseball_mlb",
        league="MLB",
        event_name="Mets vs Phillies",
        home_team="Phillies",
        away_team="Mets",
        start_time="2099-08-12T23:10:00Z",
        market_type="moneyline",
        market_family="main",
        line=line,
        selection="Mets",
        american_odds=odds,
        quote_timestamp=received or datetime.now(timezone.utc),
        received_timestamp=received or datetime.now(timezone.utc),
        available_liquidity=liquidity,
        market_limit=limit,
        mapping_confidence=0.9,
    )


def test_odds_api_adapter_separates_market_limit_from_liquidity():
    events = [{
        "id": "game-1", "sport_key": "baseball_mlb", "sport_title": "MLB",
        "commence_time": "2099-08-12T23:10:00Z", "away_team": "Mets",
        "home_team": "Phillies", "bookmakers": [{"key": "novig", "markets": [{
            "key": "h2h", "last_update": "2099-08-12T20:00:00Z", "outcomes": [
                {"name": "Mets", "price": 138, "bet_limit": 500, "liquidity": 75},
                {"name": "Phillies", "price": -150},
            ]
        }]}]
    }]
    quote = normalize_odds_api_events(events)[0]
    assert quote.provider == "novig"
    assert quote.american_odds == 138
    assert quote.available_liquidity == 75
    assert quote.market_limit == 500
    assert quote.market_id.startswith("mkt_")
    assert quote.selection_id.startswith("sel_")


def test_quote_history_deduplicates_and_preserves_reversions(tmp_path):
    db = TrackerDatabase(tmp_path / "quotes.db")
    first_time = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)
    first = _quote(received=first_time)
    unchanged = first.with_received_timestamp(first_time + timedelta(seconds=30))
    moved = _quote(odds=135, received=first_time + timedelta(seconds=60))
    reverted = _quote(odds=138, received=first_time + timedelta(seconds=90))
    assert db.record_normalized_market_quotes([first])["material_snapshots"] == 1
    assert db.record_normalized_market_quotes([unchanged])["material_snapshots"] == 0
    assert db.record_normalized_market_quotes([moved])["material_snapshots"] == 1
    assert db.record_normalized_market_quotes([reverted])["material_snapshots"] == 1
    history = db.get_normalized_market_quote_history(provider="novig")
    assert [row["american_odds"] for row in history] == [138, 135, 138]


def test_quote_history_adds_periodic_checkpoint_without_poll_duplicates(tmp_path):
    db = TrackerDatabase(tmp_path / "quote-checkpoints.db")
    observed = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)
    first = _quote(received=observed)
    assert db.record_normalized_market_quotes(
        [first], checkpoint_seconds=900
    )["material_snapshots"] == 1
    assert db.record_normalized_market_quotes(
        [first.with_received_timestamp(observed + timedelta(seconds=600))],
        checkpoint_seconds=900,
    )["checkpoints"] == 0
    assert db.record_normalized_market_quotes(
        [first.with_received_timestamp(observed + timedelta(seconds=901))],
        checkpoint_seconds=900,
    )["checkpoints"] == 1
    assert len(db.get_normalized_market_quote_history(provider="novig")) == 2


def test_quote_history_records_and_filters_same_price_line_moves(tmp_path):
    db = TrackerDatabase(tmp_path / "quote-line-moves.db")
    observed = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)
    opening = _quote(line=13.5, received=observed)
    moved = _quote(line=11.5, received=observed + timedelta(minutes=30))

    assert db.record_normalized_market_quotes([opening])["material_snapshots"] == 1
    assert db.record_normalized_market_quotes([moved])["material_snapshots"] == 1

    history = db.get_normalized_market_quote_history(
        event_id=opening.event_id,
        market_type="moneyline",
        market_family="main",
        period="full_game",
        is_alternate=False,
        selection="Mets",
    )
    assert [row["line"] for row in history] == [11.5, 13.5]


def test_weighting_profiles_support_roles_leave_one_out_and_future_maturity():
    profile = MarketWeightingProfile(
        profile_id="mlb-main-draft",
        sport="baseball_mlb",
        league="MLB",
        market_family="main",
        source_base_weights={"pinnacle": 40, "novig": 10},
        provider_roles={
            "pinnacle": ProviderRole.PRICE_DISCOVERY,
            "novig": ProviderRole.EXECUTION,
        },
        execution_source_policy=ExecutionSourcePolicy.LEAVE_ONE_OUT,
    )
    registry = WeightingProfileRegistry([profile])
    assert registry.match(
        sport="baseball_mlb", league="MLB", market_family="main", period="full_game"
    ) is profile
    engine = IconWeightingEngine()
    weight = engine.effective_weight(
        _quote(), profile,
        WeightingContext(
            quote_age_seconds=90,
            freshness_multiplier=0.5,
            maturity_score=0.5,
            provider_reliability=0.8,
        ),
    )
    assert weight.effective_weight == pytest.approx(10 * 0.5 * 0.5 * 0.8 * 0.9)
    assert not engine.eligible_for_fair_value(
        provider="novig", execution_provider="novig", profile=profile
    )
    assert engine.eligible_for_fair_value(
        provider="pinnacle", execution_provider="novig", profile=profile
    )


def test_weighting_profile_loads_from_config_and_enforces_source_floor():
    profile = MarketWeightingProfile.from_config({
        "profile_id": "nba-props-draft",
        "sport": "basketball_nba",
        "league": "NBA",
        "market_family": "player_prop",
        "source_base_weights": {"pinnacle": 1, "novig": 0.25},
        "critical_sources": ["pinnacle"],
        "minimum_sources": 2,
        "missing_source_behavior": "penalize",
        "execution_source_policy": "leave_one_out",
        "provider_roles": {"pinnacle": "price_discovery", "novig": "execution"},
    })
    assert profile.provider_roles["novig"] is ProviderRole.EXECUTION
    assert IconWeightingEngine().missing_source_multiplier(
        {"pinnacle"}, profile
    ) == pytest.approx(0.5)
