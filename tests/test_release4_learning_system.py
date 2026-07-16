from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from learning_system import (
    EDGE_MAP_VERSION,
    RULE_VIOLATION_VERSION,
    LearningConfig,
    build_edge_map,
    compare_holdout,
    evaluate_status,
    violation_analytics,
)
from release4_foundation import RELEASE4_MIGRATION_VERSION


def row(index: int, *, decision="APPROVED_STANDARD", composite=0.02, exchange=0.01, pnl=5.0):
    return {
        "candidate_id": f"candidate-{index}", "current_decision": decision,
        "detected_at": f"2026-01-{(index % 28) + 1:02d}T12:00:00+00:00",
        "event_start_time": f"2026-01-{(index % 28) + 1:02d}T18:00:00+00:00",
        "sport": "Soccer", "league": "World Cup", "provider": "polymarket",
        "market_title": "Moneyline", "entry_price": 0.50, "stake": 100,
        "result": "Won", "profit_loss": pnl, "exchange_clv": exchange,
        "composite_clv": composite, "execution_loss": 1.0, "fees": 0.25,
        "trade_grade": "A", "liquidity_grade": "GOOD", "execution_method": "TAKE_NOW",
        "snapshot": {"rawAgreeingSharpCount": 3, "weighted_sharp_count": 2.4,
                     "relative_size": 1.2, "tradeClassification": "STANDARD",
                     "primary_sharp": {"name": "Sharp One", "wallet_type": "LEAD"}},
    }


def test_small_samples_can_never_be_validated():
    config = LearningConfig()
    assert evaluate_status(24, 24, 0.20, 0.20, config) == "INSUFFICIENT_SAMPLE"
    assert evaluate_status(25, 25, 0.20, 0.20, config) == "DISCOVERY"
    assert evaluate_status(100, 100, 0.02, 0.05, config) == "PROMISING"
    assert evaluate_status(250, 100, 0.02, 0.05, config) == "VALIDATED"


def test_edge_map_reports_played_passed_clv_roi_and_reliability():
    rows = [row(i) for i in range(120)] + [row(200 + i, decision="PASSED", pnl=None) for i in range(30)]
    segments = build_edge_map(rows)
    soccer = next(item for item in segments if item["dimension"] == "sport" and item["segment_value"] == "Soccer")
    assert soccer["candidate_count"] == 150
    assert soccer["played_count"] == 120
    assert soccer["passed_count"] == 30
    assert soccer["settled_count"] == 150
    assert soccer["roi"] == pytest.approx(0.05)
    assert soccer["stake_weighted_composite_clv"] == pytest.approx(0.02)
    assert soccer["status"] == "PROMISING"
    assert soccer["calculation_version"] == EDGE_MAP_VERSION


def test_played_and_passed_are_compared_in_same_segment():
    segments = build_edge_map([row(1), row(2, decision="PASSED", pnl=None)])
    provider = next(item for item in segments if item["dimension"] == "provider")
    assert provider["played_count"] == 1
    assert provider["passed_count"] == 1


def test_weak_segment_requires_moderate_sample_and_negative_evidence():
    segment = next(item for item in build_edge_map([row(i, composite=-0.02, pnl=-4) for i in range(100)]) if item["dimension"] == "sport")
    assert segment["status"] == "WEAK"
    suspended = next(item for item in build_edge_map([row(i, composite=-0.02, pnl=-4) for i in range(250)]) if item["dimension"] == "sport")
    assert suspended["status"] == "SUSPENDED"


def test_holdout_requires_later_minimum_sample_and_positive_evidence():
    config = LearningConfig(minimum_holdout_count=50)
    baseline = {"candidate_count": 100, "stake_weighted_composite_clv": 0.03, "roi": 0.05}
    assert compare_holdout(baseline, {"candidate_count": 49, "stake_weighted_composite_clv": 0.04, "roi": 0.05}, config)["status"] == "HOLDOUT_FAILED"
    passed = compare_holdout(baseline, {"candidate_count": 50, "stake_weighted_composite_clv": 0.01, "roi": 0.01}, config)
    assert passed["status"] == "HOLDOUT_PASSED"


def test_rule_violation_analytics_preserves_unavailable_clv():
    result = violation_analytics([{"warning_code": "ABOVE_MAXIMUM_PRICE", "profit_loss": None, "exchange_clv": None, "composite_clv": None}])[0]
    assert result["count"] == 1
    assert result["settled_count"] == 0
    assert result["average_composite_clv"] is None


