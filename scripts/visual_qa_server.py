from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from math import pi, sin
from pathlib import Path
import json
import os
import sys
from types import MethodType
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from execution_providers import (
    NOVIG_LOGO_URL,
    POLYMARKET_LOGO_URL,
    PROPHETX_LOGO_URL,
)
from flask import g, jsonify, redirect, request
from personal_tracker import personal_fill_snapshot
from position_tracker import MODEL_TRACKER_USER_ID
from sharp_tracking import sharp_snapshot_from_trade


QA_TIMEZONE = ZoneInfo("America/New_York")
QA_TRADE_COUNT = 5
QA_HISTORY_START_OFFSETS = (-0.014, -0.018, -0.011, 0.021, -0.016)
QA_TRADE_SPECS = (
    {"sharps": 3, "score": 58, "entry": 0.42, "sharp_entry": 0.41},
    {"sharps": 3, "score": 56, "entry": 0.507, "sharp_entry": 0.489},
    {"sharps": 2, "score": 55, "entry": 0.40, "sharp_entry": 0.389},
    {"sharps": 2, "score": 64, "entry": 0.455, "sharp_entry": 0.46},
    {"sharps": 2, "score": 53, "entry": 0.525, "sharp_entry": 0.51},
)
QA_DFS_APP_PROVIDERS = (
    "prizepicks",
    "underdog",
    "pick6",
    "betr_picks",
    "dabble",
    "sleeper",
)
QA_DFS_SPORTSBOOKS = (
    ("fanduel", 0),
    ("fanatics", 1),
    ("novig", 3),
    ("prophetexchange", -2),
    ("draftkings", -4),
    ("pinnacle", 5),
    ("circa", 2),
    ("kalshi", -3),
    ("polymarket", 4),
)
QA_DFS_PROP_SPECS = (
    (
        "qa-dfs-yankees-red-sox",
        "MLB",
        "Boston Red Sox",
        "New York Yankees",
        "batter_hits",
        "Aaron Judge",
        1.5,
        -140,
        110,
    ),
    (
        "qa-dfs-dodgers-padres",
        "MLB",
        "San Diego Padres",
        "Los Angeles Dodgers",
        "batter_total_bases",
        "Shohei Ohtani",
        1.5,
        105,
        -135,
    ),
    (
        "qa-dfs-aces-liberty",
        "WNBA",
        "New York Liberty",
        "Las Vegas Aces",
        "player_points",
        "A'ja Wilson",
        24.5,
        -160,
        125,
    ),
    (
        "qa-dfs-fever-sky",
        "WNBA",
        "Chicago Sky",
        "Indiana Fever",
        "player_assists",
        "Caitlin Clark",
        8.5,
        -115,
        -105,
    ),
    (
        "qa-dfs-lakers-warriors",
        "NBA",
        "Golden State Warriors",
        "Los Angeles Lakers",
        "player_points_assists",
        "Luka Doncic",
        36.5,
        120,
        -150,
    ),
)


def qa_event_time(index: int, now_et: datetime) -> datetime:
    """Return a staggered, still-today start time for stable visual QA."""

    natural_start = (now_et + timedelta(minutes=30)).replace(second=0, microsecond=0)
    minute_remainder = natural_start.minute % 5
    if minute_remainder:
        natural_start += timedelta(minutes=5 - minute_remainder)
    natural_candidate = natural_start + timedelta(minutes=25 * index)
    day_end = now_et.replace(hour=23, minute=59, second=30, microsecond=0)
    if natural_candidate <= day_end:
        return natural_candidate

    # Late-evening QA still needs five future rows in the default Today view.
    # Evenly distribute the remaining window instead of rolling events tomorrow.
    remaining_seconds = max((day_end - now_et).total_seconds(), 1.0)
    return now_et + timedelta(
        seconds=remaining_seconds * ((index + 1) / (QA_TRADE_COUNT + 1))
    )


def qa_price_history(
    current_price: float,
    *,
    now: datetime,
    variation_index: int,
) -> list[dict]:
    """Build a deterministic market-like series that ends at the live quote."""

    start_offset = QA_HISTORY_START_OFFSETS[
        variation_index % len(QA_HISTORY_START_OFFSETS)
    ]
    points = []
    for point_index in range(25):
        progress = point_index / 24
        trend = start_offset * (1 - progress)
        wave = sin(progress * 3 * pi) * sin(progress * pi) * 0.0018
        price = min(max(current_price + trend + wave, 0.02), 0.98)
        if point_index == 24:
            price = current_price
        points.append(
            {
                "t": int(
                    (now - timedelta(minutes=15 * (24 - point_index))).timestamp()
                ),
                "p": f"{price:.4f}",
            }
        )
    return points


