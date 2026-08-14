from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any

from simulate_corrected_mlb_weighted_model_5000 import (
    HORIZONS,
    WALLETS,
    build_play,
    conviction_multiplier,
    load_signals,
    simulation,
    summarize,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "old-vs-corrected-mlb-model-5000-2026-08-09.json"
OLD_WEIGHTS = {
    "Formal-Cupcake": 1.00,
    "Soarin22": 0.95,
    "phonesculptor": 0.80,
}


def build_old_play(signals: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str | None]:
    eligible = [
        row
        for row in signals
        if row["eligible"] and row["wallet"] in OLD_WEIGHTS
    ]
    if not eligible:
        return None, "no_old_lead"
    outcomes = {str(row["outcome"]) for row in eligible}
    if len(outcomes) != 1:
        return None, "old_lead_conflict"

    outcome = next(iter(outcomes))
    adjusted = [
        OLD_WEIGHTS[row["wallet"]] * conviction_multiplier(row["relative_units"])
        for row in eligible
    ]
    consensus = 1.0 + 0.15 * (len(eligible) - 1)
    stake = min(3.0, mean(adjusted) * consensus)
    price = median([row["price"] for row in eligible])
    won = bool(eligible[0]["won"])
    pnl = stake * ((1.0 - price) / price if won else -1.0)
    return {
        "condition_id": eligible[0]["condition_id"],
        "event_slug": eligible[0]["event_slug"],
        "date": eligible[0]["date"],
        "outcome": outcome,
        "price": price,
        "won": won,
        "stake_units": stake,
        "pnl_units": pnl,
        "primary_leads": [row["wallet"] for row in eligible],
    }, None


def construct_plays(signals: list[dict[str, Any]], builder: Any) -> tuple[list[dict[str, Any]], dict[str, int]]:
    by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for signal in signals:
        by_condition[signal["condition_id"]].append(signal)
    plays: list[dict[str, Any]] = []
    exclusions: dict[str, int] = defaultdict(int)
    for rows in by_condition.values():
        play, reason = builder(rows)
        if play:
            plays.append(play)
        elif reason:
            exclusions[reason] += 1
    return plays, dict(sorted(exclusions.items()))


def recent(plays: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    latest = max(date.fromisoformat(row["date"]) for row in plays)
    cutoff = latest - timedelta(days=days - 1)
    return [row for row in plays if date.fromisoformat(row["date"]) >= cutoff]


def arm(plays: list[dict[str, Any]], exclusions: dict[str, int], paths: int, seed: int) -> dict[str, Any]:
    season = recent(plays, 90)
    return {
        "historical_replay": summarize(plays),
        "recent_holdout_replays": {
            str(days): summarize(recent(plays, days)) for days in HORIZONS
        },
        "in_season_simulations": {
            str(days): simulation(
                season,
                days=days,
                paths=paths,
                seed=seed + days,
            )
            for days in HORIZONS
        },
        "exclusions": exclusions,
    }


def run(paths: int, seed: int) -> dict[str, Any]:
    signals = [
        signal
        for label, policy in WALLETS.items()
        for signal in load_signals(label, policy)
    ]
    old_plays, old_exclusions = construct_plays(signals, build_old_play)
    new_plays, new_exclusions = construct_plays(signals, build_play)
    return {
        "generated_on": date.today().isoformat(),
        "paths": paths,
        "comparison_basis": {
            "scope": "Corrected settled MLB full-game moneylines only",
            "sampling": "Same 90-day in-season calendar-day block bootstrap",
            "old_setup": "Formal-Cupcake, Soarin22, and phonesculptor may each originate alone; original 1.00/0.95/0.80 weights; direct lead disagreement veto; no supporting wallets.",
            "new_setup": "Formal-Cupcake and phonesculptor originate; Soarin22 is a 0.40 conditional input; four exact-market-netted confirmer wallets may strengthen, weaken, or veto.",
        },
        "old_setup": arm(old_plays, old_exclusions, paths, seed),
        "corrected_weighted_setup": arm(new_plays, new_exclusions, paths, seed),
        "limitations": [
            "This isolates moneyline architecture; the old production model also admitted main spreads and totals.",
            "Final settled wallet positions are used rather than timestamp-perfect two-hour snapshots.",
            "Wallet average entry is the price proxy; slippage and fees are excluded.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20260809)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    payload = run(args.paths, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    for name in ("old_setup", "corrected_weighted_setup"):
        print(name, json.dumps(payload[name], indent=2))


if __name__ == "__main__":
    main()
