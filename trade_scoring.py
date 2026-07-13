from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from unit_analysis import amount_to_units


CONFIDENCE_WEIGHTS = {
    "sharps": 35,
    "combined_amount": 25,
    "relative_size": 18,
    "trader_sample": 10,
    "hit_rate": 8,
    "slippage": 4,
}


TRADER_STATS = {
    "1winstreak1": {"total_trades": 12899, "hit_rate": 0.612},
    "0xbca08c1bc204a34f2fddbe47b438b9bd42ac9705": {"total_trades": 12899, "hit_rate": 0.612},
    "0x4f2": {"total_trades": 7225, "hit_rate": 0.555},
    "0x4f29e103339919c4baaea2a60195cf1c8bb27a7e": {"total_trades": 7225, "hit_rate": 0.555},
}

EASTERN = ZoneInfo("America/New_York")


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


def _curve(value: float, denominator: float, weight: int) -> float:
    if denominator <= 0:
        return 0.0
    return max(0.0, min(1.0, value / denominator)) * weight


def _log_score(value: float, benchmark: float, weight: int) -> float:
    if value <= 0 or benchmark <= 0:
        return 0.0
    return max(0.0, min(1.0, math.log1p(value) / math.log1p(benchmark))) * weight


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
) -> float:
    amount = _safe_float(position.get("position_size_usd"))
    wallet = str(position.get("wallet_address") or "").lower()
    base_unit = unit_map.get(wallet, {}).get("estimated_base_unit") or position.get("estimated_base_unit")
    units = amount_to_units(amount, base_unit)
    if units is not None:
        return float(units)
    samples = _historical_samples(position, events_by_wallet)
    baseline = median(samples) if samples else 0
    return amount / baseline if baseline > 0 else 0.0


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


def _format_event_time(value: Any) -> dict[str, str | None]:
    parsed = _safe_datetime(value)
    if not parsed:
        return {"event_time_et": None, "event_date_et": None}
    eastern = parsed.astimezone(EASTERN)
    hour = eastern.strftime("%I").lstrip("0") or "0"
    return {
        "event_time_et": f"{eastern.strftime('%b')} {eastern.day}, {eastern.year} · {hour}:{eastern.strftime('%M %p')} ET",
        "event_date_et": eastern.isoformat(),
    }


