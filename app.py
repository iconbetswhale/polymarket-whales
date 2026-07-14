from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import Flask, g, jsonify, redirect, render_template, request, url_for

from bet_tracker import replay_tracker
from config import get_settings
from personal_tracker import (
    canonical_trade_identity,
    has_complete_identity,
    hidden_trade_snapshot,
    identity_key,
    personal_exposure_for_trade,
    personal_fill_snapshot,
    replay_personal_tracker,
)
from position_tracker import MODEL_TRACKER_USER_ID, TrackerService
from trade_scoring import filter_trades_to_play

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
LOGGER = logging.getLogger(__name__)
EASTERN = ZoneInfo("America/New_York")
USER_COOKIE = "iconbets_user"
ADMIN_COOKIE = "iconbets_tracker_admin"
VALID_TRADE_DATE_RANGES = {"today", "next24", "next7", "custom"}


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _slippage_fraction(user_entry, whale_entry) -> float | None:
    user_price = _safe_float(user_entry, -1.0)
    whale_price = _safe_float(whale_entry, -1.0)
    if user_price < 0 or whale_price <= 0:
        return None
    return (user_price - whale_price) / whale_price


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


def _format_event_start(value: str | None, now: datetime | None = None) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        return "Time unavailable"

    eastern = parsed.astimezone(EASTERN)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference_eastern = reference.astimezone(EASTERN)
    day_offset = (eastern.date() - reference_eastern.date()).days
    hour = eastern.strftime("%I").lstrip("0") or "0"
    time_text = f"{hour}:{eastern.strftime('%M %p')}"

    if day_offset == 0:
        return f"Today, {time_text}"
    if day_offset == 1:
        return f"Tomorrow, {time_text}"
    if eastern.year == reference_eastern.year:
        return f"{eastern.strftime('%b')} {eastern.day}, {time_text}"
    return f"{eastern.strftime('%b')} {eastern.day}, {eastern.year} \u00b7 {time_text}"


def _trade_card_view(
    play: dict, recommendation: dict, now: datetime | None = None
) -> dict:
    primary = play.get("primary_trader") or {}
    evidence = play.get("evidence_inputs") or {}
    hit_rate = evidence.get("adjusted_category_hit_rate")
    sharp_entry = recommendation.get("sharp_average_entry_price")
    if sharp_entry is None:
        sharp_entry = play.get("average_entry_price")

    return {
        "event_time": _format_event_start(play.get("event_date_et"), now),
        "trader_bet_amount": primary.get("amount"),
        "trader_average_entry_price": sharp_entry,
        "relative_bet_size": primary.get("relative_units"),
        "category_hit_rate": None if hit_rate is None else _safe_float(hit_rate),
        "recommended_shares": recommendation.get("recommended_shares"),
        "recommended_amount": recommendation.get("recommended_amount"),
        "recommended_units": recommendation.get("recommended_units"),
        "current_actionable_price": recommendation.get("current_user_entry_price"),
        "slippage_fraction": _slippage_fraction(
            recommendation.get("current_user_entry_price"), sharp_entry
        ),
    }


