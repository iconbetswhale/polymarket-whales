"""Simulate fixed monthly bet counts for the four-lead wallet cohort."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "outputs" / "lead-cohort-30-day-simulation-2026-07-28.json"
OUTPUT = ROOT / "outputs" / "lead-cohort-report" / "four-lead-fixed-bet-counts.json"
STARTING_BANKROLL = 10_000.0
SIMULATIONS = 5_000
HORIZON_DAYS = 30
BET_COUNTS = (60, 90, 120)
SEED = 20260729
STARTING_UNIT_DOLLARS = STARTING_BANKROLL * 0.01


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def simulate(plays: list[dict], monthly_bets: int, seed: int) -> dict:
    rng = random.Random(seed)
    bets_per_day = monthly_bets // HORIZON_DAYS
    remainder = monthly_bets % HORIZON_DAYS
    paths: list[list[float]] = []
    max_drawdowns_units: list[float] = []
    max_updraws_units: list[float] = []

    for _ in range(SIMULATIONS):
        bankroll = STARTING_BANKROLL
        path = [bankroll]
        bet_path = [bankroll]
        extra_days = set(rng.sample(range(HORIZON_DAYS), remainder))
        for day in range(HORIZON_DAYS):
            day_count = bets_per_day + (1 if day in extra_days else 0)
            for _bet in range(day_count):
                play = rng.choice(plays)
                stake = bankroll * float(play["stake_units"]) / 100
                bankroll += stake * float(play["return_per_dollar"])
                bet_path.append(bankroll)
            path.append(bankroll)
        paths.append(path)

        running_peak = bet_path[0]
        running_trough = bet_path[0]
        max_drawdown = 0.0
        max_updraw = 0.0
        for value in bet_path:
            running_peak = max(running_peak, value)
            max_drawdown = max(max_drawdown, running_peak - value)
            running_trough = min(running_trough, value)
            max_updraw = max(max_updraw, value - running_trough)
        max_drawdowns_units.append(max_drawdown / STARTING_UNIT_DOLLARS)
        max_updraws_units.append(max_updraw / STARTING_UNIT_DOLLARS)

    daily = {"p05": [], "p25": [], "p50": [], "p75": [], "p95": []}
    for day in range(HORIZON_DAYS + 1):
        values = [path[day] for path in paths]
        for label, q in (
            ("p05", 0.05),
            ("p25", 0.25),
            ("p50", 0.50),
            ("p75", 0.75),
            ("p95", 0.95),
        ):
            daily[label].append(percentile(values, q))

    endings = [path[-1] for path in paths]
    return {
        "monthly_bets": monthly_bets,
        "average_bets_per_day": monthly_bets / HORIZON_DAYS,
        "simulations": SIMULATIONS,
        "starting_bankroll": STARTING_BANKROLL,
        "probability_profitable": sum(value > STARTING_BANKROLL for value in endings)
        / SIMULATIONS,
        "ending_bankroll": {
            "p05": percentile(endings, 0.05),
            "p25": percentile(endings, 0.25),
            "p50": percentile(endings, 0.50),
            "p75": percentile(endings, 0.75),
            "p95": percentile(endings, 0.95),
        },
        "median_profit": percentile(endings, 0.50) - STARTING_BANKROLL,
        "median_roi": percentile(endings, 0.50) / STARTING_BANKROLL - 1,
        "unit_definition": {
            "one_unit_starting_bankroll_percent": 1.0,
            "one_unit_dollars": STARTING_UNIT_DOLLARS,
        },
        "path_excursions_units": {
            "max_drawdown": {
                "minimum": min(max_drawdowns_units),
                "p05": percentile(max_drawdowns_units, 0.05),
                "median": percentile(max_drawdowns_units, 0.50),
                "p95": percentile(max_drawdowns_units, 0.95),
                "maximum": max(max_drawdowns_units),
            },
            "max_updraw": {
                "minimum": min(max_updraws_units),
                "p05": percentile(max_updraws_units, 0.05),
                "median": percentile(max_updraws_units, 0.50),
                "p95": percentile(max_updraws_units, 0.95),
                "maximum": max(max_updraws_units),
            },
        },
        "daily_bankroll_percentiles": daily,
    }


def main() -> None:
    payload = json.loads(INPUT.read_text(encoding="utf-8"))
    plays = payload["cohorts"]["FOUR_LEADS"]["play_ledger"]
    results = {
        "generated_on": "2026-07-28",
        "cohort": payload["cohorts"]["FOUR_LEADS"]["wallets"],
        "cohort_rule": payload["methodology"]["cohort_rule"],
        "important_limit": payload["methodology"]["important_limit"],
        "scenarios": {
            str(count): simulate(plays, count, SEED + index)
            for index, count in enumerate(BET_COUNTS)
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in results["scenarios"].items()}, indent=2))


if __name__ == "__main__":
    main()
