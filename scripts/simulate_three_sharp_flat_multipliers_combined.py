from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs" / "three-sharp-kelly-ab-2026-08-02.json"
PRIOR_SUMMARY = ROOT / "outputs" / "three-sharp-flat-multipliers-2026-08-02.json"
OUTPUT = ROOT / "outputs" / "three-sharp-flat-multipliers-combined-15000-2026-08-03.json"
AS_OF = date(2026, 8, 2)
MULTIPLIERS = (1, 2, 3, 4, 5)
PRIOR_PATHS = 5_000
PRIOR_SEED = 20260804
NEW_PATHS = 10_000
NEW_SEED = 20260831


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


def simulate_raw(
    rows: list[dict[str, Any]], *, days: int, paths: int, starting_bankroll: float, seed: int
) -> dict[str, Any]:
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_day[str(row["date"])].append(row)
    blocks = [by_day[key] for key in sorted(by_day)]
    if not blocks:
        raise ValueError("No evaluation-day blocks are available")

    rng = np.random.default_rng(seed)
    finals = {multiplier: np.zeros(paths) for multiplier in MULTIPLIERS}
    drawdowns = {multiplier: np.zeros(paths) for multiplier in MULTIPLIERS}
    bet_counts = np.zeros(paths)

    for path_index in range(paths):
        sampled = rng.integers(0, len(blocks), size=days)
        bankrolls = {multiplier: starting_bankroll for multiplier in MULTIPLIERS}
        peaks = dict(bankrolls)
        worst = {multiplier: 0.0 for multiplier in MULTIPLIERS}
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
                    worst[multiplier] = max(
                        worst[multiplier], (peaks[multiplier] - bankrolls[multiplier]) / peaks[multiplier]
                    )
        for multiplier in MULTIPLIERS:
            finals[multiplier][path_index] = bankrolls[multiplier]
            drawdowns[multiplier][path_index] = worst[multiplier]

    return {"finals": finals, "drawdowns": drawdowns, "bet_counts": bet_counts}


def batch_summary(raw: dict[str, Any], starting_bankroll: float) -> dict[str, Any]:
    result: dict[str, Any] = {
        "paths": int(len(raw["bet_counts"])),
        "expected_bets": float(np.mean(raw["bet_counts"])),
        "multipliers": {},
    }
    for multiplier in MULTIPLIERS:
        profit = raw["finals"][multiplier] - starting_bankroll
        drawdowns = raw["drawdowns"][multiplier]
        result["multipliers"][str(multiplier)] = {
            "profit_dollars": summarize(profit),
            "profit_initial_units": summarize(profit / (starting_bankroll / 100.0)),
            "maximum_drawdown_fraction": {
                "median": float(np.median(drawdowns)),
                "p95": float(np.quantile(drawdowns, 0.95)),
                "p99": float(np.quantile(drawdowns, 0.99)),
                "maximum_observed": float(np.max(drawdowns)),
            },
            "maximum_drawdown_peak_units": {
                "median": float(np.median(drawdowns) * 100.0),
                "p95": float(np.quantile(drawdowns, 0.95) * 100.0),
                "p99": float(np.quantile(drawdowns, 0.99) * 100.0),
                "maximum_observed": float(np.max(drawdowns) * 100.0),
            },
            "probability_profitable": float(np.mean(profit > 0)),
        }
    return result


