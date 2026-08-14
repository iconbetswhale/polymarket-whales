from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_three_sharp_kelly_ab import WALLETS
from scripts.simulate_three_sharp_conviction_20000 import (
    AS_OF,
    HORIZONS,
    SIMULATION_START,
    number_summary,
    reconstruct_plays,
)


OUTPUT = ROOT / "outputs" / "three-sharp-oddsjam-vs-flat-5000-2026-08-05.json"
ARMS = {
    "flat_1x": "flat_1x_stake_units",
    "oddsjam_formula_proxy": "oddsjam_stake_units",
}


def return_per_dollar(entry_price: float, won: bool) -> float:
    return (1.0 - entry_price) / entry_price if won else -1.0


def add_sizing(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        supporters = list(row["supporters"])
        supporter_relative_units = row.get("supporter_relative_units") or {}
        weights = np.asarray(
            [float(WALLETS[label]["copy_weight"]) for label in supporters],
            dtype=float,
        )
        relative_sizes = np.asarray(
            [float(supporter_relative_units.get(label) or 1.0) for label in supporters],
            dtype=float,
        )
        relative_size_proxy = float(np.average(relative_sizes, weights=weights))
        price = float(row["entry_price_proxy"])

        item = dict(row)
        item["flat_1x_stake_units"] = float(row["stake_units"])
        # OddsJam dollars = bankroll * 0.006 * relative size * contract price.
        # Because 1u is 1% of bankroll, the equivalent unit stake is:
        # 0.6 * relative size * contract price.
        item["oddsjam_relative_size_proxy"] = relative_size_proxy
        item["oddsjam_stake_units"] = 0.6 * relative_size_proxy * price
        item["return_per_dollar"] = return_per_dollar(price, bool(row["won"]))
        enriched.append(item)
    return enriched


def replay(rows: list[dict[str, Any]], stake_field: str, bankroll: float) -> dict[str, Any]:
    initial = bankroll
    peak = bankroll
    worst_drawdown = 0.0
    best_profit = 0.0
    dollars_staked = 0.0
    wins = 0
    stakes: list[float] = []
    for row in rows:
        units = float(row[stake_field])
        stakes.append(units)
        stake = bankroll * units / 100.0
        dollars_staked += stake
        bankroll *= max(0.0, 1.0 + units / 100.0 * float(row["return_per_dollar"]))
        peak = max(peak, bankroll)
        worst_drawdown = max(worst_drawdown, (peak - bankroll) / peak)
        best_profit = max(best_profit, bankroll - initial)
        wins += int(bool(row["won"]))
    profit = bankroll - initial
    return {
        "bets": len(rows),
        "record": f"{wins}-{len(rows) - wins}",
        "win_rate": wins / len(rows) if rows else None,
        "average_stake_units": float(np.mean(stakes)) if stakes else None,
        "median_stake_units": float(np.median(stakes)) if stakes else None,
        "maximum_stake_units": float(np.max(stakes)) if stakes else None,
        "dollars_staked": dollars_staked,
        "ending_bankroll": bankroll,
        "profit_dollars": profit,
        "profit_units_on_initial_bankroll": profit / (initial / 100.0),
        "return_on_bankroll": profit / initial,
        "betting_roi": profit / dollars_staked if dollars_staked else None,
        "maximum_drawdown_units": worst_drawdown * 100.0,
        "maximum_profit_units": best_profit / (initial / 100.0),
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
    bet_counts = np.empty(paths)
    results: dict[str, dict[str, np.ndarray]] = {}

    for arm, stake_field in ARMS.items():
        ending = np.empty(paths)
        profit = np.empty(paths)
        drawdown = np.empty(paths)
        max_profit = np.empty(paths)
        staked = np.empty(paths)
        for path_index in range(paths):
            current = bankroll
            peak = bankroll
            worst_drawdown = 0.0
            best_profit = 0.0
            dollars_staked = 0.0
            bets = 0
            for block_index in sampled_days[path_index]:
                block = blocks[int(block_index)]
                bets += len(block)
                for row in block:
                    units = float(row[stake_field])
                    dollars_staked += current * units / 100.0
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
            staked[path_index] = dollars_staked
            if arm == "flat_1x":
                bet_counts[path_index] = bets
        results[arm] = {
            "ending": ending,
            "profit": profit,
            "drawdown": drawdown,
            "max_profit": max_profit,
            "staked": staked,
        }

    arms: dict[str, Any] = {}
    for arm, values in results.items():
        arms[arm] = {
            "bets": number_summary(bet_counts),
            "ending_bankroll": number_summary(values["ending"]),
            "profit_dollars": number_summary(values["profit"]),
            "profit_units_on_initial_bankroll": number_summary(
                values["profit"] / (bankroll / 100.0)
            ),
            "betting_roi": number_summary(
                np.divide(
                    values["profit"],
                    values["staked"],
                    out=np.zeros_like(values["profit"]),
                    where=values["staked"] > 0.0,
                )
            ),
            "probability_profitable": float(np.mean(values["profit"] > 0.0)),
            "maximum_drawdown_units": number_summary(values["drawdown"] * 100.0),
            "maximum_profit_units": number_summary(
                values["max_profit"] / (bankroll / 100.0)
            ),
        }

    flat = results["flat_1x"]
    oddsjam = results["oddsjam_formula_proxy"]
    delta_profit_units = (oddsjam["profit"] - flat["profit"]) / (bankroll / 100.0)
    delta_drawdown_units = (oddsjam["drawdown"] - flat["drawdown"]) * 100.0
    return {
        "arms": arms,
        "paired_difference_oddsjam_minus_flat": {
            "profit_units": number_summary(delta_profit_units),
            "maximum_drawdown_units": number_summary(delta_drawdown_units),
            "probability_oddsjam_more_profitable": float(
                np.mean(delta_profit_units > 1e-12)
            ),
            "probability_flat_more_profitable": float(
                np.mean(delta_profit_units < -1e-12)
            ),
            "probability_equal_profit": float(
                np.mean(np.abs(delta_profit_units) <= 1e-12)
            ),
        },
    }


def build_payload(paths: int, starting_bankroll: float, seed: int) -> dict[str, Any]:
    plays, exclusions, audit = reconstruct_plays()
    rows = add_sizing(plays)
    evaluation_rows = [
        row for row in rows if str(row["date"]) >= SIMULATION_START.isoformat()
    ]
    windows: dict[str, Any] = {}
    for days in HORIZONS:
        observed_start = AS_OF - timedelta(days=days - 1)
        observed = [
            row for row in rows if str(row["date"]) >= observed_start.isoformat()
        ]
        windows[str(days)] = {
            "observed_start": observed_start.isoformat(),
            "observed_end": AS_OF.isoformat(),
            "historical_replay": {
                arm: replay(observed, stake_field, starting_bankroll)
                for arm, stake_field in ARMS.items()
            },
            "simulation": paired_simulation(
                evaluation_rows,
                days=days,
                paths=paths,
                bankroll=starting_bankroll,
                seed=seed + days,
            ),
        }

    payload: dict[str, Any] = {
        "title": "Three-sharp OddsJam-formula versus original 1x flat sizing",
        "generated_on": date.today().isoformat(),
        "as_of": AS_OF.isoformat(),
        "starting_bankroll": starting_bankroll,
        "one_unit_initial_dollars": starting_bankroll / 100.0,
        "simulations_per_horizon": paths,
        "seed": seed,
        "source_date_range": {
            "start": SIMULATION_START.isoformat(),
            "end": AS_OF.isoformat(),
        },
        "source_play_count": len(evaluation_rows),
        "scope": (
            "Same three sharp wallets, settled MLB full-game moneylines, main +/-1.5 "
            "run lines, and highest-volume full-game totals; qualifying cross-wallet "
            "contradictions are vetoed."
        ),
        "arms": {
            "flat_1x": (
                "Original 1x model sizing: 0.50u base multiplied by wallet copy weight "
                "and a 1.15x step for each additional agreeing sharp, capped at 1.50u."
            ),
            "oddsjam_formula_proxy": (
                "Stake = bankroll x 0.006 x relative sharp size x contract price. "
                "Relative sharp size is the copy-weighted mean of each agreeing wallet's "
                "position divided by its configured wallet unit."
            ),
        },
        "critical_limitation": (
            "The OddsJam stake equation is reconstructed from screenshots, but OddsJam's "
            "hidden relative-size denominator is only directly observed for Formal-Cupcake. "
            "The comparison is formula-exact but uses the model's wallet-relative sizing "
            "normalization as a proxy for all three wallets. No unobserved confidence-score "
            "modifier is applied."
        ),
        "method": (
            "Paired seeded calendar-day block bootstrap. Both arms receive identical sampled "
            "dates, bets, prices, outcomes, zero-bet days, and contradiction exclusions; only "
            "stake sizing differs. Bankroll compounds after every bet."
        ),
        "entry_price_limitation": (
            "Historical entry is a copy-weighted median wallet-entry proxy, not a timestamp-"
            "perfect executable quote; slippage is excluded."
        ),
        "exclusions": exclusions,
        "source_audit": audit,
        "stake_distribution": {
            arm: number_summary(
                np.asarray([row[field] for row in evaluation_rows], dtype=float)
            )
            for arm, field in ARMS.items()
        },
        "relative_size_proxy_distribution": number_summary(
            np.asarray(
                [row["oddsjam_relative_size_proxy"] for row in evaluation_rows],
                dtype=float,
            )
        ),
        "windows": windows,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["reproducibility_sha256"] = hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", type=int, default=5_000)
    parser.add_argument("--starting-bankroll", type=float, default=10_000.0)
    parser.add_argument("--seed", type=int, default=20260805)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    payload = build_payload(args.paths, args.starting_bankroll, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    for days in map(str, HORIZONS):
        simulation = payload["windows"][days]["simulation"]
        print(f"{days}d")
        for arm in ARMS:
            values = simulation["arms"][arm]
            print(
                arm,
                "median_profit_units=",
                round(values["profit_units_on_initial_bankroll"]["median"], 3),
                "p05=",
                round(values["profit_units_on_initial_bankroll"]["p05"], 3),
                "p95=",
                round(values["profit_units_on_initial_bankroll"]["p95"], 3),
                "median_roi=",
                round(values["betting_roi"]["median"] * 100.0, 2),
                "profitable=",
                round(values["probability_profitable"] * 100.0, 2),
            )


if __name__ == "__main__":
    main()
