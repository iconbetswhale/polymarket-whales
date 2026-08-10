from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests

from config import Settings

LOGGER = logging.getLogger(__name__)
DISCORD_API_BASE_URL = "https://discord.com/api/v10"
ICONLABS_PURPLE = int("8B5CF6", 16)
THIRTY_MINUTE_CONTENT = "30-minute Model Tracker update"


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


def _american_odds(value: Any) -> str:
    probability = _safe_float(value, -1)
    if not 0 < probability < 1:
        return "Unavailable"
    if probability >= 0.5:
        odds = -100 * probability / (1 - probability)
    else:
        odds = 100 * (1 - probability) / probability
    rounded = int(round(odds))
    return f"{rounded:+d}"


def _valid_url(value: Any) -> str | None:
    url = str(value or "").strip()
    return url if url.startswith(("https://", "http://")) else None


def _absolute_event_time(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "Unavailable"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return _truncate(raw, 1024)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("America/New_York"))
    else:
        parsed = parsed.astimezone(ZoneInfo("America/New_York"))
    hour = parsed.strftime("%I").lstrip("0") or "12"
    return (
        f"{parsed.strftime('%B')} {parsed.day}, {parsed.year} at "
        f"{hour}:{parsed.strftime('%M %p')}"
    )


def _provider_name(snapshot: dict[str, Any]) -> str:
    raw = " ".join(
        str(
            snapshot.get("sportsbook")
            or snapshot.get("entry_price_source")
            or "Polymarket"
        ).split()
    )
    aliases = {
        "novig": "NoVIG",
        "prophetx": "ProphetX",
        "4cx": "4CX",
        "fourcx": "4CX",
        "polymarket": "Polymarket",
        "kalshi": "Kalshi",
    }
    return aliases.get(raw.casefold(), raw or "Polymarket")


def _provider_entry(snapshot: dict[str, Any]) -> str:
    native = str(snapshot.get("provider_display_odds") or "").strip()
    if native:
        return native
    price = snapshot.get("provider_entry_price")
    if price is None:
        price = snapshot.get("current_executable_entry_price")
    if _provider_name(snapshot) in {"Polymarket", "Kalshi"}:
        return _entry_price(price)
    return _american_odds(price)


def _american_implied_cents(display_odds: str) -> str | None:
    raw = str(display_odds or "").strip().replace(",", "")
    if not raw or raw[-1:].casefold() == "c":
        return None
    try:
        odds = float(raw)
    except ValueError:
        return None
    if odds == 0:
        return None
    probability = 100 / (odds + 100) if odds > 0 else -odds / (-odds + 100)
    return f"{probability * 100:.1f}c"


def _market_label(snapshot: dict[str, Any]) -> str:
    raw = " ".join(
        str(
            snapshot.get("sports_market_type")
            or snapshot.get("market_title")
            or "Market"
        ).split()
    )
    normalized = raw.casefold().replace("_", " ").replace("-", " ")
    if normalized in {"h2h", "ml", "money line", "moneyline"} or "moneyline" in normalized:
        return "Moneyline"
    if "spread" in normalized or "run line" in normalized:
        return "Spread"
    if "total" in normalized or "over under" in normalized:
        return "Total"
    return _truncate(raw, 80)


