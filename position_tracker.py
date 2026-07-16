from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from classification import (
    canonical_category_id,
    canonical_category_ids,
    classify_market,
    is_sports_category,
)
from clv import (
    CAPTURED,
    CLV_CALCULATION_VERSION,
    CLV_FRESHNESS_SECONDS,
    MARKET_MAPPING_ERROR,
    STALE_QUOTE,
    UNAVAILABLE,
    VOID,
    book_effective_ask,
    calculate_clv,
    normalized_provider,
    parse_timestamp,
    select_last_fresh_quote,
)
from bet_sizing import SizingConfig
from bet_tracker import tracker_status_from_event
from config import Settings
from database import TrackerDatabase
from discord_notifier import DiscordNotifier
from decision_engine import enrich_trade_decision
from execution_providers import build_execution_provider_registry
from fair_price_engine import FairPriceEngine, composite_snapshot
from model_tracker_discord import (
    DiscordNotificationDispatcher,
    ModelTrackerDiscordBot,
    build_model_tracker_discord_payload,
)
from market_lifecycle import classify_lifecycle
from measurement_foundation import (
    CompositePriceProviderRegistry,
    build_candidate_record,
    build_exclusion_record,
    unavailable_composite_snapshot,
)
from polymarket_client import PolymarketClient
from recommendation_service import (
    DUPLICATE_RECOMMENDATION,
    NOT_TODAY,
    SYNC_INCOMPLETE,
    evaluate_trade_recommendation,
)
from scoring import hours_until_resolution, score_position
from trade_scoring import build_trades_to_play
from unit_analysis import amount_to_units, estimate_unit_size
from wallet_activity import aggregate_trade_fills, normalize_trade_fills
from wallet_loader import WalletEntry, load_wallets

LOGGER = logging.getLogger(__name__)
MODEL_TRACKER_USER_ID = "iconbets-model-tracker-global"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def _wallet_signal_tier(
    units: float | None, minimum_units: float | None, actionable_units: float | None
) -> str | None:
    if units is None:
        return None
    minimum = minimum_units if minimum_units is not None else 0.2
    actionable = actionable_units if actionable_units is not None else minimum
    if units <= minimum:
        return "below-minimum"
    if units < actionable:
        return "building"
    if units < 1.0:
        return "qualifying"
    if units < 1.5:
        return "standard"
    if units <= 2.0:
        return "strong"
    return "unusually-large"


def polymarket_market_url(event_slug: Any, market_slug: Any = None) -> str:
    event_value = str(event_slug or "").strip()
    market_value = str(market_slug or "").strip()
    if not event_value and not market_value:
        return ""
    event_value = event_value or market_value
    url = f"https://polymarket.com/event/{quote(event_value, safe='-')}"
    if market_value and market_value != event_value:
        url += f"/{quote(market_value, safe='-')}"
    return url


def american_odds_from_probability(price: float | None) -> str:
    if price is None:
        return "n/a"
    probability = _safe_float(price)
    if probability <= 0 or probability >= 1:
        return "n/a"
    if probability >= 0.5:
        return str(round(-100 * probability / (1 - probability)))
    return f"+{round(100 * (1 - probability) / probability)}"


def american_odds_value_from_probability(price: float | None) -> int | None:
    odds = american_odds_from_probability(price)
    if odds == "n/a":
        return None
    return int(odds.replace("+", ""))


def probability_from_american_odds(odds: int) -> float:
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    return 100 / (odds + 100)


def within_odds_range(price: float, min_odds: int | None, max_odds: int | None) -> bool:
    if min_odds is None and max_odds is None:
        return True
    if price <= 0 or price >= 1:
        return False
    odds = american_odds_value_from_probability(price)
    if odds is None:
        return False
    if min_odds is not None and odds < min_odds:
        return False
    if max_odds is not None and odds > max_odds:
        return False
    return True


def shorten_wallet(address: str) -> str:
    return f"{address[:6]}...{address[-4:]}"


def position_key(payload: dict) -> str:
    return f"{payload.get('conditionId') or payload.get('condition_id') or payload.get('slug')}::{payload.get('outcome')}"


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def market_for_position(position: dict, event: dict | None) -> dict:
    event = event or {}
    condition_id = str(
        position.get("conditionId") or position.get("condition_id") or ""
    ).lower()
    market_slug = str(position.get("slug") or position.get("market_slug") or "").lower()
    for market in event.get("markets") or []:
        if (
            condition_id
            and str(market.get("conditionId") or "").lower() == condition_id
        ):
            return market
    for market in event.get("markets") or []:
        if market_slug and str(market.get("slug") or "").lower() == market_slug:
            return market
    return {}


def outcome_token_id(position: dict, market: dict) -> str | None:
    outcomes = [
        str(value).strip().lower() for value in _json_list(market.get("outcomes"))
    ]
    token_ids = [str(value) for value in _json_list(market.get("clobTokenIds"))]
    selected = str(position.get("outcome") or "").strip().lower()
    for index, outcome in enumerate(outcomes):
        if outcome == selected and index < len(token_ids):
            return token_ids[index]
    return str(position.get("asset") or "") or None


