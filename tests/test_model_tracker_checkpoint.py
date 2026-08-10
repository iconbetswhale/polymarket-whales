from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from database import TrackerDatabase
from model_tracker_checkpoint import (
    build_thirty_minute_checkpoint,
    timing_outlook,
)
from model_tracker_discord import (
    DiscordDeliveryResult,
    build_thirty_minute_checkpoint_discord_payload,
)
from position_tracker import MODEL_TRACKER_USER_ID, TrackerService


EVENT_ID = "event-1"
MARKET_ID = "market-1"
OUTCOME_ID = "outcome-1"
WALLET_A = "0xaaa"
WALLET_B = "0xbbb"


class FakeBot:
    enabled = True
    configured = True

    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def safe_configuration(self) -> dict:
        return {"enabled": True, "configured": True}

    def validate_connection(self):
        return None

    def send(self, payload: dict) -> DiscordDeliveryResult:
        self.payloads.append(payload)
        return DiscordDeliveryResult(True, f"message-{len(self.payloads)}", 200)


def _snapshot(
    *,
    event_start: datetime,
    recommendation_time: datetime,
) -> dict:
    return {
        "snapshot_id": "c" * 64,
        "dedupe_key": "event-1::market-1::::outcome-1::v2",
        "recommendation_timestamp": recommendation_time.isoformat(),
        "event_start_time": event_start.isoformat(),
        "final_recommended_fraction": 0.01,
        "original_displayed_amount": 100.0,
        "original_recommended_units": 1.0,
        "current_executable_entry_price": 0.50,
        "confidence_score": 82,
        "event_title": "Seattle Mariners vs Texas Rangers",
        "market_title": "Moneyline",
        "recommended_side": "Seattle Mariners",
        "sportsbook": "NoVig",
        "canonical_event_id": EVENT_ID,
        "canonical_market_id": MARKET_ID,
        "outcome_id": OUTCOME_ID,
        "market_line": None,
        "weighted_sharp_count": 1.0,
        "agreeing_wallet_ids": [WALLET_A],
        "lead_wallet_ids": [WALLET_A],
        "supporting_wallet_ids": [],
        "sharp_snapshot": {"contradicting_wallet_ids": []},
    }


def _play(
    *,
    price: float = 0.48,
    agreeing: list[str] | None = None,
    opposing: list[str] | None = None,
) -> dict:
    return {
        "id": "play-1",
        "event_title": "Seattle Mariners vs Texas Rangers",
        "event_date_et": "2026-07-27T20:00:00-04:00",
        "validation_ids": {
            "event_id": EVENT_ID,
            "condition_id": MARKET_ID,
            "outcome": OUTCOME_ID,
        },
        "clob_token_id": OUTCOME_ID,
        "market_line": None,
        "agreeingWalletIds": agreeing or [WALLET_A],
        "contradictingWalletIds": opposing or [],
        "weighted_sharp_count": 1.5 if agreeing and WALLET_B in agreeing else 1.0,
        "weightedDirectionalOpposition": 0.5 if opposing else 0.0,
        "lead_sharp_count": 1,
        "supporting_sharp_count": 1 if agreeing and WALLET_B in agreeing else 0,
        "confidence_score": 86,
        "executionOptions": [
            {
                "providerName": "NoVig",
                "bestExecutablePrice": price,
                "isAvailable": True,
                "matchingConfidence": "Exact",
                "isBestPrice": True,
                "isStale": False,
                "marketStatus": "OPEN",
            }
        ],
    }


def test_checkpoint_compares_price_and_new_sharp_evidence():
    checked_at = datetime(2026, 7, 28, 0, 30, tzinfo=timezone.utc)
    snapshot = _snapshot(
        event_start=checked_at + timedelta(minutes=30),
        recommendation_time=checked_at - timedelta(minutes=90),
    )
    record = {
        "dedupe_key": snapshot["dedupe_key"],
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot": snapshot,
    }

    checkpoint = build_thirty_minute_checkpoint(
        record,
        [_play(price=0.48, agreeing=[WALLET_A, WALLET_B])],
        checked_at,
    )

    assert checkpoint["price_verdict"] == "BETTER_AT_30_MINUTES"
    assert checkpoint["price_delta_cents"] == -2.0
    assert checkpoint["sharp_verdict"] == "SUPPORT_STRENGTHENED"
    assert checkpoint["overall_verdict"] == "IMPROVED"
    assert checkpoint["new_supporting_wallet_ids"] == [WALLET_B]
    assert checkpoint["official_model_entry_unchanged"] is True


def test_checkpoint_warns_on_new_opposition_and_missing_play():
    checked_at = datetime(2026, 7, 28, 0, 30, tzinfo=timezone.utc)
    snapshot = _snapshot(
        event_start=checked_at + timedelta(minutes=30),
        recommendation_time=checked_at - timedelta(minutes=90),
    )
    record = {
        "dedupe_key": snapshot["dedupe_key"],
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot": snapshot,
    }

    opposed = build_thirty_minute_checkpoint(
        record,
        [_play(price=0.51, opposing=[WALLET_B])],
        checked_at,
    )
    missing = build_thirty_minute_checkpoint(record, [], checked_at)

    assert opposed["price_verdict"] == "WORSE_AT_30_MINUTES"
    assert opposed["sharp_verdict"] == "OPPOSITION_ADDED"
    assert opposed["overall_verdict"] == "CAUTION"
    assert opposed["new_opposing_wallet_ids"] == [WALLET_B]
    assert missing["recommendation_still_active"] is False
    assert missing["overall_verdict"] == "NO_LONGER_RECOMMENDED"


