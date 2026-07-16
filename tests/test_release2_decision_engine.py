from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from bet_sizing import build_recommendation
from database import TrackerDatabase
from decision_engine import (
    enrich_trade_decision,
    grade_for_score,
    independent_sharp_signal,
    liquidity_quality,
    score_trade_quality,
    uncertainty_adjusted_kelly,
    weighted_opposition,
)
from fair_price_engine import FairPriceEngine, no_vig_probabilities
from measurement_foundation import build_candidate_record
from position_tracker import TrackerService
from release2_foundation import RELEASE2_MIGRATION_VERSION


NOW = datetime(2026, 7, 16, 16, 0, tzinfo=timezone.utc)


def _quote(provider: str, probability: float, *, age: int = 0, mapping: str = "EXACT") -> dict:
    return {
        "provider": provider,
        "status": "AVAILABLE",
        "quote_timestamp": (NOW - timedelta(seconds=age)).isoformat(),
        "mapping_confidence": mapping,
        "no_vig_probability": probability,
        "fabricated_data": False,
    }


def _play() -> dict:
    return {
        "id": "market::yes",
        "current_price": 0.5,
        "expected_fee_fraction": 0.0,
        "sharp_reference_entry_price": 0.49,
        "event_date_et": (NOW + timedelta(hours=2)).isoformat(),
        "tradeClassification": "STANDARD",
        "rawAgreeingSharpCount": 3,
        "agreeing_wallet_count": 3,
        "lead_sharp_count": 2,
        "supporting_sharp_count": 1,
        "has_lead_sharp": True,
        "lead_wallet_ids": ["lead-a", "lead-b"],
        "supporting_wallet_ids": ["support-c"],
        "agreeingWalletIds": ["lead-a", "lead-b", "support-c"],
        "strongest_relative_units": 3,
        "agreeingExposureDollars": 1000,
        "contradicting_wallets": [],
        "evidence_inputs": {
            "category_details": [{"sample_size": 60, "adjusted_hit_rate": 0.58}]
        },
        "orderbook": {
            "asks": [{"price": 0.5, "size": 2000}, {"price": 0.51, "size": 3000}],
            "bids": [{"price": 0.49, "size": 2000}],
        },
    }


def test_no_vig_normalization_removes_overround():
    values = no_vig_probabilities([-120, 110])
    assert values is not None
    assert sum(values) == pytest.approx(1.0)
    assert values[0] > values[1]


def test_fair_price_uses_only_fresh_exact_independent_sources():
    engine = FairPriceEngine({"pinnacle": 0.75, "circa": 0.25}, 180)
    result = engine.calculate(
        [
            _quote("pinnacle", 0.60),
            _quote("circa", 0.52),
            _quote("polymarket", 0.99),
            _quote("pinnacle", 0.10, age=181),
            _quote("circa", 0.90, mapping="PROBABLE"),
        ],
        NOW,
    ).to_dict()
    assert result["status"] == "AVAILABLE"
    assert result["fair_probability"] == pytest.approx(0.58)
    assert result["source_count"] == 2
    assert result["fabricated_data"] is False
    assert {row["exclusion_reason"] for row in result["contributions"]} >= {
        "DEPENDENT_EXECUTION_MARKET", "STALE_QUOTE", "MARKET_MAPPING_UNCERTAIN"
    }


def test_missing_fair_price_stays_unavailable_and_never_creates_kelly():
    result = FairPriceEngine().calculate([], NOW).to_dict()
    assert result["status"] == "UNAVAILABLE"
    assert result["fair_probability"] is None
    play = _play()
    play["fair_price"] = result
    recommendation = build_recommendation(play, 10000)
    assert recommendation["available"] is False
    assert recommendation["estimated_win_probability"] is None
    assert recommendation["full_kelly_fraction"] is None


def test_uncertainty_haircut_reduces_probability_edge_and_kelly():
    clean = uncertainty_adjusted_kelly(0.60, 0.50, liquidity_score=100)
    uncertain = uncertainty_adjusted_kelly(
        0.60, 0.50, reliability=0.7, source_dispersion=0.05, liquidity_score=50
    )
    assert 0.50 < uncertain["adjusted_probability"] < clean["adjusted_probability"]
    assert uncertain["half_kelly_fraction"] < clean["half_kelly_fraction"]


def test_independence_collapses_known_copy_relationships():
    play = _play()
    play["wallet_dependencies"] = {
        "lead-b": {"copy_trading": True, "type": "COPY", "target_wallet_id": "lead-a"},
        "support-c": {"synchronized_entry": True, "type": "TIMING_CLUSTER"},
    }
    result = independent_sharp_signal(play)
    assert result["raw_count"] == 3
    assert result["independent_equivalent_count"] == pytest.approx(1.5)
    assert result["independent_equivalent_count"] < result["raw_count"]


