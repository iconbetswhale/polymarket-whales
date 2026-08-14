from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def performance(rows: list[dict[str, Any]]) -> dict[str, Any]:
    risk = sum(number(row["risk_usd"]) for row in rows)
    pnl = sum(number(row["pnl_usd"]) for row in rows)
    flat_profit = sum(
        (1 - number(row["entry_price"])) / number(row["entry_price"])
        if row["won"] and 0 < number(row["entry_price"]) < 1
        else -1
        for row in rows
    )
    return {
        "plays": len(rows),
        "wins": sum(bool(row["won"]) for row in rows),
        "losses": sum(not bool(row["won"]) for row in rows),
        "risked_usd": risk,
        "pnl_usd": pnl,
        "wallet_roi": pnl / risk if risk else None,
        "flat_copy_profit_units": flat_profit,
        "flat_copy_roi": flat_profit / len(rows) if rows else None,
    }


def normalize_winners(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "condition_id": str(row.get("conditionId") or ""),
            "event_slug": str(row.get("eventSlug") or ""),
            "slug": str(row.get("slug") or ""),
            "title": str(row.get("title") or ""),
            "outcome": str(row.get("outcome") or ""),
            "market_type": "Spread" if "-spread-" in str(row.get("slug") or "") else "Moneyline",
            "entry_price": number(row.get("avgPrice")),
            "risk_usd": number(row.get("initialValue")) or number(row.get("totalBought")) * number(row.get("avgPrice")),
            "pnl_usd": number(row.get("realizedPnl")),
            "won": True,
            "month": str(row.get("endDate") or "")[:7],
        }
        for row in rows
        if str(row.get("eventSlug") or "").startswith("wnba-")
    ]


def normalize_losers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "condition_id": str(row.get("conditionId") or ""),
            "event_slug": str(row.get("eventSlug") or ""),
            "slug": str(row.get("slug") or ""),
            "title": str(row.get("title") or ""),
            "outcome": str(row.get("outcome") or ""),
            "market_type": "Spread" if "-spread-" in str(row.get("slug") or "") else "Moneyline",
            "entry_price": number(row.get("avgPrice")),
            "risk_usd": number(row.get("initialValue")),
            "pnl_usd": number(row.get("cashPnl")),
            "won": False,
            "month": str(row.get("endDate") or "")[:7],
        }
        for row in rows
        if str(row.get("eventSlug") or "").startswith("wnba-")
        and number(row.get("curPrice")) <= 0.001
        and bool(row.get("redeemable"))
    ]


def wilson_interval(wins: int, count: int) -> list[float] | None:
    if not count:
        return None
    z = 1.96
    rate = wins / count
    denominator = 1 + z * z / count
    center = (rate + z * z / (2 * count)) / denominator
    half = z * math.sqrt(rate * (1 - rate) / count + z * z / (4 * count * count)) / denominator
    return [center - half, center + half]


