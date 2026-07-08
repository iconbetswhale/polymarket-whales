"""
app.py — Polymarket Whales dashboard
Sports-only, resolves within 24 hours, conviction-scored.
Wallet list comes from top_wallets.json (built by ingest_top_wallets.py).
Same UI as PolyTrack — no SQLite needed, conviction uses in-memory fallback.
"""

import json, os, statistics, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import requests
from flask import Flask, jsonify, render_template_string
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
POSITIONS_API    = "https://data-api.polymarket.com/positions"
WALLETS_FILE     = Path("top_wallets.json")
REFRESH_SECONDS  = int(os.getenv("DASHBOARD_REFRESH", "120"))
PORT             = int(os.getenv("DASHBOARD_PORT", "5000"))
RESOLVE_HOURS    = 24   # only positions expiring within 24 hours
MY_BASE_UNIT     = float(os.getenv("MY_BASE_UNIT", "50"))
MIN_AMERICAN_ODDS = -250
MAX_AMERICAN_ODDS = 250

# Populated at startup from top_wallets.json
WALLETS: dict[str, str] = {}      # addr → label
WALLET_META: dict[str, dict] = {} # addr → full record (win_rate, overall_gain, …)

# ── Category classifier ───────────────────────────────────────────────────────
CATEGORY_RULES = [
    ("wnba",              "WNBA"),
    ("nba",               "NBA"),
    ("nfl",               "NFL"),
    ("mlb",               "MLB"),
    ("nhl",               "NHL"),
    ("fifwc",             "FIFA WC"),
    ("world-cup",         "FIFA WC"),
    ("world cup",         "FIFA WC"),
    ("epl",               "Soccer"),
    ("ucl",               "Soccer"),
    ("laliga",            "Soccer"),
    ("premier-league",    "Soccer"),
    ("premier league",    "Soccer"),
    ("champions-league",  "Soccer"),
    ("champions league",  "Soccer"),
    ("mls",               "Soccer"),
    ("serie-a",           "Soccer"),
    ("bundesliga",        "Soccer"),
    ("ligue-1",           "Soccer"),
    ("ufc",               "UFC/MMA"),
    ("mma",               "UFC/MMA"),
    ("bellator",          "UFC/MMA"),
    ("tennis",            "Tennis"),
    ("wimbledon",         "Tennis"),
    ("atp",               "Tennis"),
    ("wta",               "Tennis"),
    ("us-open",           "Tennis"),
    ("french-open",       "Tennis"),
    ("australian-open",   "Tennis"),
    ("formula-1",         "F1"),
    ("formula1",          "F1"),
    ("grand-prix",        "F1"),
    ("pga",               "Golf"),
    (" golf",             "Golf"),
    ("masters",           "Golf"),
    ("ryder",             "Golf"),
    ("ncaab",             "NCAAB"),
    ("march-madness",     "NCAAB"),
    ("ncaaf",             "NCAAF"),
    ("college-football",  "NCAAF"),
    ("valorant",          "Esports"),
    ("csgo",              "Esports"),
    ("cs2",               "Esports"),
    ("league-of-legends", "Esports"),
    ("dota",              "Esports"),
    ("boxing",            "Boxing"),
]


def classify_category(title: str, event_slug: str) -> str:
    text = f"{event_slug} {title}".lower()
    for kw, cat in CATEGORY_RULES:
        if kw in text:
            return cat
    return "Other"


