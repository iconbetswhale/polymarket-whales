from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


COMPLETED_TERMS = {
    "canceled",
    "cancelled",
    "closed",
    "complete",
    "completed",
    "ended",
    "final",
    "finished",
    "graded",
    "resolved",
    "settled",
    "void",
}
LIVE_TERMS = {
    "in progress",
    "in-progress",
    "inplay",
    "in-play",
    "live",
    "playing",
    "started",
}
DELAYED_TERMS = {"delayed", "postponed", "rescheduled", "suspended"}
STALE_LIVE_AFTER = timedelta(days=7)


@dataclass(frozen=True)
class Lifecycle:
    state: str
    reason: str
    uncertain: bool = False


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text or ("T" not in text and " " not in text):
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _status_text(position: dict[str, Any]) -> str:
    values = [
        position.get("game_status"),
        position.get("event_status"),
        position.get("market_resolution_status"),
        position.get("market_status"),
    ]
    return " ".join(str(value).strip().lower() for value in values if value)


def _contains_any(text: str, terms: set[str]) -> bool:
    return any(term in text for term in terms)


def classify_lifecycle(
    position: dict[str, Any], now: datetime | None = None
) -> Lifecycle:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)

    status_text = _status_text(position)
    event_closed = bool(position.get("event_closed") or position.get("event_ended"))
    market_closed = bool(position.get("market_closed"))
    if event_closed or market_closed or _contains_any(status_text, COMPLETED_TERMS):
        return Lifecycle("completed", "Official event or market status is completed.")

    event_time = parse_datetime(position.get("resolution_time"))
    # Gamma's event `live` flag describes publication, not an in-progress game.
    # Only explicit sports/market status terms can authoritatively mark play live.
    reports_live = _contains_any(status_text, LIVE_TERMS)
    if reports_live and event_time and now - event_time > STALE_LIVE_AFTER:
        return Lifecycle(
            "uncertain",
            "The official live flag is stale relative to the verified start time.",
            True,
        )
    if reports_live:
        return Lifecycle("live", "Official event status is live.")

    if not event_time:
        return Lifecycle(
            "uncertain", "A verified scheduled start time is unavailable.", True
        )

    if event_time > now:
        if _contains_any(status_text, DELAYED_TERMS):
            return Lifecycle(
                "upcoming", "The updated official start time is still in the future."
            )
        if (
            position.get("market_active") is False
            or position.get("accepting_orders") is False
        ):
            return Lifecycle(
                "uncertain",
                "The event is upcoming but the market is not accepting orders.",
                True,
            )
        return Lifecycle("upcoming", "Verified scheduled start time is in the future.")

    if now - event_time > STALE_LIVE_AFTER:
        return Lifecycle(
            "uncertain",
            "The scheduled start is too old to infer a live event from an open market.",
            True,
        )

    if (
        position.get("market_active") is True
        and position.get("accepting_orders") is True
    ):
        return Lifecycle(
            "live", "Scheduled start passed while the official market remains active."
        )

    return Lifecycle(
        "uncertain",
        "The start time passed without a reliable live or completed status.",
        True,
    )