def recommendation(entry: float, sharp_entry: float, fraction: float) -> dict:
    bankroll = 10_000.0
    amount = bankroll * fraction
    return {
        "available": True,
        "current_user_entry_price": entry,
        "current_top_ask_price": entry,
        "effective_entry_price": entry,
        "baseline_probability": entry,
        "sharp_average_entry_price": sharp_entry,
        "sharp_reference_entry_price": sharp_entry,
        "price_slippage_fraction": (entry - sharp_entry) / sharp_entry,
        "passes_slippage_rule": True,
        "slippage_rejection_reason": None,
        "estimated_win_probability": min(entry + 0.08, 0.95),
        "calculated_edge": 0.08,
        "evidence_score": 0.78,
        "evidence_adjustment": 0.08,
        "full_kelly_fraction": fraction * 2,
        "half_kelly_fraction": fraction,
        "sharp_risk_cap": 0.01,
        "final_recommended_fraction": fraction,
        "recommended_amount": amount,
        "recommended_shares": amount / entry,
        "recommended_units": fraction * 100,
        "bankroll": bankroll,
        "slippage_cents": (entry - sharp_entry) * 100,
        "unfavorable_slippage_pct": max((entry - sharp_entry) / sharp_entry, 0),
    }


def qa_trade(
    index: int,
    *,
    sharps: int,
    score: int,
    entry: float,
    sharp_entry: float,
    now_utc: datetime | None = None,
    now_et: datetime | None = None,
) -> dict:
    now = now_utc or datetime.now(timezone.utc)
    local_now = now_et or now.astimezone(QA_TIMEZONE)
    categories = [
        ("Baseball", "MLB", "Cincinnati Reds vs St. Louis Cardinals", "Cincinnati Reds", "Moneyline"),
        ("Baseball", "MLB", "New York Yankees vs Boston Red Sox", "Yankees", "Moneyline"),
        ("Soccer", "FIFA World Cup", "Spain vs France", "Spain", "To Advance"),
        ("Basketball", "WNBA", "New York Liberty vs Las Vegas Aces", "Over 167.5", "Game Total"),
        ("Hockey", "NHL", "New York Rangers vs Boston Bruins", "Rangers ML", "Moneyline"),
    ]
    category, league, event, outcome, market = categories[index % len(categories)]
    event_time = qa_event_time(index, local_now)
    wallet_labels = ["Bagwell306", "FerrariChampions2026", "Weflyhigh"]
    supporters = []
    for wallet_index in range(sharps):
        supporters.append(
            {
                "wallet_address": f"0x{index + 1:02x}{wallet_index + 1:038x}",
                "wallet_label": wallet_labels[wallet_index % len(wallet_labels)],
                "wallet_profile_url": "https://polymarket.com/",
                "amount": 3400 - (wallet_index * 475),
                "relative_units": 1.4 + (wallet_index * 0.6),
                "is_lead_sharp": wallet_index == 0,
                "category_weight": 1.0 if wallet_index == 0 else 0.5,
                "top_category_ids": [category],
            }
        )
    orderbook = {
        "asks": [
            {"price": f"{entry + offset:.3f}", "size": str(1200 + index * 500 + level * 900)}
            for level, offset in enumerate((0.0, 0.003, 0.006, 0.01))
        ],
        "bids": [
            {"price": f"{entry - offset:.3f}", "size": str(1500 + index * 400 + level * 800)}
            for level, offset in enumerate((0.003, 0.006, 0.01, 0.014))
        ],
        "timestamp": now.isoformat(),
        "tick_size": "0.001",
        "min_order_size": "5",
    }
    rec = recommendation(entry, sharp_entry, 0.0038 + (index * 0.0008))
    return {
        "id": f"qa-trade-{index + 1}",
        "canonical_market_key": f"qa-market-{index + 1}",
        "canonical_category_id": category.lower(),
        "condition_id": f"qa-condition-{index + 1}",
        "event_slug": f"qa-event-{index + 1}",
        "event_title": event,
        "market_title": market,
        "outcome": outcome,
        "category": category,
        "league": league,
        "sports_market_type": market.lower().replace(" ", "_"),
        # Keep all five visual-QA rows in the active Eastern-time "Today" view.
        "event_date_et": event_time.isoformat(),
        "event_time_et": f"Today, {event_time.strftime('%I:%M %p').lstrip('0')}",
        "resolution_time": (event_time + timedelta(hours=3)).isoformat(),
        "market_url": "https://polymarket.com/",
        "clob_token_id": f"qa-token-{index + 1}",
        "market_open": True,
        "lifecycle_status": "open",
        "average_entry_price": sharp_entry,
        "sharp_reference_entry_price": sharp_entry,
        "orderbook": orderbook,
        "confidence_score": score,
        "score_breakdown": {
            "consensus_band": "Verified Sharp agreement",
            "category_composition": 0.75,
        },
        "raw_sharp_count": sharps,
        "agreeing_wallet_count": sharps,
        "lead_sharp_count": 1,
        "supporting_sharp_count": sharps - 1,
        "weighted_sharp_count": 1 + max(sharps - 1, 0) * 0.5,
        "has_lead_sharp": True,
        "weighted_amount_signal": 0.83,
        "weighted_relative_size_signal": 0.77,
        "combined_exposure_exact": sum(item["amount"] for item in supporters),
        "evidence_inputs": {"adjusted_category_hit_rate": 0.5908 + index * 0.012},
        "primary_trader": {
            **supporters[0],
            "is_lead_sharp": True,
            "top_category": category,
            "sample_size": 1010 - index * 130,
            "adjusted_hit_rate": 0.5908 + index * 0.012,
        },
        "supporting_wallets": supporters,
        "search_blob": f"{category} {league} {event} {outcome} {market}".lower(),
        "_qa_recommendation": rec,
    }


