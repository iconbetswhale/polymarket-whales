from __future__ import annotations

import json
import statistics
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
from unit_analysis import estimate_unit_size
from wallet_activity import normalize_trade_fills

from simulate_bagwell_tennis_full_export import (
    ADDRESS,
    AS_OF,
    CHECKPOINT_SECONDS,
    LABEL,
    MINIMUM_WALLET_UNITS,
    PATHS,
    SOURCE,
    conviction_multiplier,
    number,
    parse_json_list,
    parse_time,
    state_at_checkpoint,
    stat,
)


EVENTS = ROOT / "outputs" / "bagwell306-kbo-wnba-events-full-export-2026-08-05.json"
OUTPUT = ROOT / "outputs" / "bagwell306-kbo-wnba-full-export-2026-08-05.json"


def sport_for_slug(slug: str) -> str | None:
    lower = slug.lower()
    if lower.startswith("wnba-"):
        return "WNBA"
    if lower.startswith("kbo-"):
        return "KBO"
    return None


def load_fills() -> dict[str, list[dict[str, Any]]]:
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    raw = payload if isinstance(payload, list) else payload.get("data", [])
    fills, duplicates = normalize_trade_fills(ADDRESS, raw)
    if duplicates:
        raise RuntimeError(f"Unexpected duplicate fills: {duplicates}")
    result: dict[str, list[dict[str, Any]]] = {"KBO": [], "WNBA": []}
    for fill in fills:
        sport = sport_for_slug(str(fill.get("event_slug") or ""))
        if sport:
            result[sport].append(fill)
    return result


def load_events(client: PolymarketClient, slugs: list[str]) -> dict[str, dict[str, Any]]:
    cached: dict[str, dict[str, Any]] = {}
    if EVENTS.exists():
        cached = json.loads(EVENTS.read_text(encoding="utf-8"))
    missing = [slug for slug in slugs if slug not in cached]
    if missing:
        fetched = client.get_events(missing, max_workers=4)
        cached.update({slug: event for slug, event in fetched.items() if event})
        EVENTS.write_text(json.dumps(cached), encoding="utf-8")
    return {slug: cached.get(slug) for slug in slugs if cached.get(slug)}


def classify_market(market: dict[str, Any]) -> str | None:
    kind = str(market.get("sportsMarketType") or "").lower()
    if kind == "moneyline":
        return "Moneyline"
    if kind == "spreads":
        return "Spread"
    if kind == "totals":
        return "Total"
    return None


