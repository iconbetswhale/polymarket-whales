from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import MethodType

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from execution_providers import NOVIG_LOGO_URL, POLYMARKET_LOGO_URL


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
    return flask_app


if __name__ == "__main__":
    build_app().run(host="127.0.0.1", port=5001, debug=False, use_reloader=False)
