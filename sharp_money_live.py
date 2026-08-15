from __future__ import annotations

import copy
import logging
import math
import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from execution_providers import PROPHETX_LOGO_URL

LOGGER = logging.getLogger(__name__)


def _number(value, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _decimal_odds(selection: dict) -> float | None:
    value = selection.get("odds")
    if isinstance(value, dict):
        value = (
            value.get("decimal")
            or value.get("price")
            or value.get("best")
            or value.get("odds")
        )
    number = _number(value)
    if number > 1:
        return number
    american = _number(selection.get("american_odds"))
    if american >= 100:
        return 1 + american / 100
    if american <= -100:
        return 1 + 100 / abs(american)
    return None


def _american(decimal: float | None) -> int | None:
    if decimal is None or decimal <= 1:
        return None
    return (
        round((decimal - 1) * 100)
        if decimal >= 2
        else round(-100 / (decimal - 1))
    )


def _selection_books(value) -> list[list[dict]]:
    if not isinstance(value, list):
        return []
    books: list[list[dict]] = []
    for item in value:
        if isinstance(item, dict):
            books.append([item])
        elif isinstance(item, list):
            levels = [child for child in item if isinstance(child, dict)]
            if levels:
                books.append(levels)
    return books


def _markets_by_event(payload) -> dict[str, list[dict]]:
    if isinstance(payload, list):
        grouped: dict[str, list[dict]] = defaultdict(list)
        for market in payload:
            if isinstance(market, dict):
                grouped[str(market.get("event_id") or "")].append(market)
        return grouped
    if not isinstance(payload, dict):
        return {}
    nested = payload.get("markets")
    if isinstance(nested, list):
        return _markets_by_event(nested)
    source = nested if isinstance(nested, dict) else payload
    return {
        str(event_id): [row for row in rows if isinstance(row, dict)]
        for event_id, rows in source.items()
        if isinstance(rows, list)
    }


def _market_kind(name: str) -> str:
    lowered = name.lower()
    if "total" in lowered or "over/under" in lowered:
        return "game_total"
    if any(token in lowered for token in ("spread", "handicap", "run line")):
        return "spread"
    return "moneyline"


def _league(tournament: dict, event: dict) -> str:
    blob = " ".join(
        str(value or "")
        for value in (
            tournament.get("name"),
            tournament.get("sport"),
            event.get("league"),
            event.get("sport"),
        )
    ).upper()
    for candidate in (
        "WNBA",
        "MLB",
        "NBA",
        "NFL",
        "NHL",
        "NCAAF",
        "NCAAB",
        "MLS",
        "ATP",
        "WTA",
    ):
        if candidate in blob:
            return candidate
    return str(tournament.get("name") or event.get("league") or "Other")


def _team_name(value) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("display_name") or "").strip()
    return str(value or "").strip()


def _liquidity(level: dict) -> float:
    return _number(
        level.get("liquidity")
        or level.get("available_liquidity")
        or level.get("available_quantity")
        or level.get("quantity")
        or level.get("amount")
    )


