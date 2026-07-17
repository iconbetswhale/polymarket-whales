from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests

from measurement_foundation import stable_hash


EASTERN = ZoneInfo("America/New_York")
MLB_MAIN_SLUG = re.compile(r"^mlb-[a-z0-9-]+-(\d{4}-\d{2}-\d{2})$")


def _list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (TypeError, ValueError):
            return []
    return []


def _market_kind(value: Any) -> str:
    raw = str(value or "").lower()
    return {"moneyline": "moneyline", "spreads": "spread", "totals": "game_total"}.get(raw, raw)


class PolymarketScheduleFeed:
    """Short-lived cache for the complete public MLB board, independent of wallets."""

    def __init__(self, timeout: float = 8.0, ttl_seconds: float = 10.0, session=None):
        self.timeout = timeout
        self.ttl_seconds = ttl_seconds
        self.session = session or requests.Session()
        self._lock = threading.Lock()
        self._cached_at = 0.0
        self._cached_rows: list[dict] = []

    def today_and_tomorrow(self, now: datetime | None = None) -> list[dict]:
        current = now or datetime.now(timezone.utc)
        with self._lock:
            if time.monotonic() - self._cached_at < self.ttl_seconds:
                return [dict(row) for row in self._cached_rows]
            response = self.session.get(
                "https://gamma-api.polymarket.com/events",
                params={"series_id": 3, "active": "true", "closed": "false", "limit": 100},
                timeout=self.timeout,
            )
            response.raise_for_status()
            rows = self._normalize(response.json(), current)
            self._cached_rows = rows
            self._cached_at = time.monotonic()
            return [dict(row) for row in rows]

    @staticmethod
    def _normalize(events: Any, now: datetime) -> list[dict]:
        eastern_today = now.astimezone(EASTERN).date()
        allowed = {eastern_today, eastern_today + timedelta(days=1)}
        rows: list[dict] = []
        for event in events if isinstance(events, list) else []:
            slug = str(event.get("slug") or "")
            match = MLB_MAIN_SLUG.match(slug)
            if not match:
                continue
            event_day = datetime.fromisoformat(match.group(1)).date()
            if event_day not in allowed:
                continue
            markets = event.get("markets") if isinstance(event.get("markets"), list) else []
            for market in markets:
                kind = _market_kind(market.get("sportsMarketType"))
                if kind not in {"moneyline", "spread", "game_total"}:
                    continue
                if market.get("closed") or market.get("active") is False:
                    continue
                outcomes, prices, tokens = (_list(market.get(name)) for name in ("outcomes", "outcomePrices", "clobTokenIds"))
                starts_at = market.get("endDate") or event.get("endDate")
                # Gamma currently dates MLB moneyline settlement seven days after first pitch.
                if kind == "moneyline" and starts_at:
                    parsed = datetime.fromisoformat(str(starts_at).replace("Z", "+00:00")) - timedelta(days=7)
                    starts_at = parsed.isoformat().replace("+00:00", "Z")
                for index, outcome in enumerate(outcomes):
                    try:
                        price = float(prices[index])
                    except (IndexError, TypeError, ValueError):
                        price = None
                    token = str(tokens[index]) if index < len(tokens) else ""
                    market_id = str(market.get("conditionId") or market.get("id") or market.get("slug") or "")
                    row_id = "schedule::" + stable_hash((market_id, outcome, index))[:24]
                    rows.append({
                        "id": row_id,
                        "event_id": str(event.get("id") or slug),
                        "market_id": market_id,
                        "condition_id": market.get("conditionId"),
                        "clob_token_id": token,
                        "event_title": event.get("title") or market.get("question"),
                        "market_title": market.get("question"),
                        "market_slug": market.get("slug"),
                        "outcome": str(outcome),
                        "current_price": price,
                        "executable_ask_price": price,
                        "sports_market_type": kind,
                        "market_line": market.get("line"),
                        "canonical_sport_id": "baseball",
                        "canonical_league_id": "mlb",
                        "league": "MLB",
                        "event_date_et": starts_at,
                        "resolution_time": starts_at,
                        "schedule_date_et": event_day.isoformat(),
                        "market_url": f"https://polymarket.com/event/{slug}",
                        "card": {"current_actionable_price": price, "recommended_amount": 0},
                        "recommendation": {"current_user_entry_price": price, "recommended_amount": 0},
                        "validation_ids": {"condition_id": market.get("conditionId"), "clob_token_id": token},
                    })
        return sorted(rows, key=lambda row: (row["schedule_date_et"], row.get("resolution_time") or "", row["event_title"], row["sports_market_type"], row["outcome"]))