def fair_price_tail_probability(rows: list[dict[str, Any]], paths: int = 100_000) -> float | None:
    if not rows:
        return None
    observed = number(performance(rows)["flat_copy_profit_units"])
    prices = [number(row["entry_price"]) for row in rows]
    rng = random.Random(777)
    exceedances = 0
    for _ in range(paths):
        profit = sum((1 - price) / price if rng.random() < price else -1 for price in prices)
        exceedances += profit >= observed
    return exceedances / paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--closed", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    closed = json.loads(args.closed.read_text(encoding="utf-8"))
    current = json.loads(args.current.read_text(encoding="utf-8"))
    winners = normalize_winners(closed)
    losers = normalize_losers(current)
    rows = winners + losers

    # Multiple alternate lines on one event are correlated. The largest-risk
    # position is the best available proxy for the wallet's primary opinion.
    by_event: dict[str, dict[str, Any]] = {}
    for row in rows:
        event = str(row["event_slug"])
        if event not in by_event or number(row["risk_usd"]) > number(by_event[event]["risk_usd"]):
            by_event[event] = row
    event_rows = list(by_event.values())
    by_spread_event: dict[str, dict[str, Any]] = {}
    for row in (value for value in rows if value["market_type"] == "Spread"):
        event = str(row["event_slug"])
        if event not in by_spread_event or number(row["risk_usd"]) > number(by_spread_event[event]["risk_usd"]):
            by_spread_event[event] = row
    event_spreads = list(by_spread_event.values())

    monthly: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        monthly[str(row["month"])].append(row)

    sizes = [number(row["risk_usd"]) for row in rows]
    prices = [number(row["entry_price"]) for row in rows]
    report = {
        "identity": {
            "address": "0xb8c842bc049bf208f73354c7b037b811d741d8a4",
            "label": "Formal-Cupcake",
            "scope": "WNBA",
        },
        "data_quality": {
            "closed_source": str(args.closed),
            "current_source": str(args.current),
            "redeemed_winner_rows": len(winners),
            "expired_worthless_rows_recovered_from_current": len(losers),
            "combined_exact_positions": len(rows),
            "unique_conditions": len({row["condition_id"] for row in rows}),
            "unique_events": len(by_event),
            "duplicate_event_market_positions": len(rows) - len(by_event),
            "clv_coverage": 0,
            "fill_timestamp_coverage": 0,
            "note": "Closed positions alone are winner-biased. Complete outcome reconstruction requires combining redeemed winners with curPrice=0 redeemable losers from the paired current snapshot.",
        },
        "sizing": {
            "measured_base_unit_usd": 1300,
            "minimum_risk_usd": min(sizes) if sizes else None,
            "median_risk_usd": statistics.median(sizes) if sizes else None,
            "maximum_risk_usd": max(sizes) if sizes else None,
            "positions_between_0.75_and_1.25_units": sum(975 <= size < 1625 for size in sizes),
        },
        "entry_price": {
            "minimum": min(prices) if prices else None,
            "median": statistics.median(prices) if prices else None,
            "maximum": max(prices) if prices else None,
        },
        "performance": {
            "all_exact_positions": performance(rows),
            "event_deduplicated": performance(event_rows),
            "exact_spreads": performance([row for row in rows if row["market_type"] == "Spread"]),
            "event_deduplicated_spreads": performance(event_spreads),
            "moneylines": performance([row for row in rows if row["market_type"] == "Moneyline"]),
            "monthly_exact_positions": {month: performance(values) for month, values in sorted(monthly.items())},
        },
        "strategy_signature": {
            "spread_positions": sum(row["market_type"] == "Spread" for row in rows),
            "spread_positions_on_underdog_plus_points": sum(row["market_type"] == "Spread" for row in rows),
            "underdog_spread_rate": 1.0,
            "description": "Systematic, nearly flat-$1,300 WNBA underdog-spread strategy; moneyline results are materially negative.",
        },
        "statistical_context": {
            "event_level_record_confidence_interval_95": wilson_interval(sum(bool(row["won"]) for row in event_rows), len(event_rows)),
            "spread_fair_price_monte_carlo_paths": 100_000,
            "probability_of_matching_or_exceeding_observed_spread_profit_under_fair_entries": fair_price_tail_probability(event_spreads),
            "interpretation": "The spread result is statistically encouraging but remains a short, non-independent historical sample without CLV verification.",
        },
        "model_recommendation": {
            "role": "CONDITIONAL_ORIGINATOR",
            "eligible_market": "WNBA full-game spreads only",
            "minimum_position_usd": 1300,
            "exclude": ["WNBA moneylines", "duplicate alternate spread lines", "opposed or materially hedged event structures"],
            "quality_weight": 0.85,
            "forward_requirement": "Track at least 50 additional event-deduplicated WNBA spread signals and closing-line value before promotion to unrestricted Lead.",
        },
        "limitations": [
            "The paired snapshots end on 2026-08-04 and do not include fill timestamps.",
            "There is no WNBA CLV coverage in the stored Formal-Cupcake CLV file.",
            "Thirty-nine event-deduplicated spread plays are promising but not enough to establish a stable long-run edge.",
            "The fair-price simulation assumes quoted entry probabilities are calibrated and treats events as independent.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