def _primary_position(group: list[dict[str, Any]], unit_map: dict[str, dict[str, Any]], events_by_wallet: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return max(
        group,
        key=lambda position: (
            _safe_float(position.get("position_size_usd")),
            _relative_units(position, unit_map, events_by_wallet),
        ),
    )


def build_trades_to_play(
    positions: list[dict[str, Any]],
    trades: list[dict[str, Any]] | None = None,
    unit_map: dict[str, dict[str, Any]] | None = None,
    now: datetime | None = None,
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
        side = canonical_side(position)
        market_sides.setdefault(side.market_key, {}).setdefault(side.side_key, []).append(position)

    playable_groups: list[list[dict[str, Any]]] = []
    for sides in market_sides.values():
        # If tracked wallets hold opposing sides of the same market, no side is playable.
        if len(sides) == 1:
            playable_groups.extend(sides.values())

    group_amounts = [sum(_safe_float(position.get("position_size_usd")) for position in group) for group in playable_groups]
    amount_benchmark = max(_percentile(group_amounts, 0.9), median(group_amounts) if group_amounts else 0, 1.0)

    output: list[dict[str, Any]] = []
    for group in playable_groups:
        unique_wallets = {str(position.get("wallet_address") or "").lower() for position in group if position.get("wallet_address")}
        wallet_count = len(unique_wallets)
        total_amount = round(sum(_safe_float(position.get("position_size_usd")) for position in group), 2)
        primary = _primary_position(group, unit_map, events_by_wallet)
        strongest_units = max(_relative_units(position, unit_map, events_by_wallet) for position in group)
        sample_size = _sample_size(primary, events_by_wallet)
        adjusted_hit_rate = _adjusted_hit_rate(primary, sample_size)
        slippage = _slippage(primary)

        sharps_points = (1 - math.exp(-max(wallet_count - 1, 0) / 1.35)) / (1 - math.exp(-4 / 1.35)) * CONFIDENCE_WEIGHTS["sharps"]
        amount_points = _log_score(total_amount, amount_benchmark, CONFIDENCE_WEIGHTS["combined_amount"])
        relative_points = _log_score(strongest_units, 5, CONFIDENCE_WEIGHTS["relative_size"])
        sample_points = _log_score(sample_size, 1000, CONFIDENCE_WEIGHTS["trader_sample"])
        hit_points = _curve(max(adjusted_hit_rate - 0.5, 0), 0.15, CONFIDENCE_WEIGHTS["hit_rate"])
        slippage_points = max(0.0, min(1.0, 1 - max(slippage, 0) / 0.15)) * CONFIDENCE_WEIGHTS["slippage"]

        breakdown = {
            "sharps_consensus": round(sharps_points, 1),
            "combined_amount": round(amount_points, 1),
            "relative_size": round(relative_points, 1),
            "trader_history": round(sample_points, 1),
            "adjusted_hit_rate": round(hit_points, 1),
            "slippage": round(slippage_points, 1),
        }
        confidence = round(sum(breakdown.values()))
        canonical = canonical_side(primary)
        event_time = _format_event_time(primary.get("resolution_time"))
        supporters = sorted(
            [
                {
                    "wallet_address": position.get("wallet_address"),
                    "wallet_label": position.get("wallet_label"),
                    "amount": round(_safe_float(position.get("position_size_usd")), 2),
                    "relative_units": round(_relative_units(position, unit_map, events_by_wallet), 2),
                    "average_entry_price": position.get("average_entry_price"),
                    "current_price": position.get("current_price"),
                    "wallet_profile_url": position.get("wallet_profile_url"),
                }
                for position in group
            ],
            key=lambda item: (-item["amount"], -item["relative_units"], str(item["wallet_label"]).lower()),
        )

        output.append(
            {
                "id": f"{canonical.market_key}::{canonical.side_key}",
                "canonical_market_key": canonical.market_key,
                "canonical_side_key": canonical.side_key,
                "confidence_score": max(0, min(100, confidence)),
                "score_breakdown": breakdown,
                "score_weights": CONFIDENCE_WEIGHTS,
                "sharps_badge": sharps_badge(wallet_count),
                "agreeing_wallet_count": wallet_count,
                "market_title": primary.get("market_title"),
                "event_title": primary.get("event_title") or primary.get("market_title"),
                "outcome": primary.get("outcome"),
                "category": primary.get("category"),
                "league": primary.get("league"),
                "event_slug": primary.get("event_slug"),
                "market_url": primary.get("market_url"),
                "current_price": primary.get("current_price"),
                "average_entry_price": round(sum(_safe_float(position.get("average_entry_price")) for position in group) / len(group), 4),
                "slippage": round(slippage, 4),
                "total_amount_bet": total_amount,
                "strongest_relative_units": round(strongest_units, 2),
                "primary_trader": {
                    "wallet_address": primary.get("wallet_address"),
                    "wallet_label": primary.get("wallet_label"),
                    "amount": round(_safe_float(primary.get("position_size_usd")), 2),
                    "relative_units": round(_relative_units(primary, unit_map, events_by_wallet), 2),
                    "wallet_profile_url": primary.get("wallet_profile_url"),
                    "sample_size": sample_size,
                    "adjusted_hit_rate": round(adjusted_hit_rate, 4),
                },
                "supporting_wallets": supporters,
                "first_detected_at": min(position.get("first_detected_at") or "" for position in group),
                "last_changed_at": max(position.get("last_changed_at") or position.get("first_detected_at") or "" for position in group),
                "entered_at": max(position.get("first_detected_at") or "" for position in group),
                **event_time,
            }
        )

    output.sort(key=lambda item: (-item["confidence_score"], -item["agreeing_wallet_count"], -item["total_amount_bet"], item["market_title"] or ""))
    return output
