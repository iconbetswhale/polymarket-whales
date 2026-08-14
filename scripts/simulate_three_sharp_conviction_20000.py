from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_three_sharp_kelly_ab import AS_OF, WALLETS, reconstruct_plays
from three_sharp_strategy import (
    CONVICTION_TIERS,
    STRATEGY_ID,
    conviction_multiplier,
    recommendation_units,
)


OUTPUT = ROOT / "outputs" / "three-sharp-conviction-20000-2026-08-03.json"
SIMULATION_START = AS_OF - timedelta(days=59)
HORIZONS = (7, 30, 60)


def number_summary(values: np.ndarray) -> dict[str, float]:
    return {
        "minimum_observed": float(np.min(values)),
        "p01": float(np.quantile(values, 0.01)),
        "p05": float(np.quantile(values, 0.05)),
        "p25": float(np.quantile(values, 0.25)),
        "median": float(np.median(values)),
        "mean": float(np.mean(values)),
        "p75": float(np.quantile(values, 0.75)),
        "p95": float(np.quantile(values, 0.95)),
        "p99": float(np.quantile(values, 0.99)),
        "maximum_observed": float(np.max(values)),
    }


def add_conviction_sizing(plays: list[dict[str, Any]]) -> list[dict[str, Any]]:
    label_to_address = {
        label: str(config["address"]).lower() for label, config in WALLETS.items()
    }
    enriched: list[dict[str, Any]] = []
    for play in plays:
        addresses = [label_to_address[label] for label in play["supporters"]]
        relative_units = {
            label_to_address[label]: float(
                (play.get("supporter_relative_units") or {}).get(label) or 1.0
            )
            for label in play["supporters"]
        }
        sizing = recommendation_units(addresses, relative_units)
        row = dict(play)
        row["conviction_stake_units"] = float(sizing["units"])
        row["conviction_multipliers"] = sizing["conviction_multipliers"]
        row["relative_units_by_wallet"] = sizing["relative_units_by_wallet"]
        row["return_per_dollar"] = (
            (1.0 - float(row["entry_price_proxy"]))
            / float(row["entry_price_proxy"])
            if bool(row["won"])
            else -1.0
        )
        enriched.append(row)
    return enriched


def replay(rows: list[dict[str, Any]], starting_bankroll: float) -> dict[str, Any]:
    bankroll = starting_bankroll
    peak = bankroll
    trough = bankroll
    maximum_drawdown = 0.0
    maximum_profit = 0.0
    dollars_staked = 0.0
    for row in rows:
        units = float(row["conviction_stake_units"])
        stake = bankroll * units / 100.0
        dollars_staked += stake
        bankroll *= max(0.0, 1.0 + units / 100.0 * float(row["return_per_dollar"]))
        peak = max(peak, bankroll)
        trough = min(trough, bankroll)
        maximum_profit = max(maximum_profit, bankroll - starting_bankroll)
        maximum_drawdown = max(maximum_drawdown, (peak - bankroll) / peak)
    profit = bankroll - starting_bankroll
    wins = sum(bool(row["won"]) for row in rows)
    stakes = [float(row["conviction_stake_units"]) for row in rows]
    return {
        "bets": len(rows),
        "record": f"{wins}-{len(rows) - wins}",
        "win_rate": wins / len(rows) if rows else None,
        "average_stake_units": float(np.mean(stakes)) if stakes else None,
        "median_stake_units": float(np.median(stakes)) if stakes else None,
        "ending_bankroll": bankroll,
        "profit_dollars": profit,
        "profit_units_on_initial_bankroll": profit / (starting_bankroll / 100.0),
        "return_on_bankroll": profit / starting_bankroll,
        "dollars_staked": dollars_staked,
        "betting_roi": profit / dollars_staked if dollars_staked else None,
        "maximum_drawdown_fraction": maximum_drawdown,
        "maximum_drawdown_units": maximum_drawdown * 100.0,
        "maximum_profit_dollars": maximum_profit,
        "minimum_bankroll": trough,
    }


