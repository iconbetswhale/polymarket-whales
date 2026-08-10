from __future__ import annotations

import argparse
import json
import math
import random
import re
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from polymarket_client import (  # noqa: E402
    CLOSED_POSITIONS_URL,
    CURRENT_POSITIONS_URL,
    PolymarketClient,
)


GENERATED_AT = "2026-07-29T00:40:00-04:00"
THROUGH_DATE = "2026-07-27"
SEASON_START = "2026-03-01"
STARTING_BANKROLL = 10_000.0
SIMULATIONS = 5_000
HORIZON_DAYS = 30
SEED = 20260728
DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")
LINE_RE = re.compile(r"-(\d+)pt(\d+)$")

SOURCE_DIR = ROOT / "outputs" / "lead-main-markets-source"
EVENTS_FILE = SOURCE_DIR / "event-catalog.json"
OUTPUT = (
    ROOT
    / "outputs"
    / "lead-cohort-main-markets-30-day-simulation-2026-07-28.json"
)

WALLETS = {
    "Soarin22": {
        "address": "0x84dbb7103982e3617704a2ed7d5b39691952aeeb",
        "unit": 7_800.0,
        "minimum_units": 0.5,
    },
    "Wordylittleneck": {
        "address": "0x3dfb153c197d4c19d3b31c1ecd2c7b6860eeabaf",
        "unit": 20_000.0,
        "minimum_units": 0.5,
    },
    "phonesculptor": {
        "address": "0xf1528f12e645462c344799b62b1b421a6a4c64aa",
        "unit": 29_000.0,
        "minimum_units": 0.5,
    },
    "Formal-Cupcake": {
        "address": "0xb8c842bc049bf208f73354c7b037b811d741d8a4",
        "unit": 1_300.0,
        "minimum_units": 1.0,
    },
}

COHORTS = {
    "THREE_LEADS": ("Soarin22", "Wordylittleneck", "phonesculptor"),
    "FOUR_LEADS": (
        "Soarin22",
        "Wordylittleneck",
        "phonesculptor",
        "Formal-Cupcake",
    ),
}


