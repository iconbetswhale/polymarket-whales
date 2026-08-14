from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


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
    return payload if isinstance(payload, list) else []


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00").replace("+00", "+00:00"))


def timing_band(minutes: float) -> str:
    if minutes > 120:
        return "PREMATCH_OVER_2H"
    if minutes > 30:
        return "PREMATCH_30M_TO_2H"
    if minutes >= 0:
        return "PREMATCH_0_TO_30M"
    if minutes >= -30:
        return "LIVE_0_TO_30M"
    if minutes >= -90:
        return "LIVE_30_TO_90M"
    return "LIVE_90M_PLUS"


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [number(row["first_fill_tail_return_units"]) for row in rows]
    prices = [number(row["first_fill_price"]) for row in rows]
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for row in sorted(rows, key=lambda item: int(item.get("timestamp") or 0)):
        equity += number(row["first_fill_tail_return_units"])
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return {
        "markets": len(rows),
        "wins": sum(bool(row["first_fill_won"]) for row in rows),
        "hit_rate": sum(bool(row["first_fill_won"]) for row in rows) / len(rows)
        if rows
        else None,
        "flat_tail_profit_units": round(sum(returns), 3),
        "flat_tail_roi": round(sum(returns) / len(rows), 5) if rows else None,
        "max_flat_tail_drawdown_units": round(max_drawdown, 3),
        "median_first_fill_price": statistics.median(prices) if prices else None,
        "p25_first_fill_price": percentile(prices, 0.25),
        "p75_first_fill_price": percentile(prices, 0.75),
    }


