from __future__ import annotations

import json
import math
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


OUTPUTS = ROOT / "outputs"
PATHS = 5_000
HORIZONS = (7, 30, 60)
CHECKPOINT_SECONDS = 30 * 60
COMMON_START = date(2026, 6, 22)
COMMON_END = date(2026, 8, 4)

BAGWELL_REPORT = OUTPUTS / "bagwell306-full-forensics-2026-08-08.json"
LILY_RAW = Path(r"C:\Users\15617\Downloads\api-response (30).json")
OUTPUT = OUTPUTS / "bagwell-lilybaeum-tennis-5000-comparison-2026-08-08.json"
LILY_EVENTS = OUTPUTS / "lilybaeum-tennis-events-independent-2026-08-08.json"


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def parse_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(str(value or "[]"))
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def parse_time(value: Any) -> int | None:
    if not value:
        return None
    text = str(value).strip().replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    except ValueError:
        return None


def is_tennis_slug(value: Any) -> bool:
    slug = str(value or "").lower()
    return slug.startswith(("atp-", "wta-", "itf-", "utr-", "challenger-", "tennis-"))


def strictly_resolved_market(row: dict[str, Any]) -> dict[str, Any] | None:
    condition = str(row.get("conditionId") or "").lower()
    start = parse_time(row.get("gameStartTime"))
    outcomes = [str(item) for item in parse_list(row.get("outcomes"))]
    prices = [number(item) for item in parse_list(row.get("outcomePrices"))]
    question = str(row.get("question") or "")
    slug = str(row.get("slug") or "")
    kind = str(row.get("sportsMarketType") or "").lower()
    lower = f"{question} {slug}".lower()
    if not condition or not start or len(outcomes) != len(prices):
        return None
    if "first set" in lower or "set-1" in lower or "first-set" in lower:
        return None
    valid_kind = kind in {
        "moneyline",
        "tennis_moneyline",
        "tennis_set_handicap",
        "tennis_match_totals",
    }
    if not valid_kind:
        return None
    if not bool(row.get("closed")) or prices.count(1.0) != 1 or any(price not in {0.0, 1.0} for price in prices):
        return None
    winner = outcomes[prices.index(1.0)]
    family = (
        "Moneyline"
        if kind in {"moneyline", "tennis_moneyline"}
        else "Spread"
        if kind == "tennis_set_handicap"
        else "Total"
    )
    return {
        "condition_id": condition,
        "start": start,
        "winner": winner,
        "title": question,
        "market_type": family,
        "event_slug": str((row.get("events") or [{}])[0].get("slug") or slug),
    }


