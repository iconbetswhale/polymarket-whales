from __future__ import annotations

import copy
import logging
import math
import os
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from execution_providers import PROPHETX_LOGO_URL
from the_odds_api_provider import normalize_the_odds_api_events

LOGGER = logging.getLogger(__name__)

ORDERBOOK_BOOK_NAMES = {
    "prophetx": "ProphetX",
    "novig": "NoVIG",
    "polymarket": "Polymarket",
    "kalshi": "Kalshi",
    "pinnacle": "Pinnacle",
    "fanduel": "FanDuel",
    "draftkings": "DraftKings",
    "betmgm": "BetMGM",
    "caesars": "Caesars",
    "betonline": "BetOnline",
}
ORDERBOOK_BOOK_LOGOS = {
    "prophetx": "/static/assets/providers/prophetx.ico",
    "novig": "/static/assets/providers/novig.png",
    "polymarket": "/static/assets/sportsbooks/polymarket.png",
    "kalshi": "/static/assets/providers/kalshi.png",
    "pinnacle": "/static/assets/providers/pinnacle.png",
    "fanduel": "/static/assets/sportsbooks/fanduel.png",
    "draftkings": "/static/assets/sportsbooks/draftkings.png",
    "betmgm": "/static/assets/sportsbooks/betmgm.png",
    "caesars": "/static/assets/sportsbooks/caesars.png",
    "betonline": "/static/assets/sportsbooks/betonline.png",
}

SHARP_CONSENSUS_BOOKS = {
    "betonline",
    "circasports",
    "lowvig",
    "novig",
    "pinnacle",
    "prophetx",
}
NON_RETAIL_MARKET_BOOKS = SHARP_CONSENSUS_BOOKS | {
    "4cx",
    "fourcx",
    "kalshi",
    "polymarket",
}


class OddsComparisonFallback:
    """Prefer OddsEngine while preserving the existing comparison fallback."""

    def __init__(self, providers) -> None:
        self.providers = tuple(
            provider
            for provider in providers
            if provider is not None and getattr(provider, "api_key", None)
        )

    def diagnostics(self) -> dict:
        if not self.providers:
            return {"provider": "odds_comparison", "configured": False}
        payload = dict(self.providers[0].diagnostics())
        payload["fallbacks"] = [
            provider.provider_key for provider in self.providers[1:]
        ]
        return payload

    def screen_options_for_trades(self, trades: list[dict]) -> dict:
        for provider in self.providers:
            try:
                return provider.screen_options_for_trades(trades)
            except Exception:
                LOGGER.warning(
                    "Sharp Money comparison provider %s failed",
                    provider.provider_key,
                )
        return {}


