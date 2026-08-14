from __future__ import annotations

import argparse
import json
from pathlib import Path

from simulate_strategy_ab_2000 import calibrate_edges, simulate


ROOT = Path(__file__).resolve().parents[1]
LEDGER_NAME = "HYBRID_CORE_WITH_CONFIRMERS"


def run(args: argparse.Namespace) -> dict:
    source = json.loads(args.source.read_text(encoding="utf-8"))
    plays = source["play_ledger"][LEDGER_NAME]
    development = [
        play for play in plays if str(play["date"]) <= args.calibration_end
    ]
    evaluation = [
        play
        for play in plays
        if args.evaluation_start <= str(play["date"]) <= args.evaluation_end
    ]
    calibration = calibrate_edges(
        development,
        prior_sample_size=args.prior_sample_size,
        maximum_edge=args.maximum_edge,
    )

    scenarios = {}
    for retention_index, retention in enumerate((1.0, 0.5, 0.25, 0.0)):
        volume_rows = {}
        for bets_per_day in range(1, args.maximum_bets_per_day + 1):
            total_bets = bets_per_day * args.days
            volume_rows[str(bets_per_day)] = {
                "bets_per_day": bets_per_day,
                "total_bets": total_bets,
                **simulate(
                    evaluation,
                    calibration,
                    paths=args.paths,
                    bets=total_bets,
                    starting_bankroll=args.starting_bankroll,
                    edge_retention=retention,
                    seed=(
                        args.seed
                        + retention_index * 100_000
                        + bets_per_day * 1_000
                    ),
                    median_execution_cost=args.execution_cost,
                ),
            }
        scenarios[f"{int(retention * 100)}_PERCENT_EDGE"] = volume_rows

    return {
        "methodology": {
            "strategy": "Balanced One Lead",
            "market": "Standard MLB moneylines",
            "season_days": args.days,
            "paths_per_volume": args.paths,
            "starting_bankroll": args.starting_bankroll,
            "risk": (
                "Historical strategy stake units; 1u equals 1% of current "
                "bankroll and each trade is capped at 2%."
            ),
            "execution": (
                f"Random fill deterioration with a {args.execution_cost:.3%} "
                "median."
            ),
            "primary_scenario": (
                "50% edge retention. The 100%, 25%, and 0% cases are "
                "sensitivity tests."
            ),
            "extreme_definition": (
                "p01/p99 are distribution estimates. Worst sampled is not a "
                "mathematical maximum; complete bankroll loss remains "
                "theoretically possible."
            ),
        },
        "calibration": calibration,
        "evaluation_plays": len(evaluation),
        "scenarios": scenarios,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT
        / "outputs"
        / "mlb-hybrid-monte-carlo"
        / "source-replay.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "outputs" / "balanced-daily-volume-simulation.json",
    )
    parser.add_argument("--paths", type=int, default=50_000)
    parser.add_argument("--days", type=int, default=162)
    parser.add_argument("--maximum-bets-per-day", type=int, default=5)
    parser.add_argument("--starting-bankroll", type=float, default=10_000.0)
    parser.add_argument("--seed", type=int, default=20260728)
    parser.add_argument("--calibration-end", default="2026-06-30")
    parser.add_argument("--evaluation-start", default="2026-07-01")
    parser.add_argument("--evaluation-end", default="2026-07-26")
    parser.add_argument("--prior-sample-size", type=float, default=40.0)
    parser.add_argument("--maximum-edge", type=float, default=0.05)
    parser.add_argument("--execution-cost", type=float, default=0.009)
    args = parser.parse_args()
    result = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)


if __name__ == "__main__":
    main()