# ── Math helpers ──────────────────────────────────────────────────────────────
def as_float(value, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def percentile_score(value: float, samples: list) -> int:
    values = sorted(as_float(v) for v in samples if as_float(v) > 0)
    if not values or value <= 0:
        return 50
    less  = sum(1 for v in values if v < value)
    equal = sum(1 for v in values if v == value)
    return round(clamp((less + 0.5 * equal) / len(values) * 100))


def american_odds_from_cents(cents: float) -> str:
    p = as_float(cents) / 100
    if p <= 0 or p >= 1:
        return "n/a"
    if p >= 0.5:
        return str(round(-100 * p / (1 - p)))
    return f"+{round(100 * (1 - p) / p)}"


def american_odds_value_from_cents(cents: float) -> Optional[int]:
    odds = american_odds_from_cents(cents)
    if odds == "n/a":
        return None
    return int(odds.replace("+", ""))


def cents_from_american_odds(odds: int) -> float:
    if odds < 0:
        return abs(odds) / (abs(odds) + 100) * 100
    return 100 / (odds + 100) * 100


def odds_in_range(cents: float) -> bool:
    low_cents  = cents_from_american_odds(MAX_AMERICAN_ODDS)
    high_cents = cents_from_american_odds(MIN_AMERICAN_ODDS)
    return low_cents <= cents <= high_cents


def first_float(data: dict, keys: tuple, default=None):
    for key in keys:
        if key in data and data[key] is not None:
            return as_float(data[key])
    return default


def is_resolved_position(position: dict) -> bool:
    cur_price = position.get("curPrice")
    return bool(position.get("redeemable", False)) or (
        cur_price is not None and as_float(cur_price) <= 0
    )


def row_pl_components(position: dict) -> tuple[float, float]:
    cash_pnl = as_float(position.get("cashPnl"))
    realized   = first_float(position, ("realizedPnl",   "realizedPnL",   "realizedPL",   "realized_pl"))
    unrealized = first_float(position, ("unrealizedPnl", "unrealizedPnL", "unrealizedPL", "unrealized_pl"))
    if realized is None and unrealized is None:
        if is_resolved_position(position):
            return cash_pnl, 0.0
        return 0.0, cash_pnl
    return realized or 0.0, unrealized or 0.0


# ── Position builder ──────────────────────────────────────────────────────────
def build_position_row(addr: str, label: str, position: dict, category: str, port_total: float) -> dict:
    initial        = as_float(position.get("initialValue"))
    cur_val        = as_float(position.get("currentValue"))
    shares         = as_float(position.get("size") or position.get("shares"))
    realized_pl, unrealized_pl = row_pl_components(position)
    row_pl         = realized_pl + unrealized_pl
    row_roi_pct    = row_pl / initial * 100 if initial > 0 else 0.0
    pct_port       = round(cur_val / port_total * 100, 1) if port_total > 0 else 0.0
    avg_price      = round(as_float(position.get("avgPrice")) * 100, 1)
    cur_price      = round(as_float(position.get("curPrice")) * 100, 1)
    if shares <= 0 and avg_price > 0:
        shares = initial / (avg_price / 100)

    resolved = is_resolved_position(position)
    win  = 1 if resolved and (realized_pl > 0 or bool(position.get("redeemable", False))) else 0
    loss = 1 if resolved and not win and (
        realized_pl < 0 or as_float(position.get("curPrice"), 1.0) <= 0
    ) else 0

    condition_id = position.get("conditionId") or position.get("condition_id")
    event_slug   = position.get("eventSlug") or position.get("event_slug") or ""
    event_id     = position.get("eventId") or position.get("event_id") or event_slug
    asset_id     = position.get("asset") or position.get("assetId")
    market_id    = condition_id or event_id or position.get("slug") or position.get("title", "?")
    source_link  = f"https://polymarket.com/event/{event_slug}" if event_slug else ""

    # Wallet-level historical data from top_wallets.json
    meta         = WALLET_META.get(addr, {})
    hist_win_rate = as_float(meta.get("roi")) * 100  # PMA win_rate is 0-1
    hist_gain    = as_float(meta.get("overall_gain"))

    return {
        "wallet":             label,
        "addr":               addr,
        "category":           category,
        "market":             position.get("title", "?"),
        "market_id":          str(market_id),
        "condition_id":       str(condition_id or ""),
        "asset_id":           str(asset_id or ""),
        "event_id":           str(event_id or ""),
        "event_slug":         str(event_slug or ""),
        "row_id":             condition_id or asset_id or position.get("slug") or position.get("title", "?"),
        "outcome":            position.get("outcome", "?"),
        "side":               position.get("outcome", "?"),
        "end_date":           (position.get("endDate") or "")[:10],
        "resolution_time":    position.get("endDate") or "",
        "last_activity_ts":   position.get("lastTradePriceTimestamp") or position.get("timestamp") or "",
        "source_link":        source_link,
        "avg_price":          avg_price,
        "cur_price":          cur_price,
        "avg_odds":           american_odds_from_cents(avg_price),
        "cur_odds":           american_odds_from_cents(cur_price),
        "avg_odds_value":     american_odds_value_from_cents(avg_price),
        "cur_odds_value":     american_odds_value_from_cents(cur_price),
        "size_usd":           round(initial, 2),
        "shares":             round(shares, 4),
        "current_value":      round(cur_val, 2),
        "row_cost":           round(initial, 2),
        "row_current_value":  round(cur_val, 2),
        "row_realized_pl":    round(realized_pl, 2),
        "row_unrealized_pl":  round(unrealized_pl, 2),
        "row_pl":             round(row_pl, 2),
        "row_roi_pct":        round(row_roi_pct, 2),
        "row_win":            win,
        "row_loss":           loss,
        "pct_portfolio":      pct_port,
        "port_total":         round(port_total, 2),
        "category_win_rate_pct": round(hist_win_rate, 2),
        "category_roi_pct":   round(hist_gain / 1_000_000 * 10, 2) if hist_gain > 0 else 0.0,
        "category_wins":      int(as_float(meta.get("trades_count", 0)) * hist_win_rate / 100) if hist_win_rate else 0,
        "category_losses":    0,
        "category_wins_losses": "",
        "category_markets":   int(as_float(meta.get("trades_count", 0))),
        "category_total_pl":  round(hist_gain, 2),
        "category_analytics_source": "top_wallets_json",
        "conviction":         50,   # filled by attach_conviction_scores
        "tail_stake":         round(MY_BASE_UNIT * 0.5, 2),
        "sharp_wallet_count": 1,
        "other_sharp_wallet_count": 0,
        "sharp_wallets":      label,
        "wallet_avg_position_size": 0.0,
        "category_avg_position_size": 0.0,
        "position_size_multiple": 1.0,
        "category_position_size_multiple": 1.0,
    }


# ── Conviction scoring (in-memory, mirrors PolyTrack) ────────────────────────
def category_skill_score(row: dict) -> int:
    markets  = as_float(row.get("category_markets"))
    win_rate = as_float(row.get("category_win_rate_pct"))
    if markets <= 0 or win_rate <= 0:
        return 50
    raw        = clamp(50 + (win_rate - 50) * 2)
    confidence = min(1.0, (markets ** 0.5) / 10)
    return round(50 + (raw - 50) * confidence)


def concentration_score(row: dict) -> int:
    return round(clamp(as_float(row.get("pct_portfolio")) / 10 * 100))


def sharp_consensus_score(row: dict) -> int:
    return round(clamp(50 + as_float(row.get("other_sharp_wallet_count")) * 20))


def attach_conviction_scores(rows: list, wallet_sizes: dict, category_sizes: dict) -> list:
    for row in rows:
        wsizes  = wallet_sizes.get(row["addr"], [row["row_cost"]])
        csizes  = category_sizes.get((row["addr"], row["category"]), [row["row_cost"]])
        w_avg   = statistics.mean(wsizes)  if wsizes  else row["row_cost"]
        c_avg   = statistics.mean(csizes)  if csizes  else row["row_cost"]

        size_score     = percentile_score(row["row_cost"], wsizes)
        cat_size_score = percentile_score(row["row_cost"], csizes)
        skill          = category_skill_score(row)
        concentration  = concentration_score(row)
        consensus      = sharp_consensus_score(row)

        conviction = round(
            0.25 * size_score
            + 0.20 * cat_size_score
            + 0.25 * skill
            + 0.15 * concentration
            + 0.15 * consensus
        )

        row.update({
            "size_score":              size_score,
            "category_size_score":     cat_size_score,
            "skill_score":             skill,
            "concentration_score":     concentration,
            "sharp_consensus_score":   consensus,
            "wallet_avg_position_size":    round(w_avg, 2),
            "category_avg_position_size":  round(c_avg, 2),
            "position_size_multiple":      round(row["row_cost"] / w_avg, 2) if w_avg > 0 else 0.0,
            "category_position_size_multiple": round(row["row_cost"] / c_avg, 2) if c_avg > 0 else 0.0,
            "conviction":  round(clamp(conviction)),
            "tail_stake":  round(MY_BASE_UNIT * clamp(conviction) / 100, 2),
        })
    return rows


# ── Card collapsing (mirrors PolyTrack exactly) ───────────────────────────────
def position_key(row: dict) -> tuple:
    return (str(row.get("row_id", "")), row.get("outcome", "?"))


def same_market(row: dict, market_id: str, category=None, resolution_time=None) -> bool:
    if str(row.get("market_id", "")) != str(market_id):
        return False
    if category and row.get("category") != category:
        return False
    if resolution_time and row.get("resolution_time") and row.get("resolution_time") != resolution_time:
        return False
    return True


def aggregate_wallet_position(rows: list) -> dict:
    first         = rows[0]
    total_cost    = sum(as_float(r.get("row_cost")) for r in rows)
    total_value   = sum(as_float(r.get("row_current_value")) for r in rows)
    total_shares  = sum(as_float(r.get("shares")) for r in rows)
    realized_pl   = sum(as_float(r.get("row_realized_pl")) for r in rows)
    unrealized_pl = sum(as_float(r.get("row_unrealized_pl")) for r in rows)
    total_pl      = realized_pl + unrealized_pl
    roi_pct       = total_pl / total_cost * 100 if total_cost > 0 else 0.0
    w_entry = (
        sum(as_float(r.get("avg_price")) * as_float(r.get("row_cost")) for r in rows) / total_cost
        if total_cost > 0 else as_float(first.get("avg_price"))
    )
    w_current = (
        sum(as_float(r.get("cur_price")) * as_float(r.get("row_current_value")) for r in rows) / total_value
        if total_value > 0 else as_float(first.get("cur_price"))
    )
    port_total   = as_float(first.get("port_total"))
    w_avg        = as_float(first.get("wallet_avg_position_size")) or total_cost
    cat_pl       = as_float(first.get("category_total_pl"))
    cat_roi      = as_float(first.get("category_roi_pct"))
    cat_wr       = as_float(first.get("category_win_rate_pct"))
    source_link  = first.get("source_link", "")
    return {
        "wallet":                    first.get("wallet"),
        "addr":                      first.get("addr"),
        "side":                      first.get("side") or first.get("outcome"),
        "outcome":                   first.get("outcome"),
        "entry_price":               round(w_entry, 2),
        "entry_odds":                american_odds_from_cents(w_entry),
        "current_price":             round(w_current, 2),
        "current_odds":              american_odds_from_cents(w_current),
        "position_size":             round(total_cost, 2),
        "shares":                    round(total_shares, 4),
        "cost_basis":                round(total_cost, 2),
        "current_value":             round(total_value, 2),
        "unrealized_pl":             round(unrealized_pl, 2),
        "realized_pl":               round(realized_pl, 2),
        "total_pl":                  round(total_pl, 2),
        "roi_pct":                   round(roi_pct, 2),
        "portfolio_size":            port_total,
        "wallet_total_portfolio_value": port_total,
        "portfolio_pct":             round(total_value / port_total * 100, 2) if port_total > 0 else 0.0,
        "wallet_avg_position_size":  round(w_avg, 2),
        "position_size_multiple":    round(total_cost / w_avg, 2) if w_avg > 0 else 0.0,
        "category_avg_position_size": round(as_float(first.get("category_avg_position_size")), 2),
        "category_position_size_multiple": round(total_cost / max(as_float(first.get("category_avg_position_size")), 0.01), 2),
        "wallet_category_portfolio_value": 0.0,
        "wallet_category_pl":        round(cat_pl, 2),
        "wallet_category_roi_pct":   round(cat_roi, 2),
        "wallet_category_total_volume": 0.0,
        "wallet_category_resolved_volume": 0.0,
        "wallet_historical_win_rate": cat_wr,
        "wallet_historical_roi":     round(cat_roi, 2),
        "wallet_category_specific_roi": round(cat_roi, 2),
        "wallet_category_stats_source": "top_wallets_json",
        "sharp_for_category":        cat_wr >= 52,
        "position_conviction":       max(as_float(r.get("conviction")) for r in rows),
        "wallet_conviction_contribution": max(as_float(r.get("sharp_consensus_score")) for r in rows),
        "last_activity_timestamp":   max(str(r.get("last_activity_ts") or "") for r in rows),
        "source_link":               source_link,
        "duplicate_fill_count":      len(rows),
    }


def get_position_wallet_details(rows: list, market_id: str, outcome_side: str, category=None, resolution_time=None) -> dict:
    market_rows = [r for r in rows if same_market(r, market_id, category=category, resolution_time=resolution_time)]
    grouped: dict[tuple, list] = {}
    for row in market_rows:
        key = (row.get("addr"), row.get("side") or row.get("outcome"))
        grouped.setdefault(key, []).append(row)

    wallet_rows = [aggregate_wallet_position(items) for items in grouped.values()]
    aligned  = sorted([r for r in wallet_rows if r["side"] == outcome_side],  key=lambda r: r["position_size"], reverse=True)
    opposing = sorted([r for r in wallet_rows if r["side"] != outcome_side],  key=lambda r: r["position_size"], reverse=True)

    selected         = next((r for r in market_rows if (r.get("side") or r.get("outcome")) == outcome_side), market_rows[0] if market_rows else {})
    aligned_exposure = sum(as_float(r["position_size"]) for r in aligned)
    opposing_exposure= sum(as_float(r["position_size"]) for r in opposing)
    avg_cat_roi      = statistics.mean([as_float(r["wallet_category_roi_pct"]) for r in aligned]) if aligned else 0.0
    final_conv       = max([as_float(r["position_conviction"]) for r in aligned], default=0.0)

    return {
        "summary": {
            "market_id":                   str(market_id),
            "market_title":                selected.get("market", ""),
            "category":                    selected.get("category", category or ""),
            "selected_side":               outcome_side,
            "resolution_time":             selected.get("resolution_time", resolution_time or ""),
            "aligned_sharp_wallet_count":  len(aligned),
            "aligned_wallet_count":        len(aligned),
            "total_aligned_exposure":      round(aligned_exposure, 2),
            "average_aligned_wallet_roi":  0.0,
            "average_aligned_category_roi": round(avg_cat_roi, 2),
            "opposing_sharp_wallet_count": len(opposing),
            "opposing_wallet_count":       len(opposing),
            "opposing_exposure":           round(opposing_exposure, 2),
            "net_sharp_alignment":         len(aligned) - len(opposing),
            "net_sharp_exposure":          round(aligned_exposure - opposing_exposure, 2),
            "final_conviction_score":      round(final_conv),
        },
        "aligned_wallets":  aligned,
        "opposing_wallets": opposing,
    }


def attach_sharp_wallet_counts(display_rows: list, source_rows: list) -> list:
    holders: dict[tuple, dict] = {}
    for row in source_rows:
        key = position_key(row)
        holders.setdefault(key, {})[row["addr"]] = row["wallet"]
    for row in display_rows:
        holder = holders.get(position_key(row), {})
        row["sharp_wallet_count"]       = len(holder)
        row["other_sharp_wallet_count"] = max(0, len(holder) - 1)
        row["sharp_wallets"]            = ", ".join(sorted(holder.values()))
    return display_rows


def attach_position_details(display_rows: list, source_rows: list) -> list:
    cache = {}
    for row in display_rows:
        key = (row.get("market_id"), row.get("side") or row.get("outcome"), row.get("category"), row.get("resolution_time"))
        if key not in cache:
            cache[key] = get_position_wallet_details(source_rows, key[0], key[1], category=key[2], resolution_time=key[3])
        row["position_details"] = cache[key]
        s = cache[key]["summary"]
        row["aligned_sharp_wallet_count"]  = s.get("aligned_sharp_wallet_count", 0)
        row["opposing_sharp_wallet_count"] = s.get("opposing_sharp_wallet_count", 0)
        row["net_sharp_alignment"]         = s.get("net_sharp_alignment", 0)
        row["net_sharp_exposure"]          = s.get("net_sharp_exposure", 0)
        row["conviction"]  = s.get("final_conviction_score", row.get("conviction", 0))
        row["tail_stake"]  = round(MY_BASE_UNIT * as_float(row["conviction"]) / 100, 2)
    return display_rows


def position_card_key(row: dict) -> tuple:
    return (str(row.get("market_id", "")), str(row.get("event_id", "")), row.get("side") or row.get("outcome"), row.get("category"), row.get("resolution_time") or row.get("end_date") or "")


def collapse_position_cards(rows: list) -> list:
    grouped: dict[tuple, list] = {}
    for row in rows:
        grouped.setdefault(position_card_key(row), []).append(row)

    cards = []
    for group_rows in grouped.values():
        rep   = max(group_rows, key=lambda r: as_float(r.get("current_value")))
        card  = rep.copy()
        details = card.get("position_details") or {}
        summary = details.get("summary", {})
        aligned = details.get("aligned_wallets", [])

        wallet_names  = sorted({w.get("wallet") for w in aligned if w.get("wallet")})
        wallet_addrs  = sorted({w.get("addr") for w in aligned if w.get("addr")})
        aligned_cost  = sum(as_float(w.get("cost_basis")) for w in aligned)
        aligned_value = sum(as_float(w.get("current_value")) for w in aligned)
        aligned_real  = sum(as_float(w.get("realized_pl")) for w in aligned)
        aligned_unreal= sum(as_float(w.get("unrealized_pl")) for w in aligned)
        aligned_pl    = aligned_real + aligned_unreal
        aligned_port  = sum(as_float(w.get("wallet_total_portfolio_value")) for w in aligned)
        cat_roi_samples = [as_float(w.get("wallet_category_roi_pct")) for w in aligned if w.get("wallet_category_roi_pct") is not None]
        wr_samples     = [as_float(w.get("wallet_historical_win_rate")) for w in aligned if w.get("wallet_historical_win_rate") is not None]

        wallet_label = wallet_names[0] if len(wallet_names) == 1 else (f"{len(wallet_names)} aligned" if wallet_names else card.get("wallet", ""))

        card.update({
            "position_card":               True,
            "wallet":                      wallet_label,
            "wallets":                     wallet_names,
            "wallet_addresses":            wallet_addrs,
            "sharp_wallets":               ", ".join(wallet_names),
            "sharp_wallet_count":          len(wallet_names),
            "other_sharp_wallet_count":    max(0, len(wallet_names) - 1),
            "aligned_sharp_wallet_count":  summary.get("aligned_sharp_wallet_count", len(wallet_names)),
            "opposing_sharp_wallet_count": summary.get("opposing_sharp_wallet_count", 0),
            "net_sharp_alignment":         summary.get("net_sharp_alignment", 0),
            "net_sharp_exposure":          summary.get("net_sharp_exposure", 0),
            "size_usd":                    round(aligned_cost, 2),
            "current_value":               round(aligned_value, 2),
            "row_cost":                    round(aligned_cost, 2),
            "row_current_value":           round(aligned_value, 2),
            "row_realized_pl":             round(aligned_real, 2),
            "row_unrealized_pl":           round(aligned_unreal, 2),
            "row_pl":                      round(aligned_pl, 2),
            "row_roi_pct":                 round(aligned_pl / aligned_cost * 100, 2) if aligned_cost > 0 else 0.0,
            "pct_portfolio":               round(aligned_value / aligned_port * 100, 2) if aligned_port > 0 else 0.0,
            "category_roi_pct":            round(statistics.mean(cat_roi_samples), 2) if cat_roi_samples else 0.0,
            "category_win_rate_pct":       round(statistics.mean(wr_samples), 2) if wr_samples else card.get("category_win_rate_pct", 0.0),
            "conviction":                  summary.get("final_conviction_score", card.get("conviction", 0)),
        })
        card["tail_stake"] = round(MY_BASE_UNIT * as_float(card.get("conviction")) / 100, 2)
        cards.append(card)
    return cards


def _side_weighted_exposure(card: dict) -> float:
    wallets = (card.get("position_details") or {}).get("aligned_wallets") or []
    if wallets:
        return sum(as_float(w.get("position_size")) * max(as_float(w.get("position_size_multiple") or 1), 0.1) for w in wallets)
    return as_float(card.get("size_usd") or card.get("row_cost")) * max(as_float(card.get("position_size_multiple") or 1), 0.1)


def dedup_by_market(cards: list) -> list:
    grouped: dict[tuple, list] = {}
    for card in cards:
        key = (str(card.get("market_id", "")), card.get("category", ""), card.get("resolution_time") or card.get("end_date") or "")
        grouped.setdefault(key, []).append(card)

    result = []
    for siblings in grouped.values():
        if len(siblings) == 1:
            result.append(siblings[0])
            continue
        siblings.sort(key=_side_weighted_exposure, reverse=True)
        dominant  = siblings[0]
        dom_we    = _side_weighted_exposure(dominant)
        other_we  = sum(_side_weighted_exposure(s) for s in siblings[1:])
        total_we  = dom_we + other_we
        consensus = max(0.0, (dom_we - other_we) / total_we) if total_we > 0 else 1.0
        raw_conv  = as_float(dominant.get("conviction"))
        adj_conv  = max(1, round(raw_conv * (0.5 + 0.5 * consensus)))
        opposing_wallets = sum(len((s.get("position_details") or {}).get("aligned_wallets") or [s]) for s in siblings[1:])
        dominant["conviction"]                  = adj_conv
        dominant["tail_stake"]                  = round(MY_BASE_UNIT * adj_conv / 100, 2)
        dominant["opposing_sharp_wallet_count"] = opposing_wallets
        dominant["net_sharp_alignment"]         = int(as_float(dominant.get("aligned_sharp_wallet_count")) - opposing_wallets)
        result.append(dominant)
    return result


def collapse_by_event(cards: list) -> list:
    grouped: dict[tuple, list] = {}
    for card in cards:
        event = card.get("event_slug") or card.get("event_id") or str(card.get("market_id", ""))
        key   = (event, card.get("category", ""), card.get("resolution_time") or card.get("end_date") or "")
        grouped.setdefault(key, []).append(card)

    result = []
    for group_cards in grouped.values():
        if len(group_cards) == 1:
            result.append(group_cards[0])
            continue
        rep  = max(group_cards, key=lambda c: as_float(c.get("conviction")))
        card = rep.copy()
        total_cost    = sum(as_float(c.get("size_usd") or c.get("row_cost")) for c in group_cards)
        total_value   = sum(as_float(c.get("current_value") or c.get("row_current_value")) for c in group_cards)
        total_real    = sum(as_float(c.get("row_realized_pl")) for c in group_cards)
        total_unreal  = sum(as_float(c.get("row_unrealized_pl")) for c in group_cards)
        total_pl      = total_real + total_unreal
        all_wallets: set = set()
        all_addrs: set   = set()
        for c in group_cards:
            all_wallets.update(c.get("wallets") or ([c.get("wallet")] if c.get("wallet") else []))
            all_addrs.update(c.get("wallet_addresses") or ([c.get("addr")] if c.get("addr") else []))
        event_slug  = rep.get("event_slug", "")
        event_title = " ".join(w.capitalize() for w in event_slug.split("-")) if event_slug else rep.get("market", "?")
        wallet_label = f"{len(all_wallets)} aligned" if len(all_wallets) > 1 else rep.get("wallet", "")
        card.update({
            "market":             event_title,
            "outcome":            "Multi",
            "side":               "Multi",
            "event_market_count": len(group_cards),
            "sub_markets":        [c.get("market", "") for c in group_cards],
            "wallet":             wallet_label,
            "wallets":            sorted(all_wallets),
            "wallet_addresses":   sorted(all_addrs),
            "sharp_wallets":      ", ".join(sorted(all_wallets)),
            "sharp_wallet_count": len(all_wallets),
            "size_usd":           round(total_cost, 2),
            "current_value":      round(total_value, 2),
            "row_cost":           round(total_cost, 2),
            "row_current_value":  round(total_value, 2),
            "row_realized_pl":    round(total_real, 2),
            "row_unrealized_pl":  round(total_unreal, 2),
            "row_pl":             round(total_pl, 2),
            "row_roi_pct":        round(total_pl / total_cost * 100, 2) if total_cost > 0 else 0.0,
            "avg_price":          0, "cur_price": 0, "avg_odds": "n/a", "cur_odds": "n/a",
        })
        result.append(card)
    return result


# ── Fetching ──────────────────────────────────────────────────────────────────
def fetch_positions(addr: str) -> list:
    try:
        r = requests.get(POSITIONS_API, params={"user": addr, "limit": 500}, timeout=15,
                         headers={"User-Agent": "polymarket-whales/1.0"})
        if r.status_code == 200:
            return r.json()
    except Exception as exc:
        print(f"[{addr[:8]}] fetch error: {exc}")
    return []


_cache: dict = {"data": [], "updated": None, "error": None}
_lock  = threading.Lock()


def build_positions() -> list:
    today   = datetime.now(timezone.utc)
    cutoff  = today + timedelta(hours=RESOLVE_HOURS)

    raw: dict = {}
    with ThreadPoolExecutor(max_workers=min(20, len(WALLETS) or 1)) as ex:
        futures = {ex.submit(fetch_positions, addr): addr for addr in WALLETS}
        for f in as_completed(futures):
            raw[futures[f]] = f.result()

    portfolio_totals = {
        addr: sum(float(p.get("currentValue", 0) or 0) for p in positions)
        for addr, positions in raw.items()
    }

    # Build wallet_sizes / category_sizes for conviction scoring
    wallet_sizes:   dict[str, list]           = {}
    category_sizes: dict[tuple, list]         = {}
    all_source_rows: list                     = []

    for addr, positions in raw.items():
        label     = WALLETS[addr]
        port_total = portfolio_totals.get(addr, 0.0)
        for p in positions:
            title = p.get("title", "?")
            eslug = p.get("eventSlug", "") or ""
            cat   = classify_category(title, eslug)
            if cat == "Other":
                continue
            row = build_position_row(addr, label, p, cat, port_total)
            all_source_rows.append(row)
            wallet_sizes.setdefault(addr, []).append(row["row_cost"])
            category_sizes.setdefault((addr, cat), []).append(row["row_cost"])

    # Attach conviction scores to all source rows using full position universe
    attach_conviction_scores(all_source_rows, wallet_sizes, category_sizes)
    attach_sharp_wallet_counts(all_source_rows, all_source_rows)

    # Now apply the 24-hour filter for display
    result = []
    for row in all_source_rows:
        if bool(row.get("row_win")) or (row.get("row_loss")):
            continue
        if row.get("cur_price", 1) <= 0:
            continue
        if not odds_in_range(row.get("cur_price", 50)):
            continue
        end_raw = row.get("resolution_time") or row.get("end_date") or ""
        if end_raw:
            try:
                end_dt = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
                if end_dt < today or end_dt > cutoff:
                    continue
            except ValueError:
                pass
        result.append(row.copy())

    # Re-attach conviction scores to the filtered set using the same full-universe sizes
    attach_conviction_scores(result, wallet_sizes, category_sizes)
    attach_sharp_wallet_counts(result, all_source_rows)
    attach_position_details(result, all_source_rows)
    result = collapse_position_cards(result)
    result = dedup_by_market(result)
    result = collapse_by_event(result)
    result.sort(key=lambda x: x["conviction"], reverse=True)
    return result


def refresh_loop():
    while True:
        try:
            data = build_positions()
            with _lock:
                _cache["data"]    = data
                _cache["updated"] = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
                _cache["error"]   = None
            print(f"[whales] refreshed — {len(data)} plays across {len(WALLETS)} wallets")
        except Exception as exc:
            with _lock:
                _cache["error"] = str(exc)
            print(f"[whales] refresh error: {exc}")
        time.sleep(REFRESH_SECONDS)


# ── Flask ─────────────────────────────────────────────────────────────────────
flask_app = Flask(__name__)


@flask_app.route("/api/positions")
def api_positions():
    with _lock:
        return jsonify({"data": _cache["data"], "updated": _cache["updated"], "error": _cache["error"]})


@flask_app.route("/")
def index():
    return render_template_string(HTML, refresh=REFRESH_SECONDS)


# ── HTML (exact PolyTrack template, title/header changed) ────────────────────
HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Polymarket Whales — Today's Plays</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0e1412; color: #96b8a2; font-family: 'Segoe UI', system-ui, sans-serif; font-size: 13px; min-height: 100vh; }
  a { color: inherit; text-decoration: none; }

  header { padding: 12px 20px; border-bottom: 1px solid #222e27; display: flex; align-items: center; gap: 14px; flex-wrap: wrap; background: #0e1412; }
  h1 { font-size: 15px; font-weight: 700; color: #34c759; letter-spacing: .2px; }
  .badge { background: #151c18; border: 1px solid #222e27; border-radius: 10px; padding: 2px 9px; font-size: 11px; color: #4d6659; }
  #meta { margin-left: auto; color: #4d6659; font-size: 11px; }
  #spinner { width: 9px; height: 9px; border: 2px solid #222e27; border-top-color: #34c759; border-radius: 50%; display: none; animation: spin .7s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  .controls { padding: 8px 20px; background: #0e1412; border-bottom: 1px solid #222e27; display: flex; align-items: center; gap: 18px; flex-wrap: wrap; }
  .controls label { color: #4d6659; display: flex; align-items: center; gap: 6px; font-size: 12px; }
  .controls select { background: #151c18; color: #96b8a2; border: 1px solid #222e27; border-radius: 4px; padding: 3px 7px; font-size: 12px; }
  input[type=range] { width: 160px; accent-color: #34c759; cursor: pointer; }
  #convVal { color: #34c759; font-weight: 700; min-width: 26px; display: inline-block; }
  #rowCount { color: #e0ece4; font-weight: 600; }

  .summary { display: flex; border-bottom: 1px solid #222e27; }
  .stat { padding: 10px 22px; border-right: 1px solid #222e27; }
  .stat-label { color: #4d6659; font-size: 10px; text-transform: uppercase; letter-spacing: .8px; margin-bottom: 1px; }
  .stat-value { font-size: 18px; font-weight: 700; color: #e0ece4; }
  .pos { color: #34c759; } .neg { color: #f0606e; }

  .sortbar { padding: 8px 20px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; border-bottom: 1px solid #222e27; background: #0e1412; }
  .sortbar button { background: #151c18; color: #4d6659; border: 1px solid #222e27; border-radius: 4px; padding: 4px 8px; font-size: 11px; font-family: inherit; cursor: pointer; transition: color .1s, border-color .1s; }
  .sortbar button:hover, .sortbar button.sorted { color: #34c759; border-color: #34c759; background: #182419; }
  .sortbar .sep { color: #222e27; font-size: 16px; }
  .odds-note { margin-left: auto; color: #4d6659; font-size: 11px; }

  .cards { padding: 10px 20px 40px; display: flex; flex-direction: column; gap: 5px; }
  .empty { text-align: center; padding: 60px; color: #4d6659; }

  .play-card { display: grid; grid-template-columns: 68px 1fr auto; background: #111814; border: 1px solid #1e2921; border-radius: 8px; cursor: pointer; overflow: hidden; transition: border-color .12s, background .12s; min-height: 76px; }
  .play-card:hover { border-color: #2a4a34; background: #141f18; }

  .conv-col { display: flex; align-items: center; justify-content: center; padding: 0 14px; border-right: 1px solid #1e2921; background: #0e1412; flex-shrink: 0; }
  .conv-num { font-size: 32px; font-weight: 800; line-height: 1; letter-spacing: -1px; }

  .card-mid { padding: 12px 16px; display: flex; flex-direction: column; justify-content: center; gap: 4px; min-width: 0; }
  .card-title { color: #d8ebe0; font-weight: 600; font-size: 14px; line-height: 1.3; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 1px; }
  .card-meta { font-size: 11px; color: #5a7a68; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .card-meta .hl { color: #8aa898; }
  .card-meta .up   { color: #34c759; }
  .card-meta .down { color: #f0606e; }
  .card-meta .gold { color: #e6a817; }
  .card-sub { display: flex; align-items: center; gap: 0; font-size: 11px; color: #5a7a68; flex-wrap: nowrap; overflow: hidden; }
  .card-sub .sep { margin: 0 5px; color: #2a3a30; }
  .side-yes   { color: #34c759; font-weight: 700; }
  .side-no    { color: #f0606e; font-weight: 700; }
  .side-multi { color: #e6a817; font-weight: 700; }
  .sub-pos  { color: #34c759; }
  .sub-neg  { color: #f0606e; }

  .card-right { display: flex; flex-direction: column; align-items: flex-end; justify-content: center; padding: 10px 16px; border-left: 1px solid #1e2921; gap: 4px; flex-shrink: 0; }
  .shares-tag { font-size: 10px; color: #4d6659; white-space: nowrap; }
  .value-tag  { font-size: 13px; font-weight: 700; color: #d8ebe0; white-space: nowrap; }
  .price-badge { background: #182d20; color: #34c759; border: 1px solid #234830; border-radius: 5px; padding: 3px 11px; font-weight: 700; font-size: 13px; white-space: nowrap; letter-spacing: .2px; }

  .cat-badge { display: inline-block; background: #151c18; color: #5ab878; border: 1px solid #234830; border-radius: 3px; padding: 1px 6px; font-size: 10px; }
  .chip { background: #151c18; border: 1px solid #222e27; border-radius: 4px; padding: 2px 7px; font-size: 11px; white-space: nowrap; color: #96b8a2; }

  .modal-backdrop { position: fixed; inset: 0; background: rgba(4,8,6,.85); display: none; z-index: 100; }
  .modal-backdrop.open { display: block; }
  .drawer { position: fixed; top: 0; right: 0; width: min(1020px, 96vw); height: 100vh; background: #111814; border-left: 1px solid #222e27; box-shadow: -20px 0 50px rgba(0,0,0,.5); overflow-y: auto; }
  .drawer-head { position: sticky; top: 0; background: #0e1412; border-bottom: 1px solid #222e27; padding: 14px 18px; z-index: 1; }
  .drawer-kicker { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; }
  .drawer-title { color: #d8ebe0; font-size: 16px; font-weight: 700; margin-bottom: 4px; }
  .drawer-sub { color: #4d6659; font-size: 11px; }
  .drawer-close { position: absolute; top: 12px; right: 14px; background: #151c18; color: #8aa898; border: 1px solid #222e27; border-radius: 4px; padding: 4px 10px; cursor: pointer; font-size: 12px; }
  .drawer-close:hover { color: #34c759; border-color: #34c759; }

  .drawer-statline { padding: 10px 18px; border-bottom: 1px solid #222e27; font-size: 12px; color: #5a7a68; display: flex; gap: 0; flex-wrap: wrap; }
  .drawer-statline .dsl-sep { margin: 0 8px; color: #2a3a30; }
  .drawer-statline .dsl-hl  { color: #8aa898; }
  .drawer-statline .dsl-pos { color: #34c759; }
  .drawer-statline .dsl-neg { color: #f0606e; }

  .drawer-align { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px; padding: 12px 18px; border-bottom: 1px solid #222e27; }
  .card-metric { min-width: 0; }
  .metric-label { color: #4d6659; font-size: 10px; text-transform: uppercase; letter-spacing: .6px; margin-bottom: 2px; }
  .metric-value { color: #d8ebe0; font-weight: 700; white-space: nowrap; }

  .drawer-body { padding: 0 18px 30px; }
  .wallet-section { margin-top: 16px; }
  .section-title { color: #d8ebe0; font-size: 13px; font-weight: 700; margin-bottom: 8px; }
  .modal-sort { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
  .modal-sort button { background: #151c18; color: #4d6659; border: 1px solid #222e27; border-radius: 4px; padding: 4px 8px; font: inherit; font-size: 11px; cursor: pointer; }
  .modal-sort button:hover { color: #34c759; border-color: #34c759; }

  .wallet-row { border: 1px solid #1e2921; border-radius: 6px; padding: 10px; margin-bottom: 7px; background: #0e1412; }
  .wallet-row.sharp { border-color: #234830; }
  .wallet-row-head { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 8px; }
  .wallet-address { color: #4d6659; font-size: 11px; overflow-wrap: anywhere; }
  .wallet-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 7px 14px; }

  @media (max-width: 640px) {
    .play-card { grid-template-columns: 58px 1fr; }
    .card-right { display: none; }
  }
</style>
</head>
<body>

<header>
  <h1>🐳 Polymarket Whales — Today's Plays</h1>
  <span class="badge" id="walletCount">– wallets</span>
  <div id="spinner"></div>
  <div id="meta">–</div>
</header>

<div class="controls">
  <label>Min conviction&nbsp;<span id="convVal">1</span>
    <input type="range" id="convSlider" min="1" max="100" value="1">
  </label>
  <label>Sport <select id="categoryFilter"><option value="">All</option></select></label>
  <label>Wallet <select id="walletFilter"><option value="">All</option></select></label>
  <span style="color:#3a6040">Showing <span id="rowCount">–</span> plays resolving in 24h</span>
</div>

<div class="summary" id="summary"></div>

<div class="sortbar">
  <button onclick="sortBy('conviction')" id="th-conviction" class="sorted">Conviction</button>
  <button onclick="sortBy('tail_stake')" id="th-tail-stake">Tail</button>
  <button onclick="sortBy('sharp_wallet_count')" id="th-sharp-wallet-count">Aligned</button>
  <button onclick="sortBy('net_sharp_alignment')" id="th-net-sharp-alignment">Net</button>
  <span class="sep">|</span>
  <button onclick="sortBy('cur_price')" id="th-cur-price">Price</button>
  <button onclick="sortBy('size_usd')" id="th-size-usd">Invested</button>
  <button onclick="sortBy('pct_portfolio')" id="th-pct-portfolio">Port %</button>
  <span class="sep">|</span>
  <button onclick="sortBy('category_win_rate_pct')" id="th-category-win-rate-pct">Win %</button>
  <button onclick="sortBy('category_roi_pct')" id="th-category-roi-pct">P&amp;L</button>
  <span class="odds-note">Odds -250 to +250 &nbsp;&bull;&nbsp; resolves &le;24h</span>
</div>

<div class="cards" id="cards"></div>

<div class="modal-backdrop" id="positionModal" onclick="backdropClose(event)">
  <div class="drawer">
    <div class="drawer-head">
      <button class="drawer-close" onclick="closePositionModal()">&#10005; Close</button>
      <div class="drawer-kicker" id="modalKicker"></div>
      <div class="drawer-title" id="modalTitle"></div>
      <div class="drawer-sub" id="modalSub"></div>
    </div>
    <div class="drawer-statline" id="drawerStatline"></div>
    <div class="drawer-align" id="modalSummary"></div>
    <div class="drawer-body">
      <div class="modal-sort">
        <button onclick="sortModal('position_size')">Exposure</button>
        <button onclick="sortModal('total_pl')">P/L</button>
        <button onclick="sortModal('wallet_category_roi_pct')">Cat ROI</button>
        <button onclick="sortModal('wallet_historical_win_rate')">Win %</button>
        <button onclick="sortModal('portfolio_size')">Portfolio</button>
      </div>
      <div class="wallet-section">
        <div class="section-title">Aligned wallets</div>
        <div id="alignedWallets"></div>
      </div>
      <div class="wallet-section">
        <div class="section-title">Opposing wallets</div>
        <div id="opposingWallets"></div>
      </div>
    </div>
  </div>
</div>

<script>
  let allData = [];
  let renderedData = [];
  let activeCard = null;
  let modalSortKey = 'position_size';
  let modalSortDir = -1;
  let sortKey = 'conviction';
  let sortDir = -1;
  const REFRESH = {{ refresh }} * 1000;

  const SPORT_ICONS = {
    'nba': '&#127936;', 'wnba': '&#127936;',
    'nfl': '&#127944;',
    'mlb': '&#9918;',
    'nhl': '&#127944;',
    'soccer': '&#9917;', 'fifa': '&#9917;',
    'tennis': '&#127934;',
    'mma': '&#129354;', 'ufc': '&#129354;', 'boxing': '&#129354;',
    'golf': '&#9971;',
    'esports': '&#127918;',
    'f1': '&#127950;', 'formula': '&#127950;',
  };

  function sportIcon(cat) {
    const lc = (cat || '').toLowerCase();
    for (const [k, v] of Object.entries(SPORT_ICONS)) {
      if (lc.includes(k)) return v;
    }
    return '&#127942;';
  }

  function convColor(c) {
    const hue = Math.round(-8 + 150 * (c / 100));
    return `hsl(${hue}, 68%, 48%)`;
  }

  function fmt(n, d=0) {
    return (n || 0).toLocaleString('en-US', {minimumFractionDigits: d, maximumFractionDigits: d});
  }

  function sign(n) { return (n || 0) >= 0 ? '+' : ''; }
  function pcls(n) { return (n || 0) >= 0 ? 'pos' : 'neg'; }

  function esc(v) {
    return String(v ?? '').replace(/[&<>"']/g, c =>
      ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function syncFilter(id, values) {
    const el = document.getElementById(id);
    const cur = el.value;
    el.innerHTML = '<option value="">All</option>' +
      values.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join('');
    if (values.includes(cur)) el.value = cur;
  }

  function alignedNames(row) {
    const ws = row.position_details?.aligned_wallets || [];
    if (ws.length) return [...new Set(ws.map(w => w.wallet).filter(Boolean))];
    return row.wallet ? [row.wallet] : [];
  }

  function walletMatches(row, w) { return !w || alignedNames(row).includes(w); }
  function walletOptions(rows) { return [...new Set(rows.flatMap(r => alignedNames(r)))].sort(); }

  function backdropClose(e) { if (e.target.id === 'positionModal') closePositionModal(); }
  function closePositionModal() { document.getElementById('positionModal').classList.remove('open'); }

  function dm(label, value, cls='') {
    return `<div class="card-metric"><div class="metric-label">${label}</div><div class="metric-value ${cls}">${value}</div></div>`;
  }

  function sortWalletRows(rows) {
    return [...rows].sort((a, b) => {
      const av = a[modalSortKey], bv = b[modalSortKey];
      if (typeof av === 'string') return av.localeCompare(bv) * modalSortDir;
      return ((av||0) - (bv||0)) * modalSortDir;
    });
  }

  function renderWalletRows(rows) {
    if (!rows.length) return '<div style="color:#4d6659;padding:12px">None</div>';
    return sortWalletRows(rows).map(w => {
      const pc  = (w.total_pl||0) >= 0 ? 'pos' : 'neg';
      const sc  = w.side === 'Yes' ? 'side-yes' : 'side-no';
      return `<div class="wallet-row ${w.sharp_for_category ? 'sharp' : ''}">
        <div class="wallet-row-head">
          <div>
            <span class="chip">${esc(w.wallet)}</span>&nbsp;
            <span class="${sc}">${esc(w.side)}</span>
            ${w.sharp_for_category ? '&nbsp;<span class="cat-badge">sharp</span>' : ''}
            <div class="wallet-address">${esc(w.addr)}</div>
          </div>
          <div class="${pc}">${(w.total_pl||0)>=0?'+':'-'}$${fmt(Math.abs(w.total_pl||0))} &middot; ${sign(w.roi_pct)}${(w.roi_pct||0).toFixed(1)}%</div>
        </div>
        <div class="wallet-grid">
          ${dm('Entry',`${w.entry_price}&#162; <span style="color:#3a6040">${esc(w.entry_odds)}</span>`)}
          ${dm('Current',`${w.current_price}&#162; <span style="color:#3a6040">${esc(w.current_odds)}</span>`)}
          ${dm('Exposure',`$${fmt(w.position_size)}`)}
          ${dm('Shares',fmt(w.shares||0,2))}
          ${dm('Cost/Value',`$${fmt(w.cost_basis)} / $${fmt(w.current_value)}`)}
          ${dm('Unrealized',`${(w.unrealized_pl||0)>=0?'+':'-'}$${fmt(Math.abs(w.unrealized_pl||0))}`,pcls(w.unrealized_pl))}
          ${dm('Portfolio',`$${fmt(w.wallet_total_portfolio_value||0)}`)}
          ${dm('% Port',`${(w.portfolio_pct||0).toFixed(2)}%`)}
          ${dm('Avg Position',`$${fmt(w.wallet_avg_position_size||0)}`)}
          ${dm('Size x',`${(w.position_size_multiple||0).toFixed(2)}x`)}
          ${dm('Win %',`${(w.wallet_historical_win_rate||0).toFixed(1)}%`)}
          ${dm('Cat P&L',`${(w.wallet_category_pl||0)>=0?'+':'-'}$${fmt(Math.abs(w.wallet_category_pl||0))}`,pcls(w.wallet_category_pl))}
          ${w.source_link ? dm('Link',`<a href="${esc(w.source_link)}" target="_blank" onclick="event.stopPropagation()">Open &#8599;</a>`) : ''}
        </div>
      </div>`;
    }).join('');
  }

  function renderModal() {
    if (!activeCard) return;
    const r = activeCard;
    const details = r.position_details || {};
    const s = details.summary || {};
    const aligned = details.aligned_wallets || [];
    const opposing = details.opposing_wallets || [];

    const isMulti  = r.outcome === 'Multi';
    const outcome  = isMulti ? 'Multi' : (s.selected_side || r.outcome || '');
    const sideCls  = isMulti ? 'side-multi' : (outcome === 'Yes' ? 'side-yes' : 'side-no');
    const entryP   = r.avg_price || r.entry_price || 0;
    const curP     = r.cur_price || r.current_price || 0;
    const wr       = (r.category_win_rate_pct || 0).toFixed(1);
    const mult     = (r.position_size_multiple || 1).toFixed(2);

    document.getElementById('modalKicker').innerHTML =
      `<span class="cat-badge">${esc(s.category||r.category)}</span>
       <span class="${sideCls}" style="margin-left:2px">${esc(outcome)}</span>`;
    document.getElementById('modalTitle').textContent = s.market_title || r.market || '';
    document.getElementById('modalSub').textContent = `Resolves ${s.resolution_time||r.end_date||'–'}`;

    const sep = `<span class="dsl-sep">&middot;</span>`;
    const priceStr = isMulti ? '' :
      sep + `${entryP}&#162; &rarr; <span class="dsl-hl">${curP}&#162;</span>`;
    document.getElementById('drawerStatline').innerHTML =
      `<span class="dsl-hl">$${fmt(r.size_usd||r.row_cost||0)}</span> invested`
      + sep + `<span class="dsl-hl">${mult}x</span> bet size`
      + priceStr
      + sep + `win <span class="dsl-hl">${wr}%</span>`
      + sep + `tail <span class="dsl-hl">$${fmt(r.tail_stake||0)}</span>`;

    const ac = (s.net_sharp_alignment||0) >= 0 ? 'pos' : 'neg';
    document.getElementById('modalSummary').innerHTML =
      dm('Aligned', s.aligned_sharp_wallet_count||0) +
      dm('Aligned exp.', `$${fmt(s.total_aligned_exposure||0)}`) +
      dm('Avg win %', `${(s.average_aligned_category_roi||0).toFixed(1)}%`) +
      dm('Opposing', s.opposing_sharp_wallet_count||0) +
      dm('Opposing exp.', `$${fmt(s.opposing_exposure||0)}`) +
      dm('Net alignment', `${sign(s.net_sharp_alignment)}${s.net_sharp_alignment||0}`, ac) +
      dm('Score', s.final_conviction_score||r.conviction||0);

    document.getElementById('alignedWallets').innerHTML  = renderWalletRows(aligned);
    document.getElementById('opposingWallets').innerHTML = renderWalletRows(opposing);
    document.getElementById('positionModal').classList.add('open');
  }

  function openCard(i) {
    activeCard = renderedData[i];
    modalSortKey = 'position_size'; modalSortDir = -1;
    renderModal();
  }

  function sortModal(key) {
    if (modalSortKey === key) modalSortDir *= -1; else { modalSortKey = key; modalSortDir = -1; }
    renderModal();
  }

  function render() {
    const minConv  = parseInt(document.getElementById('convSlider').value);
    const category = document.getElementById('categoryFilter').value;
    const wallet   = document.getElementById('walletFilter').value;
    document.getElementById('convVal').textContent = minConv;

    const filtered = allData.filter(r =>
      r.conviction >= minConv
      && (!category || r.category === category)
      && walletMatches(r, wallet)
    );
    filtered.sort((a, b) => {
      const va = a[sortKey], vb = b[sortKey];
      if (typeof va === 'string') return va.localeCompare(vb) * sortDir;
      return ((va||0) - (vb||0)) * sortDir;
    });
    renderedData = filtered;
    document.getElementById('rowCount').textContent = filtered.length;

    const inv = filtered.reduce((s,r)=>s+(r.size_usd||0),0);
    const val = filtered.reduce((s,r)=>s+(r.current_value||0),0);
    const pnl = filtered.reduce((s,r)=>s+(r.row_pl||0),0);
    document.getElementById('summary').innerHTML = `
      <div class="stat"><div class="stat-label">Plays</div><div class="stat-value">${filtered.length}</div></div>
      <div class="stat"><div class="stat-label">Invested</div><div class="stat-value">$${fmt(inv)}</div></div>
      <div class="stat"><div class="stat-label">Current Value</div><div class="stat-value">$${fmt(val)}</div></div>
      <div class="stat"><div class="stat-label">Unrealised P/L</div><div class="stat-value ${pcls(pnl)}">${sign(pnl)}$${fmt(Math.abs(pnl))}</div></div>`;

    document.getElementById('walletCount').textContent = walletOptions(filtered).length + ' whales';
    syncFilter('categoryFilter', [...new Set(allData.map(r=>r.category))].sort());
    syncFilter('walletFilter', walletOptions(allData));

    if (!filtered.length) {
      document.getElementById('cards').innerHTML = `<div class="empty">No plays resolving in the next 24h above conviction ${minConv}.<br>Check back closer to game time.</div>`;
      return;
    }

    document.getElementById('cards').innerHTML = filtered.map((r, i) => {
      const color   = convColor(r.conviction);
      const entryP  = r.avg_price || r.entry_price || 0;
      const curP    = r.cur_price || r.current_price || 0;
      const curOdds = r.cur_odds || r.current_odds || '';
      const pDelta  = curP - entryP;
      const pDir    = pDelta > 1 ? 'up' : pDelta < -1 ? 'down' : 'hl';
      const mult    = r.position_size_multiple || 1;
      const mCls    = mult >= 1.5 ? 'gold' : mult < 1.0 ? 'down' : 'hl';
      const wr      = (r.category_win_rate_pct || 0).toFixed(1);
      const ico     = sportIcon(r.category);
      const isMulti = r.outcome === 'Multi';
      const sideCls = isMulti ? 'side-multi' : (r.outcome === 'Yes' ? 'side-yes' : 'side-no');
      const names   = alignedNames(r);
      const wLabel  = names.length > 1 ? `${names.length} aligned` : esc(names[0] || r.wallet || '');

      const endRaw = r.resolution_time || r.end_date || '';
      let endLabel = '—';
      try {
        const d = new Date(endRaw);
        if (!isNaN(d)) {
          const now = new Date();
          const diffH = (d - now) / 3600000;
          if (diffH < 1) endLabel = Math.round(diffH * 60) + 'm';
          else if (diffH < 24) endLabel = diffH.toFixed(1) + 'h';
          else endLabel = d.toLocaleDateString('en-US',{month:'short',day:'numeric'});
        }
      } catch(e){}

      const sep = `<span class="sep">&middot;</span>`;

      return `<article class="play-card" onclick="openCard(${i})">
        <div class="conv-col">
          <div class="conv-num" style="color:${color}">${r.conviction}</div>
        </div>
        <div class="card-mid">
          <div class="card-title" title="${esc(r.market)}">${esc(r.market)}</div>
          <div class="card-meta">
            ${ico} ${esc(r.category)}
            &nbsp;&middot;&nbsp;${esc(wLabel)}
            &nbsp;&middot;&nbsp;<span class="hl">in ${endLabel}</span>
            &nbsp;&middot;&nbsp;<span class="hl">$${fmt(r.size_usd||r.row_cost||0)}</span>
            ${isMulti ? '' : `&nbsp;&middot;&nbsp;<span class="${pDir}">${fmt(entryP,0)}&#162;&rarr;${fmt(curP,0)}&#162;</span>`}
            &nbsp;&middot;&nbsp;<span class="${mCls}">${mult.toFixed(1)}x</span>
          </div>
          <div class="card-sub">
            ${isMulti
              ? `<span class="side-multi">${r.event_market_count} markets</span>${sep}<span style="color:#4d6659;font-size:10px">${(r.sub_markets||[]).slice(0,2).map(m=>esc(m)).join(' &middot; ')+(r.sub_markets&&r.sub_markets.length>2?' &hellip;':'')}</span>`
              : `<span class="${sideCls}">${esc(r.outcome)}</span>${sep}<span>${fmt(curP,0)}&#162;&nbsp;<span style="color:#4d6659">${esc(curOdds)}</span></span>`
            }
            ${sep}<span>win ${wr}%</span>
            ${sep}<span>${(r.pct_portfolio||0).toFixed(1)}% port</span>
            ${r.tail_stake ? `${sep}<span>tail $${fmt(r.tail_stake)}</span>` : ''}
          </div>
        </div>
        <div class="card-right">
          <div class="shares-tag">${isMulti ? (r.event_market_count+' markets') : fmt(r.shares||0,0)+' shares'}</div>
          <div class="value-tag">$${fmt(r.current_value||0)}</div>
          ${isMulti
            ? `<div class="price-badge" style="color:#e6a817;border-color:#4a3800;background:#1e1600">HEDGE</div>`
            : `<div class="price-badge">${fmt(curP,0)}&#162;</div>`
          }
        </div>
      </article>`;
    }).join('');
  }

  function sortBy(key) {
    document.querySelectorAll('.sortbar button').forEach(t => t.classList.remove('sorted'));
    if (sortKey === key) sortDir *= -1;
    else {
      sortKey = key;
      sortDir = ['conviction','tail_stake','sharp_wallet_count','net_sharp_alignment',
                 'category_roi_pct','category_win_rate_pct','size_usd','pct_portfolio','cur_price'].includes(key) ? -1 : 1;
    }
    const el = document.getElementById('th-' + key.replace(/_/g,'-'));
    if (el) el.classList.add('sorted');
    render();
  }

  async function fetchData() {
    document.getElementById('spinner').style.display = 'inline-block';
    try {
      const res  = await fetch('/api/positions');
      const json = await res.json();
      if (json.error) {
        document.getElementById('meta').textContent = 'Error: ' + json.error;
      } else {
        allData = json.data || [];
        document.getElementById('meta').textContent = 'Updated ' + (json.updated || '–');
      }
    } catch(e) {
      document.getElementById('meta').textContent = 'Fetch error';
    }
    document.getElementById('spinner').style.display = 'none';
    render();
  }

  document.getElementById('convSlider').addEventListener('input', render);
  document.getElementById('categoryFilter').addEventListener('change', render);
  document.getElementById('walletFilter').addEventListener('change', render);
  fetchData();
  setInterval(fetchData, REFRESH);
</script>
</body>
</html>"""


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not WALLETS_FILE.exists():
        raise SystemExit(f"{WALLETS_FILE} not found — run: python ingest_top_wallets.py")

    wallets = json.loads(WALLETS_FILE.read_text())
    for w in wallets:
        addr = w.get("address", "").lower()
        if addr:
            label = w.get("label") or addr[:8]
            WALLETS[addr] = label
            WALLET_META[addr] = w

    print(f"Loaded {len(WALLETS)} whale wallets from {WALLETS_FILE}")
    print("Fetching initial positions (may take a minute)...")
    try:
        initial = build_positions()
        with _lock:
            _cache["data"]    = initial
            _cache["updated"] = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        print(f"Loaded {len(initial)} plays resolving in 24h")
    except Exception as exc:
        print(f"Initial fetch error: {exc}")

    t = threading.Thread(target=refresh_loop, daemon=True)
    t.start()

    print(f"Dashboard: http://localhost:{PORT}")
    flask_app.run(host="0.0.0.0", port=PORT, debug=False)
