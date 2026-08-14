from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[1]


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    low, high = math.floor(index), math.ceil(index)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def category(row: dict[str, Any]) -> str:
    slug = str(row.get("eventSlug") or "").lower()
    prefix = slug.split("-", 1)[0]
    if prefix in {"btc", "eth", "xrp", "sol", "solana", "bnb", "doge", "hype"}:
        if "-updown-5m-" in slug:
            return "Crypto 5m"
        if "-updown-15m-" in slug:
            return "Crypto 15m"
        return "Crypto Other"
    mapping = {
        "mlb": "MLB",
        "nba": "NBA",
        "nhl": "NHL",
        "nfl": "NFL",
        "wnba": "WNBA",
        "ufc": "UFC/MMA",
        "mma": "UFC/MMA",
    }
    if prefix in mapping:
        return mapping[prefix]
    if prefix in {"atp", "wta", "itf", "utr", "challenger"}:
        return "Tennis"
    return "Other"


def analyze_fill_window(path: Path) -> dict[str, Any]:
    rows = json.loads(path.read_text(encoding="utf-8-sig"))
    rows = [row for row in rows if isinstance(row, dict)]
    timestamps = sorted(int(row.get("timestamp") or 0) for row in rows)
    costs_by_market: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    fills_by_market: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    category_notional: Counter[str] = Counter()
    prices: list[float] = []
    costs: list[float] = []
    crypto_seconds_to_close: list[float] = []
    active_days: Counter[str] = Counter()
    active_hours: Counter[int] = Counter()

    for row in rows:
        condition = str(row.get("conditionId") or "")
        outcome = str(row.get("asset") or row.get("outcomeIndex") or row.get("outcome") or "")
        price = number(row.get("price"))
        shares = number(row.get("size"))
        cost = price * shares
        timestamp = int(row.get("timestamp") or 0)
        row_category = category(row)
        costs_by_market[condition][outcome] += cost
        fills_by_market[condition] += 1
        categories[row_category] += 1
        category_notional[row_category] += cost
        prices.append(price)
        costs.append(cost)
        active_days[datetime.fromtimestamp(timestamp, ET).date().isoformat()] += 1
        active_hours[datetime.fromtimestamp(timestamp, ET).hour] += 1
        if row_category.startswith("Crypto"):
            tail = str(row.get("eventSlug") or "").rsplit("-", 1)[-1]
            if tail.isdigit():
                duration = 300 if row_category == "Crypto 5m" else 900 if row_category == "Crypto 15m" else 0
                seconds = int(tail) + duration - timestamp
                if -60 <= seconds <= 3600:
                    crypto_seconds_to_close.append(seconds)

    direction_counts: Counter[str] = Counter()
    net_sizes: list[float] = []
    opposing_ratios: list[float] = []
    for outcome_costs in costs_by_market.values():
        ordered = sorted(outcome_costs.values(), reverse=True)
        leader = ordered[0] if ordered else 0.0
        opposition = sum(ordered[1:])
        ratio = opposition / leader if leader else 0.0
        status = (
            "CLEAN_DIRECTIONAL"
            if ratio < 0.10
            else "MINOR_HEDGE"
            if ratio <= 0.20
            else "MATERIAL_HEDGE"
            if ratio <= 0.50
            else "TWO_SIDED"
        )
        direction_counts[status] += 1
        opposing_ratios.append(ratio)
        net_sizes.append(max(0.0, leader - opposition))

    gap_values = [right - left for left, right in zip(timestamps, timestamps[1:])]
    total_notional = sum(costs)
    return {
        "source_file": str(path),
        "identity": {
            "address": str(rows[0].get("proxyWallet") or "").lower() if rows else None,
            "pseudonym": str(rows[0].get("pseudonym") or "") if rows else None,
        },
        "coverage": {
            "rows": len(rows),
            "unique_transactions": len({str(row.get("transactionHash") or "") for row in rows}),
            "exact_markets": len(costs_by_market),
            "events": len({str(row.get("eventSlug") or "") for row in rows}),
            "active_days": len(active_days),
            "start_et": datetime.fromtimestamp(min(timestamps), ET).isoformat() if timestamps else None,
            "end_et": datetime.fromtimestamp(max(timestamps), ET).isoformat() if timestamps else None,
            "row_cap_warning": len(rows) in {1_000, 5_000, 10_000},
        },
        "activity": {
            "gross_buy_notional_usd": total_notional,
            "median_fill_cost_usd": statistics.median(costs) if costs else None,
            "p90_fill_cost_usd": percentile(costs, 0.90),
            "median_fills_per_market": statistics.median(fills_by_market.values()) if fills_by_market else None,
            "p90_fills_per_market": percentile(list(fills_by_market.values()), 0.90),
            "median_interfill_seconds": statistics.median(gap_values) if gap_values else None,
            "fills_within_10_seconds_rate": sum(gap <= 10 for gap in gap_values) / len(gap_values) if gap_values else None,
            "median_daily_fills": statistics.median(active_days.values()) if active_days else None,
            "p90_daily_fills": percentile(list(active_days.values()), 0.90),
            "hour_counts_et": dict(sorted(active_hours.items())),
        },
        "category_mix": {
            key: {
                "fills": categories[key],
                "fill_share": categories[key] / len(rows) if rows else None,
                "buy_notional_usd": category_notional[key],
                "notional_share": category_notional[key] / total_notional if total_notional else None,
            }
            for key in sorted(categories)
        },
        "directionality_in_attached_window": {
            "counts": dict(direction_counts),
            "clean_directional_rate": direction_counts["CLEAN_DIRECTIONAL"] / len(costs_by_market) if costs_by_market else None,
            "two_sided_rate": direction_counts["TWO_SIDED"] / len(costs_by_market) if costs_by_market else None,
            "median_opposing_ratio": statistics.median(opposing_ratios) if opposing_ratios else None,
            "median_net_directional_cost_usd": statistics.median(net_sizes) if net_sizes else None,
            "p90_net_directional_cost_usd": percentile(net_sizes, 0.90),
        },
        "entry_prices": {
            "median": statistics.median(prices) if prices else None,
            "p10": percentile(prices, 0.10),
            "p90": percentile(prices, 0.90),
            "at_or_above_0_95_rate": sum(price >= 0.95 for price in prices) / len(prices) if prices else None,
            "at_or_above_0_99_rate": sum(price >= 0.99 for price in prices) / len(prices) if prices else None,
        },
        "crypto_timing": {
            "samples": len(crypto_seconds_to_close),
            "median_seconds_before_close": statistics.median(crypto_seconds_to_close) if crypto_seconds_to_close else None,
            "p10_seconds_before_close": percentile(crypto_seconds_to_close, 0.10),
            "p90_seconds_before_close": percentile(crypto_seconds_to_close, 0.90),
            "within_10_seconds_rate": sum(-10 <= seconds <= 10 for seconds in crypto_seconds_to_close) / len(crypto_seconds_to_close) if crypto_seconds_to_close else None,
            "within_30_seconds_rate": sum(-30 <= seconds <= 30 for seconds in crypto_seconds_to_close) / len(crypto_seconds_to_close) if crypto_seconds_to_close else None,
            "after_scheduled_close_rate": sum(seconds < 0 for seconds in crypto_seconds_to_close) / len(crypto_seconds_to_close) if crypto_seconds_to_close else None,
        },
    }


