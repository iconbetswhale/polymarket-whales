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
PATHS = 5_000
CHECKPOINT_SECONDS = 30 * 60
MINIMUM_WALLET_UNITS = 0.50
SOURCE = Path(
    r"C:\Users\15617\.codex\codex-remote-attachments\019f682e-d751-7700-85f8-61e86956cf9d\B5BC4546-4A51-4C68-B607-C2216F1974DB\1-api-response-28-.json"
)
EVENTS = ROOT / "outputs" / "bagwell306-tennis-events-full-export-2026-08-05.json"
OUTPUT = ROOT / "outputs" / "bagwell306-tennis-5000-full-export-2026-08-05.json"


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def parse_json_list(value: Any) -> list[Any]:
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


def is_tennis(row: dict[str, Any]) -> bool:
    slug = str(row.get("eventSlug") or row.get("event_slug") or "").lower()
    return slug.startswith(("atp-", "wta-", "itf-", "utr-", "challenger-", "tennis-"))


def load_source() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    raw = payload if isinstance(payload, list) else payload.get("data", [])
    wallets = {str(row.get("proxyWallet") or "").lower() for row in raw if isinstance(row, dict)}
    if wallets != {ADDRESS}:
        raise RuntimeError(f"Expected Bagwell-only export; found wallets={sorted(wallets)}")
    fills, duplicates = normalize_trade_fills(ADDRESS, [row for row in raw if isinstance(row, dict)])
    tennis = [fill for fill in fills if is_tennis(fill)]
    timestamps = [int(fill["timestamp"]) for fill in tennis]
    audit = {
        "raw_rows": len(raw),
        "normalized_rows": len(fills),
        "duplicate_rows": duplicates,
        "wallet_count": len(wallets),
        "tennis_fills": len(tennis),
        "tennis_conditions": len({fill["condition_id"] for fill in tennis}),
        "tennis_events": len({fill["event_slug"] for fill in tennis}),
        "tennis_buy_fills": sum(fill["side"] == "BUY" for fill in tennis),
        "tennis_sell_fills": sum(fill["side"] == "SELL" for fill in tennis),
        "tennis_first_fill": datetime.fromtimestamp(min(timestamps), timezone.utc).isoformat(),
        "tennis_last_fill": datetime.fromtimestamp(max(timestamps), timezone.utc).isoformat(),
    }
    return tennis, audit


def load_events(client: PolymarketClient, slugs: list[str]) -> dict[str, dict[str, Any]]:
    cached: dict[str, dict[str, Any]] = {}
    if EVENTS.exists():
        cached = json.loads(EVENTS.read_text(encoding="utf-8"))
    legacy = ROOT / "outputs" / "bagwell306-tennis-events-2026-08-05.json"
    if legacy.exists():
        for slug, event in json.loads(legacy.read_text(encoding="utf-8")).items():
            if event:
                cached.setdefault(slug, event)
    missing = [slug for slug in slugs if slug not in cached]
    if missing:
        fetched = client.get_events(missing, max_workers=6)
        cached.update({slug: event for slug, event in fetched.items() if event})
        EVENTS.write_text(json.dumps(cached), encoding="utf-8")
    return {slug: cached.get(slug) for slug in slugs if cached.get(slug)}


def classify_market(event_slug: str, market: dict[str, Any]) -> str | None:
    kind = str(market.get("sportsMarketType") or "").lower()
    slug = str(market.get("slug") or "").lower()
    title = str(market.get("question") or "").lower()
    # Full-match main markets only; no first-set, props, or alternate line families.
    if "first set" in title or "set 1" in title or "set-1" in slug or "first-set" in slug:
        return None
    if kind in {"tennis_moneyline", "moneyline"} or slug == event_slug.lower():
        return "Moneyline"
    if kind == "tennis_set_handicap":
        return "Spread"
    if kind == "tennis_match_totals":
        return "Total"
    return None


def main_market_map(events: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for event_slug, event in events.items():
        families: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for market in event.get("markets") or []:
            if not isinstance(market, dict):
                continue
            family = classify_market(event_slug, market)
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
                    "market_slug": str(market.get("slug") or ""),
                    "resolution": resolution if strictly_resolved else {},
                }
    return selected