def concatenate(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    return {
        "finals": {
            multiplier: np.concatenate([first["finals"][multiplier], second["finals"][multiplier]])
            for multiplier in MULTIPLIERS
        },
        "drawdowns": {
            multiplier: np.concatenate([first["drawdowns"][multiplier], second["drawdowns"][multiplier]])
            for multiplier in MULTIPLIERS
        },
        "bet_counts": np.concatenate([first["bet_counts"], second["bet_counts"]]),
    }


def verify_prior_reproduction(prior: dict[str, Any], reproduced: dict[str, Any]) -> None:
    for days in (7, 30, 60):
        for multiplier in MULTIPLIERS:
            expected = prior["windows"][str(days)]["simulation"]["multipliers"][str(multiplier)]
            actual = reproduced[str(days)]["multipliers"][str(multiplier)]
            if not np.isclose(expected["profit_dollars"]["median"], actual["profit_dollars"]["median"]):
                raise AssertionError(f"Prior median mismatch for {days}d {multiplier}x")
            if not np.isclose(
                expected["maximum_drawdown"]["maximum_observed"],
                actual["maximum_drawdown_fraction"]["maximum_observed"],
            ):
                raise AssertionError(f"Prior maximum drawdown mismatch for {days}d {multiplier}x")


def run(starting_bankroll: float) -> dict[str, Any]:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    prior = json.loads(PRIOR_SUMMARY.read_text(encoding="utf-8"))
    evaluation_start = source["data"]["simulation_evaluation_start"]
    evaluation_rows = [row for row in source["play_ledger"] if str(row["date"]) >= evaluation_start]

    prior_summaries: dict[str, Any] = {}
    windows: dict[str, Any] = {}
    for days in (7, 30, 60):
        prior_raw = simulate_raw(
            evaluation_rows,
            days=days,
            paths=PRIOR_PATHS,
            starting_bankroll=starting_bankroll,
            seed=PRIOR_SEED + days,
        )
        new_raw = simulate_raw(
            evaluation_rows,
            days=days,
            paths=NEW_PATHS,
            starting_bankroll=starting_bankroll,
            seed=NEW_SEED + days,
        )
        combined_raw = concatenate(prior_raw, new_raw)
        prior_summary = batch_summary(prior_raw, starting_bankroll)
        prior_summaries[str(days)] = prior_summary
        windows[str(days)] = {
            "prior_5000": prior_summary,
            "new_10000": batch_summary(new_raw, starting_bankroll),
            "combined_15000": batch_summary(combined_raw, starting_bankroll),
        }

    verify_prior_reproduction(prior, prior_summaries)
    payload: dict[str, Any] = {
        "as_of": AS_OF.isoformat(),
        "generated_on": date.today().isoformat(),
        "starting_bankroll": starting_bankroll,
        "initial_unit_dollars": starting_bankroll / 100.0,
        "source_play_count": len(evaluation_rows),
        "prior_batch": {"paths": PRIOR_PATHS, "seed": PRIOR_SEED},
        "new_batch": {"paths": NEW_PATHS, "seed": NEW_SEED},
        "combined_paths_per_horizon": PRIOR_PATHS + NEW_PATHS,
        "multipliers": list(MULTIPLIERS),
        "base_sizing": source["arms"]["flat"],
        "scope": source["scope"],
        "simulation_method": (
            "Two reproducible paired calendar-day bootstrap batches. The original 5,000-path batch is "
            "reproduced with its original seed; a disjoint 10,000-path batch uses a new seed. Raw ending "
            "bankrolls and path drawdowns are concatenated before combined summaries are calculated."
        ),
        "unit_definition": (
            "Profit units equal profit dollars divided by the initial $100 unit. Drawdown units equal the "
            "percentage decline from each path's running peak, where one percentage point is labeled one peak unit."
        ),
        "entry_price_limitation": source["data"]["entry_price"],
        "windows": windows,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["deterministic_sha256"] = hashlib.sha256(canonical).hexdigest().upper()
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--starting-bankroll", type=float, default=10_000.0)
    args = parser.parse_args()
    payload = run(args.starting_bankroll)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    print("sha256", payload["deterministic_sha256"])
    for days in ("7", "30", "60"):
        for multiplier in map(str, MULTIPLIERS):
            row = payload["windows"][days]["combined_15000"]["multipliers"][multiplier]
            print(
                days,
                multiplier,
                "max_dd_u",
                round(row["maximum_drawdown_peak_units"]["maximum_observed"], 2),
                "median_profit_u",
                round(row["profit_initial_units"]["median"], 2),
                "max_profit_u",
                round(row["profit_initial_units"]["maximum_observed"], 2),
            )


if __name__ == "__main__":
    main()
