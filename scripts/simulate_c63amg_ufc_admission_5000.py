from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SOURCE = ROOT / "outputs" / "c63amg-ufc-full-forensics.json"
OUTPUT = ROOT / "outputs" / "c63amg-ufc-admission-5000-2026-08-08.json"
PATHS = 5_000
HORIZONS = (7, 30, 60)


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def summarize(values: np.ndarray) -> dict[str, float]:
    return {
        "minimum": round(float(np.min(values)), 6),
        "p05": round(float(np.quantile(values, 0.05)), 6),
        "median": round(float(np.median(values)), 6),
        "mean": round(float(np.mean(values)), 6),
        "p95": round(float(np.quantile(values, 0.95)), 6),
        "maximum": round(float(np.max(values)), 6),
    }


def actual(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (row["date"], row["condition_id"]))
    equity = peak = drawdown = 0.0
    wins = 0
    for row in ordered:
        equity += number(row["flat_tail_return_units"])
        wins += int(bool(row["dominant_won"]))
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "bets": len(ordered),
        "wins": wins,
        "losses": len(ordered) - wins,
        "profit_units": round(equity, 6),
        "roi": round(equity / len(ordered), 6) if ordered else None,
        "max_drawdown_units": round(drawdown, 6),
        "first_date": ordered[0]["date"] if ordered else None,
        "last_date": ordered[-1]["date"] if ordered else None,
    }


def simulate(
    rows: list[dict[str, Any]],
    all_days: list[str],
    horizon: int,
    seed: int,
) -> dict[str, Any]:
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_day[row["date"]].append(row)
    blocks = [by_day[day] for day in all_days]
    rng = np.random.default_rng(seed)
    profits = np.zeros(PATHS)
    bets = np.zeros(PATHS)
    wins = np.zeros(PATHS)
    drawdowns = np.zeros(PATHS)
    for path in range(PATHS):
        equity = peak = 0.0
        for block_index in rng.integers(0, len(blocks), size=horizon):
            for row in blocks[int(block_index)]:
                result = number(row["flat_tail_return_units"])
                profits[path] += result
                bets[path] += 1
                wins[path] += int(bool(row["dominant_won"]))
                equity += result
                peak = max(peak, equity)
                drawdowns[path] = max(drawdowns[path], peak - equity)
    roi = np.divide(profits, bets, out=np.zeros_like(profits), where=bets > 0)
    return {
        "bets": summarize(bets),
        "wins": summarize(wins),
        "losses": summarize(bets - wins),
        "profit_units": summarize(profits),
        "roi": summarize(roi),
        "max_drawdown_units": summarize(drawdowns),
        "probability_profitable": round(float(np.mean(profits > 0)), 6),
        "probability_no_bets": round(float(np.mean(bets == 0)), 6),
    }


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    ledger = source["market_ledger"]
    first = min(date.fromisoformat(row["date"]) for row in ledger)
    last = max(date.fromisoformat(row["date"]) for row in ledger)
    all_days = [
        (first + timedelta(days=offset)).isoformat()
        for offset in range((last - first).days + 1)
    ]
    policies: dict[str, tuple[str, Callable[[dict[str, Any]], bool]]] = {
        "broad_clean_min_1u": (
            "Clean directional UFC market with at least one measured $625 wallet unit; flat 1u copy stake.",
            lambda row: row["status"] == "CLEAN_DIRECTIONAL"
            and number(row["measured_units"]) >= 1.0,
        ),
        "exploratory_clean_4_to_8u_entry_50c_plus": (
            "Exploratory filter: clean directional, 4.0-7.99 measured wallet units, entry at least 50c; flat 1u. This filter was selected after observing history and is not an unbiased forward result.",
            lambda row: row["status"] == "CLEAN_DIRECTIONAL"
            and 4.0 <= number(row["measured_units"]) < 8.0
            and number(row["dominant_average_entry"]) >= 0.50,
        ),
    }
    results: dict[str, Any] = {}
    for policy_index, (name, (description, predicate)) in enumerate(policies.items()):
        rows = [row for row in ledger if predicate(row)]
        results[name] = {
            "description": description,
            "actual_history": actual(rows),
            "simulations": {
                str(days): simulate(
                    rows,
                    all_days,
                    days,
                    seed=20260808 + policy_index * 1000 + days,
                )
                for days in HORIZONS
            },
        }
    report = {
        "title": "C63AMG UFC production-admission simulation",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "paths_per_policy_horizon": PATHS,
        "horizons_days": list(HORIZONS),
        "historical_window": {"start": first.isoformat(), "end": last.isoformat()},
        "sampling": "Calendar-day block bootstrap with replacement, including inactive days and preserving same-day fight clustering.",
        "sizing": "Flat 1u per qualified dominant-direction signal.",
        "entry_proxy": "Wallet dominant average entry; executable copy slippage is unavailable and therefore not deducted.",
        "important": "Historical bootstrap, not a guarantee. The exploratory filter is explicitly post-selected and must not be promoted without a clean forward sample.",
        "policies": results,
        "recommendation": "Do not add C63AMG as an official UFC sharp now. Broad clean 1u copying is historically negative; retain the 4-8u/50c+ rule only as a shadow hypothesis for forward validation.",
    }
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
