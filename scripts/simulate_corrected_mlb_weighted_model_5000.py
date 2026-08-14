from __future__ import annotations

import argparse
import json
import math
import random
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.wallet_full_extraction import aggregate_closed, number


SOURCE = ROOT / "outputs" / "cross-sport-source"
OUTPUT = ROOT / "outputs" / "corrected-mlb-weighted-model-5000-2026-08-09.json"
DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")
HORIZONS = (30, 60, 90)

WALLETS: dict[str, dict[str, Any]] = {
    "Formal-Cupcake": {"file": "formal-cupcake", "unit": 1300.0, "minimum": 1.0, "weight": 1.0, "role": "PRIMARY"},
    "phonesculptor": {"file": "phonesculptor", "unit": 29000.0, "minimum": 0.5, "weight": 0.85, "role": "PRIMARY"},
    "Soarin22": {"file": "soarin22", "unit": 7800.0, "minimum": 0.5, "weight": 0.40, "role": "CONDITIONAL"},
    "sportmaster777": {"file": "sportmaster777", "unit": 6000.0, "minimum": 0.25, "weight": 0.25, "role": "CONFIRMER"},
    "1winstreak1": {"file": "1winstreak1", "unit": 3000.0, "minimum": 1.0, "weight": 0.25, "role": "CONFIRMER"},
    "0x4f2": {"file": "0x4f2", "unit": 8000.0, "minimum": 0.20, "weight": 0.15, "role": "CONFIRMER"},
    "ferrariChampions2026": {"file": "ferrarichampions2026", "unit": 17000.0, "minimum": 0.20, "weight": 0.10, "role": "CONFIRMER"},
}


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = (len(ordered) - 1) * q
    low = math.floor(index)
    high = math.ceil(index)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def settled_current(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        current_price = number(row.get("curPrice"))
        if not (row.get("redeemable") or current_price <= 0.001 or current_price >= 0.999):
            continue
        normalized = dict(row)
        normalized["realizedPnl"] = number(row.get("cashPnl")) + number(row.get("realizedPnl"))
        result.append(normalized)
    return result


def event_date(value: Any) -> str | None:
    match = DATE_RE.search(str(value or ""))
    return match.group(1) if match else None


def conviction_multiplier(units: float) -> float:
    if units >= 10.0:
        return 1.55
    if units >= 5.0:
        return 1.40
    if units >= 2.5:
        return 1.25
    if units >= 1.5:
        return 1.10
    return 1.0


def load_signals(label: str, policy: dict[str, Any]) -> list[dict[str, Any]]:
    stem = str(policy["file"])
    closed = json.loads((SOURCE / f"{stem}-closed.json").read_text(encoding="utf-8"))
    current_path = SOURCE / f"{stem}-current.json"
    current = json.loads(current_path.read_text(encoding="utf-8")) if current_path.exists() else []
    markets = aggregate_closed([*closed, *settled_current(current)])
    signals: list[dict[str, Any]] = []
    for market in markets:
        event_slug = str(market.get("event_slug") or "").lower()
        slug = str(market.get("slug") or "").lower()
        day = event_date(event_slug)
        if not day or not event_slug.startswith("mlb-") or slug != event_slug:
            continue
        relative_units = number(market.get("net_directional_cost_usd")) / float(policy["unit"])
        eligible = (
            market.get("direction_status") == "CLEAN_DIRECTIONAL"
            and relative_units + 0.01 >= float(policy["minimum"])
            and 0.0 < number(market.get("entry_price")) < 1.0
        )
        signals.append(
            {
                "condition_id": str(market["condition_id"]),
                "event_slug": event_slug,
                "date": day,
                "wallet": label,
                "role": policy["role"],
                "weight": float(policy["weight"]),
                "outcome": str(market.get("leader") or ""),
                "price": number(market.get("entry_price")),
                "won": number(market.get("flat_copy_profit_units")) > 0.0,
                "relative_units": relative_units,
                "eligible": eligible,
            }
        )
    return signals


def build_play(signals: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str | None]:
    eligible = [row for row in signals if row["eligible"]]
    primary = [row for row in eligible if row["role"] == "PRIMARY"]
    if not primary:
        return None, "no_primary_lead"
    primary_outcomes = {str(row["outcome"]) for row in primary}
    if len(primary_outcomes) != 1:
        return None, "primary_lead_conflict"
    outcome = next(iter(primary_outcomes))
    conditional = [row for row in eligible if row["role"] == "CONDITIONAL"]
    confirmers = [row for row in eligible if row["role"] == "CONFIRMER"]
    agreeing_conditional = [row for row in conditional if row["outcome"] == outcome]
    opposing_conditional = [row for row in conditional if row["outcome"] != outcome]
    if any(row["relative_units"] >= 1.0 for row in opposing_conditional):
        return None, "substantial_soarin_conflict"
    agreeing_confirmers = [row for row in confirmers if row["outcome"] == outcome]
    opposing_confirmers = [row for row in confirmers if row["outcome"] != outcome]
    confirm_weight = sum(row["weight"] * min(2.0, math.sqrt(row["relative_units"])) for row in agreeing_confirmers)
    oppose_weight = sum(row["weight"] * min(2.0, math.sqrt(row["relative_units"])) for row in opposing_confirmers)
    if oppose_weight > confirm_weight + 0.50:
        return None, "confirmer_conflict"

    adjusted_primary = [
        row["weight"] * conviction_multiplier(row["relative_units"])
        for row in primary
    ]
    consensus = 1.0
    if len(primary) == 2:
        consensus += 0.25
    if agreeing_conditional:
        consensus += 0.15
    if opposing_conditional:
        consensus -= 0.15
    consensus *= max(0.50, 1.0 + 0.12 * confirm_weight - 0.15 * oppose_weight)
    stake = min(3.0, max(0.25, mean(adjusted_primary) * consensus))
    price = median([row["price"] for row in primary])
    won = bool(primary[0]["won"])
    pnl = stake * ((1.0 - price) / price if won else -1.0)
    return {
        "condition_id": primary[0]["condition_id"],
        "event_slug": primary[0]["event_slug"],
        "date": primary[0]["date"],
        "outcome": outcome,
        "price": price,
        "won": won,
        "stake_units": stake,
        "pnl_units": pnl,
        "primary_leads": [row["wallet"] for row in primary],
        "conditional_agree": [row["wallet"] for row in agreeing_conditional],
        "conditional_oppose": [row["wallet"] for row in opposing_conditional],
        "confirmers_agree": [row["wallet"] for row in agreeing_confirmers],
        "confirmers_oppose": [row["wallet"] for row in opposing_confirmers],
    }, None


def max_drawdown(rows: list[dict[str, Any]]) -> float:
    equity = peak = drawdown = 0.0
    for row in rows:
        equity += float(row["pnl_units"])
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (row["date"], row["condition_id"]))
    wins = sum(bool(row["won"]) for row in ordered)
    stake = sum(float(row["stake_units"]) for row in ordered)
    profit = sum(float(row["pnl_units"]) for row in ordered)
    days = sorted({row["date"] for row in ordered})
    calendar_days = (date.fromisoformat(days[-1]) - date.fromisoformat(days[0])).days + 1 if days else 0
    return {
        "bets": len(ordered),
        "record": f"{wins}-{len(ordered) - wins}",
        "win_rate": wins / len(ordered) if ordered else None,
        "staked_units": stake,
        "profit_units": profit,
        "betting_roi": profit / stake if stake else None,
        "maximum_drawdown_units": max_drawdown(ordered),
        "average_stake_units": stake / len(ordered) if ordered else None,
        "calendar_days": calendar_days,
        "plays_per_calendar_day": len(ordered) / calendar_days if calendar_days else None,
    }