def latency_summary(rows: list[dict[str, Any]], delay: int) -> dict[str, Any]:
    available = [row for row in rows if row.get(f"price_after_{delay}s") is not None]
    returns = [number(row[f"tail_after_{delay}s"]) for row in available]
    changes = [
        number(row[f"price_after_{delay}s"]) - number(row["first_fill_price"])
        for row in available
    ]
    return {
        "markets_with_observed_fill_after_delay": len(available),
        "coverage_rate": len(available) / len(rows) if rows else None,
        "hit_rate": sum(bool(row["first_fill_won"]) for row in available) / len(available)
        if available
        else None,
        "flat_tail_profit_units": round(sum(returns), 3),
        "flat_tail_roi": round(sum(returns) / len(available), 5) if available else None,
        "median_price_change": statistics.median(changes) if changes else None,
        "p75_price_change": percentile(changes, 0.75),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fills", type=Path, required=True)
    parser.add_argument("--forensics", type=Path, required=True)
    parser.add_argument("--metadata-dir", type=Path, required=True)
    parser.add_argument("--metadata-prefix", default="lilybaeum-tennis-meta-")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = json.loads(args.forensics.read_text(encoding="utf-8"))
    ledger = {row["condition_id"]: row for row in report["market_ledger"]}

    metadata: dict[str, dict[str, Any]] = {}
    for path in args.metadata_dir.glob(f"{args.metadata_prefix}*.json"):
        for row in load_array(path):
            condition_id = str(row.get("conditionId") or "").lower()
            if condition_id and row.get("gameStartTime"):
                metadata[condition_id] = row

    fills = [
        row
        for row in load_array(args.fills)
        if str(row.get("eventSlug") or row.get("slug") or "")
        .lower()
        .startswith(("atp-", "wta-", "itf-", "utr-", "challenger-"))
    ]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in fills:
        grouped[str(row.get("conditionId") or "").lower()].append(row)

    observed: list[dict[str, Any]] = []
    threshold_signals: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for condition_id, rows in grouped.items():
        settled = ledger.get(condition_id)
        market = metadata.get(condition_id)
        if not settled or not market:
            continue
        rows.sort(key=lambda row: int(row.get("timestamp") or 0))
        first_timestamp = int(rows[0].get("timestamp") or 0)
        first_batch = [
            row for row in rows if int(row.get("timestamp") or 0) <= first_timestamp + 2
        ]
        first_cost_by_outcome: dict[str, float] = defaultdict(float)
        first_shares_by_outcome: dict[str, float] = defaultdict(float)
        for row in first_batch:
            outcome = str(row.get("outcome") or "")
            shares = number(row.get("size"))
            first_shares_by_outcome[outcome] += shares
            first_cost_by_outcome[outcome] += shares * number(row.get("price"))
        first_outcome = max(first_cost_by_outcome, key=first_cost_by_outcome.get)
        first_price = first_cost_by_outcome[first_outcome] / first_shares_by_outcome[first_outcome]
        winner = next(
            (str(outcome["outcome"]) for outcome in settled["outcomes"] if outcome["won"]),
            "",
        )
        won = first_outcome == winner
        game_start = parse_utc(str(market["gameStartTime"]))
        first_time = datetime.fromtimestamp(first_timestamp, game_start.tzinfo)
        minutes_before = (game_start - first_time).total_seconds() / 60
        signal = {
                "condition_id": condition_id,
                "title": settled["title"],
                "first_fill_outcome": first_outcome,
                "winner": winner,
                "first_fill_price": first_price,
                "timestamp": first_timestamp,
                "first_fill_won": won,
                "first_fill_tail_return_units": (1 - first_price) / first_price if won else -1,
                "minutes_before_scheduled_start": minutes_before,
                "timing_band": timing_band(minutes_before),
                "fill_count": len(rows),
                "final_direction_status": settled["status"],
                "final_net_cost_usd": settled["net_directional_cost_usd"],
            }
        same_outcome = [
            row for row in rows if str(row.get("outcome") or "") == first_outcome
        ]
        for delay in (5, 15, 30, 60):
            later = next(
                (
                    row
                    for row in same_outcome
                    if int(row.get("timestamp") or 0) >= first_timestamp + delay
                ),
                None,
            )
            price = number(later.get("price")) if later else None
            signal[f"price_after_{delay}s"] = price
            signal[f"tail_after_{delay}s"] = (
                ((1 - price) / price if won else -1) if price else None
            )
        observed.append(signal)

        for threshold in (50.0, 100.0, 150.0, 287.5, 575.0, 1150.0):
            costs: dict[str, float] = defaultdict(float)
            crossing = None
            crossing_outcome = ""
            for row in rows:
                outcome = str(row.get("outcome") or "")
                costs[outcome] += number(row.get("size")) * number(row.get("price"))
                current_outcome = max(costs, key=costs.get)
                opposing = sum(cost for name, cost in costs.items() if name != current_outcome)
                if costs[current_outcome] - opposing >= threshold:
                    crossing = row
                    crossing_outcome = current_outcome
                    break
            if not crossing:
                continue
            price = number(crossing.get("price"))
            crossed_at = datetime.fromtimestamp(int(crossing["timestamp"]), game_start.tzinfo)
            threshold_signals[threshold].append(
                {
                    "first_fill_won": crossing_outcome == winner,
                    "first_fill_price": price,
                    "timestamp": int(crossing["timestamp"]),
                    "first_fill_tail_return_units": (
                        (1 - price) / price if crossing_outcome == winner else -1
                    ),
                    "minutes_before_scheduled_start": (
                        game_start - crossed_at
                    ).total_seconds()
                    / 60,
                }
            )

    by_timing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_price: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in observed:
        by_timing[row["timing_band"]].append(row)
        price = number(row["first_fill_price"])
        band = "UNDER_30C" if price < 0.30 else "30_TO_49C" if price < 0.50 else "50C_PLUS"
        by_price[band].append(row)

    prematch = [row for row in observed if number(row["minutes_before_scheduled_start"]) >= 0]
    live = [row for row in observed if number(row["minutes_before_scheduled_start"]) < 0]
    by_size: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in observed:
        units = number(row["final_net_cost_usd"]) / 575
        band = (
            "UNDER_0_25U"
            if units < 0.25
            else "0_25_TO_0_5U"
            if units < 0.5
            else "0_5_TO_1U"
            if units < 1
            else "1_TO_2U"
            if units < 2
            else "2U_PLUS"
        )
        by_size[band].append(row)
    report.pop("first_observed_signal_analysis", None)
    report["first_observed_signal_analysis"] = {
        "metadata_markets_with_exact_start": len(metadata),
        "settled_markets_joined_to_recent_fill_export": len(observed),
        "all_joined": summarize(observed),
        "prematch": summarize(prematch),
        "live_or_after_scheduled_start": summarize(live),
        "by_timing": {band: summarize(rows) for band, rows in sorted(by_timing.items())},
        "by_first_fill_price": {
            band: summarize(rows) for band, rows in sorted(by_price.items())
        },
        "by_final_net_size": {
            band: summarize(rows) for band, rows in sorted(by_size.items())
        },
        "observable_execution_latency": {
            f"after_{delay}_seconds": latency_summary(observed, delay)
            for delay in (5, 15, 30, 60)
        },
        "prospective_net_threshold_crossings": {
            str(threshold): summarize(
                [
                    row
                    for row in rows
                    if number(row["minutes_before_scheduled_start"]) >= 0
                ]
            )
            for threshold, rows in threshold_signals.items()
        },
        "median_minutes_before_scheduled_start": statistics.median(
            [number(row["minutes_before_scheduled_start"]) for row in observed]
        )
        if observed
        else None,
        "observed_market_ledger": observed,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["first_observed_signal_analysis"] | {"observed_market_ledger": "omitted"}, indent=2))


if __name__ == "__main__":
    main()
