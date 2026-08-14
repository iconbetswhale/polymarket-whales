from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unit_analysis import estimate_unit_size
from wallet_activity import normalize_trade_fills


ET = ZoneInfo("America/New_York")


def number(value: Any) -> float:
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


def load_rows(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, list):
            raise ValueError(f"{path} must contain a JSON array")
        rows.extend(row for row in payload if isinstance(row, dict))
    return rows


def market_type(row: dict[str, Any]) -> str:
    slug = str(row.get("slug") or "").lower()
    title = str(row.get("title") or "").lower()
    if "-total-" in slug or "o/u " in title:
        return "TOTAL"
    if "-spread-" in slug or title.startswith("spread:"):
        return "SPREAD"
    return "MONEYLINE"


def line_value(row: dict[str, Any]) -> float | None:
    slug = str(row.get("slug") or "").lower()
    marker = "-total-" if "-total-" in slug else "-spread-" if "-spread-" in slug else ""
    if not marker:
        return None
    tail = slug.split(marker, 1)[1]
    for prefix in ("home-", "away-"):
        if tail.startswith(prefix):
            tail = tail[len(prefix) :]
    token = tail.split("-", 1)[0].replace("pt", ".").replace("neg", "-")
    try:
        return float(token)
    except ValueError:
        return None


def classify_exact_market(outcome_costs: list[float]) -> tuple[str, float, float]:
    ordered = sorted(outcome_costs, reverse=True)
    largest = ordered[0] if ordered else 0.0
    opposing = sum(ordered[1:])
    ratio = opposing / largest if largest else 0.0
    status = (
        "CLEAN_DIRECTIONAL"
        if ratio < 0.10
        else "MINOR_HEDGE"
        if ratio <= 0.20
        else "MATERIAL_HEDGE"
        if ratio <= 0.50
        else "TWO_SIDED"
    )
    return status, ratio, max(0.0, largest - opposing)


