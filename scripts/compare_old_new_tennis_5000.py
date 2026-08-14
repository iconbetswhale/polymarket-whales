from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs" / "bagwell-lilybaeum-tennis-5000-comparison-2026-08-08.json"
OUTPUT = ROOT / "outputs" / "old-vs-weighted-tennis-model-5000-2026-08-09.json"
START = date(2026, 6, 22)
END = date(2026, 8, 4)
HORIZONS = (7, 30, 60, 90)

ARM_STAKES = {
    "old_equal_model": {"Bagwell306": 1.0, "Lilybaeum": 1.0, "agreement": 2.0},
    "new_weighted_model": {"Bagwell306": 1.0, "Lilybaeum": 0.75, "agreement": 2.0},
}


def number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def play_return(play: dict[str, Any]) -> float:
    price = number(play["entry_price"])
    return (1.0 - price) / price if play["won"] else -1.0


def build_arm(
    bagwell: list[dict[str, Any]],
    lily: list[dict[str, Any]],
    stakes: dict[str, float],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for play in [*bagwell, *lily]:
        grouped[str(play["condition_id"])].append(play)

    result: list[dict[str, Any]] = []
    structure: dict[str, int] = defaultdict(int)
    for rows in grouped.values():
        if len(rows) == 1:
            row = rows[0]
            wallet = str(row["wallet"])
            result.append({**row, "stake_units": stakes[wallet], "agreement": "one_sharp"})
            structure[f"{wallet}_standalone"] += 1
            continue
        if len({str(row["selection"]) for row in rows}) > 1:
            structure["direct_conflict_skipped"] += 1
            continue
        leader = rows[0]
        result.append(
            {
                **leader,
                "wallet": "Bagwell306+Lilybaeum",
                "entry_price": max(number(row["entry_price"]) for row in rows),
                "stake_units": stakes["agreement"],
                "agreement": "two_sharp_agreement",
            }
        )
        structure["two_sharp_agreement"] += 1
    return sorted(result, key=lambda row: (row["start"], row["condition_id"])), dict(structure)


def summarize(plays: list[dict[str, Any]]) -> dict[str, Any]:
    equity = peak = drawdown = stake = profit = 0.0
    wins = 0
    for play in plays:
        units = number(play["stake_units"])
        pnl = units * play_return(play)
        equity += pnl
        profit += pnl
        stake += units
        wins += int(bool(play["won"]))
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "bets": len(plays),
        "record": f"{wins}-{len(plays) - wins}",
        "staked_units": stake,
        "profit_units": profit,
        "betting_roi": profit / stake if stake else 0.0,
        "maximum_drawdown_units": drawdown,
        "average_stake_units": stake / len(plays) if plays else 0.0,
    }


def metric(values: np.ndarray) -> dict[str, float]:
    return {
        "worst": float(np.min(values)),
        "p05": float(np.quantile(values, 0.05)),
        "median": float(np.median(values)),
        "mean": float(np.mean(values)),
        "p95": float(np.quantile(values, 0.95)),
        "best": float(np.max(values)),
    }


def simulate_paired(
    arms: dict[str, list[dict[str, Any]]],
    *,
    horizon: int,
    paths: int,
    seed: int,
) -> dict[str, Any]:
    days = [(START + timedelta(days=index)).isoformat() for index in range((END - START).days + 1)]
    by_arm_day: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for name, plays in arms.items():
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for play in plays:
            grouped[str(play["date"])].append(play)
        by_arm_day[name] = grouped

    rng = np.random.default_rng(seed)
    samples = rng.integers(0, len(days), size=(paths, horizon))
    results: dict[str, dict[str, Any]] = {}
    raw_profit: dict[str, np.ndarray] = {}
    for name in arms:
        profits = np.zeros(paths)
        stakes = np.zeros(paths)
        drawdowns = np.zeros(paths)
        bets = np.zeros(paths)
        wins = np.zeros(paths)
        for path in range(paths):
            equity = peak = 0.0
            for block_index in samples[path]:
                for play in by_arm_day[name][days[int(block_index)]]:
                    units = number(play["stake_units"])
                    pnl = units * play_return(play)
                    equity += pnl
                    profits[path] += pnl
                    stakes[path] += units
                    bets[path] += 1
                    wins[path] += int(bool(play["won"]))
                    peak = max(peak, equity)
                    drawdowns[path] = max(drawdowns[path], peak - equity)
        roi = np.divide(profits, stakes, out=np.zeros_like(profits), where=stakes > 0)
        raw_profit[name] = profits
        results[name] = {
            "plays": metric(bets),
            "median_record": f"{round(float(np.median(wins)))}-{round(float(np.median(bets - wins)))}",
            "profit_units": metric(profits),
            "betting_roi": metric(roi),
            "maximum_drawdown_units": metric(drawdowns),
            "probability_profitable": float(np.mean(profits > 0)),
        }

    difference = raw_profit["new_weighted_model"] - raw_profit["old_equal_model"]
    return {
        "arms": results,
        "paired_new_minus_old": {
            "profit_units": metric(difference),
            "probability_new_more_profitable": float(np.mean(difference > 0)),
            "probability_old_more_profitable": float(np.mean(difference < 0)),
            "probability_equal": float(np.mean(np.isclose(difference, 0.0))),
        },
    }


def run(paths: int, seed: int) -> dict[str, Any]:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    ledgers = source["qualified_play_ledgers"]
    bagwell = list(ledgers["Bagwell306"])
    lily = list(ledgers["Lilybaeum"])
    arms: dict[str, list[dict[str, Any]]] = {}
    structures: dict[str, dict[str, int]] = {}
    for name, stakes in ARM_STAKES.items():
        arms[name], structures[name] = build_arm(bagwell, lily, stakes)
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "paths": paths,
        "source_window": {"start": START.isoformat(), "end": END.isoformat()},
        "rules": ARM_STAKES,
        "structure": structures,
        "historical_replay": {name: summarize(plays) for name, plays in arms.items()},
        "simulations": {
            str(days): simulate_paired(arms, horizon=days, paths=paths, seed=seed + days)
            for days in HORIZONS
        },
        "methodology": {
            "qualification": source["methodology"]["qualification"],
            "sampling": "Paired empirical calendar-day block bootstrap; both arms receive identical sampled days.",
            "entry_proxy": source["methodology"]["entry_proxy"],
            "scope": "Only the lead-weighting change is tested. Settlement-only confirmer candidates are excluded.",
            "limitations": [
                "The qualified common window contains only 55 bets and two same-side agreements.",
                "The source ends on 2026-08-04 and is not a guarantee of future performance.",
                "Executable slippage and exchange fees are not included.",
            ],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20260809)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    payload = run(args.paths, args.seed)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    print(json.dumps({"historical_replay": payload["historical_replay"], "simulations": payload["simulations"]}, indent=2))


if __name__ == "__main__":
    main()