def qa_trades(now_utc: datetime | None = None) -> list[dict]:
    now = now_utc or datetime.now(timezone.utc)
    now_et = now.astimezone(QA_TIMEZONE)
    return [
        qa_trade(index, now_utc=now, now_et=now_et, **spec)
        for index, spec in enumerate(QA_TRADE_SPECS)
    ]


def qa_snapshot(now_utc: datetime | None = None) -> dict:
    """Return a fresh five-trade snapshot so long-running visual QA stays populated."""

    now = now_utc or datetime.now(timezone.utc)
    trades = qa_trades(now)
    return {
        "trades_to_play": trades,
        "trades": trades,
        "positions": trades,
        "status": {
            "state": "ok",
            "enabled_wallet_count": 9,
            "last_successful_refresh": now.isoformat(),
        },
    }


def _qa_dfs_bookmaker(
    book_key: str,
    *,
    market_key: str,
    player: str,
    line: float,
    over_odds: int | None,
    under_odds: int | None,
    observed_at: str,
) -> dict:
    return {
        "key": book_key,
        "title": book_key.replace("_", " ").title(),
        "last_update": observed_at,
        "markets": [
            {
                "key": market_key,
                "last_update": observed_at,
                "outcomes": [
                    {
                        "name": side,
                        "price": price,
                        "point": line,
                        "description": player,
                        "is_alt": False,
                    }
                    for side, price in (
                        ("Over", over_odds),
                        ("Under", under_odds),
                    )
                ],
            }
        ],
    }


def qa_dfs_events(now_utc: datetime | None = None) -> list[dict]:
    """Return realistic prop markets for local Fantasy Optimizer QA."""

    now = now_utc or datetime.now(timezone.utc)
    observed_at = now.isoformat()
    events = []
    for index, (
        event_id,
        sport,
        away_team,
        home_team,
        market_key,
        player,
        line,
        over_odds,
        under_odds,
    ) in enumerate(QA_DFS_PROP_SPECS):
        bookmakers = [
            _qa_dfs_bookmaker(
                book_key,
                market_key=market_key,
                player=player,
                line=line,
                over_odds=over_odds + offset,
                under_odds=under_odds - offset,
                observed_at=observed_at,
            )
            for book_key, offset in QA_DFS_SPORTSBOOKS
        ]
        bookmakers.extend(
            _qa_dfs_bookmaker(
                book_key,
                market_key=market_key,
                player=player,
                line=line,
                over_odds=None,
                under_odds=None,
                observed_at=observed_at,
            )
            for book_key in QA_DFS_APP_PROVIDERS
        )
        events.append(
            {
                "id": event_id,
                "sport_key": f"qa_{sport.lower()}",
                "sport_title": sport,
                "commence_time": (
                    now + timedelta(hours=2 + index * 2)
                ).isoformat(),
                "home_team": home_team,
                "away_team": away_team,
                "bookmakers": bookmakers,
            }
        )
    return events


