from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from bet_sizing import build_recommendation
from database import TrackerDatabase
from execution_engine import (
    PASS,
    POST_LIMIT,
    SPLIT_ORDER,
    TAKE_NOW,
    WAIT,
    build_execution_plan,
    maximum_average_price,
    walk_ask_depth,
)
from position_tracker import MODEL_TRACKER_USER_ID, TrackerService
from recommendation_service import STRATEGY_STOP, evaluate_trade_recommendation
from release3_foundation import RELEASE3_MIGRATION_VERSION
from risk_engine import (
    RiskConfig,
    bankroll_buckets,
    evaluate_portfolio_risk,
    normalize_exposure,
    risk_state,
)


NOW = datetime(2026, 7, 16, 16, 0, tzinfo=timezone.utc)


def _play(*, ask: float = 0.50, size: float = 1000, grade: str = "A") -> dict:
    return {
        "id": "release3-market::release3-outcome",
        "event_slug": "release3-event",
        "event_title": "Spain vs France",
        "market_title": "To advance",
        "outcome": "Spain",
        "clob_token_id": "release3-outcome",
        "event_date_et": (NOW + timedelta(hours=2)).isoformat(),
        "category": "Soccer",
        "canonical_sport_id": "soccer",
        "league": "World Cup",
        "market_open": True,
        "lifecycle_status": "upcoming",
        "current_price": ask,
        "average_entry_price": 0.49,
        "sharp_reference_entry_price": 0.49,
        "expected_fee_fraction": 0.0,
        "tradeClassification": "STANDARD",
        "trade_quality": {"score": 80, "grade": grade},
        "fair_price": {
            "status": "AVAILABLE",
            "fair_probability": 0.60,
            "source_count": 3,
            "source_dispersion": 0.0,
            "reliability": 1.0,
        },
        "liquidity_quality": {"score": 90},
        "agreeing_wallet_count": 2,
        "rawAgreeingSharpCount": 2,
        "lead_sharp_count": 2,
        "supporting_sharp_count": 0,
        "weighted_sharp_count": 2.0,
        "has_lead_sharp": True,
        "tracked_wallet_count": 3,
        "evidence_inputs": {
            "combined_amount": 1.0,
            "relative_size": 1.0,
            "top_category": 1.0,
            "adjusted_category_hit_rate": 1.0,
            "category_sample_size": 1.0,
        },
        "validation_ids": {
            "event_id": "release3-event",
            "condition_id": "release3-market",
            "outcome_token_id": "release3-outcome",
        },
        "orderbook": {
            "asks": [{"price": ask, "size": size}],
            "bids": [{"price": ask - 0.01, "size": size}],
            "timestamp": NOW.isoformat(),
            "tick_size": 0.001,
            "min_order_size": 1,
        },
    }


def _normal_context(exposures=None, **state):
    return {
        "exposures": exposures or [],
        "account_state": {
            "current_bankroll": 10000,
            "high_water_mark": 10000,
            **state,
        },
        "config": RiskConfig(),
        "evaluation_now": NOW,
    }


def test_maximum_average_price_reserves_edge_fees_and_execution_risk():
    maximum = maximum_average_price(
        0.60, "A", expected_fee_fraction=0.01, execution_risk_fraction=0.005
    )
    assert maximum == pytest.approx(0.565)


def test_depth_walk_uses_multiple_levels_and_stops_at_maximum_average():
    full = walk_ask_depth(
        [{"price": 0.50, "size": 100}, {"price": 0.52, "size": 100}],
        75,
        0.52,
    )
    assert full["fully_executable"] is True
    assert full["levels_used"] == 2
    assert full["effective_price"] > 0.50

    partial = walk_ask_depth(
        [{"price": 0.50, "size": 20}, {"price": 0.60, "size": 1000}],
        100,
        0.52,
    )
    assert 0 < partial["executable_amount"] < 100
    assert partial["unfilled_amount"] > 0
    assert partial["effective_price"] <= 0.52 + 1e-9