def load_lily_metadata(event_slugs: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    selected: dict[str, dict[str, Any]] = {}
    cached: dict[str, dict[str, Any] | None] = {}
    if LILY_EVENTS.exists():
        payload = json.loads(LILY_EVENTS.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            cached = payload
    missing = [slug for slug in sorted(set(event_slugs)) if slug not in cached]
    if missing:
        fetched = PolymarketClient(request_timeout=20, max_retries=5).get_events(missing, max_workers=6)
        cached.update(fetched)
        LILY_EVENTS.write_text(json.dumps(cached), encoding="utf-8")
    raw_rows = 0
    for event in cached.values():
        if not isinstance(event, dict):
            continue
        for row in event.get("markets") or []:
            raw_rows += 1
            if not isinstance(row, dict):
                continue
            market = strictly_resolved_market(row)
            if market:
                selected[market["condition_id"]] = market
    return selected, {
        "independent_event_slugs_requested": len(set(event_slugs)),
        "independent_events_found": sum(isinstance(event, dict) for event in cached.values()),
        "independent_events_missing": sum(event is None for event in cached.values()),
        "metadata_rows": raw_rows,
        "strictly_resolved_main_markets": len(selected),
    }


def load_lily_plays() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw = json.loads(LILY_RAW.read_text(encoding="utf-8-sig"))
    rows = [row for row in raw if isinstance(row, dict)]
    tennis = [row for row in rows if is_tennis_slug(row.get("eventSlug") or row.get("slug"))]
    event_slugs = [str(row.get("eventSlug") or "") for row in tennis if row.get("eventSlug")]
    metadata, audit = load_lily_metadata(event_slugs)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in tennis:
        condition = str(row.get("conditionId") or "").lower()
        grouped[condition].append(row)

    exclusions: defaultdict[str, int] = defaultdict(int)
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
        shares: dict[str, float] = defaultdict(float)
        last_price: dict[str, float] = {}
        for row in eligible:
            outcome = str(row.get("outcome") or "")
            fill_shares = number(row.get("size"))
            price = number(row.get("price"))
            multiplier = -1.0 if str(row.get("side") or "BUY").upper() == "SELL" else 1.0
            costs[outcome] += multiplier * fill_shares * price
            shares[outcome] += multiplier * fill_shares
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
        if net_cost < 575.0:
            exclusions["below_one_measured_unit"] += 1
            continue
        if entry_price < 0.35:
            exclusions["entry_below_35c"] += 1
            continue
        if not 0.01 < entry_price < 0.99:
            exclusions["invalid_entry_price"] += 1
            continue
        plays.append(
            {
                **market,
                "wallet": "Lilybaeum",
                "date": datetime.fromtimestamp(int(market["start"]), timezone.utc).date().isoformat(),
                "selection": leader,
                "entry_price": entry_price,
                "won": leader == market["winner"],
                "wallet_units": net_cost / 575.0,
                "opposing_ratio": opposing_ratio,
                "stake_units": 1.0,
            }
        )
    audit.update(
        {
            "raw_export_rows": len(rows),
            "tennis_fill_rows": len(tennis),
            "tennis_conditions": len(grouped),
            "qualified_plays": len(plays),
            "exclusions": dict(exclusions),
        }
    )
    return sorted(plays, key=lambda row: (row["start"], row["condition_id"])), audit


def load_bagwell_plays() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    report = json.loads(BAGWELL_REPORT.read_text(encoding="utf-8"))
    candidates = report["validated_tennis_copy_analysis"]["plays"]
    plays: list[dict[str, Any]] = []
    exclusions: defaultdict[str, int] = defaultdict(int)
    for row in candidates:
        if number(row.get("relative_wallet_units")) < 1.0:
            exclusions["below_one_measured_unit"] += 1
            continue
        if number(row.get("entry_price")) < 0.35:
            exclusions["entry_below_35c"] += 1
            continue
        plays.append({**row, "wallet": "Bagwell306", "wallet_units": row["relative_wallet_units"], "stake_units": 1.0})
    return plays, {
        "source_candidate_plays": len(candidates),
        "qualified_plays": len(plays),
        "exclusions": dict(exclusions),
        "source_audit": report["validated_tennis_copy_analysis"]["source_audit"],
    }


def play_return(play: dict[str, Any]) -> float:
    price = number(play["entry_price"])
    return (1.0 - price) / price if play["won"] else -1.0


def actual_summary(plays: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(plays, key=lambda row: (row["start"], row["condition_id"]))
    profit = 0.0
    stake = 0.0
    peak = 0.0
    drawdown = 0.0
    wins = 0
    for play in ordered:
        units = number(play.get("stake_units") or 1.0)
        profit += units * play_return(play)
        stake += units
        wins += int(bool(play["won"]))
        peak = max(peak, profit)
        drawdown = max(drawdown, peak - profit)
    first_day = date.fromisoformat(ordered[0]["date"]) if ordered else None
    last_day = date.fromisoformat(ordered[-1]["date"]) if ordered else None
    calendar_days = (last_day - first_day).days + 1 if first_day and last_day else 0
    return {
        "bets": len(ordered),
        "wins": wins,
        "losses": len(ordered) - wins,
        "hit_rate": wins / len(ordered) if ordered else None,
        "staked_units": round(stake, 5),
        "profit_units": round(profit, 5),
        "roi": round(profit / stake, 6) if stake else None,
        "max_drawdown_units": round(drawdown, 5),
        "first_play_date": first_day.isoformat() if first_day else None,
        "last_play_date": last_day.isoformat() if last_day else None,
        "plays_per_calendar_day": round(len(ordered) / calendar_days, 4) if calendar_days else None,
    }


def common_window(plays: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [play for play in plays if COMMON_START.isoformat() <= play["date"] <= COMMON_END.isoformat()]


def combine_plays(bagwell: list[dict[str, Any]], lily: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for play in bagwell + lily:
        grouped[play["condition_id"]].append(play)
    combined: list[dict[str, Any]] = []
    structure: defaultdict[str, int] = defaultdict(int)
    for condition, rows in grouped.items():
        if len(rows) == 1:
            combined.append({**rows[0], "wallet": "Combined", "agreement": "one_sharp", "stake_units": 1.0})
            structure["one_sharp"] += 1
            continue
        selections = {row["selection"] for row in rows}
        if len(selections) > 1:
            structure["direct_conflict_skipped"] += 1
            continue
        # Same-side agreement is one event, but represents two independent 1u sharp votes.
        conservative_entry = max(number(row["entry_price"]) for row in rows)
        leader = rows[0]
        combined.append(
            {
                **leader,
                "wallet": "Combined",
                "agreement": "two_sharp_agreement",
                "entry_price": conservative_entry,
                "stake_units": 2.0,
            }
        )
        structure["two_sharp_agreement"] += 1
    return sorted(combined, key=lambda row: (row["start"], row["condition_id"])), dict(structure)


def percentile_summary(values: np.ndarray) -> dict[str, float]:
    return {
        "minimum": float(np.min(values)),
        "p05": float(np.quantile(values, 0.05)),
        "median": float(np.median(values)),
        "mean": float(np.mean(values)),
        "p95": float(np.quantile(values, 0.95)),
        "maximum": float(np.max(values)),
    }


def simulate(plays: list[dict[str, Any]], horizon: int, seed: int) -> dict[str, Any]:
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for play in plays:
        by_day[play["date"]].append(play)
    blocks = [
        sorted(by_day[(COMMON_START + timedelta(days=index)).isoformat()], key=lambda row: (row["start"], row["condition_id"]))
        for index in range((COMMON_END - COMMON_START).days + 1)
    ]
    rng = np.random.default_rng(seed)
    profit = np.zeros(PATHS)
    stake = np.zeros(PATHS)
    bets = np.zeros(PATHS)
    wins = np.zeros(PATHS)
    max_drawdown = np.zeros(PATHS)
    for path in range(PATHS):
        equity = 0.0
        peak = 0.0
        sampled = rng.integers(0, len(blocks), size=horizon)
        for block_index in sampled:
            for play in blocks[int(block_index)]:
                units = number(play.get("stake_units") or 1.0)
                result = units * play_return(play)
                equity += result
                profit[path] += result
                stake[path] += units
                bets[path] += 1
                wins[path] += int(bool(play["won"]))
                peak = max(peak, equity)
                max_drawdown[path] = max(max_drawdown[path], peak - equity)
    losses = bets - wins
    roi = np.divide(profit, stake, out=np.zeros_like(profit), where=stake > 0)
    hit_rate = np.divide(wins, bets, out=np.zeros_like(wins), where=bets > 0)
    return {
        "bets": percentile_summary(bets),
        "wins": percentile_summary(wins),
        "losses": percentile_summary(losses),
        "hit_rate": percentile_summary(hit_rate),
        "profit_units": percentile_summary(profit),
        "roi": percentile_summary(roi),
        "max_drawdown_units": percentile_summary(max_drawdown),
        "probability_profitable": float(np.mean(profit > 0)),
        "probability_no_bets": float(np.mean(bets == 0)),
    }


def main() -> None:
    bagwell_all, bagwell_audit = load_bagwell_plays()
    lily_all, lily_audit = load_lily_plays()
    bagwell = common_window(bagwell_all)
    lily = common_window(lily_all)
    combined, structure = combine_plays(bagwell, lily)
    strategies = {"Bagwell306": bagwell, "Lilybaeum": lily, "Combined": combined}
    report = {
        "title": "Bagwell306 vs Lilybaeum tennis: 5,000-path comparison",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "methodology": {
            "paths_per_horizon": PATHS,
            "horizons_days": list(HORIZONS),
            "historical_bootstrap_window": {"start": COMMON_START.isoformat(), "end": COMMON_END.isoformat()},
            "sampling": "Empirical daily block bootstrap with replacement; preserves same-day signal clustering.",
            "qualification": "Strictly resolved full-match main tennis markets; position visible 30m before start; net directional exposure >=1 measured wallet unit; opposing exposure <10%; entry >=35c.",
            "sizing": "Flat 1u per standalone qualified signal. Same-side agreement is one event with 2u. Direct conflicts are skipped.",
            "entry_proxy": "Last observed wallet fill price on the dominant outcome by the 30-minute checkpoint; not guaranteed executable copy price.",
            "important": "This is a resampled historical copy-strategy simulation, not a prediction of guaranteed future returns.",
        },
        "wallet_units_usd": {"Bagwell306": 875.0, "Lilybaeum": 575.0},
        "source_audit": {"Bagwell306": bagwell_audit, "Lilybaeum": lily_audit},
        "full_available_qualified_history": {
            "Bagwell306": actual_summary(bagwell_all),
            "Lilybaeum": actual_summary(lily_all),
        },
        "common_window_actual": {name: actual_summary(plays) for name, plays in strategies.items()},
        "combined_structure": structure,
        "simulations": {
            name: {str(days): simulate(plays, days, seed=20260808 + index * 100 + days) for days in HORIZONS}
            for index, (name, plays) in enumerate(strategies.items())
        },
        "qualified_play_ledgers": strategies,
    }
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "qualified_play_ledgers"}, indent=2))
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
