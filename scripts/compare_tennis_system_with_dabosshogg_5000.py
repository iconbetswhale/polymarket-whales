from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from polymarket_client import PolymarketClient
from scripts.simulate_two_tennis_sharps_5000 import (
    number,
    parse_time,
    strictly_resolved_market,
)


SOURCE = ROOT / "outputs" / "bagwell-lilybaeum-tennis-5000-comparison-2026-08-08.json"
TRADE_CACHE = ROOT / "outputs" / "dabosshogg-full-trades-2026-08-10.json"
EVENT_CACHE = ROOT / "outputs" / "dabosshogg-tennis-events-2026-08-10.json"
OUTPUT = ROOT / "analysis" / "outputs" / "current-vs-dabosshogg-tennis-5000-2026-08-10.json"
ADDRESS = "0x6157d529ae129fe08f22a27ed42e741d2eaa9fb4"
START = date(2026, 6, 22)
END = date(2026, 8, 4)
CHECKPOINT_SECONDS = 30 * 60
UNIT_USD = 5050.0
HORIZONS = (7, 30, 60)


def is_tennis(row: dict[str, Any]) -> bool:
    slug = str(row.get("eventSlug") or row.get("slug") or "").lower()
    return slug.startswith(("atp-", "wta-", "itf-", "utr-", "challenger-", "tennis-"))


def load_daboss_trades() -> list[dict[str, Any]]:
    if TRADE_CACHE.exists():
        return json.loads(TRADE_CACHE.read_text(encoding="utf-8"))
    rows = PolymarketClient(request_timeout=20, max_retries=5).get_user_trades(ADDRESS)
    TRADE_CACHE.write_text(json.dumps(rows), encoding="utf-8")
    return rows


def load_metadata(event_slugs: list[str]) -> dict[str, dict[str, Any]]:
    cached: dict[str, dict[str, Any] | None] = {}
    if EVENT_CACHE.exists():
        cached = json.loads(EVENT_CACHE.read_text(encoding="utf-8"))
    missing = [slug for slug in sorted(set(event_slugs)) if slug and slug not in cached]
    if missing:
        cached.update(PolymarketClient(request_timeout=20, max_retries=5).get_events(missing, max_workers=6))
        EVENT_CACHE.write_text(json.dumps(cached), encoding="utf-8")
    selected: dict[str, dict[str, Any]] = {}
    for event in cached.values():
        if not isinstance(event, dict):
            continue
        for row in event.get("markets") or []:
            if not isinstance(row, dict):
                continue
            market = strictly_resolved_market(row)
            if market:
                selected[market["condition_id"]] = market
    return selected


