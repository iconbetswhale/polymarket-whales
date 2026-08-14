from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unit_analysis import estimate_unit_size
from wallet_activity import normalize_trade_fills


ET = ZoneInfo("America/New_York")


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


def load_array(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON array")
    return [row for row in payload if isinstance(row, dict)]


def classify_sport(row: dict[str, Any]) -> str:
    slug = str(row.get("eventSlug") or row.get("event_slug") or row.get("slug") or "").lower()
    prefix = slug.split("-", 1)[0]
    if prefix in {"atp", "wta", "itf", "utr", "challenger"}:
        return "Tennis"
    mapping = {
        "mlb": "MLB",
        "nba": "NBA",
        "wnba": "WNBA",
        "nfl": "NFL",
        "nhl": "NHL",
        "cbb": "College Basketball",
        "ncaab": "College Basketball",
        "ncaaf": "College Football",
        "ufc": "UFC/MMA",
        "mma": "UFC/MMA",
        "cs2": "CS2",
        "lol": "League of Legends",
        "dota2": "Dota 2",
    }
    if prefix in mapping:
        return mapping[prefix]
    soccer_prefixes = {
        "fifwc", "ucl", "uel", "epl", "mls", "lal", "laliga", "bun",
        "bundesliga", "seriea", "ligue1", "lib", "sud", "tur", "nor",
        "chi", "bra", "arg", "mex",
    }
    if prefix in soccer_prefixes:
        return "Soccer"
    return "Other"


def classify_market(row: dict[str, Any]) -> str:
    slug = str(row.get("slug") or row.get("market_slug") or "").lower()
    title = str(row.get("title") or row.get("market_title") or "").lower()
    if "-total-" in slug or "o/u " in title:
        return "Total"
    if "-spread-" in slug or title.startswith("spread:"):
        return "Spread"
    return "Moneyline"


def performance(rows: list[dict[str, Any]]) -> dict[str, Any]:
    risked = sum(number(row["cost_usd"]) for row in rows)
    pnl = sum(number(row["pnl_usd"]) for row in rows)
    return {
        "markets": len(rows),
        "wins": sum(number(row["pnl_usd"]) > 0 for row in rows),
        "losses": sum(number(row["pnl_usd"]) < 0 for row in rows),
        "risked_usd": risked,
        "pnl_usd": pnl,
        "roi": pnl / risked if risked else None,
        "median_risked_usd": statistics.median([number(row["cost_usd"]) for row in rows]) if rows else None,
    }


def copy_performance(rows: list[dict[str, Any]]) -> dict[str, Any]:
    staked = sum(number(row.get("stake_units")) for row in rows)
    profit = sum(
        number(row.get("stake_units"))
        * ((1 - number(row.get("entry_price"))) / number(row.get("entry_price")))
        if bool(row.get("won")) and 0 < number(row.get("entry_price")) < 1
        else -number(row.get("stake_units"))
        for row in rows
    )
    return {
        "bets": len(rows),
        "wins": sum(bool(row.get("won")) for row in rows),
        "profit_units": profit,
        "roi": profit / staked if staked else None,
    }


def aggregate_fills(fills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    positions: dict[tuple[str, str], dict[str, Any]] = {}
    for fill in fills:
        key = (str(fill["condition_id"]), str(fill["outcome_id"]))
        position = positions.setdefault(
            key,
            {
                "condition_id": key[0],
                "outcome_id": key[1],
                "event_slug": str(fill.get("event_slug") or ""),
                "market_slug": str(fill.get("market_slug") or ""),
                "title": str(fill.get("market_title") or ""),
                "outcome": str(fill.get("outcome") or ""),
                "buy_cost": 0.0,
                "buy_shares": 0.0,
                "sell_shares": 0.0,
                "fills": 0,
                "first_timestamp": int(fill["timestamp"]),
                "last_timestamp": int(fill["timestamp"]),
            },
        )
        shares = number(fill["shares"])
        if str(fill.get("side") or "").upper() == "SELL":
            position["sell_shares"] += shares
        else:
            position["buy_cost"] += number(fill["usd_amount"])
            position["buy_shares"] += shares
        position["fills"] += 1
        position["first_timestamp"] = min(position["first_timestamp"], int(fill["timestamp"]))
        position["last_timestamp"] = max(position["last_timestamp"], int(fill["timestamp"]))

    by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for position in positions.values():
        average_entry = position["buy_cost"] / position["buy_shares"] if position["buy_shares"] else 0.0
        remaining_shares = max(0.0, position["buy_shares"] - position["sell_shares"])
        position["remaining_cost"] = remaining_shares * average_entry
        by_condition[str(position["condition_id"])].append(position)

    markets: list[dict[str, Any]] = []
    for condition_id, outcomes in by_condition.items():
        ordered = sorted(outcomes, key=lambda row: number(row["remaining_cost"]), reverse=True)
        leader = number(ordered[0]["remaining_cost"]) if ordered else 0.0
        opposition = sum(number(row["remaining_cost"]) for row in ordered[1:])
        ratio = opposition / leader if leader else 0.0
        status = "CLEAN_DIRECTIONAL" if ratio < 0.10 else "MINOR_HEDGE" if ratio <= 0.20 else "MATERIAL_HEDGE" if ratio <= 0.50 else "TWO_SIDED"
        sample = outcomes[0]
        markets.append(
            {
                "condition_id": condition_id,
                "event_slug": sample["event_slug"],
                "sport": classify_sport(sample),
                "market_type": classify_market(sample),
                "direction_status": status,
                "opposing_ratio": ratio,
                "gross_remaining_cost_usd": leader + opposition,
                "net_directional_cost_usd": max(0.0, leader - opposition),
                "fill_count": sum(int(row["fills"]) for row in outcomes),
                "first_timestamp": min(int(row["first_timestamp"]) for row in outcomes),
                "last_timestamp": max(int(row["last_timestamp"]) for row in outcomes),
            }
        )
    return markets


def aggregate_closed(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = str(row.get("conditionId") or row.get("asset") or "").lower()
        if key:
            grouped[key].append(row)
    markets: list[dict[str, Any]] = []
    for condition_id, items in grouped.items():
        risked = sum(number(row.get("initialValue")) or number(row.get("totalBought")) * number(row.get("avgPrice")) for row in items)
        pnl = sum(number(row.get("realizedPnl")) for row in items)
        sample = items[0]
        markets.append(
            {
                "condition_id": condition_id,
                "title": str(sample.get("title") or ""),
                "event_slug": str(sample.get("eventSlug") or ""),
                "sport": classify_sport(sample),
                "market_type": classify_market(sample),
                "cost_usd": risked,
                "pnl_usd": pnl,
                "timestamp": max(int(row.get("timestamp") or 0) for row in items),
            }
        )
    return markets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("trades", type=Path)
    parser.add_argument("--address", required=True)
    parser.add_argument("--closed-source", type=Path)
    parser.add_argument("--validated-tennis-report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    raw = load_array(args.trades)
    address = args.address.lower()
    wrong_wallet = sum(str(row.get("proxyWallet") or "").lower() != address for row in raw)
    fills, duplicates = normalize_trade_fills(address, raw)
    markets = aggregate_fills(fills)
    timestamps = sorted(int(fill["timestamp"]) for fill in fills)
    gaps = [right - left for left, right in zip(timestamps, timestamps[1:])]
    days = Counter(datetime.fromtimestamp(ts, ET).date().isoformat() for ts in timestamps)
    hours = Counter(datetime.fromtimestamp(ts, ET).hour for ts in timestamps)

    sports = sorted({str(market["sport"]) for market in markets})
    sport_activity: dict[str, Any] = {}
    unit_analysis: dict[str, Any] = {}
    for sport in sports:
        sport_fills = [fill for fill in fills if classify_sport(fill) == sport]
        sport_markets = [market for market in markets if market["sport"] == sport]
        clean_sizes = [number(market["net_directional_cost_usd"]) for market in sport_markets if market["direction_status"] == "CLEAN_DIRECTIONAL" and number(market["net_directional_cost_usd"]) >= 100]
        estimate = estimate_unit_size(address, "Bagwell306", clean_sizes)
        counts = Counter(str(market["direction_status"]) for market in sport_markets)
        sport_activity[sport] = {
            "fills": len(sport_fills),
            "notional_usd": sum(number(fill["usd_amount"]) for fill in sport_fills),
            "events": len({str(fill.get("event_slug") or "") for fill in sport_fills}),
            "exact_markets": len(sport_markets),
            "market_types": dict(Counter(str(market["market_type"]) for market in sport_markets)),
            "direction_status": dict(counts),
            "clean_directional_rate": counts.get("CLEAN_DIRECTIONAL", 0) / len(sport_markets) if sport_markets else None,
        }
        unit_analysis[sport] = {
            "estimated_base_unit_usd": estimate.estimated_base_unit,
            "confidence": estimate.confidence,
            "matched_samples": estimate.matched_samples,
            "clean_sample": len(clean_sizes),
            "p25_usd": percentile(clean_sizes, 0.25),
            "median_usd": percentile(clean_sizes, 0.50),
            "p75_usd": percentile(clean_sizes, 0.75),
            "p90_usd": percentile(clean_sizes, 0.90),
        }

    closed_rows = load_array(args.closed_source) if args.closed_source else []
    closed_markets = aggregate_closed(closed_rows)
    settled_by_sport = {
        sport: performance([market for market in closed_markets if market["sport"] == sport])
        for sport in sorted({str(market["sport"]) for market in closed_markets})
    }
    latest_settled_ts = max((int(market["timestamp"]) for market in closed_markets), default=0)
    recent = {}
    for window in (30, 60, 90):
        cutoff = latest_settled_ts - int(timedelta(days=window).total_seconds())
        recent[f"trailing_{window}d"] = performance([market for market in closed_markets if int(market["timestamp"]) >= cutoff])

    validated = None
    tennis_segments = None
    if args.validated_tennis_report and args.validated_tennis_report.exists():
        validated = json.loads(args.validated_tennis_report.read_text(encoding="utf-8"))
        plays = [row for row in validated.get("plays", []) if isinstance(row, dict)]
        play_dates = [datetime.fromisoformat(str(row["date"])).date() for row in plays if row.get("date")]
        last_play_date = max(play_dates) if play_dates else None
        filtered = [
            row for row in plays
            if number(row.get("relative_wallet_units")) >= 1
            and number(row.get("entry_price")) >= 0.35
        ]
        tennis_segments = {
            "entry_price": {
                "below_0.35": copy_performance([row for row in plays if number(row.get("entry_price")) < 0.35]),
                "0.35_to_0.49": copy_performance([row for row in plays if 0.35 <= number(row.get("entry_price")) < 0.50]),
                "0.50_to_0.64": copy_performance([row for row in plays if 0.50 <= number(row.get("entry_price")) < 0.65]),
            },
            "wallet_conviction": {
                "0.5_to_0.99_units": copy_performance([row for row in plays if 0.5 <= number(row.get("relative_wallet_units")) < 1]),
                "1_to_1.99_units": copy_performance([row for row in plays if 1 <= number(row.get("relative_wallet_units")) < 2]),
                "2_plus_units": copy_performance([row for row in plays if number(row.get("relative_wallet_units")) >= 2]),
            },
            "latest_fill_timing": {
                "30_to_120_minutes": copy_performance([row for row in plays if 30 < number(row.get("last_fill_minutes_before_start")) <= 120]),
                "over_120_minutes": copy_performance([row for row in plays if number(row.get("last_fill_minutes_before_start")) > 120]),
            },
            "exploratory_combined_filter": {
                "rule": "At least 1.0 measured Bagwell unit and entry price at least 0.35.",
                "all_available": copy_performance(filtered),
                "trailing_60d": copy_performance([
                    row for row in filtered
                    if last_play_date and (last_play_date - datetime.fromisoformat(str(row["date"])).date()).days < 60
                ]),
                "trailing_30d": copy_performance([
                    row for row in filtered
                    if last_play_date and (last_play_date - datetime.fromisoformat(str(row["date"])).date()).days < 30
                ]),
                "validation_status": "IN_SAMPLE_EXPLORATORY_FILTER",
            },
        }

    status_counts = Counter(str(market["direction_status"]) for market in markets)
    report = {
        "identity": {"address": address, "name": "Bagwell306", "pseudonym": "Youthful-Mug"},
        "data_quality": {
            "source_file": str(args.trades),
            "raw_rows": len(raw),
            "normalized_fills": len(fills),
            "duplicate_fills": duplicates,
            "wrong_wallet_rows": wrong_wallet,
            "transaction_hashes": len({str(row.get("transactionHash") or "") for row in raw}),
            "contains_realized_pnl": any(row.get("realizedPnl") is not None for row in raw),
            "settled_snapshot_file": str(args.closed_source) if args.closed_source else None,
            "settled_snapshot_rows": len(closed_rows),
            "settled_snapshot_as_of_utc": datetime.fromtimestamp(latest_settled_ts, timezone.utc).isoformat() if latest_settled_ts else None,
        },
        "coverage": {
            "start_et": datetime.fromtimestamp(min(timestamps), ET).isoformat() if timestamps else None,
            "end_et": datetime.fromtimestamp(max(timestamps), ET).isoformat() if timestamps else None,
            "calendar_days": (datetime.fromtimestamp(max(timestamps), ET).date() - datetime.fromtimestamp(min(timestamps), ET).date()).days + 1 if timestamps else 0,
            "active_days": len(days),
            "events": len({str(fill.get("event_slug") or "") for fill in fills}),
            "exact_markets": len(markets),
            "fills": len(fills),
            "buy_fills": sum(str(fill.get("side") or "").upper() == "BUY" for fill in fills),
            "sell_fills": sum(str(fill.get("side") or "").upper() == "SELL" for fill in fills),
            "total_notional_usd": sum(number(fill["usd_amount"]) for fill in fills),
        },
        "portfolio_activity_by_sport": sport_activity,
        "directionality": {
            "market_counts": dict(status_counts),
            "clean_directional_rate": status_counts.get("CLEAN_DIRECTIONAL", 0) / len(markets) if markets else None,
            "markets_with_both_outcomes": sum(number(market["opposing_ratio"]) > 0 for market in markets),
        },
        "execution_behavior": {
            "median_fills_per_active_day": statistics.median(days.values()) if days else None,
            "p90_fills_per_active_day": percentile(list(days.values()), 0.90),
            "median_interfill_seconds": statistics.median(gaps) if gaps else None,
            "fills_within_one_second_rate": sum(gap <= 1 for gap in gaps) / len(gaps) if gaps else None,
            "fills_within_ten_seconds_rate": sum(gap <= 10 for gap in gaps) / len(gaps) if gaps else None,
            "fill_hour_distribution_et": {str(hour): count for hour, count in sorted(hours.items())},
        },
        "unit_analysis_by_sport": unit_analysis,
        "settled_snapshot_performance": {
            "overall": performance(closed_markets),
            "by_sport": settled_by_sport,
            "recent_windows_relative_to_snapshot": recent,
            "best_markets": sorted(closed_markets, key=lambda row: number(row["pnl_usd"]), reverse=True)[:10],
            "worst_markets": sorted(closed_markets, key=lambda row: number(row["pnl_usd"]))[:10],
        },
        "validated_tennis_copy_analysis": validated,
        "derived_tennis_copy_segments": tennis_segments,
        "model_assessment": {
            "recommended_tennis_role": "CONDITIONAL_ORIGINATOR",
            "measured_tennis_unit_usd": number(validated.get("estimated_wallet_base_unit_usd")) if validated else None,
            "recommended_minimum_directional_threshold_usd": number(validated.get("estimated_wallet_base_unit_usd")) if validated else None,
            "legacy_validated_minimum_threshold_usd": 0.5 * number(validated.get("estimated_wallet_base_unit_usd")) if validated else None,
            "recommended_entry_price_floor": 0.35,
            "requirements": [
                "Net exact fills and opposing event-level tennis markets before qualification.",
                "Reject opposing exposure of 10% or more.",
                "Use only resolved full-match main moneyline, spread, and total markets.",
                "Require at least 1.0 measured Bagwell unit and treat prices below 0.35 as non-originating research signals.",
                "Require ongoing forward validation because the trailing 30- and 60-day copy samples deteriorated.",
            ],
            "not_recommended": "Unfiltered tailing of every Bagwell fill or use as an unrestricted standalone lead.",
        },
        "limitations": {
            "attached_export_is_trade_fills_not_settlement_ledger": True,
            "settled_snapshot_is_older_than_trade_export": bool(latest_settled_ts and timestamps and latest_settled_ts < max(timestamps)),
            "settled_endpoint_snapshot_may_be_api_capped": len(closed_rows) == 1600,
            "settled_snapshot_positive_row_rate": sum(number(row.get("realizedPnl")) > 0 for row in closed_rows) / len(closed_rows) if closed_rows else None,
            "settled_snapshot_roi_trust": "NOT_SUITABLE_AS_TRUE_WALLET_ROI" if len(closed_rows) == 1600 else "REVIEW_REQUIRED",
            "settled_snapshot_roi_reason": "The API-capped snapshot is strongly winner-skewed and does not establish complete losing-position coverage.",
            "live_api_status": "Rate limited during 2026-08-08 reconciliation; no live-only metric is represented as complete.",
            "copy_analysis_note": "Copy-strategy ROI is a prospective rules simulation and must not be confused with wallet realized ROI.",
        },
        "generated_at_et": datetime.now(ET).isoformat(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