def number(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * quantile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def event_date(row: dict[str, Any]) -> str | None:
    value = str(row.get("eventSlug") or row.get("slug") or "")
    match = DATE_RE.search(value)
    return match.group(1) if match else None


def position_key(row: dict[str, Any]) -> str:
    asset = str(row.get("asset") or "").strip().lower()
    if asset:
        return asset
    return (
        f"{str(row.get('conditionId') or '').lower()}::"
        f"{str(row.get('outcome') or '').strip().lower()}"
    )


def position_cost(row: dict[str, Any]) -> float:
    initial_value = number(row.get("initialValue"))
    if initial_value > 0:
        return initial_value
    return number(row.get("totalBought")) * number(row.get("avgPrice"))


def is_settled_current(row: dict[str, Any]) -> bool:
    return bool(row.get("redeemable")) and (
        number(row.get("curPrice")) <= 0.001
        or number(row.get("curPrice")) >= 0.999
    )


def fetch_all_current(client: PolymarketClient, address: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    limit = 500
    while True:
        page = client._get_json(
            CURRENT_POSITIONS_URL,
            {
                "user": address,
                "limit": limit,
                "offset": offset,
                "sizeThreshold": 0,
                "sortBy": "CURRENT",
                "sortDirection": "DESC",
            },
        )
        if not isinstance(page, list):
            raise RuntimeError(f"Unexpected current-position response for {address}")
        rows.extend(page)
        if len(page) < limit:
            break
        offset += limit
    return rows


def fetch_all_closed(client: PolymarketClient, address: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    limit = 50
    while True:
        page = client._get_json(
            CLOSED_POSITIONS_URL,
            {
                "user": address,
                "limit": limit,
                "offset": offset,
                "sortBy": "TIMESTAMP",
                "sortDirection": "DESC",
            },
        )
        if not isinstance(page, list):
            raise RuntimeError(f"Unexpected closed-position response for {address}")
        rows.extend(page)
        if len(page) < limit:
            break
        offset += limit
    return rows


def source_paths(label: str) -> tuple[Path, Path]:
    safe = label.lower().replace(" ", "-")
    return SOURCE_DIR / f"{safe}-closed.json", SOURCE_DIR / f"{safe}-current.json"


def refresh_sources() -> None:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    client = PolymarketClient(request_timeout=30, max_retries=3)
    for label, config in WALLETS.items():
        closed_path, current_path = source_paths(label)
        closed = fetch_all_closed(client, str(config["address"]))
        current = fetch_all_current(client, str(config["address"]))
        closed_path.write_text(json.dumps(closed, indent=2), encoding="utf-8")
        current_path.write_text(json.dumps(current, indent=2), encoding="utf-8")
        print(f"{label}: {len(closed)} closed, {len(current)} current")

    event_slugs: set[str] = set()
    for label in WALLETS:
        closed_path, current_path = source_paths(label)
        for path in (closed_path, current_path):
            for row in json.loads(path.read_text(encoding="utf-8")):
                event_slug = str(row.get("eventSlug") or "").lower()
                market_slug = str(row.get("slug") or "").lower()
                if event_slug.startswith("mlb-") and (
                    "spread" in market_slug or "total" in market_slug
                ):
                    event_slugs.add(event_slug)
    events = client.get_events(sorted(event_slugs), max_workers=6)
    EVENTS_FILE.write_text(json.dumps(events, indent=2), encoding="utf-8")
    print(f"Event catalog: {sum(bool(value) for value in events.values())} events")


def load_source_rows(label: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    closed_path, current_path = source_paths(label)
    if not closed_path.exists() or not current_path.exists():
        raise FileNotFoundError(
            f"Missing refreshed source for {label}; rerun with --refresh"
        )
    return (
        json.loads(closed_path.read_text(encoding="utf-8")),
        json.loads(current_path.read_text(encoding="utf-8")),
    )


def reconcile_positions(
    closed: list[dict[str, Any]], current: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    closed_by_key: dict[str, dict[str, Any]] = {}
    closed_duplicates = 0
    for row in closed:
        key = position_key(row)
        if key in closed_by_key:
            closed_duplicates += 1
            if number(row.get("timestamp")) > number(
                closed_by_key[key].get("timestamp")
            ):
                closed_by_key[key] = row
        else:
            closed_by_key[key] = row

    settled_current = [row for row in current if is_settled_current(row)]
    added_current = 0
    overlap = 0
    reconciled = dict(closed_by_key)
    for row in settled_current:
        key = position_key(row)
        if key in reconciled:
            overlap += 1
            continue
        reconciled[key] = row
        added_current += 1

    rows = [
        row
        for row in reconciled.values()
        if (event_date(row) or "") <= THROUGH_DATE
    ]
    audit = {
        "raw_closed_rows": len(closed),
        "raw_current_rows": len(current),
        "closed_duplicate_keys": closed_duplicates,
        "settled_current_rows": len(settled_current),
        "current_closed_overlap_keys": overlap,
        "settled_current_rows_added": added_current,
        "reconciled_settled_rows_through_date": len(rows),
    }
    return rows, audit


def market_volume(market: dict[str, Any]) -> float:
    return number(market.get("volume"))


def build_main_market_map(events: dict[str, Any]) -> dict[str, dict[str, str | None]]:
    result: dict[str, dict[str, str | None]] = {}
    for event_slug, event in events.items():
        if not isinstance(event, dict):
            result[event_slug] = {
                "moneyline": event_slug,
                "spread": None,
                "total": None,
            }
            continue
        markets = [
            market
            for market in event.get("markets", [])
            if isinstance(market, dict)
        ]
        spreads = [
            market
            for market in markets
            if str(market.get("sportsMarketType") or "").lower() == "spreads"
            and abs(number(market.get("line"))) == 1.5
            and "-f5-" not in str(market.get("slug") or "").lower()
        ]
        totals = [
            market
            for market in markets
            if str(market.get("sportsMarketType") or "").lower() == "totals"
            and "-f5-" not in str(market.get("slug") or "").lower()
        ]
        result[event_slug] = {
            "moneyline": event_slug,
            "spread": (
                str(max(spreads, key=market_volume).get("slug") or "").lower()
                if spreads
                else None
            ),
            "total": (
                str(max(totals, key=market_volume).get("slug") or "").lower()
                if totals
                else None
            ),
        }
    return result


def classify_market(
    row: dict[str, Any], main_markets: dict[str, dict[str, str | None]]
) -> str | None:
    event_slug = str(row.get("eventSlug") or "").lower()
    market_slug = str(row.get("slug") or "").lower()
    if not event_slug.startswith("mlb-"):
        return None
    if market_slug == event_slug:
        return "moneyline"
    mapping = main_markets.get(event_slug, {})
    if market_slug and market_slug == mapping.get("spread"):
        return "spread"
    if market_slug and market_slug == mapping.get("total"):
        return "total"
    return None


def build_wallet_signals(
    label: str,
    config: dict[str, Any],
    rows: list[dict[str, Any]],
    main_markets: dict[str, dict[str, str | None]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    market_type_by_condition: dict[str, str] = {}
    main_rows = 0
    for row in rows:
        market_type = classify_market(row, main_markets)
        condition_id = str(row.get("conditionId") or "").lower()
        row_date = event_date(row)
        if (
            market_type
            and condition_id
            and row_date
            and SEASON_START <= row_date <= THROUGH_DATE
        ):
            grouped[condition_id].append(row)
            market_type_by_condition[condition_id] = market_type
            main_rows += 1

    signals: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    eligible_counts: Counter[str] = Counter()
    for condition_id, market_rows in grouped.items():
        by_outcome: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in market_rows:
            by_outcome[str(row.get("outcome") or "").strip()].append(row)
        outcomes: list[dict[str, Any]] = []
        for outcome, outcome_rows in by_outcome.items():
            risked = sum(position_cost(row) for row in outcome_rows)
            shares = sum(number(row.get("totalBought")) for row in outcome_rows)
            price = risked / shares if shares > 0 else statistics.mean(
                number(row.get("avgPrice")) for row in outcome_rows
            )
            won_values = {
                number(row.get("curPrice")) >= 0.999 for row in outcome_rows
            }
            outcomes.append(
                {
                    "outcome": outcome,
                    "risked": risked,
                    "shares": shares,
                    "price": price,
                    "won": True in won_values,
                }
            )
        outcomes.sort(key=lambda item: number(item["risked"]), reverse=True)
        leader = outcomes[0]
        opposing_risk = sum(number(item["risked"]) for item in outcomes[1:])
        leader_risk = number(leader["risked"])
        if leader_risk <= 0:
            continue
        opposing_ratio = opposing_risk / leader_risk
        net_risk = max(0.0, leader_risk - opposing_risk)
        relative_units = net_risk / number(config["unit"])
        status = (
            "CLEAN_DIRECTIONAL"
            if opposing_ratio < 0.10
            else "MINOR_HEDGE"
            if opposing_ratio <= 0.20
            else "MATERIAL_HEDGE"
            if opposing_ratio <= 0.50
            else "TWO_SIDED"
        )
        # Provider values retain tiny execution/rounding residue. Treat a position
        # within 0.1% of the configured unit threshold as meeting that threshold.
        eligible = (
            status in {"CLEAN_DIRECTIONAL", "MINOR_HEDGE"}
            and relative_units >= number(config["minimum_units"]) * 0.999
            and 0 < number(leader["price"]) < 1
        )
        status_counts[status] += 1
        if eligible:
            eligible_counts[market_type_by_condition[condition_id]] += 1
        sample = market_rows[0]
        signals.append(
            {
                "condition_id": condition_id,
                "event_slug": str(sample.get("eventSlug") or "").lower(),
                "market_slug": str(sample.get("slug") or "").lower(),
                "market_type": market_type_by_condition[condition_id],
                "date": event_date(sample),
                "wallet": label,
                "outcome": str(leader["outcome"]),
                "price": number(leader["price"]),
                "won": bool(leader["won"]),
                "leader_risked_dollars": leader_risk,
                "opposing_risked_dollars": opposing_risk,
                "net_risked_dollars": net_risk,
                "relative_units": relative_units,
                "opposing_ratio": opposing_ratio,
                "status": status,
                "eligible": eligible,
            }
        )

    all_dates = sorted(
        {
            str(event_date(row))
            for row in rows
            if str(row.get("eventSlug") or "").lower().startswith("mlb-")
            and event_date(row)
        }
    )
    season_dates = [
        value for value in all_dates if SEASON_START <= value <= THROUGH_DATE
    ]
    audit = {
        "reconciled_mlb_rows_all_history": sum(
            str(row.get("eventSlug") or "").lower().startswith("mlb-")
            for row in rows
        ),
        "reconciled_mlb_rows_2026_season": sum(
            str(row.get("eventSlug") or "").lower().startswith("mlb-")
            and bool(event_date(row))
            and SEASON_START <= str(event_date(row)) <= THROUGH_DATE
            for row in rows
        ),
        "main_market_rows": main_rows,
        "main_market_conditions": len(grouped),
        "all_signal_conditions": len(signals),
        "eligible_signal_conditions": sum(signal["eligible"] for signal in signals),
        "eligible_by_market_type": dict(sorted(eligible_counts.items())),
        "direction_status_counts": dict(sorted(status_counts.items())),
        "first_mlb_date_all_history": all_dates[0] if all_dates else None,
        "first_mlb_date_2026_season": season_dates[0] if season_dates else None,
        "last_mlb_date_2026_season": season_dates[-1] if season_dates else None,
    }
    return signals, audit


def position_return(price: float, won: bool) -> float:
    if price <= 0 or price >= 1:
        return 0.0
    return (1.0 - price) / price if won else -1.0


def build_plays(
    signal_map: dict[str, list[dict[str, Any]]], labels: tuple[str, ...]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for label in labels:
        for signal in signal_map[label]:
            if signal["eligible"]:
                by_condition[str(signal["condition_id"])].append(signal)

    plays: list[dict[str, Any]] = []
    exclusions: Counter[str] = Counter()
    for condition_id, signals in by_condition.items():
        outcomes: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for signal in signals:
            outcomes[str(signal["outcome"])].append(signal)
        ranked = sorted(outcomes.items(), key=lambda item: len(item[1]), reverse=True)
        if len(ranked) > 1 and len(ranked[0][1]) == len(ranked[1][1]):
            exclusions["exact_vote_tie"] += 1
            continue
        selected_outcome, selected = ranked[0]
        opposed = [
            signal for signal in signals if str(signal["outcome"]) != selected_outcome
        ]
        if opposed:
            exclusions["eligible_lead_opposition"] += 1
            continue
        won_values = {bool(signal["won"]) for signal in selected}
        if len(won_values) != 1:
            exclusions["inconsistent_settlement"] += 1
            continue
        price = statistics.median(number(signal["price"]) for signal in selected)
        if not 0 < price < 1:
            exclusions["invalid_entry_price"] += 1
            continue
        supporter_count = len(selected)
        stake_units = min(1.5, 0.5 + 0.25 * (supporter_count - 1))
        won = won_values.pop()
        plays.append(
            {
                "condition_id": condition_id,
                "date": selected[0]["date"],
                "event_slug": selected[0]["event_slug"],
                "market_slug": selected[0]["market_slug"],
                "market_type": selected[0]["market_type"],
                "outcome": selected_outcome,
                "supporters": sorted(signal["wallet"] for signal in selected),
                "supporter_count": supporter_count,
                "price": price,
                "won": won,
                "stake_units": stake_units,
                "return_per_dollar": position_return(price, won),
            }
        )
    return (
        sorted(
            plays,
            key=lambda row: (
                str(row["date"]),
                str(row["event_slug"]),
                str(row["market_type"]),
            ),
        ),
        dict(sorted(exclusions.items())),
    )


def excursion_metrics(pnl_units: list[float]) -> tuple[float, float]:
    equity = 0.0
    peak = 0.0
    trough = 0.0
    max_drawdown = 0.0
    max_runup = 0.0
    for pnl in pnl_units:
        equity += pnl
        peak = max(peak, equity)
        trough = min(trough, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        max_runup = max(max_runup, equity - trough)
    return max_drawdown, max_runup


def summarize_slice(plays: list[dict[str, Any]]) -> dict[str, Any]:
    if not plays:
        return {
            "bets": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": None,
            "total_staked_units": 0.0,
            "profit_units": 0.0,
            "stake_weighted_roi": None,
            "average_stake_units": None,
            "median_stake_units": None,
            "max_drawdown_units": None,
            "max_runup_units": None,
        }
    stakes = [number(play["stake_units"]) for play in plays]
    pnl_units = [
        number(play["stake_units"]) * number(play["return_per_dollar"])
        for play in plays
    ]
    drawdown, runup = excursion_metrics(pnl_units)
    wins = sum(bool(play["won"]) for play in plays)
    return {
        "bets": len(plays),
        "wins": wins,
        "losses": len(plays) - wins,
        "win_rate": wins / len(plays),
        "total_staked_units": sum(stakes),
        "profit_units": sum(pnl_units),
        "stake_weighted_roi": sum(pnl_units) / sum(stakes),
        "average_stake_units": statistics.mean(stakes),
        "median_stake_units": statistics.median(stakes),
        "average_bet_per_100_bankroll": statistics.mean(stakes),
        "median_bet_per_100_bankroll": statistics.median(stakes),
        "average_initial_bet_on_10000": statistics.mean(stakes) * 100,
        "median_initial_bet_on_10000": statistics.median(stakes) * 100,
        "max_drawdown_units": drawdown,
        "max_runup_units": runup,
    }


def historical_summary(plays: list[dict[str, Any]]) -> dict[str, Any]:
    start = min(str(play["date"]) for play in plays)
    end = max(str(play["date"]) for play in plays)
    calendar_days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    summary = summarize_slice(plays)
    summary.update(
        {
            "start": start,
            "end": end,
            "calendar_days": calendar_days,
            "active_days": len({str(play["date"]) for play in plays}),
            "bets_per_calendar_day": len(plays) / calendar_days,
            "bets_per_active_day": len(plays)
            / len({str(play["date"]) for play in plays}),
            "by_market_type": {
                market_type: summarize_slice(
                    [play for play in plays if play["market_type"] == market_type]
                )
                for market_type in ("moneyline", "spread", "total")
            },
            "by_supporter_count": {
                str(count): summarize_slice(
                    [
                        play
                        for play in plays
                        if int(play["supporter_count"]) == count
                    ]
                )
                for count in sorted({int(play["supporter_count"]) for play in plays})
            },
        }
    )
    return summary


def simulate(plays: list[dict[str, Any]], seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    start = date.fromisoformat(min(str(play["date"]) for play in plays))
    end = date.fromisoformat(max(str(play["date"]) for play in plays))
    calendar_days = (end - start).days + 1
    by_day: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for play in plays:
        day_index = (date.fromisoformat(str(play["date"])) - start).days
        by_day[day_index].append(play)

    paths: list[list[float]] = []
    bet_counts: list[float] = []
    drawdowns: list[float] = []
    runups: list[float] = []
    for _ in range(SIMULATIONS):
        bankroll = STARTING_BANKROLL
        path = [bankroll]
        count = 0
        peak = bankroll
        trough = bankroll
        max_drawdown_units = 0.0
        max_runup_units = 0.0
        for _day in range(HORIZON_DAYS):
            sampled_day = rng.randrange(calendar_days)
            for play in by_day.get(sampled_day, []):
                stake = bankroll * number(play["stake_units"]) / 100
                bankroll += stake * number(play["return_per_dollar"])
                count += 1
                peak = max(peak, bankroll)
                trough = min(trough, bankroll)
                max_drawdown_units = max(
                    max_drawdown_units, (peak - bankroll) / 100
                )
                max_runup_units = max(max_runup_units, (bankroll - trough) / 100)
            path.append(bankroll)
        paths.append(path)
        bet_counts.append(float(count))
        drawdowns.append(max_drawdown_units)
        runups.append(max_runup_units)

    daily_percentiles = {
        label: [
            percentile([path[day] for path in paths], q)
            for day in range(HORIZON_DAYS + 1)
        ]
        for label, q in (
            ("p05", 0.05),
            ("p25", 0.25),
            ("p50", 0.50),
            ("p75", 0.75),
            ("p95", 0.95),
        )
    }
    final_bankrolls = [path[-1] for path in paths]
    rois = [bankroll / STARTING_BANKROLL - 1 for bankroll in final_bankrolls]
    return {
        "simulations": SIMULATIONS,
        "horizon_days": HORIZON_DAYS,
        "starting_bankroll": STARTING_BANKROLL,
        "bootstrap_method": (
            "Calendar-day block bootstrap; samples historical dates with replacement "
            "to preserve same-day and same-game multi-market clustering."
        ),
        "median_bets": percentile(bet_counts, 0.50),
        "bets": {
            "p05": percentile(bet_counts, 0.05),
            "p50": percentile(bet_counts, 0.50),
            "p95": percentile(bet_counts, 0.95),
        },
        "probability_profitable": sum(
            bankroll > STARTING_BANKROLL for bankroll in final_bankrolls
        )
        / SIMULATIONS,
        "final_bankroll": {
            "p05": percentile(final_bankrolls, 0.05),
            "p25": percentile(final_bankrolls, 0.25),
            "p50": percentile(final_bankrolls, 0.50),
            "p75": percentile(final_bankrolls, 0.75),
            "p95": percentile(final_bankrolls, 0.95),
        },
        "roi": {
            "p05": percentile(rois, 0.05),
            "p25": percentile(rois, 0.25),
            "p50": percentile(rois, 0.50),
            "p75": percentile(rois, 0.75),
            "p95": percentile(rois, 0.95),
        },
        "max_drawdown_units": {
            "p05": percentile(drawdowns, 0.05),
            "p50": percentile(drawdowns, 0.50),
            "p95": percentile(drawdowns, 0.95),
        },
        "max_runup_units": {
            "p05": percentile(runups, 0.05),
            "p50": percentile(runups, 0.50),
            "p95": percentile(runups, 0.95),
        },
        "daily_bankroll_percentiles": daily_percentiles,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    if args.refresh:
        refresh_sources()
    if not EVENTS_FILE.exists():
        raise FileNotFoundError("Missing event catalog; rerun with --refresh")
    events = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
    main_markets = build_main_market_map(events)

    signal_map: dict[str, list[dict[str, Any]]] = {}
    wallet_audit: dict[str, Any] = {}
    for label, config in WALLETS.items():
        closed, current = load_source_rows(label)
        reconciled, reconciliation_audit = reconcile_positions(closed, current)
        signals, signal_audit = build_wallet_signals(
            label, config, reconciled, main_markets
        )
        signal_map[label] = signals
        wallet_audit[label] = {
            "address": config["address"],
            "unit_dollars": config["unit"],
            "minimum_units": config["minimum_units"],
            **reconciliation_audit,
            **signal_audit,
        }

    payload: dict[str, Any] = {
        "methodology": {
            "generated_at": GENERATED_AT,
            "through_date": THROUGH_DATE,
            "season_start": SEASON_START,
            "scope": (
                "Reconciled settled 2026 MLB moneyline, main run-line, and main "
                "total positions for the four configured lead wallets."
            ),
            "reconciliation": (
                "Deduplicate closed positions by token; add settled redeemable current "
                "positions absent from closed history so unredeemed zero-value losses "
                "and winners are preserved."
            ),
            "market_definition": {
                "moneyline": "The event-level full-game moneyline condition.",
                "spread": (
                    "The highest-volume full-game ±1.5 spread condition in Gamma "
                    "event metadata; first-five and alternate spread lines excluded."
                ),
                "total": (
                    "The highest-volume full-game totals condition in Gamma event "
                    "metadata; first-five and alternate total lines excluded."
                ),
            },
            "exposure_definition": (
                "Risked dollars equal initialValue when available, otherwise "
                "totalBought shares multiplied by avgPrice. Opposing risk is netted "
                "in dollars before applying each wallet's measured unit threshold; "
                "a 0.1% tolerance handles provider execution rounding."
            ),
            "cohort_rule": (
                "Play any eligible clean/minor-hedge lead direction from the cohort; "
                "skip an exact vote tie or any eligible lead opposition."
            ),
            "entry_price_proxy": (
                "Median average entry price among agreeing eligible lead wallets."
            ),
            "sizing_proxy": (
                "0.50u for one clean lead plus 0.25u per additional agreeing lead, "
                "capped at 1.50u; 1u is 1% of current bankroll."
            ),
            "simulation": (
                "5,000 30-day calendar-block bootstrap paths on a $10,000 bankroll, "
                "preserving same-day multi-market clusters."
            ),
            "important_limits": [
                "Position snapshots do not reconstruct the executable two-hour price, fees, slippage, or liquidity.",
                "Gamma lifetime volume identifies the main historical market but is not a pregame volume snapshot.",
                "Bootstrap results describe resampled historical outcomes and are not a guarantee or causal estimate.",
            ],
        },
        "data_quality": {
            "wallets": wallet_audit,
            "event_catalog_requested": len(events),
            "event_catalog_available": sum(bool(event) for event in events.values()),
        },
        "cohorts": {},
    }

    for index, (name, labels) in enumerate(COHORTS.items()):
        plays, exclusions = build_plays(signal_map, labels)
        payload["cohorts"][name] = {
            "wallets": list(labels),
            "historical": historical_summary(plays),
            "exclusions": exclusions,
            "simulation": simulate(plays, SEED + index),
            "play_ledger": plays,
        }

    three_ids = {
        play["condition_id"] for play in payload["cohorts"]["THREE_LEADS"]["play_ledger"]
    }
    incremental = [
        play
        for play in payload["cohorts"]["FOUR_LEADS"]["play_ledger"]
        if play["condition_id"] not in three_ids
    ]
    payload["four_lead_incremental_vs_three"] = summarize_slice(incremental)
    payload["four_lead_incremental_vs_three"]["by_market_type"] = {
        market_type: summarize_slice(
            [play for play in incremental if play["market_type"] == market_type]
        )
        for market_type in ("moneyline", "spread", "total")
    }

    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(OUTPUT)
    for name, cohort in payload["cohorts"].items():
        print(
            name,
            json.dumps(
                {
                    "historical": cohort["historical"],
                    "simulation": {
                        key: cohort["simulation"][key]
                        for key in (
                            "median_bets",
                            "probability_profitable",
                            "final_bankroll",
                            "roi",
                            "max_drawdown_units",
                            "max_runup_units",
                        )
                    },
                },
                indent=2,
            ),
        )


if __name__ == "__main__":
    main()
