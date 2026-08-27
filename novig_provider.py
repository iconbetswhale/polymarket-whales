from __future__ import annotations

import base64
import json
import logging
import math
import re
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable
from urllib.parse import quote

import requests

from execution_providers import (
    ExecutionOption,
    ExecutionProvider,
    MatchConfidence,
    NormalizedProviderMarket,
    ProviderHealthStatus,
    ProviderMarketIndex,
    _fair_quotes_from_index,
    _match_exact_trade,
    _normalize_identifier,
    _normalize_name,
    _parse_datetime,
    canonicalize_trade,
    probability_to_american,
)

LOGGER = logging.getLogger(__name__)

NOVIG_AUTH_URL = "https://api.novig.us/nbx/v1/auth/emm-token"
NOVIG_REST_BASE_URL = "https://api.novig.us/nbx/v2"
NOVIG_WEBSOCKET_URL = "wss://api.novig.us/tape"
NOVIG_LOGO_URL = (
    "https://cdn.prod.website-files.com/642ae772b9f3360398a9d449/"
    "6436d7c4d343f31dbf62d683_favicon.png"
)
NOVIG_WEB_URL = "https://novig.com/"
TOKEN_LIFETIME_SECONDS = 30 * 60
TOKEN_REFRESH_SKEW_SECONDS = 60
NOVIG_CASH_QTY_PER_CONTRACT = 100.0
NOVIG_LIVE_TAKER_FEE_COEFFICIENT = 0.03
MAX_EVENT_PAGES = 50
MAX_BATCH_EVENT_IDS = 50
SHARP_MONEY_MARKET_TYPES = {
    "MONEY",
    "MONEYLINE",
    "SPREAD",
    "TOTAL",
    "MONEY_1H",
    "MONEYLINE_1H",
    "SPREAD_1H",
    "TOTAL_1H",
}
SHARP_MONEY_OPEN_EVENT_STATUSES = ("OPEN_INGAME", "OPEN_PREGAME")
TERMINAL_EVENT_STATUSES = {
    "CANCELED",
    "CANCELLED",
    "CLOSED",
    "FINAL",
    "POSTPONED",
    "SETTLED",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat()


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _safe_text(value: object) -> str:
    return str(value or "").strip()


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


class NoVIGError(RuntimeError):
    """A sanitized provider error that never embeds a response body or token."""

    def __init__(self, code: str, *, status_code: int | None = None) -> None:
        self.code = str(code or "NOVIG_ERROR")
        self.status_code = status_code
        suffix = f" (HTTP {status_code})" if status_code is not None else ""
        super().__init__(f"{self.code}{suffix}")


class NoVIGConfigurationError(NoVIGError):
    pass


class NoVIGHTTPError(NoVIGError):
    pass


class NoVIGAuthClient:
    """OAuth client-credentials token cache with a single-flight refresh."""

    def __init__(
        self,
        client_id: str | None,
        client_secret: str | None,
        *,
        auth_url: str = NOVIG_AUTH_URL,
        timeout: float = 5.0,
        refresh_skew_seconds: int = TOKEN_REFRESH_SKEW_SECONDS,
        session: requests.Session | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client_id = _safe_text(client_id) or None
        self._client_secret = _safe_text(client_secret) or None
        self.auth_url = auth_url.rstrip("/")
        self.timeout = max(0.1, min(float(timeout), 30.0))
        self.refresh_skew_seconds = max(1, int(refresh_skew_seconds))
        self.session = session or requests.Session()
        self._monotonic = monotonic
        self._condition = threading.Condition(threading.RLock())
        self._token: str | None = None
        self._expires_at = 0.0
        self._refreshing = False
        self._refresh_count = 0
        self._last_refresh_at: str | None = None
        self._last_error_code: str | None = None

    def __repr__(self) -> str:
        return (
            f"<NoVIGAuthClient configured={self.configured} "
            f"cached={self.has_cached_token}>"
        )

    @property
    def configured(self) -> bool:
        return bool(self._client_id and self._client_secret)

    @property
    def has_cached_token(self) -> bool:
        with self._condition:
            return bool(self._token)

    @property
    def expires_in_seconds(self) -> float:
        with self._condition:
            return max(0.0, self._expires_at - self._monotonic())

    def invalidate(self) -> None:
        with self._condition:
            self._token = None
            self._expires_at = 0.0

    def get_token(self, *, force_refresh: bool = False) -> str:
        if not self.configured:
            raise NoVIGConfigurationError("NOVIG_CREDENTIALS_NOT_CONFIGURED")

        with self._condition:
            while True:
                valid = bool(
                    self._token
                    and self._expires_at - self._monotonic()
                    > self.refresh_skew_seconds
                )
                if valid and not force_refresh:
                    return str(self._token)
                if not self._refreshing:
                    self._refreshing = True
                    break
                self._condition.wait(timeout=self.timeout + 1.0)
                force_refresh = False

        token: str | None = None
        expires_at = 0.0
        error: NoVIGError | None = None
        try:
            response = self.session.post(
                self.auth_url,
                json={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            )
            if response.status_code >= 400:
                raise NoVIGHTTPError(
                    "NOVIG_AUTH_REQUEST_FAILED", status_code=response.status_code
                )
            payload = response.json()
            token = _safe_text(payload.get("access_token") or payload.get("token"))
            if not token:
                raise NoVIGHTTPError("NOVIG_AUTH_TOKEN_MISSING")
            expires_in = _token_lifetime_seconds(payload, token)
            expires_at = self._monotonic() + max(1.0, expires_in)
        except NoVIGError as exc:
            error = exc
        except (requests.RequestException, ValueError, TypeError):
            error = NoVIGHTTPError("NOVIG_AUTH_CONNECTION_FAILED")

        with self._condition:
            self._refreshing = False
            if error is None and token:
                self._token = token
                self._expires_at = expires_at
                self._refresh_count += 1
                self._last_refresh_at = _iso_now()
                self._last_error_code = None
            else:
                self._last_error_code = error.code if error else "NOVIG_AUTH_FAILED"
            self._condition.notify_all()

        if error is not None:
            raise error
        return str(token)

    def status(self) -> dict[str, object]:
        with self._condition:
            return {
                "configured": self.configured,
                "cached": bool(self._token),
                "expires_in_seconds": round(
                    max(0.0, self._expires_at - self._monotonic()), 1
                ),
                "refresh_in_progress": self._refreshing,
                "refresh_count": self._refresh_count,
                "last_refresh_at": self._last_refresh_at,
                "last_error_code": self._last_error_code,
                "credentials_exposed": False,
                "token_exposed": False,
            }


def _token_lifetime_seconds(payload: dict, token: str) -> float:
    configured = _number(payload.get("expires_in") or payload.get("expiresIn"))
    if configured and configured > 0:
        return configured
    try:
        body = token.split(".", 2)[1]
        body += "=" * (-len(body) % 4)
        claims = json.loads(base64.urlsafe_b64decode(body.encode("ascii")))
        expires_at = _number(claims.get("exp"))
        issued_at = _number(claims.get("iat")) or time.time()
        if expires_at and expires_at > issued_at:
            return expires_at - issued_at
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        pass
    return float(TOKEN_LIFETIME_SECONDS)


class NoVIGRestClient:
    """Authenticated, read-only NBX REST client with bounded retries."""

    def __init__(
        self,
        auth: NoVIGAuthClient,
        *,
        base_url: str = NOVIG_REST_BASE_URL,
        timeout: float = 5.0,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.auth = auth
        self.base_url = base_url.rstrip("/")
        self.timeout = max(0.1, min(float(timeout), 30.0))
        self.session = session or auth.session
        self._sleep = sleep
        self.last_http_status: int | None = None
        self.last_success_at: str | None = None
        self.request_count = 0
        self.rate_limit_count = 0
        self.reauthentication_count = 0

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> object:
        reauthenticated = False
        rate_retried = False
        while True:
            token = self.auth.get_token(force_refresh=False)
            try:
                response = self.session.request(
                    method.upper(),
                    f"{self.base_url}/{path.lstrip('/')}",
                    params=params,
                    json=json_body,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                raise NoVIGHTTPError("NOVIG_REST_CONNECTION_FAILED") from exc
            self.request_count += 1
            self.last_http_status = response.status_code
            if response.status_code == 401 and not reauthenticated:
                reauthenticated = True
                self.reauthentication_count += 1
                self.auth.invalidate()
                continue
            if response.status_code == 429 and not rate_retried:
                rate_retried = True
                self.rate_limit_count += 1
                self._sleep(_retry_after_seconds(response.headers))
                continue
            if response.status_code >= 400:
                raise NoVIGHTTPError(
                    "NOVIG_REST_REQUEST_FAILED", status_code=response.status_code
                )
            try:
                payload = response.json()
            except (ValueError, TypeError) as exc:
                raise NoVIGHTTPError("NOVIG_REST_INVALID_JSON") from exc
            self.last_success_at = _iso_now()
            return payload

    def list_open_markets(
        self, *, league: str | None = None, market_type: str | None = None
    ) -> list[dict]:
        params = {
            key: value
            for key, value in {
                "league": _safe_text(league) or None,
                "marketType": _safe_text(market_type) or None,
            }.items()
            if value is not None
        }
        payload = self.request("GET", "/emm/markets/open", params=params)
        if not isinstance(payload, list):
            raise NoVIGHTTPError("NOVIG_MARKETS_INVALID_PAYLOAD")
        return [row for row in payload if isinstance(row, dict)]

    def list_events(
        self,
        *,
        league: str | None = None,
        event_status: str | None = None,
        event_type: str | None = None,
    ) -> list[dict]:
        rows: list[dict] = []
        limit = 100
        for page in range(MAX_EVENT_PAGES):
            params = {
                key: value
                for key, value in {
                    "league": _safe_text(league) or None,
                    "status": _safe_text(event_status) or None,
                    "type": _safe_text(event_type) or None,
                    "limit": limit,
                    "offset": page * limit,
                }.items()
                if value is not None
            }
            payload = self.request("GET", "/emm/events", params=params)
            if not isinstance(payload, list):
                raise NoVIGHTTPError("NOVIG_EVENTS_INVALID_PAYLOAD")
            page_rows = [row for row in payload if isinstance(row, dict)]
            rows.extend(page_rows)
            if len(page_rows) < limit:
                return rows
        raise NoVIGHTTPError("NOVIG_EVENTS_PAGINATION_LIMIT")

    def list_events_page(
        self,
        *,
        league: str | None = None,
        event_status: str | None = None,
        event_type: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> list[dict]:
        """Fetch one bounded event page for probes and targeted reconciliation."""

        page_limit = max(1, min(int(limit), 100))
        page_offset = max(0, int(offset))
        params = {
            key: value
            for key, value in {
                "league": _safe_text(league) or None,
                "status": _safe_text(event_status) or None,
                "type": _safe_text(event_type) or None,
                "limit": page_limit,
                "offset": page_offset,
            }.items()
            if value is not None
        }
        payload = self.request("GET", "/emm/events", params=params)
        if not isinstance(payload, list):
            raise NoVIGHTTPError("NOVIG_EVENTS_INVALID_PAYLOAD")
        return [row for row in payload if isinstance(row, dict)]

    def get_market(self, market_id: str) -> dict:
        payload = self.request(
            "GET", f"/emm/markets/{quote(_validated_identifier(market_id), safe='')}"
        )
        if not isinstance(payload, dict):
            raise NoVIGHTTPError("NOVIG_MARKET_INVALID_PAYLOAD")
        return payload

    def get_book(self, market_id: str, *, currency: str = "CASH") -> dict:
        payload = self.request(
            "GET",
            f"/emm/book/{quote(_validated_identifier(market_id), safe='')}",
            params={"currency": _validated_currency(currency)},
        )
        if not isinstance(payload, dict):
            raise NoVIGHTTPError("NOVIG_BOOK_INVALID_PAYLOAD")
        return payload

    def get_markets_by_events(
        self, event_ids: Iterable[str], *, currency: str = "CASH"
    ) -> list[dict]:
        unique = list(
            dict.fromkeys(_validated_identifier(value) for value in event_ids)
        )
        rows: list[dict] = []
        for batch in _chunks(unique, MAX_BATCH_EVENT_IDS):
            payload = self.request(
                "POST",
                "/emm/events/getMarketsByEvents",
                json_body={
                    "eventIds": batch,
                    "currency": _validated_currency(currency),
                },
            )
            if not isinstance(payload, list):
                raise NoVIGHTTPError("NOVIG_EVENT_MARKETS_INVALID_PAYLOAD")
            rows.extend(row for row in payload if isinstance(row, dict))
        return rows

    def credential_smoke_test(self, *, sample_size: int = 3) -> dict[str, object]:
        try:
            self.auth.get_token()
            markets = self.list_open_markets()
        except NoVIGError as exc:
            return {
                "success": False,
                "http_status": exc.status_code or self.last_http_status,
                "error_code": exc.code,
                "market_count": 0,
                "market_sample": [],
                "credentials_exposed": False,
                "token_exposed": False,
            }
        sample = [
            {
                "market_id": _safe_text(row.get("id")),
                "event_id": _safe_text(row.get("eventId")),
                "league": _safe_text(row.get("league")),
                "market_type": _safe_text(row.get("type")),
                "status": _safe_text(row.get("status")),
                "outcome_count": len(row.get("outcomes") or row.get("outcomeIds") or []),
            }
            for row in markets[: max(0, min(int(sample_size), 10))]
        ]
        market_types = Counter(
            _safe_text(row.get("type")) or "UNKNOWN" for row in markets
        )
        leagues = Counter(
            _safe_text(row.get("league")) or "UNKNOWN" for row in markets
        )
        return {
            "success": True,
            "http_status": self.last_http_status,
            "error_code": None,
            "market_count": len(markets),
            "market_type_counts": dict(sorted(market_types.items())),
            "league_counts": dict(sorted(leagues.items())),
            "market_sample": sample,
            "credentials_exposed": False,
            "token_exposed": False,
        }


def _validated_identifier(value: object) -> str:
    text = _safe_text(value)
    if not text or len(text) > 128 or not re.fullmatch(r"[A-Za-z0-9_-]+", text):
        raise NoVIGHTTPError("NOVIG_INVALID_IDENTIFIER")
    return text


def _validated_currency(value: object) -> str:
    currency = _safe_text(value).upper()
    if currency not in {"CASH", "COIN"}:
        raise NoVIGHTTPError("NOVIG_INVALID_CURRENCY")
    return currency


def _retry_after_seconds(headers: object) -> float:
    try:
        value = float((headers or {}).get("Retry-After") or 0)
    except (TypeError, ValueError, AttributeError):
        value = 0.0
    # NoVIG documents Retry-After in milliseconds, not HTTP-standard seconds.
    return max(0.025, min(value / 1000.0 if value > 0 else 0.1, 5.0))


class NoVIGOrderBookState:
    """Deterministic in-memory books built from REST snapshots and WS deltas."""

    def __init__(
        self,
        *,
        qty_per_contract: float = NOVIG_CASH_QTY_PER_CONTRACT,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.qty_per_contract = max(1.0, float(qty_per_contract))
        self._clock = clock
        self._lock = threading.RLock()
        self._markets: dict[str, dict] = {}
        self._orders: dict[str, dict[str, dict[str, dict]]] = {}
        self._tombstones: dict[str, set[str]] = {}
        self._last_trade: dict[str, dict[str, float]] = {}
        self._updated_at: dict[str, datetime] = {}
        self._event_live: dict[str, bool] = {}

    def market_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._markets)

    def remove_absent_markets(self, market_ids: Iterable[str]) -> None:
        present = set(market_ids)
        with self._lock:
            for market_id in set(self._markets) - present:
                self._markets.pop(market_id, None)
                self._orders.pop(market_id, None)
                self._tombstones.pop(market_id, None)
                self._last_trade.pop(market_id, None)
                self._updated_at.pop(market_id, None)

    def bootstrap_market(
        self,
        market: dict,
        *,
        book: dict | None = None,
        received_at: datetime | None = None,
    ) -> None:
        market_id = _safe_text(market.get("id") or (book or {}).get("marketId"))
        if not market_id:
            raise NoVIGHTTPError("NOVIG_MARKET_ID_MISSING")
        received = (received_at or self._clock()).astimezone(timezone.utc)
        with self._lock:
            self._markets[market_id] = _public_market(market)
            event = (
                market.get("event")
                if isinstance(market.get("event"), dict)
                else {}
            )
            event_id = _market_event_id(market)
            if event_id:
                self._event_live[event_id] = (
                    _safe_text(event.get("status")).upper() == "OPEN_INGAME"
                )
            self._updated_at[market_id] = received
        if book is not None:
            self.bootstrap_book(book, market=market, received_at=received)

    def bootstrap_book(
        self,
        book: dict,
        *,
        market: dict | None = None,
        received_at: datetime | None = None,
    ) -> None:
        market_id = _safe_text(book.get("marketId") or (market or {}).get("id"))
        if not market_id:
            raise NoVIGHTTPError("NOVIG_BOOK_MARKET_ID_MISSING")
        received = (received_at or self._clock()).astimezone(timezone.utc)
        outcome_orders: dict[str, dict[str, dict]] = {}
        for ladder in book.get("outcomeLadders") or []:
            if not isinstance(ladder, dict):
                continue
            outcome_id = _safe_text(ladder.get("outcomeId"))
            if not outcome_id:
                continue
            orders: dict[str, dict] = {}
            for order in ladder.get("bids") or []:
                normalized = _normalized_order(order, market_id, outcome_id)
                if normalized is not None:
                    orders[normalized["id"]] = normalized
            outcome_orders[outcome_id] = orders
        with self._lock:
            if market is not None:
                self._markets[market_id] = _public_market(market)
            elif market_id not in self._markets:
                self._markets[market_id] = {
                    "id": market_id,
                    "description": _safe_text(book.get("marketDescription")),
                    "outcomes": [],
                    "outcomeIds": list(outcome_orders),
                }
            self._orders[market_id] = outcome_orders
            self._tombstones[market_id] = set()
            self._updated_at[market_id] = received

    def apply_message(
        self, message: dict, *, received_at: datetime | None = None
    ) -> set[str]:
        if not isinstance(message, dict):
            return set()
        received = (received_at or self._clock()).astimezone(timezone.utc)
        event = _safe_text(message.get("event")).lower()
        if event == "book":
            data = message.get("data") or {}
            book = data.get("book") if isinstance(data, dict) else None
            book = book if isinstance(book, dict) else data
            if isinstance(book, dict):
                self.bootstrap_book(book, received_at=received)
                market_id = _safe_text(book.get("marketId"))
                return {market_id} if market_id else set()
            return set()
        if event:
            return set()

        kind = _safe_text(message.get("type")).upper()
        market = message.get("market") if isinstance(message.get("market"), dict) else {}
        order = message.get("order") if isinstance(message.get("order"), dict) else {}
        market_id = _safe_text(market.get("id") or order.get("marketId"))
        event_id = _market_event_id(market)
        lifecycle = kind in {
            "OPEN",
            "START",
            "END",
            "CLOSE",
            "EVENT_GOLIVE",
            "EVENT_UNLIVE",
        }
        if not market_id and not (lifecycle and event_id):
            return set()
        changed_ids: set[str] = set()
        with self._lock:
            if market_id and market:
                previous = self._markets.get(market_id, {})
                self._markets[market_id] = {**previous, **_public_market(market)}
            if lifecycle:
                changed_ids = self._apply_lifecycle(
                    kind, market_id, event_id, market
                )
            elif kind in {"PLACE", "CANCEL"}:
                changed = self._apply_book_tick(kind, market_id, order)
                for fill in message.get("fills") or []:
                    if not isinstance(fill, dict):
                        continue
                    outcome_id = _safe_text(fill.get("outcomeId"))
                    price = _number(fill.get("price"))
                    if outcome_id and price is not None and 0 < price < 1:
                        self._last_trade.setdefault(market_id, {})[outcome_id] = price
                        changed = True
                if changed:
                    changed_ids.add(market_id)
            for changed_id in changed_ids:
                self._updated_at[changed_id] = received
        return changed_ids

    def _apply_lifecycle(
        self, kind: str, market_id: str, event_id: str, market: dict
    ) -> set[str]:
        affected = {
            candidate_id
            for candidate_id, candidate in self._markets.items()
            if event_id
            and _market_event_id(candidate) == event_id
        }
        if market_id:
            affected.add(market_id)
        if kind == "EVENT_GOLIVE":
            if event_id:
                self._event_live[event_id] = True
            # Documentation states that every resting event order is drained.
            for affected_id in affected:
                self._orders[affected_id] = {
                    outcome_id: {}
                    for outcome_id in self._orders.get(affected_id, {})
                }
            return affected
        if kind == "EVENT_UNLIVE":
            if event_id:
                self._event_live[event_id] = False
            return affected
        if kind in {"CLOSE", "END"}:
            if not market_id:
                return set()
            self._orders[market_id] = {
                outcome_id: {} for outcome_id in self._orders.get(market_id, {})
            }
            current = self._markets.setdefault(market_id, {"id": market_id})
            current["status"] = "CLOSED" if kind == "CLOSE" else current.get("status", "CLOSED")
            return {market_id}
        return {market_id} if market_id and market else set()

    def _apply_book_tick(self, kind: str, market_id: str, order: dict) -> bool:
        order_id = _safe_text(order.get("id"))
        outcome_id = _safe_text(order.get("outcomeId"))
        if not order_id:
            return False
        by_outcome = self._orders.setdefault(market_id, {})
        tombstones = self._tombstones.setdefault(market_id, set())
        if kind == "CANCEL":
            removed = False
            if outcome_id:
                removed = by_outcome.setdefault(outcome_id, {}).pop(order_id, None) is not None
            else:
                for orders in by_outcome.values():
                    removed = orders.pop(order_id, None) is not None or removed
            already_cancelled = order_id in tombstones
            tombstones.add(order_id)
            return removed or not already_cancelled

        normalized = _normalized_order(order, market_id, outcome_id)
        if normalized is None or order_id in tombstones:
            return False
        orders = by_outcome.setdefault(normalized["outcomeId"], {})
        previous = orders.get(order_id)
        if previous is not None:
            old_qty = _number(previous.get("qty")) or 0.0
            new_qty = _number(normalized.get("qty")) or 0.0
            # Remaining quantity cannot increase for the same order. This also
            # makes delayed duplicate PLACE frames harmless.
            if new_qty > old_qty + 1e-9:
                return False
            if previous == normalized:
                return False
        orders[order_id] = normalized
        return True

    def snapshot(
        self, market_id: str, *, stale_after_seconds: int = 30
    ) -> dict | None:
        with self._lock:
            market = self._markets.get(market_id)
            if market is None:
                return None
            orders = {
                outcome_id: list(rows.values())
                for outcome_id, rows in self._orders.get(market_id, {}).items()
            }
            updated = self._updated_at.get(market_id)
            last_trade = dict(self._last_trade.get(market_id, {}))
            event_live = dict(self._event_live)
            market_copy = json.loads(json.dumps(market))

        outcome_ids = _outcome_ids(market_copy, orders)
        outcomes_by_id = {
            _safe_text(outcome.get("id")): outcome
            for outcome in market_copy.get("outcomes") or []
            if isinstance(outcome, dict) and _safe_text(outcome.get("id"))
        }
        output: list[dict] = []
        for outcome_id in outcome_ids:
            other_ids = [value for value in outcome_ids if value != outcome_id]
            direct_bids = _aggregate_levels(
                orders.get(outcome_id, []),
                complement=False,
                qty_per_contract=self.qty_per_contract,
                reverse=True,
            )
            opposite_orders = [
                row for other in other_ids for row in orders.get(other, [])
            ]
            asks = _aggregate_levels(
                opposite_orders,
                complement=True,
                qty_per_contract=self.qty_per_contract,
                reverse=False,
            )
            best_bid = direct_bids[0]["price"] if direct_bids else None
            best_ask = asks[0]["price"] if asks else None
            output.append(
                {
                    "outcomeId": outcome_id,
                    "index": outcomes_by_id.get(outcome_id, {}).get("index"),
                    "description": _safe_text(
                        outcomes_by_id.get(outcome_id, {}).get("description")
                    ),
                    "bids": direct_bids,
                    "asks": asks,
                    "bestBid": best_bid,
                    "bestAsk": best_ask,
                    "spread": (
                        round(best_ask - best_bid, 6)
                        if best_ask is not None and best_bid is not None
                        else None
                    ),
                    "lastTradedPrice": last_trade.get(outcome_id)
                    if outcome_id in last_trade
                    else _number(outcomes_by_id.get(outcome_id, {}).get("last")),
                    "availableLiquidity": round(
                        sum(float(level["liquidityDollars"]) for level in asks), 2
                    ),
                }
            )
        age = (
            max(0.0, (self._clock().astimezone(timezone.utc) - updated).total_seconds())
            if updated is not None
            else None
        )
        event = (
            market_copy.get("event")
            if isinstance(market_copy.get("event"), dict)
            else {}
        )
        event_id = _market_event_id(market_copy)
        return {
            "provider": "novig",
            "marketId": market_id,
            "eventId": event_id,
            "market": market_copy,
            "outcomes": output,
            "marketVolumeRaw": _number(market_copy.get("volume")),
            "currency": "CASH",
            "qtyPerContract": self.qty_per_contract,
            "eventLive": event_live.get(
                event_id, _safe_text(event.get("status")).upper() == "OPEN_INGAME"
            ),
            "timestamp": updated.isoformat() if updated else None,
            "ageSeconds": round(age, 3) if age is not None else None,
            "stale": age is None or age > max(1, int(stale_after_seconds)),
        }

    def snapshots(self, *, stale_after_seconds: int = 30) -> list[dict]:
        return [
            snapshot
            for market_id in self.market_ids()
            if (
                snapshot := self.snapshot(
                    market_id, stale_after_seconds=stale_after_seconds
                )
            )
            is not None
        ]


def _normalized_order(
    order: object, market_id: str, outcome_id: str
) -> dict | None:
    if not isinstance(order, dict):
        return None
    order_id = _safe_text(order.get("id"))
    resolved_outcome = _safe_text(order.get("outcomeId") or outcome_id)
    price = _number(order.get("price"))
    qty = _number(order.get("qty"))
    status = _safe_text(order.get("status")).upper()
    if (
        not order_id
        or not resolved_outcome
        or price is None
        or not 0 < price < 1
        or qty is None
        or qty <= 0
        or status in {"CANCELLED", "CANCELED", "FILLED", "CLOSED"}
    ):
        return None
    return {
        "id": order_id,
        "price": price,
        "qty": qty,
        "originalQty": _number(order.get("originalQty")),
        "currency": _safe_text(order.get("currency") or "CASH").upper(),
        "marketId": _safe_text(order.get("marketId") or market_id),
        "outcomeId": resolved_outcome,
        "status": status or "OPEN",
        "created_at": _safe_text(order.get("created_at")) or None,
    }


def _outcome_ids(market: dict, orders: dict[str, list[dict]]) -> list[str]:
    outcomes = sorted(
        (
            row
            for row in market.get("outcomes") or []
            if isinstance(row, dict) and _safe_text(row.get("id"))
        ),
        key=lambda row: (
            _number(row.get("index")) if _number(row.get("index")) is not None else 99,
            _safe_text(row.get("id")),
        ),
    )
    return list(
        dict.fromkeys(
            [
                *[_safe_text(row.get("id")) for row in outcomes],
                *[
                    _safe_text(value)
                    for value in market.get("outcomeIds") or []
                    if _safe_text(value)
                ],
                *orders.keys(),
            ]
        )
    )


def _aggregate_levels(
    orders: Iterable[dict],
    *,
    complement: bool,
    qty_per_contract: float,
    reverse: bool,
) -> list[dict]:
    grouped: dict[float, float] = {}
    for order in orders:
        price = _number(order.get("price"))
        qty = _number(order.get("qty"))
        if price is None or qty is None or qty <= 0:
            continue
        normalized_price = 1.0 - price if complement else price
        if not 0 < normalized_price < 1:
            continue
        key = round(normalized_price, 6)
        grouped[key] = grouped.get(key, 0.0) + qty
    cumulative = 0.0
    levels: list[dict] = []
    for price in sorted(grouped, reverse=reverse):
        qty = grouped[price]
        contracts = qty / qty_per_contract
        liquidity = price * contracts
        cumulative += liquidity
        levels.append(
            {
                "price": price,
                "americanOdds": probability_to_american(price),
                "quantityMcu": qty,
                "contracts": contracts,
                "size": contracts,
                "liquidityDollars": round(liquidity, 5),
                "cumulativeDepthDollars": round(cumulative, 5),
            }
        )
    return levels


def _public_market(market: dict) -> dict:
    allowed = {
        "id",
        "description",
        "status",
        "strike",
        "type",
        "league",
        "volume",
        "eventId",
        "event",
        "outcomeIds",
        "outcomes",
        "playerId",
        "player",
        "competitor",
        "settledAt",
        "isConsensus",
    }
    return {
        key: json.loads(json.dumps(value))
        for key, value in market.items()
        if key in allowed
    }


class NoVIGStateStore:
    """Shared PostgreSQL state used by the feed worker and serverless API."""

    def __init__(self, database_url: str | None) -> None:
        self.database_url = _safe_text(database_url) or None
        self._initialized = False
        self._lock = threading.RLock()
        self._last_error_code: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.database_url)

    def __repr__(self) -> str:
        return f"<NoVIGStateStore configured={self.configured} initialized={self._initialized}>"

    def _connect(self):
        if not self.database_url:
            raise NoVIGConfigurationError("NOVIG_STATE_STORE_NOT_CONFIGURED")
        try:
            import psycopg

            return psycopg.connect(self.database_url, connect_timeout=5)
        except Exception as exc:
            raise NoVIGError("NOVIG_STATE_STORE_CONNECTION_FAILED") from exc

    def initialize(self) -> None:
        if not self.configured:
            return
        with self._lock:
            if self._initialized:
                return
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS novig_market_state (
                        market_id TEXT PRIMARY KEY,
                        event_id TEXT,
                        league TEXT,
                        market_type TEXT,
                        state_json JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS novig_market_state_event_idx
                    ON novig_market_state (event_id, league, market_type)
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS novig_feed_status (
                        provider TEXT PRIMARY KEY,
                        status_json JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                conn.commit()
            self._initialized = True
            self._last_error_code = None

    def save_markets(self, snapshots: Iterable[dict]) -> int:
        rows = [row for row in snapshots if isinstance(row, dict) and row.get("marketId")]
        if not rows or not self.configured:
            return 0
        self.initialize()
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    for row in rows:
                        market = row.get("market") or {}
                        cursor.execute(
                            """
                            INSERT INTO novig_market_state (
                                market_id, event_id, league, market_type,
                                state_json, updated_at
                            ) VALUES (%s, %s, %s, %s, %s::jsonb, NOW())
                            ON CONFLICT (market_id) DO UPDATE SET
                                event_id = EXCLUDED.event_id,
                                league = EXCLUDED.league,
                                market_type = EXCLUDED.market_type,
                                state_json = EXCLUDED.state_json,
                                updated_at = NOW()
                            """,
                            (
                                row["marketId"],
                                row.get("eventId"),
                                market.get("league"),
                                market.get("type"),
                                json.dumps(row, separators=(",", ":")),
                            ),
                        )
                conn.commit()
            self._last_error_code = None
            return len(rows)
        except NoVIGError:
            self._last_error_code = "NOVIG_STATE_STORE_WRITE_FAILED"
            raise
        except Exception as exc:
            self._last_error_code = "NOVIG_STATE_STORE_WRITE_FAILED"
            raise NoVIGError("NOVIG_STATE_STORE_WRITE_FAILED") from exc

    def delete_absent_markets(self, market_ids: Iterable[str]) -> None:
        ids = list(dict.fromkeys(_validated_identifier(value) for value in market_ids))
        if not self.configured:
            return
        self.initialize()
        with self._connect() as conn:
            if ids:
                conn.execute(
                    "DELETE FROM novig_market_state WHERE NOT (market_id = ANY(%s))",
                    (ids,),
                )
            else:
                conn.execute("DELETE FROM novig_market_state")
            conn.commit()

    def load_markets(
        self,
        *,
        league: str | None = None,
        market_type: str | None = None,
        limit: int = 5000,
    ) -> list[dict]:
        if not self.configured:
            return []
        try:
            self.initialize()
            clauses = []
            params: list[object] = []
            if league:
                clauses.append("UPPER(league) = UPPER(%s)")
                params.append(league)
            if market_type:
                clauses.append("UPPER(market_type) = UPPER(%s)")
                params.append(market_type)
            params.append(max(1, min(int(limit), 10000)))
            where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            with self._connect() as conn:
                rows = conn.execute(
                    f"SELECT state_json FROM novig_market_state{where} "
                    "ORDER BY updated_at DESC LIMIT %s",
                    params,
                ).fetchall()
            self._last_error_code = None
            return [
                row[0] if isinstance(row[0], dict) else json.loads(row[0])
                for row in rows
            ]
        except Exception:
            self._last_error_code = "NOVIG_STATE_STORE_READ_FAILED"
            return []

    def load_market(self, market_id: str) -> dict | None:
        if not self.configured:
            return None
        try:
            self.initialize()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT state_json FROM novig_market_state WHERE market_id = %s",
                    (_validated_identifier(market_id),),
                ).fetchone()
            self._last_error_code = None
            if row is None:
                return None
            return row[0] if isinstance(row[0], dict) else json.loads(row[0])
        except Exception:
            self._last_error_code = "NOVIG_STATE_STORE_READ_FAILED"
            return None

    def save_status(self, status: dict) -> None:
        if not self.configured:
            return
        self.initialize()
        safe = _sanitize_status(status)
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO novig_feed_status (provider, status_json, updated_at)
                    VALUES ('novig', %s::jsonb, NOW())
                    ON CONFLICT (provider) DO UPDATE SET
                        status_json = EXCLUDED.status_json,
                        updated_at = NOW()
                    """,
                    (json.dumps(safe, separators=(",", ":")),),
                )
                conn.commit()
            self._last_error_code = None
        except Exception as exc:
            self._last_error_code = "NOVIG_STATE_STORE_STATUS_WRITE_FAILED"
            raise NoVIGError("NOVIG_STATE_STORE_STATUS_WRITE_FAILED") from exc

    def load_status(self) -> dict:
        if not self.configured:
            return {}
        try:
            self.initialize()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT status_json, updated_at FROM novig_feed_status "
                    "WHERE provider = 'novig'"
                ).fetchone()
            self._last_error_code = None
            if row is None:
                return {}
            payload = row[0] if isinstance(row[0], dict) else json.loads(row[0])
            payload["state_updated_at"] = row[1].isoformat() if row[1] else None
            return _sanitize_status(payload)
        except Exception:
            self._last_error_code = "NOVIG_STATE_STORE_STATUS_READ_FAILED"
            return {}

    def diagnostics(self) -> dict:
        return {
            "configured": self.configured,
            "initialized": self._initialized,
            "last_error_code": self._last_error_code,
            "credentials_exposed": False,
        }


def _sanitize_status(status: dict) -> dict:
    allowed = {
        "status",
        "connected",
        "last_message_at",
        "last_bootstrap_at",
        "last_disconnect_at",
        "active_market_count",
        "reconnect_count",
        "message_count",
        "book_snapshot_count",
        "token_refresh_count",
        "last_error_code",
        "stale",
        "state_updated_at",
    }
    return {
        **{key: value for key, value in status.items() if key in allowed},
        "credentials_exposed": False,
        "token_exposed": False,
    }


@dataclass
class _DirectCache:
    loaded_at: float
    snapshots: list[dict]
    index: ProviderMarketIndex


class NoVIGNBXProvider(ExecutionProvider):
    """Read-only NoVIG NBX exchange provider."""

    provider_name = "NoVIG"
    # Kept distinct from the legacy SportsGameOdds-backed provider object.
    # Serialized options still use the canonical `novig` key.
    provider_key = "novig_nbx"

    def __init__(
        self,
        client_id: str | None,
        client_secret: str | None,
        *,
        enabled: bool = True,
        auth_url: str = NOVIG_AUTH_URL,
        base_url: str = NOVIG_REST_BASE_URL,
        websocket_url: str = NOVIG_WEBSOCKET_URL,
        state_database_url: str | None = None,
        cache_ttl_seconds: int = 10,
        stale_after_seconds: int = 30,
        request_timeout: float = 5.0,
        session: requests.Session | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.enabled = bool(enabled)
        self.websocket_url = websocket_url
        self.cache_ttl_seconds = max(1, int(cache_ttl_seconds))
        self.stale_after_seconds = max(1, int(stale_after_seconds))
        self._monotonic = monotonic
        shared_session = session or requests.Session()
        self.auth = NoVIGAuthClient(
            client_id,
            client_secret,
            auth_url=auth_url,
            timeout=request_timeout,
            session=shared_session,
            monotonic=monotonic,
        )
        self.rest = NoVIGRestClient(
            self.auth,
            base_url=base_url,
            timeout=min(float(request_timeout), 5.0),
            session=shared_session,
        )
        self.state_store = NoVIGStateStore(state_database_url)
        self._lock = threading.RLock()
        self._cache: _DirectCache | None = None
        self._snapshot_by_market: dict[str, dict] = {}
        self._last_success: str | None = None
        self._market_count = 0
        self._exact_match_count = 0
        self.failure_reasons: dict[str, str] = {}
        self._unmatched: deque[dict] = deque(maxlen=200)

    def __repr__(self) -> str:
        return (
            f"<NoVIGNBXProvider enabled={self.enabled} "
            f"configured={self.configured} read_only=True>"
        )

    @property
    def configured(self) -> bool:
        return self.enabled and self.auth.configured

    def invalidate_cache(self) -> None:
        with self._lock:
            self._cache = None
            self._snapshot_by_market.clear()

    def options_for_trades(self, trades: list[dict]) -> dict[str, ExecutionOption]:
        canonical = [row for trade in trades if (row := canonicalize_trade(trade))]
        self.failure_reasons = {}
        if not self.configured or not canonical:
            if canonical and not self.configured:
                self.failure_reasons = {
                    row.trade_id: "PROVIDER_NOT_CONFIGURED" for row in canonical
                }
            return {}
        originals = {str(row.get("id") or ""): row for row in trades}
        try:
            index = self._index(canonical)
        except NoVIGError as exc:
            LOGGER.warning("NoVIG NBX refresh failed: %s", exc.code)
            self.failure_reasons = {
                row.trade_id: "PROVIDER_UNAVAILABLE" for row in canonical
            }
            return {}
        result: dict[str, ExecutionOption] = {}
        for trade in canonical:
            confidence, matched = _match_exact_trade(trade, index)
            if confidence is not MatchConfidence.EXACT or matched is None:
                reason = (
                    "MARKET_MAPPING_UNCERTAIN"
                    if confidence is MatchConfidence.PROBABLE
                    else "MARKET_NOT_FOUND"
                )
                self.failure_reasons[trade.trade_id] = reason
                self._record_unmatched(trade, confidence, reason)
                continue
            market_id, outcome_id = _selection_parts(matched.selection_id)
            snapshot = self._snapshot_by_market.get(market_id)
            if snapshot is None:
                self.failure_reasons[trade.trade_id] = "NO_LIQUIDITY"
                continue
            option = self._option_from_snapshot(
                matched,
                snapshot,
                outcome_id,
                _recommended_stake(originals.get(trade.trade_id) or {}),
            )
            result[trade.trade_id] = option
        self._exact_match_count = len(result)
        return result

    def fair_price_quotes(self, trades: list[dict]) -> dict[str, dict]:
        canonical = [row for trade in trades if (row := canonicalize_trade(trade))]
        if not self.configured or not canonical:
            return {}
        try:
            return _fair_quotes_from_index(canonical, self._index(canonical), "novig")
        except NoVIGError:
            return {}

    def sharp_money_direct_snapshot(self, *, limit: int = 40) -> dict:
        """Return a bounded two-sided NBX slate without a sportsbook seed feed.

        Sharp Money normally uses OddsEngine prices to identify the retail
        market before matching exact NoVIG depth. This direct snapshot is the
        reliability fallback for a temporary OddsEngine throttle: it keeps
        verified NBX liquidity visible instead of returning an empty page.
        """
        if not self.configured:
            return {}
        bounded = max(1, min(int(limit), 100))
        snapshots = [
            row
            for row in self._state_snapshots([])
            if not row.get("stale")
            and _safe_text((row.get("market") or {}).get("status")).upper()
            == "OPEN"
        ]
        if not snapshots:
            snapshots = self._rest_snapshots([], limit=min(bounded * 2, 100))

        def imbalance(row: dict) -> float:
            liquidity = []
            for outcome in row.get("outcomes") or []:
                asks = outcome.get("asks") or []
                best = _number(outcome.get("bestAsk"))
                liquidity.append(
                    sum(
                        _number(level.get("liquidityDollars")) or 0.0
                        for level in asks
                        if best is not None
                        and _number(level.get("price")) is not None
                        and abs((_number(level.get("price")) or 0.0) - best) < 1e-9
                    )
                )
            return abs(liquidity[0] - liquidity[1]) if len(liquidity) == 2 else 0.0

        eligible = [
            row
            for row in snapshots
            if not row.get("stale")
            and _sharp_money_market_supported(row.get("market") or {})
            and len(row.get("outcomes") or []) == 2
            and imbalance(row) > 0
        ]
        eligible.sort(key=imbalance, reverse=True)
        return {
            "observedAt": _iso_now(),
            "snapshots": eligible[:bounded],
            "transport": "novig_nbx_direct",
        }

    def _index(self, trades: list) -> ProviderMarketIndex:
        now = self._monotonic()
        with self._lock:
            if self._cache and now - self._cache.loaded_at < self.cache_ttl_seconds:
                return self._cache.index
        leagues = sorted({str(row.league_id).upper() for row in trades})
        snapshots = self._state_snapshots(leagues)
        if not snapshots:
            snapshots = self._rest_snapshots(leagues)
        normalized = [
            item
            for snapshot in snapshots
            for item in normalize_novig_snapshot(snapshot)
        ]
        index = ProviderMarketIndex(normalized)
        with self._lock:
            self._snapshot_by_market = {
                str(row.get("marketId")): row for row in snapshots if row.get("marketId")
            }
            self._cache = _DirectCache(now, snapshots, index)
            self._market_count = len(snapshots)
            self._last_success = _iso_now()
        return index

    def _state_snapshots(self, leagues: list[str]) -> list[dict]:
        if not self.state_store.configured:
            return []
        rows = self.state_store.load_markets(limit=10000)
        worker = self.state_store.load_status()
        disconnected = bool(worker) and not bool(worker.get("connected"))
        wanted = set(leagues)
        return [
            _with_staleness(
                row,
                self.stale_after_seconds,
                force_stale=disconnected,
            )
            for row in rows
            if not wanted
            or _safe_text((row.get("market") or {}).get("league")).upper() in wanted
        ]

    def _rest_snapshots(
        self, leagues: list[str], *, limit: int | None = None
    ) -> list[dict]:
        markets: list[dict] = []
        if leagues:
            for league in leagues:
                markets.extend(self.rest.list_open_markets(league=league))
        else:
            markets = self.rest.list_open_markets()
        events: list[dict] = []
        if limit is not None:
            # The unfiltered open-market catalog is not ordered by recency and
            # can begin with hundreds of stale futures or already-final props.
            # Query the two active event states first so Sharp Money spends its
            # bounded book request on current, two-sided game markets.
            try:
                for event_status in SHARP_MONEY_OPEN_EVENT_STATUSES:
                    try:
                        if hasattr(self.rest, "list_events_page"):
                            events.extend(
                                self.rest.list_events_page(
                                    event_status=event_status,
                                    limit=100,
                                    offset=0,
                                )
                            )
                        else:
                            events.extend(
                                self.rest.list_events(event_status=event_status)
                            )
                    except NoVIGError:
                        continue
            except TypeError:
                # Preserve compatibility with lightweight provider fakes and
                # older adapters that do not accept event filters.
                try:
                    events = self.rest.list_events()
                except NoVIGError:
                    events = []
        elif leagues:
            try:
                for league in leagues:
                    for event_status in SHARP_MONEY_OPEN_EVENT_STATUSES:
                        try:
                            if hasattr(self.rest, "list_events_page"):
                                events.extend(
                                    self.rest.list_events_page(
                                        league=league,
                                        event_status=event_status,
                                        limit=100,
                                        offset=0,
                                    )
                                )
                            else:
                                events.extend(
                                    self.rest.list_events(
                                        league=league,
                                        event_status=event_status,
                                    )
                                )
                        except NoVIGError:
                            continue
            except TypeError:
                try:
                    events = self.rest.list_events()
                except NoVIGError:
                    events = []
        else:
            try:
                events = self.rest.list_events()
            except NoVIGError:
                events = []
        markets = enrich_novig_markets(markets, events)
        selected_market_ids: set[str] | None = None
        if limit is not None:
            bounded = max(1, min(int(limit), 1000))
            markets = [
                row for row in markets if _sharp_money_market_supported(row)
            ]
            markets.sort(key=_sharp_money_market_priority)
            markets = markets[:bounded]
            selected_market_ids = {
                _safe_text(row.get("id"))
                for row in markets
                if _safe_text(row.get("id"))
            }
        elif leagues and events:
            active_event_ids = {
                _safe_text(row.get("id") or row.get("eventId"))
                for row in events
                if isinstance(row, dict)
                and _safe_text(row.get("id") or row.get("eventId"))
            }
            markets = [
                row
                for row in markets
                if _market_event_id(row) in active_event_ids
            ]
        event_ids = list(
            dict.fromkeys(
                _safe_text(row.get("eventId"))
                for row in markets
                if _safe_text(row.get("eventId"))
            )
        )
        with_books = self.rest.get_markets_by_events(event_ids) if event_ids else []
        if not with_books:
            with_books = markets
        else:
            with_books = enrich_novig_markets(with_books, events)
            if selected_market_ids is not None:
                with_books = [
                    row
                    for row in with_books
                    if _safe_text(row.get("id")) in selected_market_ids
                ]
        engine = NoVIGOrderBookState()
        for market in with_books:
            book = market.get("book") if isinstance(market.get("book"), dict) else None
            if book is None:
                try:
                    book = self.rest.get_book(_safe_text(market.get("id")))
                except NoVIGError:
                    book = None
            engine.bootstrap_market(market, book=book)
        return engine.snapshots(stale_after_seconds=self.stale_after_seconds)

    def _option_from_snapshot(
        self,
        matched: NormalizedProviderMarket,
        snapshot: dict,
        outcome_id: str,
        stake: float,
    ) -> ExecutionOption:
        outcome = next(
            (
                row
                for row in snapshot.get("outcomes") or []
                if _safe_text(row.get("outcomeId")) == outcome_id
            ),
            {},
        )
        asks = [row for row in outcome.get("asks") or [] if isinstance(row, dict)]
        quote = _walk_depth(asks, stake, event_live=bool(snapshot.get("eventLive")))
        market = snapshot.get("market") or {}
        top_price = _number(outcome.get("bestAsk"))
        market_open = _safe_text(market.get("status")).upper() == "OPEN"
        stale = bool(snapshot.get("stale"))
        available = bool(market_open and not stale and top_price is not None and asks)
        market_id = _safe_text(snapshot.get("marketId"))
        # NBX market payloads do not document a consumer-web deep-link field.
        # Use NoVIG's verified public root rather than fabricate an outcome URL.
        deep_link = NOVIG_WEB_URL
        american = probability_to_american(top_price)
        return ExecutionOption(
            provider_name=self.provider_name,
            provider_key="novig",
            market_id=market_id,
            selection_id=outcome_id,
            display_odds=_format_cents(top_price) if available else "Unavailable",
            deep_link=deep_link,
            is_available=available,
            last_updated=_safe_text(snapshot.get("timestamp")) or None,
            matching_confidence=MatchConfidence.EXACT,
            logo_url=NOVIG_LOGO_URL,
            tooltip="NoVIG NBX read-only executable order book",
            american_odds=american,
            contract_price=top_price,
            effective_price=quote["effective_price"],
            available_liquidity=quote["available_liquidity"],
            can_fill_recommended_stake=quote["fillable"],
            fee_rate=quote["fee_rate"],
            estimated_fees=quote["estimated_fee"],
            quote_status="OPEN" if market_open else _safe_text(market.get("status")),
            provider_event_id=_safe_text(snapshot.get("eventId")) or matched.event_id,
            native_price_format="CENTS",
            top_price=top_price,
            top_price_american_odds=american,
            top_price_liquidity=(
                _number(asks[0].get("liquidityDollars")) if asks else None
            ),
            depth_vwap_price=quote["effective_price"],
            depth_executable_amount=quote["available_liquidity"],
            depth_levels_used=quote["levels_used"],
            quote_max_age_seconds=self.stale_after_seconds,
            order_book={
                "asks": asks,
                "bids": outcome.get("bids") or [],
                "timestamp": snapshot.get("timestamp"),
                "min_order_size": 0.01,
                "tick_size": None,
                "market_id": market_id,
                "outcome_id": outcome_id,
                "stale": stale,
            },
            order_book_url=(
                f"/api/providers/novig/book/{quote_url(market_id)}"
                f"?outcome_id={quote_url(outcome_id)}"
            ),
        )

    def market_catalog(
        self,
        *,
        league: str | None = None,
        market_type: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        if not self.configured:
            return []
        rows = self.state_store.load_markets(
            league=league, market_type=market_type, limit=limit
        )
        worker = self.state_store.load_status()
        disconnected = bool(worker) and not bool(worker.get("connected"))
        rows = [
            _with_staleness(
                row,
                self.stale_after_seconds,
                force_stale=disconnected,
            )
            for row in rows
        ]
        if not rows:
            markets = self.rest.list_open_markets(
                league=league, market_type=market_type
            )[: max(1, min(int(limit), 1000))]
            try:
                events = self.rest.list_events(league=league)
            except NoVIGError:
                events = []
            markets = enrich_novig_markets(markets, events)
            rows = [
                {
                    "marketId": market.get("id"),
                    "eventId": market.get("eventId"),
                    "market": _public_market(market),
                    "outcomes": [],
                    "timestamp": self.rest.last_success_at,
                    "stale": False,
                }
                for market in markets
            ]
        return [normalized_catalog_record(row) for row in rows[:limit]]

    def public_book(self, market_id: str, *, outcome_id: str | None = None) -> dict:
        validated = _validated_identifier(market_id)
        snapshot = self.state_store.load_market(validated)
        if snapshot is not None:
            worker = self.state_store.load_status()
            snapshot = _with_staleness(
                snapshot,
                self.stale_after_seconds,
                force_stale=bool(worker) and not bool(worker.get("connected")),
            )
        if snapshot is None:
            market = self.rest.get_market(validated)
            book = self.rest.get_book(validated)
            engine = NoVIGOrderBookState()
            engine.bootstrap_market(market, book=book)
            snapshot = engine.snapshot(
                validated, stale_after_seconds=self.stale_after_seconds
            )
        if snapshot is None:
            raise NoVIGHTTPError("NOVIG_BOOK_NOT_FOUND", status_code=404)
        if outcome_id:
            validated_outcome = _validated_identifier(outcome_id)
            snapshot = dict(snapshot)
            snapshot["outcomes"] = [
                row
                for row in snapshot.get("outcomes") or []
                if _safe_text(row.get("outcomeId")) == validated_outcome
            ]
        return snapshot

    def unmatched_report(self) -> dict:
        with self._lock:
            return {
                "provider": "novig",
                "count": len(self._unmatched),
                "records": list(self._unmatched),
                "credentials_exposed": False,
                "token_exposed": False,
            }

    def _record_unmatched(self, trade, confidence, reason: str) -> None:
        record = {
            "observed_at": _iso_now(),
            "trade_id": trade.trade_id,
            "sport": trade.sport_id,
            "league": trade.league_id,
            "start_time": trade.start_at.isoformat(),
            "participants": list(trade.participants),
            "market_type": trade.market_kind,
            "period": trade.period_id,
            "line": trade.line,
            "side": trade.side_id,
            "confidence": confidence.value,
            "reason": reason,
        }
        with self._lock:
            if not self._unmatched or self._unmatched[-1] != record:
                self._unmatched.append(record)

    def diagnostics(self, *, authenticate: bool = False) -> dict:
        smoke = self.rest.credential_smoke_test(sample_size=2) if authenticate and self.configured else None
        worker = self.state_store.load_status()
        status = "NOT_CONFIGURED"
        if self.configured:
            if worker:
                status = (
                    "CONNECTED"
                    if worker.get("connected") and not worker.get("stale")
                    else "DISCONNECTED"
                )
            elif self._last_success:
                status = "REST_FALLBACK"
            else:
                status = "CONFIGURED"
        return {
            "provider": "novig",
            "status": status,
            "configured": self.configured,
            "enabled": self.enabled,
            "read_only": True,
            "trading_enabled": False,
            "last_successful_request": self._last_success or self.rest.last_success_at,
            "active_market_count": self._market_count or worker.get("active_market_count", 0),
            "exact_market_matches": self._exact_match_count,
            "unmatched_record_count": len(self._unmatched),
            "auth": self.auth.status(),
            "rest": {
                "last_http_status": self.rest.last_http_status,
                "request_count": self.rest.request_count,
                "rate_limit_count": self.rest.rate_limit_count,
                "reauthentication_count": self.rest.reauthentication_count,
            },
            "worker": worker,
            "state_store": self.state_store.diagnostics(),
            "smoke_test": smoke,
            "credentials_exposed": False,
            "token_exposed": False,
        }

    def health_status(self, *, authenticate: bool = False) -> ProviderHealthStatus:
        if not self.configured:
            return ProviderHealthStatus.UNAUTHORIZED
        if not authenticate:
            return ProviderHealthStatus.CONFIGURED
        smoke = self.rest.credential_smoke_test(sample_size=0)
        if smoke.get("success"):
            return ProviderHealthStatus.AUTHENTICATED
        if smoke.get("http_status") == 401:
            return ProviderHealthStatus.UNAUTHORIZED
        return ProviderHealthStatus.CONNECTION_FAILED

    def place_order(self, *args, **kwargs):
        raise PermissionError("NoVIG trading is disabled; market data is read-only")

    def cancel_order(self, *args, **kwargs):
        raise PermissionError("NoVIG trading is disabled; market data is read-only")


def quote_url(value: object) -> str:
    return quote(_validated_identifier(value), safe="")


def enrich_novig_markets(
    markets: Iterable[dict], events: Iterable[dict]
) -> list[dict]:
    events_by_id = {
        _safe_text(event.get("id") or event.get("eventId")): event
        for event in events
        if isinstance(event, dict)
        and _safe_text(event.get("id") or event.get("eventId"))
    }
    enriched: list[dict] = []
    for market in markets:
        if not isinstance(market, dict):
            continue
        event_id = _market_event_id(market)
        embedded = market.get("event")
        event = dict(embedded) if isinstance(embedded, dict) else {}
        catalog_event = events_by_id.get(event_id)
        if isinstance(catalog_event, dict):
            # The open-market response sometimes embeds only an event id or a
            # stale status. The filtered event catalog is the authoritative
            # source for current status, schedule, and team metadata.
            event = {**event, **catalog_event}
        enriched.append(
            {**market, "event": json.loads(json.dumps(event))}
            if isinstance(event, dict) and event
            else dict(market)
        )
    return enriched


def _sharp_money_market_supported(market: dict) -> bool:
    """Return whether a NoVIG market can form a truthful two-sided game row."""
    if not isinstance(market, dict):
        return False
    market_id = _safe_text(market.get("id"))
    event_id = _market_event_id(market)
    if not market_id or not event_id:
        return False
    if _safe_text(market.get("status")).upper() != "OPEN":
        return False
    if _safe_text(market.get("type")).upper() not in SHARP_MONEY_MARKET_TYPES:
        return False
    outcomes = market.get("outcomes") or market.get("outcomeIds") or []
    if len(outcomes) != 2:
        return False
    event = market.get("event") if isinstance(market.get("event"), dict) else {}
    event_status = _safe_text(event.get("status")).upper()
    if event_status in TERMINAL_EVENT_STATUSES:
        return False
    game = event.get("game") if isinstance(event.get("game"), dict) else {}
    home = _team_names(game.get("homeTeam"))
    away = _team_names(game.get("awayTeam"))
    if home and away:
        return True
    description = _safe_text(market.get("description"))
    return len([part for part in description.split(" vs ") if part.strip()]) == 2


def _sharp_money_market_priority(market: dict) -> tuple[object, ...]:
    """Prefer live and near-term main game markets deterministically."""
    event = market.get("event") if isinstance(market.get("event"), dict) else {}
    game = event.get("game") if isinstance(event.get("game"), dict) else {}
    status = _safe_text(event.get("status")).upper()
    status_rank = {
        "OPEN_INGAME": 0,
        "OPEN_PREGAME": 1,
    }.get(status, 2)
    start = _parse_datetime(
        event.get("scheduledStart") or game.get("scheduledStart")
    )
    if start is None:
        start_rank = float("inf")
    else:
        delta = (start - _utc_now()).total_seconds()
        # A provider can briefly leave a started pregame event open. Keep it
        # close to current games, but push genuinely stale records behind all
        # upcoming events.
        start_rank = (
            abs(delta) if delta >= -(8 * 60 * 60) else 1e12 + abs(delta)
        )
    market_type = _safe_text(market.get("type")).upper()
    type_rank = {
        "MONEY": 0,
        "MONEYLINE": 0,
        "SPREAD": 1,
        "TOTAL": 2,
        "MONEY_1H": 3,
        "MONEYLINE_1H": 3,
        "SPREAD_1H": 4,
        "TOTAL_1H": 5,
    }.get(market_type, 9)
    return status_rank, start_rank, type_rank, _safe_text(market.get("id"))


def normalize_novig_snapshot(snapshot: dict) -> list[NormalizedProviderMarket]:
    market = snapshot.get("market") if isinstance(snapshot.get("market"), dict) else {}
    event = market.get("event") if isinstance(market.get("event"), dict) else {}
    game = event.get("game") if isinstance(event.get("game"), dict) else {}
    market_id = _safe_text(snapshot.get("marketId") or market.get("id"))
    event_id = _safe_text(snapshot.get("eventId") or market.get("eventId") or event.get("id"))
    league = _safe_text(market.get("league") or event.get("league") or game.get("league"))
    start_at = _parse_datetime(
        event.get("scheduledStart") or game.get("scheduledStart")
    )
    home_names = _team_names(game.get("homeTeam"))
    away_names = _team_names(game.get("awayTeam"))
    if not all((market_id, event_id, league, start_at, home_names, away_names)):
        return []
    market_type = _safe_text(market.get("type")).upper()
    market_name, bet_type, period, settlement = _market_shape(market_type, league)
    if not market_name or not settlement:
        return []
    outcomes = {
        _safe_text(row.get("outcomeId")): row
        for row in snapshot.get("outcomes") or []
        if isinstance(row, dict) and _safe_text(row.get("outcomeId"))
    }
    result: list[NormalizedProviderMarket] = []
    for raw in market.get("outcomes") or []:
        if not isinstance(raw, dict):
            continue
        outcome_id = _safe_text(raw.get("id"))
        index_number = _number(raw.get("index"))
        index = int(index_number) if index_number is not None else -1
        if not outcome_id or index not in {0, 1}:
            continue
        side = _outcome_side(market_type, index)
        if side is None:
            continue
        line = _outcome_line(market_type, market.get("strike"), raw, index)
        book = outcomes.get(outcome_id, {})
        price = _number(book.get("bestAsk"))
        american = probability_to_american(price)
        player = market.get("player") or {}
        competitor = market.get("competitor") or {}
        stat_entity = _normalize_identifier(
            player.get("name")
            or player.get("fullName")
            or competitor.get("name")
            or ("all" if market_name in {"moneyline", "spread", "game_total"} else "")
        ).lower()
        result.append(
            NormalizedProviderMarket(
                event_id=event_id,
                selection_id=f"{market_id}|{outcome_id}",
                sport_id=_sport_from_league(league),
                league_id=_normalize_identifier(league).upper(),
                start_at=start_at,
                home_names=home_names,
                away_names=away_names,
                market_name=market_name,
                stat_id="points" if market_name in {"moneyline", "spread", "game_total", "team_total"} else _normalize_identifier(market_type).lower(),
                stat_entity_id=stat_entity,
                period_id=period,
                bet_type_id=bet_type,
                side_id=side,
                line=line,
                is_alternative=(
                    market.get("isConsensus") is False
                    if market.get("isConsensus") is not None
                    else False
                ),
                display_odds=_format_cents(price),
                american_odds=american,
                deep_link=NOVIG_WEB_URL,
                is_available=bool(
                    _safe_text(market.get("status")).upper() == "OPEN"
                    and price is not None
                    and not snapshot.get("stale")
                ),
                last_updated=_safe_text(snapshot.get("timestamp")) or None,
                settlement_rules=settlement,
            )
        )
    return result


def normalized_catalog_record(snapshot: dict) -> dict:
    market = snapshot.get("market") or {}
    event = market.get("event") or {}
    game = event.get("game") or {}
    outcomes = []
    raw_outcomes = {
        _safe_text(row.get("id")): row
        for row in market.get("outcomes") or []
        if isinstance(row, dict)
    }
    for book in snapshot.get("outcomes") or []:
        outcome_id = _safe_text(book.get("outcomeId"))
        raw = raw_outcomes.get(outcome_id, {})
        best_ask = _number(book.get("bestAsk"))
        outcomes.append(
            {
                "outcomeId": outcome_id,
                "index": raw.get("index"),
                "outcome": _safe_text(raw.get("description") or book.get("description")),
                "side": _outcome_side(_safe_text(market.get("type")).upper(), int(_number(raw.get("index")) or 0)),
                "probabilityPrice": best_ask,
                "americanOdds": probability_to_american(best_ask),
                "availableLiquidity": _number(book.get("availableLiquidity")),
                "bestBid": _number(book.get("bestBid")),
                "bestAsk": best_ask,
                "spread": _number(book.get("spread")),
                "lastTradedPrice": _number(book.get("lastTradedPrice")),
            }
        )
    player = market.get("player") or {}
    return {
        "provider": "novig",
        "eventId": snapshot.get("eventId") or market.get("eventId"),
        "marketId": snapshot.get("marketId") or market.get("id"),
        "league": market.get("league") or event.get("league") or game.get("league"),
        "startTime": event.get("scheduledStart") or game.get("scheduledStart"),
        "homeCompetitor": _safe_text((game.get("homeTeam") or {}).get("name")),
        "awayCompetitor": _safe_text((game.get("awayTeam") or {}).get("name")),
        "playerName": _safe_text(player.get("name") or player.get("fullName")) or None,
        "marketType": market.get("type"),
        "line": market.get("strike"),
        "status": market.get("status"),
        "eventStatus": event.get("status"),
        "live": bool(snapshot.get("eventLive")),
        "marketVolumeRaw": snapshot.get("marketVolumeRaw"),
        "lastUpdateTimestamp": snapshot.get("timestamp"),
        "stale": bool(snapshot.get("stale")),
        "outcomes": outcomes,
        "orderBookUrl": f"/api/providers/novig/book/{quote_url(snapshot.get('marketId') or market.get('id'))}",
    }


def _team_names(value: object) -> tuple[str, ...]:
    if not isinstance(value, dict):
        return ()
    return tuple(
        dict.fromkeys(
            normalized
            for field in ("name", "shortName", "symbol", "mascot")
            if (normalized := _normalize_name(value.get(field)))
        )
    )


def _market_event_id(market: dict) -> str:
    event = market.get("event")
    embedded_id = event.get("id") if isinstance(event, dict) else None
    return _safe_text(market.get("eventId") or embedded_id)


def _sport_from_league(league: str) -> str:
    value = _normalize_identifier(league).upper()
    if value in {"NFL", "NCAAF"}:
        return "FOOTBALL"
    if value in {"NBA", "WNBA", "NCAAB", "NCAAWB"}:
        return "BASKETBALL"
    if value == "MLB":
        return "BASEBALL"
    if value == "NHL":
        return "HOCKEY"
    if value in {"ATP", "WTA"}:
        return "TENNIS"
    if value in {
        "MLS",
        "EPL",
        "BUNDESLIGA",
        "SERIE_A",
        "LA_LIGA",
        "LIGUE_1",
        "CHAMPIONS_LEAGUE",
        "EUROPA_LEAGUE",
        "FIFA_CLUB_WORLD_CUP",
    }:
        return "SOCCER"
    return value


def _market_shape(
    market_type: str, league: str
) -> tuple[str | None, str, str, str | None]:
    period = "1h" if market_type.endswith("_1H") else "game"
    base = market_type.removesuffix("_1H")
    sport = _sport_from_league(league)
    if base == "MONEY":
        return "moneyline", "ml", period, f"winner:{period}:draw_push"
    if base == "SPREAD":
        return "spread", "sp", period, f"spread:{period}:team"
    if base == "TOTAL":
        return "game_total", "ou", period, f"total:{period}:all"
    if base == "TEAM_TOTAL":
        return "team_total", "ou", period, f"total:{period}:team"
    if base in {"MONEYLINE_3_WAY_WIN", "MONEYLINE_3_WAY_DRAW", "1X2"}:
        return "yes_no", "yn", "reg", "yes_no:reg"
    if sport and base:
        return "yes_no", "yn", period, f"yes_no:{period}"
    return None, "", period, None


def _outcome_side(market_type: str, index: int) -> str | None:
    base = market_type.removesuffix("_1H")
    if base in {"MONEY", "SPREAD"}:
        return "home" if index == 0 else "away" if index == 1 else None
    if base in {"TOTAL", "TEAM_TOTAL"}:
        return "over" if index == 0 else "under" if index == 1 else None
    if base in {"MONEYLINE_3_WAY_WIN", "MONEYLINE_3_WAY_DRAW", "1X2"}:
        return "yes" if index == 0 else "no" if index == 1 else None
    if base:
        return "yes" if index == 0 else "no" if index == 1 else None
    return None


def _with_staleness(
    snapshot: dict,
    stale_after_seconds: int,
    *,
    force_stale: bool = False,
) -> dict:
    payload = dict(snapshot)
    timestamp = _parse_datetime(payload.get("timestamp"))
    age = (
        max(0.0, (_utc_now() - timestamp).total_seconds())
        if timestamp is not None
        else None
    )
    payload["ageSeconds"] = round(age, 3) if age is not None else None
    payload["stale"] = bool(
        force_stale
        or age is None
        or age > max(1, int(stale_after_seconds))
    )
    return payload


def _outcome_line(
    market_type: str, strike: object, outcome: dict, index: int
) -> float | None:
    base = market_type.removesuffix("_1H")
    if base not in {"SPREAD", "TOTAL", "TEAM_TOTAL"}:
        return None
    description = _safe_text(outcome.get("description"))
    matches = re.findall(r"(?<![A-Za-z])([+-]?\d+(?:\.\d+)?)", description)
    if matches:
        parsed = _number(matches[-1])
        if parsed is not None:
            return parsed
    value = _number(strike)
    if value is None:
        return None
    if base == "SPREAD" and index == 1:
        return -value
    return value


def _selection_parts(value: str) -> tuple[str, str]:
    market_id, separator, outcome_id = _safe_text(value).partition("|")
    if not separator or not market_id or not outcome_id:
        raise NoVIGError("NOVIG_SELECTION_ID_INVALID")
    return market_id, outcome_id


def _recommended_stake(trade: dict) -> float:
    for value in (
        (trade.get("card") or {}).get("recommended_amount"),
        (trade.get("recommendation") or {}).get("recommended_amount"),
        trade.get("recommended_amount"),
    ):
        parsed = _number(value)
        if parsed is not None and parsed > 0:
            return parsed
    return 0.0


def _walk_depth(
    levels: list[dict], stake: float, *, event_live: bool
) -> dict[str, object]:
    available = sum(_number(row.get("liquidityDollars")) or 0.0 for row in levels)
    if not levels:
        return {
            "effective_price": None,
            "available_liquidity": 0.0,
            "fillable": False,
            "levels_used": 0,
            "estimated_fee": 0.0,
            "fee_rate": 0.0,
        }
    target = max(0.0, float(stake))
    if target <= 0:
        target = min(available, _number(levels[0].get("liquidityDollars")) or 0.0)
    remaining = target
    cost = 0.0
    contracts = 0.0
    fee = 0.0
    used = 0
    for level in levels:
        price = _number(level.get("price"))
        size = _number(level.get("contracts") or level.get("size"))
        if price is None or size is None or not 0 < price < 1 or size <= 0:
            continue
        level_cost = price * size
        fill_cost = min(remaining, level_cost)
        fill_contracts = fill_cost / price
        if fill_contracts <= 0:
            continue
        used += 1
        cost += fill_cost
        contracts += fill_contracts
        if event_live:
            fee += (
                price
                * (1.0 - price)
                * NOVIG_LIVE_TAKER_FEE_COEFFICIENT
                * fill_contracts
            )
        remaining -= fill_cost
        if remaining <= 1e-9:
            break
    fillable = stake <= 0 or remaining <= 0.01
    return {
        "effective_price": (cost / contracts) if contracts > 0 and fillable else None,
        "available_liquidity": round(available, 5),
        "fillable": fillable,
        "levels_used": used,
        "estimated_fee": round(fee, 5),
        "fee_rate": (fee / cost) if cost > 0 else 0.0,
    }


def _format_cents(price: float | None) -> str:
    if price is None or not 0 < price < 1:
        return "Unavailable"
    cents = price * 100
    return f"{cents:.0f}\u00a2" if abs(cents - round(cents)) < 1e-9 else f"{cents:.1f}\u00a2"