def qa_dfs_payload(
    *,
    weights: dict[str, float] | None = None,
    selected_book: str = "prizepicks",
    now_utc: datetime | None = None,
) -> dict:
    """Build complete per-app DFS boards without requiring live credentials."""

    now = now_utc or datetime.now(timezone.utc)
    events = qa_dfs_events(now)
    active_book = (
        selected_book
        if selected_book in app_module.DFS_OPTIMIZER_BOOK_KEYS
        else "prizepicks"
    )
    rows_by_book = {
        book_key: app_module.build_dfs_odds_board(
            events,
            weights=weights,
            selected_dfs_book=book_key,
            now=now,
        )
        for book_key in app_module.DFS_OPTIMIZER_BOOK_KEYS
    }
    return {
        "data": rows_by_book[active_book],
        "dataByBook": rows_by_book,
        "total": len(rows_by_book[active_book]),
        "totalsByBook": {
            book_key: len(book_rows)
            for book_key, book_rows in rows_by_book.items()
        },
        "configured": True,
        "dataSource": "visual_qa",
        "selectedBook": active_book,
        "refreshSeconds": 15,
    }


def qa_positive_ev_payload(now_utc: datetime | None = None) -> dict:
    """Stable, realistic +EV rows for responsive browser QA."""

    now = now_utc or datetime.now(timezone.utc)
    specs = (
        ("qa-ev-royals", "baseball_mlb", "MLB", "Toronto Blue Jays", "Kansas City Royals", "Kansas City Royals", 100, 2.89, 35.80),
        ("qa-ev-storm", "basketball_wnba", "WNBA", "Toronto Tempo", "Seattle Storm", "Seattle Storm", -238, 1.36, 43.64),
        ("qa-ev-yankees", "baseball_mlb", "MLB", "Houston Astros", "New York Yankees", "New York Yankees", -144, 1.49, 27.02),
    )
    book_specs = (
        ("novig", "Novig", NOVIG_LOGO_URL, 0),
        ("polymarket", "Polymarket", POLYMARKET_LOGO_URL, -4),
        ("prophetexchange", "Prophet Exchange", PROPHETX_LOGO_URL, -5),
        ("pinnacle", "Pinnacle", "/static/assets/providers/pinnacle.png", -8),
        ("circa", "Circa", "/static/assets/dfs-books/circa.png", -10),
    )
    rows = []
    for index, (
        opportunity_id,
        sport_key,
        league,
        away_team,
        home_team,
        selection,
        american_odds,
        ev_percent,
        recommended_stake,
    ) in enumerate(specs):
        opponent = away_team if selection == home_team else home_team
        selection_quotes = []
        opponent_quotes = []
        for book_key, book_name, logo_url, offset in book_specs:
            selected_price = american_odds + offset
            opposing_price = -104 - offset - index
            shared = {
                "bookKey": book_key,
                "bookName": book_name,
                "logoUrl": logo_url,
                "lastUpdated": now.isoformat(),
                "quoteAgeSeconds": 4 + index,
                "deepLink": "https://novig.com/" if book_key == "novig" else "https://polymarket.com/",
            }
            selection_quotes.append(
                {
                    **shared,
                    "americanOdds": selected_price,
                    "topPriceAmericanOdds": selected_price,
                    "topPriceLiquidity": 1800 - index * 100,
                }
            )
            opponent_quotes.append(
                {
                    **shared,
                    "americanOdds": opposing_price,
                    "topPriceAmericanOdds": opposing_price,
                    "topPriceLiquidity": 1650 - index * 100,
                }
            )
        best = {
            **selection_quotes[0],
            "effectiveDecimal": (
                1 + american_odds / 100
                if american_odds > 0
                else 1 + 100 / abs(american_odds)
            ),
            "executionStatus": "executable",
        }
        rows.append(
            {
                "id": opportunity_id,
                "eventId": f"event-{index}",
                "sportKey": sport_key,
                "league": league,
                "eventTitle": f"{away_team} vs {home_team}",
                "homeTeam": home_team,
                "awayTeam": away_team,
                "commenceTime": (now + timedelta(hours=2 + index * 2)).isoformat(),
                "marketKey": "h2h",
                "marketLabel": "Moneyline",
                "selection": selection,
                "evPercent": ev_percent,
                "fairProbability": 0.51,
                "fairAmerican": -104,
                "fairConfidence": 0.91,
                "sourceCount": 3,
                "sourceBooks": [
                    {
                        "bookKey": quote["bookKey"],
                        "bookName": quote["bookName"],
                        "logoUrl": quote["logoUrl"],
                        "americanOdds": quote["americanOdds"],
                        "weight": weight,
                    }
                    for quote, weight in zip(selection_quotes[2:], (0.4, 0.35, 0.25))
                ],
                "bestQuote": best,
                "quotes": selection_quotes,
                "marketSides": [
                    {"selection": selection, "quotes": selection_quotes},
                    {"selection": opponent, "quotes": opponent_quotes},
                ],
                "executionStatus": "executable",
                "portfolioStatus": "qualified",
                "recommendedStake": recommended_stake,
                "warnings": [],
                "calculatedAt": now.isoformat(),
            }
        )
    return {
        "data": rows,
        "total": len(rows),
        "configured": True,
        "degraded": False,
        "stale": False,
        "dataSource": "visual_qa",
        "refreshSeconds": 15,
        "diagnostics": {
            "qualified": len(rows),
            "watchOnly": 0,
            "rejected": 0,
            "rejectionReasons": {},
        },
    }


