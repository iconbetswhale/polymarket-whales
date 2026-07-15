from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from classification import (
    canonical_category_id,
    canonical_category_ids,
    category_matches,
)
from trade_research import (
    CONTRADICTING_NON_CATEGORY,
    SHARP_NON_CATEGORY,
    classification_fields,
    classify_trade,
    research_confidence,
)

SECONDARY_SCORE_WEIGHTS = {
    "category_composition": 0.25,
    "combined_amount": 0.25,
    "relative_size": 0.20,
    "trader_history": 0.15,
    "adjusted_hit_rate": 0.10,
    "slippage": 0.05,
}

LOGGER = logging.getLogger(__name__)


TRADER_STATS = {
    "1winstreak1": {"total_trades": 12899, "hit_rate": 0.612},
    "0xbca08c1bc204a34f2fddbe47b438b9bd42ac9705": {
        "total_trades": 12899,
        "hit_rate": 0.612,
    },
    "0x4f2": {"total_trades": 7225, "hit_rate": 0.555},
    "0x4f29e103339919c4baaea2a60195cf1c8bb27a7e": {
        "total_trades": 7225,
        "hit_rate": 0.555,
    },
}

EASTERN = ZoneInfo("America/New_York")
MIN_PLAYABLE_UNITS = 0.2
PRIMARY_AMOUNT_SIMILARITY_RATIO = 0.02

NO_LEAD_SHARP = "NO_LEAD_SHARP"
TOP_CATEGORY_MISMATCH = "TOP_CATEGORY_MISMATCH"
UNRESOLVED_TRADE_CATEGORY = "UNRESOLVED_TRADE_CATEGORY"
OPPOSING_WALLETS = "OPPOSING_WALLETS"
BELOW_WALLET_ACTIONABLE_THRESHOLD = "BELOW_WALLET_ACTIONABLE_THRESHOLD"

TEAM_ALIASES = {
    "tor": ["toronto", "blue-jays", "bluejays", "jays"],
    "blue-jays": ["tor", "toronto", "bluejays", "jays"],
    "nyy": ["new-york-yankees", "yankees"],
    "yankees": ["nyy", "new-york-yankees"],
    "bos": ["boston-red-sox", "red-sox"],
    "red-sox": ["bos", "boston-red-sox"],
    "lad": ["los-angeles-dodgers", "dodgers"],
    "dodgers": ["lad", "los-angeles-dodgers"],
}


@dataclass(frozen=True)
class CanonicalSide:
    market_key: str
    side_key: str


def _category_profile(position: dict[str, Any]) -> dict[str, Any]:
    configured_values = (
        position.get("configured_top_category_ids")
        or position.get("configured_top_categories")
        or position.get("configured_top_category")
        or position.get("wallet_top_categories")
        or position.get("wallet_top_category")
    )
    configured_ids = canonical_category_ids(configured_values)
    statistical_values = position.get("top_category_ids") or position.get(
        "top_category"
    )
    statistical_ids = canonical_category_ids(statistical_values)
    top_category_ids = configured_ids or statistical_ids
    trade_category_id = canonical_category_id(
        position.get("canonical_category_id") or position.get("category")
    )
    is_lead = category_matches(trade_category_id, top_category_ids)
    source = position.get("top_category_source")
    if configured_ids:
        source = source or "manual_config"
    elif statistical_ids:
        source = source or "statistically_verified"
    return {
        "trade_category_id": trade_category_id,
        "top_category_ids": list(top_category_ids),
        "primary_top_category_id": (
            position.get("primary_top_category_id")
            or (top_category_ids[0] if top_category_ids else None)
        ),
        "top_category_source": source,
        "top_category_verified_at": position.get("top_category_verified_at"),
        "is_lead_sharp": is_lead,
        "sharp_role": "Lead Sharp" if is_lead else "Supporting Sharp",
        "category_weight": 1.0 if is_lead else 0.5,
    }


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _position_signal_amount(position: dict[str, Any]) -> float:
    if position.get("signal_position_size_usd") is not None:
        return _safe_float(position.get("signal_position_size_usd"))
    return _safe_float(position.get("position_size_usd"))


