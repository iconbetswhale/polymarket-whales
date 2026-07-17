from __future__ import annotations

import threading
import time
from datetime import timedelta

import requests

from execution_providers import (
    ExecutionOption, ExecutionProvider, MatchConfidence, NormalizedProviderMarket,
    ProviderMarketIndex, _fair_quotes_from_index, _match_exact_trade, _name_matches, _normalize_name,
    _parse_datetime, american_to_probability, canonicalize_trade,
)

KALSHI_LOGO_URL = "https://kalshi.com/favicon.ico"
KALSHI_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
SERIES = {
    ("BASEBALL", "MLB"): "KXMLBGAME",
    ("BASKETBALL", "NBA"): "KXNBAGAME",
    ("BASKETBALL", "WNBA"): "KXWNBAGAME",
    ("FOOTBALL", "NFL"): "KXNFLGAME",
    ("HOCKEY", "NHL"): "KXNHLGAME",
}


class KalshiProvider(ExecutionProvider):
    provider_name = "Kalshi"
    provider_key = "kalshi"

    def __init__(self, *, enabled=True, base_url=KALSHI_BASE_URL, cache_ttl_seconds=1,
                 request_timeout=10, session=None):
        self.enabled = bool(enabled)
        self.base_url = base_url.rstrip("/")
        self.cache_ttl_seconds = max(1, int(cache_ttl_seconds))
        self.request_timeout = max(1, int(request_timeout))
        self.session = session or requests.Session()
        self._lock = threading.RLock()
        self._cache = {}
        self._last_success = None
        self._market_count = 0
        self._match_count = 0

    def __repr__(self):
        return f"<KalshiProvider enabled={self.enabled} read_only=True>"

    def options_for_trades(self, trades):
        canonical = [row for trade in trades if (row := canonicalize_trade(trade))]
        if not self.enabled or not canonical:
            return {}
        index = self._index(canonical)
        originals = {str(row.get("id") or ""): row for row in trades}
        result = {}
        for trade in canonical:
            confidence, market = _match_exact_trade(trade, index, allow_same_day=True)
            if confidence is not MatchConfidence.EXACT or market is None:
                continue
            stake = _stake(originals.get(trade.trade_id) or {})
            price = _price_from_selection(market.selection_id)
            liquidity = _liquidity_from_selection(market.selection_id) * price if price is not None else 0
            fillable = liquidity >= stake if stake > 0 else liquidity > 0
            available = bool(market.is_available and price is not None and fillable)
            result[trade.trade_id] = ExecutionOption(
                provider_name=self.provider_name, provider_key=self.provider_key,
                market_id=market.event_id, selection_id=market.selection_id,
                display_odds=market.display_odds if available else "Unavailable",
                deep_link=f"https://kalshi.com/markets_by_ticker/{market.selection_id.split('|', 1)[0]}" if available else None,
                is_available=available, last_updated=market.last_updated,
                matching_confidence=MatchConfidence.EXACT, logo_url=KALSHI_LOGO_URL,
                tooltip="Kalshi public read-only executable ask",
                american_odds=market.american_odds if available else None,
                contract_price=price, effective_price=price,
                available_liquidity=liquidity,
                can_fill_recommended_stake=fillable, quote_status="OPEN" if available else "INSUFFICIENT_DEPTH",
            )
        self._match_count = len(result)
        return result

    def fair_price_quotes(self, trades):
        canonical = [row for trade in trades if (row := canonicalize_trade(trade))]
        return _fair_quotes_from_index(canonical, self._index(canonical), self.provider_key) if canonical else {}

    def diagnostics(self, *, authenticate=False):
        return {"provider": "kalshi", "status": "CONNECTED" if self._last_success else "PUBLIC_READ_ONLY",
                "read_only": True, "trading_enabled": False, "last_successful_request": self._last_success,
                "active_market_count": self._market_count, "exact_market_matches": self._match_count}

    def place_order(self, *args, **kwargs):
        raise PermissionError("Kalshi trading is disabled")

    def cancel_order(self, *args, **kwargs):
        raise PermissionError("Kalshi trading is disabled")

    def _index(self, trades):
        markets = []
        for sport_league in sorted({(row.sport_id, row.league_id) for row in trades}):
            series = SERIES.get(sport_league)
            if not series:
                continue
            markets.extend(self._series_markets(series, *sport_league))
        self._market_count = len(markets)
        return ProviderMarketIndex(markets)

    def _series_markets(self, series, sport, league):
        with self._lock:
            cached = self._cache.get(series)
            if cached and time.monotonic() - cached[0] < self.cache_ttl_seconds:
                return cached[1]
        response = self.session.get(f"{self.base_url}/markets", params={"status": "open", "series_ticker": series, "limit": 1000}, timeout=self.request_timeout)
        response.raise_for_status()
        payload = response.json()
        rows = []
        for market in payload.get("markets") or []:
            rows.extend(_normalize_market(market, sport, league))
        with self._lock:
            self._cache[series] = (time.monotonic(), rows)
            self._last_success = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        return rows