def build_app():
    flask_app = app_module.create_app(start_background=False)
    tracker = flask_app.extensions["tracker_service"]
    now = datetime.now(timezone.utc)
    trades = qa_trades(now)

    tracker.get_snapshot = MethodType(lambda self: deepcopy(qa_snapshot()), tracker)
    tracker.refresh = MethodType(lambda self: None, tracker)

    def evaluate(self, play, bankroll, **_kwargs):
        rec = deepcopy(play["_qa_recommendation"])
        score_units = {55: 0.10, 56: 0.15, 58: 0.20, 64: 0.25}
        units = score_units.get(int(play.get("confidence_score") or 0), 0.10)
        rec["bankroll"] = bankroll
        rec["recommended_units"] = units
        rec["final_recommended_fraction"] = units / 100
        rec["recommended_amount"] = bankroll * rec["final_recommended_fraction"]
        rec["recommended_shares"] = rec["recommended_amount"] / rec["effective_entry_price"]
        return {
            "recommendation": rec,
            "model_tracker_eligible": True,
            "model_tracker_rejection_reason": None,
            "recommendation_snapshot_id": f"snapshot-{play['id']}",
            "recommendation_idempotency_key": f"qa::{play['id']}",
        }

    tracker.evaluate_recommendation = MethodType(evaluate, tracker)
    trade_prices = {
        trade["clob_token_id"]: (
            trade["_qa_recommendation"]["current_user_entry_price"],
            index,
        )
        for index, trade in enumerate(trades)
    }

    def get_price_history(token_id, interval="1d", fidelity=15):
        current_price, variation_index = trade_prices.get(token_id, (0.45, 0))
        return qa_price_history(
            current_price,
            now=now,
            variation_index=variation_index,
        )

    tracker.client.get_price_history = get_price_history
    tracker.client.get_order_books = lambda token_ids: {
        token_id: {
            "bids": [
                {"price": "0.52", "size": "80"},
                {"price": "0.49", "size": "150"},
            ],
            "asks": [{"price": "0.53", "size": "200"}],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        for token_id in token_ids
    }

    registry = flask_app.extensions["execution_providers"]
    odds_fixture_rows = []
    odds_games = (
        ("qa-odds-dbacks-nats", "Arizona Diamondbacks vs Washington Nationals", ("Arizona Diamondbacks", "Washington Nationals"), 9.0),
        ("qa-odds-jays-sox", "Toronto Blue Jays vs Boston Red Sox", ("Toronto Blue Jays", "Boston Red Sox"), 7.5),
        ("qa-odds-padres-marlins", "San Diego Padres vs Miami Marlins", ("San Diego Padres", "Miami Marlins"), 8.0),
    )
    odds_start = now + timedelta(hours=3)
    for game_index, (event_id, event_title, teams, total_line) in enumerate(odds_games):
        event_start = odds_start + timedelta(minutes=game_index * 35)
        market_specs = (
            ("moneyline", "Moneyline", ((teams[0], None), (teams[1], None))),
            ("spread", "Spread", ((teams[0], 1.5), (teams[1], -1.5))),
            ("total", "Total", (("Over", total_line), ("Under", total_line))),
        )
        for market_key, market_title, outcomes in market_specs:
            market_id = f"{event_id}-{market_key}"
            for outcome_index, (outcome, market_line) in enumerate(outcomes):
                current = 0.42 + (game_index * 0.025) + (outcome_index * 0.11)
                odds_fixture_rows.append(
                    {
                        "id": f"{market_id}-{outcome_index}",
                        "condition_id": market_id,
                        "market_id": market_id,
                        "event_id": event_id,
                        "event_slug": event_id,
                        "event_title": event_title,
                        "market_title": market_title,
                        "outcome": outcome,
                        "category": "Baseball",
                        "league": "MLB",
                        "canonical_league_id": "MLB",
                        "canonical_sport_id": "Baseball",
                        "sports_market_type": market_title,
                        "market_line": market_line,
                        "event_date_et": event_start.isoformat(),
                        "resolution_time": event_start.isoformat(),
                        "schedule_date_et": event_start.astimezone().date().isoformat(),
                        "market_url": "https://polymarket.com/",
                        "clob_token_id": f"{market_id}-token-{outcome_index}",
                        "is_sports": True,
                        "market_open": True,
                        "card": {"current_actionable_price": current, "recommended_amount": 0},
                        "recommendation": {
                            "current_user_entry_price": current,
                            "recommended_amount": 25,
                        },
                        "_qa_recommendation": {
                            "current_user_entry_price": current,
                            "recommended_amount": 25,
                        },
                    }
                )
    flask_app.extensions["polymarket_schedule_feed"].today_and_tomorrow = (
        lambda _now: deepcopy(odds_fixture_rows)
    )
    odds_api_provider = next(
        (
            provider
            for provider in registry.providers
            if provider.provider_key == "the_odds_api"
        ),
        None,
    )
    if odds_api_provider is not None:
        odds_api_provider.odds_screen_rows = lambda **_kwargs: []
        odds_api_provider.screen_options_for_trades = lambda _rows: {}

    def attach_options(rows, **_kwargs):
        for index, row in enumerate(rows):
            recommendation_data = row.get("recommendation") or row["_qa_recommendation"]
            current = recommendation_data["current_user_entry_price"]
            providers = (
                ("polymarket", "Polymarket", POLYMARKET_LOGO_URL, 0.435 if index == 0 else current + 0.012, 5400),
                ("novig", "NoVIG", NOVIG_LOGO_URL, (100 / 233) if index == 0 else current - (0.012 if index != 1 else 0.003), 3800),
                ("prophetx", "ProphetX", PROPHETX_LOGO_URL, 0.445 if index == 0 else current + 0.006, 2700),
                ("4cx", "4CX", "/static/assets/providers/4cx.png", 0.440 if index == 0 else current - (0.004 if index == 1 else 0.001), 4600),
                ("kalshi", "Kalshi", "/static/assets/providers/kalshi.png", 0.43708 if index == 0 else current + 0.003, 2200),
            )
            row["executionOptions"] = []
            for provider_index, (
                provider_key,
                provider_name,
                logo_url,
                price,
                base_liquidity,
            ) in enumerate(providers):
                price = min(max(price, 0.02), 0.98)
                quote_age = 4 + provider_index * 4 + index
                quote_time = now - timedelta(seconds=quote_age)
                american_odds = None
                if provider_key not in {"polymarket", "kalshi"}:
                    american_odds = round(
                        -100 * price / (1 - price)
                        if price >= 0.5
                        else 100 * (1 - price) / price
                    )
                raw_contract_price = (
                    0.42 if provider_key == "kalshi" and index == 0 else price
                )
                estimated_fees = (
                    0.61 if provider_key == "kalshi" and index == 0 else 0.0
                )
                row["executionOptions"].append(
                    {
                        "providerName": provider_name,
                        "providerKey": provider_key,
                        "americanOdds": american_odds,
                        "contractPrice": raw_contract_price,
                        "estimatedFees": estimated_fees,
                        "recommendedStake": recommendation_data["recommended_amount"],
                        "marketId": f"{provider_key}-{index}",
                        "selectionId": f"{provider_key}-selection-{index}",
                        "displayOdds": f"{price * 100:.1f}¢",
                        "bestExecutablePrice": price,
                        "availableLiquidity": base_liquidity + index * 125,
                        "feeRate": 0.0,
                        "deepLink": f"https://{provider_key}.com/",
                        "directMarketUrl": f"https://{provider_key}.com/markets/{index}",
                        "logoUrl": logo_url,
                        "isAvailable": True,
                        "isExactMatch": True,
                        "isStale": False,
                        "marketStatus": "OPEN",
                        "canFillRecommendedStake": True,
                        "lastUpdated": quote_time.isoformat(),
                        "quoteTimestamp": quote_time.isoformat(),
                        "quoteAgeSeconds": quote_age,
                        "matchingConfidence": "Exact",
                        "tooltip": f"{provider_name} current executable price",
                    }
                )
            if index == 0:
                row["personalExposureSummary"] = {
                    "type": "exact",
                    "title": "Conflicting Bets",
                    "message": "You already have a personal fill on this exact selection.",
                    "aggregate": {"entryCount": 1, "averageEntry": 0.341, "totalShares": 118, "totalPositionCost": 40.19},
                }
            elif index == 1:
                row["personalExposureSummary"] = {
                    "type": "same_event",
                    "title": "Same-event exposure",
                    "message": "You have another personal market on this event.",
                    "aggregate": {"entryCount": 1, "averageEntry": 0.49, "totalShares": 50, "totalPositionCost": 24.5},
                }

    registry.attach_options = attach_options

    qa_user = "visual-qa-user"
    clv_values = (25.3644314869, -8.0, 6.25, None, None)
    for index, trade in enumerate(trades):
        fill = personal_fill_snapshot(
            trade,
            fill_id=f"workspace-qa-fill-{index}",
            entry_price=(0.40, 0.65, 0.45, 0.70, 0.52)[index],
            shares=(100, 60, 80, 40, 50)[index],
            fees=1,
            sportsbook="Polymarket",
        )
        try:
            stored = tracker.database.insert_personal_bet_fill(qa_user, fill)
        except Exception:
            continue
        model_dedupe = f"qa-model-clv-{index}"
        sharp_snapshot = sharp_snapshot_from_trade(trade)
        tracker.database.insert_tracker_snapshot(
            MODEL_TRACKER_USER_ID,
            {
                "snapshot_id": f"qa-model-snapshot-{index}",
                "dedupe_key": model_dedupe,
                "recommendation_version": "v2",
                "canonical_event_id": trade["event_slug"],
                "canonical_event_slug": trade["event_slug"],
                "canonical_market_id": trade["condition_id"],
                "outcome_id": trade["clob_token_id"],
                "event_title": trade["event_title"],
                "market_title": trade["market_title"],
                "recommended_side": trade["outcome"],
                "event_start_time": trade["event_date_et"],
                "recommendation_timestamp": (now - timedelta(hours=3)).isoformat(),
                "effective_entry_price": trade["_qa_recommendation"]["effective_entry_price"],
                "original_displayed_amount": 100 + index * 75,
                "original_recommended_units": 1 + index * 0.5,
                "final_recommended_fraction": 0.01,
                "estimated_win_probability": 0.55,
                "confidence_score": trade["confidence_score"],
                "sharps_count": trade["agreeing_wallet_count"],
                "primary_lead_wallet_id": trade["supporting_wallets"][0][
                    "wallet_address"
                ],
                "sharp_snapshot": sharp_snapshot,
            },
        )
        if clv_values[index] is not None:
            model_entry = 0.343 if index == 0 else trade["_qa_recommendation"]["effective_entry_price"]
            model_close = 0.43 if index == 0 else model_entry * (1 + clv_values[index] / 100)
            tracker.database.insert_closing_line(
                {
                    "tracker_type": "model",
                    "tracker_record_id": model_dedupe,
                    "user_id": MODEL_TRACKER_USER_ID,
                    "provider": "polymarket",
                    "provider_event_id": trade["event_slug"],
                    "provider_market_id": trade["condition_id"],
                    "provider_selection_id": trade["clob_token_id"],
                    "entry_price": model_entry,
                    "entry_implied_probability": model_entry,
                    "entry_stake": 100 + index * 75,
                    "closing_snapshot_timestamp": (now - timedelta(days=3 - index)).isoformat(),
                    "official_event_start_timestamp": (now - timedelta(days=3 - index) + timedelta(seconds=42)).isoformat(),
                    "closing_effective_price": model_close,
                    "closing_midpoint": model_close - 0.004,
                    "clv_cents": (model_close - model_entry) * 100,
                    "clv_probability_points": (model_close - model_entry) * 100,
                    "clv_pct": clv_values[index],
                    "midpoint_clv_pct": (((model_close - 0.004) / model_entry) - 1) * 100,
                    "clv_status": "captured",
                    "clv_unavailable_reason": None,
                    "comparison_stake": 100 + index * 75,
                    "quote_age_ms": 42000,
                    "liquidity_quality": "full",
                    "provider_close_source": "POLYMARKET_CLOB_ORDER_BOOK",
                    "calculation_version": "clv-v1",
                }
            )
        elif index == 3:
            tracker.database.insert_closing_line(
                {
                    "tracker_type": "model",
                    "tracker_record_id": model_dedupe,
                    "user_id": MODEL_TRACKER_USER_ID,
                    "provider": "polymarket",
                    "provider_event_id": trade["event_slug"],
                    "provider_market_id": trade["condition_id"],
                    "provider_selection_id": trade["clob_token_id"],
                    "entry_price": trade["_qa_recommendation"]["effective_entry_price"],
                    "entry_implied_probability": trade["_qa_recommendation"]["effective_entry_price"],
                    "entry_stake": 325,
                    "clv_status": "stale_quote",
                    "clv_unavailable_reason": "NO_FRESH_CLOSING_QUOTE",
                    "calculation_version": "clv-v1",
                }
            )
        personal_entry = float(stored["entry_price"])
        personal_pct = clv_values[index]
        if personal_pct is not None:
            personal_close = personal_entry * (1 + personal_pct / 100)
            tracker.database.insert_closing_line(
                {
                    "tracker_type": "personal", "tracker_record_id": stored["fill_id"],
                    "user_id": qa_user, "provider": "polymarket",
                    "provider_event_id": stored["canonical_event_id"],
                    "provider_market_id": stored["canonical_market_id"],
                    "provider_selection_id": stored["canonical_outcome_id"],
                    "entry_price": personal_entry, "entry_implied_probability": personal_entry,
                    "entry_stake": stored["position_cost"],
                    "closing_snapshot_timestamp": (now - timedelta(days=3 - index)).isoformat(),
                    "official_event_start_timestamp": (now - timedelta(days=3 - index) + timedelta(seconds=40)).isoformat(),
                    "closing_effective_price": personal_close, "closing_midpoint": personal_close - 0.003,
                    "clv_cents": (personal_close - personal_entry) * 100,
                    "clv_probability_points": (personal_close - personal_entry) * 100,
                    "clv_pct": personal_pct,
                    "midpoint_clv_pct": (((personal_close - 0.003) / personal_entry) - 1) * 100,
                    "clv_status": "captured", "clv_unavailable_reason": None,
                    "comparison_stake": stored["position_cost"], "quote_age_ms": 40000,
                    "liquidity_quality": "full", "provider_close_source": "POLYMARKET_CLOB_ORDER_BOOK",
                    "calculation_version": "clv-v1",
                }
            )
        if index == 2:
            tracker.database.insert_personal_position_exit(
                qa_user,
                {
                    "exit_id": "workspace-qa-exit-sold",
                    "idempotency_key": "workspace-qa-sold",
                    **{key: stored[key] for key in ("canonical_event_id", "canonical_market_id", "market_line", "canonical_outcome_id")},
                    "sportsbook": "Polymarket",
                    "shares_sold": 80,
                    "sell_price": 0.62,
                    "gross_proceeds": 49.6,
                    "fees": 0.6,
                    "net_proceeds": 49.0,
                    "sold_at": now.isoformat(),
                    "mode": "tracker_only",
                },
            )
        elif index == 3:
            tracker.database.update_personal_bet_status(
                stored["fill_id"], "lost", "Lost", now.isoformat()
            )

    @flask_app.route("/qa/session")
    def qa_session():
        user_id = request.args.get("user") or qa_user
        g.iconbets_user_id = user_id
        g.iconbets_new_user = False
        response = redirect("/trades")
        response.set_cookie("iconbets_user", user_id)
        response.delete_cookie(app_module.AUTH_SESSION_COOKIE)
        return response

    @flask_app.before_request
    def qa_live_feeds():
        if request.path == "/api/positive-ev/live":
            response = jsonify(qa_positive_ev_payload())
            response.headers["Cache-Control"] = "no-store"
            return response
        if request.path == "/api/dfs/lines":
            payload = request.get_json(silent=True) or {}
            raw_weights = request.args.get("weights")
            if raw_weights:
                try:
                    payload["weights"] = json.loads(raw_weights)
                except json.JSONDecodeError:
                    payload.pop("weights", None)
            response = jsonify(
                qa_dfs_payload(
                    weights=payload.get("weights"),
                    selected_book=str(
                        request.args.get("book") or "prizepicks"
                    ).strip().lower(),
                )
            )
            response.headers["Cache-Control"] = "no-store"
            return response
        return None

    return flask_app


if __name__ == "__main__":
    build_app().run(
        host="127.0.0.1",
        port=int(os.getenv("VISUAL_QA_PORT", "5001")),
        debug=False,
        use_reloader=False,
    )