def main_market_map(events: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for event_slug, event in events.items():
        families: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for market in event.get("markets") or []:
            if isinstance(market, dict):
                family = classify_market(market)
                if family:
                    families[family].append(market)
        for family, markets in families.items():
            market = max(markets, key=lambda row: number(row.get("volumeNum") or row.get("volume")))
            condition = str(market.get("conditionId") or "").lower()
            start = parse_time(market.get("gameStartTime"))
            outcomes = [str(value) for value in parse_json_list(market.get("outcomes"))]
            prices = [number(value) for value in parse_json_list(market.get("outcomePrices"))]
            resolution = dict(zip(outcomes, prices)) if len(outcomes) == len(prices) else {}
            strictly_resolved = (
                bool(market.get("closed"))
                and len(resolution) >= 2
                and sum(value == 1.0 for value in resolution.values()) == 1
                and all(value in {0.0, 1.0} for value in resolution.values())
            )
            if condition and start:
                selected[condition] = {
                    "event_slug": event_slug,
                    "market_type": family,
                    "start": start,
                    "title": str(event.get("title") or market.get("question") or ""),
                    "resolution": resolution if strictly_resolved else {},
                }
    return selected


def snapshots(fills: list[dict[str, Any]], markets: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fill in fills:
        if fill["condition_id"] in markets:
            grouped[fill["condition_id"]].append(fill)
    candidates: list[dict[str, Any]] = []
    excluded: defaultdict[str, int] = defaultdict(int)
    for condition, rows in grouped.items():
        market = markets[condition]
        checkpoint = int(market["start"]) - CHECKPOINT_SECONDS
        state = state_at_checkpoint(rows, checkpoint)
        active = {outcome: data for outcome, data in state.items() if data["shares"] > 1e-8}
        if not active:
            excluded["no_position_30m_prestart"] += 1
            continue
        ordered = sorted(active.items(), key=lambda item: item[1]["cost"], reverse=True)
        leader, leader_state = ordered[0]
        leader_cost = leader_state["cost"]
        opposing = sum(data["cost"] for _, data in ordered[1:])
        if leader_cost <= 0 or opposing / leader_cost >= 0.10:
            excluded["contradictory_position"] += 1
            continue
        resolution = market.get("resolution") or {}
        if leader not in resolution:
            excluded["unresolved_or_missing_resolution"] += 1
            continue
        entry = leader_state["last_price"]
        if not 0.01 < entry < 0.99:
            excluded["invalid_entry_price"] += 1
            continue
        candidates.append(
            {
                **{key: value for key, value in market.items() if key != "resolution"},
                "condition_id": condition,
                "date": datetime.fromtimestamp(int(market["start"]), timezone.utc).date().isoformat(),
                "selection": leader,
                "entry_price": entry,
                "won": resolution[leader] == 1.0,
                "net_exposure_usd": leader_cost - opposing,
            }
        )
    return candidates, dict(excluded)


def summarize(plays: list[dict[str, Any]]) -> dict[str, Any]:
    wins = sum(int(play["won"]) for play in plays)
    stake = sum(play["stake_units"] for play in plays)
    profit = sum(
        play["stake_units"] * (((1 - play["entry_price"]) / play["entry_price"]) if play["won"] else -1)
        for play in plays
    )
    return {
        "bets": len(plays),
        "record": f"{wins}-{len(plays) - wins}",
        "hit_rate": wins / len(plays) if plays else None,
        "profit_units": profit,
        "roi": profit / stake if stake else None,
        "average_stake_units": statistics.mean(play["stake_units"] for play in plays) if plays else None,
        "by_market": {
            family: {
                "bets": sum(play["market_type"] == family for play in plays),
                "wins": sum(play["market_type"] == family and play["won"] for play in plays),
            }
            for family in ("Moneyline", "Spread", "Total")
        },
    }


def simulate(plays: list[dict[str, Any]], days: int, history_start: date, seed: int) -> dict[str, Any]:
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for play in plays:
        by_day[play["date"]].append(play)
    blocks = [
        by_day[(history_start + timedelta(days=index)).isoformat()]
        for index in range((AS_OF - history_start).days + 1)
    ]
    rng = np.random.default_rng(seed)
    bets = np.zeros(PATHS)
    wins = np.zeros(PATHS)
    profit = np.zeros(PATHS)
    stake = np.zeros(PATHS)
    drawdown = np.zeros(PATHS)
    upside = np.zeros(PATHS)
    for path in range(PATHS):
        equity = 0.0
        peak = 0.0
        for block_index in rng.integers(0, len(blocks), size=days):
            for play in blocks[int(block_index)]:
                units = float(play["stake_units"])
                result = ((1 - play["entry_price"]) / play["entry_price"]) if play["won"] else -1.0
                pnl = units * result
                bets[path] += 1
                wins[path] += int(play["won"])
                stake[path] += units
                profit[path] += pnl
                equity += pnl
                peak = max(peak, equity)
                upside[path] = max(upside[path], equity)
                drawdown[path] = max(drawdown[path], peak - equity)
    hit = np.divide(wins, bets, out=np.full_like(wins, np.nan), where=bets > 0)
    roi = np.divide(profit, stake, out=np.full_like(profit, np.nan), where=stake > 0)
    return {
        "bets": stat(bets),
        "hit_rate": stat(hit[~np.isnan(hit)]) if np.any(~np.isnan(hit)) else None,
        "profit_units": stat(profit),
        "roi": stat(roi[~np.isnan(roi)]) if np.any(~np.isnan(roi)) else None,
        "max_drawdown_units": {**stat(drawdown), "worst_observed": float(np.max(drawdown))},
        "max_upside_units": {**stat(upside), "best_observed": float(np.max(upside))},
        "probability_profitable": float(np.mean(profit > 0)),
        "probability_no_bets": float(np.mean(bets == 0)),
    }


def analyze_sport(
    sport: str, fills: list[dict[str, Any]], markets: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    candidates, exclusions = snapshots(fills, markets)
    samples = [row["net_exposure_usd"] for row in candidates if row["net_exposure_usd"] >= 25]
    estimate = estimate_unit_size(ADDRESS, f"{LABEL} {sport}", samples)
    if not estimate.estimated_base_unit:
        return {
            "source_fills": len(fills),
            "candidate_snapshots": len(candidates),
            "unit_estimate": None,
            "unit_confidence": "insufficient",
            "exclusions": exclusions,
            "actual": summarize([]),
            "simulations": None,
        }
    plays: list[dict[str, Any]] = []
    for row in candidates:
        relative = row["net_exposure_usd"] / estimate.estimated_base_unit
        if relative < MINIMUM_WALLET_UNITS:
            exclusions["below_half_wallet_unit"] = exclusions.get("below_half_wallet_unit", 0) + 1
            continue
        plays.append({**row, "relative_wallet_units": relative, "stake_units": conviction_multiplier(relative)})
    plays.sort(key=lambda row: (row["start"], row["condition_id"]))
    first = min((date.fromisoformat(play["date"]) for play in plays), default=AS_OF)
    history_start = max(first, AS_OF - timedelta(days=59))
    trailing = [play for play in plays if history_start <= date.fromisoformat(play["date"]) <= AS_OF]
    return {
        "source_fills": len(fills),
        "candidate_snapshots": len(candidates),
        "unit_estimate_usd": estimate.estimated_base_unit,
        "unit_confidence": estimate.confidence,
        "unit_samples": estimate.sample_size,
        "exclusions": exclusions,
        "actual_all_available": summarize(plays),
        "actual_trailing_simulation_window": summarize(trailing),
        "simulation_history_start": history_start.isoformat(),
        "simulations": {
            str(days): simulate(trailing, days, history_start, 306_500 + days + (1 if sport == "KBO" else 2))
            for days in (7, 30, 60)
        },
        "plays": plays,
    }


def main() -> None:
    fills_by_sport = load_fills()
    slugs = sorted({fill["event_slug"] for fills in fills_by_sport.values() for fill in fills})
    events = load_events(PolymarketClient(max_retries=5), slugs)
    markets = main_market_map(events)
    payload = {
        "title": "Bagwell306 KBO and WNBA full-export analysis",
        "as_of": AS_OF.isoformat(),
        "paths_per_horizon": PATHS,
        "rule": "Main moneyline/spread/total only; net position at 30 minutes prestart; opposing exposure >=10% excluded; minimum 0.5 sport-specific Bagwell units; 1.00u-1.55u copy sizing.",
        "sports": {
            sport: analyze_sport(sport, fills, markets)
            for sport, fills in fills_by_sport.items()
        },
        "warning": "KBO and WNBA samples are extremely small. Their bootstrap distributions repeat a handful of observed games and are not reliable evidence of a durable edge.",
    }
    OUTPUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    compact = json.loads(json.dumps(payload))
    for sport in compact["sports"].values():
        sport.pop("plays", None)
    print(json.dumps(compact, indent=2))


if __name__ == "__main__":
    main()
