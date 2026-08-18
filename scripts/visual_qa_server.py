from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from math import pi, sin
from pathlib import Path
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
from flask import g, redirect, request
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


def build_app():
    flask_app = app_module.create_app(start_background=False)
    tracker = flask_app.extensions["tracker_service"]
    now = datetime.now(timezone.utc)
    trades = qa_trades(now)
    snapshot = {
        "trades_to_play": trades,
        "trades": trades,
        "positions": trades,
        "status": {
            "state": "ok",
            "enabled_wallet_count": 9,
            "last_successful_refresh": now.isoformat(),
        },
    }

    tracker.get_snapshot = MethodType(lambda self: deepcopy(snapshot), tracker)
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

    return flask_app


if __name__ == "__main__":
    build_app().run(
        host="127.0.0.1",
        port=int(os.getenv("VISUAL_QA_PORT", "5001")),
        debug=False,
        use_reloader=False,
    )
