from __future__ import annotations

import json
import logging
import os
import re
import secrets
import threading
import hashlib
import hmac
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import Flask, g, jsonify, redirect, render_template, request, url_for

from bet_tracker import replay_tracker
from clv import clv_period_analytics, clv_trend, safe_float as clv_float
from config import get_settings
from database import SettingsVersionConflict
from execution_providers import (
    ProviderHealthStatus,
    build_execution_provider_registry,
)
from personal_tracker import (
    PERSONAL_SPORTSBOOK_CHOICES,
    canonical_trade_identity,
    has_complete_identity,
    hidden_trade_snapshot,
    identity_key,
    normalize_personal_tags,
    normalize_sportsbook,
    personal_exposure_for_trade,
    personal_fill_snapshot,
    personal_tags_from_fill,
    replay_personal_tracker,
)
from personal_positions import (
    aggregate_personal_positions,
    executable_sell_quote,
    personal_realized_pnl_summary,
)
from position_tracker import MODEL_TRACKER_USER_ID, TrackerService
from risk_engine import bankroll_buckets, risk_state
from learning_system import (
    EDGE_MAP_VERSION,
    RULE_VIOLATION_VERSION,
    VIOLATION_WARNINGS,
    LearningConfig,
    build_edge_map,
    compare_holdout,
    config_dict,
    violation_analytics,
)
from measurement_foundation import stable_hash
from completion_system import explainability_trace
from sharp_tracking import (
    sharp_snapshot_from_fill,
    sharp_snapshot_from_model,
    tracker_identity,
)
from model_tracker_discord import build_discord_connection_test_payload
from trade_scoring import filter_trades_to_play
from whiteboard import (
    canonical_trade_identity as whiteboard_identity,
    dynamic_whiteboard_state,
    identity_key as whiteboard_identity_key,
    whiteboard_snapshot,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
LOGGER = logging.getLogger(__name__)
EASTERN = ZoneInfo("America/New_York")
USER_COOKIE = "iconbets_user"
AUTH_SESSION_COOKIE = "iconbets_session"
ADMIN_COOKIE = "iconbets_tracker_admin"
AUTH_SESSION_DAYS = 30
PASSWORD_ITERATIONS = 310_000
VALID_TRADE_DATE_RANGES = {"today", "next24", "next7", "custom"}

NO_LEAD_SHARP = "NO_LEAD_SHARP"


def _attach_clv(rows: list[dict], snapshots: list[dict], record_key: str) -> list[dict]:
    by_record = {str(item.get("tracker_record_id")): item for item in snapshots}
    for row in rows:
        record_id = str(row.get(record_key) or "")
        row["clv"] = by_record.get(record_id) or {
            "tracker_record_id": record_id,
            "entry_price": (row.get("snapshot") or {}).get("effective_entry_price")
            if record_key == "dedupe_key"
            else row.get("entry_price"),
            "entry_stake": row.get("recommended_amount")
            if record_key == "dedupe_key"
            else row.get("position_cost"),
            "clv_status": "pending",
            "clv_pct": None,
            "clv_cents": None,
        }
    return rows


def _attach_dual_clv(rows: list[dict], measurements: list[dict]) -> list[dict]:
    by_record = {str(item.get("tracker_record_id") or ""): item for item in measurements}
    for row in rows:
        snapshot = row.get("snapshot") or {}
        identifiers = (
            row.get("dedupe_key"),
            row.get("snapshot_id"),
            snapshot.get("candidate_id"),
            snapshot.get("snapshot_id"),
        )
        row["dual_clv"] = next(
            (by_record[str(value)] for value in identifiers if value and str(value) in by_record),
            {
                "exchange_clv_status": "PENDING",
                "composite_clv_status": "UNAVAILABLE",
                "composite_missing_reason": "NO_CONNECTED_INDEPENDENT_COMPOSITE_PROVIDER",
                "composite_closing_probability": None,
                "composite_probability_point_clv": None,
                "execution_loss": None,
            },
        )
    return rows


def _attach_historical_personal_sharps(
    fills: list[dict], model_records: list[dict]
) -> list[dict]:
    model_by_identity: dict[tuple[str, str, str, str], list[dict]] = {}
    for record in model_records:
        snapshot = record.get("snapshot") or {}
        identity = tracker_identity(snapshot)
        if all((identity[0], identity[1], identity[3])):
            model_by_identity.setdefault(identity, []).append(snapshot)

    enriched = []
    for fill in fills:
        item = dict(fill)
        current = sharp_snapshot_from_fill(item)
        if current.get("primary_sharp") or current.get("agreeing_sharps"):
            item["sharp_snapshot"] = current
            enriched.append(item)
            continue
        fill_time = _parse_datetime(item.get("created_at"))
        candidates = model_by_identity.get(tracker_identity(item), [])
        eligible = [
            snapshot
            for snapshot in candidates
            if fill_time is not None
            and (_parse_datetime(snapshot.get("recommendation_timestamp")) or fill_time)
            <= fill_time
        ]
        if eligible:
            selected = max(
                eligible,
                key=lambda snapshot: _parse_datetime(
                    snapshot.get("recommendation_timestamp")
                )
                or datetime.min.replace(tzinfo=timezone.utc),
            )
            backfilled = sharp_snapshot_from_model(selected)
            backfilled["sharp_source_status"] = "historical_signal_backfill"
            item["sharp_snapshot"] = backfilled
        enriched.append(item)
    return enriched


def _agreeing_sharp_values(snapshot: dict) -> list[str]:
    values: list[str] = []
    for wallet in snapshot.get("agreeing_sharps") or []:
        for value in (wallet.get("display_name"), wallet.get("wallet_address")):
            text = str(value or "").strip()
            if text and text.casefold() not in {item.casefold() for item in values}:
                values.append(text)
    return values


def _sharp_search_blob(snapshot: dict) -> str:
    return " ".join(_agreeing_sharp_values(snapshot)).casefold()


def _sharp_filter_matches(snapshot: dict, selected: str) -> bool:
    target = selected.strip().casefold()
    return not target or target in {
        value.casefold() for value in _agreeing_sharp_values(snapshot)
    }


def _sharp_filter_options(snapshots: list[dict]) -> list[str]:
    names = {
        str(wallet.get("display_name") or wallet.get("wallet_address") or "").strip()
        for snapshot in snapshots
        for wallet in snapshot.get("agreeing_sharps") or []
    }
    return sorted((name for name in names if name), key=str.casefold)


def _filter_sort_clv_rows(rows: list[dict]) -> list[dict]:
    status_filter = request.args.get("clv_status", "").strip().lower()
    minimum = clv_float(request.args.get("min_clv"))
    maximum = clv_float(request.args.get("max_clv"))
    if status_filter == "positive":
        rows = [row for row in rows if (clv_float(row["clv"].get("clv_pct")) or 0) > 0]
    elif status_filter == "negative":
        rows = [row for row in rows if (clv_float(row["clv"].get("clv_pct")) or 0) < 0]
    elif status_filter:
        rows = [row for row in rows if str(row["clv"].get("clv_status") or "").lower() == status_filter]
    if minimum is not None:
        rows = [row for row in rows if clv_float(row["clv"].get("clv_pct")) is not None and float(row["clv"]["clv_pct"]) >= minimum]
    if maximum is not None:
        rows = [row for row in rows if clv_float(row["clv"].get("clv_pct")) is not None and float(row["clv"]["clv_pct"]) <= maximum]
    sort = request.args.get("clv_sort", "").strip().lower()
    sorters = {
        "highest_pct": (lambda row: clv_float(row["clv"].get("clv_pct")) or -float("inf"), True),
        "lowest_pct": (lambda row: clv_float(row["clv"].get("clv_pct")) or float("inf"), False),
        "highest_cents": (lambda row: clv_float(row["clv"].get("clv_cents")) or -float("inf"), True),
        "closing_date": (lambda row: str(row["clv"].get("closing_snapshot_timestamp") or ""), True),
        "entry_price": (lambda row: clv_float(row["clv"].get("entry_price")) or float("inf"), False),
        "closing_price": (lambda row: clv_float(row["clv"].get("closing_effective_price")) or float("inf"), False),
    }
    if sort in sorters:
        key, reverse = sorters[sort]
        rows = sorted(rows, key=key, reverse=reverse)
    return rows


def _clv_analytics(rows: list[dict]) -> dict:
    values = [row["clv"] for row in rows]
    return {
        "periods": clv_period_analytics(values),
        "trend": clv_trend(values),
    }


def _personal_tracker_filter_options(fills: list[dict]) -> dict[str, list[str]]:
    used_sportsbooks = {
        normalize_sportsbook(fill.get("sportsbook")) for fill in fills
    }
    tags = {
        tag
        for fill in fills
        for tag in personal_tags_from_fill(fill)
    }
    sportsbook_choices = list(PERSONAL_SPORTSBOOK_CHOICES)
    known_choices = {choice.casefold() for choice in sportsbook_choices}
    sportsbook_choices.extend(
        sorted(
            (book for book in used_sportsbooks if book.casefold() not in known_choices),
            key=str.casefold,
        )
    )
    return {
        "sportsbooks": sorted(used_sportsbooks, key=str.casefold),
        "sportsbook_choices": sportsbook_choices,
        "tags": sorted(tags, key=str.casefold),
        "sharps": _sharp_filter_options(
            [sharp_snapshot_from_fill(fill) for fill in fills]
        ),
    }
UNRESOLVED_TRADE_CATEGORY = "UNRESOLVED_TRADE_CATEGORY"
MISSING_EXECUTABLE_PRICE = "MISSING_EXECUTABLE_PRICE"
ZERO_KELLY = "ZERO_KELLY"


def _normalize_email(value: object) -> str:
    return str(value or "").strip().lower()


def _valid_email(value: str) -> bool:
    return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value))


