from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from classification import classify_market, is_sports_category
from config import Settings
from database import TrackerDatabase
from discord_notifier import DiscordNotifier
from polymarket_client import PolymarketClient
from scoring import hours_until_resolution, score_position
from unit_analysis import amount_to_units, estimate_unit_size
from wallet_loader import WalletEntry, load_wallets

LOGGER = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


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


class TrackerService:
    def __init__(
        self,
        settings: Settings,
        client: PolymarketClient | None = None,
        database: TrackerDatabase | None = None,
        notifier: DiscordNotifier | None = None,
        auto_start: bool = True,
    ) -> None:
        self.settings = settings
        self.client = client or PolymarketClient(settings.request_timeout, settings.max_retries)
        self.database = database or TrackerDatabase(settings.database_path)
        self.notifier = notifier or DiscordNotifier.from_settings(settings)
        self._lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._started = False
        self._thread: threading.Thread | None = None
        self._cache = {
            "positions": [],
            "trades": [],
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

            if self.settings.dashboard_refresh <= 0:
                return

            self._thread = threading.Thread(target=self._refresh_loop, name="tracker-refresh", daemon=True)
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
            timestamp = status.get("last_successful_refresh") or status.get("last_refresh_attempt")

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

        status = self._empty_status()
        status["last_refresh_attempt"] = attempt_time
        status["enabled_wallet_count"] = len(loader.enabled_wallets)
        status["valid_wallet_count"] = len(loader.valid_wallets)
        status["invalid_wallet_count"] = len(loader.invalid_entries) + len(loader.file_errors)
        status["wallet_loader"] = loader.as_dict()
        status["wallets"] = wallet_payload
        status["warnings"] = loader.file_errors + [error["message"] for error in wallet_payload if error["status"] == "invalid"]

        if loader.file_errors:
            status["app_status"] = "degraded"

        if not loader.enabled_wallets:
            snapshot = {
                "positions": [],
                "trades": self.database.get_recent_events(),
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
        api_errors = fetch_results["errors"]
        status["api_errors"] = api_errors
        status["api_status"] = "ok" if not api_errors else ("degraded" if open_positions else "error")

        unique_event_slugs = [
            position.get("eventSlug")
            for positions in list(open_positions.values()) + list(closed_positions.values())
            for position in positions
            if position.get("eventSlug")
        ]
        events = self.client.get_events(unique_event_slugs)

        current_rows: list[dict] = []
        for wallet in loader.enabled_wallets:
            wallet_open = open_positions.get(wallet.address)
            if wallet_open is None:
                current_rows.extend(self.database.get_open_positions_for_wallet(wallet.address).values())
                continue

            previous_rows = self.database.get_open_positions_for_wallet(wallet.address)
            normalized_rows = self._normalize_positions(wallet, wallet_open, events)
            current_rows.extend(
                self._persist_positions(wallet, normalized_rows, previous_rows, closed_positions.get(wallet.address, []), events)
            )

        current_rows = [row for row in current_rows if self._position_matches_filters(row)]
        current_rows.sort(key=lambda row: (row.get("resolution_time") or "", -float(row.get("position_size_usd") or 0)))

        trades = self.database.get_recent_events(limit=250)
        unit_analysis = self._build_unit_analysis(loader.enabled_wallets, current_rows)
        unit_map = {entry["wallet_address"]: entry for entry in unit_analysis}
        consensus = self._build_consensus(current_rows, trades, unit_map)
        consensus_map = {
            (entry["condition_id"], entry["outcome"]): entry
            for entry in consensus
        }
        positions = self._enrich_positions(current_rows, trades, unit_map, consensus_map)
        overview = self._build_overview(positions, trades, consensus, status)

        success_time = _iso_now()
        status["last_successful_refresh"] = success_time
        status["position_count"] = len(positions)
        status["recent_trade_count"] = len([trade for trade in trades if self._within_hours(trade["detected_at"], 24)])
        status["overview"] = overview
        status["app_status"] = "ok" if status["api_status"] != "error" else "degraded"
        status["database"] = self.database.health()

        self.database.set_refresh_state("last_refresh_attempt", attempt_time)
        self.database.set_refresh_state("last_successful_refresh", success_time)
        self.database.set_refresh_state("api_status", status["api_status"])

        with self._lock:
            self._cache = {
                "positions": positions,
                "trades": trades,
                "consensus": consensus,
                "unit_analysis": unit_analysis,
                "wallets": wallet_payload,
                "status": status,
            }

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
                        "label": wallet.label,
                        "enabled": wallet.enabled,
                        "base_unit": wallet.base_unit,
                        "notes": wallet.notes,
                        "status": "enabled" if wallet.enabled else "disabled",
                        "short_address": shorten_wallet(wallet.address),
                        "profile_url": f"https://polymarket.com/profile/{wallet.address}",
                    }
                )
            else:
                payload.append(
                    {
                        "index": index,
                        "address": raw_entry.get("address"),
                        "label": raw_entry.get("label") or f"Trader {index + 1}",
                        "enabled": bool(raw_entry.get("enabled", True)),
                        "base_unit": raw_entry.get("base_unit"),
                        "notes": raw_entry.get("notes") or "",
                        "status": "invalid",
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

    def _fetch_wallet_data(self, wallets: list[WalletEntry]) -> dict[str, Any]:
        open_positions: dict[str, list[dict] | None] = {}
        closed_positions: dict[str, list[dict]] = {}
        errors: list[str] = []

        def fetch_wallet(wallet: WalletEntry) -> tuple[str, list[dict], list[dict]]:
            return (
                wallet.address,
                self.client.get_current_positions(wallet.address),
                self.client.get_closed_positions(wallet.address),
            )

        with ThreadPoolExecutor(max_workers=min(len(wallets), 8)) as executor:
            futures = {executor.submit(fetch_wallet, wallet): wallet for wallet in wallets}
            for future in as_completed(futures):
                wallet = futures[future]
                try:
                    address, current, closed = future.result()
                    open_positions[address] = current
                    closed_positions[address] = closed
                except Exception as exc:
                    LOGGER.warning("Failed wallet refresh for %s: %s", wallet.address, exc)
                    open_positions[wallet.address] = None
                    closed_positions[wallet.address] = []
                    errors.append(f"{wallet.label} ({wallet.address}): {exc}")

        return {"open_positions": open_positions, "closed_positions": closed_positions, "errors": errors}

    def _normalize_positions(self, wallet: WalletEntry, positions: list[dict], events: dict[str, dict]) -> list[dict]:
        rows: list[dict] = []
        for position in positions:
            event = events.get(position.get("eventSlug"))
            classification = classify_market(position, event)
            if self.settings.sports_only and not classification.is_sports:
                continue
            probability = _safe_float(position.get("curPrice"))
            if not within_odds_range(probability, self.settings.min_american_odds, self.settings.max_american_odds):
                continue

            size = _safe_float(position.get("size"))
            avg_price = _safe_float(position.get("avgPrice"))
            initial_value = _safe_float(position.get("initialValue") or position.get("totalBought") or size * avg_price)
            current_value = _safe_float(position.get("currentValue") or size * probability)
            realized_pnl = _safe_float(position.get("realizedPnl"))
            cash_pnl = _safe_float(position.get("cashPnl"))
            unrealized_pnl = cash_pnl - realized_pnl if cash_pnl else max(current_value - initial_value, 0.0 if current_value >= initial_value else current_value - initial_value)
            market_url = f"https://polymarket.com/event/{position.get('eventSlug')}" if position.get("eventSlug") else ""
            resolution_time = str(position.get("endDate") or "")
            profile = self.client.get_public_profile(wallet.address)
            profile_name = (profile or {}).get("name") or (profile or {}).get("pseudonym") or wallet.label

            rows.append(
                {
                    "wallet_address": wallet.address,
                    "wallet_label": wallet.label,
                    "wallet_display_name": profile_name,
                    "wallet_short_address": shorten_wallet(wallet.address),
                    "wallet_profile_url": f"https://polymarket.com/profile/{wallet.address}",
                    "position_key": position_key(position),
                    "condition_id": position.get("conditionId"),
                    "event_slug": position.get("eventSlug"),
                    "event_id": str(position.get("eventId") or ""),
                    "market_slug": position.get("slug"),
                    "market_title": position.get("title") or "",
                    "event_title": (event or {}).get("title") or position.get("title") or "",
                    "outcome": position.get("outcome") or "",
                    "opposite_outcome": position.get("oppositeOutcome") or "",
                    "category": classification.category,
                    "league": classification.league,
                    "is_sports": classification.is_sports,
                    "resolution_time": resolution_time,
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
                    "american_odds_value": american_odds_value_from_probability(probability),
                    "position_size_usd": round(initial_value, 2),
                    "current_value": round(current_value, 2),
                    "unrealized_pnl": round(unrealized_pnl, 2),
                    "realized_pnl": round(realized_pnl, 2),
                    "shares": round(size, 4),
                    "token_units": round(size, 4),
                    "market_url": market_url,
                    "status": "open",
                    "source": "current_positions",
                    "raw_position": position,
                    "event_tags": [tag.get("label") for tag in (event or {}).get("tags", [])],
                }
            )
        return rows

    def _persist_positions(
        self,
        wallet: WalletEntry,
        current_rows: list[dict],
        previous_rows: dict[str, dict],
        closed_positions: list[dict],
        events: dict[str, dict],
    ) -> list[dict]:
        now = _iso_now()
        current_by_key = {row["position_key"]: row for row in current_rows}
        closed_by_key = {
            position_key(position): position
            for position in closed_positions
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
                event = self._build_event("new_entry", None, row, now, {"message": "First detected open position"})
                self._record_event(event, initial_scan=is_initial_wallet_scan)

            row["last_seen_at"] = now
            self.database.save_open_position(row)
            output.append(row)

        missing_keys = set(previous_rows) - set(current_by_key)
        for key in missing_keys:
            previous = previous_rows[key]
            closed_match = closed_by_key.get(key)
            closed_snapshot = dict(previous)
            closed_snapshot["status"] = "closed"
            closed_snapshot["closed_at"] = now
            closed_snapshot["last_seen_at"] = now
            closed_snapshot["last_changed_at"] = now
            if closed_match:
                closed_snapshot["realized_pnl"] = round(_safe_float(closed_match.get("realizedPnl")), 2)
                closed_snapshot["current_price"] = round(_safe_float(closed_match.get("curPrice")), 4)
                closed_snapshot["current_price_cents"] = round(_safe_float(closed_match.get("curPrice")) * 100, 2)
            event = self._build_event("full_exit", previous, closed_snapshot, now, {"closed_position_found": bool(closed_match)})
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

    def _detect_changes(self, previous: dict, current: dict, timestamp: str) -> list[dict]:
        events: list[dict] = []
        size_delta = round(float(current["position_size_usd"]) - float(previous.get("position_size_usd") or 0), 2)
        current_value_delta = round(float(current["current_value"]) - float(previous.get("current_value") or 0), 2)
        unrealized_delta = round(float(current["unrealized_pnl"]) - float(previous.get("unrealized_pnl") or 0), 2)
        avg_price_delta = round(float(current["average_entry_price"]) - float(previous.get("average_entry_price") or 0), 4)
        current_price_delta = round(float(current["current_price"]) - float(previous.get("current_price") or 0), 4)

        if size_delta >= max(10.0, (previous.get("position_size_usd") or 0) * 0.05):
            events.append(self._build_event("size_increase", previous, current, timestamp, {"delta_usd": size_delta}))
        elif size_delta <= -max(10.0, (previous.get("position_size_usd") or 0) * 0.05):
            events.append(self._build_event("size_decrease", previous, current, timestamp, {"delta_usd": size_delta}))

        if abs(avg_price_delta) >= 0.01:
            events.append(self._build_event("avg_price_change", previous, current, timestamp, {"delta": avg_price_delta}))
        if abs(current_price_delta) >= 0.02:
            events.append(self._build_event("price_change", previous, current, timestamp, {"delta": current_price_delta}))
        if abs(current_value_delta) >= max(25.0, (previous.get("current_value") or 0) * 0.1):
            events.append(self._build_event("current_value_change", previous, current, timestamp, {"delta_usd": current_value_delta}))
        if abs(unrealized_delta) >= max(25.0, (abs(previous.get("unrealized_pnl") or 0)) * 0.15, 25.0):
            events.append(self._build_event("unrealized_pnl_change", previous, current, timestamp, {"delta_usd": unrealized_delta}))

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
                    "position_size_usd": round(float(payload.get("position_size_usd") or 0), 2),
                    "current_value": round(float(payload.get("current_value") or 0), 2),
                    "unrealized_pnl": round(float(payload.get("unrealized_pnl") or 0), 2),
                    "realized_pnl": round(float(payload.get("realized_pnl") or 0), 2),
                    "average_entry_price": round(float(payload.get("average_entry_price") or 0), 4),
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
        resolution = row.get("resolution_time")
        if resolution:
            hours = hours_until_resolution(resolution)
            row["hours_to_resolution"] = hours
            if hours is not None and (hours < 0 or hours > self.settings.resolve_hours):
                return False
        return True

    def _build_unit_analysis(self, wallets: list[WalletEntry], positions: list[dict]) -> list[dict]:
        results: list[dict] = []
        positions_by_wallet: dict[str, list[dict]] = {}
        for position in positions:
            positions_by_wallet.setdefault(position["wallet_address"], []).append(position)

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

            estimate = estimate_unit_size(wallet.address, wallet.label, samples, wallet.base_unit)
            results.append(asdict(estimate))

        results.sort(key=lambda item: item["wallet_label"].lower())
        return results

    def _build_consensus(self, positions: list[dict], trades: list[dict], unit_map: dict[str, dict]) -> list[dict]:
        groups: dict[tuple[str, str], list[dict]] = {}
        for position in positions:
            groups.setdefault((position["condition_id"], position["outcome"]), []).append(position)

        trade_groups: dict[tuple[str, str], list[dict]] = {}
        for trade in trades:
            trade_groups.setdefault((trade.get("current", {}) or {}).get("condition_id", None), [])

        consensus: list[dict] = []
        for (condition_id, outcome), group in groups.items():
            if len(group) < 2:
                continue
            combined_value = round(sum(float(position.get("current_value") or 0) for position in group), 2)
            combined_units = round(
                sum(
                    float(amount_to_units(position.get("position_size_usd") or 0, unit_map.get(position["wallet_address"], {}).get("estimated_base_unit")) or 0)
                    for position in group
                ),
                2,
            )
            largest_holder = max(group, key=lambda position: float(position.get("position_size_usd") or 0))
            earliest_entry = min(position.get("first_detected_at") for position in group)
            relevant_increases = [
                trade["detected_at"]
                for trade in trades
                if trade.get("event_type") == "size_increase"
                and trade.get("position_key") in {position["position_key"] for position in group}
                and trade.get("wallet_address") in {position["wallet_address"] for position in group}
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
                    "average_entry_price": round(sum(position["average_entry_price"] for position in group) / len(group), 4),
                    "current_price": round(sum(position["current_price"] for position in group) / len(group), 4),
                    "wallet_names": [position["wallet_label"] for position in group],
                    "largest_holder": largest_holder["wallet_label"],
                    "earliest_entry_time": earliest_entry,
                    "most_recent_increase": max(relevant_increases) if relevant_increases else None,
                    "market_url": group[0]["market_url"],
                }
            )

        consensus.sort(key=lambda item: (-item["wallet_count"], -item["combined_position_value"], item["market_title"].lower()))
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
            visible_totals[position["wallet_address"]] = visible_totals.get(position["wallet_address"], 0.0) + float(position.get("current_value") or 0)
            if is_sports_category(position.get("category", "")):
                sports_totals[position["wallet_address"]] = sports_totals.get(position["wallet_address"], 0.0) + float(position.get("current_value") or 0)

        output: list[dict] = []
        for position in positions:
            wallet_unit = unit_map.get(position["wallet_address"], {})
            estimated_units = amount_to_units(position.get("position_size_usd") or 0, wallet_unit.get("estimated_base_unit"))
            position["estimated_base_unit"] = wallet_unit.get("estimated_base_unit")
            position["estimated_base_unit_label"] = wallet_unit.get("estimated_base_unit_label")
            position["estimated_units"] = estimated_units
            position["wallet_total_visible_value"] = round(visible_totals.get(position["wallet_address"], 0.0), 2)
            position["wallet_sports_visible_value"] = round(sports_totals.get(position["wallet_address"], 0.0), 2)
            position["tracked_wallets_same_side"] = consensus_map.get((position["condition_id"], position["outcome"]), {}).get("wallet_count", 1)
            increase_count = len(
                [
                    trade
                    for trade in trades
                    if trade.get("wallet_address") == position["wallet_address"]
                    and trade.get("position_key") == position["position_key"]
                    and trade.get("event_type") == "size_increase"
                ]
            )
            conviction = score_position(position, wallet_unit, position["tracked_wallets_same_side"], increase_count)
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

    def _build_overview(self, positions: list[dict], trades: list[dict], consensus: list[dict], status: dict) -> dict:
        new_trades_24h = len([trade for trade in trades if trade["event_type"] == "new_entry" and self._within_hours(trade["detected_at"], 24)])
        exits_24h = len([trade for trade in trades if trade["event_type"] == "full_exit" and self._within_hours(trade["detected_at"], 24)])
        return {
            "enabled_wallets": status["enabled_wallet_count"],
            "open_sports_positions": len(positions),
            "total_current_position_value": round(sum(float(position.get("current_value") or 0) for position in positions), 2),
            "total_unrealized_pnl": round(sum(float(position.get("unrealized_pnl") or 0) for position in positions), 2),
            "new_trades_last_24h": new_trades_24h,
            "exits_last_24h": exits_24h,
            "markets_with_consensus": len(consensus),
            "last_successful_refresh": status.get("last_successful_refresh"),
            "api_status": status.get("api_status"),
        }