def coarse_event_datetime(position: dict) -> datetime | None:
    end_date = position.get("endDate")
    if end_date:
        try:
            parsed = datetime.fromisoformat(str(end_date).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    match = re.search(r"(20\d{2}-\d{2}-\d{2})", str(position.get("eventSlug") or ""))
    if not match:
        return None
    try:
        return datetime.fromisoformat(match.group(1)).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def event_start_time(
    position: dict, event: dict | None, market: dict | None = None
) -> tuple[str, str]:
    event = event or {}
    market = market or market_for_position(position, event)
    market_fields = (
        "gameStartTime",
        "eventStartTime",
        "scheduledStartTime",
        "startTime",
    )
    event_fields = ("startTime", "gameStartTime", "scheduledStartTime")
    position_fields = ("startTime", "scheduledStartTime", "gameStartTime", "start_time")
    for field in market_fields:
        if market.get(field):
            return str(market[field]), f"market.{field}"
    for field in event_fields:
        if event.get(field):
            return str(event[field]), f"event.{field}"
    for field in position_fields:
        if position.get(field):
            return str(position[field]), f"position.{field}"
    return "", "missing"


class TrackerService:
    def __init__(
        self,
        settings: Settings,
        client: PolymarketClient | None = None,
        database: TrackerDatabase | None = None,
        notifier: DiscordNotifier | None = None,
        model_discord_bot: ModelTrackerDiscordBot | None = None,
        auto_start: bool = True,
    ) -> None:
        self.settings = settings
        self.client = client or PolymarketClient(
            settings.request_timeout, settings.max_retries
        )
        self.database = database or TrackerDatabase(
            settings.database_path, settings.durable_database_url
        )
        promoted_records = self.database.promote_tracker_records_to_global(
            MODEL_TRACKER_USER_ID
        )
        if promoted_records:
            LOGGER.info(
                "Promoted %s existing recommendations into the global Model Tracker",
                promoted_records,
            )
        self.notifier = notifier or DiscordNotifier.from_settings(settings)
        self.model_discord_bot = model_discord_bot or ModelTrackerDiscordBot.from_settings(
            settings
        )
        self.discord_dispatcher = DiscordNotificationDispatcher(
            self.database,
            self.model_discord_bot,
            settings.discord_notification_batch_size,
        )
        self.sizing_config = SizingConfig(unit_percentage=settings.unit_percentage)
        self.composite_price_providers = CompositePriceProviderRegistry.release1_default()
        self.execution_providers = build_execution_provider_registry(settings)
        self.fair_price_engine = FairPriceEngine()
        self._lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._started = False
        self._thread: threading.Thread | None = None
        self._cache = {
            "positions": [],
            "trades": [],
            "trades_to_play": [],
            "trade_exclusions": [],
            "consensus": [],
            "unit_analysis": [],
            "wallets": [],
            "status": self._empty_status(),
        }
        if auto_start:
            self.start()

    def _empty_status(self) -> dict[str, Any]:
        return {
            "app_status": "starting",
            "api_status": "idle",
            "last_refresh_attempt": None,
            "last_successful_refresh": None,
            "enabled_wallet_count": 0,
            "valid_wallet_count": 0,
            "invalid_wallet_count": 0,
            "position_count": 0,
            "recent_trade_count": 0,
            "warnings": [],
            "wallet_loader": {},
            "api_errors": [],
            "overview": {},
            "database": self.database.health(),
        }

    def start(self) -> None:
        with self._start_lock:
            if self._started:
                return

            self.refresh()
            self._started = True

            if self.settings.dashboard_refresh <= 0 or os.getenv("VERCEL"):
                return

            self._thread = threading.Thread(
                target=self._refresh_loop, name="tracker-refresh", daemon=True
            )
            self._thread.start()

    def _refresh_loop(self) -> None:
        while True:
            time.sleep(self.settings.dashboard_refresh)
            self.refresh()

    def get_snapshot(self) -> dict[str, Any]:
        self.refresh_if_stale()
        with self._lock:
            return json.loads(json.dumps(self._cache))

    def refresh(self) -> None:
        with self._refresh_lock:
            self._refresh_unlocked()

    def refresh_if_stale(self) -> None:
        if not self._started:
            return
        if self.settings.dashboard_refresh <= 0 or not self._snapshot_is_stale():
            return
        if not self._refresh_lock.acquire(blocking=False):
            return
        try:
            if self._snapshot_is_stale():
                self._refresh_unlocked()
        finally:
            self._refresh_lock.release()

    def _snapshot_is_stale(self) -> bool:
        with self._lock:
            status = self._cache.get("status", {})
            timestamp = status.get("last_successful_refresh") or status.get(
                "last_refresh_attempt"
            )

        if not timestamp:
            return True

        try:
            parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        except ValueError:
            return True
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (_utc_now() - parsed).total_seconds() >= self.settings.dashboard_refresh

    def _refresh_unlocked(self) -> None:
        attempt_time = _iso_now()
        loader = load_wallets(self.settings.wallets_file)
        wallet_payload = self._build_wallet_payload(loader)
        self.database.sync_wallet_registry(
            [asdict(wallet) for wallet in loader.valid_wallets]
        )
        for wallet in loader.enabled_wallets:
            self.database.set_wallet_sync_state(wallet.address, "syncing")

        status = self._empty_status()
        status["last_refresh_attempt"] = attempt_time
        status["enabled_wallet_count"] = len(loader.enabled_wallets)
        status["valid_wallet_count"] = len(loader.valid_wallets)
        status["invalid_wallet_count"] = len(loader.invalid_entries) + len(
            loader.file_errors
        )
        status["wallet_loader"] = loader.as_dict()
        status["wallets"] = wallet_payload
        status["warnings"] = loader.file_errors + [
            error["message"] for error in wallet_payload if error["status"] == "invalid"
        ]

        if loader.file_errors:
            status["app_status"] = "degraded"

        if not loader.enabled_wallets:
            self.reconcile_model_tracker([])
            self._update_tracker_statuses({})
            snapshot = {
                "positions": [],
                "trades": self.database.get_recent_events(),
                "trades_to_play": [],
                "trade_exclusions": [],
                "consensus": [],
                "unit_analysis": [],
                "wallets": wallet_payload,
                "status": {
                    **status,
                    "app_status": "ok",
                    "api_status": "idle",
                    "recent_trade_count": len(self.database.get_recent_events()),
                    "overview": self._build_overview([], [], [], status),
                },
            }
            with self._lock:
                self._cache = snapshot
            return

        fetch_results = self._fetch_wallet_data(loader.enabled_wallets)
        open_positions = fetch_results["open_positions"]
        closed_positions = fetch_results["closed_positions"]
        raw_trade_fills = fetch_results["trade_fills"]
        api_errors = fetch_results["errors"]
        status["api_errors"] = api_errors
        status["api_status"] = (
            "ok" if not api_errors else ("degraded" if open_positions else "error")
        )

        candidate_open_positions: dict[str, list[dict] | None] = {}
        candidate_start = _utc_now() - timedelta(days=14)
        candidate_end = _utc_now() + timedelta(days=21)
        for address, positions_for_wallet in open_positions.items():
            if positions_for_wallet is None:
                candidate_open_positions[address] = None
                continue
            candidate_open_positions[address] = [
                position
                for position in positions_for_wallet
                if (
                    not self.settings.sports_only
                    or classify_market(position, None).is_sports
                )
                and (coarse_event_datetime(position) is not None)
                and candidate_start <= coarse_event_datetime(position) <= candidate_end
            ]

        unique_event_slugs = [
            position.get("eventSlug")
            for positions in candidate_open_positions.values()
            if positions
            for position in positions
            if position.get("eventSlug")
        ]
        invalidate_event_cache = getattr(self.client, "invalidate_event_cache", None)
        if invalidate_event_cache:
            invalidate_event_cache()
        events = self.client.get_events(unique_event_slugs)
        category_metrics = self._build_category_metrics(closed_positions, events)

        fill_aggregates_by_wallet: dict[
            str, dict[tuple[str, str], dict[str, Any]]
        ] = {}
        fill_sync_stats: dict[str, dict[str, Any]] = {}
        for wallet in loader.enabled_wallets:
            raw_fills = raw_trade_fills.get(wallet.address) or []
            normalized_fills, duplicate_count = normalize_trade_fills(
                wallet.address, raw_fills
            )
            imported_count = self.database.insert_wallet_execution_fills(
                normalized_fills
            )
            aggregates = aggregate_trade_fills(normalized_fills)
            fill_aggregates_by_wallet[wallet.address] = aggregates
            fill_counts = [aggregate["fill_count"] for aggregate in aggregates.values()]
            fill_sync_stats[wallet.address] = {
                "raw_fill_count": len(raw_fills),
                "deduplicated_fill_count": len(normalized_fills),
                "duplicate_fill_count": duplicate_count,
                "new_fill_count": imported_count,
                "aggregated_position_count": len(aggregates),
                "average_fills_per_aggregated_position": (
                    round(sum(fill_counts) / len(fill_counts), 2)
                    if fill_counts
                    else 0.0
                ),
            }

        current_rows: list[dict] = []
        for wallet in loader.enabled_wallets:
            wallet_open = candidate_open_positions.get(wallet.address)
            if wallet_open is None:
                continue

            previous_rows = self.database.get_open_positions_for_wallet(wallet.address)
            normalized_rows = self._normalize_positions(
                wallet,
                wallet_open,
                events,
                category_metrics.get(wallet.address, {}),
                fill_aggregates_by_wallet.get(wallet.address, {}),
            )
            self._apply_wallet_hedge_controls(normalized_rows)
            current_rows.extend(
                self._persist_positions(
                    wallet,
                    normalized_rows,
                    previous_rows,
                    closed_positions.get(wallet.address, []),
                    events,
                    observed_open_keys={
                        position_key(position)
                        for position in (open_positions.get(wallet.address) or [])
                    },
                )
            )

        try:
            get_order_books = getattr(self.client, "get_order_books", None)
            order_books = (
                get_order_books([row.get("clob_token_id") for row in current_rows])
                if get_order_books
                else {}
            )
        except Exception as exc:
            LOGGER.warning("Failed to refresh executable CLOB prices: %s", exc)
            order_books = {}
            api_errors.append(f"CLOB order books: {exc}")
            status["api_errors"] = api_errors
            status["api_status"] = "degraded"
        self._attach_order_books(current_rows, order_books)

        current_rows = [
            row for row in current_rows if self._position_matches_filters(row)
        ]
        current_rows.sort(
            key=lambda row: (
                row.get("resolution_time") or "",
                -float(row.get("position_size_usd") or 0),
            )
        )

        trades = self.database.get_recent_events(limit=250)
        unit_analysis = self._build_unit_analysis(loader.enabled_wallets, current_rows)
        unit_map = {entry["wallet_address"]: entry for entry in unit_analysis}
        consensus = self._build_consensus(current_rows, trades, unit_map)
        consensus_map = {
            (entry["condition_id"], entry["outcome"]): entry for entry in consensus
        }
        positions = self._enrich_positions(
            current_rows, trades, unit_map, consensus_map
        )
        synced_wallet_count = sum(
            1
            for wallet in loader.enabled_wallets
            if open_positions.get(wallet.address) is not None
        )
        trade_exclusions: list[dict[str, Any]] = []
        trades_to_play = build_trades_to_play(
            positions,
            trades,
            unit_map,
            tracked_wallet_count=synced_wallet_count,
            diagnostics=trade_exclusions,
        )
        self.execution_providers.attach_options(trades_to_play)
        provider_quotes = self.execution_providers.fair_price_quotes(trades_to_play)
        for play in trades_to_play:
            play["decision_bankroll"] = self.settings.default_bankroll
            fair_price = self.fair_price_engine.calculate(
                provider_quotes.get(str(play.get("id") or ""), [])
            ).to_dict()
            enrich_trade_decision(play, fair_price)
        measurement = self._record_candidate_measurements(
            trades_to_play, trade_exclusions, _utc_now()
        )
        self.reconcile_model_tracker(trades_to_play)
        self._update_tracker_statuses(events)
        success_time = _iso_now()
        status["last_successful_refresh"] = success_time
        overview = self._build_overview(positions, trades, consensus, status)
        overview["trades_to_play_count"] = len(trades_to_play)
        overview["live_position_count"] = len(
            [
                position
                for position in positions
                if position.get("lifecycle_status") == "live"
            ]
        )
        self._apply_wallet_sync_status(
            wallet_payload,
            loader.enabled_wallets,
            open_positions,
            closed_positions,
            positions,
            success_time,
            fill_sync_stats,
            category_metrics,
        )
        status["position_count"] = len(positions)
        status["recent_trade_count"] = len(
            [trade for trade in trades if self._within_hours(trade["detected_at"], 24)]
        )
        status["overview"] = overview
        status["app_status"] = "ok" if status["api_status"] != "error" else "degraded"
        status["database"] = self.database.health()
        status["measurement_foundation"] = measurement

        self.database.set_refresh_state("last_refresh_attempt", attempt_time)
        self.database.set_refresh_state("last_successful_refresh", success_time)
        self.database.set_refresh_state("api_status", status["api_status"])

        with self._lock:
            self._cache = {
                "positions": positions,
                "trades": trades,
                "trades_to_play": trades_to_play,
                "trade_exclusions": trade_exclusions,
                "consensus": consensus,
                "unit_analysis": unit_analysis,
                "wallets": wallet_payload,
                "status": status,
            }

    def track_recommendations_for_user(
        self,
        user_id: str,
        bankroll: float,
        plays: list[dict] | None = None,
    ) -> int:
        return self.reconcile_user_tracker(user_id, bankroll, plays)["inserted"]

    def track_model_recommendations(self, plays: list[dict] | None = None) -> int:
        return self.reconcile_user_tracker(
            MODEL_TRACKER_USER_ID,
            self.settings.default_bankroll,
            plays,
        )["inserted"]

    def evaluate_recommendation(
        self,
        play: dict,
        bankroll: float,
        now: datetime | None = None,
    ) -> dict:
        return evaluate_trade_recommendation(
            play, bankroll, self.sizing_config, now=now
        )

    @staticmethod
    def _rejection_row(evaluation: dict, evaluated_at: str) -> dict:
        play = evaluation.get("play") or {}
        recommendation = evaluation.get("recommendation") or {}
        return {
            "event": play.get("event_title"),
            "market": play.get("market_title"),
            "selection": play.get("outcome"),
            "event_time": play.get("event_date_et"),
            "entry_price": recommendation.get("current_user_entry_price"),
            "recommended_fraction": recommendation.get(
                "final_recommended_fraction"
            ),
            "recommended_amount": recommendation.get("recommended_amount"),
            "rejection_reason": evaluation.get(
                "model_tracker_rejection_reason"
            ),
            "recommendation_snapshot_id": evaluation.get(
                "recommendation_snapshot_id"
            ),
            "recommendation_idempotency_key": evaluation.get(
                "recommendation_idempotency_key"
            ),
            "last_evaluated_at": evaluated_at,
        }

    def reconcile_user_tracker(
        self,
        user_id: str,
        bankroll: float,
        plays: list[dict] | None = None,
        now: datetime | None = None,
    ) -> dict:
        if plays is None:
            with self._lock:
                plays = json.loads(json.dumps(self._cache.get("trades_to_play", [])))
        run_now = now or _utc_now()
        evaluated_at = run_now.astimezone(timezone.utc).isoformat()
        result = {
            "user_id": user_id,
            "evaluated": 0,
            "eligible": 0,
            "existing": 0,
            "inserted": 0,
            "rejected": 0,
            "errors": 0,
            "accepted": [],
            "rejections": [],
            "error_details": [],
        }
        for play in plays:
            try:
                evaluation = self.evaluate_recommendation(play, bankroll, run_now)
                reason = evaluation.get("model_tracker_rejection_reason")
                if reason == NOT_TODAY:
                    continue
                result["evaluated"] += 1
                if not evaluation.get("model_tracker_eligible"):
                    result["rejected"] += 1
                    LOGGER.info(
                        "Model Tracker rejected user=%s key=%s reason=%s",
                        user_id,
                        evaluation.get("recommendation_idempotency_key"),
                        reason,
                    )
                    result["rejections"].append(
                        self._rejection_row(evaluation, evaluated_at)
                    )
                    continue

                result["eligible"] += 1
                dedupe_key = evaluation["recommendation_idempotency_key"]
                existing = self.database.get_tracker_record(user_id, dedupe_key)
                if existing is None:
                    snapshot = evaluation["snapshot"]
                    identity = (
                        snapshot.get("canonical_event_id"),
                        snapshot.get("canonical_market_id"),
                        str(snapshot.get("market_line") or ""),
                        snapshot.get("outcome_id"),
                    )
                    existing = next(
                        (
                            row
                            for row in self.database.get_tracker_records(user_id)
                            if (
                                (row.get("snapshot") or {}).get("canonical_event_id"),
                                (row.get("snapshot") or {}).get("canonical_market_id"),
                                str((row.get("snapshot") or {}).get("market_line") or ""),
                                (row.get("snapshot") or {}).get("outcome_id"),
                            )
                            == identity
                        ),
                        None,
                    )
                if existing:
                    result["existing"] += 1
                    LOGGER.info(
                        "Model Tracker duplicate user=%s key=%s snapshot_id=%s",
                        user_id,
                        dedupe_key,
                        existing["snapshot_id"],
                    )
                    result["accepted"].append(
                        {
                            "recommendation_idempotency_key": dedupe_key,
                            "snapshot_id": existing["snapshot_id"],
                            "insert_result": DUPLICATE_RECOMMENDATION,
                        }
                    )
                    continue

                snapshot = evaluation["snapshot"]
                discord_payload = None
                if (
                    user_id == MODEL_TRACKER_USER_ID
                    and self.model_discord_bot.enabled
                ):
                    discord_payload = build_model_tracker_discord_payload(snapshot)
                if self.database.insert_tracker_snapshot(
                    user_id,
                    snapshot,
                    status="scheduled",
                    discord_payload=discord_payload,
                ):
                    result["inserted"] += 1
                    LOGGER.info(
                        "Model Tracker inserted user=%s key=%s snapshot_id=%s",
                        user_id,
                        dedupe_key,
                        snapshot["snapshot_id"],
                    )
                    result["accepted"].append(
                        {
                            "recommendation_idempotency_key": dedupe_key,
                            "snapshot_id": snapshot["snapshot_id"],
                            "insert_result": "INSERTED",
                        }
                    )
                    continue

                existing = self.database.get_tracker_record(user_id, dedupe_key)
                if existing:
                    result["existing"] += 1
                    LOGGER.info(
                        "Model Tracker duplicate after insert race user=%s key=%s snapshot_id=%s",
                        user_id,
                        dedupe_key,
                        existing["snapshot_id"],
                    )
                    result["accepted"].append(
                        {
                            "recommendation_idempotency_key": dedupe_key,
                            "snapshot_id": existing["snapshot_id"],
                            "insert_result": DUPLICATE_RECOMMENDATION,
                        }
                    )
                else:
                    raise RuntimeError("Tracker insert returned no record")
            except Exception as exc:
                LOGGER.exception(
                    "Model Tracker reconciliation failed for user=%s trade=%s",
                    user_id,
                    play.get("id") or play.get("event_title"),
                )
                result["errors"] += 1
                result["error_details"].append(
                    {
                        "trade_id": play.get("id"),
                        "event": play.get("event_title"),
                        "reason": SYNC_INCOMPLETE,
                        "error": str(exc),
                    }
                )
        self.database.replace_tracking_rejections(user_id, result["rejections"])
        return result

    def reconcile_model_tracker(
        self,
        plays: list[dict] | None = None,
        now: datetime | None = None,
        force: bool = False,
    ) -> dict:
        prior = self.database.get_tracking_job_state()
        attempted = (now or _utc_now()).astimezone(timezone.utc)
        if prior.get("paused") and not force:
            return {**prior, "status": "paused"}
        state = {
            "status": "running",
            "paused": bool(prior.get("paused", False)),
            "last_attempted_run": attempted.isoformat(),
            "last_successful_run": prior.get("last_successful_run"),
            "recommendations_evaluated": 0,
            "eligible_recommendations": 0,
            "records_inserted": 0,
            "records_skipped_duplicates": 0,
            "records_rejected": 0,
            "errors": 0,
            "error_details": [],
            "user_configurations": 1,
            "tracker_scope": "global",
            "interval_seconds": self.settings.tracker_job_interval_seconds,
        }
        try:
            if plays is None:
                with self._lock:
                    plays = json.loads(
                        json.dumps(self._cache.get("trades_to_play", []))
                    )
            tracker_result = self.reconcile_user_tracker(
                MODEL_TRACKER_USER_ID,
                self.settings.default_bankroll,
                plays,
                attempted,
            )
            state["recommendations_evaluated"] = tracker_result["evaluated"]
            state["eligible_recommendations"] = tracker_result["eligible"]
            state["records_inserted"] = tracker_result["inserted"]
            state["records_skipped_duplicates"] = tracker_result["existing"]
            state["records_rejected"] = tracker_result["rejected"]
            state["errors"] = tracker_result["errors"]
            state["error_details"] = tracker_result["error_details"]
            if state["errors"]:
                state["status"] = "failed"
            else:
                state["last_successful_run"] = attempted.isoformat()
                state["status"] = "running"
        except Exception as exc:
            LOGGER.exception("Model Tracker job failed")
            state["status"] = "failed"
            state["errors"] += 1
            state["error_details"].append({"error": str(exc)})
        try:
            delivery = self.discord_dispatcher.dispatch_pending()
            state["discord_notifications"] = {
                **self.discord_dispatcher.safe_status(),
                **delivery,
            }
        except Exception:
            LOGGER.exception("Discord notification dispatch failed")
            state["discord_notifications"] = {
                **self.model_discord_bot.safe_configuration(),
                "dispatch_error": True,
            }
        state["next_scheduled_run"] = (
            attempted + timedelta(seconds=self.settings.tracker_job_interval_seconds)
        ).isoformat()
        self.database.set_tracking_job_state(state)
        return state

    def _record_candidate_measurements(
        self,
        plays: list[dict[str, Any]],
        exclusions: list[dict[str, Any]],
        observed_at: datetime,
    ) -> dict[str, Any]:
        timestamp = observed_at.astimezone(timezone.utc).isoformat()
        counts = {
            "observed": 0,
            "recorded": 0,
            "approved_standard": 0,
            "research_only": 0,
            "passed": 0,
            "invalid": 0,
            "skipped_invalid_identity": 0,
            "errors": 0,
        }
        for play in plays:
            counts["observed"] += 1
            try:
                evaluation = self.evaluate_recommendation(
                    play, self.settings.default_bankroll, observed_at
                )
                record = build_candidate_record(play, evaluation, timestamp)
                self.database.record_candidate(record)
                fair_price = play.get("fair_price") or {}
                snapshot = (
                    composite_snapshot(record, fair_price)
                    if fair_price
                    else unavailable_composite_snapshot(
                        record, self.composite_price_providers.health()
                    )
                )
                self.database.insert_composite_price_snapshot(snapshot)
                self.database.record_decision_engine_snapshot(
                    record["candidate_id"], record["correlation_id"], play, timestamp
                )
                counts["recorded"] += 1
                counts[record["decision"].lower()] = (
                    counts.get(record["decision"].lower(), 0) + 1
                )
            except Exception:
                LOGGER.exception(
                    "Candidate Ledger recording failed for trade=%s",
                    play.get("id") or play.get("event_title"),
                )
                counts["errors"] += 1
        for exclusion in exclusions:
            counts["observed"] += 1
            try:
                record = build_exclusion_record(exclusion, timestamp)
                if record is None:
                    counts["skipped_invalid_identity"] += 1
                    continue
                self.database.record_candidate(record)
                self.database.insert_composite_price_snapshot(
                    unavailable_composite_snapshot(
                        record, self.composite_price_providers.health()
                    )
                )
                counts["recorded"] += 1
                counts[record["decision"].lower()] = (
                    counts.get(record["decision"].lower(), 0) + 1
                )
            except Exception:
                LOGGER.exception(
                    "Candidate Ledger recording failed for exclusion=%s",
                    exclusion.get("reason"),
                )
                counts["errors"] += 1
        return counts

    def reconcile_all_user_trackers(
        self,
        plays: list[dict] | None = None,
        now: datetime | None = None,
        force: bool = False,
    ) -> dict:
        return self.reconcile_model_tracker(plays, now, force)

    def set_tracking_paused(self, paused: bool) -> dict:
        state = self.database.get_tracking_job_state()
        state["paused"] = bool(paused)
        state["status"] = "paused" if paused else "stale"
        state["next_scheduled_run"] = None if paused else (
            _utc_now() + timedelta(seconds=self.settings.tracker_job_interval_seconds)
        ).isoformat()
        self.database.set_tracking_job_state(state)
        return state

    def tracking_diagnostics(self, user_id: str) -> dict:
        state = self.database.get_tracking_job_state()
        last_success = state.get("last_successful_run")
        if not state:
            status = "stale"
        elif state.get("paused"):
            status = "paused"
        elif state.get("status") == "failed":
            status = "failed"
        elif not last_success:
            status = "stale"
        else:
            try:
                success_time = datetime.fromisoformat(
                    str(last_success).replace("Z", "+00:00")
                )
                stale_after = max(self.settings.tracker_job_interval_seconds * 3, 600)
                status = (
                    "stale"
                    if (_utc_now() - success_time).total_seconds() > stale_after
                    else "running"
                )
            except ValueError:
                status = "stale"
        upcoming_starts = sorted(
            {
                str(value)
                for value in [
                    *(
                        row["snapshot"].get("event_start_time")
                        for row in self.database.get_active_tracker_records()
                    ),
                    *(
                        row.get("event_start_time")
                        for row in self.database.get_all_active_personal_bet_fills()
                    ),
                ]
                if parse_timestamp(value) is not None
            }
        )[:10]
        return {
            **state,
            "status": status,
            "rejections": self.database.get_tracking_rejections(user_id),
            "clv": {
                **self.database.clv_diagnostics(),
                "last_successful_clv_job_run": last_success,
                "freshness_threshold_seconds": CLV_FRESHNESS_SECONDS,
                "calculation_version": CLV_CALCULATION_VERSION,
                "next_expected_event_starts": upcoming_starts,
            },
            "discord_notifications": {
                **state.get("discord_notifications", {}),
                **self.discord_dispatcher.safe_status(),
            },
        }

    def _update_tracker_statuses(self, events: dict[str, dict]) -> None:
        records = self.database.get_active_tracker_records()
        personal_fills = self.database.get_all_active_personal_bet_fills()
        candidates = self.database.get_monitorable_candidates()
        slugs = [record["snapshot"].get("canonical_event_slug") for record in records]
        slugs.extend(fill.get("canonical_event_slug") for fill in personal_fills)
        slugs.extend(
            (candidate.get("snapshot") or {}).get("provider_event_slug")
            for candidate in candidates
        )
        missing_slugs = [slug for slug in slugs if slug and slug not in events]
        if missing_slugs:
            events = {**events, **self.client.get_events(missing_slugs)}
        self._capture_closing_lines(records, personal_fills, events)
        for record in records:
            snapshot = record["snapshot"]
            event = events.get(snapshot.get("canonical_event_slug"))
            if not event:
                continue
            update = tracker_status_from_event(snapshot, event)
            if (
                update["status"] == record.get("status")
                and not update.get("result")
                and not update.get("settled_at")
            ):
                continue
            self.database.update_tracker_status(
                record["user_id"],
                record["dedupe_key"],
                update["status"],
                update.get("result"),
                update.get("settled_at"),
            )
        for fill in personal_fills:
            event = events.get(fill.get("canonical_event_slug"))
            if not event:
                continue
            snapshot = {
                "canonical_market_id": fill.get("canonical_market_id"),
                "recommended_side": fill.get("selection"),
                "event_start_time": fill.get("event_start_time"),
            }
            update = tracker_status_from_event(snapshot, event)
            if (
                update["status"] == fill.get("status")
                and not update.get("result")
                and not update.get("settled_at")
            ):
                continue
            self.database.update_personal_bet_status(
                fill["fill_id"],
                update["status"],
                update.get("result"),
                update.get("settled_at"),
            )
        for candidate in candidates:
            snapshot = candidate.get("snapshot") or {}
            event = events.get(snapshot.get("provider_event_slug"))
            if not event:
                continue
            update = tracker_status_from_event(
                {
                    "canonical_market_id": candidate.get("canonical_market_id"),
                    "recommended_side": candidate.get("selection"),
                    "event_start_time": candidate.get("event_start_time"),
                },
                event,
            )
            status = str(update.get("status") or "unresolved")
            if status not in {"won", "lost", "push", "void", "canceled"}:
                continue
            values: dict[str, Any] = {
                "monitoring_status": "COMPLETE",
                "result": update.get("result"),
            }
            entry = _safe_float(
                (candidate.get("execution_snapshot") or {}).get(
                    "current_executable_entry"
                )
            )
            if status == "won" and 0 < entry < 1:
                values["hypothetical_profit_loss"] = (
                    100.0 * ((1.0 / entry) - 1.0)
                )
            elif status == "lost":
                values["hypothetical_profit_loss"] = -100.0
            elif status in {"push", "void", "canceled"}:
                values["hypothetical_profit_loss"] = 0.0
            if candidate.get("current_decision") == "PASSED":
                if status == "lost":
                    values["pass_reason_justified"] = True
                elif status == "won":
                    values["pass_reason_justified"] = False
            self.database.update_candidate_monitoring(
                candidate["candidate_id"], values
            )

    @staticmethod
    def _provider_quote_timestamp(value: Any) -> str:
        if value is not None:
            try:
                numeric = float(value)
                if numeric > 10_000_000_000:
                    numeric /= 1000
                return datetime.fromtimestamp(numeric, tz=timezone.utc).isoformat()
            except (TypeError, ValueError, OSError):
                parsed = parse_timestamp(value)
                if parsed is not None:
                    return parsed.isoformat()
        return _iso_now()

    @staticmethod
    def _official_event_start(event: dict, fallback: Any) -> str | None:
        for field in ("actualStartTime", "startTime", "gameStartTime", "scheduledStartTime"):
            parsed = parse_timestamp(event.get(field))
            if parsed is not None:
                return parsed.isoformat()
        parsed = parse_timestamp(fallback)
        return parsed.isoformat() if parsed is not None else None

    @staticmethod
    def _event_status_update(reference: dict, event: dict) -> dict:
        return tracker_status_from_event(
            {
                "canonical_market_id": reference.get("provider_market_id"),
                "recommended_side": reference.get("selection"),
                "event_start_time": reference.get("event_start_time"),
            },
            event,
        )

    def _capture_closing_lines(
        self,
        records: list[dict],
        personal_fills: list[dict],
        events: dict[str, dict],
    ) -> None:
        references: list[dict[str, Any]] = []
        for record in records:
            snapshot = record["snapshot"]
            references.append(
                {
                    "tracker_type": "model",
                    "tracker_record_id": record["dedupe_key"],
                    "user_id": record["user_id"],
                    "provider": "polymarket",
                    "provider_event_id": str(snapshot.get("canonical_event_id") or ""),
                    "provider_event_slug": snapshot.get("canonical_event_slug"),
                    "provider_market_id": str(snapshot.get("canonical_market_id") or ""),
                    "provider_selection_id": str(snapshot.get("outcome_id") or ""),
                    "selection": snapshot.get("recommended_side"),
                    "event_start_time": snapshot.get("event_start_time"),
                    "entry_price": snapshot.get("effective_entry_price")
                    or snapshot.get("current_executable_entry_price"),
                    "entry_stake": snapshot.get("original_displayed_amount"),
                    "entry_timestamp": snapshot.get("recommendation_timestamp"),
                }
            )
        for fill in personal_fills:
            references.append(
                {
                    "tracker_type": "personal",
                    "tracker_record_id": fill["fill_id"],
                    "user_id": fill["user_id"],
                    "provider": normalized_provider(fill.get("sportsbook")),
                    "provider_event_id": str(fill.get("canonical_event_id") or ""),
                    "provider_event_slug": fill.get("canonical_event_slug"),
                    "provider_market_id": str(fill.get("canonical_market_id") or ""),
                    "provider_selection_id": str(fill.get("canonical_outcome_id") or ""),
                    "selection": fill.get("selection"),
                    "event_start_time": fill.get("event_start_time"),
                    "entry_price": fill.get("entry_price"),
                    "entry_stake": fill.get("position_cost"),
                    "entry_timestamp": fill.get("created_at"),
                }
            )
        for candidate in self.database.get_monitorable_candidates():
            frozen = candidate.get("snapshot") or {}
            execution = candidate.get("execution_snapshot") or {}
            references.append(
                {
                    "tracker_type": "candidate",
                    "tracker_record_id": candidate["candidate_id"],
                    "user_id": MODEL_TRACKER_USER_ID,
                    "provider": candidate.get("provider") or "polymarket",
                    "provider_event_id": candidate.get("canonical_event_id") or "",
                    "provider_event_slug": frozen.get("provider_event_slug"),
                    "provider_market_id": candidate.get("canonical_market_id") or "",
                    "provider_selection_id": candidate.get("canonical_outcome_id") or "",
                    "selection": candidate.get("selection"),
                    "event_start_time": candidate.get("event_start_time"),
                    "entry_price": execution.get("current_executable_entry"),
                    "entry_stake": 100.0,
                    "entry_timestamp": candidate.get("detected_at"),
                }
            )
        existing = {
            (row["tracker_type"], row["tracker_record_id"])
            for kind, user in {(row["tracker_type"], row["user_id"]) for row in references}
            for row in self.database.get_closing_lines(kind, user)
        }
        pending = [
            reference
            for reference in references
            if (reference["tracker_type"], reference["tracker_record_id"]) not in existing
        ]
        polymarket = [
            reference
            for reference in pending
            if reference["provider"] == "polymarket"
            and reference["provider_market_id"]
            and reference["provider_selection_id"]
        ]
        try:
            books = self.client.get_order_books(
                [reference["provider_selection_id"] for reference in polymarket]
            )
        except Exception as exc:
            LOGGER.warning("CLV order-book snapshot failed: %s", exc)
            books = {}
        for reference in polymarket:
            book = books.get(reference["provider_selection_id"])
            if not book:
                continue
            event = events.get(reference["provider_event_slug"]) or {}
            market = next(
                (
                    item
                    for item in event.get("markets") or []
                    if str(item.get("conditionId") or "")
                    == reference["provider_market_id"]
                ),
                {},
            )
            bids = book.get("bids") or []
            asks = book.get("asks") or []
            best_bid = _safe_float(bids[0].get("price")) if bids else None
            best_ask = _safe_float(asks[0].get("price")) if asks else None
            midpoint = (
                (best_bid + best_ask) / 2
                if best_bid and best_ask
                else None
            )
            self.database.insert_clv_quote(
                {
                    "provider": "polymarket",
                    "provider_event_id": reference["provider_event_id"],
                    "provider_market_id": reference["provider_market_id"],
                    "provider_selection_id": reference["provider_selection_id"],
                    "quote_timestamp": self._provider_quote_timestamp(book.get("timestamp")),
                    "provider_status": (
                        "closed"
                        if market.get("closed") is True
                        or market.get("acceptingOrders") is False
                        else "open"
                    ),
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "midpoint": midpoint,
                    "last_trade": _safe_float(book.get("last_trade_price")) or None,
                    "depth": asks,
                    "source": "POLYMARKET_CLOB_ORDER_BOOK",
                }
            )
            if reference.get("tracker_type") == "candidate":
                observation = book_effective_ask(
                    asks, reference.get("entry_stake")
                ).get("effective_price")
                if observation is not None:
                    self.database.record_candidate_price_observation(
                        reference["tracker_record_id"],
                        reference.get("entry_price"),
                        observation,
                    )
        for reference in pending:
            event = events.get(reference["provider_event_slug"])
            if not event:
                continue
            official_start = self._official_event_start(event, reference["event_start_time"])
            update = self._event_status_update(reference, event)
            status = str(update.get("status") or "scheduled")
            if status in {"void", "canceled"}:
                self._freeze_unavailable_clv(reference, VOID, status.upper(), official_start)
                continue
            status_text = " ".join(
                str(value or "").lower()
                for value in (
                    event.get("gameStatus"),
                    event.get("status"),
                    event.get("eventStatus"),
                )
            )
            official_start_time = parse_timestamp(official_start)
            if any(term in status_text for term in ("delayed", "postponed", "rescheduled")):
                continue
            if official_start_time is None or official_start_time > _utc_now():
                continue
            if status == "scheduled":
                continue
            if parse_timestamp(reference.get("entry_timestamp")) and official_start and parse_timestamp(reference["entry_timestamp"]) >= parse_timestamp(official_start):
                self._freeze_unavailable_clv(reference, UNAVAILABLE, "LATE_ENTRY_NO_PREGAME_CLV", official_start)
                continue
            if reference["provider"] != "polymarket":
                self._freeze_unavailable_clv(reference, MARKET_MAPPING_ERROR, "CLV_MARKET_MAPPING_ERROR", official_start)
                continue
            quotes = self.database.get_clv_quotes(
                reference["provider"], reference["provider_market_id"], reference["provider_selection_id"]
            )
            quote, reason = select_last_fresh_quote(quotes, official_start, CLV_FRESHNESS_SECONDS)
            if quote is None:
                self._freeze_unavailable_clv(
                    reference,
                    STALE_QUOTE if reason == "NO_FRESH_CLOSING_QUOTE" else UNAVAILABLE,
                    reason or "NO_FRESH_CLOSING_QUOTE",
                    official_start,
                )
                continue
            market = next(
                (
                    item
                    for item in event.get("markets") or []
                    if str(item.get("conditionId") or "")
                    == reference["provider_market_id"]
                ),
                {},
            )
            provider_closed_at = (
                market.get("closedTime")
                or market.get("acceptingOrdersTimestamp")
                or event.get("closedTime")
            )
            parsed_provider_close = parse_timestamp(provider_closed_at)
            if (
                (market.get("closed") is True or market.get("acceptingOrders") is False)
                and parsed_provider_close is not None
                and parsed_provider_close <= official_start_time
            ):
                quote = {
                    **quote,
                    "source": "MARKET_CLOSED_PRE_EVENT",
                    "provider_close_timestamp": parsed_provider_close.isoformat(),
                }
            self._freeze_captured_clv(reference, quote, official_start)

    def _freeze_unavailable_clv(
        self, reference: dict, status: str, reason: str, official_start: str | None
    ) -> None:
        self.database.insert_closing_line(
            {
                **reference,
                "entry_implied_probability": reference.get("entry_price"),
                "closing_snapshot_timestamp": None,
                "official_event_start_timestamp": official_start,
                "clv_status": status,
                "clv_unavailable_reason": reason,
                "provider_close_source": None,
                "calculation_version": CLV_CALCULATION_VERSION,
            }
        )
        self.database.upsert_dual_clv(
            {
                "tracker_type": reference["tracker_type"],
                "tracker_record_id": reference["tracker_record_id"],
                "user_id": reference["user_id"],
                "candidate_id": reference["tracker_record_id"] if reference.get("tracker_type") == "candidate" else None,
                "entry_price": reference.get("entry_price"),
                "exchange_clv_status": status,
                "composite_clv_status": "UNAVAILABLE",
                "exchange_missing_reason": reason,
                "composite_missing_reason": "NO_CONNECTED_INDEPENDENT_COMPOSITE_PROVIDER",
                "closing_timestamp": official_start,
                "exchange_calculation_version": CLV_CALCULATION_VERSION,
                "snapshot": {"exchange_status": status, "composite_status": "UNAVAILABLE"},
            }
        )
        if reference.get("tracker_type") == "candidate":
            self.database.update_candidate_monitoring(
                reference["tracker_record_id"],
                {
                    "monitoring_status": (
                        "COMPLETE"
                        if reason in {"VOID", "CANCELED", "CANCELLED"}
                        else "MONITORING"
                    ),
                    "exchange_clv_status": status,
                    "composite_clv_status": "UNAVAILABLE",
                    "missing_reason": reason,
                    "closing_timestamp": official_start,
                },
            )

    def _freeze_captured_clv(
        self, reference: dict, quote: dict, official_start: str | None
    ) -> None:
        execution = book_effective_ask(quote.get("depth") or [], reference.get("entry_stake"))
        effective = execution.get("effective_price")
        if effective is None:
            self._freeze_unavailable_clv(reference, UNAVAILABLE, "NO_EXECUTABLE_CLOSING_LIQUIDITY", official_start)
            return
        try:
            metrics = calculate_clv(reference.get("entry_price"), effective)
            midpoint_metrics = calculate_clv(reference.get("entry_price"), quote.get("midpoint")) if quote.get("midpoint") else None
        except ValueError:
            self._freeze_unavailable_clv(reference, UNAVAILABLE, "INVALID_ENTRY_OR_CLOSING_PRICE", official_start)
            return
        start = parse_timestamp(official_start)
        captured = parse_timestamp(quote.get("quote_timestamp"))
        self.database.insert_closing_line(
            {
                **reference,
                "entry_implied_probability": reference.get("entry_price"),
                "closing_snapshot_timestamp": quote.get("quote_timestamp"),
                "official_event_start_timestamp": official_start,
                "closing_best_bid": quote.get("best_bid"),
                "closing_best_ask": quote.get("best_ask"),
                "closing_midpoint": quote.get("midpoint"),
                "closing_last_trade": quote.get("last_trade"),
                "closing_effective_price": effective,
                "closing_executable_amount": execution["executable_amount"],
                "closing_unfilled_amount": execution["unfilled_amount"],
                "comparison_stake": reference.get("entry_stake"),
                "order_book_depth": execution["levels_used"],
                "liquidity_quality": execution["liquidity_quality"],
                "quote_age_ms": int((start - captured).total_seconds() * 1000) if start and captured else None,
                "quote_freshness_status": "fresh",
                **metrics,
                "midpoint_clv_pct": midpoint_metrics["clv_pct"] if midpoint_metrics else None,
                "clv_status": CAPTURED,
                "clv_unavailable_reason": None,
                "provider_close_source": quote.get("source"),
                "provider_market_close_timestamp": quote.get("provider_close_timestamp"),
                "calculation_version": CLV_CALCULATION_VERSION,
            }
        )
        self.database.upsert_dual_clv(
            {
                "tracker_type": reference["tracker_type"],
                "tracker_record_id": reference["tracker_record_id"],
                "user_id": reference["user_id"],
                "candidate_id": reference["tracker_record_id"] if reference.get("tracker_type") == "candidate" else None,
                "entry_price": reference.get("entry_price"),
                "exchange_closing_price": effective,
                "exchange_probability_point_clv": metrics["clv_probability_points"],
                "exchange_stake_return_clv": metrics["clv_pct"] / 100.0,
                "exchange_clv_status": CAPTURED,
                "composite_clv_status": "UNAVAILABLE",
                "exchange_missing_reason": None,
                "composite_missing_reason": "NO_CONNECTED_INDEPENDENT_COMPOSITE_PROVIDER",
                "closing_timestamp": quote.get("quote_timestamp"),
                "exchange_calculation_version": CLV_CALCULATION_VERSION,
                "snapshot": {"exchange_quote": quote, "composite_status": "UNAVAILABLE"},
            }
        )
        if reference.get("tracker_type") == "candidate":
            entry = _safe_float(reference.get("entry_price"))
            hypothetical_pnl = None
            if entry > 0:
                hypothetical_pnl = 100.0 * metrics["clv_pct"] / 100.0
            self.database.update_candidate_monitoring(
                reference["tracker_record_id"],
                {
                    "monitoring_status": "MONITORING",
                    "exchange_clv_status": CAPTURED,
                    "composite_clv_status": "UNAVAILABLE",
                    "exchange_closing_price": effective,
                    "exchange_probability_point_clv": metrics["clv_probability_points"],
                    "exchange_stake_return_clv": metrics["clv_pct"] / 100.0,
                    "closing_timestamp": quote.get("quote_timestamp"),
                    "hypothetical_profit_loss": hypothetical_pnl,
                    "missing_reason": "NO_CONNECTED_INDEPENDENT_COMPOSITE_PROVIDER",
                },
            )

    def _build_wallet_payload(self, loader) -> list[dict]:
        payload: list[dict] = []
        valid_by_address = {wallet.address: wallet for wallet in loader.wallets}
        for index, raw_entry in enumerate(loader.raw_entries):
            address = str(raw_entry.get("address") or "").strip().lower()
            wallet = valid_by_address.get(address)
            if wallet:
                payload.append(
                    {
                        "index": index,
                        "address": wallet.address,
                        "display_address": wallet.display_address,
                        "label": wallet.label,
                        "enabled": wallet.enabled,
                        "base_unit": wallet.base_unit,
                        "notes": wallet.notes,
                        "top_category": wallet.top_category,
                        "top_category_display": wallet.top_category_display,
                        "top_categories": list(wallet.top_categories),
                        "sub_top_categories": list(wallet.sub_top_categories),
                        "top_category_ids": list(wallet.top_category_ids),
                        "sub_top_category_ids": list(wallet.sub_top_category_ids),
                        "primary_top_category_id": wallet.primary_top_category_id,
                        "top_category_source": wallet.top_category_source,
                        "top_category_verified_at": wallet.top_category_verified_at,
                        "bettor_type": wallet.bettor_type,
                        "trader_type": wallet.trader_type,
                        "selectivity": wallet.selectivity,
                        "selectivity_code": wallet.selectivity_code,
                        "selectivity_score": wallet.selectivity_score,
                        "hold_tendency": wallet.hold_tendency,
                        "hold_profile": wallet.hold_profile,
                        "copyability": wallet.copyability,
                        "copyability_code": wallet.copyability_code,
                        "execution_style": wallet.execution_style,
                        "execution_style_code": wallet.execution_style_code,
                        "general_strategy": wallet.general_strategy,
                        "minimum_position_units": wallet.minimum_position_units,
                        "actionable_position_units": wallet.actionable_position_units,
                        "typical_execution_tranche_dollars": wallet.typical_execution_tranche_dollars,
                        "minimum_actionable_exposure_dollars": wallet.minimum_actionable_exposure_dollars,
                        "requires_fill_aggregation": wallet.requires_fill_aggregation,
                        "hedge_detection_required": wallet.hedge_detection_required,
                        "status": "enabled" if wallet.enabled else "disabled",
                        "sync_status": "pending" if wallet.enabled else "disabled",
                        "open_position_count": 0,
                        "closed_position_count": 0,
                        "historical_position_count": 0,
                        "last_synced_at": None,
                        "raw_fill_count": 0,
                        "deduplicated_fill_count": 0,
                        "duplicate_fill_count": 0,
                        "new_fill_count": 0,
                        "aggregated_position_count": 0,
                        "average_fills_per_aggregated_position": 0.0,
                        "historical_backfill_status": "pending",
                        "short_address": shorten_wallet(wallet.address),
                        "profile_url": f"https://polymarket.com/profile/{wallet.address}",
                    }
                )
            else:
                payload.append(
                    {
                        "index": index,
                        "address": raw_entry.get("address"),
                        "display_address": raw_entry.get("address"),
                        "label": raw_entry.get("label") or f"Trader {index + 1}",
                        "enabled": bool(raw_entry.get("enabled", True)),
                        "base_unit": raw_entry.get("base_unit"),
                        "notes": raw_entry.get("notes") or "",
                        "top_category": raw_entry.get("top_category"),
                        "top_category_display": raw_entry.get("top_category_display"),
                        "top_categories": raw_entry.get("top_categories") or [],
                        "sub_top_categories": raw_entry.get("sub_top_categories") or [],
                        "top_category_ids": raw_entry.get("topCategoryIds") or [],
                        "sub_top_category_ids": raw_entry.get("subTopCategoryIds") or [],
                        "primary_top_category_id": raw_entry.get(
                            "primary_top_category"
                        )
                        or raw_entry.get("primaryTopCategoryId"),
                        "top_category_source": raw_entry.get("top_category_source")
                        or raw_entry.get("topCategorySource"),
                        "top_category_verified_at": raw_entry.get(
                            "top_category_verified_at"
                        )
                        or raw_entry.get("topCategoryVerifiedAt"),
                        "bettor_type": raw_entry.get("bettor_type"),
                        "trader_type": raw_entry.get("trader_type"),
                        "selectivity": raw_entry.get("selectivity"),
                        "selectivity_code": raw_entry.get("selectivity_code"),
                        "selectivity_score": raw_entry.get("selectivity_score"),
                        "hold_tendency": raw_entry.get("hold_tendency"),
                        "hold_profile": raw_entry.get("hold_profile"),
                        "copyability": raw_entry.get("copyability"),
                        "copyability_code": raw_entry.get("copyability_code"),
                        "execution_style": raw_entry.get("execution_style"),
                        "execution_style_code": raw_entry.get("execution_style_code"),
                        "general_strategy": raw_entry.get("general_strategy"),
                        "minimum_position_units": raw_entry.get(
                            "minimum_position_units"
                        ),
                        "actionable_position_units": raw_entry.get(
                            "actionable_position_units"
                        ),
                        "typical_execution_tranche_dollars": raw_entry.get(
                            "typical_execution_tranche_dollars"
                        ),
                        "minimum_actionable_exposure_dollars": raw_entry.get(
                            "minimum_actionable_exposure_dollars"
                        ),
                        "requires_fill_aggregation": raw_entry.get(
                            "requires_fill_aggregation", False
                        ),
                        "hedge_detection_required": raw_entry.get(
                            "hedge_detection_required", False
                        ),
                        "status": "invalid",
                        "sync_status": "failed",
                        "open_position_count": 0,
                        "closed_position_count": 0,
                        "historical_position_count": 0,
                        "last_synced_at": None,
                        "raw_fill_count": 0,
                        "deduplicated_fill_count": 0,
                        "duplicate_fill_count": 0,
                        "new_fill_count": 0,
                        "aggregated_position_count": 0,
                        "average_fills_per_aggregated_position": 0.0,
                        "historical_backfill_status": "failed",
                        "short_address": None,
                        "profile_url": None,
                        "message": next(
                            (
                                error.message
                                for error in loader.invalid_entries
                                if error.index == index
                            ),
                            "Invalid wallet entry",
                        ),
                    }
                )
        return payload

    def _apply_wallet_sync_status(
        self,
        wallet_payload: list[dict],
        enabled_wallets: list[WalletEntry],
        open_positions: dict[str, list[dict] | None],
        closed_positions: dict[str, list[dict]],
        normalized_positions: list[dict],
        timestamp: str,
        fill_sync_stats: dict[str, dict[str, Any]],
        category_metrics: dict[str, dict[str, Any]],
    ) -> None:
        enabled_addresses = {wallet.address for wallet in enabled_wallets}
        history_counts = self.database.get_wallet_history_counts()
        normalized_counts: dict[str, int] = {}
        for position in normalized_positions:
            normalized_counts[position["wallet_address"]] = (
                normalized_counts.get(position["wallet_address"], 0) + 1
            )

        for wallet in wallet_payload:
            address = str(wallet.get("address") or "").lower()
            wallet.update(fill_sync_stats.get(address, {}))
            category_profile = category_metrics.get(address, {})
            statistical_top = category_profile.get("top_category")
            wallet["statistical_top_category"] = statistical_top
            wallet["statistical_top_category_source"] = category_profile.get(
                "top_category_source"
            )
            if not wallet.get("top_category") and statistical_top:
                wallet["top_category"] = statistical_top
                wallet["top_category_ids"] = category_profile.get(
                    "top_category_ids"
                ) or []
                wallet["primary_top_category_id"] = category_profile.get(
                    "primary_top_category_id"
                )
                wallet["top_category_source"] = category_profile.get(
                    "top_category_source"
                )
                wallet["top_category_verified_at"] = category_profile.get(
                    "top_category_verified_at"
                )
            primary_category_id = wallet.get("primary_top_category_id")
            category_stats = next(
                (
                    {"category": category, **metric}
                    for category, metric in (
                        category_profile.get("categories") or {}
                    ).items()
                    if canonical_category_id(category) == primary_category_id
                ),
                None,
            )
            wallet["top_category_stats"] = category_stats
            sub_top_category_ids = set(wallet.get("sub_top_category_ids") or [])
            wallet["sub_top_category_stats"] = [
                {"category": category, **metric}
                for category, metric in (category_profile.get("categories") or {}).items()
                if canonical_category_id(category) in sub_top_category_ids
            ]
            wallet["historical_position_count"] = history_counts.get(address, 0)
            if wallet.get("status") == "invalid":
                wallet["sync_status"] = "failed"
                continue
            if address not in enabled_addresses:
                wallet["sync_status"] = "disabled"
                self.database.set_wallet_sync_state(address, "disabled")
                continue
            if open_positions.get(address) is None:
                has_cached_positions = bool(
                    self.database.get_open_positions_for_wallet(address)
                )
                wallet["sync_status"] = "stale" if has_cached_positions else "failed"
                wallet["message"] = (
                    "Current-position sync failed; wallet excluded from Trades to Play until a successful refresh."
                )
                wallet["open_position_count"] = 0
                wallet["closed_position_count"] = len(closed_positions.get(address, []))
                wallet["last_synced_at"] = None
                self.database.set_wallet_sync_state(
                    address, wallet["sync_status"], error=wallet["message"]
                )
                continue
            wallet["sync_status"] = "ready"
            wallet["open_position_count"] = normalized_counts.get(address, 0)
            wallet["closed_position_count"] = len(closed_positions.get(address, []))
            wallet["settled_aggregated_position_count"] = len(
                closed_positions.get(address, [])
            )
            wallet["historical_backfill_status"] = (
                "partial"
                if wallet.get("requires_fill_aggregation")
                and len(closed_positions.get(address, [])) >= 500
                else "ready"
            )
            wallet["last_synced_at"] = timestamp
            self.database.set_wallet_sync_state(
                address, "ready", last_synced_at=timestamp
            )

    def _fetch_wallet_data(self, wallets: list[WalletEntry]) -> dict[str, Any]:
        open_positions: dict[str, list[dict] | None] = {}
        closed_positions: dict[str, list[dict]] = {}
        trade_fills: dict[str, list[dict]] = {}
        errors: list[str] = []

        def fetch_wallet(
            wallet: WalletEntry,
        ) -> tuple[str, list[dict], list[dict], list[dict]]:
            current = self.client.get_current_positions(wallet.address)
            closed = self.client.get_closed_positions(
                wallet.address, 500 if wallet.requires_fill_aggregation else 300
            )
            fills: list[dict] = []
            if wallet.requires_fill_aggregation:
                range_start = _utc_now() - timedelta(days=30)
                range_end = _utc_now() + timedelta(days=30)
                market_ids = sorted(
                    {
                        str(position.get("conditionId") or "").lower()
                        for position in current
                        if position.get("conditionId")
                        and _safe_float(position.get("currentValue")) > 0
                        and (
                            coarse_event_datetime(position) is None
                            or range_start
                            <= coarse_event_datetime(position)
                            <= range_end
                        )
                    }
                )
                get_user_trades = getattr(self.client, "get_user_trades", None)
                if market_ids and not callable(get_user_trades):
                    raise RuntimeError(
                        "Required executed-fill sync is unavailable for this wallet"
                    )
                if market_ids:
                    fills = get_user_trades(wallet.address, market_ids)
            return (
                wallet.address,
                current,
                closed,
                fills,
            )

        with ThreadPoolExecutor(max_workers=min(len(wallets), 8)) as executor:
            futures = {
                executor.submit(fetch_wallet, wallet): wallet for wallet in wallets
            }
            for future in as_completed(futures):
                wallet = futures[future]
                try:
                    address, current, closed, fills = future.result()
                    open_positions[address] = current
                    closed_positions[address] = closed
                    trade_fills[address] = fills
                except Exception as exc:
                    LOGGER.warning(
                        "Failed wallet refresh for %s: %s", wallet.address, exc
                    )
                    open_positions[wallet.address] = None
                    closed_positions[wallet.address] = []
                    trade_fills[wallet.address] = []
                    errors.append(f"{wallet.label} ({wallet.address}): {exc}")

        return {
            "open_positions": open_positions,
            "closed_positions": closed_positions,
            "trade_fills": trade_fills,
            "errors": errors,
        }

    def _build_category_metrics(
        self,
        closed_positions: dict[str, list[dict]],
        events: dict[str, dict],
    ) -> dict[str, dict[str, Any]]:
        output: dict[str, dict[str, Any]] = {}
        for wallet_address, positions in closed_positions.items():
            categories: dict[str, dict[str, Any]] = {}
            for position in positions:
                event = events.get(position.get("eventSlug"))
                classification = classify_market(position, event)
                settlement_price = _safe_float(position.get("curPrice"), -1.0)
                if settlement_price < 0.99 and settlement_price > 0.01:
                    continue
                metric = categories.setdefault(
                    classification.category,
                    {"sample_size": 0, "wins": 0, "losses": 0, "profit_loss": 0.0},
                )
                metric["sample_size"] += 1
                metric["wins" if settlement_price >= 0.99 else "losses"] += 1
                metric["profit_loss"] += _safe_float(position.get("realizedPnl"))

            for metric in categories.values():
                sample = metric["sample_size"]
                wins = metric["wins"]
                metric["raw_hit_rate"] = wins / sample if sample else None
                metric["adjusted_hit_rate"] = (
                    (wins + (0.52 * 100)) / (sample + 100) if sample else None
                )
                metric["source"] = "Polymarket closed positions"

            proven = [
                (category, metric)
                for category, metric in categories.items()
                if metric["sample_size"] >= 20 and metric["profit_loss"] > 0
            ]
            top_category = None
            if proven:
                top_category = max(
                    proven,
                    key=lambda item: (
                        item[1].get("adjusted_hit_rate") or 0,
                        item[1]["sample_size"],
                        item[1]["profit_loss"],
                    ),
                )[0]
            for category, metric in categories.items():
                metric["is_top_category"] = (
                    None if top_category is None else category == top_category
                )
            output[wallet_address.lower()] = {
                "top_category": top_category,
                "top_category_ids": list(canonical_category_ids([top_category])),
                "primary_top_category_id": canonical_category_id(top_category),
                "top_category_source": (
                    "statistically_verified" if top_category else None
                ),
                "top_category_verified_at": _iso_now() if top_category else None,
                "categories": categories,
            }
        return output

    def _attach_order_books(
        self, positions: list[dict], order_books: dict[str, dict]
    ) -> None:
        for position in positions:
            token_id = str(position.get("clob_token_id") or "")
            book = order_books.get(token_id) or {}
            asks = book.get("asks") or []
            bids = book.get("bids") or []
            position["orderbook"] = book
            position["executable_ask_price"] = (
                _safe_float(asks[0].get("price")) if asks else None
            )
            position["best_bid_price"] = (
                _safe_float(bids[0].get("price")) if bids else None
            )
            position["executable_price_source"] = (
                "clob_orderbook_best_ask" if asks else None
            )
            position["orderbook_timestamp"] = book.get("timestamp")

    def _normalize_positions(
        self,
        wallet: WalletEntry,
        positions: list[dict],
        events: dict[str, dict],
        wallet_category_metrics: dict[str, Any] | None = None,
        fill_aggregates: dict[tuple[str, str], dict[str, Any]] | None = None,
    ) -> list[dict]:
        rows: list[dict] = []
        wallet_category_metrics = wallet_category_metrics or {}
        fill_aggregates = fill_aggregates or {}
        for position in positions:
            event = events.get(position.get("eventSlug"))
            market = market_for_position(position, event)
            classification = classify_market(position, event)
            if self.settings.sports_only and not classification.is_sports:
                continue
            probability = _safe_float(position.get("curPrice"))
            if not within_odds_range(
                probability,
                self.settings.min_american_odds,
                self.settings.max_american_odds,
            ):
                continue

            size = _safe_float(position.get("size"))
            avg_price = _safe_float(position.get("avgPrice"))
            remaining_entry_value = size * avg_price
            initial_value = _safe_float(
                position.get("initialValue")
                or position.get("totalBought")
                or remaining_entry_value
            )
            current_value = _safe_float(
                position.get("currentValue") or size * probability
            )
            realized_pnl = _safe_float(position.get("realizedPnl"))
            cash_pnl = _safe_float(position.get("cashPnl"))
            unrealized_pnl = (
                cash_pnl - realized_pnl
                if cash_pnl
                else current_value - remaining_entry_value
            )
            market_url = polymarket_market_url(
                position.get("eventSlug"),
                position.get("slug") or market.get("slug"),
            )
            resolution_time, event_time_source = event_start_time(
                position, event, market
            )
            profile = self.client.get_public_profile(wallet.address)
            profile_name = (
                (profile or {}).get("name")
                or (profile or {}).get("pseudonym")
                or wallet.label
            )
            token_id = outcome_token_id(position, market)
            fill_aggregate = fill_aggregates.get(
                (
                    str(position.get("conditionId") or "").lower(),
                    str(token_id or ""),
                )
            )
            category_metric = (wallet_category_metrics.get("categories") or {}).get(
                classification.category
            )
            configured_top_category_ids = list(wallet.top_category_ids)
            statistical_top_category_ids = list(
                wallet_category_metrics.get("top_category_ids") or []
            )
            effective_top_category_ids = (
                configured_top_category_ids or statistical_top_category_ids
            )
            effective_top_category_source = (
                wallet.top_category_source
                if configured_top_category_ids
                else wallet_category_metrics.get("top_category_source")
            )
            effective_top_category_verified_at = (
                wallet.top_category_verified_at
                if configured_top_category_ids
                else wallet_category_metrics.get("top_category_verified_at")
            )

            row = {
                "wallet_address": wallet.address,
                "wallet_label": wallet.label,
                "wallet_display_name": profile_name,
                "wallet_display_address": wallet.display_address,
                "wallet_short_address": shorten_wallet(wallet.address),
                "wallet_profile_url": f"https://polymarket.com/profile/{wallet.address}",
                "wallet_base_unit": wallet.base_unit,
                "wallet_top_category": wallet.top_category,
                "wallet_top_category_display": wallet.top_category_display,
                "wallet_top_categories": list(wallet.top_categories),
                "wallet_sub_top_categories": list(wallet.sub_top_categories),
                "wallet_bettor_type": wallet.bettor_type,
                "wallet_trader_type": wallet.trader_type,
                "wallet_selectivity": wallet.selectivity,
                "wallet_selectivity_code": wallet.selectivity_code,
                "wallet_selectivity_score": wallet.selectivity_score,
                "wallet_hold_tendency": wallet.hold_tendency,
                "wallet_hold_profile": wallet.hold_profile,
                "wallet_copyability": wallet.copyability,
                "wallet_copyability_code": wallet.copyability_code,
                "wallet_execution_style": wallet.execution_style,
                "wallet_execution_style_code": wallet.execution_style_code,
                "wallet_general_strategy": wallet.general_strategy,
                "minimum_position_units": wallet.minimum_position_units,
                "actionable_position_units": wallet.actionable_position_units,
                "typical_execution_tranche_dollars": wallet.typical_execution_tranche_dollars,
                "minimum_actionable_exposure_dollars": wallet.minimum_actionable_exposure_dollars,
                "requires_fill_aggregation": wallet.requires_fill_aggregation,
                "hedge_detection_required": wallet.hedge_detection_required,
                "position_key": position_key(position),
                "condition_id": position.get("conditionId"),
                "event_slug": position.get("eventSlug"),
                "event_id": str(position.get("eventId") or (event or {}).get("id") or ""),
                "market_id": str(
                    market.get("id") or position.get("conditionId") or ""
                ),
                "market_slug": position.get("slug"),
                "market_title": position.get("title") or "",
                "event_title": (event or {}).get("title")
                or position.get("title")
                or "",
                "outcome": position.get("outcome") or "",
                "opposite_outcome": position.get("oppositeOutcome") or "",
                "category": classification.category,
                "league": classification.league,
                "canonical_sport_id": canonical_category_id(
                    classification.category
                ),
                "canonical_league_id": canonical_category_id(
                    classification.league
                ),
                "canonical_category_id": canonical_category_id(
                    classification.category
                ),
                "is_sports": classification.is_sports,
                "resolution_time": resolution_time,
                "event_time_source": event_time_source,
                "clob_token_id": token_id,
                "market_line": market.get("line"),
                "sports_market_type": market.get("sportsMarketType")
                or market.get("marketType"),
                "event_active": event.get("active") if event else None,
                "event_closed": event.get("closed") if event else None,
                "event_archived": event.get("archived") if event else None,
                "event_live": event.get("live") if event else None,
                "event_ended": event.get("ended") if event else None,
                "event_status": event.get("status") if event else None,
                "game_status": event.get("gameStatus") if event else None,
                "market_active": market.get("active"),
                "market_closed": market.get("closed"),
                "accepting_orders": market.get("acceptingOrders"),
                "market_resolution_status": market.get("umaResolutionStatus"),
                "market_status": market.get("marketStatus"),
                "market_open": bool(
                    market
                    and market.get("active") is True
                    and market.get("closed") is not True
                    and market.get("acceptingOrders") is not False
                ),
                "fees_enabled": market.get("feesEnabled"),
                "taker_base_fee": market.get("takerBaseFee"),
                "category_metrics": category_metric,
                "top_category": wallet_category_metrics.get("top_category"),
                "configured_top_category": wallet.top_category,
                "configured_top_categories": list(wallet.top_categories),
                "configured_sub_top_categories": list(wallet.sub_top_categories),
                "configured_top_category_ids": configured_top_category_ids,
                "configured_sub_top_category_ids": list(
                    wallet.sub_top_category_ids
                ),
                "top_category_ids": effective_top_category_ids,
                "primary_top_category_id": (
                    effective_top_category_ids[0]
                    if effective_top_category_ids
                    else None
                ),
                "top_category_source": effective_top_category_source,
                "top_category_verified_at": effective_top_category_verified_at,
                "first_detected_at": _iso_now(),
                "last_seen_at": _iso_now(),
                "last_changed_at": _iso_now(),
                "closed_at": None,
                "average_entry_price": round(avg_price, 4),
                "current_price": round(probability, 4),
                "average_entry_price_cents": round(avg_price * 100, 2),
                "current_price_cents": round(probability * 100, 2),
                "average_entry_odds": american_odds_from_probability(avg_price),
                "current_odds": american_odds_from_probability(probability),
                "american_odds_value": american_odds_value_from_probability(
                    probability
                ),
                "position_size_usd": round(remaining_entry_value, 2),
                "reported_initial_value": round(initial_value, 2),
                "current_value": round(current_value, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "realized_pnl": round(realized_pnl, 2),
                "shares": round(size, 4),
                "token_units": round(size, 4),
                "market_url": market_url,
                "status": "open",
                "source": "current_positions",
                "fill_aggregation_source": (
                    "polymarket_executed_trades"
                    if wallet.requires_fill_aggregation
                    else "current_position_snapshot"
                ),
                "fill_aggregation_status": (
                    "ready"
                    if fill_aggregate
                    else (
                        "no_matching_fills"
                        if wallet.requires_fill_aggregation
                        else "not_required"
                    )
                ),
                "raw_fill_count": (fill_aggregate or {}).get("fill_count", 0),
                "deduplicated_fill_count": (fill_aggregate or {}).get(
                    "fill_count", 0
                ),
                "buy_fill_count": (fill_aggregate or {}).get("buy_fill_count", 0),
                "sell_fill_count": (fill_aggregate or {}).get("sell_fill_count", 0),
                "fill_first_entry_at": (fill_aggregate or {}).get("first_entry_at"),
                "fill_last_addition_at": (fill_aggregate or {}).get(
                    "last_addition_at"
                ),
                "fill_calculated_remaining_shares": (fill_aggregate or {}).get(
                    "remaining_shares"
                ),
                "fill_calculated_remaining_cost_basis": (fill_aggregate or {}).get(
                    "remaining_cost_basis"
                ),
                "signal_position_size_usd": round(remaining_entry_value, 6),
                "net_directional_exposure_usd": round(remaining_entry_value, 6),
                "opposing_exposure_usd": 0.0,
                "wallet_hedge_status": "unhedged",
                "signal_rejection_reason": (
                    "INVALID_MARKET_MAPPING"
                    if wallet.requires_fill_aggregation
                    and (not position.get("conditionId") or not token_id)
                    else (
                        "FULLY_EXITED_POSITION"
                        if wallet.requires_fill_aggregation
                        and (fill_aggregate or {}).get("fully_exited")
                        else (
                            SYNC_INCOMPLETE
                            if wallet.requires_fill_aggregation and not fill_aggregate
                            else None
                        )
                    )
                ),
                "raw_position": position,
                "event_tags": [
                    tag.get("label") for tag in (event or {}).get("tags", [])
                ],
            }
            lifecycle = classify_lifecycle(row)
            row["lifecycle_status"] = lifecycle.state
            row["lifecycle_reason"] = lifecycle.reason
            row["status_uncertain"] = lifecycle.uncertain
            rows.append(row)
        return rows

    def _apply_wallet_hedge_controls(self, rows: list[dict]) -> None:
        groups: dict[tuple[str, str], list[dict]] = {}
        for row in rows:
            if not row.get("hedge_detection_required"):
                continue
            groups.setdefault(
                (
                    str(row.get("wallet_address") or "").lower(),
                    str(row.get("condition_id") or "").lower(),
                ),
                [],
            ).append(row)

        for group in groups.values():
            outcomes = {
                str(row.get("outcome") or "").strip().lower(): row for row in group
            }
            if len(outcomes) < 2:
                continue

            candidates = sorted(
                group,
                key=lambda row: (
                    _safe_float(row.get("shares")),
                    _safe_float(row.get("position_size_usd")),
                ),
                reverse=True,
            )
            leader = candidates[0]
            opponent = next(
                (
                    row
                    for row in candidates[1:]
                    if str(row.get("outcome") or "").strip().lower()
                    == str(leader.get("opposite_outcome") or "").strip().lower()
                ),
                None,
            )
            if opponent is None:
                continue
            leader_shares = _safe_float(leader.get("shares"))
            opposing_shares = _safe_float(opponent.get("shares"))
            net_shares = max(0.0, leader_shares - opposing_shares)
            net_cost_basis = net_shares * _safe_float(
                leader.get("average_entry_price")
            )
            actionable_dollars = _safe_float(
                leader.get("minimum_actionable_exposure_dollars")
            )
            if actionable_dollars <= 0:
                actionable_dollars = _safe_float(leader.get("wallet_base_unit")) * _safe_float(
                    leader.get("actionable_position_units"), 0.5
                )

            for row in group:
                other_exposure = max(
                    (
                        _safe_float(other.get("position_size_usd"))
                        for other in group
                        if other is not row
                    ),
                    default=0.0,
                )
                row["gross_position_size_usd"] = _safe_float(
                    row.get("position_size_usd")
                )
                row["opposing_exposure_usd"] = round(other_exposure, 6)
                row["wallet_hedge_status"] = "opposing_exposure_detected"

            for row in group:
                if row is leader:
                    continue
                row["signal_position_size_usd"] = 0.0
                row["net_directional_exposure_usd"] = 0.0
                row["net_directional_shares"] = 0.0
                row["signal_rejection_reason"] = (
                    row.get("signal_rejection_reason") or "HEDGED_WALLET_POSITION"
                )

            leader["signal_position_size_usd"] = round(net_cost_basis, 6)
            leader["net_directional_exposure_usd"] = round(net_cost_basis, 6)
            leader["net_directional_shares"] = round(net_shares, 8)
            if net_shares <= 0 or net_cost_basis < actionable_dollars:
                leader["wallet_hedge_status"] = "no_clear_directional_exposure"
                leader["signal_rejection_reason"] = (
                    leader.get("signal_rejection_reason")
                    or "NO_CLEAR_DIRECTIONAL_EXPOSURE"
                )
            else:
                leader["wallet_hedge_status"] = "directional_after_hedge"

    def _persist_positions(
        self,
        wallet: WalletEntry,
        current_rows: list[dict],
        previous_rows: dict[str, dict],
        closed_positions: list[dict],
        events: dict[str, dict],
        observed_open_keys: set[str] | None = None,
    ) -> list[dict]:
        now = _iso_now()
        current_by_key = {row["position_key"]: row for row in current_rows}
        closed_by_key = {
            position_key(position): position for position in closed_positions
        }
        output: list[dict] = []
        is_initial_wallet_scan = not previous_rows

        for key, row in current_by_key.items():
            previous = previous_rows.get(key)
            if previous:
                row["first_detected_at"] = previous.get("first_detected_at") or now
                row["last_changed_at"] = previous.get("last_changed_at") or now
                for event in self._detect_changes(previous, row, now):
                    if self._record_event(event):
                        row["last_changed_at"] = event["detected_at"]
            else:
                event = self._build_event(
                    "new_entry",
                    None,
                    row,
                    now,
                    {"message": "First detected open position"},
                )
                self._record_event(event, initial_scan=is_initial_wallet_scan)

            row["last_seen_at"] = now
            self.database.save_open_position(row)
            output.append(row)

        # Candidate rows are date-filtered before enrichment, but exit detection
        # must compare against every position returned by the wallet endpoint.
        observed_open_keys = (
            observed_open_keys
            if observed_open_keys is not None
            else set(current_by_key)
        )
        missing_keys = set(previous_rows) - observed_open_keys
        for key in missing_keys:
            previous = previous_rows[key]
            closed_match = closed_by_key.get(key)
            closed_snapshot = dict(previous)
            closed_snapshot["status"] = "closed"
            closed_snapshot["closed_at"] = now
            closed_snapshot["last_seen_at"] = now
            closed_snapshot["last_changed_at"] = now
            if closed_match:
                closed_snapshot["realized_pnl"] = round(
                    _safe_float(closed_match.get("realizedPnl")), 2
                )
                closed_snapshot["current_price"] = round(
                    _safe_float(closed_match.get("curPrice")), 4
                )
                closed_snapshot["current_price_cents"] = round(
                    _safe_float(closed_match.get("curPrice")) * 100, 2
                )
            event = self._build_event(
                "full_exit",
                previous,
                closed_snapshot,
                now,
                {"closed_position_found": bool(closed_match)},
            )
            self._record_event(event)
            self.database.close_position(closed_snapshot)

        return output

    def _record_event(self, event: dict, initial_scan: bool = False) -> bool:
        inserted = self.database.insert_event(event)
        if not inserted:
            return False
        if initial_scan and not self.settings.discord_notify_on_initial_scan:
            return True
        self.notifier.notify(event)
        return True

    def _detect_changes(
        self, previous: dict, current: dict, timestamp: str
    ) -> list[dict]:
        events: list[dict] = []
        size_delta = round(
            float(current["position_size_usd"])
            - float(previous.get("position_size_usd") or 0),
            2,
        )
        reported_size_delta = round(
            float(current.get("reported_initial_value") or current["position_size_usd"])
            - float(
                previous.get("reported_initial_value")
                or previous.get("position_size_usd")
                or 0
            ),
            2,
        )
        current_value_delta = round(
            float(current["current_value"]) - float(previous.get("current_value") or 0),
            2,
        )
        unrealized_delta = round(
            float(current["unrealized_pnl"])
            - float(previous.get("unrealized_pnl") or 0),
            2,
        )
        avg_price_delta = round(
            float(current["average_entry_price"])
            - float(previous.get("average_entry_price") or 0),
            4,
        )
        current_price_delta = round(
            float(current["current_price"]) - float(previous.get("current_price") or 0),
            4,
        )

        size_threshold = max(10.0, (previous.get("position_size_usd") or 0) * 0.05)
        reported_size_threshold = max(
            10.0,
            (
                previous.get("reported_initial_value")
                or previous.get("position_size_usd")
                or 0
            )
            * 0.05,
        )
        if (
            size_delta >= size_threshold
            or reported_size_delta >= reported_size_threshold
        ):
            events.append(
                self._build_event(
                    "size_increase",
                    previous,
                    current,
                    timestamp,
                    {
                        "delta_usd": reported_size_delta
                        if reported_size_delta >= reported_size_threshold
                        else size_delta,
                        "active_delta_usd": size_delta,
                    },
                )
            )
        elif (
            size_delta <= -size_threshold
            or reported_size_delta <= -reported_size_threshold
        ):
            events.append(
                self._build_event(
                    "size_decrease",
                    previous,
                    current,
                    timestamp,
                    {
                        "delta_usd": reported_size_delta
                        if reported_size_delta <= -reported_size_threshold
                        else size_delta,
                        "active_delta_usd": size_delta,
                    },
                )
            )

        if abs(avg_price_delta) >= 0.01:
            events.append(
                self._build_event(
                    "avg_price_change",
                    previous,
                    current,
                    timestamp,
                    {"delta": avg_price_delta},
                )
            )
        if abs(current_price_delta) >= 0.02:
            events.append(
                self._build_event(
                    "price_change",
                    previous,
                    current,
                    timestamp,
                    {"delta": current_price_delta},
                )
            )
        if abs(current_value_delta) >= max(
            25.0, (previous.get("current_value") or 0) * 0.1
        ):
            events.append(
                self._build_event(
                    "current_value_change",
                    previous,
                    current,
                    timestamp,
                    {"delta_usd": current_value_delta},
                )
            )
        if abs(unrealized_delta) >= max(
            25.0, (abs(previous.get("unrealized_pnl") or 0)) * 0.15, 25.0
        ):
            events.append(
                self._build_event(
                    "unrealized_pnl_change",
                    previous,
                    current,
                    timestamp,
                    {"delta_usd": unrealized_delta},
                )
            )

        return events

    def _build_event(
        self,
        event_type: str,
        previous: dict | None,
        current: dict,
        timestamp: str,
        extra: dict[str, Any],
    ) -> dict:
        payload = {
            "wallet_address": current["wallet_address"],
            "wallet_label": current["wallet_label"],
            "position_key": current["position_key"],
            "event_type": event_type,
            "detected_at": timestamp,
            "category": current.get("category"),
            "league": current.get("league"),
            "market_title": current.get("market_title"),
            "outcome": current.get("outcome"),
            "position_size_usd": current.get("position_size_usd"),
            "current_value": current.get("current_value"),
            "unrealized_pnl": current.get("unrealized_pnl"),
            "realized_pnl": current.get("realized_pnl"),
            "average_entry_price": current.get("average_entry_price"),
            "current_price": current.get("current_price"),
            "market_url": current.get("market_url"),
            "wallet_profile_url": current.get("wallet_profile_url"),
            "previous": previous,
            "current": current,
            **extra,
        }
        digest = hashlib.sha256(
            json.dumps(
                {
                    "wallet_address": payload["wallet_address"],
                    "position_key": payload["position_key"],
                    "event_type": payload["event_type"],
                    "position_size_usd": round(
                        float(payload.get("position_size_usd") or 0), 2
                    ),
                    "current_value": round(float(payload.get("current_value") or 0), 2),
                    "unrealized_pnl": round(
                        float(payload.get("unrealized_pnl") or 0), 2
                    ),
                    "realized_pnl": round(float(payload.get("realized_pnl") or 0), 2),
                    "average_entry_price": round(
                        float(payload.get("average_entry_price") or 0), 4
                    ),
                    "current_price": round(float(payload.get("current_price") or 0), 4),
                    "extra": extra,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        payload["event_hash"] = digest
        return payload

    def _position_matches_filters(self, row: dict) -> bool:
        if row.get("status") != "open":
            return False
        if self.settings.sports_only and not row.get("is_sports"):
            return False
        lifecycle_status = row.get("lifecycle_status")
        if lifecycle_status == "uncertain":
            LOGGER.warning(
                "Hiding uncertain position %s (%s): %s",
                row.get("position_key"),
                row.get("event_slug"),
                row.get("lifecycle_reason"),
            )
            return False
        if lifecycle_status not in {"upcoming", "live"}:
            return False
        resolution = row.get("resolution_time")
        if resolution:
            hours = hours_until_resolution(resolution)
            row["hours_to_resolution"] = hours
            if (
                row.get("lifecycle_status") == "upcoming"
                and hours is not None
                and hours > self.settings.resolve_hours
            ):
                return False
        return True

    def _build_unit_analysis(
        self, wallets: list[WalletEntry], positions: list[dict]
    ) -> list[dict]:
        results: list[dict] = []
        positions_by_wallet: dict[str, list[dict]] = {}
        for position in positions:
            positions_by_wallet.setdefault(position["wallet_address"], []).append(
                position
            )

        for wallet in wallets:
            events = self.database.get_events_for_wallet(wallet.address, limit=250)
            samples: list[float] = []
            for event in events:
                if not is_sports_category(event.get("category", "")):
                    continue
                if event["event_type"] == "new_entry":
                    samples.append(abs(float(event.get("position_size_usd") or 0)))
                elif event["event_type"] in {"size_increase", "size_decrease"}:
                    samples.append(abs(float(event.get("delta_usd") or 0)))
            for position in positions_by_wallet.get(wallet.address, []):
                if is_sports_category(position.get("category", "")):
                    samples.append(abs(float(position.get("position_size_usd") or 0)))

            estimate = estimate_unit_size(
                wallet.address, wallet.label, samples, wallet.base_unit
            )
            result = asdict(estimate)
            result.update(
                {
                    "display_address": wallet.display_address,
                    "top_category": wallet.top_category,
                    "top_category_display": wallet.top_category_display,
                    "top_categories": list(wallet.top_categories),
                    "sub_top_categories": list(wallet.sub_top_categories),
                    "top_category_ids": list(wallet.top_category_ids),
                    "sub_top_category_ids": list(wallet.sub_top_category_ids),
                    "primary_top_category_id": wallet.primary_top_category_id,
                    "top_category_source": wallet.top_category_source,
                    "top_category_verified_at": wallet.top_category_verified_at,
                    "bettor_type": wallet.bettor_type,
                    "trader_type": wallet.trader_type,
                    "selectivity": wallet.selectivity,
                    "selectivity_code": wallet.selectivity_code,
                    "selectivity_score": wallet.selectivity_score,
                    "hold_tendency": wallet.hold_tendency,
                    "hold_profile": wallet.hold_profile,
                    "copyability": wallet.copyability,
                    "copyability_code": wallet.copyability_code,
                    "execution_style": wallet.execution_style,
                    "execution_style_code": wallet.execution_style_code,
                    "general_strategy": wallet.general_strategy,
                    "minimum_position_units": wallet.minimum_position_units,
                    "actionable_position_units": wallet.actionable_position_units,
                    "typical_execution_tranche_dollars": wallet.typical_execution_tranche_dollars,
                    "minimum_actionable_exposure_dollars": wallet.minimum_actionable_exposure_dollars,
                    "requires_fill_aggregation": wallet.requires_fill_aggregation,
                    "hedge_detection_required": wallet.hedge_detection_required,
                }
            )
            results.append(result)

        results.sort(key=lambda item: item["wallet_label"].lower())
        return results

    def _build_consensus(
        self, positions: list[dict], trades: list[dict], unit_map: dict[str, dict]
    ) -> list[dict]:
        groups: dict[tuple[str, str], list[dict]] = {}
        for position in positions:
            groups.setdefault(
                (position["condition_id"], position["outcome"]), []
            ).append(position)

        trade_groups: dict[tuple[str, str], list[dict]] = {}
        for trade in trades:
            trade_groups.setdefault(
                (trade.get("current", {}) or {}).get("condition_id", None), []
            )

        consensus: list[dict] = []
        for (condition_id, outcome), group in groups.items():
            if len(group) < 2:
                continue
            combined_value = round(
                sum(float(position.get("current_value") or 0) for position in group), 2
            )
            combined_units = round(
                sum(
                    float(
                        amount_to_units(
                            position.get("position_size_usd") or 0,
                            unit_map.get(position["wallet_address"], {}).get(
                                "estimated_base_unit"
                            ),
                        )
                        or 0
                    )
                    for position in group
                ),
                2,
            )
            largest_holder = max(
                group,
                key=lambda position: float(position.get("position_size_usd") or 0),
            )
            earliest_entry = min(
                position.get("first_detected_at") for position in group
            )
            relevant_increases = [
                trade["detected_at"]
                for trade in trades
                if trade.get("event_type") == "size_increase"
                and trade.get("position_key")
                in {position["position_key"] for position in group}
                and trade.get("wallet_address")
                in {position["wallet_address"] for position in group}
            ]
            consensus.append(
                {
                    "condition_id": condition_id,
                    "market_title": group[0]["market_title"],
                    "outcome": outcome,
                    "category": group[0]["category"],
                    "league": group[0]["league"],
                    "wallet_count": len(group),
                    "combined_position_value": combined_value,
                    "combined_estimated_units": combined_units,
                    "average_entry_price": round(
                        sum(position["average_entry_price"] for position in group)
                        / len(group),
                        4,
                    ),
                    "current_price": round(
                        sum(position["current_price"] for position in group)
                        / len(group),
                        4,
                    ),
                    "wallet_names": [position["wallet_label"] for position in group],
                    "largest_holder": largest_holder["wallet_label"],
                    "earliest_entry_time": earliest_entry,
                    "most_recent_increase": max(relevant_increases)
                    if relevant_increases
                    else None,
                    "market_url": group[0]["market_url"],
                }
            )

        consensus.sort(
            key=lambda item: (
                -item["wallet_count"],
                -item["combined_position_value"],
                item["market_title"].lower(),
            )
        )
        return consensus

    def _enrich_positions(
        self,
        positions: list[dict],
        trades: list[dict],
        unit_map: dict[str, dict],
        consensus_map: dict[tuple[str, str], dict],
    ) -> list[dict]:
        visible_totals: dict[str, float] = {}
        sports_totals: dict[str, float] = {}

        for position in positions:
            visible_totals[position["wallet_address"]] = visible_totals.get(
                position["wallet_address"], 0.0
            ) + float(position.get("current_value") or 0)
            if is_sports_category(position.get("category", "")):
                sports_totals[position["wallet_address"]] = sports_totals.get(
                    position["wallet_address"], 0.0
                ) + float(position.get("current_value") or 0)

        output: list[dict] = []
        for position in positions:
            wallet_unit = unit_map.get(position["wallet_address"], {})
            estimated_units = amount_to_units(
                position.get("position_size_usd") or 0,
                wallet_unit.get("estimated_base_unit"),
            )
            signal_units = amount_to_units(
                position.get("signal_position_size_usd")
                if position.get("signal_position_size_usd") is not None
                else position.get("position_size_usd") or 0,
                wallet_unit.get("estimated_base_unit"),
            )
            position["estimated_base_unit"] = wallet_unit.get("estimated_base_unit")
            position["estimated_base_unit_label"] = wallet_unit.get(
                "estimated_base_unit_label"
            )
            position["estimated_units"] = estimated_units
            position["position_units"] = estimated_units
            position["signal_units"] = signal_units
            minimum_units = position.get("minimum_position_units")
            actionable_units = position.get("actionable_position_units")
            position["signal_tier"] = _wallet_signal_tier(
                signal_units, minimum_units, actionable_units
            )
            position["wallet_total_visible_value"] = round(
                visible_totals.get(position["wallet_address"], 0.0), 2
            )
            position["wallet_sports_visible_value"] = round(
                sports_totals.get(position["wallet_address"], 0.0), 2
            )
            position["tracked_wallets_same_side"] = consensus_map.get(
                (position["condition_id"], position["outcome"]), {}
            ).get("wallet_count", 1)
            increase_count = len(
                [
                    trade
                    for trade in trades
                    if trade.get("wallet_address") == position["wallet_address"]
                    and trade.get("position_key") == position["position_key"]
                    and trade.get("event_type") == "size_increase"
                ]
            )
            conviction = score_position(
                position,
                wallet_unit,
                position["tracked_wallets_same_side"],
                increase_count,
            )
            position["position_conviction_status"] = conviction.status
            position["position_conviction"] = conviction.score
            position["position_conviction_breakdown"] = conviction.breakdown
            output.append(position)

        output.sort(
            key=lambda item: (
                item["position_conviction"] is None,
                -(item["position_conviction"] or 0),
                -(item.get("position_size_usd") or 0),
            )
        )
        return output

    def _within_hours(self, timestamp: str | None, hours: int) -> bool:
        if not timestamp:
            return False
        try:
            parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        except ValueError:
            return False
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed >= _utc_now() - timedelta(hours=hours)

    def _build_overview(
        self,
        positions: list[dict],
        trades: list[dict],
        consensus: list[dict],
        status: dict,
    ) -> dict:
        new_trades_24h = len(
            [
                trade
                for trade in trades
                if trade["event_type"] == "new_entry"
                and self._within_hours(trade["detected_at"], 24)
            ]
        )
        exits_24h = len(
            [
                trade
                for trade in trades
                if trade["event_type"] == "full_exit"
                and self._within_hours(trade["detected_at"], 24)
            ]
        )
        return {
            "enabled_wallets": status["enabled_wallet_count"],
            "open_sports_positions": len(positions),
            "total_current_position_value": round(
                sum(
                    float(position.get("current_value") or 0) for position in positions
                ),
                2,
            ),
            "total_unrealized_pnl": round(
                sum(
                    float(position.get("unrealized_pnl") or 0) for position in positions
                ),
                2,
            ),
            "new_trades_last_24h": new_trades_24h,
            "exits_last_24h": exits_24h,
            "markets_with_consensus": len(consensus),
            "last_successful_refresh": status.get("last_successful_refresh"),
            "api_status": status.get("api_status"),
        }