def _password_digest(password: str, salt: bytes, iterations: int) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    ).hex()


def _session_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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


def _entry_cents(value) -> float | None:
    parsed = _safe_float(value, -1.0)
    return parsed * 100.0 if 0 < parsed < 1 else None


def _parse_entry_cents(value: str | None, label: str) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = Decimal(value.strip())
    except InvalidOperation as exc:
        raise ValueError(f"{label} must be a number in cents.") from exc
    if not parsed.is_finite() or not Decimal("0") < parsed < Decimal("100"):
        raise ValueError(f"{label} must be greater than 0 and less than 100 cents.")
    if parsed != parsed.quantize(Decimal("0.1")):
        raise ValueError(f"{label} may use at most one decimal place.")
    return float(parsed)


def _entry_price_filters(args) -> tuple[float | None, float | None]:
    minimum = _parse_entry_cents(args.get("minEntryCents"), "Minimum share price")
    maximum = _parse_entry_cents(args.get("maxEntryCents"), "Maximum share price")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError("Minimum share price cannot exceed maximum share price.")
    return minimum, maximum


def _trade_feed_rejection_reason(trade: dict) -> str | None:
    recommendation = trade.get("recommendation") or {}
    if not trade.get("canonical_category_id"):
        return UNRESOLVED_TRADE_CATEGORY
    if not trade.get("tradeClassification") and int(
        trade.get("lead_sharp_count") or 0
    ) < 1:
        return NO_LEAD_SHARP
    if recommendation.get("passes_slippage_rule") is not True:
        return (
            recommendation.get("slippage_rejection_reason")
            or MISSING_EXECUTABLE_PRICE
        )
    if not _has_positive_recommendation(trade):
        return ZERO_KELLY
    return None


