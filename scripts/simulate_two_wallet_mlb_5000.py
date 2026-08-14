from __future__ import annotations

import json
import math
import random
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from polymarket_client import PolymarketClient


ET = ZoneInfo("America/New_York")
ITERATIONS = 5_000
AS_OF = date(2026, 8, 8)
HORIZONS = (7, 30, 60)
SOURCE_DIR = ROOT / "outputs" / "two-wallet-mlb-sim-source"
OUTPUT = ROOT / "outputs" / "two-wallet-mlb-5000-simulation-2026-08-08.json"

WALLETS: dict[str, dict[str, Any]] = {
    "Unkempt-Image": {
        "address": "0xd106952ebf30a3125affd8a23b6c1f30c35fc79c",
        "unit_usd": 3_000.0,
        "closed_limit": 12_000,
    },
    "Zealous-Violence": {
        "address": "0xa697d0b3fff7d285a0f92d6ee03a7f97809e59d5",
        "unit_usd": 830.0,
        "closed_limit": 6_000,
    },
}


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def position_cost(row: dict[str, Any]) -> float:
    initial = number(row.get("initialValue"))
    if initial > 0:
        return initial
    return number(row.get("totalBought")) * number(row.get("avgPrice"))


def load_closed(label: str, config: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    path = SOURCE_DIR / f"{label.lower().replace('-', '_')}-closed.json"
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [row for row in payload if isinstance(row, dict)], True
    rows = PolymarketClient(max_retries=8).get_closed_positions(
        str(config["address"]), int(config["closed_limit"])
    )
    path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    return rows, False


def event_date(slug: str, timestamp: int) -> str:
    pieces = slug.rsplit("-", 3)
    if len(pieces) == 4:
        candidate = "-".join(pieces[-3:])
        try:
            return date.fromisoformat(candidate).isoformat()
        except ValueError:
            pass
    return datetime.fromtimestamp(timestamp, ET).date().isoformat()


def stake_from_conviction(relative_units: float) -> float:
    if relative_units < 0.50:
        return 0.75
    if relative_units < 1.00:
        return 1.00
    if relative_units < 2.00:
        return 1.25
    if relative_units < 4.00:
        return 1.50
    return 1.75 + 0.25 * math.log2(relative_units / 4.0)


def build_signals(
    label: str, config: dict[str, Any], rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    audit: defaultdict[str, int] = defaultdict(int)
    for row in rows:
        event_slug = str(row.get("eventSlug") or "").lower()
        market_slug = str(row.get("slug") or "").lower()
        if not event_slug.startswith("mlb-"):
            continue
        audit["mlb_position_rows"] += 1
        if market_slug != event_slug:
            audit["non_moneyline_rows"] += 1
            continue
        key = str(row.get("conditionId") or row.get("asset") or "").lower()
        if key:
            grouped[key].append(row)

    signals: list[dict[str, Any]] = []
    for condition_id, items in grouped.items():
        outcomes: dict[str, dict[str, float]] = defaultdict(
            lambda: {"cost": 0.0, "shares": 0.0, "pnl": 0.0, "cur_price": -1.0}
        )
        for item in items:
            outcome = str(item.get("outcome") or item.get("asset") or "").strip()
            outcomes[outcome]["cost"] += position_cost(item)
            outcomes[outcome]["shares"] += number(item.get("totalBought"))
            outcomes[outcome]["pnl"] += number(item.get("realizedPnl"))
            outcomes[outcome]["cur_price"] = max(
                outcomes[outcome]["cur_price"], number(item.get("curPrice"))
            )
        ordered = sorted(outcomes.items(), key=lambda pair: pair[1]["cost"], reverse=True)
        if not ordered:
            continue
        leader, leader_values = ordered[0]
        leader_cost = leader_values["cost"]
        opposing_cost = sum(values["cost"] for _, values in ordered[1:])
        opposing_ratio = opposing_cost / leader_cost if leader_cost else 0.0
        net_cost = max(0.0, leader_cost - opposing_cost)
        relative_units = net_cost / float(config["unit_usd"])
        audit["moneyline_markets"] += 1
        if opposing_ratio > 0.20:
            audit["material_or_two_sided"] += 1
            continue
        if relative_units < 0.25:
            audit["below_quarter_unit"] += 1
            continue
        winners = [
            outcome
            for outcome, values in outcomes.items()
            if values["cur_price"] >= 0.99
        ]
        settled_outcomes = [
            outcome
            for outcome, values in outcomes.items()
            if values["cur_price"] <= 0.01 or values["cur_price"] >= 0.99
        ]
        if len(winners) != 1 or len(settled_outcomes) != len(outcomes):
            audit["unresolved_or_ambiguous"] += 1
            continue
        shares = leader_values["shares"]
        price = leader_cost / shares if shares else 0.0
        if not 0.01 <= price <= 0.99:
            audit["invalid_entry_price"] += 1
            continue
        sample = items[0]
        signals.append(
            {
                "wallet": label,
                "condition_id": condition_id,
                "event_slug": str(sample.get("eventSlug") or ""),
                "date": event_date(
                    str(sample.get("eventSlug") or ""),
                    max(int(item.get("timestamp") or 0) for item in items),
                ),
                "outcome": leader,
                "price": price,
                "won": leader == winners[0],
                "net_cost_usd": net_cost,
                "relative_units": relative_units,
                "opposing_ratio": opposing_ratio,
                "stake_units": stake_from_conviction(relative_units),
            }
        )
    audit["eligible_signals"] = len(signals)
    return signals, dict(audit)


def position_return(price: float, won: bool) -> float:
    return (1.0 - price) / price if won else -1.0


def individual_plays(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            **signal,
            "supporters": [signal["wallet"]],
            "supporter_count": 1,
            "pnl_units": signal["stake_units"]
            * position_return(float(signal["price"]), bool(signal["won"])),
        }
        for signal in signals
    ]


def combined_plays(
    signal_map: dict[str, list[dict[str, Any]]]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for signals in signal_map.values():
        for signal in signals:
            by_condition[str(signal["condition_id"])].append(signal)
    plays: list[dict[str, Any]] = []
    audit: defaultdict[str, int] = defaultdict(int)
    for condition_id, signals in by_condition.items():
        if len(signals) > 1 and len({str(signal["outcome"]) for signal in signals}) > 1:
            audit["qualifying_wallet_conflicts_skipped"] += 1
            continue
        outcome = str(signals[0]["outcome"])
        won = bool(signals[0]["won"])
        if any(bool(signal["won"]) != won for signal in signals):
            audit["settlement_mismatch_skipped"] += 1
            continue
        stake = sum(float(signal["stake_units"]) for signal in signals)
        price = statistics.median(float(signal["price"]) for signal in signals)
        supporters = sorted(str(signal["wallet"]) for signal in signals)
        plays.append(
            {
                "condition_id": condition_id,
                "event_slug": signals[0]["event_slug"],
                "date": signals[0]["date"],
                "outcome": outcome,
                "price": price,
                "won": won,
                "stake_units": stake,
                "pnl_units": stake * position_return(price, won),
                "supporters": supporters,
                "supporter_count": len(supporters),
            }
        )
        audit["agreement_plays" if len(supporters) == 2 else "single_wallet_plays"] += 1
    return plays, dict(audit)


def max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    result = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        result = max(result, peak - equity)
    return result


def summarize_actual(plays: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(plays, key=lambda row: (str(row["date"]), str(row["condition_id"])))
    stake = sum(float(play["stake_units"]) for play in ordered)
    profit = sum(float(play["pnl_units"]) for play in ordered)
    wins = sum(bool(play["won"]) for play in ordered)
    active_days = len({str(play["date"]) for play in ordered})
    return {
        "bets": len(ordered),
        "record": f"{wins}-{len(ordered) - wins}",
        "win_rate": wins / len(ordered) if ordered else None,
        "active_days": active_days,
        "plays_per_active_day": len(ordered) / active_days if active_days else None,
        "average_stake_units": stake / len(ordered) if ordered else None,
        "staked_units": stake,
        "profit_units": profit,
        "roi": profit / stake if stake else None,
        "max_drawdown_units": max_drawdown([float(play["pnl_units"]) for play in ordered]),
    }


def distribution(values: list[float]) -> dict[str, float]:
    return {
        "minimum_sampled": min(values),
        "p01": percentile(values, 0.01),
        "p05": percentile(values, 0.05),
        "median": percentile(values, 0.50),
        "mean": statistics.mean(values),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "maximum_sampled": max(values),
    }


def simulate(plays: list[dict[str, Any]], days: int, seed: int) -> dict[str, Any]:
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    first = min(date.fromisoformat(str(play["date"])) for play in plays)
    last = min(AS_OF, max(date.fromisoformat(str(play["date"])) for play in plays))
    for play in plays:
        play_date = date.fromisoformat(str(play["date"]))
        if first <= play_date <= last:
            by_day[play_date.isoformat()].append(play)
    blocks = [
        by_day[(first + timedelta(days=index)).isoformat()]
        for index in range((last - first).days + 1)
    ]
    rng = random.Random(seed)
    finals: list[float] = []
    rois: list[float] = []
    bets: list[float] = []
    wins: list[float] = []
    drawdowns: list[float] = []
    upsides: list[float] = []
    for _ in range(ITERATIONS):
        path_pnl: list[float] = []
        path_stake = 0.0
        path_bets = 0
        path_wins = 0
        equity = 0.0
        maximum_equity = 0.0
        for _day in range(days):
            for play in rng.choice(blocks):
                pnl = float(play["pnl_units"])
                path_pnl.append(pnl)
                path_stake += float(play["stake_units"])
                path_bets += 1
                path_wins += int(bool(play["won"]))
                equity += pnl
                maximum_equity = max(maximum_equity, equity)
        profit = sum(path_pnl)
        finals.append(profit)
        rois.append(profit / path_stake if path_stake else 0.0)
        bets.append(float(path_bets))
        wins.append(path_wins / path_bets if path_bets else 0.0)
        drawdowns.append(max_drawdown(path_pnl))
        upsides.append(maximum_equity)
    return {
        "iterations": ITERATIONS,
        "days": days,
        "probability_profitable": sum(value > 0 for value in finals) / ITERATIONS,
        "probability_no_bets": sum(value == 0 for value in bets) / ITERATIONS,
        "bets": distribution(bets),
        "hit_rate": distribution(wins),
        "profit_units": distribution(finals),
        "roi": distribution(rois),
        "maximum_drawdown_units": distribution(drawdowns),
        "maximum_upside_units": distribution(upsides),
    }


def main() -> None:
    signal_map: dict[str, list[dict[str, Any]]] = {}
    source_audit: dict[str, Any] = {}
    signal_audit: dict[str, Any] = {}
    for label, config in WALLETS.items():
        rows, cached = load_closed(label, config)
        signals, audit = build_signals(label, config, rows)
        signal_map[label] = signals
        source_audit[label] = {
            "closed_rows": len(rows),
            "requested_limit": config["closed_limit"],
            "may_be_capped": len(rows) >= int(config["closed_limit"]),
            "loaded_from_cache": cached,
        }
        signal_audit[label] = audit

    strategies = {
        label: individual_plays(signals) for label, signals in signal_map.items()
    }
    combined, combined_audit = combined_plays(signal_map)
    strategies["Combined no-conflict"] = combined
    result = {
        "as_of_et": datetime.now(ET).isoformat(),
        "iterations": ITERATIONS,
        "method": {
            "scope": "Settled MLB moneylines only.",
            "signal": "Largest-cost outcome after exact-market netting; opposing ratio must be <=20% and net exposure >=0.25 measured wallet unit.",
            "units": {label: config["unit_usd"] for label, config in WALLETS.items()},
            "sizing": "Conviction ladder begins at 0.75u and rises with net wallet units; no maximum cap. Agreement combines both wallet stakes.",
            "conflicts": "If both wallets qualify on opposite outcomes, no play is made.",
            "simulation": "5,000 calendar-day block-bootstrap paths for each horizon, including zero-play days.",
            "limitation": "This is an in-sample settled-position replay. Entry prices are wallet average prices, not guaranteed follower prices, and the public ledgers are capped at the requested row limits.",
        },
        "source_audit": source_audit,
        "signal_audit": signal_audit,
        "combined_audit": combined_audit,
        "strategies": {
            name: {
                "historical_sample": summarize_actual(plays),
                "simulations": {
                    str(days): simulate(plays, days, 8800 + index * 100 + days)
                    for index, days in enumerate(HORIZONS)
                },
            }
            for name, plays in strategies.items()
        },
    }
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
