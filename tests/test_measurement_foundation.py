from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from database import TrackerDatabase
from measurement_foundation import (
    CandidateDecision,
    CandidateReason,
    CompositePriceProviderRegistry,
    RELEASE1_MIGRATION_VERSION,
    build_candidate_record,
    build_exclusion_record,
    unavailable_composite_snapshot,
)
from position_tracker import TrackerService


NOW = datetime(2026, 7, 15, 16, 0, tzinfo=timezone.utc)


def play(*, classification: str = "STANDARD", event_id: str = "event-1") -> dict:
    start = NOW + timedelta(hours=3)
    return {
        "id": f"market-1::outcome-1",
        "event_slug": event_id,
        "event_title": "Spain vs France",
        "market_title": "To Advance",
        "market_line": None,
        "outcome": "Spain",
        "clob_token_id": "outcome-1",
        "event_date_et": start.isoformat(),
        "category": "Soccer",
        "league": "World Cup",
        "market_open": True,
        "lifecycle_status": "upcoming",
        "agreeing_wallet_count": 2,
        "rawAgreeingSharpCount": 2,
        "rawContradictingSharpCount": 0,
        "raw_sharp_count": 2,
        "lead_sharp_count": 2 if classification == "STANDARD" else 0,
        "supporting_sharp_count": 0 if classification == "STANDARD" else 2,
        "weighted_sharp_count": 2.0 if classification == "STANDARD" else 0.5,
        "has_lead_sharp": classification == "STANDARD",
        "lead_wallet_ids": ["0xlead1", "0xlead2"] if classification == "STANDARD" else [],
        "supporting_wallet_ids": [] if classification == "STANDARD" else ["0xsupport1", "0xsupport2"],
        "tracked_wallet_count": 2,
        "confidence_score": 82 if classification == "STANDARD" else 58,
        "fair_price": {
            "status": "AVAILABLE",
            "fair_probability": 0.44,
            "source_count": 2,
            "source_dispersion": 0.01,
        },
        "trade_quality": {
            "score": 72 if classification == "STANDARD" else 58,
            "grade": "B" if classification == "STANDARD" else "DISCOVERY",
            "components": {},
            "caps": [] if classification == "STANDARD" else ["RESEARCH_CLASSIFICATION"],
            "pass_reasons": [],
            "calculation_version": "trade-quality-v2",
        },
        "liquidity_quality": {"score": 100},
        "combined_exposure_exact": 2000.0,
        "expected_fee_fraction": 0.0,
        "average_entry_price": 0.4,
        "tradeClassification": classification,
        "supporting_wallets": [],
        "evidence_inputs": {
            "combined_amount": 1.0,
            "relative_size": 1.0,
            "top_category": 1.0,
            "adjusted_category_hit_rate": 1.0,
            "category_sample_size": 1.0,
        },
        "validation_ids": {
            "event_id": event_id,
            "condition_id": "market-1",
            "outcome_token_id": "outcome-1",
            "event_slug": event_id,
            "market_slug": "market-1",
        },
        "orderbook": {
            "asks": [{"price": 0.4, "size": 10000}],
            "bids": [{"price": 0.39, "size": 10000}],
            "timestamp": NOW.isoformat(),
            "min_order_size": 1,
        },
    }


def test_release1_migration_is_backward_compatible_and_additive(db: TrackerDatabase):
    with db.connection() as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        migration = conn.execute(
            "SELECT version FROM schema_migrations WHERE version = ?",
            (RELEASE1_MIGRATION_VERSION,),
        ).fetchone()
    assert {
        "candidate_ledger",
        "candidate_decisions",
        "candidate_monitoring",
        "dual_clv_measurements",
        "composite_price_snapshots",
        "composite_source_contributions",
        "model_versions",
    } <= tables
    assert migration[0] == RELEASE1_MIGRATION_VERSION
    assert "bet_tracker" in tables
    assert "personal_bet_fills" in tables


