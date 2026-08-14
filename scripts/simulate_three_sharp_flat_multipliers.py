from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs" / "three-sharp-kelly-ab-2026-08-02.json"
OUTPUT = ROOT / "outputs" / "three-sharp-flat-multipliers-2026-08-02.json"
AS_OF = date(2026, 8, 2)
MULTIPLIERS = (1, 2, 3, 4, 5)


def position_return(price: float, won: bool) -> float:
    return (1.0 - price) / price if won else -1.0


def summarize(values: np.ndarray) -> dict[str, float]:
    return {
        "p01": float(np.quantile(values, 0.01)),
        "p05": float(np.quantile(values, 0.05)),
        "p25": float(np.quantile(values, 0.25)),
        "median": float(np.median(values)),
        "mean": float(np.mean(values)),
        "p75": float(np.quantile(values, 0.75)),
        "p95": float(np.quantile(values, 0.95)),
        "p99": float(np.quantile(values, 0.99)),
        "minimum_observed": float(np.min(values)),
        "maximum_observed": float(np.max(values)),
    }


def replay(rows: list[dict[str, Any]], multiplier: int, starting_bankroll: float) -> dict[str, Any]:
    bankroll = starting_bankroll
    peak = bankroll
    maximum_drawdown = 0.0
    dollars_staked = 0.0
    for row in rows:
        units = float(row["stake_units"]) * multiplier
        stake = bankroll * units / 100.0
        dollars_staked += stake
        bankroll *= max(0.0, 1.0 + units / 100.0 * position_return(float(row["entry_price_proxy"]), bool(row["won"])))
        peak = max(peak, bankroll)
        maximum_drawdown = max(maximum_drawdown, (peak - bankroll) / peak)
    profit = bankroll - starting_bankroll
    return {
        "bets": len(rows),
        "record": f"{sum(bool(row['won']) for row in rows)}-{sum(not bool(row['won']) for row in rows)}",
        "average_stake_units": float(np.mean([float(row["stake_units"]) * multiplier for row in rows])),
        "ending_bankroll": bankroll,
        "profit_dollars": profit,
        "return_on_bankroll": profit / starting_bankroll,
        "dollars_staked": dollars_staked,
        "betting_roi": profit / dollars_staked if dollars_staked else 0.0,
        "maximum_drawdown": maximum_drawdown,
    }