def simulate(
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
    # Include zero-bet dates. Sampling active dates only would materially inflate
    # projected volume and returns while claiming to be a calendar-day bootstrap.
    blocks = [
        by_day[(SIMULATION_START + timedelta(days=offset)).isoformat()]
        for offset in range((AS_OF - SIMULATION_START).days + 1)
    ]
    if not blocks:
        raise ValueError("No historical day blocks available")

    rng = np.random.default_rng(seed)
    ending = np.empty(paths)
    profit = np.empty(paths)
    drawdown = np.empty(paths)
    max_profit = np.empty(paths)
    bet_counts = np.empty(paths)
    daily_paths = np.empty((paths, days + 1))

    for path_index in range(paths):
        sampled = rng.integers(0, len(blocks), size=days)
        bankroll = starting_bankroll
        peak = bankroll
        worst_drawdown = 0.0
        best_profit = 0.0
        bets = 0
        daily_paths[path_index, 0] = bankroll
        for day_index, block_index in enumerate(sampled, start=1):
            block = blocks[int(block_index)]
            bets += len(block)
            for row in block:
                units = float(row["conviction_stake_units"])
                bankroll *= max(
                    0.0,
                    1.0 + units / 100.0 * float(row["return_per_dollar"]),
                )
                peak = max(peak, bankroll)
                best_profit = max(best_profit, bankroll - starting_bankroll)
                worst_drawdown = max(worst_drawdown, (peak - bankroll) / peak)
            daily_paths[path_index, day_index] = bankroll
        ending[path_index] = bankroll
        profit[path_index] = bankroll - starting_bankroll
        drawdown[path_index] = worst_drawdown
        max_profit[path_index] = best_profit
        bet_counts[path_index] = bets

    profit_units = profit / (starting_bankroll / 100.0)
    return {
        "expected_bets": float(np.mean(bet_counts)),
        "bets": number_summary(bet_counts),
        "ending_bankroll": number_summary(ending),
        "profit_dollars": number_summary(profit),
        "profit_units_on_initial_bankroll": number_summary(profit_units),
        "probability_profitable": float(np.mean(profit > 0.0)),
        "probability_loss_10_percent": float(
            np.mean(ending <= starting_bankroll * 0.90)
        ),
        "probability_loss_20_percent": float(
            np.mean(ending <= starting_bankroll * 0.80)
        ),
        "maximum_drawdown_fraction": number_summary(drawdown),
        "maximum_drawdown_units": number_summary(drawdown * 100.0),
        "maximum_profit_dollars": number_summary(max_profit),
        "maximum_profit_units": number_summary(
            max_profit / (starting_bankroll / 100.0)
        ),
        "percentile_paths": {
            label: np.quantile(daily_paths, quantile, axis=0).tolist()
            for label, quantile in (
                ("p05", 0.05),
                ("p25", 0.25),
                ("median", 0.50),
                ("p75", 0.75),
                ("p95", 0.95),
            )
        },
    }


def build_payload(paths: int, starting_bankroll: float, seed: int) -> dict[str, Any]:
    plays, exclusions, source_audit = reconstruct_plays()
    plays = add_conviction_sizing(plays)
    evaluation_rows = [
        row for row in plays if str(row["date"]) >= SIMULATION_START.isoformat()
    ]
    tier_counts: Counter[str] = Counter()
    for row in evaluation_rows:
        for multiplier in row["conviction_multipliers"].values():
            tier_counts[f"{float(multiplier):.2f}x"] += 1

    windows: dict[str, Any] = {}
    for days in HORIZONS:
        observed_start = AS_OF - timedelta(days=days - 1)
        observed = [
            row for row in plays if str(row["date"]) >= observed_start.isoformat()
        ]
        windows[str(days)] = {
            "observed_start": observed_start.isoformat(),
            "observed_end": AS_OF.isoformat(),
            "historical_replay": replay(observed, starting_bankroll),
            "simulation": simulate(
                evaluation_rows,
                days=days,
                paths=paths,
                starting_bankroll=starting_bankroll,
                seed=seed + days,
            ),
        }

    payload = {
        "title": "Three-sharp conviction-weighted model — 20,000-path simulation",
        "as_of": AS_OF.isoformat(),
        "generated_on": date.today().isoformat(),
        "strategy_id": STRATEGY_ID,
        "starting_bankroll": starting_bankroll,
        "one_unit_initial_dollars": starting_bankroll / 100.0,
        "simulations_per_horizon": paths,
        "seed": seed,
        "wallets": WALLETS,
        "conviction_tiers": [
            {"minimum_wallet_units": minimum, "multiplier": multiplier}
            for minimum, multiplier in CONVICTION_TIERS
        ],
        "scope": (
            "Settled MLB full-game moneylines, main +/-1.5 run lines, and the "
            "highest-volume full-game total for Formal-Cupcake, Soarin22, and "
            "phonesculptor; any qualifying cross-wallet contradiction is vetoed."
        ),
        "simulation_method": (
            "Seeded calendar-day block bootstrap from the final 60 calendar days "
            "of the common historical sample. Sampling preserves observed same-day "
            "bet volume and correlation; the bankroll compounds after each bet."
        ),
        "entry_price_limitation": (
            "Historical entry is a copy-weighted median wallet entry proxy, not a "
            "timestamp-perfect executable sportsbook quote; slippage is excluded."
        ),
        "source_play_count": len(evaluation_rows),
        "source_date_range": {
            "start": SIMULATION_START.isoformat(),
            "end": AS_OF.isoformat(),
        },
        "exclusions": exclusions,
        "source_audit": source_audit,
        "data_quality": {
            "relative_unit_coverage": float(
                np.mean(
                    [
                        bool(row.get("relative_units_by_wallet"))
                        for row in evaluation_rows
                    ]
                )
            ),
            "conviction_tier_observations": dict(sorted(tier_counts.items())),
            "stake_units": number_summary(
                np.asarray(
                    [row["conviction_stake_units"] for row in evaluation_rows],
                    dtype=float,
                )
            ),
            "capped_at_3u_count": sum(
                float(row["conviction_stake_units"]) >= 3.0
                for row in evaluation_rows
            ),
        },
        "windows": windows,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["reproducibility_sha256"] = hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", type=int, default=20_000)
    parser.add_argument("--starting-bankroll", type=float, default=10_000.0)
    parser.add_argument("--seed", type=int, default=20260803)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    payload = build_payload(args.paths, args.starting_bankroll, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    for days in map(str, HORIZONS):
        simulation = payload["windows"][days]["simulation"]
        print(
            days,
            "days",
            "median_profit_units=",
            round(simulation["profit_units_on_initial_bankroll"]["median"], 3),
            "p05=",
            round(simulation["profit_units_on_initial_bankroll"]["p05"], 3),
            "p95=",
            round(simulation["profit_units_on_initial_bankroll"]["p95"], 3),
            "profitable=",
            round(simulation["probability_profitable"] * 100, 2),
            "%",
        )


if __name__ == "__main__":
    main()