def test_checkpoint_storage_and_discord_outbox_are_atomic(tmp_path):
    database = TrackerDatabase(tmp_path / "tracker.db")
    checked_at = datetime(2026, 7, 28, 0, 30, tzinfo=timezone.utc)
    snapshot = _snapshot(
        event_start=checked_at + timedelta(minutes=30),
        recommendation_time=checked_at - timedelta(minutes=90),
    )
    assert database.insert_tracker_snapshot(MODEL_TRACKER_USER_ID, snapshot)
    record = database.get_tracker_record(
        MODEL_TRACKER_USER_ID, snapshot["dedupe_key"]
    )
    checkpoint = build_thirty_minute_checkpoint(record, [_play()], checked_at)
    payload = build_thirty_minute_checkpoint_discord_payload(checkpoint)

    assert database.insert_tracker_checkpoint(
        MODEL_TRACKER_USER_ID, snapshot["dedupe_key"], checkpoint, payload
    )
    assert not database.insert_tracker_checkpoint(
        MODEL_TRACKER_USER_ID, snapshot["dedupe_key"], checkpoint, payload
    )
    stored = database.get_tracker_record(
        MODEL_TRACKER_USER_ID, snapshot["dedupe_key"]
    )
    with database.connection() as connection:
        notifications = connection.execute(
            """
            SELECT notification_type
            FROM discord_trade_notifications
            WHERE user_id = ? AND dedupe_key = ?
            """,
            (MODEL_TRACKER_USER_ID, snapshot["dedupe_key"]),
        ).fetchall()

    assert stored["thirty_minute_checkpoint"]["price_at_thirty_minutes"] == 0.48
    assert [row["notification_type"] for row in notifications] == [
        "model_tracker_30m_update"
    ]


def test_reconcile_does_not_create_retired_checkpoint_or_discord_update(
    temp_settings, db, monkeypatch
):
    settings = replace(temp_settings, discord_notifications_enabled=True)
    bot = FakeBot()
    service = TrackerService(
        settings, database=db, model_discord_bot=bot, auto_start=False
    )
    event_start = datetime(2026, 7, 28, 1, 0, tzinfo=timezone.utc)
    recommendation_time = event_start - timedelta(hours=2)
    snapshot = _snapshot(
        event_start=event_start,
        recommendation_time=recommendation_time,
    )
    assert db.insert_tracker_snapshot(MODEL_TRACKER_USER_ID, snapshot)
    monkeypatch.setattr(
        service,
        "evaluate_recommendation",
        lambda play, bankroll, now=None: {
            "model_tracker_rejection_reason": None,
            "model_tracker_eligible": True,
            "recommendation_idempotency_key": snapshot["dedupe_key"],
            "snapshot": snapshot,
        },
    )

    too_early = service.reconcile_model_tracker(
        [_play()], event_start - timedelta(minutes=31)
    )
    first = service.reconcile_model_tracker(
        [_play()], event_start - timedelta(minutes=30)
    )
    repeated = service.reconcile_model_tracker(
        [_play()], event_start - timedelta(minutes=25)
    )
    records = db.get_tracker_records(MODEL_TRACKER_USER_ID)

    assert "thirty_minute_checkpoints_inserted" not in too_early
    assert "thirty_minute_checkpoints_inserted" not in first
    assert "thirty_minute_checkpoints_inserted" not in repeated
    assert len(records) == 1
    assert records[0]["status"] == "scheduled"
    assert records[0]["result"] is None
    assert records[0]["thirty_minute_checkpoint"] is None
    assert bot.payloads == []


def test_timing_outlook_uses_lower_cost_as_better_and_does_not_invent_results():
    rows = []
    for index in range(10):
        price_30m = 0.48 if index < 7 else 0.52
        rows.append(
            {
                "status": "scheduled",
                "snapshot": {"original_displayed_amount": 100},
                "thirty_minute_checkpoint": {
                    "price_at_two_hours": 0.50,
                    "price_at_thirty_minutes": price_30m,
                    "price_delta_cents": (price_30m - 0.50) * 100,
                    "recommendation_still_active": True,
                    "sharp_verdict": "UNCHANGED",
                },
            }
        )

    outlook = timing_outlook(rows)

    assert outlook["better_at_thirty_minutes"] == 7
    assert outlook["worse_at_thirty_minutes"] == 3
    assert outlook["entry_window_recommendation"] == "THIRTY_MINUTES_LEAN"
    assert outlook["settled_comparison_count"] == 0
    assert outlook["fixed_stake_pnl_delta_if_waited"] == 0.0