def simulate(
    rows: list[dict[str, Any]], *, days: int, paths: int, starting_bankroll: float, seed: int
) -> dict[str, Any]:
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_day[str(row["date"])].append(row)
    blocks = [by_day[key] for key in sorted(by_day)]
    rng = np.random.default_rng(seed)
    finals = {multiplier: np.zeros(paths) for multiplier in MULTIPLIERS}
    drawdowns = {multiplier: np.zeros(paths) for multiplier in MULTIPLIERS}
    daily_paths = {multiplier: [] for multiplier in MULTIPLIERS}
    bet_counts = np.zeros(paths)

    for path_index in range(paths):
        sampled = rng.integers(0, len(blocks), size=days)
        bankrolls = {multiplier: starting_bankroll for multiplier in MULTIPLIERS}
        peaks = dict(bankrolls)
        worst = {multiplier: 0.0 for multiplier in MULTIPLIERS}
        daily = {multiplier: [starting_bankroll] for multiplier in MULTIPLIERS}
        for block_index in sampled:
            block = blocks[int(block_index)]
            bet_counts[path_index] += len(block)
            for row in block:
                base_units = float(row["stake_units"])
                result = position_return(float(row["entry_price_proxy"]), bool(row["won"]))
                for multiplier in MULTIPLIERS:
                    units = base_units * multiplier
                    bankrolls[multiplier] *= max(0.0, 1.0 + units / 100.0 * result)
                    peaks[multiplier] = max(peaks[multiplier], bankrolls[multiplier])
                    worst[multiplier] = max(worst[multiplier], (peaks[multiplier] - bankrolls[multiplier]) / peaks[multiplier])
            for multiplier in MULTIPLIERS:
                daily[multiplier].append(bankrolls[multiplier])
        for multiplier in MULTIPLIERS:
            finals[multiplier][path_index] = bankrolls[multiplier]
            drawdowns[multiplier][path_index] = worst[multiplier]
            daily_paths[multiplier].append(daily[multiplier])

    output: dict[str, Any] = {"expected_bets": float(np.mean(bet_counts)), "multipliers": {}}
    for multiplier in MULTIPLIERS:
        profit = finals[multiplier] - starting_bankroll
        path_array = np.asarray(daily_paths[multiplier])
        output["multipliers"][str(multiplier)] = {
            "average_starting_stake_units": multiplier * float(np.mean([float(row["stake_units"]) for row in rows])),
            "profit_dollars": summarize(profit),
            "ending_bankroll": summarize(finals[multiplier]),
            "probability_profitable": float(np.mean(profit > 0)),
            "probability_losing_10_percent": float(np.mean(finals[multiplier] <= starting_bankroll * 0.90)),
            "probability_losing_20_percent": float(np.mean(finals[multiplier] <= starting_bankroll * 0.80)),
            "maximum_drawdown": {
                "median": float(np.median(drawdowns[multiplier])),
                "p90": float(np.quantile(drawdowns[multiplier], 0.90)),
                "p95": float(np.quantile(drawdowns[multiplier], 0.95)),
                "p99": float(np.quantile(drawdowns[multiplier], 0.99)),
                "maximum_observed": float(np.max(drawdowns[multiplier])),
            },
            "percentile_paths": {
                label: np.quantile(path_array, quantile, axis=0).tolist()
                for label, quantile in (("p05", 0.05), ("median", 0.50), ("p95", 0.95))
            },
        }
    return output


def run(paths: int, starting_bankroll: float, seed: int) -> dict[str, Any]:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    evaluation_start = source["data"]["simulation_evaluation_start"]
    evaluation_rows = [row for row in source["play_ledger"] if str(row["date"]) >= evaluation_start]
    windows: dict[str, Any] = {}
    for days in (7, 30, 60):
        start = AS_OF - timedelta(days=days - 1)
        observed_rows = [row for row in source["play_ledger"] if str(row["date"]) >= start.isoformat()]
        windows[str(days)] = {
            "start": start.isoformat(),
            "end": AS_OF.isoformat(),
            "observed": {str(multiplier): replay(observed_rows, multiplier, starting_bankroll) for multiplier in MULTIPLIERS},
            "simulation": simulate(evaluation_rows, days=days, paths=paths, starting_bankroll=starting_bankroll, seed=seed + days),
        }
    return {
        "as_of": AS_OF.isoformat(),
        "starting_bankroll": starting_bankroll,
        "simulations_per_horizon": paths,
        "multipliers": list(MULTIPLIERS),
        "base_sizing": source["arms"]["flat"],
        "scope": source["scope"],
        "source_play_count": len(evaluation_rows),
        "simulation_method": "Paired calendar-day bootstrap. Every multiplier receives identical sampled days, plays, prices, and outcomes; only the current weighted flat stake is multiplied by 1x through 5x, and bankroll compounds.",
        "entry_price_limitation": source["data"]["entry_price"],
        "windows": windows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--paths", type=int, default=5_000)
    parser.add_argument("--starting-bankroll", type=float, default=10_000.0)
    parser.add_argument("--seed", type=int, default=20260804)
    args = parser.parse_args()
    payload = run(args.paths, args.starting_bankroll, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    for days in ("7", "30", "60"):
        for multiplier in map(str, MULTIPLIERS):
            row = payload["windows"][days]["simulation"]["multipliers"][multiplier]
            print(days, multiplier, round(row["profit_dollars"]["median"], 2), round(row["maximum_drawdown"]["median"] * 100, 2))


if __name__ == "__main__":
    main()