def main() -> None:
    inputs = [
        (
            Path(r"C:\Users\15617\.codex\codex-remote-attachments\019f63cc-fa15-7ff3-aab8-b15eddcb9a08\271DAA48-97D8-4A50-B239-88DFA6BEA078\1-api-response-32-1-.json"),
            ROOT / "outputs" / "unkempt-image-full-extraction-2026-08-08.json",
        ),
        (
            Path(r"C:\Users\15617\.codex\codex-remote-attachments\019f63cc-fa15-7ff3-aab8-b15eddcb9a08\271DAA48-97D8-4A50-B239-88DFA6BEA078\2-api-response-33-.json"),
            ROOT / "outputs" / "zealous-violence-full-extraction-2026-08-08.json",
        ),
    ]
    wallets = []
    for source, ledger_report in inputs:
        wallets.append(
            {
                "fill_window": analyze_fill_window(source),
                "settled_ledger": json.loads(ledger_report.read_text(encoding="utf-8")),
            }
        )
    report = {
        "as_of_et": datetime.now(ET).isoformat(),
        "method": {
            "settled_performance": "Public Polymarket closed-position rows, aggregated by exact condition and outcome.",
            "execution_behavior": "Attached BUY-fill windows, deduplicated by their unique transaction hashes.",
            "copy_test": "One flat unit on the largest-cost outcome in each settled exact market; this is not the wallet's account ROI.",
            "limitations": [
                "Attached exports contain BUY fills only and cannot independently reproduce exits or realized P&L.",
                "Unkempt-Image exceeds 100,000 public fills; its 10,000-row attachment is a truncated recent window.",
                "Zealous-Violence settled results are the latest 6,000 position rows and may not represent lifetime performance.",
            ],
        },
        "wallets": wallets,
    }
    output = ROOT / "outputs" / "two-wallet-full-extraction-summary-2026-08-08.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
