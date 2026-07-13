from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

SECONDARY_SCORE_WEIGHTS = {
    "combined_amount": 0.35,
    "relative_size": 0.30,
    "trader_history": 0.20,
    "adjusted_hit_rate": 0.10,
    "slippage": 0.05,
}


TRADER_STATS = {
    "1winstreak1": {"total_trades": 12899, "hit_rate": 0.612},
    "0xbca08c1bc204a34f2fddbe47b438b9bd42ac9705": {"total_trades": 12899, "hit_rate": 0.612},
    "0x4f2": {"total_trades": 7225, "hit_rate": 0.555},
    "0x4f29e103339919c4baaea2a60195cf1c8bb27a7e": {"total_trades": 7225, "hit_rate": 0.555},
}

EASTERN = ZoneInfo("America/New_York")
MIN_PLAYABLE_UNITS = 0.2

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


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


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
                _normalize_text(position.get("market_slug") or position.get("market_title")),
            ]
        )
    return CanonicalSide(market_key=market_key, side_key=_normalize_text(position.get("outcome")))


def sharps_badge(wallet_count: int) -> str | None:
    if wallet_count < 2:
        return None
    names = {2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten"}
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


def _consensus_band(wallet_count: int, tracked_wallet_count: int | None) -> dict[str, Any]:
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
        raw_progress = max(0.0, min(1.0, (wallet_count - 3) / (tracked_wallet_count - 3)))
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


def _weighted_hit_rate(group: list[dict[str, Any]], events_by_wallet: dict[str, list[dict[str, Any]]]) -> float:
    total_samples = 0
    weighted_rate = 0.0
    for position in group:
        sample = _sample_size(position, events_by_wallet)
        rate = _adjusted_hit_rate(position, sample)
        total_samples += sample
        weighted_rate += rate * sample
    return weighted_rate / total_samples if total_samples > 0 else 0.5


def _confidence_score(
    *,
    wallet_count: int,
    tracked_wallet_count: int | None,
    total_amount: float,
    amount_benchmark: float,
    primary_units: float,
    strongest_units: float,
    average_units: float,
    sample_size: int,
    adjusted_hit_rate: float,
    group_hit_rate: float,
    slippage: float,
) -> tuple[int, dict[str, Any]]:
    band = _consensus_band(wallet_count, tracked_wallet_count)
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
            "combined_amount": 1.0,
            "relative_size": 1.0,
            "trader_history": 1.0,
            "adjusted_hit_rate": 1.0,
            "slippage": 1.0,
            "explanation": "Complete tracked-wallet agreement. Every enabled tracked wallet has an active position on this exact side.",
        }

    conviction_units = (primary_units * 0.40) + (min(strongest_units, 10) * 0.35) + (min(average_units, 10) * 0.25)
    hit_rate_quality = _curve(max(((adjusted_hit_rate * 0.7) + (group_hit_rate * 0.3)) - 0.5, 0), 0.15)
    components = {
        "combined_amount": _log_score(total_amount, amount_benchmark),
        "relative_size": _log_score(conviction_units, 5),
        "trader_history": _log_score(sample_size, 1000),
        "adjusted_hit_rate": hit_rate_quality,
        "slippage": _slippage_quality(slippage),
    }
    secondary_quality = sum(components[key] * SECONDARY_SCORE_WEIGHTS[key] for key in SECONDARY_SCORE_WEIGHTS)
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
        "combined_amount": round(components["combined_amount"], 4),
        "relative_size": round(components["relative_size"], 4),
        "trader_history": round(components["trader_history"], 4),
        "adjusted_hit_rate": round(components["adjusted_hit_rate"], 4),
        "slippage": round(components["slippage"], 4),
        "explanation": f"{band['description']} Secondary metrics placed it at {score} within that consensus range.",
    }


def _trader_stat(position: dict[str, Any], field: str) -> Any:
    label = str(position.get("wallet_label") or "").lower()
    address = str(position.get("wallet_address") or "").lower()
    return (TRADER_STATS.get(label) or TRADER_STATS.get(address) or {}).get(field)


def _historical_samples(position: dict[str, Any], events_by_wallet: dict[str, list[dict[str, Any]]]) -> list[float]:
    samples = []
    for event in events_by_wallet.get(str(position.get("wallet_address") or "").lower(), []):
        amount = abs(_safe_float(event.get("position_size_usd") or event.get("delta_usd")))
        if amount > 0:
            samples.append(amount)
    return samples


def _relative_units(
    position: dict[str, Any],
    unit_map: dict[str, dict[str, Any]],
    events_by_wallet: dict[str, list[dict[str, Any]]],
) -> float | None:
    amount = _safe_float(position.get("position_size_usd"))
    wallet = str(position.get("wallet_address") or "").lower()
    base_unit = unit_map.get(wallet, {}).get("estimated_base_unit") or position.get("estimated_base_unit")
    if base_unit and _safe_float(base_unit) > 0:
        return amount / _safe_float(base_unit)
    samples = _historical_samples(position, events_by_wallet)
    baseline = median(samples) if samples else 0
    return amount / baseline if baseline > 0 else None


