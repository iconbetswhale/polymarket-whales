from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs" / "cross-sport-source"
OUTPUT = ROOT / "outputs" / "cross-sport-tailability-matrix-2026-08-09.json"


SOCCER_PREFIXES = {
    "arg", "bra", "bun", "bundesliga", "cde", "chi", "col", "den",
    "dfb", "efa", "elc", "english", "epl", "ere", "fed", "fif",
    "fifwc", "fl1", "itc", "j1100", "lal", "laliga", "lib", "ligue1",
    "mex", "mls", "nor", "por", "sea", "serie", "spl", "sud", "tur",
    "ucl", "uefa", "uel",
}
TENNIS_PREFIXES = {"atp", "challenger", "itf", "utr", "wta"}
ESPORT_PREFIXES = {"cs2", "dota2", "lol", "val", "valorant"}
CRICKET_PREFIXES = {"cric", "cricipl", "cricodc", "crict20", "cricw"}


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def position_cost(row: dict[str, Any]) -> float:
    initial = number(row.get("initialValue"))
    return initial if initial > 0 else number(row.get("totalBought")) * number(row.get("avgPrice"))


def classify_sport(row: dict[str, Any]) -> str:
    slug = str(row.get("eventSlug") or row.get("slug") or "").lower()
    prefix = slug.split("-", 1)[0]
    direct = {
        "mlb": "MLB", "kbo": "KBO", "npb": "NPB",
        "nba": "NBA", "wnba": "WNBA", "cbb": "College Basketball",
        "ncaab": "College Basketball", "nfl": "NFL", "ncaaf": "College Football",
        "cfb": "College Football", "nhl": "NHL", "ufc": "UFC/MMA",
        "mma": "UFC/MMA", "boxing": "Boxing", "f1": "Formula 1",
        "golf": "Golf", "pga": "Golf", "btc": "Crypto", "eth": "Crypto",
    }
    if prefix in direct:
        return direct[prefix]
    if prefix in SOCCER_PREFIXES:
        return "Soccer"
    if prefix in TENNIS_PREFIXES:
        return "Tennis"
    if prefix in ESPORT_PREFIXES:
        return "Esports"
    if prefix in CRICKET_PREFIXES or prefix.startswith("cric"):
        return "Cricket"
    icon = str(row.get("icon") or "").lower()
    title = str(row.get("title") or "").lower()
    if "tennis" in icon or any(token in title for token in ("atp ", "wta ", "itf ")):
        return "Tennis"
    if "soccer" in icon or "football" in icon:
        return "Soccer"
    return "Other"


def classify_market(row: dict[str, Any]) -> str:
    slug = str(row.get("slug") or "").lower()
    title = str(row.get("title") or "").lower()
    if "-total-" in slug or "o/u " in title or "total" in title:
        return "Total"
    if "-spread-" in slug or title.startswith("spread:"):
        return "Spread"
    if "nrfi" in slug or "first inning" in title:
        return "NRFI/YRFI"
    return "Moneyline"


