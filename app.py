from __future__ import annotations

import json
import logging
import os
import secrets
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import Flask, g, jsonify, redirect, render_template, request, url_for

from bet_sizing import build_recommendation
from bet_tracker import replay_tracker
from config import get_settings
from position_tracker import TrackerService
from trade_scoring import filter_trades_to_play

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
LOGGER = logging.getLogger(__name__)
EASTERN = ZoneInfo("America/New_York")
USER_COOKIE = "iconbets_user"
VALID_TRADE_DATE_RANGES = {"today", "next24", "next7", "custom"}


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _has_positive_recommendation(trade: dict) -> bool:
    recommendation = trade.get("recommendation") or {}
    return (
        recommendation.get("available") is True
        and _safe_float(recommendation.get("final_recommended_fraction")) > 0
        and _safe_float(recommendation.get("recommended_amount")) > 0
    )


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=EASTERN)
    return parsed.astimezone(timezone.utc)


def create_app(start_background: bool = True) -> Flask:
    settings = get_settings()
    tracker = TrackerService(settings, auto_start=False)

    app = Flask(__name__)
    app.extensions["tracker_service"] = tracker
    app.extensions["tracker_starting"] = False
    app.config["SETTINGS"] = settings

    @app.before_request
    def prepare_request():
        user_id = request.cookies.get(USER_COOKIE)
        g.iconbets_new_user = not bool(user_id)
        g.iconbets_user_id = user_id or secrets.token_urlsafe(24)

        if (
            not start_background
            or app.extensions.get("tracker_starting")
            or tracker._started
        ):
            return
        if os.getenv("VERCEL"):
            tracker.start()
            return

        def start_tracker() -> None:
            try:
                tracker.start()
            finally:
                app.extensions["tracker_starting"] = False

        app.extensions["tracker_starting"] = True
        threading.Thread(
            target=start_tracker, name="tracker-startup", daemon=True
        ).start()

    @app.after_request
    def persist_user_cookie(response):
        if getattr(g, "iconbets_new_user", False):
            response.set_cookie(
                USER_COOKIE,
                g.iconbets_user_id,
                max_age=60 * 60 * 24 * 365,
                httponly=True,
                secure=request.is_secure,
                samesite="Lax",
            )
        return response

    def user_settings() -> dict:
        return tracker.database.get_or_create_user_settings(
            g.iconbets_user_id,
            settings.default_bankroll,
            settings.unit_percentage,
        )

    def public_trade(play: dict, bankroll: float) -> dict:
        recommendation = build_recommendation(play, bankroll, tracker.sizing_config)
        payload = json.loads(json.dumps(play))
        orderbook = payload.pop("orderbook", {}) or {}
        payload["orderbook_summary"] = {
            "best_ask": (orderbook.get("asks") or [{}])[0].get("price")
            if orderbook.get("asks")
            else None,
            "best_bid": (orderbook.get("bids") or [{}])[0].get("price")
            if orderbook.get("bids")
            else None,
            "ask_levels": len(orderbook.get("asks") or []),
            "bid_levels": len(orderbook.get("bids") or []),
            "min_order_size": orderbook.get("min_order_size"),
            "tick_size": orderbook.get("tick_size"),
            "timestamp": orderbook.get("timestamp"),
        }
        payload["recommendation"] = recommendation
        return payload

    @app.route("/")
    def index():
        return redirect(url_for("trades_page"))

    @app.route("/overview")
    def overview_page():
        return render_template(
            "overview.html", title="IconBets Overview", page="overview"
        )

    @app.route("/trades")
    def trades_page():
        return render_template(
            "trades.html", title="IconBets Trades to Play", page="trades"
        )

    @app.route("/live-positions")
    def live_positions_page():
        return render_template(
            "live_positions.html",
            title="IconBets Live Positions",
            page="live-positions",
        )

    @app.route("/wallets")
    def wallets_page():
        return render_template("wallets.html", title="IconBets Wallets", page="wallets")

    @app.route("/position-history")
    def position_history_page():
        return render_template(
            "position_history.html",
            title="IconBets Position History",
            page="position-history",
        )

    @app.route("/bet-tracker")
    def bet_tracker_page():
        return render_template(
            "bet_tracker.html", title="IconBets Bet Tracker", page="bet-tracker"
        )

    @app.route("/history")
    def legacy_history():
        return redirect(url_for("position_history_page"), code=301)

    @app.route("/health")
    def health():
        snapshot = tracker.get_snapshot()
        status = snapshot["status"]
        return jsonify(
            {
                "app_status": status["app_status"],
                "database_status": status["database"],
                "enabled_wallet_count": status["enabled_wallet_count"],
                "valid_wallet_count": status["valid_wallet_count"],
                "invalid_wallet_count": status["invalid_wallet_count"],
                "last_refresh_attempt": status["last_refresh_attempt"],
                "last_successful_refresh": status["last_successful_refresh"],
                "position_count": status["position_count"],
                "recent_trade_count": status["recent_trade_count"],
                "api_status": status["api_status"],
            }
        )

    @app.route("/api/status")
    def api_status():
        return jsonify(tracker.get_snapshot()["status"])

    @app.route("/api/overview")
    def api_overview():
        snapshot = tracker.get_snapshot()
        current_settings = user_settings()
        bankroll = _safe_float(current_settings["starting_bankroll"])
        top = filter_trades_to_play(
            snapshot.get("trades_to_play", []), date_range="today"
        )[:3]
        return jsonify(
            {
                "data": snapshot["status"].get("overview", {}),
                "top_trades": [public_trade(play, bankroll) for play in top],
                "status": snapshot["status"],
            }
        )

    @app.route("/api/positions")
    def api_positions():
        snapshot = tracker.get_snapshot()
        rows = snapshot.get("positions", [])
        lifecycle = request.args.get("lifecycle", "")
        search = request.args.get("q", "").strip().lower()
        wallet = request.args.get("wallet", "").strip().lower()
        sport = request.args.get("sport", "").strip().lower()
        league = request.args.get("league", "").strip().lower()
        market = request.args.get("market", "").strip().lower()
        if lifecycle:
            rows = [
                row
                for row in rows
                if str(row.get("lifecycle_status") or "") == lifecycle
            ]
        if search:
            rows = [
                row
                for row in rows
                if search
                in " ".join(
                    str(row.get(field) or "").lower()
                    for field in (
                        "wallet_label",
                        "wallet_address",
                        "event_title",
                        "market_title",
                        "outcome",
                        "category",
                        "league",
                    )
                )
            ]
        if wallet:
            rows = [
                row
                for row in rows
                if wallet
                in {
                    str(row.get("wallet_label") or "").lower(),
                    str(row.get("wallet_address") or "").lower(),
                }
            ]
        if sport:
            rows = [
                row for row in rows if str(row.get("category") or "").lower() == sport
            ]
        if league:
            rows = [
                row for row in rows if str(row.get("league") or "").lower() == league
            ]
        if market:
            rows = [
                row
                for row in rows
                if market
                in str(
                    row.get("sports_market_type") or row.get("market_title") or ""
                ).lower()
            ]
        sort = request.args.get("sort", "value-desc")
        sorters = {
            "value-desc": lambda row: -_safe_float(row.get("current_value")),
            "value-asc": lambda row: _safe_float(row.get("current_value")),
            "start-asc": lambda row: str(row.get("resolution_time") or "~"),
            "wallet-asc": lambda row: str(row.get("wallet_label") or "").lower(),
        }
        rows = sorted(rows, key=sorters.get(sort, sorters["value-desc"]))
        page = max(request.args.get("page", 1, type=int) or 1, 1)
        per_page = min(max(request.args.get("per_page", 50, type=int) or 50, 1), 100)
        start = (page - 1) * per_page
        return jsonify(
            {
                "data": rows[start : start + per_page],
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total": len(rows),
                    "has_next": start + per_page < len(rows),
                    "has_prev": page > 1,
                },
                "status": snapshot["status"],
            }
        )

    @app.route("/api/wallets")
    def api_wallets():
        snapshot = tracker.get_snapshot()
        rows = snapshot.get("wallets", [])
        search = request.args.get("q", "").strip().lower()
        status_filter = request.args.get("status", "").strip().lower()
        if search:
            rows = [
                row
                for row in rows
                if search in f"{row.get('label', '')} {row.get('address', '')}".lower()
            ]
        if status_filter:
            rows = [
                row
                for row in rows
                if str(row.get("sync_status") or row.get("status") or "").lower()
                == status_filter
            ]
        sort = request.args.get("sort", "label-asc")
        if sort == "positions-desc":
            rows = sorted(
                rows, key=lambda row: -int(row.get("open_position_count") or 0)
            )
        elif sort == "sync-desc":
            rows = sorted(
                rows, key=lambda row: str(row.get("last_synced_at") or ""), reverse=True
            )
        else:
            rows = sorted(rows, key=lambda row: str(row.get("label") or "").lower())
        return jsonify({"data": rows, "total": len(rows), "status": snapshot["status"]})

    @app.route("/api/trades")
    def api_trades():
        snapshot = tracker.get_snapshot()
        return jsonify({"data": snapshot["trades"], "status": snapshot["status"]})

    @app.route("/api/trades-to-play")
    def api_trades_to_play():
        snapshot = tracker.get_snapshot()
        date_range = request.args.get("date_range", "today")
        if date_range not in VALID_TRADE_DATE_RANGES:
            return jsonify({"error": "Unsupported date range"}), 400
        current_settings = user_settings()
        bankroll = _safe_float(current_settings["starting_bankroll"])
        tracker.track_recommendations_for_user(
            g.iconbets_user_id, bankroll, snapshot.get("trades_to_play", [])
        )
        page = max(request.args.get("page", 1, type=int) or 1, 1)
        per_page = min(max(request.args.get("per_page", 100, type=int) or 100, 1), 100)
        filtered = filter_trades_to_play(
            snapshot.get("trades_to_play", []),
            search=request.args.get("q", ""),
            min_sharps=max(request.args.get("min_sharps", 0, type=int) or 0, 0),
            date_range=date_range,
            custom_start=request.args.get("custom_start"),
            custom_end=request.args.get("custom_end"),
            min_confidence=max(request.args.get("min_confidence", 0, type=int) or 0, 0),
            sport=request.args.get("sport", ""),
            league=request.args.get("league", ""),
            wallet=request.args.get("wallet", ""),
        )
        sized = [public_trade(play, bankroll) for play in filtered]
        actionable = [trade for trade in sized if _has_positive_recommendation(trade)]
        start = (page - 1) * per_page
        return jsonify(
            {
                "data": actionable[start : start + per_page],
                "bankroll": current_settings,
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total": len(actionable),
                    "has_next": start + per_page < len(actionable),
                    "has_prev": page > 1,
                },
                "status": snapshot["status"],
            }
        )

    @app.route("/api/history")
    def api_history():
        return jsonify(
            tracker.database.get_events_page(
                page=request.args.get("page", 1, type=int),
                per_page=request.args.get("per_page", 50, type=int),
                search=request.args.get("q", ""),
                wallet=request.args.get("wallet", ""),
                sport=request.args.get("sport", ""),
                league=request.args.get("league", ""),
                event_type=request.args.get("event_type", ""),
                start=request.args.get("start", ""),
                end=request.args.get("end", ""),
                sort=request.args.get("sort", "desc"),
            )
        )

    @app.route("/api/consensus")
    def api_consensus():
        snapshot = tracker.get_snapshot()
        return jsonify({"data": snapshot["consensus"], "status": snapshot["status"]})

    @app.route("/api/user-settings", methods=["GET", "PUT"])
    def api_user_settings():
        current = user_settings()
        if request.method == "PUT":
            payload = request.get_json(silent=True) or {}
            bankroll = _safe_float(payload.get("starting_bankroll"), -1)
            if bankroll <= 0:
                return jsonify(
                    {"error": "Starting bankroll must be greater than zero."}
                ), 400
            current = tracker.database.update_user_settings(
                g.iconbets_user_id,
                bankroll,
                settings.unit_percentage,
            )
            tracker.track_recommendations_for_user(g.iconbets_user_id, bankroll)
        current["unit_value"] = _safe_float(current["starting_bankroll"]) * _safe_float(
            current["unit_percentage"]
        )
        return jsonify({"data": current})

    @app.route("/api/bet-tracker")
    def api_bet_tracker():
        current_settings = user_settings()
        replay = replay_tracker(
            tracker.database.get_tracker_records(g.iconbets_user_id),
            _safe_float(current_settings["starting_bankroll"]),
        )
        rows = replay["rows"]
        query = request.args.get("q", "").strip().lower()
        status_filter = request.args.get("status", "").strip().lower()
        sport = request.args.get("sport", "").strip().lower()
        league = request.args.get("league", "").strip().lower()
        result = request.args.get("result", "").strip().lower()
        min_sharps = max(request.args.get("min_sharps", 0, type=int) or 0, 0)
        if query:
            rows = [
                row
                for row in rows
                if query
                in " ".join(
                    str((row.get("snapshot") or {}).get(field) or "").lower()
                    for field in (
                        "event_title",
                        "market_title",
                        "recommended_side",
                        "agreeing_wallet_labels",
                    )
                )
            ]
        if status_filter:
            rows = [
                row
                for row in rows
                if str(row.get("status") or "").lower() == status_filter
            ]
        if sport:
            rows = [
                row
                for row in rows
                if str((row.get("snapshot") or {}).get("category") or "").lower()
                == sport
            ]
        if league:
            rows = [
                row
                for row in rows
                if str((row.get("snapshot") or {}).get("league") or "").lower()
                == league
            ]
        if result:
            rows = [
                row for row in rows if str(row.get("result") or "").lower() == result
            ]
        if min_sharps:
            rows = [
                row
                for row in rows
                if int((row.get("snapshot") or {}).get("sharps_count") or 0)
                >= min_sharps
            ]

        graph_range = request.args.get("graph_range", "month")
        now = datetime.now(timezone.utc)
        cutoffs = {
            "today": now - timedelta(days=1),
            "week": now - timedelta(days=7),
            "month": now - timedelta(days=31),
            "year": now - timedelta(days=366),
        }
        cutoff = cutoffs.get(graph_range, cutoffs["month"])
        graph = [
            point
            for point in replay["graph"]
            if point.get("timestamp") is None
            or (
                _parse_datetime(point.get("timestamp"))
                or datetime.min.replace(tzinfo=timezone.utc)
            )
            >= cutoff
        ]
        page = max(request.args.get("page", 1, type=int) or 1, 1)
        per_page = min(max(request.args.get("per_page", 50, type=int) or 50, 1), 100)
        start = (page - 1) * per_page
        return jsonify(
            {
                "data": list(reversed(rows))[start : start + per_page],
                "summary": replay["summary"],
                "graph": graph,
                "bankroll": current_settings,
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total": len(rows),
                    "has_next": start + per_page < len(rows),
                    "has_prev": page > 1,
                },
            }
        )

    @app.route("/api/price-history")
    def api_price_history():
        token_id = request.args.get("token_id", "")
        snapshot = tracker.get_snapshot()
        allowed = {
            str(position.get("clob_token_id"))
            for position in snapshot.get("positions", [])
            if position.get("clob_token_id")
        }
        if token_id not in allowed:
            return jsonify({"error": "Unknown tracked outcome token"}), 404
        try:
            history = tracker.client.get_price_history(
                token_id, interval=request.args.get("interval", "1d"), fidelity=15
            )
        except Exception as exc:
            LOGGER.warning("Price-history request failed: %s", exc)
            return jsonify(
                {"error": "Live price history is temporarily unavailable"}
            ), 502
        return jsonify({"data": history, "source": "Polymarket CLOB prices-history"})

    @app.route("/api/refresh", methods=["POST"])
    def api_refresh():
        tracker.refresh()
        return jsonify({"status": tracker.get_snapshot()["status"]})

    return app


app = create_app(start_background=True)


if __name__ == "__main__":
    current_settings = get_settings()
    app.run(host="0.0.0.0", port=current_settings.dashboard_port, debug=False)
