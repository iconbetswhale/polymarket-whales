from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
AS_OF = date(2026, 8, 2)
HISTORY_START = date(2026, 5, 5)
SOURCE_DIR = ROOT / "outputs" / "five-lead-recap-source"
OUTPUT = ROOT / "outputs" / "three-sharp-kelly-ab-2026-08-02.json"

WALLETS: dict[str, dict[str, Any]] = {
    "Formal-Cupcake": {
        "address": "0xb8c842bc049bf208f73354c7b037b811d741d8a4",
        "unit": 1300.0,
        "minimum_units": 1.0,
        "copy_weight": 1.00,
    },
    "Soarin22": {
        "address": "0x84dbb7103982e3617704a2ed7d5b39691952aeeb",
        "unit": 7800.0,
        "minimum_units": 0.5,
        "copy_weight": 0.95,
    },
    "phonesculptor": {
        "address": "0xf1528f12e645462c344799b62b1b421a6a4c64aa",
        "unit": 29000.0,
        "minimum_units": 0.5,
        "copy_weight": 0.80,
    },
}


def supporter_bucket(play: dict[str, Any]) -> str:
    count = int(play["supporter_count"])
    if count <= 1:
        return "ONE"
    if count == 2:
        return "TWO"
    return "3_PLUS"


def calibrate_edges(
    plays: list[dict[str, Any]], *, prior_sample_size: float, maximum_edge: float
) -> dict[str, dict[str, float]]:
    residuals: dict[str, list[float]] = defaultdict(list)
    for play in plays:
        residual = float(bool(play["won"])) - float(play["entry_price_proxy"])
        residuals["ALL"].append(residual)
        residuals[supporter_bucket(play)].append(residual)
    result: dict[str, dict[str, float]] = {}
    for bucket, values in residuals.items():
        raw = sum(values) / len(values)
        shrunk = sum(values) / (len(values) + prior_sample_size)
        result[bucket] = {
            "plays": len(values),
            "raw_edge_points": raw,
            "shrunk_edge_points": max(-maximum_edge, min(maximum_edge, shrunk)),
        }
    return result


def reconstruct_plays() -> tuple[list[dict[str, Any]], dict[str, int], dict[str, Any]]:
    from scripts import simulate_lead_cohorts_main_markets as base
    from scripts import _tmp_five_wallet_recap as recap

    base.THROUGH_DATE = AS_OF.isoformat()
    base.SEASON_START = HISTORY_START.isoformat()
    base.SOURCE_DIR = SOURCE_DIR
    base.EVENTS_FILE = SOURCE_DIR / "event-catalog.json"
    base.WALLETS = WALLETS
    recap.WALLETS = WALLETS

    events = json.loads(base.EVENTS_FILE.read_text(encoding="utf-8"))
    main_markets = base.build_main_market_map(events)
    signal_map: dict[str, list[dict[str, Any]]] = {}
    audits: dict[str, Any] = {}
    for label, config in WALLETS.items():
        closed, current = base.load_source_rows(label)
        reconciled, reconciliation = base.reconcile_positions(closed, current)
        signals, signal_audit = base.build_wallet_signals(
            label, config, reconciled, main_markets
        )
        signal_map[label] = signals
        audits[label] = {**reconciliation, **signal_audit}
    plays, exclusions = recap.build_plays(signal_map)
    return plays, exclusions, audits


