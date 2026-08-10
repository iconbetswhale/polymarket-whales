from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


PRICE_TOLERANCE = 0.0005


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed


def _ids(values: Any) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {str(value).strip().lower() for value in values if str(value).strip()}


def _play_identity(play: dict[str, Any]) -> tuple[str, str, str, str]:
    validation = play.get("validation_ids") or {}
    return (
        str(validation.get("event_id") or play.get("event_slug") or "").lower(),
        str(
            validation.get("condition_id")
            or play.get("canonical_market_key")
            or ""
        ).lower(),
        str(play.get("market_line") or ""),
        str(
            play.get("clob_token_id")
            or validation.get("outcome")
            or play.get("canonical_side_key")
            or play.get("outcome")
            or ""
        ).lower(),
    )


def _snapshot_identity(snapshot: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(snapshot.get("canonical_event_id") or "").lower(),
        str(snapshot.get("canonical_market_id") or "").lower(),
        str(snapshot.get("market_line") or ""),
        str(snapshot.get("outcome_id") or snapshot.get("recommended_side") or "").lower(),
    )


def _best_execution(play: dict[str, Any]) -> dict[str, Any]:
    options = [
        option
        for option in (play.get("executionOptions") or [])
        if isinstance(option, dict)
        and option.get("isAvailable") is True
        and option.get("matchingConfidence") == "Exact"
        and option.get("isStale") is not True
        and str(option.get("marketStatus") or "OPEN").upper() == "OPEN"
        and _safe_float(option.get("bestExecutablePrice")) is not None
    ]
    marked = next((option for option in options if option.get("isBestPrice")), None)
    if marked:
        return marked
    return min(
        options,
        key=lambda option: _safe_float(option.get("bestExecutablePrice"), 2.0),
        default={},
    )


def _wallet_ids(play: dict[str, Any], key: str, fallback_key: str) -> set[str]:
    values = _ids(play.get(key))
    if values:
        return values
    return {
        str(wallet.get("wallet_address") or "").strip().lower()
        for wallet in (play.get(fallback_key) or [])
        if str(wallet.get("wallet_address") or "").strip()
    }


