from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from bet_sizing import (
    MISSING_EXECUTABLE_PRICE,
    SizingConfig,
    build_recommendation,
)
from bet_tracker import recommendation_snapshot


EASTERN = ZoneInfo("America/New_York")

INVALID_EVENT_TIME = "INVALID_EVENT_TIME"
EVENT_ALREADY_STARTED = "EVENT_ALREADY_STARTED"
NOT_TODAY = "NOT_TODAY"
MARKET_NOT_ACTIONABLE = "MARKET_NOT_ACTIONABLE"
MISSING_BANKROLL = "MISSING_BANKROLL"
MISSING_ENTRY_PRICE = "MISSING_ENTRY_PRICE"
INVALID_PROBABILITY_INPUT = "INVALID_PROBABILITY_INPUT"
ZERO_KELLY = "ZERO_KELLY"
DUPLICATE_RECOMMENDATION = "DUPLICATE_RECOMMENDATION"
SYNC_INCOMPLETE = "SYNC_INCOMPLETE"
MISSING_LEAD_SHARP = "MISSING_LEAD_SHARP"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value if value is not None else default)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def parse_event_start(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=EASTERN)
    return parsed.astimezone(timezone.utc)


def event_is_today(event_start: datetime, now: datetime) -> bool:
    return event_start.astimezone(EASTERN).date() == now.astimezone(EASTERN).date()


def _unavailable_reason(recommendation: dict[str, Any]) -> str:
    reason = str(recommendation.get("reason") or "").lower()
    if "lead sharp" in reason:
        return MISSING_LEAD_SHARP
    if "bankroll" in reason:
        return MISSING_BANKROLL
    if "ask" in reason or "order-book" in reason or "depth" in reason:
        return MISSING_EXECUTABLE_PRICE
    return SYNC_INCOMPLETE


def evaluate_trade_recommendation(
    play: dict[str, Any],
    bankroll: float,
    config: SizingConfig,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return the one canonical sizing and Model Tracker eligibility decision."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)

    recommendation = build_recommendation(play, bankroll, config)
    snapshot = recommendation_snapshot(play, recommendation, bankroll, now)
    event_start = parse_event_start(play.get("event_date_et"))
    rejection_reason: str | None = None

    if event_start is None:
        rejection_reason = INVALID_EVENT_TIME
    elif event_start <= now:
        rejection_reason = EVENT_ALREADY_STARTED
    elif not event_is_today(event_start, now):
        rejection_reason = NOT_TODAY
    elif play.get("market_open") is not True or str(
        play.get("lifecycle_status") or ""
    ).lower() != "upcoming":
        rejection_reason = MARKET_NOT_ACTIONABLE
    elif _safe_float(bankroll) <= 0:
        rejection_reason = MISSING_BANKROLL
    elif recommendation.get("available") is not True:
        rejection_reason = _unavailable_reason(recommendation)
    else:
        entry_price = _safe_float(
            recommendation.get("current_user_entry_price"), -1.0
        )
        estimated_probability = _safe_float(
            recommendation.get("estimated_win_probability"), -1.0
        )
        final_fraction = _safe_float(
            recommendation.get("final_recommended_fraction"), -1.0
        )
        recommended_amount = _safe_float(
            recommendation.get("recommended_amount"), -1.0
        )
        if not 0 < entry_price < 1:
            rejection_reason = MISSING_ENTRY_PRICE
        elif recommendation.get("passes_slippage_rule") is not True:
            rejection_reason = (
                recommendation.get("slippage_rejection_reason")
                or MISSING_EXECUTABLE_PRICE
            )
        elif not 0 < estimated_probability < 1:
            rejection_reason = INVALID_PROBABILITY_INPUT
        elif final_fraction <= 0 or recommended_amount <= 0:
            rejection_reason = ZERO_KELLY

    return {
        "play": play,
        "recommendation": recommendation,
        "snapshot": snapshot,
        "event_start_utc": event_start.isoformat() if event_start else None,
        "event_start_et": (
            event_start.astimezone(EASTERN).isoformat() if event_start else None
        ),
        "qualifies_today": bool(event_start and event_is_today(event_start, now)),
        "model_tracker_eligible": rejection_reason is None,
        "model_tracker_rejection_reason": rejection_reason,
        "recommendation_snapshot_id": snapshot["snapshot_id"],
        "recommendation_idempotency_key": snapshot["dedupe_key"],
    }
