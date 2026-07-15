from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

import model_tracker_discord as discord_module
from config import get_settings
from database import TrackerDatabase
from model_tracker_discord import (
    DiscordDeliveryResult,
    DiscordNotificationDispatcher,
    ModelTrackerDiscordBot,
    build_discord_connection_test_payload,
    build_model_tracker_discord_payload,
)
from position_tracker import MODEL_TRACKER_USER_ID, TrackerService


def _snapshot(dedupe_key: str = "event::market::::outcome::v2") -> dict:
    return {
        "snapshot_id": "a" * 64,
        "dedupe_key": dedupe_key,
        "recommendation_timestamp": "2026-07-14T18:00:00+00:00",
        "event_start_time": "Jul 14, 2026, 8:00 PM ET",
        "final_recommended_fraction": 0.01,
        "original_displayed_amount": 100,
        "original_recommended_units": 1,
        "current_executable_entry_price": 0.4,
        "confidence_score": 84,
        "event_title": "Example event",
        "market_title": "Moneyline",
        "recommended_side": "Example side",
        "market_url": "https://polymarket.com/event/example",
    }


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class FakeBot:
    enabled = True
    configured = True

    def __init__(self, results: list[DiscordDeliveryResult] | None = None) -> None:
        self.results = list(results or [DiscordDeliveryResult(True, "message-1", 200)])
        self.payloads: list[dict] = []

    def safe_configuration(self) -> dict[str, bool]:
        return {"enabled": True, "configured": True}

    def validate_connection(self):
        return None

    def send(self, payload: dict) -> DiscordDeliveryResult:
        self.payloads.append(payload)
        return self.results.pop(0)


