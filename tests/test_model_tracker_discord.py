from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

import model_tracker_discord as discord_module
from config import get_settings
from database import TrackerDatabase
from model_tracker_discord import (
    ICONLABS_PURPLE,
    THIRTY_MINUTE_CONTENT,
    DiscordDeliveryResult,
    DiscordNotificationDispatcher,
    ModelTrackerDiscordBot,
    build_discord_connection_test_payload,
    build_model_tracker_discord_payload,
    build_thirty_minute_checkpoint_discord_payload,
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
        "sportsbook": "Novig",
        "provider_display_odds": "+144",
        "provider_entry_price": 100 / 244,
        "provider_deep_link": "https://novig.com/events/example",
        "provider_logo_url": "https://cdn.example.com/novig.png",
        "sharp_reference_entry_price": 0.4046,
        "event_start_time": "2026-07-14T19:30:00+00:00",
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


def test_official_payload_names_execution_book_and_preserves_sharp_entry():
    payload = build_model_tracker_discord_payload(_snapshot())
    embed = payload["embeds"][0]
    fields = {field["name"]: field["value"] for field in embed["fields"]}

    assert "content" not in payload
    assert embed["title"] == "Example side Moneyline +144"
    assert "description" not in embed
    assert embed["url"] == "https://novig.com/events/example"
    assert embed["thumbnail"]["url"] == "https://cdn.example.com/novig.png"
    assert fields["BEST PRICE"] == "NoVIG +144 / 41.0c"
    assert fields["SHARP ENTRY"] == "40.5c"
    assert fields["STARTS"] == "July 14, 2026 at 3:30 PM"


def test_exchange_entry_falls_back_to_american_odds_without_mislabeled_link():
    snapshot = _snapshot()
    snapshot.pop("provider_display_odds")
    snapshot.pop("provider_deep_link")
    snapshot["provider_entry_price"] = 100 / 244

    payload = build_model_tracker_discord_payload(snapshot)
    embed = payload["embeds"][0]
    fields = {field["name"]: field["value"] for field in embed["fields"]}

    assert fields["BEST PRICE"] == "NoVIG +144 / 41.0c"
    assert "description" not in embed
    assert "url" not in embed


def test_profitx_embed_shows_american_odds_and_equivalent_cents():
    snapshot = _snapshot()
    snapshot["recommended_side"] = "Detroit Tigers"
    snapshot["sports_market_type"] = "moneyline"
    snapshot["sportsbook"] = "ProphetX"
    snapshot["provider_display_odds"] = "+111"
    snapshot["provider_entry_price"] = 100 / 211

    payload = build_model_tracker_discord_payload(snapshot)
    embed = payload["embeds"][0]
    fields = {field["name"]: field["value"] for field in embed["fields"]}

    assert "content" not in payload
    assert embed["title"] == "Detroit Tigers Moneyline +111"
    assert fields["BEST PRICE"] == "ProphetX +111 / 47.4c"


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


def test_missing_official_play_outbox_is_backfilled_once(tmp_path):
    database = TrackerDatabase(tmp_path / "tracker.db")
    snapshot = _snapshot()

    assert database.insert_tracker_snapshot(MODEL_TRACKER_USER_ID, snapshot)
    assert database.get_discord_notification(
        MODEL_TRACKER_USER_ID, snapshot["dedupe_key"]
    ) is None

    payload = build_model_tracker_discord_payload(snapshot)
    assert database.ensure_model_tracker_discord_notification(
        MODEL_TRACKER_USER_ID, snapshot, payload
    )
    assert not database.ensure_model_tracker_discord_notification(
        MODEL_TRACKER_USER_ID, snapshot, payload
    )
    notification = database.get_discord_notification(
        MODEL_TRACKER_USER_ID, snapshot["dedupe_key"]
    )
    assert notification["status"] == "pending"
    assert notification["payload"] == payload


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
        "checkpoint_channel_configured": False,
        "checkpoint_channel_name": "model-tracker-30m",
        "status": "authenticated",
    }


