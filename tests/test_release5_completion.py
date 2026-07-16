from __future__ import annotations

from dataclasses import replace

import pytest

from completion_system import (
    APPLIED_POLICY_VERSION,
    EXPLAINABILITY_VERSION,
    explainability_trace,
    matching_policy,
)
from position_tracker import TrackerService
from release5_foundation import RELEASE5_MIGRATION_VERSION


def approved_proposal(db, *, multiplier: float = 0.75):
    proposal = db.create_configuration_proposal(
        {
            "segment_dimension": "sport",
            "segment_value": "Soccer",
            "proposal_type": "STAKE_MULTIPLIER",
            "old_config": {"stake_multiplier": 1.0},
            "proposed_config": {"stake_multiplier": multiplier},
            "evidence": {"status": "HOLDOUT_PASSED", "sample_size": 75},
        },
        "admin",
    )
    db.review_configuration_proposal(proposal["proposal_id"], "HOLDOUT_PASSED", "holdout-engine")
    return db.review_configuration_proposal(proposal["proposal_id"], "APPROVED", "admin")


def test_release5_additive_migration_is_recorded(db):
    with db.connection() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        version = conn.execute(
            "SELECT version FROM schema_migrations WHERE version = ?",
            (RELEASE5_MIGRATION_VERSION,),
        ).fetchone()
    assert {
        "production_configuration_versions",
        "segment_policy_assignments",
        "post_change_monitoring_runs",
    } <= tables
    assert version[0] == RELEASE5_MIGRATION_VERSION


def test_only_approved_non_risk_increasing_policy_can_be_applied(db):
    proposal = db.create_configuration_proposal(
        {
            "segment_dimension": "sport",
            "segment_value": "Soccer",
            "proposal_type": "STAKE_MULTIPLIER",
            "proposed_config": {"stake_multiplier": 0.8},
        },
        "admin",
    )
    with pytest.raises(ValueError, match="approved"):
        db.apply_configuration_proposal(proposal["proposal_id"], "admin")

    unsafe = approved_proposal(db, multiplier=1.01)
    with pytest.raises(ValueError, match="cannot increase risk"):
        db.apply_configuration_proposal(unsafe["proposal_id"], "admin")


def test_applied_policy_matches_segment_and_records_post_change_monitoring(db):
    proposal = approved_proposal(db)
    applied = db.apply_configuration_proposal(proposal["proposal_id"], "admin")
    assert applied["stake_multiplier"] == 0.75
    policy = matching_policy(
        {"category": "Soccer", "league": "World Cup", "market_title": "Winner"},
        db.active_segment_policies(),
    )
    assert policy["stake_multiplier"] == 0.75
    assert policy["calculation_version"] == APPLIED_POLICY_VERSION
    assert len(policy["matched_policies"]) == 1

    count = db.record_post_change_monitoring(
        "edge-run-5",
        [{"dimension": "sport", "segment_value": "Soccer", "status": "PROMISING", "candidate_count": 80}],
    )
    assert count == 1
    diagnostics = db.completion_diagnostics()
    assert diagnostics["table_counts"]["post_change_monitoring_runs"] == 1
    assert diagnostics["risk_increasing_policies_allowed"] is False


def test_explainability_trace_is_complete_and_never_fabricates_missing_sources():
    trace = explainability_trace(
        {
            "candidate": {
                "candidate_id": "candidate-5",
                "correlation_id": "correlation-5",
                "canonical_event_id": "event-5",
                "snapshot": {"lead_sharp_count": 1, "weighted_sharp_count": 1.0},
            },
            "decisions": [{"decision": "APPROVED_STANDARD"}],
            "composite_price_snapshots": [],
            "composite_source_contributions": [],
        }
    )
    assert len(trace["stages"]) == 16
    assert trace["calculation_version"] == EXPLAINABILITY_VERSION
    assert trace["fabricated_data"] is False
    stages = {item["stage"]: item for item in trace["stages"]}
    assert stages["fair_price_sources"]["status"] == "UNAVAILABLE"
    assert stages["composite_probability"]["status"] == "UNAVAILABLE"
    assert stages["kelly"]["status"] == "UNAVAILABLE"
    assert stages["final_recommendation"]["status"] == "UNAVAILABLE"
    assert stages["model_tracker_eligibility"]["status"] == "AVAILABLE"


def test_completion_admin_routes_are_authorized(monkeypatch, temp_settings, db):
    import app as app_module

    service = TrackerService(temp_settings, database=db, auto_start=False)
    settings = replace(temp_settings, admin_password="release-five-admin")
    monkeypatch.setattr(app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(app_module, "TrackerService", lambda _settings, auto_start=True: service)
    client = app_module.create_app(start_background=False).test_client()

    assert client.get("/intelligence").status_code == 200
    assert client.get("/api/admin/completion/diagnostics").status_code == 403
    assert client.get("/api/admin/rule-violations").status_code == 403
    assert client.get("/api/admin/explainability/missing").status_code == 403
    assert client.get("/api/tracker/advanced-analytics").status_code == 200

    assert client.post("/api/admin/login", json={"password": "release-five-admin"}).status_code == 200
    diagnostics = client.get("/api/admin/completion/diagnostics").get_json()["data"]
    assert diagnostics["release"] == "release-5-completion"
    assert diagnostics["fabricated_data"] is False

    proposal = approved_proposal(db)
    response = client.post(f"/api/admin/configuration-proposals/{proposal['proposal_id']}/apply")
    assert response.status_code == 200
    assert response.get_json()["risk_increase_allowed"] is False