def test_execution_methods_cover_take_post_split_wait_and_pass():
    play = _play()
    take = build_execution_plan(play, 50, 0.60, "A", expected_fee_fraction=0, now=NOW)
    assert take["recommended_execution_method"] == TAKE_NOW

    above = _play(ask=0.59)
    post = build_execution_plan(above, 50, 0.60, "A", expected_fee_fraction=0, now=NOW)
    assert post["recommended_execution_method"] == POST_LIMIT
    assert post["execution_reason_code"] == "BEST_ASK_ABOVE_MAXIMUM"

    thin = _play(size=10)
    split = build_execution_plan(thin, 50, 0.60, "A", expected_fee_fraction=0, now=NOW)
    assert split["recommended_execution_method"] == SPLIT_ORDER
    assert split["unfilled_amount"] > 0

    stale = _play()
    stale["orderbook"]["timestamp"] = (NOW - timedelta(seconds=61)).isoformat()
    wait = build_execution_plan(stale, 50, 0.60, "A", expected_fee_fraction=0, now=NOW)
    assert wait["recommended_execution_method"] == WAIT

    passed = build_execution_plan(play, 0, 0.60, "A", expected_fee_fraction=0, now=NOW)
    assert passed["recommended_execution_method"] == PASS


def test_bankroll_buckets_are_separate_and_reserve_is_not_spendable():
    exposures = [
        {"bucket": "CORE", "amount": 100},
        {"bucket": "DISCOVERY", "amount": 25},
    ]
    result = bankroll_buckets(1000, exposures)
    assert result["buckets"]["CORE"]["allocated_amount"] == 700
    assert result["buckets"]["CORE"]["available_amount"] == 600
    assert result["buckets"]["DISCOVERY"]["available_amount"] == 75
    assert result["buckets"]["LIQUIDITY_RESERVE"]["allocated_amount"] == 150
    assert result["buckets"]["OPERATIONAL_BUFFER"]["allocated_amount"] == 50


@pytest.mark.parametrize(
    ("current", "state", "multiplier"),
    [
        (9600, "NORMAL", 1.0),
        (9500, "REVIEW", 1.0),
        (9000, "REDUCED", 0.75),
        (8500, "DEFENSIVE", 0.50),
    ],
)
def test_drawdown_protocol_thresholds(current, state, multiplier):
    result = risk_state(current, 10000)
    assert result["state"] == state
    assert result["stake_multiplier"] == multiplier


def test_each_strategy_stop_condition_fails_closed():
    assert risk_state(10000, 10000, manual_kill_switch=True)["state"] == "STRATEGY_STOP"
    assert risk_state(
        10000, 10000, recent_stake_weighted_composite_clv=-0.01,
        recent_valid_trade_count=100,
    )["state"] == "STRATEGY_STOP"
    assert risk_state(10000, 10000, material_error_count_7d=3)["state"] == "STRATEGY_STOP"
    assert risk_state(10000, 10000, wallet_data_invalid=True)["state"] == "STRATEGY_STOP"
    assert risk_state(10000, 10000, provider_unreliable=True)["state"] == "STRATEGY_STOP"


def test_correlation_reduces_stake_using_model_and_personal_exposure():
    play = _play()
    existing_model = normalize_exposure(
        {"snapshot": {**play, "original_displayed_amount": 150}}, "MODEL_TRACKER"
    )
    existing_personal = normalize_exposure(
        {**play, "total_paid": 80, "sportsbook": "Polymarket"}, "PERSONAL_TRACKER"
    )
    result = evaluate_portfolio_risk(
        play, 100, 10000, [existing_model, existing_personal],
        {"current_bankroll": 10000, "high_water_mark": 10000},
    )
    assert result["existing_related_exposure"]["same_game"] == 230
    assert result["remaining_capacity"]["same_game"] == 20
    assert result["final_capped_stake"] == 20
    assert result["correlation_multiplier"] == pytest.approx(0.2)