def test_all_discord_alert_embeds_use_iconlabs_purple():
    official = build_model_tracker_discord_payload(_snapshot())
    checkpoint = build_thirty_minute_checkpoint_discord_payload(
        {
            "snapshot_id": "a" * 64,
            "event_title": "Example event",
            "market_title": "Moneyline",
            "selection": "Example side",
            "price_at_two_hours": 0.4,
            "price_at_thirty_minutes": 0.42,
            "overall_verdict": "WEAKER",
            "recommendation_still_active": False,
            "checked_at": "2026-07-14T19:30:00+00:00",
        }
    )

    assert official["embeds"][0]["color"] == ICONLABS_PURPLE
    assert checkpoint["embeds"][0]["color"] == ICONLABS_PURPLE
    assert "not canceled" in checkpoint["embeds"][0]["description"]


def test_checkpoint_alert_is_private_and_never_sent(monkeypatch):
    calls: list[tuple[str, str, dict]] = []

    def fake_get(url, **kwargs):
        calls.append(("GET", url, kwargs))
        if url.endswith("/guilds/guild-1/channels"):
            return FakeResponse(200, [])
        return FakeResponse(200, {"guild_id": "guild-1"})

    def fake_post(url, **kwargs):
        calls.append(("POST", url, kwargs))
        if url.endswith("/guilds/guild-1/channels"):
            return FakeResponse(201, {"id": "channel-30m"})
        return FakeResponse(200, {"id": "checkpoint-message"})

    monkeypatch.setattr(discord_module.requests, "get", fake_get)
    monkeypatch.setattr(discord_module.requests, "post", fake_post)
    bot = ModelTrackerDiscordBot(
        token="secret-token",
        guild_id="guild-1",
        channel_id="channel-main",
        enabled=True,
    )
    payload = {
        "content": THIRTY_MINUTE_CONTENT,
        "embeds": [{"color": ICONLABS_PURPLE}],
        "allowed_mentions": {"parse": []},
    }

    result = bot.send(payload)

    assert result.delivered is False
    assert result.error_code == "private_only"
    assert result.terminal is True
    assert calls == []


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


def test_final_thirty_minute_model_play_tracks_and_dispatches_once(
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
    now = datetime(2026, 7, 14, 19, 0, tzinfo=timezone.utc)
    play = {
        "id": "approved-trade",
        "event_title": "Example event",
        "event_date_et": "2026-07-14T15:30:00-04:00",
    }

    personal = service.reconcile_user_tracker("personal-user", 10000, [play])
    first = service.reconcile_model_tracker([play], now)
    repeated = service.reconcile_model_tracker([play], now)

    assert personal["inserted"] == 1
    assert db.get_discord_notification("personal-user", snapshot["dedupe_key"]) is None
    assert first["recommendations_evaluated"] == 1
    assert first["deferred_until_pregame"] == 0
    assert first["records_inserted"] == 1
    assert first["discord_notifications"]["delivered"] == 1
    assert repeated["records_skipped_duplicates"] == 1
    assert repeated["discord_notifications"]["delivered"] == 0
    assert len(bot.payloads) == 1


def test_existing_official_play_without_outbox_is_repaired_and_dispatched(
    temp_settings, db, monkeypatch
):
    settings = replace(temp_settings, discord_notifications_enabled=True)
    bot = FakeBot()
    service = TrackerService(
        settings, database=db, model_discord_bot=bot, auto_start=False
    )
    snapshot = _snapshot()
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
    now = datetime(2026, 7, 14, 19, 0, tzinfo=timezone.utc)
    play = {
        "id": "existing-approved-trade",
        "event_title": "Example event",
        "event_date_et": "2026-07-14T15:30:00-04:00",
    }

    repaired = service.reconcile_model_tracker([play], now)
    repeated = service.reconcile_model_tracker([play], now)

    assert repaired["records_inserted"] == 0
    assert repaired["records_skipped_duplicates"] == 1
    assert repaired["discord_notifications"]["delivered"] == 1
    assert repeated["discord_notifications"]["delivered"] == 0
    assert len(bot.payloads) == 1
