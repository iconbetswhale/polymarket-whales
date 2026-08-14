from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = {
    "CURRENT_HYBRID": "HYBRID_CONSENSUS_2",
    "BALANCED_ONE_LEAD": "HYBRID_CORE_WITH_CONFIRMERS",
    "LEAD_ORIGINATORS_ONLY": "PRECISION_ONLY",
}
PERCENTILES = (0.01, 0.05, 0.50, 0.95, 0.99)


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def supporter_bucket(play: dict[str, Any]) -> str:
    count = len(play.get("supporters") or [])
    if count <= 1:
        return "ONE"
    if count == 2:
        return "TWO"
    return "3_PLUS"


def calibrate_edges(
    plays: list[dict[str, Any]],
    *,
    prior_sample_size: float,
    maximum_edge: float,
) -> dict[str, dict[str, float]]:
    residuals: dict[str, list[float]] = defaultdict(list)
    for play in plays:
        residual = float(bool(play["won"])) - float(play["price"])
        residuals["ALL"].append(residual)
        residuals[supporter_bucket(play)].append(residual)

    result: dict[str, dict[str, float]] = {}
    for bucket, values in residuals.items():
        edge = sum(values) / (len(values) + prior_sample_size)
        result[bucket] = {
            "plays": len(values),
            "raw_edge_points": round(sum(values) / len(values), 6),
            "shrunk_edge_points": round(
                clamp(edge, -maximum_edge, maximum_edge), 6
            ),
        }
    return result


def historical_summary(
    plays: list[dict[str, Any]], *, start: str, end: str
) -> dict[str, Any]:
    selected = [
        play for play in plays if start <= str(play["date"]) <= end
    ]
    if not selected:
        return {"bets": 0}
    start_date = np.datetime64(start)
    end_date = np.datetime64(end)
    calendar_days = int((end_date - start_date) / np.timedelta64(1, "D")) + 1
    stake = sum(float(play["stake_units"]) for play in selected)
    pnl = sum(float(play["sized_pnl_units"]) for play in selected)
    return {
        "bets": len(selected),
        "calendar_days": calendar_days,
        "bets_per_calendar_day": round(len(selected) / calendar_days, 3),
        "active_days": len({str(play["date"]) for play in selected}),
        "average_stake_units": round(
            sum(float(play["stake_units"]) for play in selected) / len(selected),
            4,
        ),
        "win_rate": round(
            sum(bool(play["won"]) for play in selected) / len(selected), 4
        ),
        "sized_roi": round(pnl / stake, 4) if stake else None,
        "estimated_days_for_2000_bets": round(
            2_000 / (len(selected) / calendar_days), 1
        ),
    }


def summarize_paths(
    final_bankrolls: np.ndarray,
    max_drawdowns: np.ndarray,
    *,
    starting_bankroll: float,
) -> dict[str, Any]:
    percentiles = np.quantile(final_bankrolls, PERCENTILES)
    return {
        "median_final_bankroll": round(float(np.median(final_bankrolls)), 2),
        "mean_final_bankroll": round(float(np.mean(final_bankrolls)), 2),
        "worst_sampled_final_bankroll": round(float(final_bankrolls.min()), 2),
        "best_sampled_final_bankroll": round(float(final_bankrolls.max()), 2),
        "probability_profitable": round(
            float(np.mean(final_bankrolls > starting_bankroll)), 4
        ),
        "probability_loss_20_percent": round(
            float(np.mean(final_bankrolls <= starting_bankroll * 0.80)), 4
        ),
        "final_bankroll_percentiles": {
            f"p{int(q * 100):02d}": round(float(value), 2)
            for q, value in zip(PERCENTILES, percentiles)
        },
        "maximum_drawdown": {
            "median": round(float(np.median(max_drawdowns)), 4),
            "p95": round(float(np.quantile(max_drawdowns, 0.95)), 4),
            "p99": round(float(np.quantile(max_drawdowns, 0.99)), 4),
            "worst_sampled": round(float(max_drawdowns.max()), 4),
        },
    }


