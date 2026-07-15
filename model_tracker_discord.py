from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from config import Settings

LOGGER = logging.getLogger(__name__)
DISCORD_API_BASE_URL = "https://discord.com/api/v10"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _truncate(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(limit - 3, 0)]}..."


def _money(value: Any) -> str:
    return f"${_safe_float(value):,.2f}"


def _entry_price(value: Any) -> str:
    price = _safe_float(value, -1)
    return "Unavailable" if price < 0 else f"{price * 100:.1f}c"


def build_model_tracker_discord_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Format an already-approved Model Tracker snapshot for Discord."""
    event_title = _truncate(snapshot.get("event_title") or "New model trade", 256)
    selection = _truncate(snapshot.get("recommended_side") or "Unknown", 1024)
    market_title = _truncate(snapshot.get("market_title") or "Market", 1024)
    amount = _safe_float(snapshot.get("original_displayed_amount"))
    fraction = _safe_float(snapshot.get("final_recommended_fraction"))
    units = _safe_float(snapshot.get("original_recommended_units"))
    confidence = _safe_float(snapshot.get("confidence_score"))
    market_url = str(snapshot.get("market_url") or "").strip()
    description = f"**{market_title}**"
    if market_url.startswith(("https://", "http://")):
        description += f"\n\n[Open exact Polymarket market]({market_url})"

    fields = [
        {"name": "Selection", "value": selection, "inline": True},
        {
            "name": "Entry",
            "value": _entry_price(snapshot.get("current_executable_entry_price")),
            "inline": True,
        },
        {
            "name": "Recommended stake",
            "value": f"{_money(amount)} | {fraction * 100:.2f}%",
            "inline": True,
        },
    ]
    if units > 0:
        fields.append(
            {"name": "Units", "value": f"{units:.2f}u", "inline": True}
        )
    if confidence > 0:
        fields.append(
            {"name": "Confidence", "value": f"{confidence:.0f}", "inline": True}
        )
    if snapshot.get("event_start_time"):
        fields.append(
            {
                "name": "Starts",
                "value": _truncate(snapshot.get("event_start_time"), 1024),
                "inline": True,
            }
        )

    snapshot_id = str(snapshot.get("snapshot_id") or "")
    embed: dict[str, Any] = {
        "title": event_title,
        "description": description,
        "color": int("D6AA50", 16),
        "fields": fields,
        "footer": {"text": "Icon Labs Model Tracker"},
    }
    timestamp = str(snapshot.get("recommendation_timestamp") or "").strip()
    if timestamp:
        embed["timestamp"] = timestamp
    payload = {
        "content": "New Model Tracker recommendation",
        "embeds": [embed],
        "allowed_mentions": {"parse": []},
    }
    if snapshot_id:
        payload["nonce"] = snapshot_id[:25]
        payload["enforce_nonce"] = True
    return payload


@dataclass(frozen=True)
class DiscordDeliveryResult:
    delivered: bool
    message_id: str | None = None
    status_code: int | None = None
    error_code: str | None = None
    retry_after_seconds: float | None = None
    terminal: bool = False


class ModelTrackerDiscordBot:
    def __init__(
        self,
        *,
        token: str | None,
        guild_id: str | None,
        channel_id: str | None,
        enabled: bool,
        timeout: int = 10,
    ) -> None:
        self._token = token
        self._guild_id = guild_id
        self._channel_id = channel_id
        self.enabled = enabled
        self.timeout = timeout
        self._channel_validated = False
        self._connection_status = (
            "disabled"
            if not enabled
            else "configured"
            if self.configured
            else "not configured"
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "ModelTrackerDiscordBot":
        return cls(
            token=settings.discord_bot_token,
            guild_id=settings.discord_guild_id,
            channel_id=settings.discord_trade_channel_id,
            enabled=settings.discord_notifications_enabled,
            timeout=min(max(settings.request_timeout, 1), 5),
        )

    @property
    def configured(self) -> bool:
        return bool(self._token and self._guild_id and self._channel_id)

    def safe_configuration(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "configured": self.configured,
            "status": self._connection_status,
        }

    def _record_connection_failure(
        self, result: DiscordDeliveryResult
    ) -> DiscordDeliveryResult:
        if result.error_code in {
            "unauthorized",
            "forbidden",
            "channel_not_found",
            "guild_mismatch",
        }:
            self._connection_status = "unauthorized"
        else:
            self._connection_status = "connection failed"
        return result

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bot {self._token}",
            "Content-Type": "application/json",
            "User-Agent": "IconLabsModelTracker/1.0",
        }

    @staticmethod
    def _failure(response: requests.Response) -> DiscordDeliveryResult:
        status = response.status_code
        if status == 429:
            try:
                retry_after = float(response.json().get("retry_after") or 5)
            except (TypeError, ValueError):
                retry_after = 5
            return DiscordDeliveryResult(
                False,
                status_code=status,
                error_code="rate_limited",
                retry_after_seconds=max(retry_after, 1),
            )
        codes = {
            400: "invalid_message",
            401: "unauthorized",
            403: "forbidden",
            404: "channel_not_found",
        }
        error_code = codes.get(
            status,
            "discord_server_error" if status >= 500 else "discord_request_failed",
        )
        return DiscordDeliveryResult(
            False,
            status_code=status,
            error_code=error_code,
            terminal=status == 400,
        )

    def _validate_channel(self) -> DiscordDeliveryResult | None:
        if self._channel_validated:
            return None
        try:
            response = requests.get(
                f"{DISCORD_API_BASE_URL}/channels/{self._channel_id}",
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException:
            return self._record_connection_failure(
                DiscordDeliveryResult(False, error_code="connection_failed")
            )
        if response.status_code != 200:
            return self._record_connection_failure(self._failure(response))
        try:
            channel_guild_id = str(response.json().get("guild_id") or "")
        except ValueError:
            return self._record_connection_failure(
                DiscordDeliveryResult(False, error_code="invalid_channel_response")
            )
        if channel_guild_id != str(self._guild_id):
            return self._record_connection_failure(
                DiscordDeliveryResult(False, error_code="guild_mismatch")
            )
        self._channel_validated = True
        self._connection_status = "authenticated"
        return None

    def validate_connection(self) -> DiscordDeliveryResult | None:
        if not self.enabled:
            self._connection_status = "disabled"
            return DiscordDeliveryResult(False, error_code="disabled", terminal=True)
        if not self.configured:
            self._connection_status = "not configured"
            return DiscordDeliveryResult(False, error_code="not_configured")
        return self._validate_channel()

    def send(self, payload: dict[str, Any]) -> DiscordDeliveryResult:
        validation_failure = self.validate_connection()
        if validation_failure:
            return validation_failure
        try:
            response = requests.post(
                f"{DISCORD_API_BASE_URL}/channels/{self._channel_id}/messages",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException:
            return DiscordDeliveryResult(False, error_code="connection_failed")
        if response.status_code not in {200, 201}:
            return self._failure(response)
        try:
            message_id = str(response.json().get("id") or "") or None
        except ValueError:
            message_id = None
        return DiscordDeliveryResult(
            True, message_id=message_id, status_code=response.status_code
        )


class DiscordNotificationDispatcher:
    def __init__(
        self, database: Any, bot: ModelTrackerDiscordBot, batch_size: int = 10
    ) -> None:
        self.database = database
        self.bot = bot
        self.batch_size = max(int(batch_size), 1)

    def safe_status(self) -> dict[str, Any]:
        return {
            **self.bot.safe_configuration(),
            "delivery": self.database.get_discord_notification_stats(),
        }

    def dispatch_pending(self) -> dict[str, Any]:
        result = {"claimed": 0, "delivered": 0, "failed": 0, "retrying": 0}
        if not self.bot.enabled or not self.bot.configured:
            return result
        validation_failure = self.bot.validate_connection()
        if validation_failure:
            result["connection_failed"] = 1
            return result
        try:
            jobs = self.database.claim_discord_notifications(self.batch_size)
        except Exception:
            LOGGER.exception("Discord outbox claim failed")
            result["failed"] = 1
            return result
        result["claimed"] = len(jobs)
        for job in jobs:
            try:
                delivery = self.bot.send(job["payload"])
            except Exception:
                LOGGER.exception(
                    "Unexpected Discord delivery failure for notification_id=%s",
                    job["id"],
                )
                delivery = DiscordDeliveryResult(
                    False, error_code="connection_failed"
                )
            if delivery.delivered:
                self.database.mark_discord_notification_delivered(
                    job["id"], delivery.message_id, delivery.status_code
                )
                result["delivered"] += 1
                continue
            if delivery.terminal:
                self.database.mark_discord_notification_failed(
                    job["id"],
                    delivery.error_code or "delivery_failed",
                    delivery.status_code,
                    terminal=True,
                )
                result["failed"] += 1
                continue
            delay = delivery.retry_after_seconds or min(
                300.0, 5.0 * (2 ** max(int(job.get("attempts") or 1) - 1, 0))
            )
            retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            self.database.mark_discord_notification_failed(
                job["id"],
                delivery.error_code or "delivery_failed",
                delivery.status_code,
                retry_at=retry_at,
            )
            result["retrying"] += 1
        return result
