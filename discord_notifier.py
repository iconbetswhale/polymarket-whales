from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests

from config import Settings

LOGGER = logging.getLogger(__name__)


def _money(value: Any) -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0
    return f"${amount:,.2f}"


def _price_cents(value: Any) -> str:
    try:
        price = float(value or 0)
    except (TypeError, ValueError):
        return "n/a"
    return f"{price * 100:.1f}c"


@dataclass(frozen=True)
class DiscordNotifier:
    webhook_url: str | None
    alert_types: set[str]
    min_position_usd: float = 0.0
    timeout: int = 10

    @classmethod
    def from_settings(cls, settings: Settings) -> "DiscordNotifier":
        return cls(
            webhook_url=settings.discord_webhook_url,
            alert_types=set(settings.discord_alert_types),
            min_position_usd=settings.discord_min_position_usd,
        )

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    def should_notify(self, event: dict) -> bool:
        if not self.enabled:
            return False
        if event.get("event_type") not in self.alert_types:
            return False
        position_size = float(event.get("position_size_usd") or 0)
        return position_size >= self.min_position_usd

    def notify(self, event: dict) -> bool:
        if not self.should_notify(event):
            return False

        payload = self._build_payload(event)
        try:
            response = requests.post(self.webhook_url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            return True
        except requests.RequestException as exc:
            LOGGER.warning("Discord notification failed: %s", exc)
            return False

    def _build_payload(self, event: dict) -> dict:
        event_type = str(event.get("event_type") or "wallet_event")
        action = {
            "new_entry": "opened a new position",
            "size_increase": "added to a position",
            "size_decrease": "reduced a position",
            "full_exit": "exited a position",
        }.get(event_type, event_type.replace("_", " "))

        wallet_label = event.get("wallet_label") or "Tracked wallet"
        market_title = event.get("market_title") or "Unknown market"
        outcome = event.get("outcome") or "Unknown outcome"

        fields = [
            {"name": "Wallet", "value": str(wallet_label), "inline": True},
            {"name": "Outcome", "value": str(outcome), "inline": True},
            {"name": "Position", "value": _money(event.get("position_size_usd")), "inline": True},
            {"name": "Current Value", "value": _money(event.get("current_value")), "inline": True},
            {"name": "Avg Entry", "value": _price_cents(event.get("average_entry_price")), "inline": True},
            {"name": "Current Price", "value": _price_cents(event.get("current_price")), "inline": True},
        ]

        if event.get("delta_usd") is not None:
            fields.append({"name": "Size Change", "value": _money(event.get("delta_usd")), "inline": True})

        links = []
        if event.get("market_url"):
            links.append(f"[Market]({event['market_url']})")
        if event.get("wallet_profile_url"):
            links.append(f"[Wallet]({event['wallet_profile_url']})")

        embed = {
            "title": f"{wallet_label} {action}",
            "description": f"**{market_title}**",
            "color": 3209337,
            "fields": fields,
            "footer": {"text": "IconBets Polymarket Wallet Tracker"},
            "timestamp": event.get("detected_at"),
        }
        if links:
            embed["description"] = f"{embed['description']}\n\n{' | '.join(links)}"

        return {
            "username": "IconBets Wallet Alerts",
            "embeds": [embed],
        }