def test_weighted_opposition_distinguishes_note_from_pass():
    play = _play()
    play["contradicting_wallets"] = [{"wallet_address": "opp", "amount": 20, "relative_units": 0.1, "is_hedge": True}]
    note = weighted_opposition(play)
    play["contradicting_wallets"] = [
        {"wallet_address": "opp", "amount": 3000, "relative_units": 5, "category_metrics": {"sample_size": 60}}
        for _ in range(2)
    ]
    passed = weighted_opposition(play)
    assert note["action"] == "NOTE_ONLY"
    assert passed["action"] == "PASS"


def test_liquidity_score_and_trade_quality_component_limits():
    play = _play()
    fair = FairPriceEngine({"pinnacle": 1.0}).calculate([_quote("pinnacle", 0.60)], NOW).to_dict()
    liquidity = liquidity_quality(play)
    quality = score_trade_quality(play, fair)
    assert 0 <= liquidity["score"] <= 100
    assert quality.components["signal"] <= 30
    assert quality.components["price"] <= 30
    assert quality.components["liquidity"] <= 23
    assert quality.components["context"] <= 17
    assert 0 <= quality.score <= 100


@pytest.mark.parametrize(
    ("score", "grade"), [(54, "PASS"), (55, "DISCOVERY"), (65, "B"), (75, "A"), (85, "A_PLUS")]
)
def test_grade_thresholds(score, grade):
    assert grade_for_score(score) == grade


def test_missing_fair_price_and_research_are_capped_at_discovery():
    play = _play()
    unavailable = FairPriceEngine().calculate([], NOW).to_dict()
    result = score_trade_quality(play, unavailable)
    assert result.grade in {"PASS", "DISCOVERY"}
    play["tradeClassification"] = "SHARP_NON_CATEGORY"
    available = FairPriceEngine({"pinnacle": 1.0}).calculate([_quote("pinnacle", 0.70)], NOW).to_dict()
    assert score_trade_quality(play, available).grade in {"PASS", "DISCOVERY"}


def test_release2_migration_is_additive_and_diagnostics_are_authorized(
    monkeypatch, temp_settings, db: TrackerDatabase
):
    with db.connection() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        migration = conn.execute(
            "SELECT version FROM schema_migrations WHERE version = ?", (RELEASE2_MIGRATION_VERSION,)
        ).fetchone()
    assert {
        "trade_quality_snapshots", "liquidity_quality_snapshots",
        "wallet_dependency_edges", "opposition_snapshots",
    } <= tables
    assert migration[0] == RELEASE2_MIGRATION_VERSION

    import app as app_module

    service = TrackerService(temp_settings, database=db, auto_start=False)
    admin_settings = replace(temp_settings, admin_password="release-two-admin")
    monkeypatch.setattr(app_module, "get_settings", lambda: admin_settings)
    monkeypatch.setattr(app_module, "TrackerService", lambda _settings, auto_start=True: service)
    client = app_module.create_app(start_background=False).test_client()
    assert client.get("/api/admin/decision-engine/diagnostics").status_code == 403
    assert client.post("/api/admin/login", json={"password": "release-two-admin"}).status_code == 200
    payload = client.get("/api/admin/decision-engine/diagnostics").get_json()["data"]
    assert payload["release"] == "release-2-decision-engine"
    assert payload["fabricated_provider_data"] is False


def test_decision_snapshots_are_persisted_without_overwriting_history(
    temp_settings, db: TrackerDatabase
):
    service = TrackerService(temp_settings, database=db, auto_start=False)
    candidate = _play()
    candidate.update(
        {
            "event_slug": "release2-event",
            "event_title": "Spain vs France",
            "market_title": "To advance",
            "outcome": "Spain",
            "clob_token_id": "release2-outcome",
            "category": "Soccer",
            "league": "World Cup",
            "market_open": True,
            "lifecycle_status": "upcoming",
            "average_entry_price": 0.49,
            "validation_ids": {
                "event_id": "release2-event",
                "condition_id": "release2-market",
                "outcome_token_id": "release2-outcome",
            },
        }
    )
    fair = FairPriceEngine({"pinnacle": 1.0}).calculate(
        [_quote("pinnacle", 0.60)], NOW
    ).to_dict()
    enrich_trade_decision(candidate, fair)
    evaluation = service.evaluate_recommendation(candidate, 10000, NOW)
    record = build_candidate_record(candidate, evaluation, NOW.isoformat())
    db.record_candidate(record)
    db.record_decision_engine_snapshot(
        record["candidate_id"], record["correlation_id"], candidate, NOW.isoformat()
    )
    diagnostics = db.decision_engine_diagnostics()
    assert diagnostics["table_counts"]["trade_quality_snapshots"] == 1
    assert diagnostics["table_counts"]["liquidity_quality_snapshots"] == 1
    assert diagnostics["table_counts"]["opposition_snapshots"] == 1
    assert diagnostics["table_counts"]["wallet_dependency_edges"] == 3