def load_daboss_plays() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = load_daboss_trades()
    tennis = [row for row in rows if isinstance(row, dict) and is_tennis(row)]
    metadata = load_metadata([str(row.get("eventSlug") or "") for row in tennis])
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in tennis:
        grouped[str(row.get("conditionId") or "").lower()].append(row)
    exclusions: dict[str, int] = defaultdict(int)
    plays: list[dict[str, Any]] = []
    for condition, fills in grouped.items():
        market = metadata.get(condition)
        if not market:
            exclusions["missing_resolved_main_market_metadata"] += 1
            continue
        checkpoint = int(market["start"]) - CHECKPOINT_SECONDS
        eligible = sorted(
            (row for row in fills if int(row.get("timestamp") or 0) <= checkpoint),
            key=lambda row: int(row.get("timestamp") or 0),
        )
        if not eligible:
            exclusions["no_position_30m_prestart"] += 1
            continue
        costs: dict[str, float] = defaultdict(float)
        last_price: dict[str, float] = {}
        for row in eligible:
            outcome = str(row.get("outcome") or "")
            price = number(row.get("price"))
            shares = number(row.get("size"))
            sign = -1.0 if str(row.get("side") or "BUY").upper() == "SELL" else 1.0
            costs[outcome] += sign * shares * price
            last_price[outcome] = price
        positive = {outcome: cost for outcome, cost in costs.items() if cost > 0}
        if not positive:
            exclusions["no_positive_direction"] += 1
            continue
        leader = max(positive, key=positive.get)
        leader_cost = positive[leader]
        opposing_cost = sum(cost for outcome, cost in positive.items() if outcome != leader)
        opposing_ratio = opposing_cost / leader_cost if leader_cost else 1.0
        net_cost = max(0.0, leader_cost - opposing_cost)
        entry_price = last_price.get(leader, 0.0)
        if opposing_ratio >= 0.10:
            exclusions["meaningful_opposition"] += 1
            continue
        if net_cost < UNIT_USD:
            exclusions["below_one_measured_unit"] += 1
            continue
        if entry_price < 0.35:
            exclusions["entry_below_35c"] += 1
            continue
        if not 0.01 < entry_price < 0.99:
            exclusions["invalid_entry_price"] += 1
            continue
        play_date = datetime.fromtimestamp(int(market["start"]), timezone.utc).date()
        if not START <= play_date <= END:
            exclusions["outside_shared_window"] += 1
            continue
        plays.append(
            {
                **market,
                "wallet": "DaBossHogg",
                "date": play_date.isoformat(),
                "selection": leader,
                "entry_price": entry_price,
                "won": leader == market["winner"],
                "wallet_units": net_cost / UNIT_USD,
                "opposing_ratio": opposing_ratio,
                "stake_units": 1.0,
            }
        )
    return sorted(plays, key=lambda row: (row["start"], row["condition_id"])), {
        "full_trade_rows": len(rows),
        "tennis_fill_rows": len(tennis),
        "tennis_conditions": len(grouped),
        "resolved_main_markets": len(metadata),
        "qualified_shared_window_plays": len(plays),
        "estimated_unit_usd": UNIT_USD,
        "exclusions": dict(exclusions),
    }


def play_return(play: dict[str, Any]) -> float:
    price = number(play["entry_price"])
    return (1.0 - price) / price if play["won"] else -1.0


def build_arm(wallet_plays: dict[str, list[dict[str, Any]]], include_daboss: bool) -> tuple[list[dict[str, Any]], dict[str, int]]:
    included = {"Bagwell306", "Lilybaeum"} | ({"DaBossHogg"} if include_daboss else set())
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for wallet in included:
        for play in wallet_plays[wallet]:
            grouped[str(play["condition_id"])].append(play)
    result: list[dict[str, Any]] = []
    structure: dict[str, int] = defaultdict(int)
    standalone = {"Bagwell306": 1.0, "Lilybaeum": 0.75, "DaBossHogg": 1.0}
    for rows in grouped.values():
        selections = {str(row["selection"]) for row in rows}
        if len(selections) > 1:
            structure["direct_conflict_skipped"] += 1
            continue
        count = len(rows)
        units = standalone[str(rows[0]["wallet"])] if count == 1 else float(count)
        wallets = "+".join(sorted(str(row["wallet"]) for row in rows))
        result.append(
            {
                **rows[0],
                "wallet": wallets,
                "entry_price": max(number(row["entry_price"]) for row in rows),
                "stake_units": units,
                "agreement": f"{count}_sharp",
            }
        )
        structure[f"{count}_sharp_plays"] += 1
        if count == 1:
            structure[f"{wallets}_standalone"] += 1
    return sorted(result, key=lambda row: (row["start"], row["condition_id"])), dict(structure)


def summarize(plays: list[dict[str, Any]]) -> dict[str, Any]:
    profit = stake = equity = peak = drawdown = 0.0
    wins = 0
    for play in plays:
        units = number(play["stake_units"])
        pnl = units * play_return(play)
        profit += pnl
        stake += units
        equity += pnl
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
        wins += int(bool(play["won"]))
    return {
        "bets": len(plays),
        "record": f"{wins}-{len(plays)-wins}",
        "profit_units": profit,
        "staked_units": stake,
        "roi": profit / stake if stake else 0.0,
        "max_drawdown_units": drawdown,
    }


def metric(values: np.ndarray) -> dict[str, float]:
    return {key: float(value) for key, value in {
        "worst": np.min(values),
        "p05": np.quantile(values, 0.05),
        "median": np.median(values),
        "mean": np.mean(values),
        "p95": np.quantile(values, 0.95),
        "best": np.max(values),
    }.items()}