def _sample_size(position: dict[str, Any], events_by_wallet: dict[str, list[dict[str, Any]]]) -> int:
    manual = _trader_stat(position, "total_trades")
    if manual:
        return int(manual)
    return len(events_by_wallet.get(str(position.get("wallet_address") or "").lower(), []))


def _adjusted_hit_rate(position: dict[str, Any], sample_size: int) -> float:
    hit_rate = _trader_stat(position, "hit_rate")
    if hit_rate is None:
        return 0.5
    prior_rate = 0.52
    prior_samples = 100
    wins = float(hit_rate) * max(sample_size, 0)
    return (wins + prior_rate * prior_samples) / (max(sample_size, 0) + prior_samples)


def _slippage(position: dict[str, Any]) -> float:
    return _safe_float(position.get("current_price")) - _safe_float(position.get("average_entry_price"))


def _is_actionable(position: dict[str, Any], now: datetime) -> bool:
    if str(position.get("status") or "open").lower() != "open":
        return False
    event_time = _safe_datetime(position.get("resolution_time"))
    return bool(event_time and event_time > now)


def _is_playable_size(position: dict[str, Any], unit_map: dict[str, dict[str, Any]], events_by_wallet: dict[str, list[dict[str, Any]]]) -> bool:
    units = _relative_units(position, unit_map, events_by_wallet)
    return units is not None and units > MIN_PLAYABLE_UNITS and _safe_float(position.get("position_size_usd")) > 0


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