def test_strategy_stop_blocks_model_tracker_but_preserves_trace(temp_settings, db):
    service = TrackerService(temp_settings, database=db, auto_start=False)
    db.set_manual_kill_switch(
        MODEL_TRACKER_USER_ID, True, "MANUAL_ADMIN_KILL_SWITCH", "test-admin"
    )
    evaluation = service.evaluate_recommendation(_play(), 10000, NOW)
    assert evaluation["model_tracker_eligible"] is False
    assert evaluation["model_tracker_rejection_reason"] == STRATEGY_STOP
    assert evaluation["recommendation"]["portfolio_risk"]["risk_state"]["state"] == "STRATEGY_STOP"
    assert evaluation["recommendation"]["execution_plan"]


def test_release3_migration_snapshot_history_and_admin_security(
    monkeypatch, temp_settings, db: TrackerDatabase
):
    with db.connection() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        migration = conn.execute(
            "SELECT version FROM schema_migrations WHERE version = ?",
            (RELEASE3_MIGRATION_VERSION,),
        ).fetchone()
    assert {
        "execution_plan_snapshots", "portfolio_risk_snapshots",
        "bankroll_bucket_configs", "risk_account_state", "kill_switch_audit",
    } <= tables
    assert migration[0] == RELEASE3_MIGRATION_VERSION

    service = TrackerService(temp_settings, database=db, auto_start=False)
    recommendation = build_recommendation(_play(), 10000, risk_context=_normal_context())
    db.record_release3_snapshots(
        MODEL_TRACKER_USER_ID, "candidate", "correlation", "recommendation",
        recommendation["execution_plan"], recommendation["portfolio_risk"], NOW.isoformat(),
    )
    diagnostics = db.release3_diagnostics()
    assert diagnostics["table_counts"]["execution_plan_snapshots"] == 1
    assert diagnostics["table_counts"]["portfolio_risk_snapshots"] == 1

    import app as app_module

    admin_settings = replace(temp_settings, admin_password="release-three-admin")
    monkeypatch.setattr(app_module, "get_settings", lambda: admin_settings)
    monkeypatch.setattr(app_module, "TrackerService", lambda _settings, auto_start=True: service)
    client = app_module.create_app(start_background=False).test_client()
    assert client.get("/api/admin/execution-risk/diagnostics").status_code == 403
    assert client.post("/api/admin/risk/kill-switch", json={"enabled": True}).status_code == 403
    assert client.post("/api/admin/login", json={"password": "release-three-admin"}).status_code == 200
    payload = client.get("/api/admin/execution-risk/diagnostics").get_json()["data"]
    assert payload["release"] == "release-3-execution-and-risk"
    assert payload["personal_positions_private"] is True
    assert payload["fabricated_data"] is False


def test_bankroll_configuration_is_user_specific_and_validated(db: TrackerDatabase):
    first = db.update_bankroll_bucket_config(
        "user-a",
        {
            "core_allocation": 0.60,
            "discovery_allocation": 0.15,
            "liquidity_reserve_allocation": 0.20,
            "operational_buffer_allocation": 0.05,
            "combine_model_and_personal": False,
        },
    )
    second = db.get_bankroll_bucket_config("user-b")
    assert first["core_allocation"] == pytest.approx(0.60)
    assert first["combine_model_and_personal"] is False
    assert second["core_allocation"] == pytest.approx(0.70)
    with pytest.raises(ValueError):
        db.update_bankroll_bucket_config(
            "user-a",
            {
                "core_allocation": 0.80,
                "discovery_allocation": 0.20,
                "liquidity_reserve_allocation": 0.20,
                "operational_buffer_allocation": 0.05,
            },
        )


def test_personal_research_tags_use_discovery_bucket():
    exposure = normalize_exposure(
        {
            **_play(),
            "total_paid": 75,
            "tags_json": '["manual", "research-only"]',
        },
        "PERSONAL_TRACKER",
    )
    assert exposure["bucket"] == "DISCOVERY"