def simulate(arms: dict[str, list[dict[str, Any]]], horizon: int, paths: int, seed: int) -> dict[str, Any]:
    days = [(START + timedelta(days=i)).isoformat() for i in range((END - START).days + 1)]
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for arm, plays in arms.items():
        by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for play in plays:
            by_day[str(play["date"])].append(play)
        grouped[arm] = by_day
    rng = np.random.default_rng(seed)
    samples = rng.integers(0, len(days), size=(paths, horizon))
    raw_profit: dict[str, np.ndarray] = {}
    output: dict[str, Any] = {}
    for arm in arms:
        profits = np.zeros(paths)
        stakes = np.zeros(paths)
        bets = np.zeros(paths)
        drawdowns = np.zeros(paths)
        for path in range(paths):
            equity = peak = 0.0
            for day_index in samples[path]:
                for play in grouped[arm][days[int(day_index)]]:
                    units = number(play["stake_units"])
                    pnl = units * play_return(play)
                    profits[path] += pnl
                    stakes[path] += units
                    bets[path] += 1
                    equity += pnl
                    peak = max(peak, equity)
                    drawdowns[path] = max(drawdowns[path], peak - equity)
        rois = np.divide(profits, stakes, out=np.zeros_like(profits), where=stakes > 0)
        raw_profit[arm] = profits
        output[arm] = {
            "bets": metric(bets),
            "profit_units": metric(profits),
            "roi": metric(rois),
            "max_drawdown_units": metric(drawdowns),
            "probability_profitable": float(np.mean(profits > 0)),
        }
    delta = raw_profit["with_dabosshogg"] - raw_profit["current_two_wallet"]
    return {
        "arms": output,
        "paired_with_minus_current": {
            "profit_units": metric(delta),
            "probability_improves_profit": float(np.mean(delta > 0)),
            "probability_reduces_profit": float(np.mean(delta < 0)),
            "probability_equal": float(np.mean(np.isclose(delta, 0.0))),
        },
    }


def run(paths: int, seed: int) -> dict[str, Any]:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    ledgers = source["qualified_play_ledgers"]
    wallet_plays = {
        "Bagwell306": [row for row in ledgers["Bagwell306"] if START <= date.fromisoformat(row["date"]) <= END],
        "Lilybaeum": [row for row in ledgers["Lilybaeum"] if START <= date.fromisoformat(row["date"]) <= END],
    }
    wallet_plays["DaBossHogg"], audit = load_daboss_plays()
    current, current_structure = build_arm(wallet_plays, False)
    augmented, augmented_structure = build_arm(wallet_plays, True)
    arms = {"current_two_wallet": current, "with_dabosshogg": augmented}
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "paths": paths,
        "shared_window": {"start": START.isoformat(), "end": END.isoformat()},
        "rules": {
            "standalone_units": {"Bagwell306": 1.0, "Lilybaeum": 0.75, "DaBossHogg": 1.0},
            "same_side_units": "2 sharps = 2u; 3 sharps = 3u",
            "direct_conflicts": "skip",
            "entry_proxy": "last wallet entry at/before 30 minutes pre-start; agreements use the worst entry price",
            "minimum_wallet_position": "1 estimated wallet unit",
        },
        "dabosshogg_audit": audit,
        "structure": {"current_two_wallet": current_structure, "with_dabosshogg": augmented_structure},
        "historical_replay": {name: summarize(plays) for name, plays in arms.items()},
        "simulations": {str(h): simulate(arms, h, paths, seed + h) for h in HORIZONS},
        "qualified_play_ledgers": arms,
        "limitations": [
            "This is a paired empirical day-block bootstrap, not a guarantee of future results.",
            "DaBossHogg has a concentrated historical P&L profile and a shorter observed sample than Bagwell306.",
            "Follower slippage, fees, and missed fills are excluded.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20260810)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    payload = run(args.paths, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    print(json.dumps({key: value for key, value in payload.items() if key != "qualified_play_ledgers"}, indent=2))


if __name__ == "__main__":
    main()