def _number(value, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _decimal_odds(selection: dict) -> float | None:
    value = (
        selection.get("odds")
        if selection.get("odds") is not None
        else selection.get("price")
        if selection.get("price") is not None
        else selection.get("adjusted_price")
    )
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


def _book_key(value: object) -> str:
    normalized = "".join(
        character
        for character in str(value or "").lower()
        if character.isalnum()
    )
    for prefix in ("oddsengine", "oddsapi"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    return {
        "prophetexchange": "prophetx",
        "betonlineag": "betonline",
        "draftkingssportsbook": "draftkings",
        "hardrockbet": "hardrock",
    }.get(normalized, normalized)


def _decimal_from_american(value: object) -> float | None:
    american = _number(value)
    if american >= 100:
        return 1 + american / 100
    if american <= -100:
        return 1 + 100 / abs(american)
    return None


def _orderbook_levels(book: dict) -> list[dict]:
    rows = []
    for level in book.get("order_book") or []:
        if not isinstance(level, dict):
            continue
        raw_odds = _number(level.get("odds"))
        decimal = (
            raw_odds
            if 1 < raw_odds < 100
            else _decimal_from_american(raw_odds)
        )
        american = _american(decimal)
        if american is None:
            continue
        rows.append(
            {
                "americanOdds": american,
                "decimalOdds": decimal,
                "liquidity": _liquidity(level),
            }
        )
    return rows


def _book_liquidity(book: dict) -> float:
    explicit = _number(
        book.get("total_liquidity")
        if book.get("total_liquidity") is not None
        else book.get("liquidity")
    )
    if explicit > 0:
        return explicit
    return sum(row["liquidity"] for row in _orderbook_levels(book))


def _quoted_book_liquidity(book: dict) -> float:
    """Return executable dollars at the displayed exchange price.

    ``total_liquidity`` can include worse prices deeper in the book. Crossed
    market Sharp Money must use only the dollars available at the quoted line.
    """
    explicit = _number(book.get("liquidity"))
    if explicit > 0:
        return explicit
    levels = _orderbook_levels(book)
    return levels[0]["liquidity"] if levels else 0.0


def _sharp_side_liquidity(side: dict) -> tuple[float, dict[str, float]]:
    sources: dict[str, float] = {}
    for raw_key, raw_book in (side.get("books") or {}).items():
        key = _book_key(raw_key)
        if key not in {"novig", "prophetx"} or not isinstance(raw_book, dict):
            continue
        value = _quoted_book_liquidity(raw_book)
        if value > 0:
            sources[key] = value
    return sum(sources.values()), sources


def _crossed_market_liquidity(comparisons: list[dict]) -> dict | None:
    """Find the retail/sharp cross and its executable exchange liquidity.

    The recommended bet is the best retail price. Liquidity comes from the
    equal-and-opposite NoVIG/ProphetX quotes that individually cross it.
    Liquidity on the recommended exchange side is not subtracted: it is a
    different executable quote, not a matched-position balance.
    """
    retail = [
        row
        for row in comparisons
        if _book_key(row.get("providerKey")) not in NON_RETAIL_MARKET_BOOKS
        and _decimal_from_american(row.get("americanOdds")) is not None
    ]
    if not retail:
        return None
    best_retail = max(
        retail,
        key=lambda row: _number(row.get("americanOdds"), -100000),
    )
    retail_decimal = _decimal_from_american(best_retail.get("americanOdds"))
    if retail_decimal is None:
        return None
    sources: dict[str, float] = {}
    sharp_prices: dict[str, int] = {}
    best_implied_sum: float | None = None
    for row in comparisons:
        key = _book_key(row.get("providerKey"))
        if key not in {"novig", "prophetx"}:
            continue
        opposite_decimal = _decimal_from_american(
            row.get("oppositeAmericanOdds")
        )
        liquidity = _number(row.get("oppositeAvailableLiquidity"))
        if opposite_decimal is None or liquidity <= 0:
            continue
        implied_sum = (1 / retail_decimal) + (1 / opposite_decimal)
        if implied_sum >= 1:
            continue
        sources[key] = liquidity
        sharp_prices[key] = round(_number(row.get("oppositeAmericanOdds")))
        if best_implied_sum is None or implied_sum < best_implied_sum:
            best_implied_sum = implied_sum
    if not sources or best_implied_sum is None:
        return None
    return {
        "liquidity": sum(sources.values()),
        "sources": sources,
        "sharpPrices": sharp_prices,
        "retailBook": _book_key(best_retail.get("providerKey")),
        "retailOdds": round(_number(best_retail.get("americanOdds"))),
        "roiPercent": (1 / best_implied_sum - 1) * 100,
    }


def _net_exchange_liquidity(comparisons: list[dict]) -> dict | None:
    """Return the positive two-sided liquidity imbalance for a selection.

    Sharp Money is directional order-book pressure, not sportsbook volume.
    For each direct exchange, executable dollars on the selected side are
    combined and executable dollars on the equal-and-opposite side are
    subtracted. A market is emitted only for the positive direction, so the
    same liquidity cannot be counted on both sides.
    """
    retail = [
        row
        for row in comparisons
        if _book_key(row.get("providerKey")) not in NON_RETAIL_MARKET_BOOKS
        and _decimal_from_american(row.get("americanOdds")) is not None
    ]
    best_retail = (
        max(
            retail,
            key=lambda row: _number(row.get("americanOdds"), -100000),
        )
        if retail
        else None
    )
    selected_total = 0.0
    opposite_total = 0.0
    sources: dict[str, float] = {}
    selected_sources: dict[str, float] = {}
    opposite_sources: dict[str, float] = {}
    selected_prices: dict[str, int] = {}
    opposite_prices: dict[str, int] = {}
    for row in comparisons:
        key = _book_key(row.get("providerKey"))
        if key not in {"novig", "prophetx"}:
            continue
        selected = max(0.0, _number(row.get("availableLiquidity")))
        opposite = max(0.0, _number(row.get("oppositeAvailableLiquidity")))
        if selected <= 0 and opposite <= 0:
            continue
        selected_total += selected
        opposite_total += opposite
        selected_sources[key] = selected
        opposite_sources[key] = opposite
        sources[key] = selected - opposite
        selected_price = _number(row.get("americanOdds"))
        opposite_price = _number(row.get("oppositeAmericanOdds"))
        if _decimal_from_american(selected_price) is not None:
            selected_prices[key] = round(selected_price)
        if _decimal_from_american(opposite_price) is not None:
            opposite_prices[key] = round(opposite_price)
    net = selected_total - opposite_total
    if net <= 0:
        return None
    return {
        "liquidity": net,
        "selectedLiquidity": selected_total,
        "oppositeLiquidity": opposite_total,
        "sources": sources,
        "selectedSources": selected_sources,
        "oppositeSources": opposite_sources,
        "sharpPrices": selected_prices,
        "oppositeSharpPrices": opposite_prices,
        "retailBook": (
            _book_key(best_retail.get("providerKey"))
            if best_retail is not None
            else None
        ),
        "retailOdds": (
            round(_number(best_retail.get("americanOdds")))
            if best_retail is not None
            else None
        ),
    }


def _side_name(side: dict, market: dict) -> str:
    side_key = str(side.get("side") or "").upper()
    line = (
        side.get("line")
        if side.get("line") is not None
        else market.get("line")
    )
    if side_key == "HOME":
        return str(market.get("home_team") or "Home").strip()
    if side_key == "AWAY":
        return str(market.get("away_team") or "Away").strip()
    if side_key in {"OVER", "UNDER"}:
        entity = str(market.get("entity_name") or "").strip()
        selection = (
            f"{side_key.title()} {line}"
            if line is not None
            else side_key.title()
        )
        return f"{entity} · {selection}" if entity else selection
    return side_key.title() or "Selection"


def _side_book(
    side: dict, target: str
) -> tuple[str, dict] | tuple[None, None]:
    for raw_key, value in (side.get("books") or {}).items():
        if isinstance(value, dict) and _book_key(raw_key) == target:
            return str(raw_key), value
    return None, None


class SharpMoneyCollector:
    """Read-only exchange-depth flow monitor.

    Direct ProphetX collection keeps the existing local Play/Pause gate.
    OddsEngine's materialized order-book endpoint refreshes automatically on
    serverless reads, with a process cache and an edge-cache-friendly cadence.
    """

    def __init__(
        self,
        prophetx_provider,
        odds_provider=None,
        *,
        fallback_source=None,
        poll_seconds: float = 1.0,
        comparison_seconds: float = 60.0,
        automatic_refresh_seconds: float = 30.0,
        advanced_orderbook_enabled: bool = False,
        novig_provider=None,
        local_control: bool | None = None,
    ) -> None:
        self.prophetx = prophetx_provider
        self.fallback_source = fallback_source
        self._active_source = prophetx_provider
        self.odds_provider = odds_provider
        self.poll_seconds = max(1.0, float(poll_seconds))
        self.comparison_seconds = max(20.0, float(comparison_seconds))
        self.automatic_refresh_seconds = max(
            20.0, float(automatic_refresh_seconds)
        )
        self.advanced_orderbook_enabled = bool(advanced_orderbook_enabled)
        self.novig_provider = novig_provider
        self.local_control = (
            not bool(os.getenv("VERCEL"))
            if local_control is None
            else bool(local_control)
        )
        self._lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self._started_at: str | None = None
        self._last_snapshot_at: str | None = None
        self._last_comparison_at: str | None = None
        self._last_error: str | None = None
        self._signal_mode = "order_book"
        self._cycles = 0
        self._previous: dict[str, dict] = {}
        self._history: dict[str, deque] = defaultdict(lambda: deque(maxlen=90))
        self._signals: list[dict] = []
        self._comparisons: dict[str, list[dict]] = {}
        self._last_comparison_monotonic = 0.0
        self._last_refresh_monotonic = 0.0

    @staticmethod
    def _configured(provider) -> bool:
        if provider is None:
            return False
        if hasattr(provider, "diagnostics"):
            return bool(provider.diagnostics().get("configured"))
        return True

    def _automatic(self) -> bool:
        if self.local_control:
            return False
        return any(
            self._configured(provider)
            and (
                hasattr(provider, "sharp_money_quote_snapshot")
                or hasattr(provider, "sharp_money_snapshot")
                or hasattr(provider, "sharp_money_direct_snapshot")
                or hasattr(provider, "live_market_snapshot")
            )
            for provider in (
                self.prophetx,
                self.fallback_source,
                self.novig_provider,
            )
        )

    def _orderbook_error_message(self, exc: Exception) -> str:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        if status == 401:
            return "OddsEngine rejected the API key (HTTP 401)."
        if status == 403:
            if not self.advanced_orderbook_enabled:
                return "OddsEngine rejected Sharp Money price-feed access (HTTP 403)."
            return (
                "OddsEngine rejected Advanced order-book access (HTTP 403). "
                "Confirm this API key includes the Advanced plan."
            )
        if status == 429:
            return (
                "OddsEngine order-book rate limit reached (HTTP 429)."
                if self.advanced_orderbook_enabled
                else "OddsEngine price-feed rate limit reached (HTTP 429)."
            )
        if status is not None:
            feed = "order-book" if self.advanced_orderbook_enabled else "price-feed"
            return f"OddsEngine {feed} request failed (HTTP {status})."
        feed = "order-book" if self.advanced_orderbook_enabled else "price-feed"
        return f"OddsEngine {feed} request failed before an HTTP response."

    def play(self) -> tuple[bool, str]:
        if not self.local_control:
            if self._automatic():
                return False, "Sharp Money order-book refresh is automatic."
            return False, "Live Sharp Money control is local-only."
        if self.prophetx is None:
            return False, "No Sharp Money depth source is configured."
        if hasattr(self.prophetx, "diagnostics"):
            diagnostics = self.prophetx.diagnostics()
            if not diagnostics.get("configured"):
                return (
                    False,
                    "Add an OddsEngine or ProphetX depth credential before Play.",
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
        return True, "Sharp Money order-book collector started."

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
            automatic = self._automatic()
            running = self._running or automatic
            source = self._active_source or self.prophetx
            source_diagnostics = {}
            for provider in (
                self.prophetx,
                self.fallback_source,
                self.novig_provider,
            ):
                if provider is None or not hasattr(provider, "diagnostics"):
                    continue
                key = str(getattr(provider, "provider_key", "source"))
                try:
                    source_diagnostics[key] = provider.diagnostics()
                except Exception:
                    source_diagnostics[key] = {
                        "provider": key,
                        "configured": False,
                        "status": "diagnostic unavailable",
                    }
            return {
                "schemaVersion": "sharp-money-live-v1",
                "mode": "live" if running else "paused",
                "running": running,
                "paused": not running,
                "automatic": automatic,
                "advancedOrderBookEnabled": self.advanced_orderbook_enabled,
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
                "signalMode": self._signal_mode,
                "cycles": self._cycles,
                "pollSeconds": self.poll_seconds,
                "comparisonSeconds": self.comparison_seconds,
                "refreshSeconds": (
                    self.automatic_refresh_seconds
                    if automatic
                    else self.poll_seconds
                ),
                "signalCount": len(self._signals),
                "provider": (
                    source.diagnostics()
                    if source is not None and hasattr(source, "diagnostics")
                    else {"provider": "orderbook", "configured": False}
                ),
                "sourceFallbacks": [
                    provider.provider_key
                    for provider in (self.fallback_source,)
                    if provider is not None
                    and getattr(provider, "provider_key", None)
                ],
                "sourceDiagnostics": source_diagnostics,
                "depthProviders": sorted(
                    {
                        ORDERBOOK_BOOK_NAMES.get(key, key.title())
                        for signal in self._signals
                        for key in (signal.get("liquiditySources") or {})
                    }
                ),
                "comparisonProvider": self._odds_diagnostics(),
            }

    def payload(self, *, refresh_if_stale: bool = False) -> dict:
        if refresh_if_stale and self._automatic():
            self._refresh_automatic_if_stale()
        with self._lock:
            payload = self.status()
            payload["signals"] = copy.deepcopy(self._signals)
            return payload

    def _refresh_automatic_if_stale(self) -> None:
        now = time.monotonic()
        if (
            self._last_refresh_monotonic
            and now - self._last_refresh_monotonic
            < self.automatic_refresh_seconds
        ):
            return
        if not self._refresh_lock.acquire(blocking=False):
            return
        try:
            now = time.monotonic()
            if (
                self._last_refresh_monotonic
                and now - self._last_refresh_monotonic
                < self.automatic_refresh_seconds
            ):
                return
            try:
                self.refresh_once()
            except Exception as exc:
                LOGGER.warning(
                    "Automatic Sharp Money order-book refresh failed: %s",
                    type(exc).__name__,
                )
                with self._lock:
                    self._last_error = self._orderbook_error_message(exc)
                    self._last_refresh_monotonic = time.monotonic()
        finally:
            self._refresh_lock.release()

    def refresh_once(self) -> list[dict]:
        """Run one read-only provider snapshot for scheduled consumers."""
        if (
            self.prophetx is None
            and self.fallback_source is None
            and self.novig_provider is None
        ):
            return []
        source, source_kind, snapshot = self._read_source_snapshot()
        if source_kind == "odds_engine_orderbook":
            signals = self._build_oddsengine_signals(snapshot)
        elif source_kind == "odds_engine_quotes":
            signals = self._build_oddsengine_quote_signals(snapshot)
            direct_signals = self._enrich_quote_signals_with_novig(signals)
            if direct_signals:
                signals = direct_signals
                source_kind = "direct_novig_quotes"
        elif source_kind == "novig_direct":
            signals = self._build_novig_direct_signals(snapshot)
        else:
            signals = self._build_signals(snapshot)
        now = time.monotonic()
        direct_orderbook = source_kind not in {
            "odds_engine_orderbook",
            "odds_engine_quotes",
        }
        if (
            self.odds_provider is not None
            and signals
            and direct_orderbook
            and source_kind not in {"direct_novig_quotes", "novig_direct"}
            and now - self._last_comparison_monotonic >= self.comparison_seconds
        ):
            self._refresh_comparisons(signals)
            self._last_comparison_monotonic = now
        for signal in signals:
            if not signal.get("comparisonLines"):
                signal["comparisonLines"] = copy.deepcopy(
                    self._comparisons.get(signal["id"], [])
                )
        if direct_orderbook and (
            self.odds_provider is not None
            or source_kind == "direct_novig_quotes"
        ):
            signals = self._finalize_direct_signals(signals)
        with self._lock:
            self._active_source = source
            self._signals = signals
            self._cycles += 1
            self._last_snapshot_at = str(
                snapshot.get("observedAt")
                or (snapshot.get("meta") or {}).get("updated_at")
                or datetime.now(timezone.utc).isoformat()
            )
            if source_kind == "odds_engine_orderbook":
                self._last_comparison_at = self._last_snapshot_at
            elif source_kind == "odds_engine_quotes":
                self._last_comparison_at = self._last_snapshot_at
            elif source_kind == "direct_novig_quotes":
                self._last_comparison_at = self._last_snapshot_at
            self._signal_mode = {
                "odds_engine_orderbook": "order_book",
                "odds_engine_quotes": "quote_consensus",
            }.get(source_kind, "direct_order_book")
            self._last_error = None
            self._last_refresh_monotonic = time.monotonic()
        return copy.deepcopy(signals)

    def _read_source_snapshot(self):
        last_error: Exception | None = None
        quote_fallbacks = []
        for provider in (self.prophetx, self.fallback_source):
            try:
                if not self._configured(provider):
                    continue
                if (
                    hasattr(provider, "sharp_money_quote_snapshot")
                    and not self.advanced_orderbook_enabled
                ):
                    return (
                        provider,
                        "odds_engine_quotes",
                        provider.sharp_money_quote_snapshot(limit=40),
                    )
                if (
                    self.advanced_orderbook_enabled
                    and hasattr(provider, "sharp_money_snapshot")
                ):
                    try:
                        return (
                            provider,
                            "odds_engine_orderbook",
                            provider.sharp_money_snapshot(limit=40),
                        )
                    except Exception as exc:
                        status = getattr(
                            getattr(exc, "response", None), "status_code", None
                        )
                        last_error = exc
                        if hasattr(provider, "sharp_money_quote_snapshot"):
                            quote_fallbacks.append(provider)
                        LOGGER.info(
                            "OddsEngine Advanced depth unavailable (HTTP %s); "
                            "trying direct exchange order books",
                            status if status is not None else "n/a",
                        )
                        continue
                if hasattr(provider, "sharp_money_quote_snapshot"):
                    return (
                        provider,
                        "odds_engine_quotes",
                        provider.sharp_money_quote_snapshot(limit=40),
                    )
                return provider, "prophetx_rest", provider.live_market_snapshot()
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                previous_status = getattr(
                    getattr(last_error, "response", None), "status_code", None
                )
                if last_error is None or status is not None or previous_status is None:
                    last_error = exc
                LOGGER.warning(
                    "Sharp Money source %s failed (%s, HTTP %s); trying fallback",
                    getattr(provider, "provider_key", "unknown"),
                    type(exc).__name__,
                    status if status is not None else "n/a",
                )
        for provider in quote_fallbacks:
            try:
                return (
                    provider,
                    "odds_engine_quotes",
                    provider.sharp_money_quote_snapshot(limit=40),
                )
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                previous_status = getattr(
                    getattr(last_error, "response", None), "status_code", None
                )
                if last_error is None or status is not None or previous_status is None:
                    last_error = exc
                LOGGER.warning(
                    "Sharp Money exact-price fallback %s failed (%s, HTTP %s)",
                    getattr(provider, "provider_key", "unknown"),
                    type(exc).__name__,
                    status if status is not None else "n/a",
                )
        direct_novig = self.novig_provider
        if (
            direct_novig is not None
            and bool(getattr(direct_novig, "configured", False))
            and hasattr(direct_novig, "sharp_money_direct_snapshot")
        ):
            try:
                snapshot = direct_novig.sharp_money_direct_snapshot(limit=40)
                if snapshot.get("snapshots"):
                    return direct_novig, "novig_direct", snapshot
            except Exception as exc:
                last_error = exc
                LOGGER.warning(
                    "Direct NoVIG Sharp Money fallback failed (%s)",
                    type(exc).__name__,
                )
        if last_error is not None:
            raise last_error
        return self.prophetx, "unconfigured", {}

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
                        "Sharp Money depth refresh failed. Credentials, plan "
                        "access, and API connectivity should be checked."
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
                        or selection.get("outcome_id")
                        or selection.get("strike_id")
                        or selection.get("line_id")
                        or ""
                    )
                    name = str(selection.get("name") or "").strip()
                    decimal = _decimal_odds(selection)
                    # Only dollars executable at the displayed top price count
                    # toward crossed liquidity. Worse-price depth remains in
                    # the detail ladder but is not added to the headline.
                    liquidity = sum(
                        _liquidity(level)
                        for level in levels
                        if decimal is not None
                        and _decimal_odds(level) is not None
                        and abs(_decimal_odds(level) - decimal) < 1e-9
                    )
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
                            else selection.get("strike")
                            if selection.get("strike") is not None
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
                # Sharp Money requires an unambiguous equal-and-opposite side.
                # Three-way markets cannot be represented by this protocol.
                if len(selection_rows) != 2:
                    continue
                total_liquidity = sum(
                    item["liquidity"] for item in selection_rows
                )
                for selected, opposing in (
                    (selection_rows[0], selection_rows[1]),
                    (selection_rows[1], selection_rows[0]),
                ):
                    # The displayed opportunity is the retail side. Exchange
                    # liquidity belongs to the equal-and-opposite side.
                    confidence = min(
                        99,
                        round(
                            45
                            + abs(opposing["pressure"]) * 260
                            + min(opposing["liquidity"] / 10000, 25)
                        ),
                    )
                    signal_id = (
                        f"px:{event_id}:{market_id}:{selected['selectionId']}"
                    )
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
                                "line": selected.get("line"),
                            },
                            "selection": selected["name"],
                            "selectionId": selected["selectionId"],
                            "oppositeSelection": copy.deepcopy(opposing),
                            "americanOdds": selected["americanOdds"],
                            "decimalOdds": selected["decimalOdds"],
                            "liquidity": opposing["liquidity"],
                            "totalLiquidity": total_liquidity,
                            "liquidityDelta": opposing["liquidityDelta"],
                            "probabilityDelta": opposing["probabilityDelta"],
                            "pressure": opposing["pressure"],
                            "pressureLabel": "Crossed-market candidate",
                            "confidence": confidence,
                            "inferenceOnly": True,
                            "transport": "ProphetX direct order book",
                            "outcomes": [selected, opposing],
                            "history": list(self._history[opposing["key"]]),
                            "comparisonLines": [],
                        }
                    )
        self._previous = current
        return sorted(
            rows,
            key=lambda item: (
                item["liquidity"],
                abs(item["pressure"]),
                item["totalLiquidity"],
            ),
            reverse=True,
        )[:40]

    def _build_novig_direct_signals(self, payload: dict) -> list[dict]:
        """Build directional Sharp Money rows from verified NBX depth alone."""
        rows: list[dict] = []
        current: dict[str, dict] = {}
        observed_at = str(
            payload.get("observedAt") or datetime.now(timezone.utc).isoformat()
        )
        for snapshot in payload.get("snapshots") or []:
            if not isinstance(snapshot, dict) or snapshot.get("stale"):
                continue
            market = snapshot.get("market") or {}
            event = market.get("event") or {}
            game = event.get("game") or {}
            market_id = str(snapshot.get("marketId") or market.get("id") or "")
            event_id = str(
                snapshot.get("eventId")
                or market.get("eventId")
                or event.get("id")
                or ""
            )
            home = _team_name(game.get("homeTeam"))
            away = _team_name(game.get("awayTeam"))
            if not home or not away:
                event_parts = str(market.get("description") or "").split(" vs ")
                if len(event_parts) == 2:
                    home = home or event_parts[0].strip()
                    away = away or event_parts[1].strip()
            if not market_id or not event_id or not home or not away:
                continue
            league = str(
                market.get("league")
                or event.get("league")
                or game.get("league")
                or "Other"
            ).upper()
            market_type = str(market.get("type") or "Moneyline")
            market_kind = _market_kind(market_type)
            market_name = {
                "moneyline": "Moneyline",
                "spread": "Spread",
                "game_total": "Game Total",
            }[market_kind]
            raw_outcomes = {
                str(item.get("id") or ""): item
                for item in market.get("outcomes") or []
                if isinstance(item, dict) and item.get("id")
            }
            outcomes: list[dict] = []
            for index, book in enumerate(snapshot.get("outcomes") or []):
                if not isinstance(book, dict):
                    continue
                outcome_id = str(book.get("outcomeId") or "")
                raw = raw_outcomes.get(outcome_id, {})
                probability = _number(book.get("bestAsk"))
                if not outcome_id or not 0 < probability < 1:
                    continue
                decimal = 1 / probability
                american = _american(decimal)
                if american is None:
                    continue
                asks = [
                    level
                    for level in book.get("asks") or []
                    if isinstance(level, dict)
                ]
                top_liquidity = sum(
                    max(0.0, _number(level.get("liquidityDollars")))
                    for level in asks
                    if abs(_number(level.get("price")) - probability) < 1e-9
                )
                if top_liquidity <= 0:
                    continue
                name = str(
                    raw.get("description")
                    or book.get("description")
                    or (home if index == 0 else away)
                ).strip()
                line = (
                    raw.get("line")
                    if raw.get("line") is not None
                    else raw.get("strike")
                    if raw.get("strike") is not None
                    else market.get("strike")
                )
                key = f"novig:{event_id}:{market_id}:{outcome_id}"
                previous = self._previous.get(key)
                probability_delta = (
                    probability - previous["probability"] if previous else 0.0
                )
                outcome = {
                    "key": key,
                    "selectionId": outcome_id,
                    "name": name,
                    "decimalOdds": decimal,
                    "americanOdds": american,
                    "probability": probability,
                    "liquidity": top_liquidity,
                    "line": line,
                    "probabilityDelta": probability_delta,
                    "liquidityDelta": (
                        top_liquidity - previous["liquidity"] if previous else 0.0
                    ),
                    "pressure": probability_delta,
                    "levels": [
                        {
                            "americanOdds": _american(
                                1 / _number(level.get("price"))
                            ),
                            "decimalOdds": 1 / _number(level.get("price")),
                            "liquidity": max(
                                0.0,
                                _number(level.get("liquidityDollars")),
                            ),
                        }
                        for level in asks
                        if 0 < _number(level.get("price")) < 1
                        and _number(level.get("liquidityDollars")) > 0
                    ],
                }
                current[key] = outcome
                self._history[key].append(
                    {
                        "observedAt": snapshot.get("timestamp") or observed_at,
                        "americanOdds": american,
                        "liquidity": top_liquidity,
                        "pressure": probability_delta,
                    }
                )
                outcomes.append(outcome)
            if len(outcomes) != 2:
                continue
            selected, opposite = sorted(
                outcomes, key=lambda item: item["liquidity"], reverse=True
            )
            net_liquidity = selected["liquidity"] - opposite["liquidity"]
            if net_liquidity <= 0:
                continue
            comparison_lines = [
                {
                    "providerName": "NoVIG",
                    "providerKey": "novig",
                    "displayOdds": (
                        f"+{selected['americanOdds']}"
                        if selected["americanOdds"] > 0
                        else str(selected["americanOdds"])
                    ),
                    "americanOdds": selected["americanOdds"],
                    "oppositeAmericanOdds": opposite["americanOdds"],
                    "availableLiquidity": selected["liquidity"],
                    "oppositeAvailableLiquidity": opposite["liquidity"],
                    "orderBookLevels": selected["levels"],
                    "oppositeOrderBookLevels": opposite["levels"],
                    "deepLink": "https://novig.com/",
                    "logoUrl": ORDERBOOK_BOOK_LOGOS["novig"],
                    "isAvailable": True,
                    "matchingConfidence": "Exact",
                    "tooltip": "Direct NoVIG executable order book",
                }
            ]
            total_liquidity = selected["liquidity"] + opposite["liquidity"]
            confidence = min(
                99,
                round(50 + 45 * net_liquidity / max(total_liquidity, 1.0)),
            )
            rows.append(
                {
                    "id": f"novig:{event_id}:{market_id}:{selected['selectionId']}",
                    "provider": "NoVIG",
                    "providerKey": "sharp_exchanges",
                    "providerLogo": ORDERBOOK_BOOK_LOGOS["novig"],
                    "sport": league,
                    "league": league,
                    "event": f"{away} vs. {home}",
                    "homeTeam": home,
                    "awayTeam": away,
                    "startsAt": event.get("scheduledStart")
                    or game.get("scheduledStart"),
                    "market": {
                        "id": market_id,
                        "name": market_name,
                        "kind": market_kind,
                        "line": selected.get("line"),
                    },
                    "selection": selected["name"],
                    "selectionId": selected["selectionId"],
                    "oppositeSelection": copy.deepcopy(opposite),
                    "americanOdds": selected["americanOdds"],
                    "decimalOdds": selected["decimalOdds"],
                    "liquidity": net_liquidity,
                    "totalLiquidity": total_liquidity,
                    "liquidityDelta": selected["liquidityDelta"],
                    "probabilityDelta": selected["probabilityDelta"],
                    "pressure": selected["pressure"],
                    "pressureLabel": "Directional liquidity imbalance",
                    "confidence": confidence,
                    "inferenceOnly": False,
                    "depthAvailable": True,
                    "transport": "Direct NoVIG net order book",
                    "outcomes": [selected, opposite],
                    "history": list(self._history[selected["key"]]),
                    "comparisonLines": comparison_lines,
                    "edgePercent": 0.0,
                    "whaleVolume": 0.0,
                    "bestBook": None,
                }
            )
        self._previous = current
        return rows[:40]

    @staticmethod
    def _quote_selection_name(market, side_id: str, line: float | None) -> str:
        if side_id == "home":
            name = market.home_names[0]
        elif side_id == "away":
            name = market.away_names[0]
        elif side_id in {"over", "under"}:
            return f"{side_id.title()} {line}" if line is not None else side_id.title()
        else:
            name = side_id.title()
        if market.market_name == "spread" and line is not None:
            return f"{name} {line:+g}"
        return name

    def _build_oddsengine_quote_signals(self, snapshot: dict) -> list[dict]:
        """Infer sharp consensus from standard-plan exact REST prices.

        This mode never claims wager volume or depth. Pressure combines the
        movement in cross-book implied probability with the current difference
        between recognized sharp books and the full market consensus.
        """
        events = snapshot.get("events") or []
        by_book, metadata = normalize_the_odds_api_events(events)
        groups: dict[tuple, dict] = {}
        for raw_book_key, markets in by_book.items():
            book_key = _book_key(raw_book_key)
            for market in markets:
                if market.is_alternative or market.american_odds is None:
                    continue
                group_line = (
                    abs(float(market.line))
                    if market.market_name == "spread" and market.line is not None
                    else market.line
                )
                group_key = (
                    market.event_id,
                    market.market_name,
                    group_line,
                )
                group = groups.setdefault(
                    group_key,
                    {
                        "market": market,
                        "sides": defaultdict(list),
                    },
                )
                decimal = _decimal_from_american(market.american_odds)
                if decimal is None:
                    continue
                meta = metadata.get(market.selection_id)
                group["sides"][market.side_id].append(
                    {
                        "providerKey": book_key,
                        "providerName": (
                            getattr(meta, "name", None)
                            or ORDERBOOK_BOOK_NAMES.get(book_key)
                            or str(raw_book_key).title()
                        ),
                        "logoUrl": (
                            ORDERBOOK_BOOK_LOGOS.get(book_key)
                            or getattr(meta, "logo_url", "")
                        ),
                        "americanOdds": market.american_odds,
                        "decimalOdds": decimal,
                        "probability": 1 / decimal,
                        "availableLiquidity": getattr(meta, "bet_limit", None),
                        "deepLink": getattr(meta, "direct_link", None) or "",
                        "lastUpdated": market.last_updated,
                        "line": market.line,
                    }
                )

        observed_at = str(
            snapshot.get("observedAt") or datetime.now(timezone.utc).isoformat()
        )
        current: dict[str, dict] = {}
        rows: list[dict] = []
        for (event_id, market_kind, group_line), group in groups.items():
            sides = {
                side_id: quotes
                for side_id, quotes in group["sides"].items()
                if quotes
            }
            if len(sides) != 2:
                continue
            market = group["market"]
            outcomes: list[dict] = []
            quote_sets: dict[str, list[dict]] = {}
            for side_id, quotes in sides.items():
                probabilities = [row["probability"] for row in quotes]
                consensus_probability = sum(probabilities) / len(probabilities)
                sharp_probabilities = [
                    row["probability"]
                    for row in quotes
                    if row["providerKey"] in SHARP_CONSENSUS_BOOKS
                ]
                sharp_probability = (
                    sum(sharp_probabilities) / len(sharp_probabilities)
                    if sharp_probabilities
                    else consensus_probability
                )
                side_key = f"rest:{event_id}:{market_kind}:{group_line}:{side_id}"
                known_liquidity = None
                previous = self._previous.get(side_key)
                probability_delta = (
                    consensus_probability - previous["probability"]
                    if previous
                    else 0.0
                )
                liquidity_delta = 0.0
                sharp_edge = sharp_probability - consensus_probability
                pressure = probability_delta + sharp_edge
                line = quotes[0].get("line")
                outcome = {
                    "key": side_key,
                    "selectionId": side_id,
                    "name": self._quote_selection_name(market, side_id, line),
                    "decimalOdds": 1 / consensus_probability,
                    "americanOdds": _american(1 / consensus_probability),
                    "probability": consensus_probability,
                    "liquidity": known_liquidity,
                    "line": line,
                    "probabilityDelta": probability_delta,
                    "liquidityDelta": liquidity_delta,
                    "pressure": pressure,
                    "sharpConsensusEdge": sharp_edge,
                    "bookCount": len(quotes),
                }
                current[side_key] = outcome
                self._history[side_key].append(
                    {
                        "observedAt": observed_at,
                        "americanOdds": outcome["americanOdds"],
                        "liquidity": known_liquidity,
                        "pressure": pressure,
                    }
                )
                outcomes.append(outcome)
                quote_sets[side_id] = quotes

            leader = max(
                outcomes,
                key=lambda item: (
                    item["pressure"],
                    item["bookCount"],
                    item["liquidity"] or 0,
                ),
            )
            opposite = next(row for row in outcomes if row is not leader)
            leader_quotes = quote_sets[leader["selectionId"]]
            opposite_quotes = {
                row["providerKey"]: row
                for row in quote_sets[opposite["selectionId"]]
            }
            comparisons: list[dict] = []
            for quote in leader_quotes:
                peer = opposite_quotes.get(quote["providerKey"], {})
                comparisons.append(
                    {
                        "providerName": quote["providerName"],
                        "providerKey": quote["providerKey"],
                        "displayOdds": (
                            f"+{quote['americanOdds']}"
                            if quote["americanOdds"] > 0
                            else str(quote["americanOdds"])
                        ),
                        "americanOdds": quote["americanOdds"],
                        "oppositeAmericanOdds": peer.get("americanOdds"),
                        "availableLiquidity": quote.get("availableLiquidity"),
                        "oppositeAvailableLiquidity": peer.get(
                            "availableLiquidity"
                        ),
                        "marketLimit": quote.get("availableLiquidity"),
                        "deepLink": quote.get("deepLink") or "",
                        "logoUrl": quote.get("logoUrl") or "",
                        "isAvailable": True,
                        "matchingConfidence": "Exact",
                        "tooltip": (
                            "OddsEngine exact REST quote; order-book depth is "
                            "not available on this plan"
                        ),
                    }
                )
            comparisons.sort(
                key=lambda row: _number(row.get("americanOdds"), -100000),
                reverse=True,
            )
            total_liquidity = None
            confidence = min(
                95,
                round(
                    45
                    + min(abs(leader["pressure"]) * 800, 30)
                    + min(leader["bookCount"] * 2, 20)
                ),
            )
            best_quote = max(
                leader_quotes,
                key=lambda row: row["americanOdds"],
            )
            market_name = {
                "moneyline": "Moneyline",
                "spread": "Spread",
                "game_total": "Game Total",
            }.get(market_kind, market_kind.replace("_", " ").title())
            rows.append(
                {
                    "id": (
                        f"oe:rest:{event_id}:{market_kind}:{group_line}:"
                        f"{leader['selectionId']}"
                    ),
                    "provider": "OddsEngine",
                    "providerKey": "odds_engine",
                    "providerLogo": best_quote.get("logoUrl") or "",
                    "sport": market.sport_id.title(),
                    "league": market.league_id,
                    "event": (
                        f"{market.away_names[0]} vs. {market.home_names[0]}"
                    ),
                    "homeTeam": market.home_names[0],
                    "awayTeam": market.away_names[0],
                    "startsAt": market.start_at.isoformat(),
                    "market": {
                        "id": f"{event_id}:{market_kind}:{group_line}",
                        "name": market_name,
                        "kind": market_kind,
                        "line": leader.get("line"),
                    },
                    "selection": leader["name"],
                    "selectionId": leader["selectionId"],
                    "americanOdds": leader["americanOdds"],
                    "decimalOdds": leader["decimalOdds"],
                    "liquidity": None,
                    "crossedLiquidity": None,
                    "liquiditySources": {},
                    "totalLiquidity": total_liquidity,
                    "liquidityDelta": leader["liquidityDelta"],
                    "probabilityDelta": leader["probabilityDelta"],
                    "pressure": leader["pressure"],
                    "pressureLabel": (
                        "Sharp consensus detected"
                        if abs(leader["pressure"]) >= 0.01
                        else "Monitoring consensus"
                    ),
                    "confidence": confidence,
                    "inferenceOnly": True,
                    "depthAvailable": False,
                    "transport": "OddsEngine REST sharp-consensus snapshot",
                    "oppositeSelection": copy.deepcopy(opposite),
                    "outcomes": [leader, opposite],
                    "history": list(self._history[leader["key"]]),
                    "comparisonLines": comparisons,
                    "edgePercent": leader["pressure"] * 100,
                    "fairOdds": leader["americanOdds"],
                    "whaleVolume": 0.0,
                    "whaleVolumeMode": "unavailable_on_standard_plan",
                    "bestBook": best_quote["providerKey"],
                }
            )
        self._previous = current
        return sorted(
            rows,
            key=lambda item: (
                abs(item["pressure"]),
                max((row.get("bookCount", 0) for row in item["outcomes"]), default=0),
                item["totalLiquidity"] or 0,
            ),
            reverse=True,
        )[: max(1, min(int(snapshot.get("limit") or 40), 100))]

    @staticmethod
    def _oddsengine_outcome(
        market: dict,
        side: dict,
        *,
        fallback_american: object = None,
        fallback_liquidity: object = None,
    ) -> dict | None:
        _raw_book, book = _side_book(side, "prophetx")
        if not book:
            _raw_book, book = _side_book(side, "novig")
        book = book or {}
        american = round(
            _number(
                book.get("odds_american")
                if book.get("odds_american") is not None
                else fallback_american
            )
        )
        decimal = _number(book.get("odds_decimal")) or _decimal_from_american(
            american
        )
        if decimal is None or decimal <= 1:
            return None
        liquidity, liquidity_sources = _sharp_side_liquidity(side)
        liquidity = liquidity or _number(fallback_liquidity)
        return {
            "key": (
                f"{market.get('event_id')}:{market.get('id')}:"
                f"{str(side.get('side') or '').lower()}"
            ),
            "selectionId": str(side.get("side") or "").lower(),
            "name": _side_name(side, market),
            "decimalOdds": decimal,
            "americanOdds": american,
            "probability": 1 / decimal,
            "liquidity": liquidity,
            "liquiditySources": liquidity_sources,
            "line": (
                side.get("line")
                if side.get("line") is not None
                else market.get("line")
            ),
            "levels": _orderbook_levels(book),
        }

    @staticmethod
    def _oddsengine_comparisons(
        recommended: dict,
        opposite: dict,
    ) -> list[dict]:
        opposite_books = {
            _book_key(raw_key): value
            for raw_key, value in (opposite.get("books") or {}).items()
            if isinstance(value, dict)
        }
        rows: dict[str, dict] = {}
        for raw_key, raw_book in (recommended.get("books") or {}).items():
            if not isinstance(raw_book, dict):
                continue
            key = _book_key(raw_key)
            if not key:
                continue
            opposite_book = opposite_books.get(key, {})
            american = round(_number(raw_book.get("odds_american")))
            if not american:
                continue
            opposite_american = round(
                _number(opposite_book.get("odds_american"))
            )
            rows[key] = {
                "providerName": ORDERBOOK_BOOK_NAMES.get(
                    key, str(raw_key).strip() or key.title()
                ),
                "providerKey": key,
                "displayOdds": f"+{american}" if american > 0 else str(american),
                "americanOdds": american,
                "oppositeAmericanOdds": opposite_american or None,
                "availableLiquidity": _quoted_book_liquidity(raw_book),
                "oppositeAvailableLiquidity": _quoted_book_liquidity(
                    opposite_book
                ),
                "marketLimit": raw_book.get("limit"),
                "deepLink": str(raw_book.get("bet_link") or ""),
                "logoUrl": ORDERBOOK_BOOK_LOGOS.get(key, ""),
                "isAvailable": True,
                "matchingConfidence": "Exact",
                "orderBookLevels": _orderbook_levels(raw_book),
                "oppositeOrderBookLevels": _orderbook_levels(opposite_book),
                "tooltip": "OddsEngine two-sided order-book quote",
            }
        for peer in recommended.get("peers") or []:
            if not isinstance(peer, dict):
                continue
            key = _book_key(peer.get("book"))
            if not key or key in rows:
                continue
            american = round(_number(peer.get("odds_american")))
            if not american:
                continue
            rows[key] = {
                "providerName": ORDERBOOK_BOOK_NAMES.get(
                    key, str(peer.get("book") or key).strip().title()
                ),
                "providerKey": key,
                "displayOdds": f"+{american}" if american > 0 else str(american),
                "americanOdds": american,
                "oppositeAmericanOdds": (
                    round(_number(peer.get("opp_odds_american"))) or None
                ),
                "availableLiquidity": peer.get("limit"),
                "oppositeAvailableLiquidity": None,
                "marketLimit": peer.get("limit"),
                "deepLink": str(peer.get("bet_link") or ""),
                "logoUrl": ORDERBOOK_BOOK_LOGOS.get(key, ""),
                "isAvailable": True,
                "matchingConfidence": "Exact",
                "tooltip": "OddsEngine retail peer quote",
            }
        return list(rows.values())

    def _build_oddsengine_signals(self, snapshot: dict) -> list[dict]:
        opportunities = snapshot.get("opportunities") or []
        observed_at = str(
            (snapshot.get("meta") or {}).get("updated_at")
            or datetime.now(timezone.utc).isoformat()
        )
        current: dict[str, dict] = {}
        rows: list[dict] = []
        for opportunity in opportunities:
            if not isinstance(opportunity, dict):
                continue
            market = opportunity.get("market_data") or {}
            recommended = opportunity.get("recommended_side") or {}
            opposite = opportunity.get("opposite_side") or {}
            if not isinstance(market, dict) or not isinstance(recommended, dict):
                continue
            if not isinstance(opposite, dict) or not opposite:
                continue
            selected = self._oddsengine_outcome(
                market,
                recommended,
                fallback_american=opportunity.get("best_odds"),
                fallback_liquidity=opportunity.get("edge_supporting_liquidity"),
            )
            opposing = self._oddsengine_outcome(market, opposite)
            if selected is None or opposing is None:
                continue
            comparisons = self._oddsengine_comparisons(recommended, opposite)
            crossed = _crossed_market_liquidity(comparisons)
            if crossed is None:
                continue
            crossed_liquidity = crossed["liquidity"]
            crossed_sources = crossed["sources"]
            previous = self._previous.get(selected["key"])
            probability_delta = (
                selected["probability"] - previous["probability"]
                if previous
                else 0.0
            )
            liquidity_delta = (
                crossed_liquidity - previous.get("crossedLiquidity", 0.0)
                if previous
                else 0.0
            )
            edge_percent = _number(opportunity.get("edge_percent"))
            pressure = edge_percent / 100 if edge_percent else probability_delta
            selected.update(
                {
                    "probabilityDelta": probability_delta,
                    "liquidityDelta": liquidity_delta,
                    "pressure": pressure,
                    "crossedLiquidity": crossed_liquidity,
                }
            )
            current[selected["key"]] = selected
            self._history[selected["key"]].append(
                {
                    "observedAt": observed_at,
                    "americanOdds": selected["americanOdds"],
                    "liquidity": crossed_liquidity,
                    "pressure": pressure,
                }
            )
            event_id = str(market.get("event_id") or "")
            market_id = str(market.get("id") or "")
            if not event_id or not market_id:
                continue
            home = str(market.get("home_team") or "").strip()
            away = str(market.get("away_team") or "").strip()
            event_name = str(market.get("event") or "").strip()
            if not event_name:
                event_name = " vs. ".join(value for value in (away, home) if value)
            market_name = str(market.get("market") or "Market").strip()
            whale_volume = _number(opportunity.get("whale_volume"))
            total_liquidity = selected["liquidity"] + opposing["liquidity"]
            confidence = min(
                99,
                round(
                    45
                    + min(abs(edge_percent) * 4, 30)
                    + min(math.log10(max(1.0, whale_volume)) * 4, 20)
                ),
            )
            rows.append(
                {
                    "id": f"oe:px:{event_id}:{market_id}:{selected['selectionId']}",
                    "provider": "NoVIG + ProphetX",
                    "providerKey": "sharp_exchanges",
                    "providerLogo": PROPHETX_LOGO_URL,
                    "sport": str(market.get("sport") or market.get("league") or ""),
                    "league": str(market.get("league") or "Other").upper(),
                    "event": event_name,
                    "homeTeam": home,
                    "awayTeam": away,
                    "startsAt": market.get("event_start"),
                    "market": {
                        "id": market_id,
                        "name": market_name,
                        "kind": _market_kind(market_name),
                        "line": selected.get("line"),
                    },
                    "selection": selected["name"],
                    "americanOdds": selected["americanOdds"],
                    "decimalOdds": selected["decimalOdds"],
                    "liquidity": crossed_liquidity,
                    "crossedLiquidity": crossed_liquidity,
                    "liquiditySources": crossed_sources,
                    "crossedSharpOdds": crossed["sharpPrices"],
                    "crossedRetailOdds": crossed["retailOdds"],
                    "crossedRoiPercent": crossed["roiPercent"],
                    "counterLiquidity": selected["liquidity"],
                    "totalLiquidity": total_liquidity,
                    "liquidityDelta": liquidity_delta,
                    "probabilityDelta": probability_delta,
                    "pressure": pressure,
                    "pressureLabel": (
                        "Whale flow detected"
                        if abs(pressure) >= 0.01
                        else "Monitoring"
                    ),
                    "confidence": confidence,
                    "inferenceOnly": True,
                    "depthAvailable": True,
                    "transport": "OddsEngine NoVIG + ProphetX full order books",
                    "outcomes": [selected, opposing],
                    "history": list(self._history[selected["key"]]),
                    "comparisonLines": comparisons,
                    "edgePercent": edge_percent,
                    "fairOdds": opportunity.get("fair_odds"),
                    "whaleVolume": whale_volume,
                    "whaleVolumeMode": opportunity.get("whale_volume_mode"),
                    "bestBook": crossed["retailBook"],
                }
            )
        self._previous = current
        return sorted(
            rows,
            key=lambda item: (
                item["crossedLiquidity"],
                abs(item["pressure"]),
                item["totalLiquidity"],
            ),
            reverse=True,
        )[:40]

    def _finalize_direct_signals(self, signals: list[dict]) -> list[dict]:
        rows = []
        for signal in signals:
            comparisons = signal.get("comparisonLines") or []
            net = _net_exchange_liquidity(comparisons)
            if net is None:
                continue
            sources = net["sources"]
            provider_names = [
                name
                for key, name in (("novig", "NoVIG"), ("prophetx", "ProphetX"))
                if key in sources
            ]
            provider_label = " + ".join(provider_names)
            signal.update(
                {
                    "provider": provider_label,
                    "providerKey": "sharp_exchanges",
                    "liquidity": net["liquidity"],
                    "crossedLiquidity": net["liquidity"],
                    "liquiditySources": sources,
                    "selectedLiquidity": net["selectedLiquidity"],
                    "oppositeLiquidity": net["oppositeLiquidity"],
                    "selectedLiquiditySources": net["selectedSources"],
                    "oppositeLiquiditySources": net["oppositeSources"],
                    "crossedSharpOdds": net["sharpPrices"],
                    "oppositeSharpOdds": net["oppositeSharpPrices"],
                    "crossedRetailOdds": net["retailOdds"],
                    "crossedRoiPercent": 0.0,
                    "counterLiquidity": net["oppositeLiquidity"],
                    "bestBook": net["retailBook"],
                    "depthAvailable": True,
                    "transport": (
                        f"Direct {provider_label} net order book"
                        if len(provider_names) == 1
                        else "Direct NoVIG + ProphetX net order books"
                    ),
                    "edgePercent": signal.get("edgePercent", 0.0),
                    "whaleVolume": 0,
                }
            )
            rows.append(signal)
        return sorted(
            rows,
            key=lambda item: (
                item["crossedLiquidity"],
                abs(_number(item.get("edgePercent"))),
            ),
            reverse=True,
        )[:40]

    @staticmethod
    def _opposite_quote_signal(signal: dict) -> dict | None:
        outcomes = signal.get("outcomes") or []
        if len(outcomes) != 2:
            return None
        selected, opposite = outcomes
        clone = copy.deepcopy(signal)
        clone["id"] = f"{signal['id']}:opposite"
        clone["selection"] = opposite.get("name") or "Opposing side"
        clone["selectionId"] = opposite.get("selectionId")
        clone["americanOdds"] = opposite.get("americanOdds")
        clone["decimalOdds"] = opposite.get("decimalOdds")
        clone["liquidity"] = opposite.get("liquidity")
        clone["market"]["line"] = opposite.get("line")
        clone["oppositeSelection"] = copy.deepcopy(selected)
        clone["outcomes"] = [copy.deepcopy(opposite), copy.deepcopy(selected)]
        inverted = []
        for row in clone.get("comparisonLines") or []:
            current = dict(row)
            current["americanOdds"], current["oppositeAmericanOdds"] = (
                current.get("oppositeAmericanOdds"),
                current.get("americanOdds"),
            )
            current["availableLiquidity"], current[
                "oppositeAvailableLiquidity"
            ] = (
                current.get("oppositeAvailableLiquidity"),
                current.get("availableLiquidity"),
            )
            odds = current.get("americanOdds")
            current["displayOdds"] = (
                f"+{round(_number(odds))}"
                if _number(odds) > 0
                else str(round(_number(odds)))
            )
            inverted.append(current)
        clone["comparisonLines"] = inverted
        return clone

    def _enrich_quote_signals_with_novig(
        self, signals: list[dict]
    ) -> list[dict]:
        provider = self.novig_provider
        if not provider or not bool(getattr(provider, "configured", False)):
            return []
        candidates: list[dict] = []
        for signal in signals[:20]:
            candidates.append(copy.deepcopy(signal))
            opposite = self._opposite_quote_signal(signal)
            if opposite is not None:
                candidates.append(opposite)
        trades = []
        for signal in candidates:
            trades.append(self._trade_for_signal(signal))
            trades.append(
                self._trade_for_signal(
                    signal,
                    outcome=signal.get("oppositeSelection") or {},
                    trade_id=f"{signal['id']}:exchange-opposite",
                )
            )
        try:
            options = provider.options_for_trades(trades)
        except Exception:
            LOGGER.warning("Direct NoVIG quote enrichment failed")
            return []

        def liquidity(option) -> float:
            return max(
                0.0,
                _number(getattr(option, "top_price_liquidity", None)),
            )

        def levels(option) -> list[dict]:
            order_book = getattr(option, "order_book", None) or {}
            return [
                {
                    "americanOdds": round(_number(row.get("americanOdds"))),
                    "liquidity": _number(row.get("liquidityDollars")),
                }
                for row in order_book.get("asks") or []
                if row.get("americanOdds") is not None
                and _number(row.get("liquidityDollars")) > 0
            ]

        enriched = []
        for signal in candidates:
            selected = options.get(signal["id"])
            opposite = options.get(f"{signal['id']}:exchange-opposite")
            selected_liquidity = liquidity(selected)
            opposite_liquidity = liquidity(opposite)
            if selected_liquidity <= 0 and opposite_liquidity <= 0:
                continue
            rows = [
                row
                for row in signal.get("comparisonLines") or []
                if _book_key(row.get("providerKey"))
                not in {"novig", "prophetx"}
            ]
            rows.append(
                {
                    "providerName": "NoVIG",
                    "providerKey": "novig",
                    "displayOdds": getattr(selected, "display_odds", ""),
                    "americanOdds": getattr(selected, "american_odds", None),
                    "oppositeAmericanOdds": getattr(
                        opposite, "american_odds", None
                    ),
                    "availableLiquidity": selected_liquidity,
                    "oppositeAvailableLiquidity": opposite_liquidity,
                    "orderBookLevels": levels(selected),
                    "oppositeOrderBookLevels": levels(opposite),
                    "deepLink": getattr(selected, "deep_link", ""),
                    "logoUrl": getattr(selected, "logo_url", ""),
                    "isAvailable": selected_liquidity > 0,
                    "matchingConfidence": "Exact",
                    "tooltip": "Direct NoVIG executable order book",
                }
            )
            signal["comparisonLines"] = rows
            enriched.append(signal)
        return enriched

    def _trade_for_signal(
        self,
        signal: dict,
        *,
        outcome: dict | None = None,
        trade_id: str | None = None,
    ) -> dict:
        kind = signal["market"]["kind"]
        market_type = {
            "moneyline": "Moneyline",
            "spread": "Spread",
            "game_total": "Total",
        }[kind]
        selected = outcome or {}
        return {
            "id": trade_id or signal["id"],
            "category": signal["sport"],
            "league": signal["league"],
            "event_date_et": signal["startsAt"],
            "event_title": signal["event"],
            "market_title": signal["market"]["name"],
            "sports_market_type": market_type,
            "outcome": selected.get("name") or signal["selection"],
            "line": (
                selected.get("line")
                if selected.get("line") is not None
                else signal["market"].get("line")
            ),
            "recommended_amount": 100,
        }

    def _refresh_comparisons(self, signals: list[dict]) -> None:
        visible = signals[:16]
        trades = [self._trade_for_signal(signal) for signal in visible]
        novig_trades = []
        for signal in visible:
            novig_trades.append(self._trade_for_signal(signal))
            novig_trades.append(
                self._trade_for_signal(
                    signal,
                    outcome=signal.get("oppositeSelection") or {},
                    trade_id=f"{signal['id']}:opposite",
                )
            )

        def retail_options():
            return self.odds_provider.screen_options_for_trades(trades)

        def direct_novig_options():
            provider = self.novig_provider
            if not provider or not bool(getattr(provider, "configured", False)):
                return {}
            try:
                return provider.options_for_trades(novig_trades)
            except Exception:
                LOGGER.warning("Direct NoVIG Sharp Money refresh failed")
                return {}

        with ThreadPoolExecutor(max_workers=2) as executor:
            retail_future = executor.submit(retail_options)
            novig_future = executor.submit(direct_novig_options)
            options = retail_future.result()
            novig_options = novig_future.result()

        def novig_liquidity(option) -> float:
            return _number(getattr(option, "top_price_liquidity", None))

        def novig_levels(option) -> list[dict]:
            order_book = getattr(option, "order_book", None) or {}
            levels = []
            for row in order_book.get("asks") or []:
                american = row.get("americanOdds")
                liquidity = row.get("liquidityDollars")
                if american is None or _number(liquidity) <= 0:
                    continue
                levels.append(
                    {
                        "americanOdds": round(_number(american)),
                        "liquidity": _number(liquidity),
                    }
                )
            return levels

        comparisons: dict[str, list[dict]] = {}
        for signal in visible:
            rows = []
            for option in options.get(signal["id"], []):
                if not option.is_available or option.american_odds is None:
                    continue
                row = option.to_dict()
                key = _book_key(row.get("providerKey"))
                # Direct exchange rows below carry verified top-price depth.
                # Never let price-only aggregator rows impersonate liquidity.
                if key in {"novig", "prophetx"}:
                    continue
                if key == "pinnacle" and row.get("marketLimit") is None:
                    row["marketLimit"] = row.get("availableLiquidity")
                rows.append(row)

            selected = (signal.get("outcomes") or [{}])[0]
            opposing = signal.get("oppositeSelection") or {}
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
                    "oppositeAmericanOdds": opposing.get("americanOdds"),
                    "availableLiquidity": _number(selected.get("liquidity")),
                    "oppositeAvailableLiquidity": _number(
                        opposing.get("liquidity")
                    ),
                    "orderBookLevels": selected.get("levels") or [],
                    "oppositeOrderBookLevels": opposing.get("levels") or [],
                    "logoUrl": PROPHETX_LOGO_URL,
                    "isAvailable": True,
                    "matchingConfidence": "Exact",
                    "tooltip": "Direct ProphetX executable order book",
                }
            )

            novig_selected = novig_options.get(signal["id"])
            novig_opposing = novig_options.get(f"{signal['id']}:opposite")
            if (
                novig_selected is not None
                and novig_opposing is not None
                and getattr(novig_selected, "is_available", False)
                and getattr(novig_opposing, "is_available", False)
            ):
                selected_liquidity = novig_liquidity(novig_selected)
                opposing_liquidity = novig_liquidity(novig_opposing)
                rows.append(
                    {
                        "providerName": "NoVIG",
                        "providerKey": "novig",
                        "displayOdds": getattr(
                            novig_selected, "display_odds", ""
                        ),
                        "americanOdds": getattr(
                            novig_selected, "american_odds", None
                        ),
                        "oppositeAmericanOdds": getattr(
                            novig_opposing, "american_odds", None
                        ),
                        "availableLiquidity": selected_liquidity,
                        "oppositeAvailableLiquidity": opposing_liquidity,
                        "orderBookLevels": novig_levels(novig_selected),
                        "oppositeOrderBookLevels": novig_levels(
                            novig_opposing
                        ),
                        "deepLink": getattr(novig_selected, "deep_link", ""),
                        "logoUrl": getattr(novig_selected, "logo_url", ""),
                        "isAvailable": True,
                        "matchingConfidence": "Exact",
                        "tooltip": "Direct NoVIG executable order book",
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
    comparison_provider = OddsComparisonFallback(
        (
            providers.get("odds_engine"),
            providers.get("the_odds_api"),
        )
    )
    odds_engine = providers.get("odds_engine")
    direct_prophetx = providers.get("prophetx")
    direct_prophetx_configured = bool(
        direct_prophetx is not None
        and direct_prophetx.diagnostics().get("configured")
    )
    odds_engine_configured = bool(
        odds_engine is not None and getattr(odds_engine, "api_key", None)
    )
    advanced_orderbook_enabled = bool(
        getattr(settings, "sharp_money_advanced_orderbook_enabled", False)
    )
    # Direct exchange credentials expose executable depth without depending on
    # the OddsEngine Advanced entitlement. On the standard plan, OddsEngine's
    # quote feed must run first: it supplies the market map used to match direct
    # NoVIG depth and avoids blocking every cold page load on an unavailable
    # ProphetX production login. Direct ProphetX remains the fallback and is the
    # preferred source only when Advanced depth is explicitly enabled.
    if odds_engine_configured and not advanced_orderbook_enabled:
        primary_source = odds_engine
        fallback_source = direct_prophetx if direct_prophetx_configured else None
    elif direct_prophetx_configured:
        primary_source = direct_prophetx
        fallback_source = odds_engine if odds_engine_configured else None
    elif odds_engine_configured:
        primary_source = odds_engine
        fallback_source = None
    else:
        # Preserve the provider object for local diagnostics and cached-read
        # tests even when its credentials are absent.
        primary_source = direct_prophetx
        fallback_source = None
    return SharpMoneyCollector(
        primary_source,
        comparison_provider,
        fallback_source=fallback_source,
        novig_provider=providers.get("novig_nbx"),
        poll_seconds=float(
            os.getenv("SHARP_MONEY_PROPHETX_POLL_SECONDS", "1")
        ),
        comparison_seconds=float(
            os.getenv("SHARP_MONEY_COMPARISON_SECONDS", "60")
        ),
        automatic_refresh_seconds=float(
            os.getenv("SHARP_MONEY_ODDSENGINE_REFRESH_SECONDS", "30")
        ),
        advanced_orderbook_enabled=advanced_orderbook_enabled,
    )