def add_walk_forward_kelly(
    plays: list[dict[str, Any]],
    *,
    prior_sample_size: float,
    maximum_edge: float,
    kelly_multiplier: float,
    kelly_unit_scale: float,
    maximum_stake_units: float,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    dates = sorted({str(play["date"]) for play in plays})
    prior: list[dict[str, Any]] = []
    for play_date in dates:
        day_rows = [play for play in plays if str(play["date"]) == play_date]
        calibration = calibrate_edges(
            prior,
            prior_sample_size=prior_sample_size,
            maximum_edge=maximum_edge,
        ) if prior else {}
        for play in day_rows:
            bucket = supporter_bucket(play)
            selected = calibration.get(bucket) or calibration.get("ALL")
            edge = float(selected["shrunk_edge_points"]) if selected else 0.0
            market_probability = float(play["entry_price_proxy"])
            fair_probability = max(0.01, min(0.99, market_probability + edge))
            full_kelly_fraction = max(
                0.0,
                (fair_probability - market_probability) / (1.0 - market_probability),
            )
            risk_fraction = min(
                maximum_stake_units / 100.0,
                kelly_multiplier * full_kelly_fraction * kelly_unit_scale,
            )
            row = dict(play)
            row.update(
                {
                    "supporter_bucket": bucket,
                    "calibration_sample": int(selected["plays"]) if selected else 0,
                    "estimated_edge_points": edge,
                    "estimated_fair_probability": fair_probability,
                    "full_kelly_fraction": full_kelly_fraction,
                    "dynamic_stake_units": risk_fraction * 100.0,
                }
            )
            enriched.append(row)
        # Settlement-time discipline: no same-day outcomes inform another play.
        prior.extend(day_rows)
    return enriched


def training_exposure_scale(
    plays: list[dict[str, Any]],
    *,
    training_end: date,
    prior_sample_size: float,
    maximum_edge: float,
    kelly_multiplier: float,
) -> dict[str, float]:
    training = [
        play for play in plays if str(play["date"]) <= training_end.isoformat()
    ]
    calibration = calibrate_edges(
        training,
        prior_sample_size=prior_sample_size,
        maximum_edge=maximum_edge,
    )
    raw_units: list[float] = []
    for play in training:
        selected = calibration.get(supporter_bucket(play)) or calibration["ALL"]
        edge = float(selected["shrunk_edge_points"])
        market_probability = float(play["entry_price_proxy"])
        fair_probability = max(0.01, min(0.99, market_probability + edge))
        full_kelly = max(
            0.0,
            (fair_probability - market_probability) / (1.0 - market_probability),
        )
        raw_units.append(kelly_multiplier * full_kelly * 100.0)
    target = sum(float(play["stake_units"]) for play in training) / len(training)
    raw = sum(raw_units) / len(raw_units)
    return {
        "training_plays": len(training),
        "target_average_flat_units": target,
        "raw_average_kelly_units": raw,
        "kelly_unit_scale": target / raw if raw else 0.0,
    }


def position_return(price: float, won: bool) -> float:
    return (1.0 - price) / price if won else -1.0


def max_drawdown(path: list[float]) -> float:
    peak = path[0]
    worst = 0.0
    for value in path:
        peak = max(peak, value)
        if peak:
            worst = max(worst, (peak - value) / peak)
    return worst


def replay(
    rows: list[dict[str, Any]], *, strategy: str, starting_bankroll: float
) -> dict[str, Any]:
    bankroll = starting_bankroll
    path = [bankroll]
    staked = 0.0
    funded = 0
    stakes: list[float] = []
    for row in rows:
        units = (
            float(row["stake_units"])
            if strategy == "flat"
            else float(row["dynamic_stake_units"])
        )
        stake = bankroll * units / 100.0
        staked += stake
        stakes.append(units)
        if stake > 0:
            funded += 1
        bankroll += stake * position_return(
            float(row["entry_price_proxy"]), bool(row["won"])
        )
        path.append(bankroll)
    profit = bankroll - starting_bankroll
    return {
        "eligible_plays": len(rows),
        "funded_bets": funded,
        "record": f"{sum(bool(r['won']) for r in rows)}-{sum(not bool(r['won']) for r in rows)}",
        "ending_bankroll": bankroll,
        "profit_dollars": profit,
        "return_on_bankroll": profit / starting_bankroll,
        "dollars_staked": staked,
        "betting_roi": profit / staked if staked else None,
        "average_stake_units_all_eligible": sum(stakes) / len(stakes) if stakes else 0.0,
        "average_stake_units_when_funded": (
            sum(v for v in stakes if v > 0) / funded if funded else 0.0
        ),
        "maximum_drawdown": max_drawdown(path),
        "bankroll_path": path,
    }


def summarize_distribution(values: np.ndarray) -> dict[str, float]:
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


def simulate_paired(
    rows: list[dict[str, Any]],
    *,
    days: int,
    paths: int,
    starting_bankroll: float,
    seed: int,
) -> dict[str, Any]:
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_day[str(row["date"])].append(row)
    day_blocks = [by_day[key] for key in sorted(by_day)]
    rng = np.random.default_rng(seed)
    finals = {
        "flat": np.zeros(paths),
        "dynamic_kelly": np.zeros(paths),
    }
    drawdowns = {
        "flat": np.zeros(paths),
        "dynamic_kelly": np.zeros(paths),
    }
    bet_counts = np.zeros(paths)
    percentile_paths: dict[str, list[list[float]]] = {
        "flat": [],
        "dynamic_kelly": [],
    }
    all_daily_paths: dict[str, list[list[float]]] = {
        "flat": [],
        "dynamic_kelly": [],
    }
    for path_index in range(paths):
        sampled = rng.integers(0, len(day_blocks), size=days)
        bankrolls = {"flat": starting_bankroll, "dynamic_kelly": starting_bankroll}
        peaks = dict(bankrolls)
        worst = {"flat": 0.0, "dynamic_kelly": 0.0}
        daily = {
            "flat": [starting_bankroll],
            "dynamic_kelly": [starting_bankroll],
        }
        for block_index in sampled:
            block = day_blocks[int(block_index)]
            bet_counts[path_index] += len(block)
            for row in block:
                ret = position_return(
                    float(row["entry_price_proxy"]), bool(row["won"])
                )
                for strategy, units_key in (
                    ("flat", "stake_units"),
                    ("dynamic_kelly", "dynamic_stake_units"),
                ):
                    units = float(row[units_key])
                    bankrolls[strategy] *= max(0.0, 1.0 + units / 100.0 * ret)
                    peaks[strategy] = max(peaks[strategy], bankrolls[strategy])
                    worst[strategy] = max(
                        worst[strategy],
                        (peaks[strategy] - bankrolls[strategy]) / peaks[strategy],
                    )
            for strategy in daily:
                daily[strategy].append(bankrolls[strategy])
        for strategy in finals:
            finals[strategy][path_index] = bankrolls[strategy]
            drawdowns[strategy][path_index] = worst[strategy]
            all_daily_paths[strategy].append(daily[strategy])

    result: dict[str, Any] = {"expected_bets": float(np.mean(bet_counts))}
    for strategy in finals:
        profits = finals[strategy] - starting_bankroll
        path_array = np.array(all_daily_paths[strategy])
        result[strategy] = {
            "profit_dollars": summarize_distribution(profits),
            "ending_bankroll": summarize_distribution(finals[strategy]),
            "probability_profitable": float(np.mean(profits > 0)),
            "maximum_drawdown": {
                "median": float(np.median(drawdowns[strategy])),
                "p90": float(np.quantile(drawdowns[strategy], 0.90)),
                "p95": float(np.quantile(drawdowns[strategy], 0.95)),
                "maximum_observed": float(np.max(drawdowns[strategy])),
            },
            "percentile_paths": {
                label: np.quantile(path_array, q, axis=0).tolist()
                for label, q in (
                    ("p05", 0.05),
                    ("p25", 0.25),
                    ("median", 0.50),
                    ("p75", 0.75),
                    ("p95", 0.95),
                )
            },
        }
    paired_delta = finals["dynamic_kelly"] - finals["flat"]
    result["dynamic_minus_flat"] = {
        "profit_delta_dollars": summarize_distribution(paired_delta),
        "probability_dynamic_finishes_ahead": float(np.mean(paired_delta > 0)),
    }
    return result


def run(args: argparse.Namespace) -> dict[str, Any]:
    plays, exclusions, audits = reconstruct_plays()
    evaluation_start = AS_OF - timedelta(days=59)
    exposure_calibration = training_exposure_scale(
        plays,
        training_end=evaluation_start - timedelta(days=1),
        prior_sample_size=args.prior_sample_size,
        maximum_edge=args.maximum_edge,
        kelly_multiplier=args.kelly_multiplier,
    )
    plays = add_walk_forward_kelly(
        plays,
        prior_sample_size=args.prior_sample_size,
        maximum_edge=args.maximum_edge,
        kelly_multiplier=args.kelly_multiplier,
        kelly_unit_scale=exposure_calibration["kelly_unit_scale"],
        maximum_stake_units=args.maximum_stake_units,
    )
    evaluation_rows = [
        play for play in plays if str(play["date"]) >= evaluation_start.isoformat()
    ]
    windows: dict[str, Any] = {}
    for days in (7, 30, 60):
        start = AS_OF - timedelta(days=days - 1)
        rows = [play for play in plays if str(play["date"]) >= start.isoformat()]
        windows[str(days)] = {
            "start": start.isoformat(),
            "end": AS_OF.isoformat(),
            "historical": {
                "flat": replay(rows, strategy="flat", starting_bankroll=args.starting_bankroll),
                "dynamic_kelly": replay(
                    rows,
                    strategy="dynamic_kelly",
                    starting_bankroll=args.starting_bankroll,
                ),
                "dynamic_edge": {
                    "average_estimated_edge_points": sum(
                        float(row["estimated_edge_points"]) for row in rows
                    ) / len(rows),
                    "positive_edge_plays": sum(
                        float(row["estimated_edge_points"]) > 0 for row in rows
                    ),
                    "zero_or_negative_edge_plays": sum(
                        float(row["estimated_edge_points"]) <= 0 for row in rows
                    ),
                    "capped_stakes": sum(
                        math.isclose(
                            float(row["dynamic_stake_units"]),
                            args.maximum_stake_units,
                            abs_tol=1e-12,
                        )
                        for row in rows
                    ),
                },
            },
            "simulation": simulate_paired(
                evaluation_rows,
                days=days,
                paths=args.paths,
                starting_bankroll=args.starting_bankroll,
                seed=args.seed + days,
            ),
        }
    return {
        "as_of": AS_OF.isoformat(),
        "scope": (
            "Formal-Cupcake, Soarin22, and phonesculptor; settled MLB full-game "
            "moneylines, main +/-1.5 run lines, and main full-game totals; "
            "qualified cross-wallet contradictions excluded."
        ),
        "starting_bankroll": args.starting_bankroll,
        "unit_dollars_at_start": args.starting_bankroll * 0.01,
        "simulations_per_horizon": args.paths,
        "data": {
            "history_start": HISTORY_START.isoformat(),
            "history_end": AS_OF.isoformat(),
            "eligible_plays": len(plays),
            "simulation_evaluation_start": evaluation_start.isoformat(),
            "simulation_evaluation_end": AS_OF.isoformat(),
            "simulation_evaluation_plays": len(evaluation_rows),
            "kelly_exposure_calibration": exposure_calibration,
            "cross_wallet_conflicts_excluded": exclusions.get(
                "cross_wallet_contradiction", 0
            ),
            "entry_price": (
                "Copy-weighted median wallet entry price proxy; not a reconstructed "
                "timestamp-perfect executable quote and no slippage is modeled."
            ),
            "wallet_audits": audits,
        },
        "arms": {
            "flat": (
                "Existing formula: 0.50 x mean(copy weights) x consensus multiplier; "
                "1u is 1% of current bankroll."
            ),
            "dynamic_kelly": (
                f"Walk-forward {args.kelly_multiplier:.2f}x Kelly. Fair probability "
                "equals entry implied probability plus a supporter-count edge calibrated "
                f"only on prior dates, shrunk by {args.prior_sample_size:.0f} equivalent "
                f"bets, capped at +/-{args.maximum_edge:.1%}. A fixed scale learned "
                "from the pre-test warm-up matches the flat arm's average exposure; "
                f"stake is capped at {args.maximum_stake_units:.2f}u with no positive "
                "minimum."
            ),
        },
        "simulation_method": (
            "Paired calendar-day bootstrap of the final 60 days after a 30-day "
            "calibration warm-up. Each arm receives the same sampled days, plays, "
            "outcomes, and entry-price proxies; bankroll and stakes compound."
        ),
        "windows": windows,
        "play_ledger": plays,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--paths", type=int, default=5_000)
    parser.add_argument("--starting-bankroll", type=float, default=10_000.0)
    parser.add_argument("--seed", type=int, default=20260803)
    parser.add_argument("--prior-sample-size", type=float, default=40.0)
    parser.add_argument("--maximum-edge", type=float, default=0.05)
    parser.add_argument("--kelly-multiplier", type=float, default=0.50)
    parser.add_argument("--maximum-stake-units", type=float, default=1.50)
    args = parser.parse_args()
    payload = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    for days, window in payload["windows"].items():
        flat = window["simulation"]["flat"]
        dynamic = window["simulation"]["dynamic_kelly"]
        print(
            days,
            "flat median",
            round(flat["profit_dollars"]["median"], 2),
            "dynamic median",
            round(dynamic["profit_dollars"]["median"], 2),
            "P(dynamic>flat)",
            round(
                window["simulation"]["dynamic_minus_flat"][
                    "probability_dynamic_finishes_ahead"
                ],
                4,
            ),
        )


if __name__ == "__main__":
    main()