def _primary_position(group: list[dict[str, Any]], unit_map: dict[str, dict[str, Any]], events_by_wallet: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return max(
        group,
        key=lambda position: (
            _safe_float(position.get("position_size_usd")),
            _relative_units(position, unit_map, events_by_wallet) or 0,
        ),
    )


def _collapse_unique_wallets(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_wallet: dict[str, dict[str, Any]] = {}
    for position in group:
        wallet = str(position.get("wallet_address") or "").lower()
        existing = by_wallet.get(wallet)
        if not existing:
            by_wallet[wallet] = position
            continue
        existing_time = str(existing.get("last_changed_at") or existing.get("first_detected_at") or "")
        position_time = str(position.get("last_changed_at") or position.get("first_detected_at") or "")
        if position_time > existing_time or _safe_float(position.get("position_size_usd")) > _safe_float(existing.get("position_size_usd")):
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


def _date_window(mode: str, now: datetime, start: str | None = None, end: str | None = None) -> tuple[datetime | None, datetime | None]:
    now_et = now.astimezone(EASTERN)
    if mode == "today":
        day = now_et.date()
        return datetime.combine(day, time.min, EASTERN), datetime.combine(day, time.max, EASTERN)
    if mode == "tomorrow":
        day = now_et.date() + timedelta(days=1)
        return datetime.combine(day, time.min, EASTERN), datetime.combine(day, time.max, EASTERN)
    if mode == "next24":
        return now_et, now_et + timedelta(hours=24)
    if mode == "next48":
        return now_et, now_et + timedelta(hours=48)
    if mode == "week":
        days_until_sunday = 6 - now_et.weekday()
        end_day = now_et.date() + timedelta(days=days_until_sunday)
        return now_et, datetime.combine(end_day, time.max, EASTERN)
    if mode == "custom":
        try:
            start_dt = datetime.combine(datetime.fromisoformat(start).date(), time.min, EASTERN) if start else None
            end_dt = datetime.combine(datetime.fromisoformat(end).date(), time.max, EASTERN) if end else None
        except ValueError:
            return None, None
        return start_dt, end_dt
    if mode in {"all", ""}:
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
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    query_tokens = _search_tokens(search) if search else set()
    start, end = _date_window(date_range, now, custom_start, custom_end)

    filtered: list[dict[str, Any]] = []
    for play in plays:
        if min_sharps and int(play.get("agreeing_wallet_count") or 0) < min_sharps:
            continue
        if min_confidence and int(play.get("confidence_score") or 0) < min_confidence:
            continue
        if sport and str(play.get("category") or "") != sport:
            continue
        if league and str(play.get("league") or "") != league:
            continue
        if wallet and not any(
            supporter.get("wallet_label") == wallet or str(supporter.get("wallet_address") or "").lower() == wallet.lower()
            for supporter in play.get("supporting_wallets", [])
        ):
            continue
        if query_tokens and not query_tokens.intersection(set(str(play.get("search_blob") or "").split())):
            continue
        event_time = _safe_datetime(play.get("event_date_et"))
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
) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    unit_map = {str(key).lower(): value for key, value in (unit_map or {}).items()}
    trades = trades or []
    events_by_wallet: dict[str, list[dict[str, Any]]] = {}
    for event in trades:
        events_by_wallet.setdefault(str(event.get("wallet_address") or "").lower(), []).append(event)

    market_sides: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for position in positions:
        if not _is_actionable(position, now):
            continue
        if not _is_playable_size(position, unit_map, events_by_wallet):
            continue
        side = canonical_side(position)
        market_sides.setdefault(side.market_key, {}).setdefault(side.side_key, []).append(position)

    playable_groups: list[list[dict[str, Any]]] = []
    for sides in market_sides.values():
        # If tracked wallets hold opposing sides of the same market, no side is playable.
        if len(sides) == 1:
            playable_groups.extend(_collapse_unique_wallets(group) for group in sides.values())

    group_amounts = [sum(_safe_float(position.get("position_size_usd")) for position in group) for group in playable_groups]
    amount_benchmark = max(_percentile(group_amounts, 0.9), median(group_amounts) if group_amounts else 0, 1.0)

    output: list[dict[str, Any]] = []
    for group in playable_groups:
        unique_wallets = {str(position.get("wallet_address") or "").lower() for position in group if position.get("wallet_address")}
        wallet_count = len(unique_wallets)
        total_amount = sum(_safe_float(position.get("position_size_usd")) for position in group)
        primary = _primary_position(group, unit_map, events_by_wallet)
        strongest_units = max((_relative_units(position, unit_map, events_by_wallet) or 0) for position in group)
        primary_units = _relative_units(primary, unit_map, events_by_wallet) or 0
        average_units = sum((_relative_units(position, unit_map, events_by_wallet) or 0) for position in group) / len(group)
        sample_size = _sample_size(primary, events_by_wallet)
        adjusted_hit_rate = _adjusted_hit_rate(primary, sample_size)
        group_hit_rate = _weighted_hit_rate(group, events_by_wallet)
        slippage = _slippage(primary)

        confidence, breakdown = _confidence_score(
            wallet_count=wallet_count,
            tracked_wallet_count=tracked_wallet_count,
            total_amount=total_amount,
            amount_benchmark=amount_benchmark,
            primary_units=primary_units,
            strongest_units=strongest_units,
            average_units=average_units,
            sample_size=sample_size,
            adjusted_hit_rate=adjusted_hit_rate,
            group_hit_rate=group_hit_rate,
            slippage=slippage,
        )
        canonical = canonical_side(primary)
        event_time = _format_event_time(primary.get("resolution_time"))
        supporters = sorted(
            [
                {
                    "wallet_address": position.get("wallet_address"),
                    "wallet_label": position.get("wallet_label"),
                    "amount": _safe_float(position.get("position_size_usd")),
                    "relative_units": _relative_units(position, unit_map, events_by_wallet),
                    "average_entry_price": position.get("average_entry_price"),
                    "current_price": position.get("current_price"),
                    "shares": position.get("shares") or position.get("token_units"),
                    "last_changed_at": position.get("last_changed_at"),
                    "wallet_profile_url": position.get("wallet_profile_url"),
                    "source": "active_position_snapshot",
                }
                for position in group
            ],
            key=lambda item: (-item["amount"], -(item["relative_units"] or 0), str(item["wallet_label"]).lower()),
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
                    "event_time_source": primary.get("event_time_source") or "unknown",
                    "wallet_addresses": sorted(unique_wallets),
                },
                "confidence_score": confidence,
                "score_breakdown": breakdown,
                "score_weights": SECONDARY_SCORE_WEIGHTS,
                "tracked_wallet_count": tracked_wallet_count,
                "sharps_badge": sharps_badge(wallet_count),
                "agreeing_wallet_count": wallet_count,
                "market_title": primary.get("market_title"),
                "event_title": primary.get("event_title") or primary.get("market_title"),
                "outcome": primary.get("outcome"),
                "category": primary.get("category"),
                "league": primary.get("league"),
                "event_slug": primary.get("event_slug"),
                "event_time_source": primary.get("event_time_source") or "unknown",
                "market_url": primary.get("market_url"),
                "current_price": primary.get("current_price"),
                "average_entry_price": round(sum(_safe_float(position.get("average_entry_price")) for position in group) / len(group), 4),
                "slippage": round(slippage, 4),
                "total_amount_bet": round(total_amount, 6),
                "combined_exposure_exact": total_amount,
                "strongest_relative_units": strongest_units,
                "primary_trader": {
                    "wallet_address": primary.get("wallet_address"),
                    "wallet_label": primary.get("wallet_label"),
                    "amount": _safe_float(primary.get("position_size_usd")),
                    "relative_units": _relative_units(primary, unit_map, events_by_wallet),
                    "wallet_profile_url": primary.get("wallet_profile_url"),
                    "sample_size": sample_size,
                    "adjusted_hit_rate": round(adjusted_hit_rate, 4),
                    "source": "active_position_snapshot",
                },
                "supporting_wallets": supporters,
                "first_detected_at": min(position.get("first_detected_at") or "" for position in group),
                "last_changed_at": max(position.get("last_changed_at") or position.get("first_detected_at") or "" for position in group),
                "entered_at": max(position.get("first_detected_at") or "" for position in group),
                **event_time,
            }
        play["search_blob"] = _search_blob(play)
        output.append(play)

    output.sort(key=lambda item: (-item["confidence_score"], -item["agreeing_wallet_count"], -item["total_amount_bet"], item["market_title"] or ""))
    return output