def analyze(
    paths: list[Path], address: str, scope: str = "MLB"
) -> dict[str, Any]:
    rows = load_rows(paths)
    normalized_address = address.lower()
    wrong_wallet = [
        row
        for row in rows
        if str(row.get("proxyWallet") or "").lower() != normalized_address
    ]
    prefixes = {
        "MLB": ("mlb-",),
        "TENNIS": ("atp-", "wta-", "itf-", "utr-", "challenger-"),
        "UFC": ("ufc-", "mma-"),
        "SOCCER": (
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
        ),
    }[scope]
    scoped_rows = [
        row
        for row in rows
        if str(row.get("eventSlug") or row.get("slug") or "")
        .lower()
        .startswith(prefixes)
    ]
    fills, duplicate_count = normalize_trade_fills(address, scoped_rows)

    by_position: dict[tuple[str, str], dict[str, Any]] = {}
    by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    fill_hours: Counter[int] = Counter()
    first_condition_time: dict[str, int] = {}
    condition_times: dict[str, list[int]] = defaultdict(list)
    same_second_counts: Counter[tuple[str, int]] = Counter()
    event_conditions: dict[str, set[str]] = defaultdict(set)
    event_market_types: dict[str, Counter[str]] = defaultdict(Counter)
    event_total_sides: dict[str, dict[str, set[float]]] = defaultdict(
        lambda: defaultdict(set)
    )
    event_moneyline_outcomes: dict[str, set[str]] = defaultdict(set)
    event_spread_outcomes: dict[str, set[str]] = defaultdict(set)

    for fill in fills:
        condition_id = str(fill["condition_id"])
        outcome_id = str(fill["outcome_id"])
        timestamp = int(fill["timestamp"])
        cost = number(fill["usd_amount"])
        key = (condition_id, outcome_id)
        aggregate = by_position.setdefault(
            key,
            {
                "condition_id": condition_id,
                "outcome_id": outcome_id,
                "outcome": str(fill.get("outcome") or ""),
                "event_slug": str(fill.get("event_slug") or ""),
                "market_slug": str(fill.get("market_slug") or ""),
                "title": str(fill.get("market_title") or ""),
                "cost": 0.0,
                "shares": 0.0,
                "buy_cost": 0.0,
                "buy_shares": 0.0,
                "sell_shares": 0.0,
                "fill_count": 0,
                "first_timestamp": timestamp,
                "last_timestamp": timestamp,
            },
        )
        shares = number(fill["shares"])
        if str(fill.get("side") or "").upper() == "SELL":
            aggregate["sell_shares"] += shares
        else:
            aggregate["buy_cost"] += cost
            aggregate["buy_shares"] += shares
        aggregate["fill_count"] += 1
        aggregate["first_timestamp"] = min(aggregate["first_timestamp"], timestamp)
        aggregate["last_timestamp"] = max(aggregate["last_timestamp"], timestamp)
        condition_times[condition_id].append(timestamp)
        first_condition_time[condition_id] = min(
            timestamp, first_condition_time.get(condition_id, timestamp)
        )
        fill_hours[datetime.fromtimestamp(timestamp, ET).hour] += 1
        same_second_counts[(condition_id, timestamp)] += 1

    for aggregate in by_position.values():
        average_entry = (
            aggregate["buy_cost"] / aggregate["buy_shares"]
            if aggregate["buy_shares"] > 0
            else 0.0
        )
        aggregate["shares"] = max(
            0.0, aggregate["buy_shares"] - aggregate["sell_shares"]
        )
        aggregate["cost"] = aggregate["shares"] * average_entry
        by_condition[str(aggregate["condition_id"])].append(aggregate)
        event = str(aggregate["event_slug"])
        event_conditions[event].add(str(aggregate["condition_id"]))
        row_type = market_type(
            {"slug": aggregate["market_slug"], "title": aggregate["title"]}
        )
        event_market_types[event][row_type] += 1
        outcome = str(aggregate["outcome"]).strip().lower()
        line = line_value(
            {"slug": aggregate["market_slug"], "title": aggregate["title"]}
        )
        if row_type == "TOTAL" and line is not None:
            event_total_sides[event][outcome].add(line)
        elif row_type == "MONEYLINE":
            event_moneyline_outcomes[event].add(outcome)
        elif row_type == "SPREAD":
            event_spread_outcomes[event].add(outcome)

    exact_markets: list[dict[str, Any]] = []
    for condition_id, positions in by_condition.items():
        status, ratio, net = classify_exact_market(
            [number(position["cost"]) for position in positions]
        )
        exact_markets.append(
            {
                "condition_id": condition_id,
                "event_slug": positions[0]["event_slug"],
                "market_type": market_type(
                    {
                        "slug": positions[0]["market_slug"],
                        "title": positions[0]["title"],
                    }
                ),
                "status": status,
                "opposing_ratio": ratio,
                "net_directional_cost": net,
                "gross_cost": sum(number(position["cost"]) for position in positions),
                "fill_count": sum(int(position["fill_count"]) for position in positions),
            }
        )

    clean_sizes = [
        number(market["net_directional_cost"])
        for market in exact_markets
        if market["status"] == "CLEAN_DIRECTIONAL"
        and number(market["net_directional_cost"]) >= 100
    ]
    unit = estimate_unit_size(address, address[:8], clean_sizes)
    timestamps = [int(fill["timestamp"]) for fill in fills]
    condition_durations = [
        max(times) - min(times) for times in condition_times.values() if times
    ]
    first_entry_hours = Counter(
        datetime.fromtimestamp(timestamp, ET).hour
        for timestamp in first_condition_time.values()
    )
    total_hour_count = sum(fill_hours.values())
    days = Counter(
        datetime.fromtimestamp(timestamp, ET).date().isoformat()
        for timestamp in first_condition_time.values()
    )
    events_with_total_middle = sum(
        bool(
            sides.get("over")
            and sides.get("under")
            and min(sides["over"]) < max(sides["under"])
        )
        for sides in event_total_sides.values()
    )
    events_with_opposing_totals = sum(
        bool(sides.get("over") and sides.get("under"))
        for sides in event_total_sides.values()
    )
    result = {
        "address": normalized_address,
        "scope": scope,
        "source_files": [str(path) for path in paths],
        "data_quality": {
            "raw_rows": len(rows),
            "wrong_wallet_rows": len(wrong_wallet),
            "scoped_rows": len(scoped_rows),
            "non_scoped_rows": len(rows) - len(scoped_rows),
            "deduplicated_scoped_fills": len(fills),
            "duplicate_scoped_fills": duplicate_count,
            "all_sides": dict(Counter(str(row.get("side") or "") for row in rows)),
            "scoped_sides": dict(Counter(str(row.get("side") or "") for row in scoped_rows)),
            "contains_settlement_pnl": any(
                row.get("realizedPnl") is not None for row in rows
            ),
        },
        "coverage": {
            "start_utc": (
                datetime.fromtimestamp(min(timestamps), ET).isoformat()
                if timestamps
                else None
            ),
            "end_utc": (
                datetime.fromtimestamp(max(timestamps), ET).isoformat()
                if timestamps
                else None
            ),
            "active_days": len(days),
            "events": len(event_conditions),
            "exact_markets": len(exact_markets),
            "aggregated_outcome_positions": len(by_position),
        },
        "activity": {
            "median_exact_markets_per_active_day": (
                statistics.median(days.values()) if days else None
            ),
            "p90_exact_markets_per_active_day": percentile(
                list(days.values()), 0.90
            ),
            "median_fills_per_exact_market": (
                statistics.median(
                    int(market["fill_count"]) for market in exact_markets
                )
                if exact_markets
                else None
            ),
            "p90_fills_per_exact_market": percentile(
                [int(market["fill_count"]) for market in exact_markets], 0.90
            ),
            "median_market_activity_minutes": (
                statistics.median(condition_durations) / 60
                if condition_durations
                else None
            ),
            "same_second_multi_fill_rate": (
                sum(count for count in same_second_counts.values() if count > 1)
                / len(fills)
                if fills
                else None
            ),
            "fill_hour_distribution_et": {
                str(hour): round(count / total_hour_count, 4)
                for hour, count in sorted(fill_hours.items())
            },
            "first_entry_hour_counts_et": {
                str(hour): count for hour, count in sorted(first_entry_hours.items())
            },
        },
        "exact_market_direction": {
            status: sum(market["status"] == status for market in exact_markets)
            for status in (
                "CLEAN_DIRECTIONAL",
                "MINOR_HEDGE",
                "MATERIAL_HEDGE",
                "TWO_SIDED",
            )
        },
        "event_structure": {
            "events_with_both_moneyline_teams": sum(
                len(outcomes) > 1 for outcomes in event_moneyline_outcomes.values()
            ),
            "events_with_both_spread_teams": sum(
                len(outcomes) > 1 for outcomes in event_spread_outcomes.values()
            ),
            "events_with_over_and_under": events_with_opposing_totals,
            "events_with_total_middle_corridor": events_with_total_middle,
            "median_exact_markets_per_event": (
                statistics.median(len(value) for value in event_conditions.values())
                if event_conditions
                else None
            ),
            "p90_exact_markets_per_event": percentile(
                [len(value) for value in event_conditions.values()], 0.90
            ),
        },
        "clean_directional_unit_analysis": {
            "sample": len(clean_sizes),
            "estimated_unit_usd": unit.estimated_base_unit,
            "confidence": unit.confidence,
            "matched_samples": unit.matched_samples,
            "p25_usd": percentile(clean_sizes, 0.25),
            "median_usd": percentile(clean_sizes, 0.50),
            "p75_usd": percentile(clean_sizes, 0.75),
            "p90_usd": percentile(clean_sizes, 0.90),
        },
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--address", required=True)
    parser.add_argument(
        "--scope", choices=("MLB", "TENNIS", "UFC", "SOCCER"), default="MLB"
    )
    parser.add_argument("--output")
    args = parser.parse_args()
    report = analyze(args.paths, args.address, args.scope)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