class SharpMoneyCollector:
    """Local, read-only ProphetX flow monitor.

    The collector always boots paused. Cached GETs never call an upstream
    provider. Only ``play`` opens the request gate; ``pause`` closes it.
    """

    def __init__(
        self,
        prophetx_provider,
        odds_provider=None,
        *,
        poll_seconds: float = 1.0,
        comparison_seconds: float = 60.0,
        local_control: bool | None = None,
    ) -> None:
        self.prophetx = prophetx_provider
        self.odds_provider = odds_provider
        self.poll_seconds = max(1.0, float(poll_seconds))
        self.comparison_seconds = max(20.0, float(comparison_seconds))
        self.local_control = (
            not bool(os.getenv("VERCEL"))
            if local_control is None
            else bool(local_control)
        )
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self._started_at: str | None = None
        self._last_snapshot_at: str | None = None
        self._last_comparison_at: str | None = None
        self._last_error: str | None = None
        self._cycles = 0
        self._previous: dict[str, dict] = {}
        self._history: dict[str, deque] = defaultdict(lambda: deque(maxlen=90))
        self._signals: list[dict] = []
        self._comparisons: dict[str, list[dict]] = {}
        self._last_comparison_monotonic = 0.0

    def play(self) -> tuple[bool, str]:
        if not self.local_control:
            return False, "Live Sharp Money control is local-only."
        if self.prophetx is None:
            return False, "ProphetX is not configured."
        if hasattr(self.prophetx, "diagnostics"):
            diagnostics = self.prophetx.diagnostics()
            if not diagnostics.get("configured"):
                return (
                    False,
                    "Add PROPHETX_ACCESS_KEY and PROPHETX_SECRET_KEY before Play.",
                )
        with self._lock:
            self._running = True
            self._started_at = self._started_at or datetime.now(
                timezone.utc
            ).isoformat()
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._loop,
                    name="sharp-money-local-collector",
                    daemon=True,
                )
                self._thread.start()
        self._wake.set()
        return True, "ProphetX Sharp Money collector started."

    def pause(self) -> tuple[bool, str]:
        with self._lock:
            self._running = False
        self._wake.set()
        return True, "Collector paused. No new provider requests will begin."

    def close(self) -> None:
        self._stop.set()
        self._wake.set()

    def status(self) -> dict:
        with self._lock:
            running = self._running
            return {
                "schemaVersion": "sharp-money-live-v1",
                "mode": "live" if running else "paused",
                "running": running,
                "paused": not running,
                "localControl": self.local_control,
                "readOnly": True,
                "executionEnabled": False,
                "notificationsEnabled": False,
                "trackerWritesEnabled": False,
                "fabricatedData": False,
                "startedAt": self._started_at,
                "lastSnapshotAt": self._last_snapshot_at,
                "lastComparisonAt": self._last_comparison_at,
                "lastError": self._last_error,
                "cycles": self._cycles,
                "pollSeconds": self.poll_seconds,
                "comparisonSeconds": self.comparison_seconds,
                "signalCount": len(self._signals),
                "provider": (
                    self.prophetx.diagnostics()
                    if self.prophetx is not None
                    and hasattr(self.prophetx, "diagnostics")
                    else {"provider": "prophetx", "configured": False}
                ),
                "comparisonProvider": self._odds_diagnostics(),
            }

    def payload(self) -> dict:
        with self._lock:
            payload = self.status()
            payload["signals"] = copy.deepcopy(self._signals)
            return payload

    def refresh_once(self) -> list[dict]:
        """Run one read-only provider snapshot for scheduled consumers."""
        if self.prophetx is None:
            return []
        snapshot = self.prophetx.live_market_snapshot()
        signals = self._build_signals(snapshot)
        now = time.monotonic()
        if (
            self.odds_provider is not None
            and signals
            and now - self._last_comparison_monotonic >= self.comparison_seconds
        ):
            self._refresh_comparisons(signals)
            self._last_comparison_monotonic = now
        for signal in signals:
            signal["comparisonLines"] = copy.deepcopy(
                self._comparisons.get(signal["id"], [])
            )
        with self._lock:
            self._signals = signals
            self._cycles += 1
            self._last_snapshot_at = str(
                snapshot.get("observedAt")
                or datetime.now(timezone.utc).isoformat()
            )
            self._last_error = None
        return copy.deepcopy(signals)

    def _odds_diagnostics(self) -> dict:
        if self.odds_provider is None:
            return {"provider": "the_odds_api", "configured": False}
        if hasattr(self.odds_provider, "diagnostics"):
            return self.odds_provider.diagnostics()
        return {"provider": "the_odds_api", "configured": True}

    def _loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                running = self._running
            if not running:
                self._wake.wait()
                self._wake.clear()
                continue
            started = time.monotonic()
            try:
                self.refresh_once()
            except Exception:
                LOGGER.warning(
                    "Local Sharp Money collection cycle failed",
                    exc_info=True,
                )
                with self._lock:
                    self._last_error = (
                        "ProphetX refresh failed. Credentials, sandbox access, "
                        "and API connectivity should be checked."
                    )
            elapsed = time.monotonic() - started
            self._wake.wait(max(0.05, self.poll_seconds - elapsed))
            self._wake.clear()

    def _build_signals(self, snapshot: dict) -> list[dict]:
        tournaments = {
            str(row.get("id")): row
            for row in snapshot.get("tournaments") or []
            if isinstance(row, dict)
        }
        market_map = _markets_by_event(snapshot.get("markets"))
        rows: list[dict] = []
        current: dict[str, dict] = {}
        for event in snapshot.get("events") or []:
            if not isinstance(event, dict):
                continue
            event_id = str(event.get("event_id") or "")
            tournament = tournaments.get(str(event.get("tournament_id")), {})
            home = _team_name(event.get("home_team"))
            away = _team_name(event.get("away_team"))
            if not event_id or not home or not away:
                continue
            league = _league(tournament, event)
            for market in market_map.get(event_id, []):
                market_id = str(market.get("market_id") or market.get("id") or "")
                market_name = str(
                    market.get("name")
                    or market.get("market_type")
                    or market.get("type")
                    or "Moneyline"
                )
                selection_books = _selection_books(market.get("selections"))
                if len(selection_books) < 2:
                    continue
                selection_rows: list[dict] = []
                for levels in selection_books:
                    selection = levels[0]
                    selection_id = str(
                        selection.get("id")
                        or selection.get("selection_id")
                        or selection.get("strike_id")
                        or ""
                    )
                    name = str(selection.get("name") or "").strip()
                    decimal = _decimal_odds(selection)
                    liquidity = sum(_liquidity(level) for level in levels)
                    if not selection_id or not name or decimal is None:
                        continue
                    key = f"{event_id}:{market_id}:{selection_id}"
                    sample = {
                        "key": key,
                        "selectionId": selection_id,
                        "name": name,
                        "decimalOdds": decimal,
                        "americanOdds": _american(decimal),
                        "probability": 1 / decimal,
                        "liquidity": liquidity,
                        "line": (
                            selection.get("line")
                            if selection.get("line") is not None
                            else market.get("line")
                        ),
                        "levels": [
                            {
                                "americanOdds": _american(
                                    _decimal_odds(level)
                                ),
                                "decimalOdds": _decimal_odds(level),
                                "liquidity": _liquidity(level),
                            }
                            for level in levels
                            if _decimal_odds(level) is not None
                        ],
                    }
                    current[key] = sample
                    previous = self._previous.get(key)
                    probability_delta = (
                        sample["probability"] - previous["probability"]
                        if previous
                        else 0.0
                    )
                    liquidity_delta = (
                        liquidity - previous["liquidity"] if previous else 0.0
                    )
                    relative_depth = (
                        liquidity_delta / max(previous["liquidity"], 100.0)
                        if previous
                        else 0.0
                    )
                    pressure = probability_delta * 100 + max(
                        -relative_depth, 0.0
                    ) * 0.18
                    sample.update(
                        {
                            "probabilityDelta": probability_delta,
                            "liquidityDelta": liquidity_delta,
                            "pressure": pressure,
                        }
                    )
                    self._history[key].append(
                        {
                            "observedAt": snapshot.get("observedAt"),
                            "americanOdds": sample["americanOdds"],
                            "liquidity": liquidity,
                            "pressure": pressure,
                        }
                    )
                    selection_rows.append(sample)
                if len(selection_rows) < 2:
                    continue
                leader = max(
                    selection_rows,
                    key=lambda item: (
                        item["pressure"],
                        item["liquidity"],
                    ),
                )
                total_liquidity = sum(
                    item["liquidity"] for item in selection_rows
                )
                confidence = min(
                    99,
                    round(
                        45
                        + abs(leader["pressure"]) * 260
                        + min(total_liquidity / 10000, 25)
                    ),
                )
                signal_id = f"px:{event_id}:{market_id}:{leader['selectionId']}"
                rows.append(
                    {
                        "id": signal_id,
                        "provider": "ProphetX",
                        "providerKey": "prophetx",
                        "providerLogo": PROPHETX_LOGO_URL,
                        "sport": str(tournament.get("sport") or league),
                        "league": league,
                        "event": f"{away} vs. {home}",
                        "homeTeam": home,
                        "awayTeam": away,
                        "startsAt": event.get("start_time"),
                        "market": {
                            "id": market_id,
                            "name": market_name,
                            "kind": _market_kind(market_name),
                            "line": leader.get("line"),
                        },
                        "selection": leader["name"],
                        "americanOdds": leader["americanOdds"],
                        "decimalOdds": leader["decimalOdds"],
                        "liquidity": leader["liquidity"],
                        "totalLiquidity": total_liquidity,
                        "liquidityDelta": leader["liquidityDelta"],
                        "probabilityDelta": leader["probabilityDelta"],
                        "pressure": leader["pressure"],
                        "pressureLabel": (
                            "Flow detected"
                            if abs(leader["pressure"]) >= 0.01
                            else "Monitoring"
                        ),
                        "confidence": confidence,
                        "inferenceOnly": True,
                        "transport": "ProphetX REST snapshot",
                        "outcomes": selection_rows,
                        "history": list(self._history[leader["key"]]),
                        "comparisonLines": [],
                    }
                )
        self._previous = current
        return sorted(
            rows,
            key=lambda item: (
                abs(item["pressure"]),
                item["totalLiquidity"],
            ),
            reverse=True,
        )[:40]

    def _trade_for_signal(self, signal: dict) -> dict:
        kind = signal["market"]["kind"]
        market_type = {
            "moneyline": "Moneyline",
            "spread": "Spread",
            "game_total": "Total",
        }[kind]
        return {
            "id": signal["id"],
            "category": signal["sport"],
            "league": signal["league"],
            "event_date_et": signal["startsAt"],
            "event_title": signal["event"],
            "market_title": signal["market"]["name"],
            "sports_market_type": market_type,
            "outcome": signal["selection"],
            "line": signal["market"].get("line"),
            "recommended_amount": 100,
        }

    def _refresh_comparisons(self, signals: list[dict]) -> None:
        trades = [self._trade_for_signal(signal) for signal in signals[:16]]
        options = self.odds_provider.screen_options_for_trades(trades)
        comparisons: dict[str, list[dict]] = {}
        for signal in signals[:16]:
            rows = [
                option.to_dict()
                for option in options.get(signal["id"], [])
                if option.is_available and option.american_odds is not None
            ]
            rows.append(
                {
                    "providerName": "ProphetX",
                    "providerKey": "prophetx",
                    "displayOdds": (
                        f"+{signal['americanOdds']}"
                        if (signal["americanOdds"] or 0) > 0
                        else str(signal["americanOdds"])
                    ),
                    "americanOdds": signal["americanOdds"],
                    "availableLiquidity": signal["liquidity"],
                    "logoUrl": PROPHETX_LOGO_URL,
                    "isAvailable": True,
                    "matchingConfidence": "Exact",
                    "tooltip": "Direct ProphetX sandbox quote",
                }
            )
            rows.sort(
                key=lambda row: _number(row.get("americanOdds"), -100000),
                reverse=True,
            )
            comparisons[signal["id"]] = rows
        with self._lock:
            self._comparisons = comparisons
            self._last_comparison_at = datetime.now(timezone.utc).isoformat()


def build_sharp_money_collector(registry, settings) -> SharpMoneyCollector:
    providers = {
        str(provider.provider_key).lower(): provider
        for provider in getattr(registry, "providers", ())
    }
    return SharpMoneyCollector(
        providers.get("prophetx"),
        providers.get("the_odds_api"),
        poll_seconds=float(
            os.getenv("SHARP_MONEY_PROPHETX_POLL_SECONDS", "1")
        ),
        comparison_seconds=float(
            os.getenv("SHARP_MONEY_COMPARISON_SECONDS", "60")
        ),
    )