def create_app(start_background: bool = True) -> Flask:
    settings = get_settings()
    tracker = TrackerService(settings, auto_start=False)

    app = Flask(__name__)
    app.extensions["tracker_service"] = tracker
    app.extensions["tracker_starting"] = False
    app.config["SETTINGS"] = settings
    app.jinja_env.globals["asset_version"] = (
        os.getenv("VERCEL_GIT_COMMIT_SHA") or os.getenv("ASSET_VERSION") or "local"
    )

    @app.before_request
    def prepare_request():
        user_id = request.cookies.get(USER_COOKIE)
        g.iconbets_new_user = not bool(user_id)
        g.iconbets_user_id = user_id or secrets.token_urlsafe(24)

        if request.endpoint == "api_model_tracker_reconcile":
            return
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
            set_user_cookie(response, g.iconbets_user_id)
        return response

    def set_user_cookie(response, user_id: str) -> None:
        response.set_cookie(
            USER_COOKIE,
            user_id,
            max_age=60 * 60 * 24 * 365,
            httponly=True,
            secure=request.is_secure,
            samesite="Lax",
            path="/",
        )

    def user_settings() -> dict:
        return tracker.database.get_or_create_user_settings(
            g.iconbets_user_id,
            settings.default_bankroll,
            settings.unit_percentage,
        )

    def public_trade(play: dict, bankroll: float) -> dict:
        evaluation = tracker.evaluate_recommendation(play, bankroll)
        recommendation = evaluation["recommendation"]
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
        payload["modelTrackerEligible"] = evaluation["model_tracker_eligible"]
        payload["modelTrackerRejectionReason"] = evaluation[
            "model_tracker_rejection_reason"
        ]
        payload["recommendationSnapshotId"] = evaluation[
            "recommendation_snapshot_id"
        ]
        payload["recommendationIdempotencyKey"] = evaluation[
            "recommendation_idempotency_key"
        ]
        payload["card"] = _trade_card_view(payload, recommendation)
        return payload

    def admin_cookie_value() -> str:
        password = settings.admin_password or ""
        return hmac.new(
            password.encode("utf-8"),
            b"iconbets-model-tracker-admin",
            hashlib.sha256,
        ).hexdigest()

    def is_admin() -> bool:
        if not settings.admin_password:
            return False
        supplied = request.cookies.get(ADMIN_COOKIE, "")
        return bool(supplied) and hmac.compare_digest(supplied, admin_cookie_value())

    def has_job_authorization() -> bool:
        if is_admin():
            return True
        configured = settings.tracker_job_secret or ""
        supplied = request.headers.get("Authorization", "")
        if supplied.lower().startswith("bearer "):
            supplied = supplied[7:].strip()
        return bool(configured and supplied) and hmac.compare_digest(
            supplied, configured
        )

    def find_trade(snapshot: dict, trade_id: str) -> dict | None:
        return next(
            (
                trade
                for trade in snapshot.get("trades_to_play", [])
                if str(trade.get("id") or "") == trade_id
            ),
            None,
        )

    def hidden_records_by_key(user_id: str) -> tuple[list[dict], dict[tuple, dict]]:
        records = tracker.database.get_hidden_trades(user_id)
        return records, {identity_key(record): record for record in records}

    def decorate_personal_state(
        trade: dict,
        active_personal_fills: list[dict],
        hidden_by_key: dict[tuple, dict],
    ) -> dict:
        hidden = hidden_by_key.get(identity_key(canonical_trade_identity(trade)))
        exposure = personal_exposure_for_trade(trade, active_personal_fills)
        trade["isHidden"] = bool(hidden)
        trade["hiddenRecordId"] = hidden.get("id") if hidden else None
        trade["personalExposureType"] = exposure["type"]
        trade["personalEntryCount"] = exposure["personalEntryCount"]
        trade["hasExactPersonalPosition"] = exposure["hasExactPersonalPosition"]
        trade["hasOpposingPersonalPosition"] = exposure["hasOpposingPersonalPosition"]
        trade["hasSameEventDifferentMarketPosition"] = exposure[
            "hasSameEventDifferentMarketPosition"
        ]
        trade["personalExposureSummary"] = exposure
        return trade

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

    @app.route("/model-tracker")
    def model_tracker_page():
        return render_template(
            "bet_tracker.html", title="IconBets Model Tracker", page="model-tracker"
        )

    @app.route("/personal-tracking")
    def personal_tracking_page():
        return render_template(
            "personal_tracking.html",
            title="IconBets Personal Tracking",
            page="personal-tracking",
        )

    @app.route("/bet-tracker")
    def legacy_bet_tracker():
        return redirect(url_for("model_tracker_page"), code=301)

    @app.route("/personal-tracker")
    def legacy_personal_tracker():
        return redirect(url_for("personal_tracking_page"), code=301)

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
        page = max(request.args.get("page", 1, type=int) or 1, 1)
        per_page = min(max(request.args.get("per_page", 100, type=int) or 100, 1), 100)
        show_hidden = request.args.get("show_hidden", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        hidden_records, hidden_by_key = hidden_records_by_key(g.iconbets_user_id)
        active_personal_fills = tracker.database.get_personal_bet_fills(
            g.iconbets_user_id, active_only=True
        )
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
        sized = [
            decorate_personal_state(
                public_trade(play, bankroll), active_personal_fills, hidden_by_key
            )
            for play in filtered
        ]
        actionable = [trade for trade in sized if _has_positive_recommendation(trade)]
        visible = (
            actionable
            if show_hidden
            else [trade for trade in actionable if not trade["isHidden"]]
        )
        start = (page - 1) * per_page
        return jsonify(
            {
                "data": visible[start : start + per_page],
                "bankroll": current_settings,
                "hiddenCount": len(hidden_records),
                "showHidden": show_hidden,
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total": len(visible),
                    "has_next": start + per_page < len(visible),
                    "has_prev": page > 1,
                },
                "status": snapshot["status"],
            }
        )

    @app.route("/api/hidden-trades", methods=["GET", "POST", "DELETE"])
    def api_hidden_trades():
        if request.method == "DELETE":
            restored = tracker.database.restore_all_hidden_trades(g.iconbets_user_id)
            return jsonify({"restored": restored})

        snapshot = tracker.get_snapshot()
        current_settings = user_settings()
        bankroll = _safe_float(current_settings["starting_bankroll"])
        if request.method == "POST":
            payload = request.get_json(silent=True) or {}
            trade = find_trade(snapshot, str(payload.get("trade_id") or ""))
            if not trade:
                return jsonify({"error": "Trade is no longer available."}), 404
            hidden = hidden_trade_snapshot(trade)
            if not has_complete_identity(hidden):
                return jsonify({"error": "Trade is missing a canonical identity."}), 409
            record = tracker.database.hide_trade(g.iconbets_user_id, hidden)
            public_record = {
                key: value for key, value in record.items() if key != "user_id"
            }
            return jsonify({"data": public_record}), 201

        records = tracker.database.get_hidden_trades(g.iconbets_user_id)
        actionable_keys = {
            identity_key(canonical_trade_identity(trade))
            for trade in (
                public_trade(play, bankroll)
                for play in snapshot.get("trades_to_play", [])
            )
            if _has_positive_recommendation(trade)
        }
        rows = [
            {
                **{key: value for key, value in record.items() if key != "user_id"},
                "active": identity_key(record) in actionable_keys,
                "status": (
                    "Eligible to restore"
                    if identity_key(record) in actionable_keys
                    else "No longer active"
                ),
            }
            for record in records
        ]
        return jsonify({"data": rows, "total": len(rows)})

    @app.route("/api/hidden-trades/<int:hidden_id>", methods=["DELETE"])
    def api_restore_hidden_trade(hidden_id: int):
        if not tracker.database.restore_hidden_trade(g.iconbets_user_id, hidden_id):
            return jsonify({"error": "Hidden trade was not found."}), 404
        return jsonify({"restored": True})

    @app.route("/api/personal-exposure")
    def api_personal_exposure():
        snapshot = tracker.get_snapshot()
        trade = find_trade(snapshot, request.args.get("trade_id", ""))
        if not trade:
            return jsonify({"error": "Trade is no longer available."}), 404
        active_fills = tracker.database.get_personal_bet_fills(
            g.iconbets_user_id, active_only=True
        )
        return jsonify(
            {
                "data": personal_exposure_for_trade(
                    trade, active_fills, include_entries=True
                )
            }
        )

    @app.route("/api/personal-bets", methods=["POST"])
    def api_personal_bets():
        payload = request.get_json(silent=True) or {}
        snapshot = tracker.get_snapshot()
        trade = find_trade(snapshot, str(payload.get("trade_id") or ""))
        if not trade:
            return jsonify({"error": "Trade is no longer available."}), 404

        current_settings = user_settings()
        public = public_trade(trade, _safe_float(current_settings["starting_bankroll"]))
        if not _has_positive_recommendation(public):
            return jsonify({"error": "Trade is no longer actionable."}), 409
        identity = canonical_trade_identity(public)
        if not has_complete_identity(identity):
            return jsonify({"error": "Trade is missing a canonical identity."}), 409

        active_fills = tracker.database.get_personal_bet_fills(
            g.iconbets_user_id, active_only=True
        )
        exposure = personal_exposure_for_trade(public, active_fills)
        if exposure["hasOpposingPersonalPosition"] and not bool(
            payload.get("confirm_conflict")
        ):
            return jsonify(
                {
                    "error": (
                        "You already hold the opposing outcome in this market. "
                        "Confirm opposing exposure before saving."
                    ),
                    "confirmationRequired": "conflict",
                    "personalExposureSummary": exposure,
                }
            ), 409
        if exposure["hasExactPersonalPosition"] and not bool(
            payload.get("confirm_duplicate")
        ):
            return jsonify(
                {
                    "error": (
                        "You already have a personal position on this exact "
                        "selection. Confirm another purchase before saving."
                    ),
                    "confirmationRequired": "duplicate",
                    "personalExposureSummary": exposure,
                }
            ), 409

        entry_price = _safe_float(payload.get("entry_price"), -1)
        shares = _safe_float(payload.get("shares"), -1)
        fees = _safe_float(payload.get("fees"), 0)
        if not 0 < entry_price < 1:
            return jsonify({"error": "Entry price must be between 0 and 1."}), 400
        if shares <= 0:
            return jsonify({"error": "Shares must be greater than zero."}), 400
        if fees < 0:
            return jsonify({"error": "Fees cannot be negative."}), 400

        fill = personal_fill_snapshot(
            public,
            fill_id=secrets.token_urlsafe(18),
            entry_price=entry_price,
            shares=shares,
            fees=fees,
        )
        stored = tracker.database.insert_personal_bet_fill(
            g.iconbets_user_id, fill, status="scheduled"
        )
        updated_fills = [*active_fills, stored]
        updated_exposure = personal_exposure_for_trade(public, updated_fills)
        public_fill = {key: value for key, value in stored.items() if key != "user_id"}
        return jsonify(
            {"data": public_fill, "personalExposureSummary": updated_exposure}
        ), 201

    @app.route("/api/personal-bets/<fill_id>", methods=["DELETE"])
    def api_delete_personal_bet(fill_id: str):
        if not tracker.database.cancel_personal_bet_fill(g.iconbets_user_id, fill_id):
            return jsonify({"error": "Personal fill was not found."}), 404
        return jsonify({"canceled": True})

    @app.route("/api/personal-tracker")
    def api_personal_tracker():
        replay = replay_personal_tracker(
            tracker.database.get_personal_bet_fills(g.iconbets_user_id)
        )
        rows = replay["rows"]
        query = request.args.get("q", "").strip().lower()
        status_filter = request.args.get("status", "").strip().lower()
        result_filter = request.args.get("result", "").strip().lower()
        if query:
            rows = [
                row
                for row in rows
                if query
                in " ".join(
                    str(row.get(field) or "").lower()
                    for field in ("event_title", "market_title", "selection")
                )
            ]
        if status_filter:
            rows = [
                row
                for row in rows
                if str(row.get("status") or "").lower() == status_filter
            ]
        if result_filter:
            rows = [
                row
                for row in rows
                if str(row.get("result") or "").lower() == result_filter
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
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total": len(rows),
                    "has_next": start + per_page < len(rows),
                    "has_prev": page > 1,
                },
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
        current["unit_value"] = _safe_float(current["starting_bankroll"]) * _safe_float(
            current["unit_percentage"]
        )
        return jsonify({"data": current})

    @app.route("/api/model-tracker/settings", methods=["GET", "PUT"])
    @app.route("/api/bet-tracker/settings", methods=["GET", "PUT"])
    def api_bet_tracker_settings():
        current = user_settings()
        if request.method == "PUT":
            payload = request.get_json(silent=True) or {}
            bankroll = _safe_float(payload.get("tracker_bankroll"), -1)
            if bankroll <= 0:
                return jsonify(
                    {"error": "Model Tracker bankroll must be greater than zero."}
                ), 400
            current = tracker.database.update_tracker_bankroll(
                g.iconbets_user_id,
                bankroll,
            )
        return jsonify({"data": current})

    @app.route("/api/model-tracker")
    @app.route("/api/bet-tracker")
    def api_bet_tracker():
        current_settings = user_settings()
        replay = replay_tracker(
            tracker.database.get_tracker_records(MODEL_TRACKER_USER_ID),
            _safe_float(current_settings["tracker_bankroll"]),
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
                "tracking": {
                    key: value
                    for key, value in tracker.tracking_diagnostics(
                        MODEL_TRACKER_USER_ID
                    ).items()
                    if key != "rejections"
                },
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total": len(rows),
                    "has_next": start + per_page < len(rows),
                    "has_prev": page > 1,
                },
            }
        )

    @app.route("/api/admin/login", methods=["POST"])
    def api_admin_login():
        if not settings.admin_password:
            return jsonify({"error": "Administrator access is not configured."}), 404
        supplied = str((request.get_json(silent=True) or {}).get("password") or "")
        if not hmac.compare_digest(supplied, settings.admin_password):
            return jsonify({"error": "Invalid administrator password."}), 403
        response = jsonify({"authenticated": True})
        response.set_cookie(
            ADMIN_COOKIE,
            admin_cookie_value(),
            max_age=60 * 60 * 12,
            httponly=True,
            secure=request.is_secure,
            samesite="Strict",
        )
        return response

    @app.route("/api/admin/model-tracker/diagnostics")
    def api_model_tracker_diagnostics():
        if not is_admin():
            return jsonify({"error": "Administrator access required."}), 403
        return jsonify({"data": tracker.tracking_diagnostics(MODEL_TRACKER_USER_ID)})

    @app.route("/api/admin/model-tracker/pause", methods=["POST"])
    def api_model_tracker_pause():
        if not is_admin():
            return jsonify({"error": "Administrator access required."}), 403
        paused = bool((request.get_json(silent=True) or {}).get("paused"))
        return jsonify({"data": tracker.set_tracking_paused(paused)})

    @app.route("/api/admin/model-tracker/reconcile", methods=["POST"])
    def api_model_tracker_reconcile():
        if not has_job_authorization():
            return jsonify({"error": "Model Tracker job authorization required."}), 401
        force = bool((request.get_json(silent=True) or {}).get("force"))
        state = tracker.database.get_tracking_job_state()
        if state.get("paused") and not force:
            return jsonify({"data": {**state, "status": "paused"}})
        tracker.refresh()
        if state.get("paused") and force:
            result = tracker.reconcile_model_tracker(force=True)
        else:
            result = tracker.database.get_tracking_job_state()
        return jsonify({"data": result})

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