def state_at_checkpoint(fills: list[dict[str, Any]], checkpoint: int) -> dict[str, dict[str, float]]:
    state: dict[str, dict[str, float]] = defaultdict(
        lambda: {"shares": 0.0, "cost": 0.0, "last_price": 0.0, "last_fill": 0.0}
    )
    for fill in sorted(fills, key=lambda row: (int(row["timestamp"]), row["fill_id"])):
        if int(fill["timestamp"]) > checkpoint:
            continue
        outcome = str(fill.get("outcome") or "")
        shares = number(fill.get("shares"))
        price = number(fill.get("price"))
        current = state[outcome]
        if fill["side"] == "BUY":
            current["shares"] += shares
            current["cost"] += shares * price
        elif current["shares"] > 0:
            removed = min(shares, current["shares"])
            average = current["cost"] / current["shares"]
            current["shares"] -= removed
            current["cost"] -= removed * average
        current["last_price"] = price
        current["last_fill"] = int(fill["timestamp"])
    return state


def candidate_snapshots(
    fills: list[dict[str, Any]], markets: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fill in fills:
        if fill["condition_id"] in markets:
            grouped[fill["condition_id"]].append(fill)
    candidates: list[dict[str, Any]] = []
    exclusions: defaultdict[str, int] = defaultdict(int)
    for condition, rows in grouped.items():
        market = markets[condition]
        checkpoint = int(market["start"]) - CHECKPOINT_SECONDS
        state = state_at_checkpoint(rows, checkpoint)
        active = {outcome: data for outcome, data in state.items() if data["shares"] > 1e-8}
        if not active:
            exclusions["no_position_30m_prestart"] += 1
            continue
        ordered = sorted(active.items(), key=lambda item: item[1]["cost"], reverse=True)
        leader, leader_state = ordered[0]
        leader_cost = leader_state["cost"]
        opposing_cost = sum(data["cost"] for _, data in ordered[1:])
        opposing_ratio = opposing_cost / leader_cost if leader_cost else 1.0
        resolution = market.get("resolution") or {}
        if opposing_ratio >= 0.10:
            exclusions["contradictory_position"] += 1
            continue
        if leader not in resolution:
            exclusions["unresolved_or_missing_resolution"] += 1
            continue
        price = leader_state["last_price"]
        if not 0.01 < price < 0.99:
            exclusions["invalid_entry_price"] += 1
            continue
        candidates.append(
            {
                **{key: value for key, value in market.items() if key != "resolution"},
                "condition_id": condition,
                "date": datetime.fromtimestamp(int(market["start"]), timezone.utc).date().isoformat(),
                "selection": leader,
                "entry_price": price,
                "won": resolution[leader] == 1.0,
                "net_exposure_usd": max(0.0, leader_cost - opposing_cost),
                "opposing_ratio": opposing_ratio,
                "last_fill_minutes_before_start": (int(market["start"]) - leader_state["last_fill"]) / 60,
            }
        )
    return candidates, dict(exclusions)


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


def stat(values: np.ndarray) -> dict[str, float]:
    return {
        "p05": float(np.quantile(values, 0.05)),
        "median": float(np.median(values)),
        "mean": float(np.mean(values)),
        "p95": float(np.quantile(values, 0.95)),
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
    max_drawdown = np.zeros(PATHS)
    max_upside = np.zeros(PATHS)
    for path in range(PATHS):
        equity = 0.0
        peak = 0.0
        for block_index in rng.integers(0, len(blocks), size=days):
            for play in blocks[int(block_index)]:
                units = float(play["stake_units"])
                result = ((1.0 - play["entry_price"]) / play["entry_price"]) if play["won"] else -1.0
                bets[path] += 1
                wins[path] += int(play["won"])
                stake[path] += units
                profit[path] += units * result
                equity += units * result
                peak = max(peak, equity)
                max_upside[path] = max(max_upside[path], equity)
                max_drawdown[path] = max(max_drawdown[path], peak - equity)
    hit = np.divide(wins, bets, out=np.full_like(wins, np.nan), where=bets > 0)
    roi = np.divide(profit, stake, out=np.full_like(profit, np.nan), where=stake > 0)
    return {
        "bets": stat(bets),
        "hit_rate": stat(hit[~np.isnan(hit)]),
        "profit_units": stat(profit),
        "betting_roi": stat(roi[~np.isnan(roi)]),
        "max_drawdown_units": {
            **stat(max_drawdown),
            "worst_observed": float(np.max(max_drawdown)),
        },
        "max_upside_units": {
            **stat(max_upside),
            "best_observed": float(np.max(max_upside)),
        },
        "probability_profitable": float(np.mean(profit > 0)),
        "probability_no_bets": float(np.mean(bets == 0)),
    }


def summarize_actual(plays: list[dict[str, Any]]) -> dict[str, Any]:
    wins = sum(int(play["won"]) for play in plays)
    stake = sum(play["stake_units"] for play in plays)
    profit = sum(
        play["stake_units"]
        * (((1 - play["entry_price"]) / play["entry_price"]) if play["won"] else -1)
        for play in plays
    )
    return {
        "bets": len(plays),
        "record": f"{wins}-{len(plays) - wins}",
        "hit_rate": wins / len(plays) if plays else None,
        "profit_units": profit,
        "betting_roi": profit / stake if stake else None,
        "average_stake_units": statistics.mean(play["stake_units"] for play in plays) if plays else None,
        "by_market": {
            market_type: {
                "bets": sum(play["market_type"] == market_type for play in plays),
                "wins": sum(play["market_type"] == market_type and play["won"] for play in plays),
            }
            for market_type in ("Moneyline", "Spread", "Total")
        },
    }


def main() -> None:
    fills, source_audit = load_source()
    client = PolymarketClient(max_retries=5)
    slugs = sorted({fill["event_slug"] for fill in fills if fill["event_slug"]})
    events = load_events(client, slugs)
    markets = main_market_map(events)
    candidates, exclusions = candidate_snapshots(fills, markets)

    unit_samples = [row["net_exposure_usd"] for row in candidates if row["net_exposure_usd"] >= 25]
    unit = estimate_unit_size(ADDRESS, LABEL, unit_samples)
    if not unit.estimated_base_unit:
        raise RuntimeError("Could not estimate Bagwell306 base unit from full export")
    plays: list[dict[str, Any]] = []
    for row in candidates:
        relative = row["net_exposure_usd"] / unit.estimated_base_unit
        if relative < MINIMUM_WALLET_UNITS:
            exclusions["below_half_wallet_unit"] = exclusions.get("below_half_wallet_unit", 0) + 1
            continue
        plays.append({**row, "relative_wallet_units": relative, "stake_units": conviction_multiplier(relative)})
    plays.sort(key=lambda row: (row["start"], row["condition_id"]))

    first_play = min(date.fromisoformat(play["date"]) for play in plays)
    trailing_60_start = AS_OF - timedelta(days=59)
    trailing_60 = [play for play in plays if trailing_60_start <= date.fromisoformat(play["date"]) <= AS_OF]
    actual_by_horizon = {
        str(days): summarize_actual(
            [
                play
                for play in plays
                if AS_OF - timedelta(days=days - 1)
                <= date.fromisoformat(play["date"])
                <= AS_OF
            ]
        )
        for days in (7, 30, 60)
    }
    payload = {
        "title": "Bagwell306 tennis — corrected full-export 5,000-path analysis",
        "as_of": AS_OF.isoformat(),
        "paths_per_horizon": PATHS,
        "wallet": {"label": LABEL, "address": ADDRESS},
        "source_audit": {
            **source_audit,
            "event_metadata_found": len(events),
            "main_market_conditions_in_metadata": len(markets),
            "eligible_directional_snapshots_before_unit_threshold": len(candidates),
            "exclusions": exclusions,
        },
        "estimated_wallet_base_unit_usd": unit.estimated_base_unit,
        "unit_estimate_confidence": unit.confidence,
        "unit_estimate_samples": unit.sample_size,
        "rule": "At 30 minutes before scheduled start: net all Bagwell buys and sells; exclude opposing exposure >=10%; require at least 0.5 estimated Bagwell units; include only resolved full-match main moneyline, spread, and total markets. Copy sizing is the prior 1.00u–1.55u conviction schedule.",
        "actual_all_available": summarize_actual(plays),
        "actual_trailing_60d": summarize_actual(trailing_60),
        "actual_by_horizon": actual_by_horizon,
        "simulations": {
            str(days): simulate(trailing_60, days, trailing_60_start, 306_100 + days)
            for days in (7, 30, 60)
        },
        "limitations": [
            "The simulation bootstraps observed calendar days from the trailing 60-day regime; it is descriptive, not independent out-of-sample validation.",
            "Copy entry uses Bagwell's latest executed fill available by the 30-minute checkpoint, not a timestamp-matched executable NoVIG/ProphetX quote.",
            "Main spread and total are identified as the highest-volume full-match line within each event family because the export does not label opening/main versus alternate lines directly.",
        ],
        "plays": plays,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in payload.items() if key != "plays"}, indent=2))


if __name__ == "__main__":
    main()
