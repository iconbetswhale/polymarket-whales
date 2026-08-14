from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.simulate_three_sharp_conviction_20000 import (
    AS_OF,
    HORIZONS,
    SIMULATION_START,
    add_conviction_sizing,
    number_summary,
    reconstruct_plays,
)

OUTPUT = ROOT / "outputs" / "three-sharp-flat-vs-conviction-20000-2026-08-03.json"
ARMS = {
    "flat_2x": "flat_stake_units",
    "conviction_scaled_2x": "conviction_stake_units",
}


def add_flat_sizing(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched = []
    for row in rows:
        item = dict(row)
        # Source stake_units is the original 1x flat strategy. Both comparison
        # arms use the approved 2x model; only conviction scaling differs.
        item["flat_stake_units"] = min(3.0, 2.0 * float(item["stake_units"]))
        enriched.append(item)
    return enriched


def replay(rows: list[dict[str, Any]], stake_field: str, bankroll: float) -> dict[str, Any]:
    initial = bankroll
    peak = bankroll
    worst_drawdown = 0.0
    dollars_staked = 0.0
    wins = 0
    stakes = []
    for row in rows:
        units = float(row[stake_field])
        stakes.append(units)
        stake = bankroll * units / 100.0
        dollars_staked += stake
        bankroll *= max(0.0, 1.0 + units / 100.0 * float(row["return_per_dollar"]))
        peak = max(peak, bankroll)
        worst_drawdown = max(worst_drawdown, (peak - bankroll) / peak)
        wins += int(bool(row["won"]))
    profit = bankroll - initial
    return {
        "bets": len(rows),
        "record": f"{wins}-{len(rows) - wins}",
        "win_rate": wins / len(rows) if rows else None,
        "average_stake_units": float(np.mean(stakes)) if stakes else None,
        "median_stake_units": float(np.median(stakes)) if stakes else None,
        "maximum_stake_units": float(np.max(stakes)) if stakes else None,
        "profit_dollars": profit,
        "profit_units_on_initial_bankroll": profit / (initial / 100.0),
        "return_on_bankroll": profit / initial,
        "betting_roi": profit / dollars_staked if dollars_staked else None,
        "maximum_drawdown_units": worst_drawdown * 100.0,
        "ending_bankroll": bankroll,
    }


def paired_simulation(
    rows: list[dict[str, Any]], *, days: int, paths: int, bankroll: float, seed: int
) -> dict[str, Any]:
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_day[str(row["date"])].append(row)
    blocks = [
        by_day[(SIMULATION_START + timedelta(days=offset)).isoformat()]
        for offset in range((AS_OF - SIMULATION_START).days + 1)
    ]
    rng = np.random.default_rng(seed)
    sampled_days = rng.integers(0, len(blocks), size=(paths, days))
    results: dict[str, dict[str, np.ndarray]] = {}
    bet_counts = np.empty(paths)

    for arm, stake_field in ARMS.items():
        ending = np.empty(paths)
        profit = np.empty(paths)
        drawdown = np.empty(paths)
        max_profit = np.empty(paths)
        for path_index in range(paths):
            current = bankroll
            peak = bankroll
            worst_drawdown = 0.0
            best_profit = 0.0
            bets = 0
            for block_index in sampled_days[path_index]:
                block = blocks[int(block_index)]
                bets += len(block)
                for row in block:
                    units = float(row[stake_field])
                    current *= max(
                        0.0,
                        1.0 + units / 100.0 * float(row["return_per_dollar"]),
                    )
                    peak = max(peak, current)
                    best_profit = max(best_profit, current - bankroll)
                    worst_drawdown = max(worst_drawdown, (peak - current) / peak)
            ending[path_index] = current
            profit[path_index] = current - bankroll
            drawdown[path_index] = worst_drawdown
            max_profit[path_index] = best_profit
            if arm == "flat_2x":
                bet_counts[path_index] = bets
        results[arm] = {
            "ending": ending,
            "profit": profit,
            "drawdown": drawdown,
            "max_profit": max_profit,
        }

    arms = {}
    for arm, values in results.items():
        arms[arm] = {
            "bets": number_summary(bet_counts),
            "ending_bankroll": number_summary(values["ending"]),
            "profit_dollars": number_summary(values["profit"]),
            "profit_units_on_initial_bankroll": number_summary(
                values["profit"] / (bankroll / 100.0)
            ),
            "probability_profitable": float(np.mean(values["profit"] > 0.0)),
            "maximum_drawdown_units": number_summary(values["drawdown"] * 100.0),
            "maximum_profit_units": number_summary(
                values["max_profit"] / (bankroll / 100.0)
            ),
        }

    flat = results["flat_2x"]
    scaled = results["conviction_scaled_2x"]
    delta_profit_units = (scaled["profit"] - flat["profit"]) / (bankroll / 100.0)
    delta_drawdown_units = (scaled["drawdown"] - flat["drawdown"]) * 100.0
    return {
        "arms": arms,
        "paired_difference_scaled_minus_flat": {
            "profit_units": number_summary(delta_profit_units),
            "maximum_drawdown_units": number_summary(delta_drawdown_units),
            "probability_scaled_more_profitable": float(np.mean(delta_profit_units > 1e-12)),
            "probability_flat_more_profitable": float(np.mean(delta_profit_units < -1e-12)),
            "probability_equal_profit": float(np.mean(np.abs(delta_profit_units) <= 1e-12)),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", type=int, default=20_000)
    parser.add_argument("--starting-bankroll", type=float, default=10_000.0)
    parser.add_argument("--seed", type=int, default=20260803)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    plays, exclusions, audit = reconstruct_plays()
    rows = add_flat_sizing(add_conviction_sizing(plays))
    rows = [row for row in rows if str(row["date"]) >= SIMULATION_START.isoformat()]
    windows = {}
    for days in HORIZONS:
        observed_start = AS_OF - timedelta(days=days - 1)
        observed = [row for row in rows if str(row["date"]) >= observed_start.isoformat()]
        windows[str(days)] = {
            "historical_replay": {
                arm: replay(observed, stake_field, args.starting_bankroll)
                for arm, stake_field in ARMS.items()
            },
            "simulation": paired_simulation(
                rows,
                days=days,
                paths=args.paths,
                bankroll=args.starting_bankroll,
                seed=args.seed + days,
            ),
        }

    payload = {
        "title": "Three-sharp paired sizing comparison",
        "as_of": AS_OF.isoformat(),
        "source_date_range": {"start": SIMULATION_START.isoformat(), "end": AS_OF.isoformat()},
        "source_play_count": len(rows),
        "starting_bankroll": args.starting_bankroll,
        "one_unit_initial_dollars": args.starting_bankroll / 100.0,
        "simulations_per_horizon": args.paths,
        "seed": args.seed,
        "arms": {
            "flat_2x": "Approved 2x flat wallet/consensus sizing; ignores within-wallet bet magnitude.",
            "conviction_scaled_2x": "Same 2x base sizing plus 1.00x-1.55x multiplier from each wallet's position relative to its own unit.",
        },
        "method": "Paired calendar-day block bootstrap. Each arm receives identical sampled dates, bets, prices, and outcomes; only stake sizing changes. All zero-bet dates are included.",
        "entry_price_limitation": "Historical entry is a copy-weighted median wallet-entry proxy, not a timestamp-perfect executable quote; slippage is excluded.",
        "exclusions": exclusions,
        "source_audit": audit,
        "stake_distribution": {
            arm: number_summary(np.asarray([row[field] for row in rows], dtype=float))
            for arm, field in ARMS.items()
        },
        "windows": windows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    for days in map(str, HORIZONS):
        sim = windows[days]["simulation"]
        print(f"{days}d")
        for arm in ARMS:
            value = sim["arms"][arm]
            print(arm, round(value["profit_units_on_initial_bankroll"]["median"], 3), round(value["maximum_drawdown_units"]["median"], 3), round(value["probability_profitable"] * 100, 2))
        diff = sim["paired_difference_scaled_minus_flat"]
        print("scaled-flat", round(diff["profit_units"]["median"], 3), round(diff["probability_scaled_more_profitable"] * 100, 2))


if __name__ == "__main__":
    main()
