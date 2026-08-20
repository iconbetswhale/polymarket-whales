"""Discover and rank NFL wallet candidates from public Polymarket data.

The scanner is intentionally research-only.  It uses current holders on liquid
NFL game markets and the public sports leaderboard as discovery inputs, then
evaluates settled full-game NFL moneylines, spreads, and totals.  It does not
write wallets.json or promote a wallet into production.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests


EVENTS_URL = "https://gamma-api.polymarket.com/events"
HOLDERS_URL = "https://data-api.polymarket.com/holders"
LEADERBOARD_URL = "https://data-api.polymarket.com/v1/leaderboard"
CLOSED_POSITIONS_URL = "https://data-api.polymarket.com/closed-positions"
POSITIONS_URL = "https://data-api.polymarket.com/positions"
USER_AGENT = "iconbets-nfl-wallet-research/1.0"
ROOT = Path(__file__).resolve().parents[1]
WALLETS_PATH = ROOT / "wallets.json"

NFL_GAME_RE = re.compile(r"^nfl-[a-z0-9]+-[a-z0-9]+-\d{4}-\d{2}-\d{2}$")
NFL_MAIN_MARKET_TYPES = {"moneyline", "spreads", "totals"}


def number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except ValueError:
            return []
        if isinstance(payload, list):
            return [str(item) for item in payload]
    return []


def chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def get_json(
    url: str,
    params: dict[str, Any],
    *,
    timeout: int = 20,
    retries: int = 4,
) -> Any:
    headers = {"User-Agent": USER_AGENT}
    delay = 0.5
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
            if response.status_code == 429 or response.status_code >= 500:
                last_error = RuntimeError(f"HTTP {response.status_code}")
                retry_after = response.headers.get("Retry-After")
                time.sleep(max(number(retry_after), delay))
                delay *= 2
                continue
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"Failed request to {url}: {last_error}") from last_error


def is_nfl_game_event(event: dict[str, Any]) -> bool:
    return bool(NFL_GAME_RE.fullmatch(str(event.get("slug") or "").lower()))


def market_type(row: dict[str, Any]) -> str | None:
    raw = str(row.get("sportsMarketType") or "").lower()
    if raw == "moneyline":
        return "Moneyline"
    if raw == "spreads":
        return "Spread"
    if raw == "totals":
        return "Total"
    slug = str(row.get("slug") or "").lower()
    if "-1h-" in slug or "-team-total-" in slug:
        return None
    if "-spread-" in slug:
        return "Spread"
    if "-total-" in slug:
        return "Total"
    if NFL_GAME_RE.fullmatch(slug):
        return "Moneyline"
    return None


def select_liquid_main_markets(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select the most liquid active full-game line per type and NFL event."""
    selected: list[dict[str, Any]] = []
    for event in events:
        if not is_nfl_game_event(event):
            continue
        by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for market in event.get("markets") or []:
            raw_type = str(market.get("sportsMarketType") or "").lower()
            if raw_type not in NFL_MAIN_MARKET_TYPES:
                continue
            if market.get("active") is False or market.get("closed") is True:
                continue
            by_type[raw_type].append(market)
        for raw_type, rows in by_type.items():
            winner = max(rows, key=lambda row: number(row.get("volume")))
            selected.append(
                {
                    "event_id": str(event.get("id") or ""),
                    "event_slug": str(event.get("slug") or ""),
                    "event_title": str(event.get("title") or ""),
                    "condition_id": str(winner.get("conditionId") or "").lower(),
                    "market_slug": str(winner.get("slug") or ""),
                    "market_type": market_type(winner),
                    "clob_token_ids": string_list(winner.get("clobTokenIds")),
                    "line": winner.get("line"),
                    "volume_usd": round(number(winner.get("volume")), 4),
                    "liquidity_usd": round(number(winner.get("liquidity")), 4),
                }
            )
    return [row for row in selected if row["condition_id"] and row["market_type"]]


def fetch_active_nfl_markets(limit: int = 200) -> list[dict[str, Any]]:
    payload = get_json(
        EVENTS_URL,
        {
            "tag_slug": "nfl",
            "active": "true",
            "closed": "false",
            "limit": limit,
            "order": "volume",
            "ascending": "false",
        },
    )
    if not isinstance(payload, list):
        raise RuntimeError("Unexpected NFL events payload")
    return select_liquid_main_markets(payload)


