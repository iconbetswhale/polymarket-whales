from __future__ import annotations

import json
import logging
import random
import threading
import time
from datetime import datetime, timezone
from typing import Callable

from novig_provider import (
    NoVIGAuthClient,
    NoVIGError,
    NoVIGOrderBookState,
    NoVIGRestClient,
    NoVIGStateStore,
    NOVIG_WEBSOCKET_URL,
    enrich_novig_markets,
)

LOGGER = logging.getLogger(__name__)


class NoVIGFeedWorker:
    """Long-running NBX REST bootstrap + WebSocket state worker."""

    def __init__(
        self,
        auth: NoVIGAuthClient,
        rest: NoVIGRestClient,
        state_store: NoVIGStateStore,
        *,
        websocket_url: str = NOVIG_WEBSOCKET_URL,
        stale_after_seconds: int = 30,
        flush_interval_seconds: float = 0.5,
        market_subscription_limit: int = 0,
        socket_factory: Callable | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.auth = auth
        self.rest = rest
        self.state_store = state_store
        self.websocket_url = websocket_url
        self.stale_after_seconds = max(1, int(stale_after_seconds))
        self.flush_interval_seconds = max(0.1, float(flush_interval_seconds))
        self.market_subscription_limit = max(0, int(market_subscription_limit))
        self.socket_factory = socket_factory or _default_socket_factory
        self._monotonic = monotonic
        self._sleep = sleep
        self._jitter = jitter
        self._stop = threading.Event()
        self._socket = None
        self.engine = NoVIGOrderBookState()
        self._dirty: set[str] = set()
        self._last_flush = 0.0
        self._last_status_write = 0.0
        self._status = {
            "status": "STARTING",
            "connected": False,
            "last_message_at": None,
            "last_bootstrap_at": None,
            "last_disconnect_at": None,
            "active_market_count": 0,
            "reconnect_count": 0,
            "message_count": 0,
            "book_snapshot_count": 0,
            "last_error_code": None,
            "stale": True,
        }

    def status(self) -> dict:
        payload = dict(self._status)
        payload["token_refresh_count"] = self.auth.status()["refresh_count"]
        payload["credentials_exposed"] = False
        payload["token_exposed"] = False
        return payload

    def stop(self) -> None:
        self._stop.set()
        socket = self._socket
        if socket is not None:
            try:
                socket.close()
            except Exception:
                pass

    def bootstrap(self) -> list[str]:
        markets = self.rest.list_open_markets()
        try:
            events = self.rest.list_events()
        except NoVIGError:
            events = []
        markets = enrich_novig_markets(markets, events)
        event_ids = list(
            dict.fromkeys(
                str(row.get("eventId") or "").strip()
                for row in markets
                if str(row.get("eventId") or "").strip()
            )
        )
        with_books = self.rest.get_markets_by_events(event_ids) if event_ids else []
        if not with_books:
            with_books = markets
        else:
            with_books = enrich_novig_markets(with_books, events)
        loaded_ids: list[str] = []
        for market in with_books:
            market_id = str(market.get("id") or "").strip()
            if not market_id:
                continue
            book = market.get("book") if isinstance(market.get("book"), dict) else None
            if book is None:
                try:
                    book = self.rest.get_book(market_id)
                except NoVIGError:
                    book = None
            self.engine.bootstrap_market(market, book=book)
            loaded_ids.append(market_id)
        self.engine.remove_absent_markets(loaded_ids)
        snapshots = self.engine.snapshots(
            stale_after_seconds=self.stale_after_seconds
        )
        if self.state_store.configured:
            self.state_store.initialize()
            self.state_store.save_markets(snapshots)
            self.state_store.delete_absent_markets(loaded_ids)
        self._status.update(
            {
                "status": "BOOTSTRAPPED",
                "last_bootstrap_at": _iso_now(),
                "active_market_count": len(loaded_ids),
                "last_error_code": None,
            }
        )
        _structured_log(
            logging.INFO,
            "bootstrap_complete",
            active_market_count=len(loaded_ids),
        )
        self._write_status(force=True)
        return loaded_ids

    def connect_once(self, *, max_messages: int | None = None) -> None:
        market_ids = self.bootstrap()
        token = self.auth.get_token()
        socket = self.socket_factory(
            self.websocket_url,
            authorization=f"Bearer {token}",
            timeout=20,
        )
        self._socket = socket
        self._status.update(
            {
                "status": "CONNECTED",
                "connected": True,
                "last_error_code": None,
                "stale": False,
            }
        )
        subscriptions = ["tape", "lifecycle"]
        if self.market_subscription_limit:
            subscriptions.extend(market_ids[: self.market_subscription_limit])
        for channel in subscriptions:
            socket.send(json.dumps({"event": "subscribe", "data": channel}))
        _structured_log(
            logging.INFO,
            "websocket_connected",
            subscription_count=len(subscriptions),
            active_market_count=len(market_ids),
        )
        self._write_status(force=True)

        received = 0
        try:
            while not self._stop.is_set():
                if self.auth.expires_in_seconds <= 60:
                    raise NoVIGError("NOVIG_WEBSOCKET_TOKEN_RENEWAL")
                raw = socket.recv()
                if raw is None or raw == b"" or raw == "":
                    raise NoVIGError("NOVIG_WEBSOCKET_CLOSED")
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                try:
                    message = json.loads(raw)
                except (TypeError, ValueError, json.JSONDecodeError):
                    self._status["last_error_code"] = "NOVIG_WEBSOCKET_INVALID_JSON"
                    continue
                if not isinstance(message, dict):
                    continue
                if str(message.get("event") or "").lower() == "error":
                    raise NoVIGError("NOVIG_WEBSOCKET_ERROR_FRAME")
                changed = self.engine.apply_message(message)
                self._dirty.update(changed)
                received += 1
                self._status["message_count"] += 1
                self._status["last_message_at"] = _iso_now()
                self._status["stale"] = False
                if str(message.get("event") or "").lower() == "book":
                    self._status["book_snapshot_count"] += 1
                self._flush_if_due()
                self._write_status()
                if max_messages is not None and received >= max_messages:
                    return
        finally:
            self._flush(force=True)
            self._status.update(
                {
                    "connected": False,
                    "last_disconnect_at": _iso_now(),
                    "stale": True,
                }
            )
            self._write_status(force=True)
            _structured_log(
                logging.INFO,
                "websocket_disconnected",
                message_count=self._status["message_count"],
                last_error_code=self._status["last_error_code"],
            )
            try:
                socket.close()
            except Exception:
                pass
            self._socket = None

    def run_forever(self) -> None:
        if not self.auth.configured:
            raise NoVIGError("NOVIG_CREDENTIALS_NOT_CONFIGURED")
        if not self.state_store.configured:
            raise NoVIGError("NOVIG_STATE_STORE_NOT_CONFIGURED")
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self.connect_once()
                backoff = 1.0
            except NoVIGError as exc:
                self._status.update(
                    {
                        "status": "RECONNECTING",
                        "connected": False,
                        "last_error_code": exc.code,
                        "last_disconnect_at": _iso_now(),
                        "stale": True,
                    }
                )
                if exc.code in {
                    "NOVIG_WEBSOCKET_UNAUTHORIZED",
                    "NOVIG_WEBSOCKET_TOKEN_RENEWAL",
                }:
                    self.auth.invalidate()
            except Exception:
                self._status.update(
                    {
                        "status": "RECONNECTING",
                        "connected": False,
                        "last_error_code": "NOVIG_WEBSOCKET_CONNECTION_FAILED",
                        "last_disconnect_at": _iso_now(),
                        "stale": True,
                    }
                )
            if self._stop.is_set():
                break
            self._status["reconnect_count"] += 1
            self._write_status(force=True)
            delay = min(30.0, backoff) * (0.75 + 0.5 * self._jitter())
            _structured_log(
                logging.WARNING,
                "websocket_reconnect_scheduled",
                reconnect_count=self._status["reconnect_count"],
                delay_seconds=round(delay, 3),
                last_error_code=self._status["last_error_code"],
            )
            self._sleep(delay)
            backoff = min(30.0, backoff * 2.0)
        self._status.update({"status": "STOPPED", "connected": False, "stale": True})
        self._write_status(force=True)

    def _flush_if_due(self) -> None:
        if self._monotonic() - self._last_flush >= self.flush_interval_seconds:
            self._flush()

    def _flush(self, *, force: bool = False) -> None:
        if not self._dirty and not force:
            return
        dirty = set(self._dirty)
        if force and not dirty:
            dirty.update(self.engine.market_ids())
        snapshots = [
            snapshot
            for market_id in dirty
            if (
                snapshot := self.engine.snapshot(
                    market_id, stale_after_seconds=self.stale_after_seconds
                )
            )
            is not None
        ]
        if snapshots and self.state_store.configured:
            self.state_store.save_markets(snapshots)
        self._dirty.difference_update(dirty)
        self._last_flush = self._monotonic()

    def _write_status(self, *, force: bool = False) -> None:
        now = self._monotonic()
        if not force and now - self._last_status_write < 5.0:
            return
        if self.state_store.configured:
            self.state_store.save_status(self.status())
        self._last_status_write = now


def websocket_smoke_test(
    auth: NoVIGAuthClient,
    rest: NoVIGRestClient,
    *,
    websocket_url: str = NOVIG_WEBSOCKET_URL,
    timeout_seconds: float = 8.0,
    socket_factory: Callable | None = None,
) -> dict:
    result = {
        "success": False,
        "connected": False,
        "market_subscription_sent": False,
        "book_snapshot_received": False,
        "update_received": False,
        "message_types": [],
        "error_code": None,
        "credentials_exposed": False,
        "token_exposed": False,
    }
    socket = None
    try:
        # The unfiltered open-markets response can be very large. A smoke test
        # only needs one valid market subscription, so use server-side market
        # type filters and keep the diagnostic's memory footprint bounded.
        markets = rest.list_open_markets(market_type="TOTAL")
        if not markets:
            markets = rest.list_open_markets(market_type="SPREAD")
        if not markets:
            result["error_code"] = "NOVIG_NO_OPEN_MARKETS"
            return result
        market_id = str(markets[0].get("id") or "").strip()
        token = auth.get_token()
        factory = socket_factory or _default_socket_factory
        socket = factory(
            websocket_url,
            authorization=f"Bearer {token}",
            timeout=max(1.0, float(timeout_seconds)),
        )
        result["connected"] = True
        for channel in (market_id, "tape", "lifecycle"):
            socket.send(json.dumps({"event": "subscribe", "data": channel}))
        result["market_subscription_sent"] = True
        deadline = time.monotonic() + max(1.0, float(timeout_seconds))
        while time.monotonic() < deadline:
            try:
                raw = socket.recv()
            except Exception as exc:
                if "timed out" in str(exc).lower():
                    break
                raise
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            if not raw:
                break
            message = json.loads(raw)
            event = str(message.get("event") or "").lower()
            kind = str(message.get("type") or "").upper()
            label = event or kind
            if label and label not in result["message_types"]:
                result["message_types"].append(label)
            if event == "book":
                result["book_snapshot_received"] = True
            if kind in {
                "PLACE",
                "CANCEL",
                "OPEN",
                "START",
                "END",
                "CLOSE",
                "EVENT_GOLIVE",
                "EVENT_UNLIVE",
            }:
                result["update_received"] = True
            if result["book_snapshot_received"] and result["update_received"]:
                break
        result["success"] = bool(
            result["connected"] and result["book_snapshot_received"]
        )
        if not result["success"]:
            result["error_code"] = "NOVIG_WEBSOCKET_SNAPSHOT_NOT_OBSERVED"
    except NoVIGError as exc:
        result["error_code"] = exc.code
    except Exception:
        result["error_code"] = "NOVIG_WEBSOCKET_CONNECTION_FAILED"
    finally:
        if socket is not None:
            try:
                socket.close()
            except Exception:
                pass
    return result


def _default_socket_factory(url: str, *, authorization: str, timeout: float):
    import websocket

    try:
        return websocket.create_connection(
            url,
            header=[f"Authorization: {authorization}"],
            timeout=timeout,
            enable_multithread=True,
        )
    except websocket.WebSocketBadStatusException as exc:
        if getattr(exc, "status_code", None) == 401:
            raise NoVIGError("NOVIG_WEBSOCKET_UNAUTHORIZED", status_code=401) from exc
        raise NoVIGError("NOVIG_WEBSOCKET_HANDSHAKE_FAILED") from exc
    except Exception as exc:
        raise NoVIGError("NOVIG_WEBSOCKET_CONNECTION_FAILED") from exc


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _structured_log(level: int, event: str, **fields) -> None:
    safe = {
        "provider": "novig",
        "event": event,
        **{
            key: value
            for key, value in fields.items()
            if key
            in {
                "active_market_count",
                "subscription_count",
                "message_count",
                "reconnect_count",
                "delay_seconds",
                "last_error_code",
            }
        },
    }
    LOGGER.log(level, json.dumps(safe, separators=(",", ":"), sort_keys=True))
