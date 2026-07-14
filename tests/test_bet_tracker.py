from __future__ import annotations

import copy

import pytest

import database as database_module
from bet_tracker import recommendation_snapshot, replay_tracker
from database import TrackerDatabase


def _snapshot(fraction=0.02, entry=0.4):
    return {
        "snapshot_id": "snapshot-1",
        "dedupe_key": "event::market::yes::v1",
        "recommendation_timestamp": "2026-07-13T12:00:00+00:00",
        "event_start_time": "2026-07-13T20:00:00+00:00",
        "final_recommended_fraction": fraction,
        "effective_entry_price": entry,
        "event_title": "Example event",
        "recommended_side": "Yes",
    }


def test_tracker_snapshot_insert_is_deduplicated_and_immutable(tmp_path):
    database = TrackerDatabase(tmp_path / "tracker.db")
    original = _snapshot()

    assert database.insert_tracker_snapshot("user-1", original) is True
    changed = copy.deepcopy(original)
    changed["effective_entry_price"] = 0.9
    assert database.insert_tracker_snapshot("user-1", changed) is False

    stored = database.get_tracker_records("user-1")[0]["snapshot"]
    assert stored["effective_entry_price"] == 0.4


def test_tracker_rejects_near_zero_recommendation(tmp_path):
    database = TrackerDatabase(tmp_path / "tracker.db")
    snapshot = _snapshot(5e-17, 0.94)
    snapshot["original_displayed_amount"] = 5e-13

    assert database.insert_tracker_snapshot("user-1", snapshot) is False
    assert database.get_tracker_records("user-1") == []


def test_existing_user_records_promote_to_one_global_ledger_without_deletion(tmp_path):
    database = TrackerDatabase(tmp_path / "tracker.db")
    first = _snapshot()
    second = copy.deepcopy(first)
    second["snapshot_id"] = "snapshot-2"
    second["dedupe_key"] = "event-2::market-2::::outcome-2::v2"
    assert database.insert_tracker_snapshot("user-1", first) is True
    assert database.insert_tracker_snapshot("user-2", first) is True
    assert database.insert_tracker_snapshot("user-2", second) is True

    promoted = database.promote_tracker_records_to_global("global-model")

    assert promoted == 2
    assert len(database.get_tracker_records("global-model")) == 2
    assert len(database.get_tracker_records("user-1")) == 1
    assert len(database.get_tracker_records("user-2")) == 2
    assert database.promote_tracker_records_to_global("global-model") == 0


def test_durable_store_receives_user_owned_tracker_data(tmp_path, monkeypatch):
    class FakeDurableStore:
        def __init__(self, database_url):
            self.database_url = database_url
            self.records = []

        def insert_tracker_snapshot(self, user_id, snapshot, status):
            self.records.append((user_id, copy.deepcopy(snapshot), status))
            return True

        def get_tracker_records(self, user_id):
            return [
                {
                    "dedupe_key": snapshot["dedupe_key"],
                    "snapshot_id": snapshot["snapshot_id"],
                    "status": status,
                    "result": None,
                    "settled_at": None,
                    "created_at": snapshot["recommendation_timestamp"],
                    "updated_at": snapshot["recommendation_timestamp"],
                    "snapshot": snapshot,
                }
                for owner, snapshot, status in self.records
                if owner == user_id
            ]

        def health(self):
            return {"backend": "postgresql", "persistent": True, "status": "ok"}

    monkeypatch.setattr(database_module, "PostgresUserStore", FakeDurableStore)
    database = TrackerDatabase(
        tmp_path / "tracker.db", "postgresql://durable.example/iconbets"
    )

    assert database.insert_tracker_snapshot("user-1", _snapshot()) is True
    assert database.get_tracker_records("user-1")[0]["snapshot_id"] == "snapshot-1"
    health = database.health()
    assert health["user_data_persistent"] is True
    assert health["durable_user_store"]["status"] == "ok"


def test_replay_uses_frozen_percentage_and_effective_entry():
    records = [
        {
            "status": "won",
            "settled_at": "2026-07-14T00:00:00Z",
            "snapshot": _snapshot(0.02, 0.4),
        },
        {
            "status": "lost",
            "settled_at": "2026-07-15T00:00:00Z",
            "snapshot": {
                **_snapshot(0.01, 0.5),
                "recommendation_timestamp": "2026-07-14T12:00:00Z",
            },
        },
    ]

    replay = replay_tracker(records, 10000)

    first_profit = 200 * ((1 / 0.4) - 1)
    bankroll_after_first = 10000 + first_profit
    second_loss = bankroll_after_first * 0.01
    assert replay["rows"][0]["recommended_amount"] == pytest.approx(200)
    assert replay["rows"][0]["profit_loss"] == pytest.approx(first_profit)
    assert replay["summary"]["current_bankroll"] == pytest.approx(
        bankroll_after_first - second_loss
    )


def test_open_bets_do_not_change_realized_profit():
    replay = replay_tracker(
        [{"status": "live", "settled_at": None, "snapshot": _snapshot()}], 10000
    )

    assert replay["summary"]["realized_profit_loss"] == 0
    assert replay["summary"]["open_exposure"] == pytest.approx(200)
    assert replay["rows"][0]["profit_loss"] is None


def test_recommendation_snapshot_keeps_sharp_and_user_entries_separate():
    play = {
        "id": "market::yes",
        "event_slug": "event",
        "event_title": "Event",
        "market_title": "Market",
        "outcome": "Yes",
        "clob_token_id": "token-yes",
        "average_entry_price": 0.42,
        "raw_sharp_count": 2,
        "lead_sharp_count": 1,
        "supporting_sharp_count": 1,
        "weighted_sharp_count": 1.5,
        "has_lead_sharp": True,
        "lead_wallet_ids": ["0xlead"],
        "supporting_wallet_ids": ["0xsupport"],
        "primary_lead_wallet_id": "0xlead",
        "category_weight_by_wallet": {"0xlead": 1.0, "0xsupport": 0.5},
        "validation_ids": {
            "event_id": "1",
            "condition_id": "condition",
            "market_slug": "market",
        },
        "supporting_wallets": [],
    }
    recommendation = {
        "recommendation_version": "v1",
        "current_user_entry_price": 0.5,
        "effective_entry_price": 0.5,
        "sharp_average_entry_price": 0.42,
        "final_recommended_fraction": 0.01,
        "recommended_amount": 100,
        "recommended_units": 1,
        "category_weighting": "Lead 1.0x, Supporting 0.5x",
    }

    snapshot = recommendation_snapshot(play, recommendation, 10000)

    assert snapshot["current_executable_entry_price"] == 0.5
    assert snapshot["sharp_average_entry_price"] == 0.42
    assert snapshot["raw_sharp_count"] == 2
    assert snapshot["lead_sharp_count"] == 1
    assert snapshot["supporting_sharp_count"] == 1
    assert snapshot["weighted_sharp_count"] == 1.5
    assert snapshot["primary_lead_wallet_id"] == "0xlead"
    assert snapshot["category_weight_by_wallet"]["0xsupport"] == 0.5