def test_release1_migration_preserves_existing_tracker_history(db: TrackerDatabase):
    historical = {
        "final_recommended_fraction": 0.01,
        "original_displayed_amount": 100.0,
        "event_title": "Historical recommendation",
    }
    with db.connection() as conn:
        conn.execute(
            """
            INSERT INTO bet_tracker(
                user_id, dedupe_key, snapshot_id, status, created_at,
                updated_at, snapshot_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-user", "legacy-key", "legacy-snapshot", "won",
                NOW.isoformat(), NOW.isoformat(), json.dumps(historical),
            ),
        )

    TrackerDatabase(db.path)

    with db.connection() as conn:
        preserved = conn.execute(
            "SELECT status, snapshot_json FROM bet_tracker WHERE dedupe_key = ?",
            ("legacy-key",),
        ).fetchone()
    assert preserved["status"] == "won"
    assert json.loads(preserved["snapshot_json"]) == historical


def test_approved_candidate_is_persisted_without_changing_live_decision(
    db: TrackerDatabase, temp_settings
):
    service = TrackerService(temp_settings, database=db, auto_start=False)
    candidate = play()
    evaluation = service.evaluate_recommendation(candidate, 10000, NOW)
    original_fraction = evaluation["recommendation"]["final_recommended_fraction"]
    record = build_candidate_record(candidate, evaluation, NOW.isoformat())

    stored = db.record_candidate(record)

    assert evaluation["model_tracker_eligible"] is True
    assert evaluation["recommendation"]["final_recommended_fraction"] == original_fraction
    assert stored["current_decision"] == CandidateDecision.APPROVED_STANDARD.value
    assert stored["snapshot"]["versions"]["trade_scoring"] == "trade-quality-v2"
    assert stored["snapshot"]["versions"]["fair_price"] == "fair-price-v3"
    assert stored["correlation_id"].startswith("corr_")


def test_passed_research_and_invalid_decisions_have_machine_reasons(
    db: TrackerDatabase, temp_settings
):
    service = TrackerService(temp_settings, database=db, auto_start=False)

    passed_play = play(event_id="passed-event")
    passed_play["orderbook"]["asks"] = []
    passed = build_candidate_record(
        passed_play,
        service.evaluate_recommendation(passed_play, 10000, NOW),
        NOW.isoformat(),
    )
    research_play = play(classification="SHARP_NON_CATEGORY", event_id="research-event")
    research = build_candidate_record(
        research_play,
        service.evaluate_recommendation(research_play, 10000, NOW),
        NOW.isoformat(),
    )
    invalid_play = play(event_id="invalid-event")
    invalid_play["validation_ids"]["condition_id"] = ""
    invalid_play["id"] = ""
    invalid = build_candidate_record(
        invalid_play,
        service.evaluate_recommendation(invalid_play, 10000, NOW),
        NOW.isoformat(),
    )

    assert passed["decision"] == CandidateDecision.PASSED.value
    assert passed["reason_codes"] == [CandidateReason.PROVIDER_DATA_UNAVAILABLE.value]
    assert research["decision"] == CandidateDecision.RESEARCH_ONLY.value
    assert research["reason_codes"] == [CandidateReason.RESEARCH_ONLY_NON_CATEGORY.value]
    assert invalid["decision"] == CandidateDecision.INVALID.value
    assert invalid["reason_codes"] == [CandidateReason.MARKET_MAPPING_UNCERTAIN.value]
    for record in (passed, research, invalid):
        db.record_candidate(record)
    assert len(db.get_monitorable_candidates()) == 2
    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM bet_tracker").fetchone()[0] == 0


def test_exclusion_ledger_preserves_pass_reason_and_skips_incomplete_identity():
    exclusion = {
        "reason": "BELOW_WALLET_ACTIONABLE_THRESHOLD",
        "event_id": "event-2",
        "condition_id": "market-2",
        "outcome_id": "token-2",
        "event_title": "Candidate event",
        "market_title": "Moneyline",
        "outcome": "Yes",
        "wallets": [{"wallet_address": "0xwallet"}],
    }
    record = build_exclusion_record(exclusion, NOW.isoformat())
    assert record is not None
    assert record["decision"] == CandidateDecision.PASSED.value
    assert record["reason_codes"] == [CandidateReason.BELOW_WALLET_ACTIONABLE_THRESHOLD.value]
    research = build_exclusion_record(
        {**exclusion, "reason": "NON_CATEGORY_CONSENSUS_RESEARCH_ONLY"},
        NOW.isoformat(),
    )
    assert research["decision"] == CandidateDecision.RESEARCH_ONLY.value
    assert research["reason_codes"] == [
        CandidateReason.RESEARCH_ONLY_NON_CATEGORY.value
    ]
    assert build_exclusion_record({"reason": "DUST"}, NOW.isoformat()) is None


def test_first_candidate_snapshot_is_immutable_but_decision_is_current(
    db: TrackerDatabase, temp_settings
):
    service = TrackerService(temp_settings, database=db, auto_start=False)
    candidate = play(event_id="immutable-event")
    approved = build_candidate_record(
        candidate,
        service.evaluate_recommendation(candidate, 10000, NOW),
        NOW.isoformat(),
    )
    db.record_candidate(approved)
    changed = dict(approved)
    changed["decision"] = CandidateDecision.PASSED.value
    changed["reason_codes"] = [CandidateReason.SLIPPAGE_ABOVE_LIMIT.value]
    changed["detected_at"] = (NOW + timedelta(minutes=1)).isoformat()
    changed["candidate_snapshot"] = {"should_not": "replace the original"}
    db.record_candidate(changed)
    stored = db.get_candidate(approved["candidate_id"])
    assert stored["current_decision"] == CandidateDecision.PASSED.value
    assert stored["snapshot"]["event"] == "Spain vs France"


def test_unavailable_composite_provider_never_fabricates_price(db: TrackerDatabase, temp_settings):
    service = TrackerService(temp_settings, database=db, auto_start=False)
    candidate = play(event_id="composite-event")
    record = build_candidate_record(
        candidate,
        service.evaluate_recommendation(candidate, 10000, NOW),
        NOW.isoformat(),
    )
    db.record_candidate(record)
    registry = CompositePriceProviderRegistry.release1_default()
    snapshot = unavailable_composite_snapshot(record, registry.health())
    assert snapshot["composite_fair_probability"] is None
    assert snapshot["source_count"] == 0
    assert snapshot["snapshot"]["fabricated_data"] is False
    assert all(item["included"] is False for item in snapshot["contributions"])
    assert db.insert_composite_price_snapshot(snapshot) is True
    assert db.insert_composite_price_snapshot(snapshot) is False


def test_passed_candidate_receives_separate_exchange_and_composite_clv(
    db: TrackerDatabase, temp_settings
):
    service = TrackerService(temp_settings, database=db, auto_start=False)
    candidate = play(event_id="passed-clv-event")
    candidate["orderbook"]["asks"] = [{"price": 0.5, "size": 10000}]
    candidate["orderbook"]["bids"] = [{"price": 0.49, "size": 10000}]
    record = build_candidate_record(
        candidate,
        service.evaluate_recommendation(candidate, 10000, NOW),
        NOW.isoformat(),
    )
    assert record["decision"] == CandidateDecision.PASSED.value
    db.record_candidate(record)
    reference = {
        "tracker_type": "candidate",
        "tracker_record_id": record["candidate_id"],
        "user_id": "__global_model_tracker__",
        "provider": "polymarket",
        "provider_event_id": record["canonical_event_id"],
        "provider_event_slug": candidate["event_slug"],
        "provider_market_id": record["canonical_market_id"],
        "provider_selection_id": record["canonical_outcome_id"],
        "selection": record["selection"],
        "event_start_time": record["event_start_time"],
        "entry_price": 0.5,
        "entry_stake": 100.0,
        "entry_timestamp": NOW.isoformat(),
    }
    quote = {
        "best_bid": 0.54,
        "best_ask": 0.55,
        "midpoint": 0.545,
        "last_trade": 0.54,
        "depth": [{"price": 0.55, "size": 10000}],
        "quote_timestamp": (NOW + timedelta(hours=2, minutes=59)).isoformat(),
        "source": "TEST_POLYMARKET_BOOK",
    }

    service._freeze_captured_clv(reference, quote, record["event_start_time"])
    details = db.get_candidate_measurements(record["candidate_id"])

    assert details["monitoring"]["exchange_clv_status"] == "captured"
    assert details["monitoring"]["composite_clv_status"] == "UNAVAILABLE"
    assert details["dual_clv"]["exchange_closing_price"] == 0.55
    assert details["dual_clv"]["composite_closing_probability"] is None
    assert details["dual_clv"]["composite_missing_reason"] == (
        "NO_CONNECTED_INDEPENDENT_COMPOSITE_PROVIDER"
    )


def test_passed_candidate_tracks_price_path_and_settlement(
    db: TrackerDatabase, temp_settings
):
    service = TrackerService(temp_settings, database=db, auto_start=False)
    service.client.get_order_books = lambda _ids: {}
    service.client.get_events = lambda _slugs: {}
    candidate = play(event_id="settled-passed-event")
    candidate["orderbook"]["asks"] = [{"price": 0.5, "size": 10000}]
    candidate["orderbook"]["bids"] = [{"price": 0.49, "size": 10000}]
    record = build_candidate_record(
        candidate,
        service.evaluate_recommendation(candidate, 10000, NOW),
        NOW.isoformat(),
    )
    db.record_candidate(record)
    db.record_candidate_price_observation(record["candidate_id"], 0.5, 0.57)
    db.record_candidate_price_observation(record["candidate_id"], 0.5, 0.43)
    event = {
        "closed": True,
        "ended": True,
        "gameStatus": "final",
        "finishedTimestamp": (NOW + timedelta(hours=5)).isoformat(),
        "markets": [
            {
                "conditionId": record["canonical_market_id"],
                "closed": True,
                "outcomes": ["Spain", "France"],
                "outcomePrices": ["1", "0"],
            }
        ],
    }

    service._update_tracker_statuses({candidate["event_slug"]: event})
    details = db.get_candidate_measurements(record["candidate_id"])

    assert details["monitoring"]["monitoring_status"] == "COMPLETE"
    assert details["monitoring"]["result"] == "Won"
    assert details["monitoring"]["hypothetical_profit_loss"] == 100.0
    assert details["monitoring"]["maximum_favorable_movement"] == pytest.approx(0.07)
    assert details["monitoring"]["maximum_adverse_movement"] == pytest.approx(-0.07)
    assert details["monitoring"]["pass_reason_justified"] == 0


def test_measurement_diagnostics_report_decisions_versions_and_monitoring(
    db: TrackerDatabase, temp_settings
):
    service = TrackerService(temp_settings, database=db, auto_start=False)
    candidate = play(event_id="diag-event")
    candidate["orderbook"]["asks"] = []
    record = build_candidate_record(
        candidate,
        service.evaluate_recommendation(candidate, 10000, NOW),
        NOW.isoformat(),
    )
    db.record_candidate(record)
    diagnostics = db.measurement_diagnostics()
    assert diagnostics["candidate_counts"]["PASSED"] == 1
    assert diagnostics["reason_counts"]["PROVIDER_DATA_UNAVAILABLE"] == 1
    assert diagnostics["monitoring"][0]["composite_clv_status"] == "UNAVAILABLE"
    assert any(row["component"] == "candidate_ledger" for row in diagnostics["versions"])


def test_admin_measurement_routes_require_authorization(app_client):
    assert app_client.get("/api/admin/measurement-foundation/diagnostics").status_code == 403
    assert app_client.get("/api/admin/candidate-ledger").status_code == 403


def test_admin_measurement_routes_return_diagnostics_and_candidate_detail(
    monkeypatch, temp_settings, db: TrackerDatabase
):
    import app as app_module

    service = TrackerService(temp_settings, database=db, auto_start=False)
    candidate = play(event_id="admin-diagnostic-event")
    candidate["orderbook"]["asks"] = []
    record = build_candidate_record(
        candidate,
        service.evaluate_recommendation(candidate, 10000, NOW),
        NOW.isoformat(),
    )
    db.record_candidate(record)
    admin_settings = replace(
        temp_settings, admin_password="release-one-admin"
    )
    monkeypatch.setattr(app_module, "get_settings", lambda: admin_settings)
    monkeypatch.setattr(
        app_module,
        "TrackerService",
        lambda _settings, auto_start=True: service,
    )
    client = app_module.create_app(start_background=False).test_client()

    assert client.post(
        "/api/admin/login", json={"password": "release-one-admin"}
    ).status_code == 200
    diagnostics = client.get(
        "/api/admin/measurement-foundation/diagnostics"
    ).get_json()["data"]
    ledger = client.get("/api/admin/candidate-ledger?decision=PASSED").get_json()
    detail = client.get(
        f"/api/admin/candidate-ledger/{record['candidate_id']}"
    ).get_json()["data"]

    assert diagnostics["release"] == "release-1-measurement-foundation"
    assert diagnostics["live_decision_logic_changed"] is False
    assert diagnostics["fabricated_provider_data"] is False
    assert diagnostics["table_counts"]["candidate_ledger"] == 1
    assert ledger["count"] == 1
    assert detail["candidate"]["candidate_id"] == record["candidate_id"]
    assert detail["decisions"][0]["reason_codes"] == [
        CandidateReason.PROVIDER_DATA_UNAVAILABLE.value
    ]
    assert detail["monitoring"]["composite_clv_status"] == "UNAVAILABLE"