def price_stress(rows: list[dict[str, Any]], points: float) -> list[dict[str, Any]]:
    stressed: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        price = min(0.99, float(row["price"]) + points)
        item["price"] = price
        item["pnl_units"] = float(row["stake_units"]) * (
            (1.0 - price) / price if row["won"] else -1.0
        )
        stressed.append(item)
    return stressed


def simulation(plays: list[dict[str, Any]], *, days: int, paths: int, seed: int) -> dict[str, Any]:
    start = min(date.fromisoformat(row["date"]) for row in plays)
    end = max(date.fromisoformat(row["date"]) for row in plays)
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in plays:
        by_day[row["date"]].append(row)
    blocks = [by_day[(start + timedelta(days=offset)).isoformat()] for offset in range((end - start).days + 1)]
    rng = random.Random(seed)
    finals: list[float] = []
    rois: list[float] = []
    drawdowns: list[float] = []
    bets: list[float] = []
    wins: list[float] = []
    for _ in range(paths):
        path_rows: list[dict[str, Any]] = []
        for _day in range(days):
            path_rows.extend(blocks[rng.randrange(len(blocks))])
        summary = summarize(path_rows)
        finals.append(float(summary["profit_units"]))
        rois.append(float(summary["betting_roi"] or 0.0))
        drawdowns.append(float(summary["maximum_drawdown_units"]))
        bets.append(float(summary["bets"]))
        wins.append(float(str(summary["record"]).split("-", 1)[0]))
    return {
        "paths": paths,
        "horizon_days": days,
        "median_record": f"{round(percentile(wins, 0.50))}-{round(percentile(bets, 0.50) - percentile(wins, 0.50))}",
        "plays": {"p05": percentile(bets, 0.05), "median": percentile(bets, 0.50), "p95": percentile(bets, 0.95)},
        "plays_per_day_median": percentile(bets, 0.50) / days,
        "profit_units": {"worst": min(finals), "p05": percentile(finals, 0.05), "median": percentile(finals, 0.50), "p95": percentile(finals, 0.95), "best": max(finals)},
        "betting_roi": {"p05": percentile(rois, 0.05), "median": percentile(rois, 0.50), "p95": percentile(rois, 0.95)},
        "maximum_drawdown_units": {"median": percentile(drawdowns, 0.50), "p95": percentile(drawdowns, 0.95), "worst": max(drawdowns)},
        "probability_profitable": sum(value > 0 for value in finals) / paths,
    }