def simulate(
    plays: list[dict[str, Any]],
    calibration: dict[str, dict[str, float]],
    *,
    paths: int,
    bets: int,
    starting_bankroll: float,
    edge_retention: float,
    seed: int,
    median_execution_cost: float,
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    prices = np.array([float(play["price"]) for play in plays])
    unit_fractions = np.array(
        [float(play["stake_units"]) * 0.01 for play in plays]
    )
    edges = np.array(
        [
            calibration.get(
                supporter_bucket(play), calibration["ALL"]
            )["shrunk_edge_points"]
            for play in plays
        ]
    )

    bankroll = np.full(paths, starting_bankroll, dtype=np.float64)
    peak = bankroll.copy()
    max_drawdown = np.zeros(paths, dtype=np.float64)

    for _ in range(bets):
        indices = rng.integers(0, len(plays), size=paths)
        quoted_price = prices[indices]
        # A lognormal cost prevents a single optimistic fixed slippage assumption.
        execution_cost = rng.lognormal(
            mean=math.log(max(median_execution_cost, 0.00001)),
            sigma=0.55,
            size=paths,
        )
        entry_price = np.minimum(0.99, quoted_price + execution_cost)
        probability = np.clip(
            quoted_price + edges[indices] * edge_retention, 0.01, 0.99
        )
        won = rng.random(paths) < probability
        risk_fraction = np.minimum(unit_fractions[indices], 0.02)
        returns = np.where(won, (1.0 - entry_price) / entry_price, -1.0)
        bankroll *= np.maximum(0.0, 1.0 + risk_fraction * returns)
        peak = np.maximum(peak, bankroll)
        drawdown = np.divide(
            peak - bankroll,
            peak,
            out=np.zeros_like(bankroll),
            where=peak > 0,
        )
        max_drawdown = np.maximum(max_drawdown, drawdown)

    return summarize_paths(
        bankroll, max_drawdown, starting_bankroll=starting_bankroll
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    source = json.loads(args.source.read_text(encoding="utf-8"))
    report: dict[str, Any] = {
        "methodology": {
            "scope": "Standard MLB moneylines only",
            "starting_bankroll": args.starting_bankroll,
            "bets_per_path": args.bets,
            "paths": args.paths,
            "development_period": f"through {args.calibration_end}",
            "evaluation_period": (
                f"{args.evaluation_start} through {args.evaluation_end}"
            ),
            "risk": (
                "Historical recommended units, where 1u risks 1% of current "
                "bankroll, capped at 2% per bet for both strategies."
            ),
            "execution": (
                "Each simulated fill pays a random lognormal price cost with "
                f"{args.execution_cost:.3%} median deterioration."
            ),
            "important_limit": (
                "The closed-position replay is not timestamp-perfect and does "
                "not reproduce the exact two-hour candidate set. The simulation "
                "compares strategy behavior; it does not guarantee future ROI."
            ),
        },
        "strategies": {},
    }

    for strategy_index, (label, ledger_name) in enumerate(STRATEGIES.items()):
        all_plays = source["play_ledger"][ledger_name]
        development = [
            play
            for play in all_plays
            if str(play["date"]) <= args.calibration_end
        ]
        evaluation = [
            play
            for play in all_plays
            if args.evaluation_start
            <= str(play["date"])
            <= args.evaluation_end
        ]
        calibration = calibrate_edges(
            development,
            prior_sample_size=args.prior_sample_size,
            maximum_edge=args.maximum_edge,
        )
        scenarios = {}
        for scenario_index, retention in enumerate((1.0, 0.5, 0.25, 0.0)):
            scenarios[f"{int(retention * 100)}_PERCENT_EDGE"] = simulate(
                evaluation,
                calibration,
                paths=args.paths,
                bets=args.bets,
                starting_bankroll=args.starting_bankroll,
                edge_retention=retention,
                seed=args.seed + strategy_index * 10_000 + scenario_index,
                median_execution_cost=args.execution_cost,
            )
        report["strategies"][label] = {
            "source_strategy": ledger_name,
            "rule": {
                "CURRENT_HYBRID": (
                    "Require at least two qualifying wallets, including a precision "
                    "lead; core conflict or sufficiently strong opposing portfolio "
                    "action rejects the play."
                ),
                "BALANCED_ONE_LEAD": (
                    "Allow one qualifying precision lead to originate; pass on "
                    "precision-lead conflicts or when weighted opposing portfolio "
                    "action materially exceeds confirming action."
                ),
                "LEAD_ORIGINATORS_ONLY": (
                    "Tail any qualifying precision lead; pass when precision "
                    "leads oppose each other; supporting wallets neither confirm "
                    "nor veto the play."
                ),
            }[label],
            "development_bets": len(development),
            "calibration": calibration,
            "historical_evaluation": historical_summary(
                all_plays,
                start=args.evaluation_start,
                end=args.evaluation_end,
            ),
            "simulation": scenarios,
        }
    return report


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
        default=ROOT / "outputs" / "strategy-ab-2000.json",
    )
    parser.add_argument("--paths", type=int, default=20_000)
    parser.add_argument("--bets", type=int, default=2_000)
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
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