def test_bot_configuration_reads_exact_server_environment_names(monkeypatch, tmp_path):
    token = "never-print-this-token"
    monkeypatch.setenv("DISCORD_BOT_TOKEN", token)
    monkeypatch.setenv("DISCORD_GUILD_ID", "guild-1")
    monkeypatch.setenv("DISCORD_TRADE_CHANNEL_ID", "channel-1")
    monkeypatch.setenv("DISCORD_NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "tracker.db"))

    settings = get_settings()

    assert settings.discord_bot_token == token
    assert settings.discord_guild_id == "guild-1"
    assert settings.discord_trade_channel_id == "channel-1"
    assert settings.discord_notifications_enabled is True
    assert token not in repr(settings)


def test_connection_test_payload_is_labeled_and_deduplicated():
    payload = build_discord_connection_test_payload("commit-sha-for-test-message")

    assert payload["content"] == "IconBets Discord connection test"
    assert payload["embeds"][0]["footer"]["text"].endswith("Test message")
    assert payload["allowed_mentions"] == {"parse": []}
    assert len(payload["nonce"]) <= 25
    assert payload["enforce_nonce"] is True


def test_tracker_insert_and_discord_outbox_are_atomic_and_deduplicated(tmp_path):
    database = TrackerDatabase(tmp_path / "tracker.db")
    snapshot = _snapshot()
    payload = build_model_tracker_discord_payload(snapshot)

    assert database.insert_tracker_snapshot(
        MODEL_TRACKER_USER_ID, snapshot, discord_payload=payload
    )
    assert not database.insert_tracker_snapshot(
        MODEL_TRACKER_USER_ID, snapshot, discord_payload=payload
    )

    notification = database.get_discord_notification(
        MODEL_TRACKER_USER_ID, snapshot["dedupe_key"]
    )
    assert notification["status"] == "pending"
    assert notification["attempts"] == 0
    assert database.get_discord_notification_stats()["pending"] == 1


def test_personal_tracker_insert_does_not_create_discord_job(tmp_path):
    database = TrackerDatabase(tmp_path / "tracker.db")
    snapshot = _snapshot()

    assert database.insert_tracker_snapshot("personal-user", snapshot)
    assert database.get_discord_notification("personal-user", snapshot["dedupe_key"]) is None


def test_bot_validates_guild_and_posts_with_mentions_disabled(monkeypatch):
    calls: dict[str, dict] = {}

    def fake_get(url, **kwargs):
        calls["get"] = {"url": url, **kwargs}
        return FakeResponse(200, {"guild_id": "guild-1"})

    def fake_post(url, **kwargs):
        calls["post"] = {"url": url, **kwargs}
        return FakeResponse(200, {"id": "discord-message-1"})

    monkeypatch.setattr(discord_module.requests, "get", fake_get)
    monkeypatch.setattr(discord_module.requests, "post", fake_post)
    bot = ModelTrackerDiscordBot(
        token="secret-token",
        guild_id="guild-1",
        channel_id="channel-1",
        enabled=True,
    )
    payload = build_model_tracker_discord_payload(_snapshot())

    result = bot.send(payload)

    assert result.delivered is True
    assert result.message_id == "discord-message-1"
    assert calls["post"]["json"]["allowed_mentions"] == {"parse": []}
    assert calls["post"]["json"]["enforce_nonce"] is True
    assert calls["get"]["url"].endswith("/channels/channel-1")
    assert calls["post"]["url"].endswith("/channels/channel-1/messages")
    assert bot.safe_configuration() == {
        "enabled": True,
        "configured": True,
        "status": "authenticated",
    }


def test_bot_refuses_channel_from_another_guild(monkeypatch):
    monkeypatch.setattr(
        discord_module.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(200, {"guild_id": "wrong-guild"}),
    )
    monkeypatch.setattr(
        discord_module.requests,
        "post",
        lambda *args, **kwargs: pytest.fail("message must not be sent"),
    )
    bot = ModelTrackerDiscordBot(
        token="secret-token",
        guild_id="guild-1",
        channel_id="channel-1",
        enabled=True,
    )

    result = bot.send(build_model_tracker_discord_payload(_snapshot()))

    assert result.delivered is False
    assert result.error_code == "guild_mismatch"
    assert result.terminal is False
    assert bot.safe_configuration()["status"] == "unauthorized"


def test_dispatcher_stores_delivery_and_retry_results(tmp_path):
    database = TrackerDatabase(tmp_path / "tracker.db")
    first = _snapshot("event::first::::outcome::v2")
    second = {**_snapshot("event::second::::outcome::v2"), "snapshot_id": "b" * 64}
    database.insert_tracker_snapshot(
        MODEL_TRACKER_USER_ID,
        first,
        discord_payload=build_model_tracker_discord_payload(first),
    )
    database.insert_tracker_snapshot(
        MODEL_TRACKER_USER_ID,
        second,
        discord_payload=build_model_tracker_discord_payload(second),
    )
    bot = FakeBot(
        [
            DiscordDeliveryResult(True, "message-1", 200),
            DiscordDeliveryResult(False, error_code="connection_failed"),
        ]
    )

    result = DiscordNotificationDispatcher(database, bot).dispatch_pending()

    assert result == {"claimed": 2, "delivered": 1, "failed": 0, "retrying": 1}
    assert database.get_discord_notification(
        MODEL_TRACKER_USER_ID, first["dedupe_key"]
    )["status"] == "delivered"
    retry = database.get_discord_notification(
        MODEL_TRACKER_USER_ID, second["dedupe_key"]
    )
    assert retry["status"] == "retry"
    assert retry["last_error"] == "connection_failed"
    assert retry["next_attempt_at"] is not None


def test_model_reconcile_dispatches_once_and_personal_reconcile_never_enqueues(
    temp_settings, db, monkeypatch
):
    settings = replace(temp_settings, discord_notifications_enabled=True)
    bot = FakeBot()
    service = TrackerService(
        settings, database=db, model_discord_bot=bot, auto_start=False
    )
    snapshot = _snapshot()

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
    play = {"id": "approved-trade", "event_title": "Example event"}

    personal = service.reconcile_user_tracker("personal-user", 10000, [play])
    first = service.reconcile_model_tracker([play], datetime.now(timezone.utc))
    repeated = service.reconcile_model_tracker([play], datetime.now(timezone.utc))

    assert personal["inserted"] == 1
    assert db.get_discord_notification("personal-user", snapshot["dedupe_key"]) is None
    assert first["records_inserted"] == 1
    assert first["discord_notifications"]["delivered"] == 1
    assert repeated["records_skipped_duplicates"] == 1
    assert repeated["discord_notifications"]["delivered"] == 0
    assert len(bot.payloads) == 1