def _safe_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_text(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    return normalized.strip("-") or "unknown"


def _search_tokens(value: Any) -> set[str]:
    normalized = _normalize_text(value)
    tokens = {normalized}
    tokens.update(part for part in normalized.split("-") if part)
    for token in list(tokens):
        tokens.update(TEAM_ALIASES.get(token, []))
    return tokens


def canonical_side(position: dict[str, Any]) -> CanonicalSide:
    condition_id = str(position.get("condition_id") or "").strip().lower()
    market_key = condition_id
    if not market_key:
        market_key = "::".join(
            [
                _normalize_text(position.get("event_slug") or position.get("event_id")),
                _normalize_text(
                    position.get("market_slug") or position.get("market_title")
                ),
            ]
        )
    return CanonicalSide(
        market_key=market_key, side_key=_normalize_text(position.get("outcome"))
    )


def sharps_badge(wallet_count: int) -> str | None:
    if wallet_count < 2:
        return None
    names = {
        2: "Two",
        3: "Three",
        4: "Four",
        5: "Five",
        6: "Six",
        7: "Seven",
        8: "Eight",
        9: "Nine",
        10: "Ten",
    }
    return f"{names.get(wallet_count, str(wallet_count))} Sharps"


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[int(index)]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _curve(value: float, denominator: float, weight: float = 1.0) -> float:
    if denominator <= 0:
        return 0.0
    return max(0.0, min(1.0, value / denominator)) * weight


def _log_score(value: float, benchmark: float, weight: float = 1.0) -> float:
    if value <= 0 or benchmark <= 0:
        return 0.0
    return max(0.0, min(1.0, math.log1p(value) / math.log1p(benchmark))) * weight


def _slippage_quality(slippage: float) -> float:
    if slippage <= 0:
        return 1.0
    return max(0.0, min(1.0, 1 - slippage / 0.15))


def _consensus_band(
    wallet_count: int, tracked_wallet_count: int | None
) -> dict[str, Any]:
    if tracked_wallet_count and wallet_count == tracked_wallet_count:
        return {
            "name": "Complete tracked-wallet agreement",
            "start": 100,
            "end": 100,
            "floor": 100,
            "is_unanimous": True,
            "description": "Every enabled tracked wallet has an active position on this exact side.",
        }
    if wallet_count <= 1:
        return {
            "name": "1 Sharp",
            "start": 50,
            "end": 69,
            "floor": 50,
            "is_unanimous": False,
            "description": "1 Sharp qualified for the 50-69 range.",
        }
    if wallet_count == 2:
        return {
            "name": "2 Sharps",
            "start": 70,
            "end": 79,
            "floor": 70,
            "is_unanimous": False,
            "description": "2 Sharps qualified for the 70-79 range.",
        }

    consensus_bonus = 0
    if tracked_wallet_count and tracked_wallet_count > 3:
        raw_progress = max(
            0.0, min(1.0, (wallet_count - 3) / (tracked_wallet_count - 3))
        )
        pct_progress = max(0.0, min(1.0, wallet_count / tracked_wallet_count))
        consensus_bonus = round((raw_progress * 0.6 + pct_progress * 0.4) * 8)
    floor = min(94, 80 + consensus_bonus)
    return {
        "name": "3+ Sharps",
        "start": 80,
        "end": 99,
        "floor": floor,
        "is_unanimous": False,
        "description": f"{wallet_count} Sharps qualified for the 80-99 range.",
    }


def _weighted_hit_rate(
    group: list[dict[str, Any]],
    events_by_wallet: dict[str, list[dict[str, Any]]],
    category_weights: dict[str, float] | None = None,
) -> float:
    total_samples = 0.0
    weighted_rate = 0.0
    for position in group:
        sample = _sample_size(position, events_by_wallet)
        rate = _adjusted_hit_rate(position, sample)
        wallet = str(position.get("wallet_address") or "").lower()
        category_weight = (category_weights or {}).get(wallet, 1.0)
        weighted_sample = sample * category_weight
        total_samples += weighted_sample
        weighted_rate += rate * weighted_sample
    return weighted_rate / total_samples if total_samples > 0 else 0.5


def _confidence_score(
    *,
    wallet_count: int,
    lead_sharp_count: int,
    supporting_sharp_count: int,
    weighted_sharp_count: float,
    tracked_wallet_count: int | None,
    combined_amount_signal: float,
    relative_size_signal: float,
    trader_history_signal: float,
    adjusted_hit_rate: float,
    group_hit_rate: float,
    slippage: float,
) -> tuple[int, dict[str, Any]]:
    band = _consensus_band(wallet_count, tracked_wallet_count)
    composition_quality = max(
        0.0, min(1.0, weighted_sharp_count / max(1, wallet_count))
    )
    hit_rate_quality = _curve(
        max(((adjusted_hit_rate * 0.7) + (group_hit_rate * 0.3)) - 0.5, 0), 0.15
    )
    if band["is_unanimous"]:
        return 100, {
            "architecture": "consensus_first",
            "consensus_band": band["name"],
            "band_start": 100,
            "band_end": 100,
            "consensus_floor": 100,
            "available_secondary_points": 0,
            "secondary_points": 0,
            "secondary_quality": 1.0,
            "raw_sharp_count": wallet_count,
            "lead_sharp_count": lead_sharp_count,
            "leadSharpCount": lead_sharp_count,
            "supporting_sharp_count": supporting_sharp_count,
            "supportingSharpCount": supporting_sharp_count,
            "weighted_sharp_count": weighted_sharp_count,
            "category_composition": round(composition_quality, 4),
            "combined_amount": round(combined_amount_signal, 4),
            "relative_size": round(relative_size_signal, 4),
            "trader_history": round(trader_history_signal, 4),
            "adjusted_hit_rate": round(hit_rate_quality, 4),
            "slippage": round(_slippage_quality(slippage), 4),
            "explanation": "Complete tracked-wallet agreement. Every enabled tracked wallet has an active position on this exact side.",
        }

    components = {
        "category_composition": composition_quality,
        "combined_amount": combined_amount_signal,
        "relative_size": relative_size_signal,
        "trader_history": trader_history_signal,
        "adjusted_hit_rate": hit_rate_quality,
        "slippage": _slippage_quality(slippage),
    }
    non_category_quality = sum(
        components[key] * SECONDARY_SCORE_WEIGHTS[key]
        for key in SECONDARY_SCORE_WEIGHTS
        if key != "category_composition"
    )
    category_factor = 0.5 + (0.5 * composition_quality)
    secondary_quality = min(
        1.0,
        (
            components["category_composition"]
            * SECONDARY_SCORE_WEIGHTS["category_composition"]
        )
        + (non_category_quality * category_factor),
    )
    available_points = max(0, band["end"] - band["floor"])
    secondary_points = round(secondary_quality * available_points)
    score = min(band["end"], band["floor"] + secondary_points)
    return score, {
        "architecture": "consensus_first",
        "consensus_band": band["name"],
        "band_start": band["start"],
        "band_end": band["end"],
        "consensus_floor": band["floor"],
        "available_secondary_points": available_points,
        "secondary_points": secondary_points,
        "secondary_quality": round(secondary_quality, 4),
        "raw_sharp_count": wallet_count,
        "lead_sharp_count": lead_sharp_count,
        "supporting_sharp_count": supporting_sharp_count,
        "weighted_sharp_count": weighted_sharp_count,
        "category_composition": round(composition_quality, 4),
        "combined_amount": round(components["combined_amount"], 4),
        "relative_size": round(components["relative_size"], 4),
        "trader_history": round(components["trader_history"], 4),
        "adjusted_hit_rate": round(components["adjusted_hit_rate"], 4),
        "slippage": round(components["slippage"], 4),
        "explanation": f"{band['description']} {lead_sharp_count} Lead and {supporting_sharp_count} Supporting Sharps produced {weighted_sharp_count:g} weighted consensus. Secondary metrics placed it at {score} within that consensus range.",
    }


def _trader_stat(position: dict[str, Any], field: str) -> Any:
    label = str(position.get("wallet_label") or "").lower()
    address = str(position.get("wallet_address") or "").lower()
    return (TRADER_STATS.get(label) or TRADER_STATS.get(address) or {}).get(field)


def _historical_samples(
    position: dict[str, Any], events_by_wallet: dict[str, list[dict[str, Any]]]
) -> list[float]:
    samples = []
    for event in events_by_wallet.get(
        str(position.get("wallet_address") or "").lower(), []
    ):
        amount = abs(
            _safe_float(event.get("position_size_usd") or event.get("delta_usd"))
        )
        if amount > 0:
            samples.append(amount)
    return samples


def _relative_units(
    position: dict[str, Any],
    unit_map: dict[str, dict[str, Any]],
    events_by_wallet: dict[str, list[dict[str, Any]]],
) -> float | None:
    amount = _position_signal_amount(position)
    wallet = str(position.get("wallet_address") or "").lower()
    base_unit = unit_map.get(wallet, {}).get("estimated_base_unit") or position.get(
        "estimated_base_unit"
    )
    if base_unit and _safe_float(base_unit) > 0:
        return amount / _safe_float(base_unit)
    samples = _historical_samples(position, events_by_wallet)
    baseline = median(samples) if samples else 0
    return amount / baseline if baseline > 0 else None


def _minimum_units(position: dict[str, Any]) -> float:
    configured = position.get("minimum_position_units")
    if configured is None:
        return MIN_PLAYABLE_UNITS
    return max(_safe_float(configured, MIN_PLAYABLE_UNITS), MIN_PLAYABLE_UNITS)


def _actionable_units(position: dict[str, Any]) -> float:
    minimum = _minimum_units(position)
    configured = position.get("actionable_position_units")
    if configured is None:
        return minimum
    return max(_safe_float(configured, minimum), minimum)


def _sample_size(
    position: dict[str, Any], events_by_wallet: dict[str, list[dict[str, Any]]]
) -> int:
    manual = _trader_stat(position, "total_trades")
    if manual:
        return int(manual)
    return len(
        events_by_wallet.get(str(position.get("wallet_address") or "").lower(), [])
    )


def _adjusted_hit_rate(position: dict[str, Any], sample_size: int) -> float:
    hit_rate = _trader_stat(position, "hit_rate")
    if hit_rate is None:
        return 0.5
    prior_rate = 0.52
    prior_samples = 100
    wins = float(hit_rate) * max(sample_size, 0)
    return (wins + prior_rate * prior_samples) / (max(sample_size, 0) + prior_samples)


def _slippage(position: dict[str, Any]) -> float:
    current = position.get("executable_ask_price")
    if current is None:
        current = position.get("current_price")
    return _safe_float(current) - _safe_float(position.get("average_entry_price"))


def _is_actionable(position: dict[str, Any], now: datetime) -> bool:
    if str(position.get("status") or "open").lower() != "open":
        return False
    if (
        position.get("lifecycle_status")
        and position.get("lifecycle_status") != "upcoming"
    ):
        return False
    if "market_open" in position and position.get("market_open") is not True:
        return False
    if position.get("clob_token_id") and not position.get("executable_ask_price"):
        return False
    event_time = _safe_datetime(position.get("resolution_time"))
    return bool(event_time and event_time > now)


def _is_playable_size(
    position: dict[str, Any],
    unit_map: dict[str, dict[str, Any]],
    events_by_wallet: dict[str, list[dict[str, Any]]],
) -> bool:
    units = _relative_units(position, unit_map, events_by_wallet)
    return (
        units is not None
        and units > _minimum_units(position)
        and _position_signal_amount(position) > 0
    )


def _is_actionable_wallet_position(
    position: dict[str, Any],
    unit_map: dict[str, dict[str, Any]],
    events_by_wallet: dict[str, list[dict[str, Any]]],
) -> bool:
    units = _relative_units(position, unit_map, events_by_wallet)
    return units is not None and units >= _actionable_units(position)


def _format_event_time(value: Any) -> dict[str, str | None]:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped and "T" not in stripped and " " not in stripped:
            return {"event_time_et": None, "event_date_et": None}
    parsed = _safe_datetime(value)
    if not parsed:
        return {"event_time_et": None, "event_date_et": None}
    eastern = parsed.astimezone(EASTERN)
    hour = eastern.strftime("%I").lstrip("0") or "0"
    return {
        "event_time_et": f"{eastern.strftime('%b')} {eastern.day}, {eastern.year} - {hour}:{eastern.strftime('%M %p')} ET",
        "event_date_et": eastern.isoformat(),
    }


def _primary_position(
    group: list[dict[str, Any]],
    unit_map: dict[str, dict[str, Any]],
    events_by_wallet: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    def category_record(position: dict[str, Any]) -> tuple[float, int]:
        metric = position.get("category_metrics") or {}
        return (
            _safe_float(metric.get("adjusted_hit_rate"), 0.5),
            int(metric.get("sample_size") or 0),
        )

    largest_amount = max(
        _position_signal_amount(position) for position in group
    )
    materially_similar = [
        position
        for position in group
        if _position_signal_amount(position)
        >= largest_amount * (1.0 - PRIMARY_AMOUNT_SIMILARITY_RATIO)
    ]
    return max(
        materially_similar,
        key=lambda position: (
            _relative_units(position, unit_map, events_by_wallet) or 0,
            category_record(position),
            _position_signal_amount(position),
        ),
    )


def _amount_weighted_entry(positions: list[dict[str, Any]]) -> float:
    weighted_total = 0.0
    amount_total = 0.0
    for position in positions:
        amount = _position_signal_amount(position)
        entry = _safe_float(position.get("average_entry_price"))
        if amount <= 0 or not 0 < entry < 1:
            continue
        weighted_total += entry * amount
        amount_total += amount
    return weighted_total / amount_total if amount_total > 0 else 0.0


def _exclusion_record(
    group: list[dict[str, Any]], reason: str, trade_category_id: str | None = None
) -> dict[str, Any]:
    primary = max(
        group,
        key=_position_signal_amount,
    )
    return {
        "reason": reason,
        "event_id": primary.get("event_id"),
        "event_slug": primary.get("event_slug"),
        "market_id": primary.get("market_id"),
        "condition_id": primary.get("condition_id"),
        "outcome_id": primary.get("clob_token_id"),
        "outcome": primary.get("outcome"),
        "event_title": primary.get("event_title"),
        "market_title": primary.get("market_title"),
        "canonical_category_id": trade_category_id,
        "aggregated_cost_basis": _safe_float(primary.get("position_size_usd")),
        "signal_cost_basis": _position_signal_amount(primary),
        "calculated_units": primary.get("signal_units")
        or primary.get("position_units"),
        "opposing_exposure_usd": _safe_float(
            primary.get("opposing_exposure_usd")
        ),
        "net_directional_exposure_usd": _safe_float(
            primary.get("net_directional_exposure_usd")
        ),
        "wallet_hedge_status": primary.get("wallet_hedge_status"),
        "fill_count": int(primary.get("deduplicated_fill_count") or 0),
        "wallets": [
            {
                "wallet_address": position.get("wallet_address"),
                "wallet_label": position.get("wallet_label"),
                "top_category_ids": _category_profile(position)[
                    "top_category_ids"
                ],
            }
            for position in group
        ],
    }


def _collapse_unique_wallets(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_wallet: dict[str, dict[str, Any]] = {}
    for position in group:
        wallet = str(position.get("wallet_address") or "").lower()
        existing = by_wallet.get(wallet)
        if not existing:
            by_wallet[wallet] = position
            continue
        existing_time = str(
            existing.get("last_changed_at") or existing.get("first_detected_at") or ""
        )
        position_time = str(
            position.get("last_changed_at") or position.get("first_detected_at") or ""
        )
        if position_time > existing_time or _position_signal_amount(
            position
        ) > _position_signal_amount(existing):
            by_wallet[wallet] = position
    return list(by_wallet.values())


def _search_blob(play: dict[str, Any]) -> str:
    values = [
        play.get("event_title"),
        play.get("market_title"),
        play.get("outcome"),
        play.get("category"),
        play.get("league"),
        play.get("event_slug"),
        play.get("canonical_market_key"),
        play.get("canonical_side_key"),
        play.get("primary_trader", {}).get("wallet_label"),
    ]
    for supporter in play.get("supporting_wallets", []):
        values.append(supporter.get("wallet_label"))
    tokens: set[str] = set()
    for value in values:
        tokens.update(_search_tokens(value))
    return " ".join(sorted(tokens))


def _date_window(
    mode: str, now: datetime, start: str | None = None, end: str | None = None
) -> tuple[datetime | None, datetime | None]:
    now_et = now.astimezone(EASTERN)
    if mode == "today":
        day = now_et.date()
        return datetime.combine(day, time.min, EASTERN), datetime.combine(
            day, time.max, EASTERN
        )
    if mode == "next24":
        return now_et, now_et + timedelta(hours=24)
    if mode == "next7":
        return now_et, now_et + timedelta(days=7)
    if mode == "custom":
        try:
            start_dt = datetime.fromisoformat(start) if start else None
            end_dt = datetime.fromisoformat(end) if end else None
        except ValueError:
            return None, None
        if start_dt and start and "T" not in start and " " not in start:
            start_dt = datetime.combine(start_dt.date(), time.min)
        if end_dt and end and "T" not in end and " " not in end:
            end_dt = datetime.combine(end_dt.date(), time.max)
        if start_dt and start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=EASTERN)
        if end_dt and end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=EASTERN)
        return start_dt, end_dt
    if mode == "":
        return None, None
    return None, None


def filter_trades_to_play(
    plays: list[dict[str, Any]],
    *,
    search: str = "",
    min_sharps: int = 0,
    date_range: str = "",
    custom_start: str | None = None,
    custom_end: str | None = None,
    min_confidence: int = 0,
    sport: str = "",
    league: str = "",
    wallet: str = "",
    classification: str = "",
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    if date_range not in {"", "today", "next24", "next7", "custom"}:
        return []
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    query_tokens = _search_tokens(search) if search else set()
    start, end = _date_window(date_range, now, custom_start, custom_end)

    filtered: list[dict[str, Any]] = []
    for play in plays:
        if not canonical_category_id(play.get("canonical_category_id")):
            continue
        if not play.get("tradeClassification"):
            if int(play.get("lead_sharp_count") or 0) < 1:
                continue
            play["tradeClassification"] = "STANDARD"
            play["isResearchOnly"] = False
        if classification:
            current = str(play.get("tradeClassification") or "")
            if classification == "RESEARCH_ONLY":
                if not play.get("isResearchOnly"):
                    continue
            elif current != classification:
                continue
        if min_sharps and int(play.get("agreeing_wallet_count") or 0) < min_sharps:
            continue
        if min_confidence and int(play.get("confidence_score") or 0) < min_confidence:
            continue
        if sport and str(play.get("category") or "") != sport:
            continue
        if league and str(play.get("league") or "") != league:
            continue
        if wallet and not any(
            supporter.get("wallet_label") == wallet
            or str(supporter.get("wallet_address") or "").lower() == wallet.lower()
            for supporter in play.get("supporting_wallets", [])
        ):
            continue
        if query_tokens and not query_tokens.intersection(
            set(str(play.get("search_blob") or "").split())
        ):
            continue
        event_time = _safe_datetime(play.get("event_date_et"))
        if not event_time or event_time <= now:
            continue
        if (start or end) and not event_time:
            continue
        if event_time:
            event_et = event_time.astimezone(EASTERN)
            if start and event_et < start:
                continue
            if end and event_et > end:
                continue
        filtered.append(play)
    return filtered


def build_trades_to_play(
    positions: list[dict[str, Any]],
    trades: list[dict[str, Any]] | None = None,
    unit_map: dict[str, dict[str, Any]] | None = None,
    now: datetime | None = None,
    tracked_wallet_count: int | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    unit_map = {str(key).lower(): value for key, value in (unit_map or {}).items()}
    trades = trades or []
    events_by_wallet: dict[str, list[dict[str, Any]]] = {}
    for event in trades:
        events_by_wallet.setdefault(
            str(event.get("wallet_address") or "").lower(), []
        ).append(event)

    diagnostics = diagnostics if diagnostics is not None else []
    market_sides: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for position in positions:
        rejection_reason = position.get("signal_rejection_reason")
        if rejection_reason:
            diagnostics.append(_exclusion_record([position], str(rejection_reason)))
            continue
        if not _is_actionable(position, now):
            continue
        if not _is_playable_size(position, unit_map, events_by_wallet):
            if position.get("actionable_position_units") is not None:
                diagnostics.append(
                    _exclusion_record(
                        [position], BELOW_WALLET_ACTIONABLE_THRESHOLD
                    )
                )
            continue
        if not _is_actionable_wallet_position(position, unit_map, events_by_wallet):
            diagnostics.append(
                _exclusion_record([position], BELOW_WALLET_ACTIONABLE_THRESHOLD)
            )
            continue
        side = canonical_side(position)
        market_sides.setdefault(side.market_key, {}).setdefault(
            side.side_key, []
        ).append(position)

    playable_groups: list[
        tuple[list[dict[str, Any]], list[dict[str, Any]], str]
    ] = []
    missing_category_wallets: set[str] = set()
    for sides in market_sides.values():
        for side_key, group in sides.items():
            unique_group = _collapse_unique_wallets(group)
            opposing_group = _collapse_unique_wallets(
                [
                    position
                    for other_side, other_positions in sides.items()
                    if other_side != side_key
                    for position in other_positions
                ]
            )
            profiles = [_category_profile(position) for position in unique_group]
            trade_category_id = profiles[0]["trade_category_id"] if profiles else None
            for position, profile in zip(unique_group, profiles):
                if not profile["top_category_ids"]:
                    missing_category_wallets.add(
                        str(
                            position.get("wallet_label")
                            or position.get("wallet_address")
                            or "unknown wallet"
                        )
                    )
            if not trade_category_id:
                diagnostics.append(
                    _exclusion_record(
                        unique_group, UNRESOLVED_TRADE_CATEGORY, trade_category_id
                    )
                )
                continue
            lead_count = sum(1 for profile in profiles if profile["is_lead_sharp"])
            classification = classify_trade(
                len(unique_group), len(opposing_group), lead_count
            )
            if classification is None:
                if opposing_group:
                    reason = (
                        "TIED_SHARPS"
                        if len(unique_group) == len(opposing_group)
                        else "CONTRADICTING_SIDE_MAJORITY"
                        if len(unique_group) < len(opposing_group)
                        else "INSUFFICIENT_AGREEING_MAJORITY"
                    )
                else:
                    reason = "SINGLE_NON_CATEGORY_WALLET"
                diagnostics.append(
                    _exclusion_record(unique_group, reason, trade_category_id)
                )
                continue
            playable_groups.append((unique_group, opposing_group, classification))

    if missing_category_wallets:
        LOGGER.warning(
            "Wallets without a verified top category were limited to Supporting Sharp weight: %s",
            ", ".join(sorted(missing_category_wallets)),
        )

    group_amounts = [
        sum(_position_signal_amount(position) for position in group)
        for group, _opposing, _classification in playable_groups
    ]
    historical_amounts = [
        abs(_safe_float(event.get("position_size_usd") or event.get("delta_usd")))
        for event in trades
        if abs(_safe_float(event.get("position_size_usd") or event.get("delta_usd")))
        > 0
    ]
    benchmark_samples = group_amounts + historical_amounts
    amount_benchmark = max(
        _percentile(benchmark_samples, 0.9),
        median(benchmark_samples) if benchmark_samples else 0,
        1.0,
    )

    output: list[dict[str, Any]] = []
    for group, opposing_group, classification in playable_groups:
        unique_wallets = {
            str(position.get("wallet_address") or "").lower()
            for position in group
            if position.get("wallet_address")
        }
        wallet_count = len(unique_wallets)
        profiles_by_wallet = {
            str(position.get("wallet_address") or "").lower(): _category_profile(
                position
            )
            for position in group
        }
        lead_positions = [
            position
            for position in group
            if profiles_by_wallet[
                str(position.get("wallet_address") or "").lower()
            ]["is_lead_sharp"]
        ]
        supporting_positions = [
            position
            for position in group
            if not profiles_by_wallet[
                str(position.get("wallet_address") or "").lower()
            ]["is_lead_sharp"]
        ]
        lead_sharp_count = len(lead_positions)
        supporting_sharp_count = len(supporting_positions)
        supporting_weight = (
            0.25
            if classification in {SHARP_NON_CATEGORY, CONTRADICTING_NON_CATEGORY}
            else 0.5
        )
        weighted_sharp_count = lead_sharp_count + (
            supporting_sharp_count * supporting_weight
        )
        category_weights = {
            wallet: (1.0 if profile["is_lead_sharp"] else supporting_weight)
            for wallet, profile in profiles_by_wallet.items()
        }
        total_amount = sum(
            _position_signal_amount(position) for position in group
        )
        weighted_total_amount = sum(
            _position_signal_amount(position)
            * category_weights[
                str(position.get("wallet_address") or "").lower()
            ]
            for position in group
        )
        primary = _primary_position(
            lead_positions or group, unit_map, events_by_wallet
        )
        units_by_wallet = {
            str(position.get("wallet_address") or "").lower(): (
                _relative_units(position, unit_map, events_by_wallet) or 0
            )
            for position in group
        }
        strongest_units = max(units_by_wallet.values())
        primary_wallet = str(primary.get("wallet_address") or "").lower()
        primary_units = units_by_wallet[primary_wallet]
        average_units = sum(units_by_wallet.values()) / len(group)
        weighted_strongest_units = max(
            units * category_weights[wallet]
            for wallet, units in units_by_wallet.items()
        )
        weighted_average_units = sum(
            units * category_weights[wallet]
            for wallet, units in units_by_wallet.items()
        ) / weighted_sharp_count
        weighted_conviction_units = (
            (primary_units * 0.40)
            + (min(weighted_strongest_units, 10) * 0.35)
            + (min(weighted_average_units, 10) * 0.25)
        )
        sample_size = _sample_size(primary, events_by_wallet)
        adjusted_hit_rate = _adjusted_hit_rate(primary, sample_size)
        weighted_sample_total = sum(
            _sample_size(position, events_by_wallet)
            * category_weights[
                str(position.get("wallet_address") or "").lower()
            ]
            for position in group
        )
        group_hit_rate = _weighted_hit_rate(
            group, events_by_wallet, category_weights
        )
        slippage = _slippage(primary)

        canonical = canonical_side(primary)
        event_time = _format_event_time(primary.get("resolution_time"))
        sharp_average_entry = _amount_weighted_entry(lead_positions or group) or _safe_float(
            primary.get("average_entry_price")
        )
        category_metrics = []
        for position in group:
            metric = position.get("category_metrics")
            if not metric:
                continue
            wallet = str(position.get("wallet_address") or "").lower()
            category_metrics.append(
                {
                    **metric,
                    "wallet_address": position.get("wallet_address"),
                    "wallet_label": position.get("wallet_label"),
                    "category_weight": category_weights[wallet],
                }
            )
        category_sample_total = sum(
            int(metric.get("sample_size") or 0) for metric in category_metrics
        )
        weighted_category_sample_total = sum(
            int(metric.get("sample_size") or 0)
            * _safe_float(metric.get("category_weight"), 0.5)
            for metric in category_metrics
        )
        category_hit_rate = None
        if weighted_category_sample_total > 0:
            category_hit_rate = (
                sum(
                    _safe_float(metric.get("adjusted_hit_rate"), 0.5)
                    * int(metric.get("sample_size") or 0)
                    * _safe_float(metric.get("category_weight"), 0.5)
                    for metric in category_metrics
                )
                / weighted_category_sample_total
            )
        weighted_amount_signal = _log_score(
            weighted_total_amount, amount_benchmark
        )
        weighted_relative_size_signal = _log_score(weighted_conviction_units, 5)
        weighted_history_signal = _log_score(weighted_sample_total, 1000)
        confidence, breakdown = _confidence_score(
            wallet_count=wallet_count,
            lead_sharp_count=lead_sharp_count,
            supporting_sharp_count=supporting_sharp_count,
            weighted_sharp_count=weighted_sharp_count,
            tracked_wallet_count=tracked_wallet_count,
            combined_amount_signal=weighted_amount_signal,
            relative_size_signal=weighted_relative_size_signal,
            trader_history_signal=weighted_history_signal,
            adjusted_hit_rate=adjusted_hit_rate,
            group_hit_rate=(
                category_hit_rate
                if category_hit_rate is not None
                else group_hit_rate
            ),
            slippage=slippage,
        )
        classification_meta = classification_fields(
            classification, wallet_count, len(opposing_group)
        )
        if classification_meta["isResearchOnly"]:
            confidence = research_confidence(
                classification,
                wallet_count,
                len(opposing_group),
                (
                    weighted_amount_signal
                    + weighted_relative_size_signal
                    + weighted_history_signal
                )
                / 3,
            )
            breakdown = {
                **breakdown,
                "research_only": True,
                "classification": classification,
                "score_cap": classification_meta["confidenceScoreCap"],
                "majority_ratio": classification_meta["majorityRatio"],
                "net_sharp_majority": classification_meta["netSharpMajority"],
            }
        top_category_score = weighted_sharp_count / wallet_count
        evidence_inputs = {
            "combined_amount": weighted_amount_signal,
            "relative_size": weighted_relative_size_signal,
            "top_category": top_category_score,
            "adjusted_category_hit_rate": category_hit_rate,
            "category_sample_size": _log_score(
                weighted_category_sample_total, 500
            )
            if weighted_category_sample_total
            else None,
            "raw_sharp_count": wallet_count,
            "lead_sharp_count": lead_sharp_count,
            "supporting_sharp_count": supporting_sharp_count,
            "weighted_sharp_count": weighted_sharp_count,
            "actual_combined_amount": total_amount,
            "weighted_combined_amount": weighted_total_amount,
            "weighted_amount_signal": weighted_amount_signal,
            "weighted_relative_size_signal": weighted_relative_size_signal,
            "weighted_history_signal": weighted_history_signal,
            "actual_category_sample_size": category_sample_total,
            "weighted_category_sample_size": weighted_category_sample_total,
            "relative_size_details": {
                "primary_units": primary_units,
                "strongest_units": strongest_units,
                "average_units": average_units,
                "weighted_strongest_units": weighted_strongest_units,
                "weighted_average_units": weighted_average_units,
                "weighted_conviction_units": weighted_conviction_units,
            },
            "category_details": category_metrics,
            "amount_benchmark_p90": amount_benchmark,
        }
        supporters = []
        for position in group:
            wallet = str(position.get("wallet_address") or "").lower()
            profile = profiles_by_wallet[wallet]
            units = units_by_wallet[wallet]
            supporters.append(
                {
                    "wallet_address": position.get("wallet_address"),
                    "wallet_label": position.get("wallet_label"),
                    "amount": _position_signal_amount(position),
                    "gross_amount": _safe_float(position.get("position_size_usd")),
                    "relative_units": units,
                    "average_entry_price": position.get("average_entry_price"),
                    "current_price": position.get("current_price"),
                    "shares": position.get("shares") or position.get("token_units"),
                    "minimum_position_units": position.get("minimum_position_units"),
                    "actionable_position_units": position.get(
                        "actionable_position_units"
                    ),
                    "signal_tier": position.get("signal_tier"),
                    "top_category": position.get("configured_top_category")
                    or position.get("top_category"),
                    "sub_top_categories": position.get(
                        "configured_sub_top_categories"
                    )
                    or position.get("wallet_sub_top_categories")
                    or [],
                    "top_category_ids": profile["top_category_ids"],
                    "sub_top_category_ids": position.get(
                        "configured_sub_top_category_ids"
                    )
                    or [],
                    "primary_top_category_id": profile[
                        "primary_top_category_id"
                    ],
                    "top_category_source": profile["top_category_source"],
                    "top_category_verified_at": profile[
                        "top_category_verified_at"
                    ],
                    "is_lead_sharp": profile["is_lead_sharp"],
                    "sharp_role": profile["sharp_role"],
                    "category_match": profile["is_lead_sharp"],
                    "category_weight": profile["category_weight"],
                    "weighted_amount_contribution": _position_signal_amount(position)
                    * profile["category_weight"],
                    "weighted_relative_contribution": units
                    * profile["category_weight"],
                    "bettor_type": position.get("wallet_bettor_type"),
                    "selectivity": position.get("wallet_selectivity"),
                    "selectivity_score": position.get("wallet_selectivity_score"),
                    "hold_tendency": position.get("wallet_hold_tendency"),
                    "copyability": position.get("wallet_copyability"),
                    "last_changed_at": position.get("last_changed_at"),
                    "wallet_profile_url": position.get("wallet_profile_url"),
                    "category_metrics": position.get("category_metrics"),
                    "source": "active_position_snapshot",
                }
            )
        supporters.sort(
            key=lambda item: (
                not item["is_lead_sharp"],
                -item["amount"],
                -(item["relative_units"] or 0),
                str(item["wallet_label"]).lower(),
            ),
        )
        contradictors = [
            {
                "wallet_address": position.get("wallet_address"),
                "wallet_label": position.get("wallet_label"),
                "opposing_selection": position.get("outcome"),
                "amount": _position_signal_amount(position),
                "gross_amount": _safe_float(position.get("position_size_usd")),
                "relative_units": _relative_units(
                    position, unit_map, events_by_wallet
                )
                or 0,
                "average_entry_price": position.get("average_entry_price"),
                "current_price": position.get("current_price"),
                "top_category": position.get("configured_top_category")
                or position.get("top_category"),
                "wallet_profile_url": position.get("wallet_profile_url"),
                "source": "active_position_snapshot",
            }
            for position in opposing_group
        ]
        contradictors.sort(
            key=lambda item: (
                -item["amount"],
                -item["relative_units"],
                str(item["wallet_label"]).lower(),
            )
        )

        play = {
            "id": f"{canonical.market_key}::{canonical.side_key}",
            "canonical_market_key": canonical.market_key,
            "canonical_side_key": canonical.side_key,
            "source": "active_position_snapshot",
            "validation_ids": {
                "event_id": primary.get("event_id"),
                "event_slug": primary.get("event_slug"),
                "condition_id": primary.get("condition_id"),
                "market_slug": primary.get("market_slug"),
                "outcome": primary.get("outcome"),
                "outcome_token_id": primary.get("clob_token_id"),
                "event_time_source": primary.get("event_time_source") or "unknown",
                "wallet_addresses": sorted(unique_wallets),
            },
            "confidence_score": confidence,
            "confidenceScore": confidence,
            "score_breakdown": breakdown,
            "score_weights": SECONDARY_SCORE_WEIGHTS,
            "tracked_wallet_count": tracked_wallet_count,
            "sharps_badge": sharps_badge(wallet_count),
            "agreeing_wallet_count": wallet_count,
            "rawAgreeingSharpCount": wallet_count,
            "rawContradictingSharpCount": len(opposing_group),
            "raw_sharp_count": wallet_count,
            "lead_sharp_count": lead_sharp_count,
            "supporting_sharp_count": supporting_sharp_count,
            "weighted_sharp_count": weighted_sharp_count,
            "weightedAgreeingConsensus": weighted_sharp_count,
            "weightedContradictingConsensus": float(len(opposing_group)),
            "has_lead_sharp": lead_sharp_count > 0,
            "lead_wallet_ids": sorted(
                str(position.get("wallet_address") or "").lower()
                for position in lead_positions
            ),
            "supporting_wallet_ids": sorted(
                str(position.get("wallet_address") or "").lower()
                for position in supporting_positions
            ),
            "primary_lead_wallet_id": primary_wallet,
            "agreeingWalletIds": sorted(unique_wallets),
            "contradictingWalletIds": sorted(
                str(position.get("wallet_address") or "").lower()
                for position in opposing_group
                if position.get("wallet_address")
            ),
            "leadWalletIds": sorted(
                str(position.get("wallet_address") or "").lower()
                for position in lead_positions
            ),
            "supportingWalletIds": sorted(
                str(position.get("wallet_address") or "").lower()
                for position in supporting_positions
            ),
            "category_match_by_wallet": {
                wallet: profile["is_lead_sharp"]
                for wallet, profile in profiles_by_wallet.items()
            },
            "category_weight_by_wallet": category_weights,
            "weighted_consensus_score": weighted_sharp_count,
            "weighted_amount_signal": weighted_amount_signal,
            "weighted_relative_size_signal": weighted_relative_size_signal,
            "market_title": primary.get("market_title"),
            "event_title": primary.get("event_title") or primary.get("market_title"),
            "outcome": primary.get("outcome"),
            "category": primary.get("category"),
            "league": primary.get("league"),
            "canonical_sport_id": primary.get("canonical_sport_id")
            or canonical_category_id(primary.get("category")),
            "canonical_league_id": primary.get("canonical_league_id")
            or canonical_category_id(primary.get("league")),
            "canonical_category_id": primary.get("canonical_category_id")
            or canonical_category_id(primary.get("category")),
            "event_slug": primary.get("event_slug"),
            "event_time_source": primary.get("event_time_source") or "unknown",
            "market_url": primary.get("market_url"),
            "current_price": primary.get("executable_ask_price")
            or primary.get("current_price"),
            "snapshot_current_price": primary.get("current_price"),
            "current_price_source": primary.get("executable_price_source")
            or "active_position_snapshot",
            "clob_token_id": primary.get("clob_token_id"),
            "orderbook": primary.get("orderbook") or {},
            "orderbook_timestamp": primary.get("orderbook_timestamp"),
            "market_line": primary.get("market_line"),
            "sports_market_type": primary.get("sports_market_type"),
            "market_open": primary.get("market_open"),
            "lifecycle_status": primary.get("lifecycle_status"),
            "lifecycle_reason": primary.get("lifecycle_reason"),
            "average_entry_price": round(sharp_average_entry, 6),
            "sharp_reference_entry_price": round(sharp_average_entry, 6),
            "sharp_reference_method": (
                "amount_weighted_lead_sharps"
                if lead_positions
                else "amount_weighted_research_consensus"
            ),
            "slippage": round(slippage, 4),
            "total_amount_bet": round(total_amount, 6),
            "combined_exposure_exact": total_amount,
            "agreeingExposureDollars": total_amount,
            "contradictingExposureDollars": sum(
                _position_signal_amount(position) for position in opposing_group
            ),
            "strongest_relative_units": strongest_units,
            "evidence_inputs": evidence_inputs,
            "primary_trader": {
                "wallet_address": primary.get("wallet_address"),
                "wallet_label": primary.get("wallet_label"),
                "amount": _position_signal_amount(primary),
                "gross_amount": _safe_float(primary.get("position_size_usd")),
                "relative_units": _relative_units(primary, unit_map, events_by_wallet),
                "minimum_position_units": primary.get("minimum_position_units"),
                "actionable_position_units": primary.get("actionable_position_units"),
                "signal_tier": primary.get("signal_tier"),
                "top_category": primary.get("configured_top_category")
                or primary.get("top_category"),
                "top_category_ids": profiles_by_wallet[primary_wallet][
                    "top_category_ids"
                ],
                "primary_top_category_id": profiles_by_wallet[primary_wallet][
                    "primary_top_category_id"
                ],
                "top_category_source": profiles_by_wallet[primary_wallet][
                    "top_category_source"
                ],
                "top_category_verified_at": profiles_by_wallet[primary_wallet][
                    "top_category_verified_at"
                ],
                "is_lead_sharp": bool(lead_positions),
                "is_research_anchor": not bool(lead_positions),
                "sharp_role": "Lead Sharp" if lead_positions else "Research Anchor",
                "category_match": bool(lead_positions),
                "category_weight": 1.0 if lead_positions else supporting_weight,
                "bettor_type": primary.get("wallet_bettor_type"),
                "selectivity": primary.get("wallet_selectivity"),
                "selectivity_score": primary.get("wallet_selectivity_score"),
                "hold_tendency": primary.get("wallet_hold_tendency"),
                "copyability": primary.get("wallet_copyability"),
                "wallet_profile_url": primary.get("wallet_profile_url"),
                "sample_size": sample_size,
                "adjusted_hit_rate": round(adjusted_hit_rate, 4),
                "source": "active_position_snapshot",
            },
            "supporting_wallets": supporters,
            "contradicting_wallets": contradictors,
            **classification_meta,
            "first_detected_at": min(
                position.get("first_detected_at") or "" for position in group
            ),
            "last_changed_at": max(
                position.get("last_changed_at")
                or position.get("first_detected_at")
                or ""
                for position in group
            ),
            "entered_at": max(
                position.get("first_detected_at") or "" for position in group
            ),
            **event_time,
        }
        play["search_blob"] = _search_blob(play)
        output.append(play)

    output.sort(
        key=lambda item: (
            -item["confidence_score"],
            -item["agreeing_wallet_count"],
            -item["total_amount_bet"],
            item["market_title"] or "",
        )
    )
    return output