def _normalize_market(market, sport, league):
    ticker = str(market.get("ticker") or "")
    event_id = str(market.get("event_ticker") or ticker)
    title = str(market.get("title") or "")
    participants = _participants(title)
    start = _parse_datetime(market.get("occurrence_datetime") or market.get("expected_expiration_time"))
    if not ticker or not start or len(participants) != 2:
        return []
    yes_name = _normalize_name(market.get("yes_sub_title") or market.get("subtitle"))
    if not yes_name:
        return []
    yes_is_first = _name_matches(yes_name, (participants[0],))
    yes_side = "away" if yes_is_first else "home"
    updated = str(market.get("updated_time") or "") or None
    available = str(market.get("status") or "").lower() in {"open", "active"}
    result = []
    # Kalshi publishes one binary contract per team. Its YES ask is the direct
    # sportsbook-equivalent moneyline for that team; emitting NO as the opponent
    # creates duplicate ambiguous matches when the opponent contract also exists.
    for outcome, side, price_key, size_key in (
        ("yes", yes_side, "yes_ask_dollars", "yes_ask_size_fp"),
    ):
        price = _float(market.get(price_key))
        size = _float(market.get(size_key)) or 0
        american = _probability_to_american(price)
        result.append(NormalizedProviderMarket(
            event_id=event_id, selection_id=f"{ticker}|{outcome}|{size:g}|{price:g}", sport_id=sport,
            league_id=league, start_at=start, home_names=(participants[1],), away_names=(participants[0],),
            market_name="moneyline", stat_id="points", stat_entity_id="all", period_id="game",
            bet_type_id="ml", side_id=side, line=None, is_alternative=False,
            display_odds=f"{american:+d}" if american else "Unavailable", american_odds=american,
            deep_link=f"https://kalshi.com/markets_by_ticker/{ticker}", is_available=available and bool(price) and size > 0,
            last_updated=updated, settlement_rules="winner:game:draw_push",
        ))
    return result


def _participants(title):
    clean = _normalize_name(title)
    clean = __import__("re").sub(r"\s+winner$", "", clean).strip()
    for token in (" vs ", " versus ", " at "):
        if token in clean:
            left, right = clean.split(token, 1)
            return left.strip(), right.strip()
    return ()


def _probability_to_american(price):
    if price is None or price <= 0 or price >= 1:
        return None
    return round(-100 * price / (1 - price)) if price >= .5 else round(100 * (1 - price) / price)


def _liquidity_from_selection(selection_id):
    try:
        return float(selection_id.rsplit("|", 2)[1])
    except (ValueError, IndexError):
        return 0.0


def _price_from_selection(selection_id):
    try:
        return float(selection_id.rsplit("|", 1)[1])
    except (ValueError, IndexError):
        return None


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _stake(trade):
    try:
        return float((trade.get("card") or {}).get("recommended_amount") or (trade.get("recommendation") or {}).get("recommended_amount") or 0)
    except (TypeError, ValueError):
        return 0.0
