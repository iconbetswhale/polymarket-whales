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


ADDRESS = "0x9c76cdb43fb46454da005fbc82047a64a18ec926"
LABEL = "Bagwell306"
AS_OF = date(2026, 8, 5)
HISTORY_START = AS_OF - timedelta(days=59)
PATHS = 5_000
MINIMUM_WALLET_UNITS = 0.50
CHECKPOINT_SECONDS = 30 * 60
SOURCE = ROOT / "outputs" / "bagwell306-closed-source-2026-08-05.json"
EVENTS = ROOT / "outputs" / "bagwell306-tennis-events-2026-08-05.json"
TRADES = ROOT / "outputs" / "bagwell306-tennis-trades-2026-08-05.json"
OUTPUT = ROOT / "outputs" / "bagwell306-tennis-5000-validated-2026-08-05.json"


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


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


def is_tennis(row: dict[str, Any]) -> bool:
    slug = str(row.get("eventSlug") or row.get("slug") or "").lower()
    return slug.startswith(("atp-", "wta-", "itf-", "utr-", "challenger-"))


def load_closed() -> list[dict[str, Any]]:
    if not SOURCE.exists():
        raise RuntimeError(f"Missing cached closed-position source: {SOURCE}")
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    return [row for row in payload if isinstance(row, dict) and is_tennis(row)]


def load_events(client: PolymarketClient, slugs: list[str]) -> dict[str, dict[str, Any]]:
    if EVENTS.exists():
        return json.loads(EVENTS.read_text(encoding="utf-8"))
    result = client.get_events(slugs, max_workers=3)
    EVENTS.write_text(json.dumps(result), encoding="utf-8")
    return result