def fetch_market_holders(markets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_condition = {row["condition_id"]: row for row in markets}
    by_token = {
        token: row
        for row in markets
        for token in row.get("clob_token_ids") or []
    }
    candidates: dict[str, dict[str, Any]] = {}
    for condition_chunk in chunks(list(by_condition), 20):
        payload = get_json(
            HOLDERS_URL,
            {"market": ",".join(condition_chunk), "limit": 20, "minBalance": 1},
        )
        if not isinstance(payload, list):
            raise RuntimeError("Unexpected NFL holders payload")
        for token_result in payload:
            token_id = str(token_result.get("token") or "")
            market = by_token.get(token_id)
            if not market:
                continue
            condition_id = market["condition_id"]
            for holder in token_result.get("holders") or []:
                address = str(holder.get("proxyWallet") or "").lower()
                if not re.fullmatch(r"0x[a-f0-9]{40}", address):
                    continue
                candidate = candidates.setdefault(
                    address,
                    {
                        "address": address,
                        "label": str(holder.get("pseudonym") or holder.get("name") or ""),
                        "active_nfl_balance": 0.0,
                        "active_conditions": set(),
                        "active_events": set(),
                        "discovery_sources": {"active_nfl_holders"},
                    },
                )
                candidate["active_nfl_balance"] += number(holder.get("amount"))
                candidate["active_conditions"].add(condition_id)
                candidate["active_events"].add(market["event_slug"])
    return candidates


def fetch_sports_leaderboard() -> dict[str, dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for period in ("MONTH", "ALL"):
        for order_by in ("PNL", "VOL"):
            payload = get_json(
                LEADERBOARD_URL,
                {
                    "category": "SPORTS",
                    "timePeriod": period,
                    "orderBy": order_by,
                    "limit": 50,
                    "offset": 0,
                },
            )
            if not isinstance(payload, list):
                raise RuntimeError("Unexpected sports leaderboard payload")
            source = f"sports_leaderboard_{period.lower()}_{order_by.lower()}"
            for row in payload:
                address = str(row.get("proxyWallet") or "").lower()
                if not re.fullmatch(r"0x[a-f0-9]{40}", address):
                    continue
                candidate = candidates.setdefault(
                    address,
                    {
                        "address": address,
                        "label": str(row.get("userName") or ""),
                        "active_nfl_balance": 0.0,
                        "active_conditions": set(),
                        "active_events": set(),
                        "discovery_sources": set(),
                    },
                )
                candidate["discovery_sources"].add(source)
                candidate[f"{period.lower()}_{order_by.lower()}_rank"] = int(
                    number(row.get("rank"), 9999)
                )
                candidate[f"{period.lower()}_pnl"] = number(row.get("pnl"))
                candidate[f"{period.lower()}_volume"] = number(row.get("vol"))
    return candidates


def candidate_priority(row: dict[str, Any]) -> tuple[float, float, int]:
    active = number(row.get("active_nfl_balance"))
    best_rank = min(
        [
            int(value)
            for key, value in row.items()
            if key.endswith("_rank") and int(value) > 0
        ]
        or [9999]
    )
    rank_score = max(0.0, 100.0 - best_rank)
    return (math.log1p(active) * 20.0 + rank_score, active, -best_rank)


def fetch_closed_positions(address: str, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    offset = 0
    while len(results) < limit:
        page_limit = min(50, limit - len(results))
        payload = get_json(
            CLOSED_POSITIONS_URL,
            {
                "user": address,
                "limit": page_limit,
                "offset": offset,
                "sortBy": "TIMESTAMP",
                "sortDirection": "DESC",
            },
        )
        if not isinstance(payload, list):
            raise RuntimeError(f"Unexpected closed positions payload for {address}")
        results.extend(payload)
        if len(payload) < page_limit:
            break
        offset += page_limit
    return results


def fetch_all_positions(address: str, max_rows: int = 20_000) -> list[dict[str, Any]]:
    """Fetch open plus terminal-unredeemed positions without zero-value truncation."""
    results: list[dict[str, Any]] = []
    signatures: set[tuple[str, str]] = set()
    offset = 0
    limit = 500
    while len(results) < max_rows:
        page_limit = min(limit, max_rows - len(results))
        payload = get_json(
            POSITIONS_URL,
            {
                "user": address,
                "limit": page_limit,
                "offset": offset,
                "sizeThreshold": 0,
                "sortBy": "CURRENT",
                "sortDirection": "DESC",
            },
        )
        if not isinstance(payload, list):
            raise RuntimeError(f"Unexpected current positions payload for {address}")
        if not payload:
            break
        signature = (
            str(payload[0].get("asset") or payload[0].get("conditionId") or ""),
            str(payload[-1].get("asset") or payload[-1].get("conditionId") or ""),
        )
        if signature in signatures:
            break
        signatures.add(signature)
        results.extend(payload)
        if len(payload) < page_limit:
            break
        offset += page_limit
    return results


def settled_unredeemed_positions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    settled: list[dict[str, Any]] = []
    for row in rows:
        current_price = number(row.get("curPrice"))
        if not (
            bool(row.get("redeemable"))
            or current_price <= 0.001
            or current_price >= 0.999
        ):
            continue
        normalized = dict(row)
        normalized["realizedPnl"] = number(row.get("cashPnl")) + number(
            row.get("realizedPnl")
        )
        settled.append(normalized)
    return settled


def is_nfl_main_position(row: dict[str, Any]) -> bool:
    event_slug = str(row.get("eventSlug") or "").lower()
    slug = str(row.get("slug") or "").lower()
    if not NFL_GAME_RE.fullmatch(event_slug):
        return False
    if "-1h-" in slug or "-team-total-" in slug:
        return False
    return market_type(row) in {"Moneyline", "Spread", "Total"}


def aggregate_exact_markets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if is_nfl_main_position(row):
            grouped[str(row.get("conditionId") or "")].append(row)

    markets: list[dict[str, Any]] = []
    for condition_id, outcomes in grouped.items():
        sized = [
            (number(row.get("avgPrice")) * number(row.get("totalBought")), row)
            for row in outcomes
        ]
        sized.sort(key=lambda item: item[0], reverse=True)
        leader_cost, leader = sized[0]
        opposing_cost = sum(cost for cost, _ in sized[1:])
        opposing_ratio = opposing_cost / leader_cost if leader_cost else 1.0
        entry = number(leader.get("avgPrice"))
        resolution = number(leader.get("curPrice"))
        if resolution >= 0.999:
            result = "WIN"
            flat_profit = (1.0 - entry) / entry if 0 < entry < 1 else 0.0
        elif resolution <= 0.001:
            result = "LOSS"
            flat_profit = -1.0
        else:
            result = "PUSH"
            flat_profit = 0.0
        markets.append(
            {
                "condition_id": condition_id,
                "event_slug": str(leader.get("eventSlug") or ""),
                "market_slug": str(leader.get("slug") or ""),
                "market_type": market_type(leader),
                "result": result,
                "entry_price": entry,
                "risked_usd": sum(cost for cost, _ in sized),
                "net_directional_risk_usd": max(0.0, leader_cost - opposing_cost),
                "opposing_ratio": opposing_ratio,
                "clean_directional": opposing_ratio <= 0.1,
                "flat_profit_units": flat_profit,
                "realized_pnl_usd": sum(number(row.get("realizedPnl")) for row in outcomes),
                "timestamp": max(int(number(row.get("timestamp"))) for row in outcomes),
            }
        )
    return markets


def summarize_markets(markets: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = [row for row in markets if row["result"] in {"WIN", "LOSS"}]
    wins = sum(row["result"] == "WIN" for row in decisions)
    losses = sum(row["result"] == "LOSS" for row in decisions)
    flat_units = sum(number(row["flat_profit_units"]) for row in decisions)
    risk = sum(number(row["risked_usd"]) for row in decisions)
    pnl = sum(number(row["realized_pnl_usd"]) for row in decisions)
    return {
        "markets": len(markets),
        "decisions": len(decisions),
        "record": f"{wins}-{losses}",
        "hit_rate": round(wins / len(decisions), 6) if decisions else None,
        "flat_copy_profit_units": round(flat_units, 6),
        "flat_copy_roi": round(flat_units / len(decisions), 6) if decisions else None,
        "wallet_turnover_roi": round(pnl / risk, 6) if risk else None,
        "risked_usd": round(risk, 2),
        "realized_pnl_usd": round(pnl, 2),
    }


def analyze_candidate(candidate: dict[str, Any], closed_limit: int) -> dict[str, Any]:
    closed_rows = fetch_closed_positions(candidate["address"], closed_limit)
    current_rows = fetch_all_positions(candidate["address"])
    terminal_rows = settled_unredeemed_positions(current_rows)
    markets = aggregate_exact_markets([*closed_rows, *terminal_rows])
    clean = [row for row in markets if row["clean_directional"]]
    by_type = {
        market: summarize_markets([row for row in clean if row["market_type"] == market])
        for market in ("Moneyline", "Spread", "Total")
    }
    overall = summarize_markets(clean)
    sample = overall["decisions"]
    flat_roi = number(overall.get("flat_copy_roi"), -99.0)
    wallet_roi = number(overall.get("wallet_turnover_roi"), -99.0)
    if sample >= 50 and flat_roi >= 0.05 and wallet_roi > 0:
        status = "PRIORITY_RESEARCH"
    elif sample >= 20 and flat_roi > 0:
        status = "WATCHLIST"
    else:
        status = "INSUFFICIENT_OR_NEGATIVE"
    valid_timestamps = [row["timestamp"] for row in clean if row["timestamp"] > 0]
    first_timestamp = min(valid_timestamps, default=None)
    last_timestamp = max(valid_timestamps, default=None)
    return {
        **candidate,
        "closed_rows_scanned": len(closed_rows),
        "closed_history_capped": len(closed_rows) >= closed_limit,
        "current_position_rows_scanned": len(current_rows),
        "settled_unredeemed_rows_included": len(terminal_rows),
        "nfl_main_markets": overall,
        "nfl_main_markets_by_type": by_type,
        "clean_directional_rate": round(len(clean) / len(markets), 6) if markets else None,
        "coverage_start_utc": (
            datetime.fromtimestamp(first_timestamp, timezone.utc).isoformat()
            if first_timestamp
            else None
        ),
        "coverage_end_utc": (
            datetime.fromtimestamp(last_timestamp, timezone.utc).isoformat()
            if last_timestamp
            else None
        ),
        "research_status": status,
    }


def serializable_candidate(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key in ("active_conditions", "active_events", "discovery_sources"):
        result[key] = sorted(result.get(key) or [])
    result["active_nfl_balance"] = round(number(result.get("active_nfl_balance")), 4)
    return result


def load_wallet_registry(path: Path = WALLETS_PATH) -> dict[str, dict[str, Any]]:
    """Load labels and NFL scope without granting any discovery candidate a role."""
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    registry: dict[str, dict[str, Any]] = {}
    for wallet in payload:
        address = str(wallet.get("address") or "").lower()
        if not address:
            continue
        categories = {
            str(category).upper()
            for category in [
                wallet.get("top_category"),
                *(wallet.get("top_categories") or []),
            ]
            if category
        }
        registry[address] = {
            "already_registered": True,
            "registry_label": str(wallet.get("label") or ""),
            "registry_status": str(wallet.get("registry_status") or ""),
            "registered_nfl_scope": "NFL" in categories,
        }
    return registry


def merge_candidates(
    holders: dict[str, dict[str, Any]],
    leaderboard: dict[str, dict[str, Any]],
    registry: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for source in (leaderboard, holders):
        for address, incoming in source.items():
            current = merged.setdefault(
                address,
                {
                    "address": address,
                    "label": incoming.get("label") or "",
                    "active_nfl_balance": 0.0,
                    "active_conditions": set(),
                    "active_events": set(),
                    "discovery_sources": set(),
                },
            )
            if incoming.get("label") and not current.get("label"):
                current["label"] = incoming["label"]
            current["active_nfl_balance"] = max(
                number(current.get("active_nfl_balance")),
                number(incoming.get("active_nfl_balance")),
            )
            for key in ("active_conditions", "active_events", "discovery_sources"):
                current[key].update(incoming.get(key) or set())
            for key, value in incoming.items():
                if key not in {
                    "address",
                    "label",
                    "active_nfl_balance",
                    "active_conditions",
                    "active_events",
                    "discovery_sources",
                }:
                    current[key] = value
    for address, registry_row in (registry or {}).items():
        if address not in merged and not registry_row["registered_nfl_scope"]:
            continue
        current = merged.setdefault(
            address,
            {
                "address": address,
                "label": "",
                "active_nfl_balance": 0.0,
                "active_conditions": set(),
                "active_events": set(),
                "discovery_sources": set(),
            },
        )
        current.update(registry_row)
        if registry_row.get("registry_label"):
            current["label"] = registry_row["registry_label"]
        if registry_row["registered_nfl_scope"]:
            current["discovery_sources"].add("registry_nfl_benchmark")
    return sorted(merged.values(), key=candidate_priority, reverse=True)


def build_report(candidate_limit: int, closed_limit: int, workers: int) -> dict[str, Any]:
    markets = fetch_active_nfl_markets()
    holders = fetch_market_holders(markets)
    leaderboard = fetch_sports_leaderboard()
    registry = load_wallet_registry()
    ranked_candidates = merge_candidates(holders, leaderboard, registry)
    candidates = ranked_candidates[:candidate_limit]
    selected_addresses = {row["address"] for row in candidates}
    candidates.extend(
        row
        for row in ranked_candidates
        if row.get("registered_nfl_scope") and row["address"] not in selected_addresses
    )

    analyzed: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(analyze_candidate, candidate, closed_limit): candidate
            for candidate in candidates
        }
        for future in as_completed(futures):
            candidate = futures[future]
            try:
                analyzed.append(serializable_candidate(future.result()))
            except Exception as exc:  # preserve partial discovery on one-wallet failure
                try:
                    analyzed.append(
                        serializable_candidate(analyze_candidate(candidate, closed_limit))
                    )
                except Exception as retry_exc:
                    errors.append(
                        {
                            "address": candidate["address"],
                            "error": str(retry_exc),
                            "initial_error": str(exc),
                        }
                    )

    status_rank = {
        "PRIORITY_RESEARCH": 2,
        "WATCHLIST": 1,
        "INSUFFICIENT_OR_NEGATIVE": 0,
    }
    analyzed.sort(
        key=lambda row: (
            status_rank[row["research_status"]],
            int(row["nfl_main_markets"]["decisions"]),
            number(row["nfl_main_markets"].get("flat_copy_roi"), -99.0),
            number(row.get("active_nfl_balance")),
        ),
        reverse=True,
    )
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "policy": {
            "mode": "RESEARCH_ONLY",
            "automatic_registry_write": False,
            "automatic_promotion": False,
            "priority_research_rule": "50+ settled clean NFL main-market decisions, at least 5% flat-copy ROI, and positive wallet turnover ROI",
            "watchlist_rule": "20+ settled clean NFL main-market decisions and positive flat-copy ROI",
            "required_next_step": "Forward-track exact segments with executable prices before any live role review",
        },
        "method": {
            "discovery": "Top holders on the most liquid current full-game NFL moneyline, spread, and total for each active NFL game, plus SPORTS leaderboards for MONTH/ALL by PNL/VOL.",
            "history": f"Newest {closed_limit} public closed-position rows per candidate plus all terminal current-position rows (up to 20,000) to restore settled unredeemed losers.",
            "exact_market_netting": "Select the larger risked outcome per condition ID and classify as clean directional only when opposing risk is no more than 10% of leader risk.",
            "copy_test": "Risk one normalized unit per clean settled full-game NFL moneyline, spread, or total at the wallet's reported average entry price.",
            "limitations": [
                "Closed-position pagination may cap very active multi-sport wallets before older NFL history is reached.",
                "Terminal current-position reconciliation reduces redeemed-only winner bias, but finalists still require the full executed-fill extraction before registry admission.",
                "Holder balances are discovery signals, not proof of NFL skill or copyable execution.",
            ],
        },
        "active_market_sample": {
            "selected_main_markets": len(markets),
            "events": len({row["event_slug"] for row in markets}),
            "markets": markets,
        },
        "candidate_pool": {
            "active_holder_wallets": len(holders),
            "sports_leaderboard_wallets": len(leaderboard),
            "analyzed_wallets": len(analyzed),
            "requested_candidate_limit": candidate_limit,
            "errors": errors,
        },
        "candidates": analyzed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-limit", type=int, default=30)
    parser.add_argument("--closed-limit", type=int, default=2000)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs") / "nfl-wallet-candidates-latest.json",
    )
    args = parser.parse_args()
    report = build_report(
        candidate_limit=max(1, args.candidate_limit),
        closed_limit=max(50, args.closed_limit),
        workers=max(1, args.workers),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(args.output)


if __name__ == "__main__":
    main()