def build_thirty_minute_checkpoint(
    record: dict[str, Any],
    plays: list[dict[str, Any]],
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    snapshot = record.get("snapshot") or {}
    identity = _snapshot_identity(snapshot)
    exact = next((play for play in plays if _play_identity(play) == identity), None)
    same_market = [
        play
        for play in plays
        if _play_identity(play)[:3] == identity[:3]
        and _play_identity(play)[3] != identity[3]
    ]

    original_agreeing = _ids(
        snapshot.get("agreeing_wallet_ids")
        or snapshot.get("lead_wallet_ids")
        or []
    ) | _ids(snapshot.get("supporting_wallet_ids"))
    original_opposing = _ids(
        (snapshot.get("sharp_snapshot") or {}).get("contradicting_wallet_ids")
        or snapshot.get("contradicting_wallet_ids")
        or []
    )

    current_agreeing: set[str] = set()
    current_opposing: set[str] = set()
    if exact:
        current_agreeing = _wallet_ids(exact, "agreeingWalletIds", "supporting_wallets")
        current_opposing = _wallet_ids(
            exact, "contradictingWalletIds", "contradicting_wallets"
        )
    for opposing_play in same_market:
        current_opposing |= _wallet_ids(
            opposing_play, "agreeingWalletIds", "supporting_wallets"
        )

    execution = _best_execution(exact or {})
    price_30m = _safe_float(execution.get("bestExecutablePrice"))
    if price_30m is None and exact:
        price_30m = _safe_float(
            exact.get("effective_entry_price")
            or exact.get("current_price")
            or exact.get("snapshot_current_price")
        )
    price_2h = _safe_float(
        snapshot.get("current_executable_entry_price")
        or snapshot.get("effective_entry_price")
    )
    price_delta_cents = (
        round((price_30m - price_2h) * 100, 4)
        if price_30m is not None and price_2h is not None
        else None
    )
    if price_delta_cents is None:
        price_verdict = "UNAVAILABLE"
    elif price_delta_cents < -(PRICE_TOLERANCE * 100):
        price_verdict = "BETTER_AT_30_MINUTES"
    elif price_delta_cents > PRICE_TOLERANCE * 100:
        price_verdict = "WORSE_AT_30_MINUTES"
    else:
        price_verdict = "UNCHANGED"

    original_weight = _safe_float(snapshot.get("weighted_sharp_count"), 0.0) or 0.0
    current_weight = (
        _safe_float(
            (exact or {}).get("weighted_sharp_count")
            or (exact or {}).get("weightedAgreeingConsensus"),
            0.0,
        )
        or 0.0
    )
    current_opposing_weight = (
        _safe_float(
            (exact or {}).get("weightedDirectionalOpposition")
            or (exact or {}).get("weighted_directional_opposition"),
            0.0,
        )
        or 0.0
    )
    for opposing_play in same_market:
        current_opposing_weight += (
            _safe_float(
                opposing_play.get("weightedDirectionalSupport")
                or opposing_play.get("weighted_sharp_count"),
                0.0,
            )
            or 0.0
        )

    new_supporters = sorted(current_agreeing - original_agreeing)
    dropped_supporters = sorted(original_agreeing - current_agreeing)
    new_opponents = sorted(current_opposing - original_opposing)
    still_active = exact is not None
    if new_opponents or current_opposing_weight > 0:
        sharp_verdict = "OPPOSITION_ADDED"
    elif current_weight > original_weight + 0.05 or new_supporters:
        sharp_verdict = "SUPPORT_STRENGTHENED"
    elif not still_active or current_weight + 0.05 < original_weight or dropped_supporters:
        sharp_verdict = "SUPPORT_WEAKENED"
    else:
        sharp_verdict = "UNCHANGED"

    if sharp_verdict == "OPPOSITION_ADDED":
        overall = "CAUTION"
    elif not still_active:
        overall = "NO_LONGER_RECOMMENDED"
    elif price_verdict == "BETTER_AT_30_MINUTES" and sharp_verdict == "SUPPORT_STRENGTHENED":
        overall = "IMPROVED"
    elif price_verdict == "WORSE_AT_30_MINUTES" or sharp_verdict == "SUPPORT_WEAKENED":
        overall = "WEAKER"
    else:
        overall = "STABLE"

    checked = (checked_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return {
        "checkpoint_version": "entry-timing-v1",
        "checkpoint_type": "THIRTY_MINUTE_REVIEW",
        "checked_at": checked.isoformat(),
        "original_dedupe_key": record.get("dedupe_key"),
        "snapshot_id": record.get("snapshot_id"),
        "event_title": snapshot.get("event_title"),
        "market_title": snapshot.get("market_title"),
        "selection": snapshot.get("recommended_side"),
        "event_start_time": snapshot.get("event_start_time"),
        "market_url": snapshot.get("market_url"),
        "recommendation_still_active": still_active,
        "price_at_two_hours": price_2h,
        "price_at_thirty_minutes": price_30m,
        "price_delta_cents": price_delta_cents,
        "price_verdict": price_verdict,
        "two_hour_sportsbook": snapshot.get("sportsbook"),
        "thirty_minute_sportsbook": execution.get("providerName"),
        "original_confidence_score": snapshot.get("confidence_score"),
        "current_confidence_score": (exact or {}).get("confidence_score"),
        "original_lead_sharp_count": snapshot.get("lead_sharp_count"),
        "current_lead_sharp_count": (exact or {}).get("lead_sharp_count", 0),
        "original_supporting_sharp_count": snapshot.get("supporting_sharp_count"),
        "current_supporting_sharp_count": (exact or {}).get(
            "supporting_sharp_count", 0
        ),
        "original_weighted_support": round(original_weight, 6),
        "current_weighted_support": round(current_weight, 6),
        "current_weighted_opposition": round(current_opposing_weight, 6),
        "new_supporting_wallet_ids": new_supporters,
        "dropped_supporting_wallet_ids": dropped_supporters,
        "new_opposing_wallet_ids": new_opponents,
        "current_agreeing_wallet_ids": sorted(current_agreeing),
        "current_opposing_wallet_ids": sorted(current_opposing),
        "opposite_play_count": len(same_market),
        "sharp_verdict": sharp_verdict,
        "overall_verdict": overall,
        "official_model_entry_unchanged": True,
    }


def timing_outlook(records: list[dict[str, Any]]) -> dict[str, Any]:
    checkpoints = [
        (record, record.get("thirty_minute_checkpoint") or {})
        for record in records
        if record.get("thirty_minute_checkpoint")
    ]
    deltas = [
        checkpoint.get("price_delta_cents")
        for _, checkpoint in checkpoints
        if checkpoint.get("price_delta_cents") is not None
    ]
    better = sum(delta < -(PRICE_TOLERANCE * 100) for delta in deltas)
    worse = sum(delta > PRICE_TOLERANCE * 100 for delta in deltas)
    unchanged = len(deltas) - better - worse
    settled_pnl_delta = 0.0
    settled_comparisons = 0
    for record, checkpoint in checkpoints:
        if str(record.get("status") or "").lower() not in {"won", "lost"}:
            continue
        entry_2h = _safe_float(checkpoint.get("price_at_two_hours"))
        entry_30m = _safe_float(checkpoint.get("price_at_thirty_minutes"))
        stake = _safe_float(
            (record.get("snapshot") or {}).get("original_displayed_amount")
        )
        if not entry_2h or not entry_30m or not stake:
            continue
        settled_comparisons += 1
        if str(record.get("status")).lower() == "won":
            settled_pnl_delta += stake * ((1 / entry_30m) - (1 / entry_2h))

    measured = len(deltas)
    if measured < 10:
        recommendation = "COLLECTING_EVIDENCE"
        explanation = "Wait for at least 10 measured checkpoints before choosing an entry window."
    elif better > worse:
        recommendation = "THIRTY_MINUTES_LEAN"
        explanation = "Thirty-minute prices have been better more often than two-hour prices."
    elif worse > better:
        recommendation = "TWO_HOURS_LEAN"
        explanation = "Two-hour prices have been better more often than thirty-minute prices."
    else:
        recommendation = "NO_CLEAR_EDGE"
        explanation = "Neither entry window has a clear pricing advantage yet."

    return {
        "checkpoint_count": len(checkpoints),
        "price_comparison_count": measured,
        "better_at_thirty_minutes": better,
        "worse_at_thirty_minutes": worse,
        "unchanged_price": unchanged,
        "average_price_delta_cents": (
            round(sum(deltas) / measured, 4) if measured else None
        ),
        "support_strengthened": sum(
            checkpoint.get("sharp_verdict") == "SUPPORT_STRENGTHENED"
            for _, checkpoint in checkpoints
        ),
        "opposition_added": sum(
            checkpoint.get("sharp_verdict") == "OPPOSITION_ADDED"
            for _, checkpoint in checkpoints
        ),
        "no_longer_recommended": sum(
            not checkpoint.get("recommendation_still_active")
            for _, checkpoint in checkpoints
        ),
        "settled_comparison_count": settled_comparisons,
        "fixed_stake_pnl_delta_if_waited": round(settled_pnl_delta, 2),
        "entry_window_recommendation": recommendation,
        "explanation": explanation,
    }
