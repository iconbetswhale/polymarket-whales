from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ET = ZoneInfo("America/New_York")
DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")


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


def load_array(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON array")
    return [row for row in payload if isinstance(row, dict)]


def is_sport(row: dict[str, Any], sport: str) -> bool:
    prefixes = {
        "ufc": ("ufc-", "mma-"),
        "tennis": ("atp-", "wta-", "itf-", "utr-", "challenger-"),
    }[sport]
    return str(row.get("eventSlug") or row.get("slug") or "").lower().startswith(
        prefixes
    )


def date_from_row(row: dict[str, Any]) -> str | None:
    match = DATE_RE.search(str(row.get("eventSlug") or row.get("slug") or ""))
    return match.group(1) if match else None


def direction_status(ratio: float) -> str:
    if ratio < 0.10:
        return "CLEAN_DIRECTIONAL"
    if ratio <= 0.20:
        return "MINOR_HEDGE"
    if ratio <= 0.50:
        return "MATERIAL_HEDGE"
    return "TWO_SIDED"


def summarize(markets: list[dict[str, Any]]) -> dict[str, Any]:
    cost = sum(number(market["gross_cost_usd"]) for market in markets)
    pnl = sum(number(market["realized_pnl_usd"]) for market in markets)
    tail = [number(market["flat_tail_return_units"]) for market in markets]
    return {
        "markets": len(markets),
        "wins": sum(bool(market["dominant_won"]) for market in markets),
        "dominant_hit_rate": (
            sum(bool(market["dominant_won"]) for market in markets) / len(markets)
            if markets
            else None
        ),
        "gross_cost_usd": round(cost, 2),
        "realized_pnl_usd": round(pnl, 2),
        "realized_roi_on_cost": round(pnl / cost, 5) if cost else None,
        "positive_market_pnl_rate": (
            sum(number(market["realized_pnl_usd"]) > 0 for market in markets)
            / len(markets)
            if markets
            else None
        ),
        "flat_tail_profit_units": round(sum(tail), 3),
        "flat_tail_roi": round(sum(tail) / len(tail), 5) if tail else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fills", type=Path, required=True)
    parser.add_argument("--closed-dir", type=Path, required=True)
    parser.add_argument("--closed-prefix", default="c63amg-closed-")
    parser.add_argument("--sport", choices=("ufc", "tennis"), default="ufc")
    parser.add_argument("--unit", type=float, default=625.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    fills_all = load_array(args.fills)
    fills = [row for row in fills_all if is_sport(row, args.sport)]

    closed_paths = sorted(
        args.closed_dir.glob(f"{args.closed_prefix}*.json"),
        key=lambda path: int(re.search(r"-(\d+)\.json$", path.name).group(1)),
    )
    closed_all: list[dict[str, Any]] = []
    seen_closed: set[tuple[str, str]] = set()
    duplicate_closed = 0
    for path in closed_paths:
        for row in load_array(path):
            key = (str(row.get("conditionId") or ""), str(row.get("asset") or ""))
            if key in seen_closed:
                duplicate_closed += 1
                continue
            seen_closed.add(key)
            closed_all.append(row)
    closed = [row for row in closed_all if is_sport(row, args.sport)]

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in closed:
        condition_id = str(row.get("conditionId") or "").lower()
        if condition_id:
            grouped[condition_id].append(row)

    markets: list[dict[str, Any]] = []
    for condition_id, rows in grouped.items():
        outcomes: list[dict[str, Any]] = []
        for row in rows:
            shares = number(row.get("totalBought"))
            price = number(row.get("avgPrice"))
            outcomes.append(
                {
                    "outcome": str(row.get("outcome") or ""),
                    "shares": shares,
                    "average_entry": price,
                    "cost_usd": shares * price,
                    "realized_pnl_usd": number(row.get("realizedPnl")),
                    "won": number(row.get("curPrice")) >= 0.99,
                }
            )
        outcomes.sort(key=lambda outcome: outcome["cost_usd"], reverse=True)
        leader = outcomes[0]
        opposing_cost = sum(number(outcome["cost_usd"]) for outcome in outcomes[1:])
        ratio = opposing_cost / number(leader["cost_usd"]) if leader["cost_usd"] else 0
        price = number(leader["average_entry"])
        won = bool(leader["won"])
        tail_return = ((1 - price) / price if won else -1.0) if 0 < price < 1 else 0
        date = date_from_row(rows[0])
        markets.append(
            {
                "condition_id": condition_id,
                "event_slug": str(rows[0].get("eventSlug") or ""),
                "title": str(rows[0].get("title") or ""),
                "date": date,
                "dominant_outcome": leader["outcome"],
                "dominant_average_entry": price,
                "dominant_cost_usd": round(number(leader["cost_usd"]), 6),
                "opposing_cost_usd": round(opposing_cost, 6),
                "net_directional_cost_usd": round(
                    max(0.0, number(leader["cost_usd"]) - opposing_cost), 6
                ),
                "gross_cost_usd": round(
                    sum(number(outcome["cost_usd"]) for outcome in outcomes), 6
                ),
                "opposing_ratio": ratio,
                "status": direction_status(ratio),
                "dominant_won": won,
                "realized_pnl_usd": round(
                    sum(number(outcome["realized_pnl_usd"]) for outcome in outcomes), 6
                ),
                "flat_tail_return_units": tail_return,
                "outcomes": outcomes,
            }
        )

    markets.sort(key=lambda market: (str(market["date"]), market["condition_id"]))
    directional = [
        market
        for market in markets
        if market["status"] in {"CLEAN_DIRECTIONAL", "MINOR_HEDGE"}
    ]

    size_bands: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for market in directional:
        units = number(market["net_directional_cost_usd"]) / args.unit
        market["measured_units"] = units
        band = (
            "UNDER_0_5U"
            if units < 0.5
            else "0_5_TO_1U"
            if units < 1
            else "1_TO_2U"
            if units < 2
            else "2_TO_4U"
            if units < 4
            else "4_TO_8U"
            if units < 8
            else "8U_PLUS"
        )
        size_bands[band].append(market)

    price_bands: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for market in directional:
        price = number(market["dominant_average_entry"])
        band = (
            "UNDER_30C"
            if price < 0.30
            else "30_TO_49C"
            if price < 0.50
            else "50_TO_69C"
            if price < 0.70
            else "70C_PLUS"
        )
        price_bands[band].append(market)

    monthly: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for market in directional:
        if market["date"]:
            monthly[str(market["date"])[:7]].append(market)

    # Global inter-fill cadence catches portfolio batching across different UFC fights.
    timestamps = sorted(int(row.get("timestamp") or 0) for row in fills)
    gaps = [right - left for left, right in zip(timestamps, timestamps[1:])]
    timestamp_counts = Counter(timestamps)
    fill_notionals = [number(row.get("size")) * number(row.get("price")) for row in fills]
    first_fill_by_condition: dict[str, int] = {}
    for row in fills:
        condition = str(row.get("conditionId") or "")
        timestamp = int(row.get("timestamp") or 0)
        first_fill_by_condition[condition] = min(
            timestamp, first_fill_by_condition.get(condition, timestamp)
        )
    lead_days: list[float] = []
    for row in fills:
        condition = str(row.get("conditionId") or "")
        if first_fill_by_condition.get(condition) != int(row.get("timestamp") or 0):
            continue
        date = date_from_row(row)
        if date:
            event_midnight = datetime.fromisoformat(date).replace(tzinfo=ET)
            first = datetime.fromtimestamp(int(row["timestamp"]), ET)
            lead_days.append((event_midnight - first).total_seconds() / 86400)

    top_wins = sorted(markets, key=lambda market: market["realized_pnl_usd"], reverse=True)[:10]
    top_losses = sorted(markets, key=lambda market: market["realized_pnl_usd"])[:10]
    gross_pnl = sum(abs(number(market["realized_pnl_usd"])) for market in markets)

    report = {
        "identity": {
            "address": str(fills_all[0].get("proxyWallet") or "").lower(),
            "name": str(fills_all[0].get("name") or ""),
            "pseudonym": str(fills_all[0].get("pseudonym") or ""),
        },
        "data_quality": {
            "raw_fill_rows": len(fills_all),
            f"{args.sport}_fill_rows": len(fills),
            "closed_pages": len(closed_paths),
            "deduplicated_closed_rows_all_categories": len(closed_all),
            "duplicate_closed_rows_removed": duplicate_closed,
            f"{args.sport}_closed_rows": len(closed),
            f"{args.sport}_exact_markets": len(markets),
            "contains_complete_settlement_pnl": bool(closed),
        },
        "coverage": {
            "fill_start_et": datetime.fromtimestamp(min(timestamps), ET).isoformat(),
            "fill_end_et": datetime.fromtimestamp(max(timestamps), ET).isoformat(),
            "settled_start": min(str(market["date"]) for market in markets),
            "settled_end": max(str(market["date"]) for market in markets),
            "active_fill_days": len(
                {datetime.fromtimestamp(timestamp, ET).date() for timestamp in timestamps}
            ),
        },
        "performance": {
            f"all_{args.sport}": summarize(markets),
            "clean_or_minor_directional": summarize(directional),
            "by_direction_status": {
                status: summarize(
                    [market for market in markets if market["status"] == status]
                )
                for status in (
                    "CLEAN_DIRECTIONAL",
                    "MINOR_HEDGE",
                    "MATERIAL_HEDGE",
                    "TWO_SIDED",
                )
            },
            "by_measured_size": {
                band: summarize(rows) for band, rows in sorted(size_bands.items())
            },
            "by_entry_price": {
                band: summarize(rows) for band, rows in sorted(price_bands.items())
            },
            "by_month": {
                month: summarize(rows) for month, rows in sorted(monthly.items())
            },
        },
        "unit_analysis": {
            "measured_unit_usd": args.unit,
            "directional_market_sample": len(directional),
            "net_size_p25_usd": percentile(
                [number(market["net_directional_cost_usd"]) for market in directional], 0.25
            ),
            "net_size_median_usd": percentile(
                [number(market["net_directional_cost_usd"]) for market in directional], 0.50
            ),
            "net_size_p75_usd": percentile(
                [number(market["net_directional_cost_usd"]) for market in directional], 0.75
            ),
            "net_size_p90_usd": percentile(
                [number(market["net_directional_cost_usd"]) for market in directional], 0.90
            ),
            "largest_net_position_usd": max(
                number(market["net_directional_cost_usd"]) for market in directional
            ),
        },
        "execution_behavior": {
            "buy_fills": sum(str(row.get("side") or "").upper() == "BUY" for row in fills),
            "sell_fills": sum(str(row.get("side") or "").upper() == "SELL" for row in fills),
            "median_fill_notional_usd": statistics.median(fill_notionals),
            "p90_fill_notional_usd": percentile(fill_notionals, 0.90),
            "median_global_interfill_seconds": statistics.median(gaps) if gaps else None,
            "interfills_within_1_second_rate": (
                sum(gap <= 1 for gap in gaps) / len(gaps) if gaps else None
            ),
            "interfills_within_10_seconds_rate": (
                sum(gap <= 10 for gap in gaps) / len(gaps) if gaps else None
            ),
            "fills_sharing_timestamp_rate": (
                sum(count for count in timestamp_counts.values() if count > 1) / len(fills)
                if fills
                else None
            ),
            "median_calendar_days_before_event": statistics.median(lead_days),
            "p25_calendar_days_before_event": percentile(lead_days, 0.25),
            "p75_calendar_days_before_event": percentile(lead_days, 0.75),
            "first_entries_on_event_date_or_later_rate": (
                sum(days <= 0 for days in lead_days) / len(lead_days) if lead_days else None
            ),
        },
        "concentration": {
            "top_5_absolute_pnl_share": (
                sum(abs(number(market["realized_pnl_usd"])) for market in sorted(
                    markets,
                    key=lambda market: abs(number(market["realized_pnl_usd"])),
                    reverse=True,
                )[:5])
                / gross_pnl
                if gross_pnl
                else None
            ),
            "top_5_cost_share": sum(
                number(market["gross_cost_usd"])
                for market in sorted(markets, key=lambda market: market["gross_cost_usd"], reverse=True)[:5]
            )
            / sum(number(market["gross_cost_usd"]) for market in markets),
        },
        "largest_wins": top_wins,
        "largest_losses": top_losses,
        "market_ledger": markets,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in report if key != "market_ledger"}, indent=2))


if __name__ == "__main__":
    main()