def build_model_tracker_discord_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Format an already-approved Model Tracker snapshot for Discord."""
    selection = _truncate(snapshot.get("recommended_side") or "Unknown", 1024)
    market_label = _market_label(snapshot)
    amount = _safe_float(snapshot.get("original_displayed_amount"))
    fraction = _safe_float(snapshot.get("final_recommended_fraction"))
    units = _safe_float(snapshot.get("original_recommended_units"))
    confidence = _safe_float(snapshot.get("confidence_score"))
    provider = _provider_name(snapshot)
    provider_entry = _provider_entry(snapshot)
    implied_cents = _american_implied_cents(provider_entry)
    best_price = f"{provider} {provider_entry}"
    if implied_cents:
        best_price += f" / {implied_cents}"
    sharp_entry = _entry_price(
        snapshot.get("sharp_reference_entry_price")
        or snapshot.get("sharp_average_entry_price")
    )
    market_url = _valid_url(snapshot.get("provider_deep_link"))
    provider_logo_url = _valid_url(snapshot.get("provider_logo_url"))
    fields = [
        {
            "name": "BEST PRICE",
            "value": best_price,
            "inline": True,
        },
        {
            "name": "SHARP ENTRY",
            "value": sharp_entry,
            "inline": True,
        },
        {
            "name": "BET SIZE",
            "value": _money(amount),
            "inline": True,
        },
    ]
    if units > 0:
        fields.append(
            {"name": "UNITS", "value": f"{units:.2f}u", "inline": True}
        )
    if confidence > 0:
        fields.append(
            {"name": "CONFIDENCE", "value": f"{confidence:.0f}", "inline": True}
        )
    if snapshot.get("event_start_time"):
        fields.append(
            {
                "name": "STARTS",
                "value": _absolute_event_time(snapshot.get("event_start_time")),
                "inline": True,
            }
        )

    snapshot_id = str(snapshot.get("snapshot_id") or "")
    embed: dict[str, Any] = {
        "author": {"name": "ICON LABS • OFFICIAL MODEL PLAY"},
        "title": f"{selection} {market_label} {provider_entry}",
        "color": ICONLABS_PURPLE,
        "fields": fields,
        "footer": {
            "text": f"Private testing • {fraction * 100:.2f}% bankroll • Entry locked"
        },
    }
    if market_url:
        embed["url"] = market_url
    if provider_logo_url:
        embed["thumbnail"] = {"url": provider_logo_url}
    timestamp = str(snapshot.get("recommendation_timestamp") or "").strip()
    if timestamp:
        embed["timestamp"] = timestamp
    payload = {
        "embeds": [embed],
        "allowed_mentions": {"parse": []},
    }
    if snapshot_id:
        payload["nonce"] = snapshot_id[:25]
        payload["enforce_nonce"] = True
    return payload


def build_thirty_minute_checkpoint_discord_payload(
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    """Format a non-bet 30-minute comparison against the frozen model entry."""
    event_title = _truncate(checkpoint.get("event_title") or "Model trade update", 256)
    selection = _truncate(checkpoint.get("selection") or "Unknown", 1024)
    price_delta = checkpoint.get("price_delta_cents")
    if price_delta is None:
        price_change = "Comparison unavailable"
    elif abs(_safe_float(price_delta)) < 0.05:
        price_change = "Unchanged"
    elif _safe_float(price_delta) < 0:
        price_change = f"{abs(_safe_float(price_delta)):.1f}c better at 30m"
    else:
        price_change = f"{_safe_float(price_delta):.1f}c worse at 30m"

    new_support = len(checkpoint.get("new_supporting_wallet_ids") or [])
    new_opposition = len(checkpoint.get("new_opposing_wallet_ids") or [])
    dropped = len(checkpoint.get("dropped_supporting_wallet_ids") or [])
    active = checkpoint.get("recommendation_still_active") is True
    sharp_summary = (
        f"{checkpoint.get('sharp_verdict', 'UNCHANGED').replace('_', ' ').title()}\n"
        f"+{new_support} support | +{new_opposition} opposing | {dropped} dropped"
    )
    description = (
        f"**{_truncate(checkpoint.get('market_title') or 'Market', 900)}**\n"
        "Observation only. The original two-hour bet, stake, and P&L are unchanged."
    )
    market_url = str(checkpoint.get("market_url") or "").strip()
    if market_url.startswith(("https://", "http://")):
        description += f"\n\n[Open exact market]({market_url})"

    new_entry_guidance = (
        "Still acceptable at 30m"
        if checkpoint.get("overall_verdict") in {"IMPROVED", "STABLE"}
        else "Review before entering now"
        if checkpoint.get("overall_verdict") in {"CAUTION", "WEAKER"}
        else "Would not qualify as a new entry now"
    )
    embed = {
        "title": f"30-minute update: {event_title}",
        "description": (
            f"{description}\n\n"
            "**The original tracked play is not canceled.** This update only "
            "evaluates whether a new entry would still be attractive now."
        ),
        "color": ICONLABS_PURPLE,
        "fields": [
            {
                "name": "Official play",
                "value": "LOCKED | Original stake unchanged",
                "inline": False,
            },
            {"name": "Play", "value": selection, "inline": True},
            {
                "name": "2-hour entry",
                "value": _entry_price(checkpoint.get("price_at_two_hours")),
                "inline": True,
            },
            {
                "name": "30-minute price",
                "value": _entry_price(checkpoint.get("price_at_thirty_minutes")),
                "inline": True,
            },
            {"name": "Price update", "value": price_change, "inline": True},
            {
                "name": "Sharp update",
                "value": _truncate(sharp_summary, 1024),
                "inline": True,
            },
            {
                "name": "Live candidate status",
                "value": "Still qualifies" if active else "No longer qualifies live",
                "inline": True,
            },
            {
                "name": "Overall",
                "value": str(checkpoint.get("overall_verdict") or "STABLE")
                .replace("_", " ")
                .title(),
                "inline": True,
            },
            {
                "name": "If entering for the first time now",
                "value": new_entry_guidance,
                "inline": False,
            },
        ],
        "footer": {
            "text": "Icon Labs Entry Timing Lab | Separate 30-minute review"
        },
        "timestamp": checkpoint.get("checked_at"),
    }
    nonce = f"30m-{checkpoint.get('snapshot_id') or ''}"[:25]
    payload = {
        "content": THIRTY_MINUTE_CONTENT,
        "embeds": [embed],
        "allowed_mentions": {"parse": []},
    }
    if nonce:
        payload["nonce"] = nonce
        payload["enforce_nonce"] = True
    return payload


def build_discord_connection_test_payload(nonce: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "content": "IconBets Discord connection test",
        "embeds": [
            {
                "title": "Connection successful",
                "description": (
                    "The IconBets production backend can securely post Model "
                    "Tracker recommendations to this channel."
                ),
                "color": ICONLABS_PURPLE,
                "footer": {"text": "Icon Labs Model Tracker | Test message"},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ],
        "allowed_mentions": {"parse": []},
    }
    safe_nonce = str(nonce or "").strip()[:25]
    if safe_nonce:
        payload["nonce"] = safe_nonce
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
        checkpoint_channel_id: str | None = None,
        checkpoint_channel_name: str = "model-tracker-30m",
        timeout: int = 10,
    ) -> None:
        self._token = token
        self._guild_id = guild_id
        self._channel_id = channel_id
        self._checkpoint_channel_id = checkpoint_channel_id
        self._checkpoint_channel_name = (
            str(checkpoint_channel_name or "model-tracker-30m").strip().lower()
        )
        self.enabled = enabled
        self.timeout = timeout
        self._channel_validated = False
        self._validated_channel_ids: set[str] = set()
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
            checkpoint_channel_id=settings.discord_checkpoint_channel_id,
            checkpoint_channel_name=settings.discord_checkpoint_channel_name,
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
            "checkpoint_channel_configured": bool(self._checkpoint_channel_id),
            "checkpoint_channel_name": self._checkpoint_channel_name,
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

    def _validate_channel_id(
        self, channel_id: str | None
    ) -> DiscordDeliveryResult | None:
        if channel_id and channel_id in self._validated_channel_ids:
            return None
        if not channel_id:
            return self._record_connection_failure(
                DiscordDeliveryResult(False, error_code="channel_not_found")
            )
        try:
            response = requests.get(
                f"{DISCORD_API_BASE_URL}/channels/{channel_id}",
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
        self._validated_channel_ids.add(channel_id)
        if channel_id == self._channel_id:
            self._channel_validated = True
        self._connection_status = "authenticated"
        return None

    def _validate_channel(self) -> DiscordDeliveryResult | None:
        if self._channel_validated:
            return None
        return self._validate_channel_id(self._channel_id)

    def _resolve_checkpoint_channel(
        self,
    ) -> tuple[str | None, DiscordDeliveryResult | None]:
        if self._checkpoint_channel_id:
            return self._checkpoint_channel_id, None
        try:
            response = requests.get(
                f"{DISCORD_API_BASE_URL}/guilds/{self._guild_id}/channels",
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException:
            return None, DiscordDeliveryResult(
                False, error_code="connection_failed"
            )
        if response.status_code != 200:
            return None, self._failure(response)
        try:
            channels = response.json()
        except ValueError:
            return None, DiscordDeliveryResult(
                False, error_code="invalid_channel_response"
            )
        existing = next(
            (
                channel
                for channel in channels
                if str(channel.get("name") or "").strip().lower()
                == self._checkpoint_channel_name
                and int(channel.get("type") or 0) == 0
            ),
            None,
        )
        if existing:
            self._checkpoint_channel_id = str(existing.get("id") or "") or None
            return self._checkpoint_channel_id, None
        try:
            response = requests.post(
                f"{DISCORD_API_BASE_URL}/guilds/{self._guild_id}/channels",
                headers=self._headers(),
                json={
                    "name": self._checkpoint_channel_name,
                    "type": 0,
                    "topic": (
                        "Icon Labs 30-minute price and Sharp-evidence reviews. "
                        "These updates never rewrite official tracked plays."
                    ),
                },
                timeout=self.timeout,
            )
        except requests.RequestException:
            return None, DiscordDeliveryResult(
                False, error_code="connection_failed"
            )
        if response.status_code not in {200, 201}:
            return None, self._failure(response)
        try:
            self._checkpoint_channel_id = (
                str(response.json().get("id") or "") or None
            )
        except ValueError:
            return None, DiscordDeliveryResult(
                False, error_code="invalid_channel_response"
            )
        if self._checkpoint_channel_id:
            self._validated_channel_ids.add(self._checkpoint_channel_id)
        return self._checkpoint_channel_id, None

    def validate_connection(self) -> DiscordDeliveryResult | None:
        if not self.enabled:
            self._connection_status = "disabled"
            return DiscordDeliveryResult(False, error_code="disabled", terminal=True)
        if not self.configured:
            self._connection_status = "not configured"
            return DiscordDeliveryResult(False, error_code="not_configured")
        return self._validate_channel()

    def send(self, payload: dict[str, Any]) -> DiscordDeliveryResult:
        embeds = payload.get("embeds") or []
        embed = embeds[0] if len(embeds) == 1 else {}
        author = str((embed.get("author") or {}).get("name") or "")
        if author != "ICON LABS • OFFICIAL MODEL PLAY" or payload.get("content"):
            LOGGER.warning("Blocked private or non-official Discord notification")
            return DiscordDeliveryResult(
                False,
                error_code="private_only",
                terminal=True,
            )
        validation_failure = self._validate_channel_id(self._channel_id)
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
            result["connection_error"] = validation_failure.error_code
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
