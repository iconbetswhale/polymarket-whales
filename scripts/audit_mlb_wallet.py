from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from polymarket_client import PolymarketClient
from unit_analysis import estimate_unit_size
from wallet_activity import normalize_trade_fills


ET = ZoneInfo("America/New_York")


def number(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * quantile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def is_scope(position: dict[str, object], scope: str) -> bool:
    searchable = " ".join(
        str(position.get(key) or "")
        for key in ("eventSlug", "slug", "title", "marketTitle")
    ).lower()
    if scope == "TENNIS":
        return searchable.startswith(("atp-", "wta-", "itf-", "utr-", "challenger-"))
    if scope == "UFC":
        return searchable.startswith(("ufc-", "mma-"))
    if scope == "SOCCER":
        return searchable.startswith(
            (
                "fifwc-",
                "mls-",
                "epl-",
                "uefa-",
                "ucl-",
                "uel-",
                "laliga-",
                "bundesliga-",
                "seriea-",
                "ligue1-",
                "bra-",
                "arg-",
                "mex-",
            )
        )
    return searchable.startswith("mlb-") or " mlb " in f" {searchable} "


def classify_ratio(ratio: float) -> str:
    if ratio < 0.10:
        return "CLEAN_DIRECTIONAL"
    if ratio <= 0.20:
        return "MINOR_HEDGE"
    if ratio <= 0.50:
        return "MATERIAL_HEDGE"
    return "TWO_SIDED"


def aggregate_closed_positions(
    positions: list[dict[str, object]],
) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for position in positions:
        condition_id = str(position.get("conditionId") or "").lower()
        if condition_id:
            grouped[condition_id].append(position)

    aggregates: list[dict[str, object]] = []
    for condition_id, rows in grouped.items():
        exposures = sorted(
            (number(row.get("totalBought")) for row in rows),
            reverse=True,
        )
        largest = exposures[0] if exposures else 0.0
        opposing = sum(exposures[1:])
        ratio = opposing / largest if largest > 0 else 0.0
        aggregates.append(
            {
                "condition_id": condition_id,
                "event_slug": str(rows[0].get("eventSlug") or ""),
                "date": str(rows[0].get("endDate") or "")[:10],
                "gross_bought": sum(exposures),
                "net_directional_exposure": max(0.0, largest - opposing),
                "opposing_exposure_ratio": ratio,
                "status": classify_ratio(ratio),
                "realized_pnl": sum(number(row.get("realizedPnl")) for row in rows),
            }
        )
    return aggregates


def performance(rows: list[dict[str, object]]) -> dict[str, object]:
    stake = sum(number(row["gross_bought"]) for row in rows)
    pnl = sum(number(row["realized_pnl"]) for row in rows)
    return {
        "markets": len(rows),
        "gross_bought_usd": round(stake, 2),
        "realized_pnl_usd": round(pnl, 2),
        "gross_turnover_roi": round(pnl / stake, 4) if stake else None,
        "positive_pnl_rate": (
            round(sum(number(row["realized_pnl"]) > 0 for row in rows) / len(rows), 4)
            if rows
            else None
        ),
    }


def fill_diagnostics(
    client: PolymarketClient,
    address: str,
    condition_ids: list[str],
    sample_size: int,
) -> dict[str, object]:
    sampled_ids = condition_ids[:sample_size]
    raw = client.get_user_trades(address, sampled_ids, max_records=100_000)
    fills, duplicate_count = normalize_trade_fills(address, raw)
    by_market: Counter[str] = Counter()
    outcomes: dict[str, set[str]] = defaultdict(set)
    first_outcome_time: dict[str, dict[str, int]] = defaultdict(dict)
    first_market_time: dict[str, int] = {}
    last_market_time: dict[str, int] = {}
    fill_hours: Counter[int] = Counter()
    first_entry_hours: Counter[int] = Counter()

    for fill in fills:
        condition_id = str(fill["condition_id"])
        outcome_id = str(fill["outcome_id"])
        timestamp = int(fill["timestamp"])
        by_market[condition_id] += 1
        outcomes[condition_id].add(outcome_id)
        first_outcome_time[condition_id].setdefault(outcome_id, timestamp)
        first_market_time[condition_id] = min(
            timestamp, first_market_time.get(condition_id, timestamp)
        )
        last_market_time[condition_id] = max(
            timestamp, last_market_time.get(condition_id, timestamp)
        )
        fill_hours[datetime.fromtimestamp(timestamp, ET).hour] += 1

    for timestamp in first_market_time.values():
        first_entry_hours[datetime.fromtimestamp(timestamp, ET).hour] += 1

    ordered_timestamps = sorted(int(fill["timestamp"]) for fill in fills)
    gaps = [
        right - left
        for left, right in zip(ordered_timestamps, ordered_timestamps[1:])
    ]
    opposing_delays = [
        max(times.values()) - min(times.values())
        for times in first_outcome_time.values()
        if len(times) > 1
    ]
    durations = [
        last_market_time[key] - first_market_time[key]
        for key in first_market_time
    ]
    total_hours = sum(fill_hours.values())
    return {
        "sample_markets": len(sampled_ids),
        "raw_fills": len(raw),
        "deduplicated_fills": len(fills),
        "duplicate_fills": duplicate_count,
        "buy_fills": sum(fill["side"] == "BUY" for fill in fills),
        "sell_fills": sum(fill["side"] == "SELL" for fill in fills),
        "markets_with_both_outcomes": sum(len(value) > 1 for value in outcomes.values()),
        "median_fills_per_market": (
            round(statistics.median(by_market.values()), 1) if by_market else None
        ),
        "p90_fills_per_market": percentile(list(by_market.values()), 0.90),
        "median_interfill_seconds": (
            round(statistics.median(gaps), 1) if gaps else None
        ),
        "gaps_within_one_second_rate": (
            round(sum(gap <= 1 for gap in gaps) / len(gaps), 4) if gaps else None
        ),
        "gaps_within_ten_seconds_rate": (
            round(sum(gap <= 10 for gap in gaps) / len(gaps), 4) if gaps else None
        ),
        "median_opposite_side_delay_minutes": (
            round(statistics.median(opposing_delays) / 60, 1)
            if opposing_delays
            else None
        ),
        "opposite_side_within_five_minutes_rate": (
            round(sum(delay <= 300 for delay in opposing_delays) / len(opposing_delays), 4)
            if opposing_delays
            else None
        ),
        "median_market_activity_duration_minutes": (
            round(statistics.median(durations) / 60, 1) if durations else None
        ),
        "fill_hour_distribution_et": {
            str(hour): round(count / total_hours, 4)
            for hour, count in sorted(fill_hours.items())
        },
        "first_entry_hour_counts_et": {
            str(hour): count for hour, count in sorted(first_entry_hours.items())
        },
    }


def audit(
    address: str, closed_limit: int, fill_sample: int, scope: str = "MLB"
) -> dict[str, object]:
    client = PolymarketClient(max_retries=5)
    all_closed = client.get_closed_positions(address, closed_limit)
    scoped_closed = [
        position for position in all_closed if is_scope(position, scope)
    ]
    markets = aggregate_closed_positions(scoped_closed)
    clean = [
        market
        for market in markets
        if market["status"] == "CLEAN_DIRECTIONAL"
        and number(market["net_directional_exposure"]) >= 500
    ]
    clean_sizes = [number(market["net_directional_exposure"]) for market in clean]
    unit_estimate = estimate_unit_size(address, address[:6], clean_sizes)

    status_groups = {
        status: [market for market in markets if market["status"] == status]
        for status in (
            "CLEAN_DIRECTIONAL",
            "MINOR_HEDGE",
            "MATERIAL_HEDGE",
            "TWO_SIDED",
        )
    }
    unit = round(number(unit_estimate.estimated_base_unit) / 250) * 250
    unit = unit or None
    size_bands: dict[str, list[dict[str, object]]] = defaultdict(list)
    if unit:
        for market in clean:
            units = number(market["net_directional_exposure"]) / unit
            band = (
                "UNDER_0_5U"
                if units < 0.5
                else "0_5_TO_1U"
                if units < 1
                else "1_TO_2U"
                if units < 2
                else "2_TO_3U"
                if units < 3
                else "3U_PLUS"
            )
            size_bands[band].append(market)

    events = {str(position.get("eventSlug") or "") for position in scoped_closed}
    dates = [str(market["date"]) for market in markets if market["date"]]
    daily_counts = Counter(str(market["date"]) for market in markets if market["date"])
    sorted_markets = sorted(
        markets, key=lambda market: str(market["date"]), reverse=True
    )
    fill_metrics = (
        fill_diagnostics(
            client,
            address,
            [str(market["condition_id"]) for market in sorted_markets],
            fill_sample,
        )
        if fill_sample > 0
        else {
            "sample_markets": 0,
            "raw_fills": 0,
            "deduplicated_fills": 0,
            "note": "Fill diagnostics skipped; use a supplied execution export.",
        }
    )
    return {
        "address": address.lower(),
        "scope": scope,
        "source": "Polymarket closed positions and executed trades",
        "coverage": {
            "start": min(dates) if dates else None,
            "end": max(dates) if dates else None,
            "closed_rows": len(scoped_closed),
            "markets": len(markets),
            "events": len(events),
            "active_days": len(daily_counts),
        },
        "performance": performance(markets),
        "market_frequency": {
            "median_markets_per_active_day": (
                round(statistics.median(daily_counts.values()), 1)
                if daily_counts
                else None
            ),
            "p90_markets_per_active_day": percentile(list(daily_counts.values()), 0.90),
        },
        "hedge_breakdown": {
            status: performance(rows) for status, rows in status_groups.items()
        },
        "clean_directional_unit_analysis": {
            "eligible_sample": len(clean_sizes),
            "estimated_unit_usd": unit,
            "raw_estimate_usd": unit_estimate.estimated_base_unit,
            "confidence": unit_estimate.confidence,
            "matched_samples": unit_estimate.matched_samples,
            "p25_usd": percentile(clean_sizes, 0.25),
            "median_usd": percentile(clean_sizes, 0.50),
            "p75_usd": percentile(clean_sizes, 0.75),
            "p90_usd": percentile(clean_sizes, 0.90),
            "performance_by_relative_size": {
                band: performance(rows) for band, rows in size_bands.items()
            },
        },
        "fill_diagnostics": fill_metrics,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("address")
    parser.add_argument("--closed-limit", type=int, default=20_000)
    parser.add_argument("--fill-sample", type=int, default=120)
    parser.add_argument(
        "--scope", choices=("MLB", "TENNIS", "UFC", "SOCCER"), default="MLB"
    )
    parser.add_argument("--output")
    args = parser.parse_args()
    report = audit(args.address, args.closed_limit, args.fill_sample, args.scope)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