def aggregate_markets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = str(row.get("conditionId") or row.get("asset") or "").lower()
        if key:
            grouped[key].append(row)

    markets: list[dict[str, Any]] = []
    for condition_id, items in grouped.items():
        outcomes: dict[str, dict[str, float]] = defaultdict(
            lambda: {"cost": 0.0, "shares": 0.0, "pnl": 0.0, "cur_price": -1.0}
        )
        for item in items:
            outcome = str(item.get("outcome") or item.get("asset") or "")
            values = outcomes[outcome]
            values["cost"] += position_cost(item)
            values["shares"] += number(item.get("totalBought"))
            values["pnl"] += number(item.get("realizedPnl"))
            values["cur_price"] = max(values["cur_price"], number(item.get("curPrice")))
        ordered = sorted(outcomes.items(), key=lambda pair: pair[1]["cost"], reverse=True)
        if not ordered:
            continue
        leader, leader_values = ordered[0]
        opposition = sum(values["cost"] for _, values in ordered[1:])
        ratio = opposition / leader_values["cost"] if leader_values["cost"] else math.inf
        status = (
            "CLEAN_DIRECTIONAL" if ratio < 0.10 else
            "MINOR_HEDGE" if ratio <= 0.20 else
            "MATERIAL_HEDGE" if ratio <= 0.50 else
            "TWO_SIDED"
        )
        entry = leader_values["cost"] / leader_values["shares"] if leader_values["shares"] else 0.0
        resolved = all(values["cur_price"] <= 0.01 or values["cur_price"] >= 0.99 for values in outcomes.values())
        won = leader_values["cur_price"] >= 0.99
        flat_profit = None
        if resolved and 0 < entry < 1:
            flat_profit = (1 - entry) / entry if won else -1.0
        sample = items[0]
        markets.append({
            "condition_id": condition_id,
            "sport": classify_sport(sample),
            "market": classify_market(sample),
            "status": status,
            "opposing_ratio": ratio,
            "entry_price": entry,
            "won": won,
            "flat_profit_units": flat_profit,
            "risked_usd": sum(values["cost"] for values in outcomes.values()),
            "pnl_usd": sum(values["pnl"] for values in outcomes.values()),
        })
    return markets


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    resolved = [row for row in rows if row["flat_profit_units"] is not None]
    risked = sum(number(row["risked_usd"]) for row in rows)
    pnl = sum(number(row["pnl_usd"]) for row in rows)
    flat_profit = sum(number(row["flat_profit_units"]) for row in resolved)
    return {
        "markets": len(rows),
        "resolved_flat_bets": len(resolved),
        "wins": sum(bool(row["won"]) for row in resolved),
        "account_risked_usd": risked,
        "account_pnl_usd": pnl,
        "account_roi": pnl / risked if risked else None,
        "flat_tail_profit_units": flat_profit,
        "flat_tail_roi": flat_profit / len(resolved) if resolved else None,
        "median_entry_price": sorted(number(row["entry_price"]) for row in resolved)[len(resolved) // 2] if resolved else None,
    }


def main() -> None:
    result: dict[str, Any] = {"method": {}, "wallets": {}}
    for path in sorted(SOURCE.glob("*-closed.json")):
        name = path.name.removesuffix("-closed.json")
        raw = json.loads(path.read_text(encoding="utf-8"))
        closed_row_count = len(raw) if isinstance(raw, list) else 0
        current_path = SOURCE / f"{name}-current.json"
        settled_unredeemed: list[dict[str, Any]] = []
        if current_path.exists():
            current = json.loads(current_path.read_text(encoding="utf-8"))
            for row in current if isinstance(current, list) else []:
                if not isinstance(row, dict):
                    continue
                cur_price = number(row.get("curPrice"))
                if not (bool(row.get("redeemable")) or cur_price <= 0.001 or cur_price >= 0.999):
                    continue
                normalized = dict(row)
                normalized["realizedPnl"] = number(row.get("cashPnl")) + number(row.get("realizedPnl"))
                settled_unredeemed.append(normalized)
            raw.extend(settled_unredeemed)
        markets = aggregate_markets([row for row in raw if isinstance(row, dict)])
        eligible = [row for row in markets if row["status"] in {"CLEAN_DIRECTIONAL", "MINOR_HEDGE"}]
        by_segment: dict[str, Any] = {}
        segment_keys = sorted({(row["sport"], row["market"]) for row in eligible})
        for sport, market in segment_keys:
            segment = [row for row in eligible if row["sport"] == sport and row["market"] == market]
            by_segment[f"{sport} / {market}"] = summarize(segment)
        by_sport = {
            sport: summarize([row for row in eligible if row["sport"] == sport])
            for sport in sorted({row["sport"] for row in eligible})
        }
        counts = Counter(row["status"] for row in markets)
        result["wallets"][name] = {
            "closed_rows": closed_row_count,
            "total_settled_rows_analyzed": len(raw),
            "settled_unredeemed_rows_included": len(settled_unredeemed),
            "closed_history_capped": len(raw) >= 5000,
            "exact_markets": len(markets),
            "direction_counts": dict(counts),
            "clean_or_minor_rate": (
                (counts["CLEAN_DIRECTIONAL"] + counts["MINOR_HEDGE"]) / len(markets)
                if markets else None
            ),
            "clean_or_minor_overall": summarize(eligible),
            "by_sport": by_sport,
            "by_sport_and_market": by_segment,
        }
    result["method"] = {
        "position_rule": "Aggregate all settled rows by exact condition and outcome; tail the largest residual outcome.",
        "direction_rule": "Include clean (<10% opposing cost) and minor-hedge (<=20%) markets only.",
        "flat_tail_rule": "Risk one unit at the wallet's dominant-outcome average entry price.",
        "important_limitation": "This is a settled-position transferability screen, not a timestamp-perfect follower backtest. Capped histories and late-entry strategies require separate validation.",
        "settlement_scope": "Includes settled unredeemed current-position rows when a matching current-position source file is present.",
    }
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