def run(paths: int, seed: int) -> dict[str, Any]:
    all_signals = [signal for label, policy in WALLETS.items() for signal in load_signals(label, policy)]
    by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for signal in all_signals:
        by_condition[signal["condition_id"]].append(signal)
    plays: list[dict[str, Any]] = []
    exclusions: dict[str, int] = defaultdict(int)
    for signals in by_condition.values():
        play, reason = build_play(signals)
        if play:
            plays.append(play)
        elif reason:
            exclusions[reason] += 1
    latest = max(date.fromisoformat(row["date"]) for row in plays)
    holdouts = {
        str(days): summarize(
            [
                row
                for row in plays
                if date.fromisoformat(row["date"]) >= latest - timedelta(days=days - 1)
            ]
        )
        for days in (30, 60, 90)
    }
    one_point = price_stress(plays, 0.01)
    two_points = price_stress(plays, 0.02)
    recent_season = [
        row
        for row in plays
        if date.fromisoformat(row["date"]) >= latest - timedelta(days=89)
    ]
    return {
        "generated_on": date.today().isoformat(),
        "paths": paths,
        "wallet_roles": WALLETS,
        "historical_replay": summarize(plays),
        "recent_holdout_replays": holdouts,
        "simulations": {str(days): simulation(plays, days=days, paths=paths, seed=seed + days) for days in HORIZONS},
        "in_season_simulations": {
            str(days): simulation(
                recent_season,
                days=days,
                paths=paths,
                seed=seed + 200 + days,
            )
            for days in HORIZONS
        },
        "price_stress": {
            "one_probability_point_worse": {
                "historical_replay": summarize(one_point),
                "thirty_day_simulation": simulation(one_point, days=30, paths=paths, seed=seed + 101),
            },
            "two_probability_points_worse": {
                "historical_replay": summarize(two_points),
                "thirty_day_simulation": simulation(two_points, days=30, paths=paths, seed=seed + 102),
            },
        },
        "source_date_range": {"start": min(row["date"] for row in plays), "end": max(row["date"] for row in plays)},
        "exclusions": dict(sorted(exclusions.items())),
        "methodology": {
            "scope": "Corrected settled MLB full-game moneylines",
            "selection": "Formal-Cupcake or phonesculptor must originate; direct disagreement vetoes. Soarin is a reduced-weight conditional input. Automated wallets are exact-moneyline-netted confirmers.",
            "simulation": "Seeded calendar-day block bootstrap including zero-play days",
            "critical_limitations": [
                "Final settled wallet positions are used, not positions reconstructed exactly two hours before game time.",
                "Wallet average entry is the price proxy; executable line-shopping slippage and fees are not included.",
                "Portfolio confirmers are netted inside the exact moneyline market; cross-market spread and total exposure cannot be translated reliably into moneyline-equivalent dollars from settlement rows alone.",
                "Bootstrap results measure historical-pattern uncertainty and do not guarantee future profitability.",
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
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    print(json.dumps({"historical_replay": payload["historical_replay"], "simulations": payload["simulations"]}, indent=2))


if __name__ == "__main__":
    main()
