from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import quote

import requests

LOGGER = logging.getLogger(__name__)

CURRENT_POSITIONS_URL = "https://data-api.polymarket.com/positions"
CLOSED_POSITIONS_URL = "https://data-api.polymarket.com/closed-positions"
EVENT_BY_SLUG_URL = "https://gamma-api.polymarket.com/events/slug"
PUBLIC_PROFILE_URL = "https://gamma-api.polymarket.com/public-profile"
CLOB_BOOKS_URL = "https://clob.polymarket.com/books"
CLOB_PRICE_HISTORY_URL = "https://clob.polymarket.com/prices-history"


class PolymarketClient:
    def __init__(self, request_timeout: int = 15, max_retries: int = 3) -> None:
        self.request_timeout = request_timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "iconbets-wallet-tracker/2.0"})
        self._event_cache: dict[str, dict] = {}
        self._profile_cache: dict[str, dict | None] = {}

    def _get_json(self, url: str, params: dict[str, Any]) -> Any:
        backoff = 1.0
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(
                    url, params=params, timeout=self.request_timeout
                )
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    wait = max(float(retry_after), backoff) if retry_after else backoff
                    LOGGER.warning(
                        "Polymarket rate-limited request to %s. Sleeping %.1fs",
                        url,
                        wait,
                    )
                    time.sleep(wait)
                    backoff *= 2
                    continue
                if response.status_code >= 500:
                    LOGGER.warning(
                        "Polymarket server error %s for %s", response.status_code, url
                    )
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(backoff)
                backoff *= 2

        raise RuntimeError(f"Failed request to {url}: {last_error}") from last_error

    def _post_json(self, url: str, payload: Any) -> Any:
        backoff = 1.0
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.post(
                    url, json=payload, timeout=self.request_timeout
                )
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    wait = max(float(retry_after), backoff) if retry_after else backoff
                    LOGGER.warning(
                        "Polymarket rate-limited request to %s. Sleeping %.1fs",
                        url,
                        wait,
                    )
                    time.sleep(wait)
                    backoff *= 2
                    continue
                if response.status_code >= 500:
                    LOGGER.warning(
                        "Polymarket server error %s for %s", response.status_code, url
                    )
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(backoff)
                backoff *= 2
        raise RuntimeError(f"Failed request to {url}: {last_error}") from last_error

    def get_current_positions(self, wallet_address: str) -> list[dict]:
        results: list[dict] = []
        offset = 0
        limit = 500

        while True:
            payload = self._get_json(
                CURRENT_POSITIONS_URL,
                {
                    "user": wallet_address,
                    "limit": limit,
                    "offset": offset,
                    # Polymarket's documented default excludes dust while preserving
                    # meaningful open positions and keeps pagination bounded.
                    "sizeThreshold": 1,
                    "sortBy": "CURRENT",
                    "sortDirection": "DESC",
                },
            )
            if not isinstance(payload, list):
                raise RuntimeError(
                    f"Unexpected current positions payload for {wallet_address}"
                )
            results.extend(payload)
            if len(payload) < limit:
                break
            offset += limit

        return results

    def get_closed_positions(self, wallet_address: str, limit: int = 50) -> list[dict]:
        payload = self._get_json(
            CLOSED_POSITIONS_URL,
            {
                "user": wallet_address,
                "limit": min(limit, 50),
                "offset": 0,
                "sortBy": "TIMESTAMP",
                "sortDirection": "DESC",
            },
        )
        if not isinstance(payload, list):
            raise RuntimeError(
                f"Unexpected closed positions payload for {wallet_address}"
            )
        return payload

    def get_event(self, event_slug: str) -> dict | None:
        if not event_slug:
            return None
        if event_slug in self._event_cache:
            return self._event_cache[event_slug]
        payload = self._get_json(
            f"{EVENT_BY_SLUG_URL}/{quote(event_slug, safe='')}", {}
        )
        event = payload if isinstance(payload, dict) else None
        self._event_cache[event_slug] = event
        return event

    def get_events(
        self, event_slugs: list[str], max_workers: int = 3
    ) -> dict[str, dict]:
        unresolved = [
            slug
            for slug in sorted(set(event_slugs))
            if slug and slug not in self._event_cache
        ]
        if unresolved:
            with ThreadPoolExecutor(
                max_workers=min(max_workers, len(unresolved))
            ) as executor:
                futures = {
                    executor.submit(self.get_event, slug): slug for slug in unresolved
                }
                for future in as_completed(futures):
                    slug = futures[future]
                    try:
                        future.result()
                    except Exception as exc:
                        LOGGER.warning("Failed to fetch event %s: %s", slug, exc)
                        self._event_cache[slug] = None
        return {slug: self._event_cache.get(slug) for slug in event_slugs if slug}

    def invalidate_event_cache(self) -> None:
        self._event_cache.clear()

    def get_public_profile(self, wallet_address: str) -> dict | None:
        if wallet_address in self._profile_cache:
            return self._profile_cache[wallet_address]
        try:
            payload = self._get_json(PUBLIC_PROFILE_URL, {"address": wallet_address})
        except Exception:
            payload = None
        self._profile_cache[wallet_address] = payload
        return payload

    def get_order_books(self, token_ids: list[str]) -> dict[str, dict]:
        books: dict[str, dict] = {}
        unique_ids = sorted({str(token_id) for token_id in token_ids if token_id})
        for offset in range(0, len(unique_ids), 100):
            chunk = unique_ids[offset : offset + 100]
            payload = self._post_json(
                CLOB_BOOKS_URL, [{"token_id": token_id} for token_id in chunk]
            )
            if not isinstance(payload, list):
                raise RuntimeError("Unexpected CLOB order-book payload")
            for book in payload:
                asset_id = str(book.get("asset_id") or "")
                if not asset_id:
                    continue
                books[asset_id] = {
                    "asset_id": asset_id,
                    "market": book.get("market"),
                    "timestamp": book.get("timestamp"),
                    "hash": book.get("hash"),
                    "asks": sorted(
                        book.get("asks") or [],
                        key=lambda level: float(level.get("price") or 0),
                    ),
                    "bids": sorted(
                        book.get("bids") or [],
                        key=lambda level: float(level.get("price") or 0),
                        reverse=True,
                    ),
                    "min_order_size": book.get("min_order_size"),
                    "tick_size": book.get("tick_size"),
                    "neg_risk": book.get("neg_risk"),
                    "last_trade_price": book.get("last_trade_price"),
                }
        return books

    def get_price_history(
        self,
        token_id: str,
        *,
        interval: str = "1d",
        fidelity: int = 15,
        start_timestamp: int | None = None,
        end_timestamp: int | None = None,
    ) -> list[dict]:
        params: dict[str, Any] = {"market": token_id, "fidelity": max(1, fidelity)}
        if start_timestamp is not None or end_timestamp is not None:
            if start_timestamp is not None:
                params["startTs"] = start_timestamp
            if end_timestamp is not None:
                params["endTs"] = end_timestamp
        else:
            params["interval"] = interval
        payload = self._get_json(CLOB_PRICE_HISTORY_URL, params)
        history = payload.get("history") if isinstance(payload, dict) else None
        return history if isinstance(history, list) else []