def main_market_map(events: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for event_slug, event in events.items():
        candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for market in event.get("markets") or []:
            if not isinstance(market, dict):
                continue
            kind = str(market.get("sportsMarketType") or "").lower()
            slug = str(market.get("slug") or "").lower()
            if kind in {"tennis_moneyline", "moneyline"} or slug == event_slug.lower():
                candidates["Moneyline"].append(market)
            elif kind == "tennis_set_handicap":
                candidates["Spread"].append(market)
            elif kind == "tennis_match_totals":
                candidates["Total"].append(market)
        for market_type, rows in candidates.items():
            # The main line is the highest-volume full-match market in that family.
            market = max(rows, key=lambda row: number(row.get("volume")))
            condition_id = str(market.get("conditionId") or "").lower()
            start = parse_time(market.get("gameStartTime"))
            if condition_id and start:
                selected[condition_id] = {
                    "event_slug": event_slug,
                    "market_type": market_type,
                    "start": start,
                    "title": str(event.get("title") or market.get("question") or ""),
                    "market_slug": str(market.get("slug") or ""),
                }
    return selected


def load_trades(client: PolymarketClient, condition_ids: list[str]) -> list[dict[str, Any]]:
    if TRADES.exists():
        return json.loads(TRADES.read_text(encoding="utf-8"))
    raw = client.get_user_trades(ADDRESS, condition_ids, max_records=100_000)
    fills, _ = normalize_trade_fills(ADDRESS, raw)
    TRADES.write_text(json.dumps(fills), encoding="utf-8")
    return fills


def resolution_map(closed: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = defaultdict(dict)
    for row in closed:
        condition = str(row.get("conditionId") or "").lower()
        outcome = str(row.get("outcome") or "")
        if condition and outcome:
            result[condition][outcome] = number(row.get("curPrice"))
    return result


def conviction_multiplier(relative_units: float) -> float:
    if relative_units >= 10:
        return 1.55
    if relative_units >= 5:
        return 1.40
    if relative_units >= 2.5:
        return 1.25
    if relative_units >= 1.5:
        return 1.10
    return 1.00


def snapshot_plays(
    trades: list[dict[str, Any]],
    markets: dict[str, dict[str, Any]],
    resolutions: dict[str, dict[str, float]],
    base_unit: float,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fill in trades:
        condition = str(fill.get("condition_id") or fill.get("conditionId") or "").lower()
        if condition in markets:
            grouped[condition].append(fill)
    plays: list[dict[str, Any]] = []
    for condition, fills in grouped.items():
        market = markets[condition]
        checkpoint = int(market["start"]) - CHECKPOINT_SECONDS
        eligible = sorted(
            (fill for fill in fills if int(fill.get("timestamp") or 0) <= checkpoint),
            key=lambda fill: int(fill.get("timestamp") or 0),
        )
        if not eligible:
            continue
        state: dict[str, dict[str, float]] = defaultdict(
            lambda: {"shares": 0.0, "buy_cost": 0.0, "buy_shares": 0.0, "last_price": 0.0}
        )
        for fill in eligible:
            outcome = str(fill.get("outcome") or fill.get("outcome_id") or "")
            side = str(fill.get("side") or "BUY").upper()
            size = number(fill.get("size") or fill.get("shares"))
            price = number(fill.get("price"))
            signed = size if side == "BUY" else -size
            state[outcome]["shares"] += signed
            state[outcome]["last_price"] = price
            if side == "BUY":
                state[outcome]["buy_cost"] += size * price
                state[outcome]["buy_shares"] += size
        exposures = {
            outcome: max(0.0, values["shares"] * values["last_price"])
            for outcome, values in state.items()
        }
        if not exposures:
            continue
        leader = max(exposures, key=exposures.get)
        leader_exposure = exposures[leader]
        opposing = sum(value for outcome, value in exposures.items() if outcome != leader)
        opposing_ratio = opposing / leader_exposure if leader_exposure else 1.0
        relative = max(0.0, leader_exposure - opposing) / base_unit
        resolution = resolutions.get(condition, {}).get(leader)
        if opposing_ratio >= 0.10 or relative < MINIMUM_WALLET_UNITS or resolution not in {0.0, 1.0}:
            continue
        price = state[leader]["last_price"]
        if not 0.01 < price < 0.99:
            continue
        plays.append(
            {
                **market,
                "condition_id": condition,
                "date": datetime.fromtimestamp(int(market["start"]), timezone.utc).date().isoformat(),
                "selection": leader,
                "entry_price": price,
                "won": resolution == 1.0,
                "relative_wallet_units": relative,
                "stake_units": conviction_multiplier(relative),
                "opposing_ratio": opposing_ratio,
            }
        )
    return sorted(plays, key=lambda row: (row["start"], row["condition_id"]))


def stat(values: np.ndarray) -> dict[str, float]:
    return {
        "p05": float(np.quantile(values, 0.05)),
        "median": float(np.median(values)),
        "mean": float(np.mean(values)),
        "p95": float(np.quantile(values, 0.95)),
    }


def simulate(plays: list[dict[str, Any]], days: int, seed: int) -> dict[str, Any]:
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for play in plays:
        by_day[play["date"]].append(play)
    blocks = [
        by_day[(HISTORY_START + timedelta(days=index)).isoformat()]
        for index in range((AS_OF - HISTORY_START).days + 1)
    ]
    rng = np.random.default_rng(seed)
    bets = np.zeros(PATHS)
    wins = np.zeros(PATHS)
    profit = np.zeros(PATHS)
    stake = np.zeros(PATHS)
    for path in range(PATHS):
        for block_index in rng.integers(0, len(blocks), size=days):
            for play in blocks[int(block_index)]:
                units = float(play["stake_units"])
                result = ((1.0 - play["entry_price"]) / play["entry_price"]) if play["won"] else -1.0
                bets[path] += 1
                wins[path] += int(play["won"])
                stake[path] += units
                profit[path] += units * result
    hit = np.divide(wins, bets, out=np.zeros_like(wins), where=bets > 0)
    roi = np.divide(profit, stake, out=np.zeros_like(profit), where=stake > 0)
    return {
        "bets": stat(bets),
        "hit_rate": stat(hit),
        "profit_units": stat(profit),
        "betting_roi": stat(roi),
        "probability_profitable": float(np.mean(profit > 0)),
    }


def main() -> None:
    closed = load_closed()
    client = PolymarketClient(max_retries=5)
    event_slugs = sorted({str(row.get("eventSlug") or "") for row in closed if row.get("eventSlug")})
    events = load_events(client, event_slugs)
    markets = main_market_map(events)
    interacted = sorted({str(row.get("conditionId") or "").lower() for row in closed} & set(markets))
    trades = load_trades(client, interacted)
    resolutions = resolution_map(closed)

    # Estimate Bagwell's normal risk unit from clean, settled main-market inventory.
    closed_costs: list[float] = []
    by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in closed:
        condition = str(row.get("conditionId") or "").lower()
        if condition in markets:
            by_condition[condition].append(row)
    for rows in by_condition.values():
        outcome_costs: dict[str, float] = defaultdict(float)
        for row in rows:
            outcome_costs[str(row.get("outcome") or "")] += number(row.get("totalBought")) * number(row.get("avgPrice"))
        ordered = sorted(outcome_costs.values(), reverse=True)
        if ordered and (sum(ordered[1:]) / ordered[0] if ordered[0] else 1.0) < 0.10:
            closed_costs.append(max(0.0, ordered[0] - sum(ordered[1:])))
    unit = estimate_unit_size(ADDRESS, LABEL, [value for value in closed_costs if value >= 25])
    if not unit.estimated_base_unit:
        raise RuntimeError("Could not estimate Bagwell306 base unit")

    plays = [
        play for play in snapshot_plays(trades, markets, resolutions, unit.estimated_base_unit)
        if HISTORY_START.isoformat() <= play["date"] <= AS_OF.isoformat()
    ]
    wins = sum(int(play["won"]) for play in plays)
    historical_profit = sum(
        play["stake_units"] * (((1 - play["entry_price"]) / play["entry_price"]) if play["won"] else -1)
        for play in plays
    )
    historical_stake = sum(play["stake_units"] for play in plays)
    payload = {
        "title": "Bagwell306 Tennis — validated 5,000-path simulation",
        "as_of": AS_OF.isoformat(),
        "paths_per_horizon": PATHS,
        "wallet": {"label": LABEL, "address": ADDRESS},
        "method": "Trailing-60-day calendar-day block bootstrap. Signals are reconstructed from executed fills at the model's 30-minute pre-start checkpoint. Only the highest-volume full-match moneyline, set handicap, and match total are eligible. Contradictions >=10% and positions below 0.5 Bagwell units are excluded.",
        "estimated_wallet_base_unit_usd": unit.estimated_base_unit,
        "unit_estimate_confidence": unit.confidence,
        "eligible_60d": {
            "bets": len(plays),
            "record": f"{wins}-{len(plays)-wins}",
            "hit_rate": wins / len(plays) if plays else None,
            "profit_units": historical_profit,
            "betting_roi": historical_profit / historical_stake if historical_stake else None,
            "average_stake_units": statistics.mean(play["stake_units"] for play in plays) if plays else None,
            "by_market": {
                kind: sum(play["market_type"] == kind for play in plays)
                for kind in ("Moneyline", "Spread", "Total")
            },
        },
        "simulations": {str(days): simulate(plays, days, 306_000 + days) for days in (7, 30, 60)},
        "limitations": [
            "The copy price is Bagwell's latest executed fill before the checkpoint, not a timestamp-matched NoVIG/ProphetX executable quote.",
            "A bootstrap measures repetition of this observed 60-day regime; it is not independent predictive validation.",
        ],
        "plays": plays,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in payload.items() if key != "plays"}, indent=2))


if __name__ == "__main__":
    main()