def test_release4_migration_and_snapshot_persistence(db):
    with db.connection() as conn:
        tables = {item[0] for item in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        version = conn.execute("SELECT version FROM schema_migrations WHERE version = ?", (RELEASE4_MIGRATION_VERSION,)).fetchone()
    assert {"edge_map_runs", "edge_map_segment_snapshots", "holdout_evaluations", "configuration_proposals", "rule_violations"} <= tables
    assert version[0] == RELEASE4_MIGRATION_VERSION
    segments = build_edge_map([row(1)])
    now = datetime.now(timezone.utc).isoformat()
    run = {"run_id": "run-1", "window_start": now, "window_end": now, "candidate_count": 1, "config": {}, "calculation_version": EDGE_MAP_VERSION, "created_at": now}
    db.record_edge_map(run, segments)
    assert db.latest_edge_map()["run"]["run_id"] == "run-1"
    assert db.release4_diagnostics()["table_counts"]["edge_map_segment_snapshots"] == len(segments)


def test_configuration_proposal_cannot_approve_before_passed_holdout(db):
    proposal = db.create_configuration_proposal({"segment_dimension": "sport", "segment_value": "Soccer", "proposal_type": "WEIGHT_CHANGE", "old_config": {"weight": 1}, "proposed_config": {"weight": 1.1}, "evidence": {"status": "PROMISING"}}, "admin")
    with pytest.raises(ValueError):
        db.review_configuration_proposal(proposal["proposal_id"], "APPROVED", "admin")
    db.review_configuration_proposal(proposal["proposal_id"], "HOLDOUT_PASSED", "holdout-engine")
    approved = db.review_configuration_proposal(proposal["proposal_id"], "APPROVED", "admin")
    assert approved["status"] == "APPROVED"
    assert approved["applied_at"] is None
    assert approved["config_version_after"]


def test_rule_violation_requires_explicit_confirmation_and_is_user_scoped(app_client):
    assert app_client.post("/api/rule-violations", json={"trade_id": "t1", "warning_code": "ABOVE_MAXIMUM_PRICE", "confirmed_action": "BUY"}).status_code == 400
    response = app_client.post("/api/rule-violations", json={"trade_id": "t1", "warning_code": "ABOVE_MAXIMUM_PRICE", "confirmed_action": "BUY", "confirmed": True, "confirmation_text": "I understand the maximum-price warning.", "profit_loss": 999, "composite_clv": 1})
    assert response.status_code == 201
    stored = app_client.get("/api/rule-violations").get_json()["data"][0]
    assert stored["profit_loss"] is None
    assert stored["composite_clv"] is None
    assert stored["calculation_version"] == RULE_VIOLATION_VERSION


def test_edge_map_page_and_api_are_available_without_fabricated_rows(app_client):
    assert app_client.get("/edge-map").status_code == 200
    payload = app_client.get("/api/edge-map").get_json()
    assert payload["data"]["run"]["candidate_count"] == 0
    assert payload["data"]["segments"] == []
    assert payload["production_weights_auto_changed"] is False


def test_learning_admin_routes_require_auth_and_recalculation_is_observational(app_client):
    assert app_client.get("/api/admin/learning-system/diagnostics").status_code == 403
    assert app_client.post("/api/admin/learning-system/recalculate").status_code == 403
    assert app_client.get("/api/admin/configuration-proposals").status_code == 403


def test_admin_learning_workflow(monkeypatch, temp_settings, db):
    import app as app_module
    from position_tracker import TrackerService
    service = TrackerService(temp_settings, database=db, auto_start=False)
    settings = replace(temp_settings, admin_password="release-four-admin")
    monkeypatch.setattr(app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(app_module, "TrackerService", lambda _settings, auto_start=True: service)
    client = app_module.create_app(start_background=False).test_client()
    assert client.post("/api/admin/login", json={"password": "release-four-admin"}).status_code == 200
    recalculated = client.post("/api/admin/learning-system/recalculate").get_json()["data"]
    assert recalculated["run"]["candidate_count"] == 0
    proposal = client.post("/api/admin/configuration-proposals", json={"segment_dimension": "sport", "segment_value": "Soccer", "proposal_type": "WEIGHT_CHANGE", "proposed_config": {"weight": 1.1}})
    assert proposal.status_code == 201
    assert proposal.get_json()["live_configuration_changed"] is False
    diagnostics = client.get("/api/admin/learning-system/diagnostics").get_json()["data"]
    assert diagnostics["release"] == "release-4-learning-system"
    assert diagnostics["production_weights_auto_changed"] is False
    assert diagnostics["provider_data_fabricated"] is False