def _entry_price_matches(
    trade: dict, minimum_cents: float | None, maximum_cents: float | None
) -> bool:
    cents = trade.get("effectiveEntryCents")
    if cents is None:
        return False
    value = _safe_float(cents, -1.0)
    if minimum_cents is not None and value + 1e-9 < minimum_cents:
        return False
    if maximum_cents is not None and value - 1e-9 > maximum_cents:
        return False
    return True


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
    execution_providers = tracker.execution_providers

    app = Flask(__name__)
    app.extensions["tracker_service"] = tracker
    app.extensions["execution_providers"] = execution_providers
    app.extensions["tracker_starting"] = False
    app.config["SETTINGS"] = settings
    app.jinja_env.globals["asset_version"] = (
        os.getenv("VERCEL_GIT_COMMIT_SHA") or os.getenv("ASSET_VERSION") or "local"
    )

    @app.before_request
    def prepare_request():
        session_token = request.cookies.get(AUTH_SESSION_COOKIE)
        account = (
            tracker.database.get_auth_session(_session_token_hash(session_token))
            if session_token
            else None
        )
        user_id = account.get("user_id") if account else request.cookies.get(USER_COOKIE)
        g.iconbets_authenticated = bool(account)
        g.iconbets_account_email = account.get("email") if account else None
        g.iconbets_session_token = session_token if account else None
        g.iconbets_new_user = not bool(user_id)
        g.iconbets_user_id = user_id or secrets.token_urlsafe(24)

        if request.endpoint in {
            "api_model_tracker_reconcile",
            "api_prophetx_health",
            "api_fourcx_health",
        }:
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
            secure=request.is_secure or bool(os.getenv("VERCEL")),
            samesite="Lax",
            path="/",
        )

    def set_auth_cookie(response, token: str) -> None:
        response.set_cookie(
            AUTH_SESSION_COOKIE,
            token,
            max_age=60 * 60 * 24 * AUTH_SESSION_DAYS,
            httponly=True,
            secure=request.is_secure or bool(os.getenv("VERCEL")),
            samesite="Lax",
            path="/",
        )

    def create_account_session(user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(days=AUTH_SESSION_DAYS)
        ).isoformat()
        tracker.database.create_auth_session(
            user_id, _session_token_hash(token), expires_at
        )
        return token

    def present_user_settings(current: dict) -> dict:
        current = dict(current)
        current["sizing_bankroll_configured"] = bool(
            current.get("sizing_bankroll_configured")
        )
        current["account_authenticated"] = bool(g.iconbets_authenticated)
        current["account_email"] = g.iconbets_account_email
        return current

    def user_settings() -> dict:
        return present_user_settings(
            tracker.database.get_or_create_user_settings(
                g.iconbets_user_id,
                settings.default_bankroll,
                settings.unit_percentage,
            )
        )

    def public_trade(play: dict, bankroll: float) -> dict:
        evaluation = tracker.evaluate_recommendation(
            play,
            bankroll,
            user_id=g.iconbets_user_id,
            include_personal=True,
        )
        recommendation = evaluation["recommendation"]
        payload = json.loads(json.dumps(play))
        orderbook = payload.pop("orderbook", {}) or {}
        asks = orderbook.get("asks") or []
        bids = orderbook.get("bids") or []
        payload["orderbook_summary"] = {
            "best_ask": asks[0].get("price") if asks else None,
            "best_bid": bids[0].get("price") if bids else None,
            "ask_levels": len(asks),
            "bid_levels": len(bids),
            "min_order_size": orderbook.get("min_order_size"),
            "tick_size": orderbook.get("tick_size"),
            "timestamp": orderbook.get("timestamp"),
        }
        payload["orderbook"] = {
            "asks": [
                {"price": level.get("price"), "size": level.get("size")}
                for level in asks[:8]
            ],
            "bids": [
                {"price": level.get("price"), "size": level.get("size")}
                for level in bids[:8]
            ],
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
        payload["sharpReferenceEntryCents"] = _entry_cents(
            recommendation.get("sharp_reference_entry_price")
        )
        payload["currentTopAskCents"] = _entry_cents(
            recommendation.get("current_top_ask_price")
        )
        payload["effectiveEntryCents"] = _entry_cents(
            recommendation.get("effective_entry_price")
        )
        payload["slippageCents"] = recommendation.get("slippage_cents")
        payload["unfavorableSlippagePct"] = recommendation.get(
            "unfavorable_slippage_pct"
        )
        payload["passesSlippageRule"] = recommendation.get(
            "passes_slippage_rule"
        )
        payload["slippageRejectionReason"] = recommendation.get(
            "slippage_rejection_reason"
        )
        payload["card"] = _trade_card_view(payload, recommendation)
        payload["tradeFeedRejectionReason"] = _trade_feed_rejection_reason(payload)
        payload["tradeFeedEligible"] = payload["tradeFeedRejectionReason"] is None
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

    @app.route("/odds-screen")
    def odds_screen_page():
        return render_template("odds_screen.html", title="IconBets Live Odds Screen", page="odds-screen")

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

    @app.route("/tracker")
    def tracker_page():
        return render_template("tracker.html", title="IconBets Tracker", page="tracker")

    @app.route("/edge-map")
    def edge_map_page():
        return render_template("edge_map.html", title="IconBets Reece Edge Map", page="edge-map")

    @app.route("/intelligence")
    def intelligence_page():
        return render_template("intelligence.html", title="IconBets Intelligence", page="intelligence")

    @app.route("/model-tracker")
    def model_tracker_page():
        return redirect(url_for("tracker_page", view="model"), code=301)

    @app.route("/personal-tracking")
    def personal_tracking_page():
        return redirect(url_for("tracker_page", view="personal"), code=301)

    @app.route("/bet-tracker")
    def legacy_bet_tracker():
        return redirect(url_for("tracker_page", view="model"), code=301)

    @app.route("/personal-tracker")
    def legacy_personal_tracker():
        return redirect(url_for("tracker_page", view="personal"), code=301)

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

    @app.route("/api/provider-health/prophetx", methods=["GET", "POST"])
    def api_prophetx_health():
        if request.method == "POST" and not has_job_authorization():
            return jsonify({"status": ProviderHealthStatus.UNAUTHORIZED.value}), 401
        status = execution_providers.provider_health(
            "prophetx", authenticate=request.method == "POST"
        )
        return jsonify({"status": status.value})

    @app.route("/api/provider-health/4cx", methods=["GET", "POST"])
    def api_fourcx_health():
        if not has_job_authorization():
            return jsonify({"status": "UNAUTHORIZED"}), 401
        return jsonify(execution_providers.provider_diagnostics(
            "4cx", authenticate=request.method == "POST"
        ))

    @app.route("/api/admin/discord-notifications/test", methods=["POST"])
    def api_discord_notification_test():
        if not has_job_authorization():
            return jsonify({"status": "unauthorized"}), 401
        nonce = str((request.get_json(silent=True) or {}).get("nonce") or "")
        result = tracker.model_discord_bot.send(
            build_discord_connection_test_payload(nonce)
        )
        if result.delivered:
            return jsonify({"status": "authenticated", "delivered": True})
        return (
            jsonify(
                {
                    "status": tracker.model_discord_bot.safe_configuration()["status"],
                    "delivered": False,
                    "error": result.error_code or "connection_failed",
                }
            ),
            502,
        )

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

    @app.route("/api/odds-screen")
    def api_odds_screen():
        """Live read-only odds universe, independent of recommendation eligibility."""
        snapshot = tracker.get_snapshot()
        date_range = request.args.get("date_range", "today")
        if date_range not in {"today", "next24", "next7"}:
            return jsonify({"error": "Unsupported date range"}), 400
        now = datetime.now(timezone.utc)
        maximum = now + timedelta(days=7 if date_range == "next7" else 1)
        if date_range == "today":
            eastern_now = now.astimezone(EASTERN)
            maximum = eastern_now.replace(hour=23, minute=59, second=59).astimezone(timezone.utc)

        unique: dict[tuple, dict] = {}
        for source in snapshot.get("positions", []):
            if not source.get("is_sports") or source.get("market_closed") or source.get("event_closed"):
                continue
            starts_at = _parse_datetime(source.get("resolution_time"))
            if starts_at and (starts_at < now - timedelta(hours=6) or starts_at > maximum):
                continue
            key = (
                str(source.get("condition_id") or source.get("market_id") or source.get("event_id") or ""),
                str(source.get("outcome") or "").lower(),
                str(source.get("sports_market_type") or "").lower(),
                source.get("market_line"),
            )
            if not key[0] or not key[1]:
                continue
            row = dict(source)
            row["id"] = "odds::" + stable_hash(key)[:24]
            row["event_date_et"] = source.get("resolution_time")
            executable = source.get("executable_ask_price")
            current = executable if executable is not None else source.get("current_price")
            row["card"] = {"current_actionable_price": current, "recommended_amount": 0}
            row["recommendation"] = {"current_user_entry_price": current, "recommended_amount": 0}
            row.pop("orderbook", None)
            unique[key] = row

        rows = sorted(
            unique.values(),
            key=lambda row: str(row.get("resolution_time") or "~"),
        )[:250]
        execution_providers.attach_options(rows)
        return jsonify(
            {
                "data": rows,
                "pagination": {"total": len(rows), "page": 1, "per_page": 250},
                "status": snapshot["status"],
                "source": "active_sports_positions",
            }
        )

    @app.route("/api/trades-to-play")
    def api_trades_to_play():
        snapshot = tracker.get_snapshot()
        date_range = request.args.get("date_range", "today")
        if date_range not in VALID_TRADE_DATE_RANGES:
            return jsonify({"error": "Unsupported date range"}), 400
        try:
            minimum_cents, maximum_cents = _entry_price_filters(request.args)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
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
        active_pins = tracker.database.get_whiteboard_pins(g.iconbets_user_id)
        pinned_keys = {
            whiteboard_identity_key(pin): pin["id"] for pin in active_pins
        }
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
            classification=request.args.get("classification", ""),
        )
        sized = [
            decorate_personal_state(
                public_trade(play, bankroll), active_personal_fills, hidden_by_key
            )
            for play in filtered
        ]
        for trade in sized:
            pin_id = pinned_keys.get(
                whiteboard_identity_key(whiteboard_identity(trade))
            )
            trade["isPinnedByCurrentUser"] = pin_id is not None
            trade["whiteboardPinId"] = pin_id
        actionable = [trade for trade in sized if trade["tradeFeedEligible"]]
        price_matched = [
            trade
            for trade in actionable
            if _entry_price_matches(trade, minimum_cents, maximum_cents)
        ]
        visible = (
            price_matched
            if show_hidden
            else [trade for trade in price_matched if not trade["isHidden"]]
        )
        start = (page - 1) * per_page
        page_trades = visible[start : start + per_page]
        execution_providers.attach_options(page_trades)
        return jsonify(
            {
                "data": page_trades,
                "bankroll": current_settings,
                "hiddenCount": len(hidden_records),
                "whiteboardCount": len(active_pins),
                "showHidden": show_hidden,
                "entryPriceFilters": {
                    "minEntryCents": minimum_cents,
                    "maxEntryCents": maximum_cents,
                },
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

    @app.route("/api/whiteboard", methods=["GET", "POST"])
    def api_whiteboard():
        snapshot = tracker.get_snapshot()
        current_settings = user_settings()
        bankroll = _safe_float(current_settings["starting_bankroll"])
        current_trades = [
            public_trade(play, bankroll)
            for play in snapshot.get("trades_to_play", [])
        ]
        execution_providers.attach_options(current_trades)
        current_by_key = {
            whiteboard_identity_key(whiteboard_identity(trade)): trade
            for trade in current_trades
        }
        if request.method == "POST":
            payload = request.get_json(silent=True) or {}
            trade_id = str(payload.get("trade_id") or "")
            trade = next(
                (item for item in current_trades if str(item.get("id")) == trade_id),
                None,
            )
            if trade is None:
                return jsonify({"error": "Trade is no longer available to pin"}), 409
            frozen = whiteboard_snapshot(trade)
            record = tracker.database.pin_whiteboard_trade(
                g.iconbets_user_id,
                {
                    **whiteboard_identity(trade),
                    "market_type": trade.get("sports_market_type"),
                    "period": trade.get("period") or "game",
                    "snapshot": frozen,
                },
            )
            return jsonify({"data": {key: value for key, value in record.items() if key != "user_id"}}), 201

        records = tracker.database.get_whiteboard_pins(g.iconbets_user_id)
        rows = []
        now = datetime.now(timezone.utc)
        for record in records:
            frozen = record["snapshot"]
            key = whiteboard_identity_key(record)
            current = current_by_key.get(key)
            dynamic = dynamic_whiteboard_state(frozen, current)
            status = str(dynamic.get("official_event_status") or "").lower()
            event_start = _parse_datetime(dynamic.get("official_event_start_time"))
            archive_reason = None
            if "cancel" in status:
                archive_reason = "EVENT_CANCELED"
            elif "void" in status:
                archive_reason = "MARKET_VOIDED"
            elif status in {"settled", "resolved", "closed"}:
                archive_reason = "MARKET_SETTLED"
            elif event_start and event_start <= now and status != "postponed":
                archive_reason = "EVENT_STARTED"
            if archive_reason:
                tracker.database.archive_whiteboard_pin(
                    g.iconbets_user_id, record["id"], archive_reason
                )
                continue
            row = {
                key: value
                for key, value in record.items()
                if key not in {"user_id", "snapshot"}
            }
            rows.append(
                {
                    **row,
                    "snapshot": frozen,
                    "dynamic": dynamic,
                    "currentTrade": current,
                }
            )
        query = request.args.get("q", "").strip().lower()
        if query:
            rows = [
                row
                for row in rows
                if query
                in " ".join(
                    str(row["snapshot"].get(key) or "").lower()
                    for key in ("event_title", "market_title", "selection", "sport", "league")
                )
            ]
        sort = request.args.get("sort", "event")
        if sort == "pinned":
            rows.sort(key=lambda row: str(row.get("pinned_at") or ""), reverse=True)
        elif sort == "score":
            rows.sort(key=lambda row: -_safe_float(row["snapshot"].get("confidence_score")))
        elif sort == "slippage":
            rows.sort(key=lambda row: _safe_float(row["dynamic"].get("current_unfavorable_slippage_pct"), 9999))
        elif sort == "amount":
            rows.sort(key=lambda row: -_safe_float(row["snapshot"].get("recommended_dollar_amount")))
        elif sort == "classification":
            rows.sort(key=lambda row: str(row["snapshot"].get("trade_classification") or ""))
        else:
            rows.sort(key=lambda row: str(row["dynamic"].get("official_event_start_time") or "9999"))
        return jsonify({"data": rows, "total": len(rows)})

    @app.route("/api/whiteboard/<int:pin_id>", methods=["DELETE"])
    def api_unpin_whiteboard(pin_id: int):
        if not tracker.database.archive_whiteboard_pin(
            g.iconbets_user_id, pin_id, "USER_UNPINNED"
        ):
            return jsonify({"error": "Pin not found"}), 404
        return jsonify({"archived": True, "archiveReason": "USER_UNPINNED"})

    @app.route("/api/admin/trade-eligibility-diagnostics")
    def api_trade_eligibility_diagnostics():
        if not is_admin():
            return jsonify({"error": "Admin access required"}), 403
        snapshot = tracker.get_snapshot()
        evaluated = [
            public_trade(play, settings.default_bankroll)
            for play in snapshot.get("trades_to_play", [])
        ]
        sized_rejections = [
            {
                "reason": trade.get("tradeFeedRejectionReason"),
                "event_id": (trade.get("validation_ids") or {}).get("event_id"),
                "condition_id": (trade.get("validation_ids") or {}).get(
                    "condition_id"
                ),
                "outcome_id": (trade.get("validation_ids") or {}).get(
                    "outcome_token_id"
                ),
                "event_title": trade.get("event_title"),
                "market_title": trade.get("market_title"),
                "outcome": trade.get("outcome"),
                "canonical_category_id": trade.get("canonical_category_id"),
                "unfavorableSlippagePct": trade.get(
                    "unfavorableSlippagePct"
                ),
                "tradeClassification": trade.get("tradeClassification"),
                "rawAgreeingSharpCount": trade.get("rawAgreeingSharpCount"),
                "rawContradictingSharpCount": trade.get("rawContradictingSharpCount"),
                "weightedAgreeingConsensus": trade.get("weightedAgreeingConsensus"),
                "weightedContradictingConsensus": trade.get("weightedContradictingConsensus"),
                "netSharpMajority": trade.get("netSharpMajority"),
                "majorityRatio": trade.get("majorityRatio"),
                "confidenceScoreCap": trade.get("confidenceScoreCap"),
                "probabilityAdjustmentCap": trade.get("probabilityAdjustmentCap"),
                "riskCap": trade.get("riskCap"),
            }
            for trade in evaluated
            if not trade.get("tradeFeedEligible")
        ]
        exclusions = list(snapshot.get("trade_exclusions", [])) + sized_rejections
        return jsonify({"data": exclusions, "total": len(exclusions)})

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
        try:
            sportsbook = normalize_sportsbook(payload.get("sportsbook"))
            tags = normalize_personal_tags(payload.get("tags"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        fill = personal_fill_snapshot(
            public,
            fill_id=secrets.token_urlsafe(18),
            entry_price=entry_price,
            shares=shares,
            fees=fees,
            sportsbook=sportsbook,
            tags=tags,
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

    @app.route("/api/personal-bets/manual", methods=["POST"])
    def api_manual_personal_bet():
        payload = request.get_json(silent=True) or {}
        event_title = " ".join(str(payload.get("event_title") or "").split())
        market_title = " ".join(
            str(payload.get("market_title") or event_title).split()
        )
        selection = " ".join(str(payload.get("selection") or "").split())
        if not event_title or not selection:
            return jsonify({"error": "Event and selection are required."}), 400
        if max(len(event_title), len(market_title), len(selection)) > 200:
            return jsonify({"error": "Event, market, and selection must be 200 characters or fewer."}), 400

        entry_price = _safe_float(payload.get("entry_price"), -1)
        stake = _safe_float(payload.get("stake"), -1)
        fees = _safe_float(payload.get("fees"), 0)
        if not 0 < entry_price < 1:
            return jsonify({"error": "Entry price must be between 0 and 1."}), 400
        if stake <= 0:
            return jsonify({"error": "Stake must be greater than zero."}), 400
        if fees < 0:
            return jsonify({"error": "Fees cannot be negative."}), 400

        market_url = str(payload.get("market_url") or "").strip()
        if market_url and not re.fullmatch(r"https://[^\s]+", market_url):
            return jsonify({"error": "Market URL must be a valid HTTPS URL."}), 400
        try:
            sportsbook = normalize_sportsbook(payload.get("sportsbook"))
            tags = normalize_personal_tags(payload.get("tags"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if not any(tag.casefold() == "manual entry" for tag in tags):
            tags.append("Manual Entry")

        identity_seed = stable_hash(event_title, market_title, selection, market_url)
        event_id = str(payload.get("canonical_event_id") or "").strip()
        market_id = str(payload.get("canonical_market_id") or "").strip()
        outcome_id = str(payload.get("canonical_outcome_id") or "").strip()
        event_id = event_id or f"manual-event-{identity_seed[:24]}"
        market_id = market_id or f"manual-market-{identity_seed[:24]}"
        outcome_id = outcome_id or f"manual-outcome-{identity_seed[:24]}"
        event_slug = str(payload.get("event_slug") or "").strip() or None
        market_slug = str(payload.get("market_slug") or "").strip() or None
        event_start_time = str(payload.get("event_start_time") or "").strip() or None
        status = str(payload.get("status") or "scheduled").strip().lower()
        if status not in {"scheduled", "live", "unresolved"}:
            return jsonify({"error": "Status must be scheduled, live, or unresolved."}), 400

        trade = {
            "event_title": event_title,
            "market_title": market_title,
            "outcome": selection,
            "event_slug": event_slug,
            "event_date_et": event_start_time,
            "market_url": market_url or None,
            "entry_source": "manual",
            "sharp_source_status": "manual_entry",
            "validation_ids": {
                "event_id": event_id,
                "event_slug": event_slug,
                "condition_id": market_id,
                "market_slug": market_slug,
                "outcome_token_id": outcome_id,
            },
        }
        identity = canonical_trade_identity(trade)
        if not has_complete_identity(identity):
            return jsonify({"error": "Manual bet is missing a canonical identity."}), 409

        active_fills = tracker.database.get_personal_bet_fills(
            g.iconbets_user_id, active_only=True
        )
        exposure = personal_exposure_for_trade(trade, active_fills)
        if exposure["hasOpposingPersonalPosition"] and not bool(
            payload.get("confirm_conflict")
        ):
            return jsonify({
                "error": "You already hold the opposing outcome in this market.",
                "confirmationRequired": "conflict",
                "personalExposureSummary": exposure,
            }), 409
        if exposure["hasExactPersonalPosition"] and not bool(
            payload.get("confirm_duplicate")
        ):
            return jsonify({
                "error": "You already have a personal position on this exact selection.",
                "confirmationRequired": "duplicate",
                "personalExposureSummary": exposure,
            }), 409

        fill = personal_fill_snapshot(
            trade,
            fill_id=secrets.token_urlsafe(18),
            entry_price=entry_price,
            shares=stake / entry_price,
            fees=fees,
            sportsbook=sportsbook,
            tags=tags,
        )
        stored = tracker.database.insert_personal_bet_fill(
            g.iconbets_user_id, fill, status=status
        )
        public_fill = {key: value for key, value in stored.items() if key != "user_id"}
        return jsonify({"data": public_fill, "source": "manual_entry"}), 201

    @app.route("/api/personal-bets/<fill_id>", methods=["DELETE"])
    def api_delete_personal_bet(fill_id: str):
        if not tracker.database.cancel_personal_bet_fill(g.iconbets_user_id, fill_id):
            return jsonify({"error": "Personal fill was not found."}), 404
        return jsonify({"canceled": True})

    @app.route("/api/personal-tracker/options")
    def api_personal_tracker_options():
        fills = tracker.database.get_personal_bet_fills(g.iconbets_user_id)
        return jsonify({"data": _personal_tracker_filter_options(fills)})

    def personal_position_snapshot(*, include_quotes: bool = True) -> list[dict]:
        fills = tracker.database.get_personal_bet_fills(g.iconbets_user_id)
        exits = tracker.database.get_personal_position_exits(g.iconbets_user_id)
        preliminary = aggregate_personal_positions(fills, exits)
        polymarket_open = [
            item
            for item in preliminary
            if not item["isClosed"]
            and item["provider"].lower() == "polymarket"
            and item["canonicalOutcomeId"]
        ]
        quotes = {}
        if include_quotes and polymarket_open:
            try:
                books = tracker.client.get_order_books(
                    [item["canonicalOutcomeId"] for item in polymarket_open]
                )
            except Exception as exc:
                LOGGER.warning("Personal position quotes unavailable: %s", exc)
                books = {}
            for item in polymarket_open:
                book = books.get(item["canonicalOutcomeId"]) or {}
                quotes[item["canonicalOutcomeId"]] = executable_sell_quote(
                    book.get("bids") or [],
                    item["remainingShares"],
                    timestamp=book.get("timestamp"),
                )
        return aggregate_personal_positions(fills, exits, quotes)

    @app.route("/api/personal-positions")
    def api_personal_positions():
        state = request.args.get("state", "open").lower()
        if state not in {"open", "closed", "all"}:
            state = "open"
        positions = personal_position_snapshot(include_quotes=state != "closed")
        closure = request.args.get("closure", "all").lower()
        query = request.args.get("q", "").strip().lower()
        visible = positions
        if state == "open":
            visible = [item for item in visible if not item["isClosed"]]
        elif state == "closed":
            visible = [item for item in visible if item["isClosed"]]
        if closure in {"sold", "resolved"}:
            visible = [item for item in visible if item["closureMethod"] == closure]
        if query:
            visible = [
                item
                for item in visible
                if query
                in " ".join(
                    str(item.get(key) or "").lower()
                    for key in ("eventTitle", "marketTitle", "selection", "provider")
                )
            ]
        page = max(request.args.get("page", 1, type=int) or 1, 1)
        per_page = min(max(request.args.get("per_page", 50, type=int) or 50, 1), 100)
        start = (page - 1) * per_page
        return jsonify(
            {
                "data": visible[start : start + per_page],
                "counts": {
                    "positions": sum(not item["isClosed"] for item in positions),
                    "closed": sum(item["isClosed"] for item in positions),
                },
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total": len(visible),
                    "has_next": start + per_page < len(visible),
                },
            }
        )

    @app.route("/api/personal-positions/<position_id>/exits", methods=["POST"])
    def api_record_personal_exit(position_id: str):
        payload = request.get_json(silent=True) or {}
        position = next(
            (
                item
                for item in personal_position_snapshot(include_quotes=False)
                if item["positionId"] == position_id and not item["isClosed"]
            ),
            None,
        )
        if position is None:
            return jsonify({"error": "Open personal position was not found."}), 404
        shares = _safe_float(payload.get("shares"), -1)
        price = _safe_float(payload.get("sell_price"), -1)
        fees = _safe_float(payload.get("fees"), 0)
        if shares <= 0 or shares > position["remainingShares"] + 1e-9:
            return jsonify({"error": "Shares must not exceed the open balance."}), 400
        if not 0 < price <= 1:
            return jsonify({"error": "Sell price must be between 0 and 1."}), 400
        if fees < 0:
            return jsonify({"error": "Fees cannot be negative."}), 400
        idempotency_key = str(payload.get("idempotency_key") or "").strip()
        if not idempotency_key or len(idempotency_key) > 128:
            return jsonify({"error": "A valid idempotency key is required."}), 400
        sold_at = datetime.now(timezone.utc).isoformat()
        gross = shares * price
        record = {
            "exit_id": secrets.token_urlsafe(18),
            "idempotency_key": idempotency_key,
            "canonical_event_id": position["canonicalEventId"],
            "canonical_market_id": position["canonicalMarketId"],
            "market_line": position["marketLine"],
            "canonical_outcome_id": position["canonicalOutcomeId"],
            "sportsbook": position["provider"],
            "shares_sold": shares,
            "sell_price": price,
            "gross_proceeds": gross,
            "fees": fees,
            "net_proceeds": gross - fees,
            "sold_at": sold_at,
            "mode": "tracker_only",
        }
        try:
            stored = tracker.database.insert_personal_position_exit(
                g.iconbets_user_id, record
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify({"data": stored, "executionMode": "tracker_only"}), 201

    @app.route("/api/personal-positions/<position_id>/price-history")
    def api_personal_position_price_history(position_id: str):
        position = next(
            (
                item
                for item in personal_position_snapshot(include_quotes=False)
                if item["positionId"] == position_id
            ),
            None,
        )
        if position is None:
            return jsonify({"error": "Personal position was not found."}), 404
        if position["provider"].lower() != "polymarket":
            return jsonify({"error": "Price history is unavailable for this provider."}), 409
        interval = request.args.get("interval", "1d")
        if interval not in {"1d", "1w", "1m", "max"}:
            interval = "1d"
        try:
            history = tracker.client.get_price_history(
                position["canonicalOutcomeId"], interval=interval, fidelity=15
            )
        except Exception as exc:
            LOGGER.warning("Personal position price history unavailable: %s", exc)
            return jsonify({"error": "Price history is temporarily unavailable."}), 502
        return jsonify({"data": history, "source": "Polymarket CLOB"})

    @app.route("/api/personal-pnl")
    def api_personal_pnl():
        positions = personal_position_snapshot(include_quotes=False)
        return jsonify(
            {
                "data": personal_realized_pnl_summary(
                    positions, request.args.get("period", "week")
                )
            }
        )

    @app.route("/api/personal-tracker")
    def api_personal_tracker():
        current_settings = user_settings()
        all_fills = tracker.database.get_personal_bet_fills(g.iconbets_user_id)
        all_fills = _attach_historical_personal_sharps(
            all_fills,
            tracker.database.get_tracker_records(MODEL_TRACKER_USER_ID),
        )
        filter_options = _personal_tracker_filter_options(all_fills)
        query = request.args.get("q", "").strip().lower()
        status_filter = request.args.get("status", "").strip().lower()
        result_filter = request.args.get("result", "").strip().lower()
        sportsbook_filter = request.args.get("sportsbook", "").strip().lower()
        tag_filter = request.args.get("tag", "").strip().lower()
        sharp_filter = request.args.get("sharp", "").strip()
        fills = all_fills
        if query:
            fills = [
                fill
                for fill in fills
                if query
                in " ".join(
                    [
                        *(
                            str(fill.get(field) or "").lower()
                            for field in (
                                "event_title",
                                "market_title",
                                "selection",
                                "sportsbook",
                            )
                        ),
                        *(tag.lower() for tag in personal_tags_from_fill(fill)),
                        _sharp_search_blob(sharp_snapshot_from_fill(fill)),
                    ]
                )
            ]
        if status_filter:
            fills = [
                fill
                for fill in fills
                if str(fill.get("status") or "").lower() == status_filter
            ]
        if result_filter:
            fills = [
                fill
                for fill in fills
                if str(fill.get("result") or "").lower() == result_filter
            ]
        if sportsbook_filter:
            fills = [
                fill
                for fill in fills
                if normalize_sportsbook(fill.get("sportsbook")).lower()
                == sportsbook_filter
            ]
        if tag_filter:
            fills = [
                fill
                for fill in fills
                if tag_filter
                in {tag.lower() for tag in personal_tags_from_fill(fill)}
            ]
        if sharp_filter:
            fills = [
                fill
                for fill in fills
                if _sharp_filter_matches(
                    sharp_snapshot_from_fill(fill), sharp_filter
                )
            ]

        replay = replay_personal_tracker(
            fills,
            _safe_float(current_settings["personal_tracker_bankroll"]),
        )
        all_exits = tracker.database.get_personal_position_exits(g.iconbets_user_id)
        fill_keys = {
            (
                str(fill.get("canonical_event_id") or "").lower(),
                str(fill.get("canonical_market_id") or "").lower(),
                str(fill.get("market_line") or "").lower(),
                str(fill.get("canonical_outcome_id") or "").lower(),
                normalize_sportsbook(fill.get("sportsbook")).lower(),
            )
            for fill in fills
        }
        exits = [
            item
            for item in all_exits
            if (
                str(item.get("canonical_event_id") or "").lower(),
                str(item.get("canonical_market_id") or "").lower(),
                str(item.get("market_line") or "").lower(),
                str(item.get("canonical_outcome_id") or "").lower(),
                normalize_sportsbook(item.get("sportsbook")).lower(),
            )
            in fill_keys
        ]
        if exits:
            positions = aggregate_personal_positions(fills, exits)
            realized = sum(float(item.get("realizedPnl") or 0) for item in positions)
            starting = _safe_float(current_settings["personal_tracker_bankroll"])
            closed = [item for item in positions if item["isClosed"]]
            replay["summary"].update(
                {
                    "current_bankroll": starting + realized,
                    "realized_profit_loss": realized,
                    "roi": realized / starting if starting > 0 else 0,
                    "open_exposure": sum(
                        float(item.get("remainingCostBasis") or 0)
                        for item in positions
                        if not item["isClosed"]
                    ),
                    "settled_wagered": sum(
                        float(item.get("totalPaid") or 0) for item in closed
                    ),
                }
            )
            realized_graph = personal_realized_pnl_summary(positions, "all")["graph"]
            replay["graph"] = [
                {"timestamp": None, "profit_loss": 0, "bankroll": starting},
                *(
                    {
                        "timestamp": point["timestamp"],
                        "profit_loss": point["profitLoss"],
                        "bankroll": starting + point["profitLoss"],
                    }
                    for point in realized_graph
                ),
            ]
        rows = replay["rows"]
        rows = _attach_clv(
            rows,
            tracker.database.get_closing_lines("personal", g.iconbets_user_id),
            "fill_id",
        )
        rows = _filter_sort_clv_rows(rows)
        clv_analytics = _clv_analytics(rows)

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
                "clv": clv_analytics,
                "bankroll": current_settings,
                "filter_options": filter_options,
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

    @app.route("/api/auth/session")
    def api_auth_session():
        return jsonify(
            {
                "authenticated": bool(g.iconbets_authenticated),
                "email": g.iconbets_account_email,
            }
        )

    @app.route("/api/auth/register", methods=["POST"])
    def api_auth_register():
        payload = request.get_json(silent=True) or {}
        email = _normalize_email(payload.get("email"))
        password = str(payload.get("password") or "")
        if not _valid_email(email):
            return jsonify({"error": "Enter a valid email address."}), 400
        if len(password) < 8:
            return jsonify({"error": "Password must be at least 8 characters."}), 400
        salt = secrets.token_bytes(16)
        try:
            tracker.database.create_account(
                g.iconbets_user_id,
                email,
                salt.hex(),
                _password_digest(password, salt, PASSWORD_ITERATIONS),
                PASSWORD_ITERATIONS,
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 409
        user_settings()
        token = create_account_session(g.iconbets_user_id)
        response = jsonify({"authenticated": True, "email": email})
        g.iconbets_new_user = False
        set_auth_cookie(response, token)
        response.delete_cookie(USER_COOKIE, path="/")
        return response, 201

    @app.route("/api/auth/login", methods=["POST"])
    def api_auth_login():
        payload = request.get_json(silent=True) or {}
        email = _normalize_email(payload.get("email"))
        password = str(payload.get("password") or "")
        account = tracker.database.get_account_by_email(email)
        if account is None:
            return jsonify({"error": "Email or password is incorrect."}), 401
        try:
            salt = bytes.fromhex(str(account["password_salt"]))
            iterations = int(account["password_iterations"])
        except (KeyError, TypeError, ValueError):
            return jsonify({"error": "Email or password is incorrect."}), 401
        supplied = _password_digest(password, salt, iterations)
        if not hmac.compare_digest(supplied, str(account["password_hash"])):
            return jsonify({"error": "Email or password is incorrect."}), 401
        token = create_account_session(str(account["user_id"]))
        response = jsonify({"authenticated": True, "email": account["email"]})
        g.iconbets_new_user = False
        set_auth_cookie(response, token)
        response.delete_cookie(USER_COOKIE, path="/")
        return response

    @app.route("/api/auth/logout", methods=["POST"])
    def api_auth_logout():
        session_token = request.cookies.get(AUTH_SESSION_COOKIE)
        if session_token:
            tracker.database.delete_auth_session(_session_token_hash(session_token))
        anonymous_user_id = secrets.token_urlsafe(24)
        response = jsonify({"authenticated": False})
        response.delete_cookie(AUTH_SESSION_COOKIE, path="/")
        set_user_cookie(response, anonymous_user_id)
        return response

    @app.route("/api/user-settings", methods=["GET", "PUT"])
    def api_user_settings():
        current = user_settings()
        if request.method == "PUT":
            payload = request.get_json(silent=True) or {}
            bankroll = _safe_float(
                payload.get("trades_to_play_bankroll", payload.get("starting_bankroll")),
                -1,
            )
            if bankroll <= 0:
                return jsonify(
                    {"error": "Starting bankroll must be greater than zero."}
                ), 400
            expected_version = payload.get("expected_version")
            if expected_version is not None:
                try:
                    expected_version = int(expected_version)
                except (TypeError, ValueError):
                    return jsonify({"error": "Settings version must be an integer."}), 400
            try:
                current = tracker.database.update_user_settings(
                    g.iconbets_user_id,
                    bankroll,
                    settings.unit_percentage,
                    expected_version,
                )
                tracker.database.update_risk_account_state(
                    g.iconbets_user_id,
                    bankroll,
                    {"current_bankroll": bankroll, "high_water_mark": bankroll},
                )
            except SettingsVersionConflict as exc:
                latest = present_user_settings(exc.current)
                latest["unit_value"] = _safe_float(
                    latest["trades_to_play_bankroll"]
                ) * _safe_float(latest["unit_percentage"])
                return jsonify(
                    {
                        "error": "Bankroll changed in another session. Reloaded the latest saved value.",
                        "data": latest,
                    }
                ), 409
        current = present_user_settings(current)
        current["unit_value"] = _safe_float(
            current["trades_to_play_bankroll"]
        ) * _safe_float(current["unit_percentage"])
        return jsonify({"data": current})

    @app.route("/api/tracker-preference", methods=["PUT"])
    def api_tracker_preference():
        payload = request.get_json(silent=True) or {}
        tracker_view = str(payload.get("view") or "").strip().lower()
        if tracker_view not in {"model", "personal"}:
            return jsonify({"error": "Tracker view must be model or personal."}), 400
        user_settings()
        return jsonify(
            {
                "data": tracker.database.update_tracker_view(
                    g.iconbets_user_id, tracker_view
                )
            }
        )

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

    @app.route("/api/personal-tracker/settings", methods=["GET", "PUT"])
    def api_personal_tracker_settings():
        current = user_settings()
        if request.method == "PUT":
            payload = request.get_json(silent=True) or {}
            bankroll = _safe_float(payload.get("personal_tracker_bankroll"), -1)
            if bankroll <= 0:
                return jsonify(
                    {"error": "Personal Tracker starting bankroll must be greater than zero."}
                ), 400
            current = tracker.database.update_personal_tracker_bankroll(
                g.iconbets_user_id, bankroll
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
        for row in rows:
            row["sharp_snapshot"] = sharp_snapshot_from_model(row.get("snapshot") or {})
        sharp_options = _sharp_filter_options(
            [row["sharp_snapshot"] for row in rows]
        )
        query = request.args.get("q", "").strip().lower()
        status_filter = request.args.get("status", "").strip().lower()
        sport = request.args.get("sport", "").strip().lower()
        league = request.args.get("league", "").strip().lower()
        result = request.args.get("result", "").strip().lower()
        min_sharps = max(request.args.get("min_sharps", 0, type=int) or 0, 0)
        sharp_filter = request.args.get("sharp", "").strip()
        grade_filter = request.args.get("grade", "").strip().upper()
        liquidity_filter = request.args.get("liquidity_grade", "").strip().upper()
        execution_filter = request.args.get("execution_method", "").strip().upper()
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
                ) + " " + _sharp_search_blob(row.get("sharp_snapshot") or {})
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
        if sharp_filter:
            rows = [
                row
                for row in rows
                if _sharp_filter_matches(
                    row.get("sharp_snapshot") or {}, sharp_filter
                )
            ]
        if grade_filter:
            rows = [row for row in rows if str((row.get("snapshot") or {}).get("trade_grade") or "UNAVAILABLE").upper() == grade_filter]
        if liquidity_filter:
            rows = [row for row in rows if str((row.get("snapshot") or {}).get("liquidity_grade") or "UNAVAILABLE").upper() == liquidity_filter]
        if execution_filter:
            rows = [row for row in rows if str((row.get("snapshot") or {}).get("execution_method") or "UNAVAILABLE").upper() == execution_filter]
        rows = _attach_clv(
            rows,
            tracker.database.get_closing_lines("model", MODEL_TRACKER_USER_ID),
            "dedupe_key",
        )
        rows = _attach_dual_clv(
            rows,
            tracker.database.get_dual_clv_measurements("model", MODEL_TRACKER_USER_ID),
        )
        rows = _filter_sort_clv_rows(rows)
        clv_analytics = _clv_analytics(rows)

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
                "clv": clv_analytics,
                "bankroll": current_settings,
                "tracking": {
                    key: value
                    for key, value in tracker.tracking_diagnostics(
                        MODEL_TRACKER_USER_ID
                    ).items()
                    if key != "rejections"
                },
                "filter_options": {"sharps": sharp_options},
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

    @app.route("/api/admin/measurement-foundation/diagnostics")
    def api_measurement_foundation_diagnostics():
        if not is_admin():
            return jsonify({"error": "Administrator access required."}), 403
        return jsonify(
            {
                "data": {
                    **tracker.database.measurement_diagnostics(),
                    "composite_price_providers": tracker.composite_price_providers.health(),
                    "release": "release-1-measurement-foundation",
                    "live_decision_logic_changed": False,
                    "fabricated_provider_data": False,
                }
            }
        )

    @app.route("/api/admin/candidate-ledger")
    def api_candidate_ledger():
        if not is_admin():
            return jsonify({"error": "Administrator access required."}), 403
        decision = request.args.get("decision", "").strip().upper() or None
        limit = max(1, min(request.args.get("limit", 100, type=int) or 100, 500))
        offset = max(request.args.get("offset", 0, type=int) or 0, 0)
        rows = tracker.database.list_candidates(decision, limit, offset)
        return jsonify({"data": rows, "count": len(rows), "limit": limit, "offset": offset})

    @app.route("/api/admin/decision-engine/diagnostics")
    def api_decision_engine_diagnostics():
        if not is_admin():
            return jsonify({"error": "Administrator access required."}), 403
        return jsonify(
            {
                "data": {
                    **tracker.database.decision_engine_diagnostics(),
                    "release": "release-2-decision-engine",
                    "provider_health": tracker.composite_price_providers.health(),
                    "connected_provider_health": tracker.execution_providers.fair_price_provider_health(),
                    "fair_price_weights": tracker.fair_price_engine.provider_weights,
                    "max_quote_age_seconds": tracker.fair_price_engine.max_quote_age_seconds,
                    "automatic_model_tracker_requires_independent_fair_price": True,
                    "fabricated_provider_data": False,
                }
            }
        )

    @app.route("/api/risk/bankroll-buckets", methods=["GET", "PUT"])
    def api_bankroll_buckets():
        if request.method == "PUT":
            payload = request.get_json(silent=True) or {}
            try:
                config_row = tracker.database.update_bankroll_bucket_config(
                    g.iconbets_user_id, payload
                )
            except (KeyError, TypeError, ValueError) as exc:
                return jsonify({"error": str(exc)}), 400
        else:
            config_row = tracker.database.get_bankroll_bucket_config(g.iconbets_user_id)
        current = user_settings()
        bankroll = _safe_float(current["trades_to_play_bankroll"])
        context = tracker.build_risk_context(
            bankroll, user_id=g.iconbets_user_id, include_personal=True
        )
        return jsonify(
            {
                "data": {
                    "config": config_row,
                    "state": risk_state(
                        context["account_state"]["current_bankroll"],
                        context["account_state"]["high_water_mark"],
                        manual_kill_switch=bool(context["account_state"].get("manual_kill_switch")),
                        manual_reason=context["account_state"].get("manual_reason"),
                    ),
                    "allocation": bankroll_buckets(
                        bankroll, context["exposures"], context["config"]
                    ),
                }
            }
        )

    @app.route("/api/admin/execution-risk/diagnostics")
    def api_execution_risk_diagnostics():
        if not is_admin():
            return jsonify({"error": "Administrator access required."}), 403
        return jsonify(
            {
                "data": {
                    **tracker.database.release3_diagnostics(),
                    "release": "release-3-execution-and-risk",
                    "automatic_model_tracker_honors_kill_switch": True,
                    "personal_positions_private": True,
                    "fabricated_data": False,
                }
            }
        )

    def learning_config() -> LearningConfig:
        return LearningConfig(
            insufficient_sample_count=settings.edge_map_insufficient_sample_count,
            moderate_sample_count=settings.edge_map_moderate_sample_count,
            strong_sample_count=settings.edge_map_strong_sample_count,
            minimum_holdout_count=settings.edge_map_minimum_holdout_count,
        )

    def calculate_edge_map(persist: bool = False) -> dict:
        rows = tracker.database.learning_candidate_rows()
        config = learning_config()
        segments = build_edge_map(rows, config)
        now = datetime.now(timezone.utc).isoformat()
        run = {
            "run_id": stable_hash(EDGE_MAP_VERSION, now, len(rows)),
            "window_start": min((row.get("detected_at") for row in rows if row.get("detected_at")), default=None),
            "window_end": max((row.get("detected_at") for row in rows if row.get("detected_at")), default=None),
            "candidate_count": len(rows), "config": config_dict(config),
            "calculation_version": EDGE_MAP_VERSION, "created_at": now,
        }
        if persist:
            tracker.database.record_edge_map(run, segments)
            tracker.database.record_post_change_monitoring(run["run_id"], segments)
        return {"run": run, "segments": segments}

    @app.route("/api/edge-map")
    def api_edge_map():
        dimension = request.args.get("dimension", "").strip() or None
        result = tracker.database.latest_edge_map(dimension)
        if result["run"] is None:
            result = calculate_edge_map(persist=False)
            if dimension:
                result["segments"] = [row for row in result["segments"] if row["dimension"] == dimension]
        return jsonify({"data": result, "production_weights_auto_changed": False})

    @app.route("/api/rule-violations", methods=["GET", "POST"])
    def api_rule_violations():
        if request.method == "GET":
            rows = tracker.database.list_rule_violations(g.iconbets_user_id)
            return jsonify({"data": rows, "analytics": violation_analytics(rows)})
        payload = request.get_json(silent=True) or {}
        warning = str(payload.get("warning_code") or "").strip().upper()
        if warning not in VIOLATION_WARNINGS:
            return jsonify({"error": "Unknown rule-violation warning."}), 400
        if payload.get("confirmed") is not True or not str(payload.get("confirmation_text") or "").strip():
            return jsonify({"error": "Explicit confirmation text is required."}), 400
        if not str(payload.get("trade_id") or "").strip() or not str(payload.get("confirmed_action") or "").strip():
            return jsonify({"error": "Trade ID and confirmed action are required."}), 400
        values = {
            "trade_id": str(payload["trade_id"]), "candidate_id": payload.get("candidate_id"),
            "warning_code": warning, "confirmed_action": str(payload["confirmed_action"]),
            "confirmation_text": str(payload["confirmation_text"]),
            "entry_price": payload.get("entry_price"), "outcome": payload.get("outcome"),
            "profit_loss": None, "exchange_clv": None,
            "composite_clv": None, "context": payload.get("context") or {},
            "calculation_version": RULE_VIOLATION_VERSION,
        }
        return jsonify({"data": tracker.database.record_rule_violation(g.iconbets_user_id, values)}), 201

    @app.route("/api/admin/rule-violations/<violation_id>/settle", methods=["POST"])
    def api_admin_settle_rule_violation(violation_id: str):
        if not is_admin():
            return jsonify({"error": "Administrator access required."}), 403
        payload = request.get_json(silent=True) or {}
        try:
            row = tracker.database.settle_rule_violation(violation_id, payload)
        except KeyError as exc:
            return jsonify({"error": str(exc)}), 404
        return jsonify({"data": row})

    @app.route("/api/admin/rule-violations")
    def api_admin_rule_violations():
        if not is_admin():
            return jsonify({"error": "Administrator access required."}), 403
        rows = tracker.database.list_rule_violations()
        return jsonify({"data": rows, "analytics": violation_analytics(rows)})

    @app.route("/api/admin/learning-system/recalculate", methods=["POST"])
    def api_admin_learning_recalculate():
        if not is_admin():
            return jsonify({"error": "Administrator access required."}), 403
        return jsonify({"data": calculate_edge_map(persist=True)})

    @app.route("/api/admin/learning-system/diagnostics")
    def api_admin_learning_diagnostics():
        if not is_admin():
            return jsonify({"error": "Administrator access required."}), 403
        violations = tracker.database.list_rule_violations()
        return jsonify({"data": {**tracker.database.release4_diagnostics(), "release": "release-4-learning-system", "config": config_dict(learning_config()), "rule_violation_analytics": violation_analytics(violations), "provider_data_fabricated": False}})

    @app.route("/api/admin/configuration-proposals", methods=["GET", "POST"])
    def api_admin_configuration_proposals():
        if not is_admin():
            return jsonify({"error": "Administrator access required."}), 403
        if request.method == "GET":
            return jsonify({"data": tracker.database.list_configuration_proposals()})
        payload = request.get_json(silent=True) or {}
        required = ("segment_dimension", "segment_value", "proposal_type", "proposed_config")
        if any(key not in payload for key in required):
            return jsonify({"error": "Segment, proposal type, and proposed configuration are required."}), 400
        proposal = tracker.database.create_configuration_proposal(payload, "admin")
        return jsonify({"data": proposal, "live_configuration_changed": False}), 201

    @app.route("/api/admin/configuration-proposals/<proposal_id>/holdout", methods=["POST"])
    def api_admin_configuration_holdout(proposal_id: str):
        if not is_admin():
            return jsonify({"error": "Administrator access required."}), 403
        proposal = tracker.database.get_configuration_proposal(proposal_id)
        if not proposal:
            return jsonify({"error": "Proposal not found."}), 404
        payload = request.get_json(silent=True) or {}
        required = ("baseline_start", "baseline_end", "holdout_start", "holdout_end")
        if any(not payload.get(key) for key in required):
            return jsonify({"error": "Baseline and holdout date windows are required."}), 400
        if not (payload["baseline_start"] <= payload["baseline_end"] < payload["holdout_start"] <= payload["holdout_end"]):
            return jsonify({"error": "Holdout must be a later, non-overlapping period."}), 400
        rows = tracker.database.learning_candidate_rows()
        def metrics(start, end):
            selected = [row for row in rows if start <= str(row.get("detected_at") or "") <= end]
            return next((row for row in build_edge_map(selected, learning_config()) if row["dimension"] == proposal["segment_dimension"] and row["segment_value"] == proposal["segment_value"]), {"candidate_count": 0})
        baseline = metrics(payload["baseline_start"], payload["baseline_end"])
        holdout = metrics(payload["holdout_start"], payload["holdout_end"])
        evaluation = compare_holdout(baseline, holdout, learning_config())
        stored = tracker.database.record_holdout(proposal_id, proposal["segment_dimension"], proposal["segment_value"], baseline, holdout, evaluation, payload)
        return jsonify({"data": stored, "live_configuration_changed": False})

    @app.route("/api/admin/configuration-proposals/<proposal_id>/review", methods=["POST"])
    def api_admin_configuration_review(proposal_id: str):
        if not is_admin():
            return jsonify({"error": "Administrator access required."}), 403
        payload = request.get_json(silent=True) or {}
        try:
            row = tracker.database.review_configuration_proposal(proposal_id, str(payload.get("status") or "").upper(), "admin", payload.get("reason"))
        except KeyError as exc:
            return jsonify({"error": str(exc)}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"data": row, "live_configuration_changed": False})

    @app.route("/api/admin/configuration-proposals/<proposal_id>/apply", methods=["POST"])
    def api_admin_configuration_apply(proposal_id: str):
        if not is_admin():
            return jsonify({"error": "Administrator access required."}), 403
        try:
            row = tracker.database.apply_configuration_proposal(proposal_id, "admin")
        except KeyError as exc:
            return jsonify({"error": str(exc)}), 404
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"data": row, "live_configuration_changed": True, "risk_increase_allowed": False})

    @app.route("/api/admin/explainability/<candidate_id>")
    def api_admin_explainability(candidate_id: str):
        if not is_admin():
            return jsonify({"error": "Administrator access required."}), 403
        measurements = tracker.database.get_candidate_measurements(candidate_id)
        if not measurements:
            return jsonify({"error": "Candidate not found."}), 404
        return jsonify({"data": explainability_trace(measurements)})

    @app.route("/api/tracker/advanced-analytics")
    def api_tracker_advanced_analytics():
        rows = tracker.database.learning_candidate_rows()
        segments = build_edge_map(rows, learning_config())
        wanted = {"wallet", "sport", "time_to_event_bucket", "trade_grade", "liquidity_grade", "execution_method", "decision_class"}
        return jsonify({"data": {"segments": [row for row in segments if row["dimension"] in wanted], "played_vs_passed": {"played": sum(str(row.get("current_decision", "")).startswith("APPROVED") for row in rows), "passed": sum(row.get("current_decision") == "PASSED" for row in rows), "research_only": sum(row.get("current_decision") == "RESEARCH_ONLY" for row in rows)}, "calculation_version": EDGE_MAP_VERSION, "fabricated_data": False}})

    @app.route("/api/admin/completion/diagnostics")
    def api_admin_completion_diagnostics():
        if not is_admin():
            return jsonify({"error": "Administrator access required."}), 403
        return jsonify({"data": {**tracker.database.completion_diagnostics(), "measurement": tracker.database.measurement_diagnostics(), "decision": tracker.database.decision_engine_diagnostics(), "execution_risk": tracker.database.release3_diagnostics(), "learning": tracker.database.release4_diagnostics(), "release": "release-5-completion"}})

    @app.route("/api/admin/risk/kill-switch", methods=["POST"])
    def api_admin_risk_kill_switch():
        if not is_admin():
            return jsonify({"error": "Administrator access required."}), 403
        payload = request.get_json(silent=True) or {}
        enabled = bool(payload.get("enabled"))
        reason = str(payload.get("reason") or "MANUAL_ADMIN_KILL_SWITCH").strip().upper()
        user_id = str(payload.get("user_id") or MODEL_TRACKER_USER_ID)
        state = tracker.database.set_manual_kill_switch(
            user_id, enabled, reason, "admin", override=not enabled
        )
        return jsonify({"data": state})

    @app.route("/api/admin/risk/state", methods=["POST"])
    def api_admin_risk_state():
        if not is_admin():
            return jsonify({"error": "Administrator access required."}), 403
        payload = request.get_json(silent=True) or {}
        user_id = str(payload.pop("user_id", MODEL_TRACKER_USER_ID))
        bankroll = _safe_float(payload.get("current_bankroll"), settings.default_bankroll)
        try:
            state = tracker.database.update_risk_account_state(user_id, bankroll, payload)
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"data": state})

    @app.route("/api/admin/candidate-ledger/<candidate_id>")
    def api_candidate_ledger_record(candidate_id: str):
        if not is_admin():
            return jsonify({"error": "Administrator access required."}), 403
        row = tracker.database.get_candidate_measurements(candidate_id)
        if row is None:
            return jsonify({"error": "Candidate not found."}), 404
        return jsonify({"data": row})

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
        now = datetime.now(timezone.utc)
        for pin in tracker.database.get_all_active_whiteboard_pins():
            frozen = pin.get("snapshot") or {}
            status = str(frozen.get("official_event_status") or "").lower()
            event_start = _parse_datetime(
                frozen.get("official_event_start_time")
                or frozen.get("event_start_time")
            )
            reason = None
            if "cancel" in status:
                reason = "EVENT_CANCELED"
            elif "void" in status:
                reason = "MARKET_VOIDED"
            elif status in {"settled", "resolved", "closed"}:
                reason = "MARKET_SETTLED"
            elif event_start and event_start <= now and status != "postponed":
                reason = "EVENT_STARTED"
            if reason:
                tracker.database.archive_whiteboard_pin(
                    pin["user_id"], pin["id"], reason
                )
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
