from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import sys
from types import MethodType

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from execution_providers import NOVIG_LOGO_URL, POLYMARKET_LOGO_URL
from flask import redirect
from personal_tracker import personal_fill_snapshot
from position_tracker import MODEL_TRACKER_USER_ID
from sharp_tracking import sharp_snapshot_from_trade


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


def qa_trade(index: int, *, sharps: int, score: int, entry: float, sharp_entry: float) -> dict:
    now = datetime.now(timezone.utc)
    categories = [
        ("Tennis", "ATP", "Swiss Open: Jaime Faria vs Stan Wawrinka", "Stan Wawrinka", "Moneyline"),
        ("Baseball", "MLB", "New York Yankees vs Boston Red Sox", "Yankees", "Moneyline"),
        ("Soccer", "FIFA World Cup", "Spain vs France", "Spain", "To Advance"),
        ("Basketball", "WNBA", "New York Liberty vs Las Vegas Aces", "Over 167.5", "Game Total"),
    ]
    category, league, event, outcome, market = categories[index % len(categories)]
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
        "event_date_et": (now + timedelta(hours=2 + index)).isoformat(),
        "event_time_et": f"Today, {2 + index}:30 PM",
        "resolution_time": (now + timedelta(hours=2 + index)).isoformat(),
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


def build_app():
    flask_app = app_module.create_app(start_background=False)
    tracker = flask_app.extensions["tracker_service"]
    now = datetime.now(timezone.utc)
    trades = [
        qa_trade(0, sharps=1, score=64, entry=0.34, sharp_entry=0.34),
        qa_trade(1, sharps=3, score=88, entry=0.507, sharp_entry=0.489),
        qa_trade(2, sharps=2, score=76, entry=0.40, sharp_entry=0.389),
        qa_trade(3, sharps=2, score=73, entry=0.455, sharp_entry=0.46),
    ]
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

    def evaluate(self, play, bankroll):
        rec = deepcopy(play["_qa_recommendation"])
        rec["bankroll"] = bankroll
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
    tracker.client.get_price_history = lambda token_id, interval="1d", fidelity=15: [
        {"t": int((now - timedelta(minutes=15 * step)).timestamp()), "p": str(0.31 + step * 0.002)}
        for step in range(24, -1, -1)
    ]
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

    def attach_options(rows):
        for index, row in enumerate(rows):
            current = row["recommendation"]["current_user_entry_price"]
            row["executionOptions"] = [
                {
                    "providerName": "Polymarket",
                    "providerKey": "polymarket",
                    "marketId": row["condition_id"],
                    "selectionId": row["clob_token_id"],
                    "displayOdds": f"{current * 100:.1f}¢",
                    "americanOdds": None,
                    "deepLink": row["market_url"],
                    "logoUrl": POLYMARKET_LOGO_URL,
                    "isAvailable": True,
                    "lastUpdated": now.isoformat(),
                    "matchingConfidence": "Exact",
                    "tooltip": "Polymarket Current Best Price",
                }
            ]
            if index in {0, 2}:
                row["executionOptions"].append(
                    {
                        "providerName": "NoVIG",
                        "providerKey": "novig",
                        "marketId": f"novig-{index}",
                        "selectionId": f"novig-selection-{index}",
                        "displayOdds": "+108" if index == 0 else "-112",
                        "americanOdds": 108 if index == 0 else -112,
                        "deepLink": "https://novig.us/",
                        "logoUrl": NOVIG_LOGO_URL,
                        "isAvailable": True,
                        "lastUpdated": now.isoformat(),
                        "matchingConfidence": "Exact",
                        "tooltip": "NoVIG Current Best Price",
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
    clv_values = (25.3644314869, -8.0, 6.25, None)
    for index, trade in enumerate(trades):
        fill = personal_fill_snapshot(
            trade,
            fill_id=f"workspace-qa-fill-{index}",
            entry_price=(0.40, 0.65, 0.45, 0.70)[index],
            shares=(100, 60, 80, 40)[index],
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
        response = redirect("/trades")
        response.set_cookie("iconbets_user", qa_user)
        return response

    return flask_app


if __name__ == "__main__":
    build_app().run(
        host="127.0.0.1",
        port=int(os.getenv("VISUAL_QA_PORT", "5001")),
        debug=False,
        use_reloader=False,
    )
