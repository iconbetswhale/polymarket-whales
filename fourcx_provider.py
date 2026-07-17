from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Iterable

import requests

from execution_providers import (
    CanonicalTrade,
    ExecutionOption,
    ExecutionProvider,
    MatchConfidence,
    NormalizedProviderMarket,
    ProviderMarketIndex,
    _equivalent_market_key,
    _match_exact_trade,
    _normalize_name,
    _normalize_identifier,
    _parse_datetime,
    american_to_probability,
    canonicalize_trade,
)
from fair_price_engine import no_vig_probabilities

FOURCX_MAPPING_UNCERTAIN = "4CX_MARKET_MAPPING_UNCERTAIN"
FOURCX_LOGO_URL = "https://4cx.io/favicon.ico"
FOURCX_TRADE_URL = "https://4cx.io/"


class FourCXHealthStatus(str, Enum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    AUTHENTICATING = "AUTHENTICATING"
    CONNECTED = "CONNECTED"
    UNAUTHORIZED = "UNAUTHORIZED"
    RATE_LIMITED = "RATE_LIMITED"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
    MAPPING_UNCERTAIN = "MAPPING_UNCERTAIN"
    DEGRADED = "DEGRADED"
    ERROR = "ERROR"


@dataclass
class _FourCXCache:
    loaded_at: float
    fetched_at: datetime
    index: ProviderMarketIndex
    depth: dict[str, list[dict]]


class FourCXProvider(ExecutionProvider):
    """Read-only 4CX market-data adapter. Trading endpoints are intentionally absent."""

    provider_name = "4CX"
    provider_key = "4cx"

    def __init__(
        self,
        username: str | None,
        password: str | None,
        *,
        enabled: bool = False,
        trading_enabled: bool = False,
        base_url: str = "https://api.4cx.io",
        cache_ttl_seconds: int = 30,
        request_timeout: int = 15,
        max_quote_age_seconds: int = 60,
        session: requests.Session | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._username = str(username or "").strip() or None
        self._password = str(password or "").strip() or None
        self.enabled = bool(enabled)
        self.trading_enabled = bool(trading_enabled)
        self.base_url = base_url.rstrip("/")
        self.cache_ttl_seconds = max(1, int(cache_ttl_seconds))
        self.request_timeout = max(1, int(request_timeout))
        self.max_quote_age_seconds = max(1, int(max_quote_age_seconds))
        self.session = session or requests.Session()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._token: str | None = None
        self._cache: _FourCXCache | None = None
        self._status = FourCXHealthStatus.NOT_CONFIGURED
        self._last_error_code: str | None = None
        self._last_successful_login: str | None = None
        self._last_successful_request: str | None = None
        self._last_event_refresh: str | None = None
        self._player_mode: str | None = None
        self._active_event_count = 0
        self._exact_market_matches = 0
        self._mapping_failures = 0

    def __repr__(self) -> str:
        return f"<FourCXProvider enabled={self.enabled} configured={self._configured} trading_enabled={self.trading_enabled}>"

    @property
    def _configured(self) -> bool:
        return bool(self.enabled and self._username and self._password)

    def health_status(self, *, authenticate: bool = False) -> FourCXHealthStatus:
        if not self._configured:
            return FourCXHealthStatus.NOT_CONFIGURED
        if authenticate:
            try:
                self._login()
            except (requests.RequestException, ValueError, TypeError):
                pass
        return self._status

    def diagnostics(self, *, authenticate: bool = False) -> dict:
        status = self.health_status(authenticate=authenticate)
        return {
            "provider": self.provider_key,
            "status": status.value,
            "mode": self._player_mode,
            "read_only": True,
            "trading_enabled": False,
            "last_successful_login": self._last_successful_login,
            "last_successful_request": self._last_successful_request,
            "last_event_refresh": self._last_event_refresh,
            "active_event_count": self._active_event_count,
            "exact_market_matches": self._exact_market_matches,
            "mapping_failures": self._mapping_failures,
            "last_error_code": self._last_error_code,
        }

    def options_for_trades(self, trades: list[dict]) -> dict[str, ExecutionOption]:
        canonical = [item for trade in trades if (item := canonicalize_trade(trade))]
        if not self._configured or not canonical:
            return {}
        try:
            cache = self._market_index(canonical)
        except (requests.RequestException, ValueError, TypeError):
            return {}
        originals = {str(row.get("id") or ""): row for row in trades}
        results: dict[str, ExecutionOption] = {}
        mapping_failures = 0
        for trade in canonical:
            confidence, market = _match_exact_trade(trade, cache.index)
            if confidence is not MatchConfidence.EXACT or market is None:
                if confidence is MatchConfidence.PROBABLE:
                    mapping_failures += 1
                continue
            stake = _recommended_stake(originals.get(trade.trade_id) or {})
            effective, liquidity, fillable = _effective_price(
                cache.depth.get(market.selection_id, []), stake
            )
            contract = american_to_probability(market.american_odds)
            available = bool(market.is_available and contract is not None and fillable)
            results[trade.trade_id] = ExecutionOption(
                provider_name=self.provider_name,
                provider_key=self.provider_key,
                market_id=market.event_id,
                selection_id=market.selection_id,
                display_odds=market.display_odds if available else "Unavailable",
                deep_link=FOURCX_TRADE_URL if available else None,
                is_available=available,
                last_updated=market.last_updated,
                matching_confidence=MatchConfidence.EXACT,
                logo_url=FOURCX_LOGO_URL,
                tooltip="4CX executable price from live order-book depth; 0% current commission",
                american_odds=market.american_odds if available else None,
                contract_price=contract,
                effective_price=effective,
                available_liquidity=liquidity,
                can_fill_recommended_stake=fillable,
                fee_rate=0.0,
                quote_status="OPEN" if available else "INSUFFICIENT_DEPTH",
            )
        self._exact_market_matches = len(results)
        self._mapping_failures = mapping_failures
        if mapping_failures and not results:
            self._status = FourCXHealthStatus.MAPPING_UNCERTAIN
        return results

    def fair_price_quotes(self, trades: list[dict]) -> dict[str, dict]:
        canonical = [item for trade in trades if (item := canonicalize_trade(trade))]
        if not self._configured or not canonical:
            return {}
        try:
            cache = self._market_index(canonical)
        except (requests.RequestException, ValueError, TypeError):
            return {}
        if (self._clock() - cache.fetched_at).total_seconds() > self.max_quote_age_seconds:
            return {}
        results: dict[str, dict] = {}
        for trade in canonical:
            confidence, matched = _match_exact_trade(trade, cache.index)
            if confidence is MatchConfidence.PROBABLE:
                results[trade.trade_id] = {
                    "provider": self.provider_key, "status": "UNAVAILABLE",
                    "mapping_confidence": "UNCERTAIN", "missing_reason": FOURCX_MAPPING_UNCERTAIN,
                    "fabricated_data": False,
                }
                continue
            if confidence is not MatchConfidence.EXACT or matched is None:
                continue
            siblings = [row for row in cache.index.markets if _equivalent_market_key(row) == _equivalent_market_key(matched) and row.is_available and row.american_odds]
            probabilities = no_vig_probabilities(row.american_odds for row in siblings)
            selected = next((i for i, row in enumerate(siblings) if row.selection_id == matched.selection_id), None)
            if probabilities is None or selected is None:
                continue
            results[trade.trade_id] = {
                "provider": self.provider_key, "status": "AVAILABLE",
                "quote_timestamp": matched.last_updated, "mapping_confidence": "EXACT",
                "provider_event_id": matched.event_id,
                "provider_market_id": "::".join(str(v) for v in _equivalent_market_key(matched)),
                "provider_selection_id": matched.selection_id, "sport": matched.sport_id,
                "league": matched.league_id, "start_time": matched.start_at.isoformat(),
                "home_participant": matched.home_names[0], "away_participant": matched.away_names[0],
                "market_type": matched.market_name, "period": matched.period_id,
                "line": matched.line, "selection": matched.side_id,
                "settlement_rules": matched.settlement_rules, "native_odds": matched.display_odds,
                "american_odds": matched.american_odds,
                "raw_implied_probability": american_to_probability(matched.american_odds),
                "no_vig_probability": probabilities[selected], "outcome_count": len(siblings),
                "liquidity": sum(float(row.get("remaining") or 0) for row in cache.depth.get(matched.selection_id, [])),
                "limits": None, "quality_metadata": {"liquidity_status": "AVAILABLE", "fee_rate": 0.0},
                "fabricated_data": False,
            }
        return results

    def place_order(self, *args, **kwargs):
        raise PermissionError("4CX trading is disabled in this read-only integration")

    def cancel_order(self, *args, **kwargs):
        raise PermissionError("4CX trading is disabled in this read-only integration")

    def _login(self) -> str:
        self._status = FourCXHealthStatus.AUTHENTICATING
        response = self.session.post(
            f"{self.base_url}/user/login",
            json={"username": self._username, "password": self._password},
            timeout=self.request_timeout,
        )
        if response.status_code == 401:
            self._status, self._last_error_code = FourCXHealthStatus.UNAUTHORIZED, "UNAUTHORIZED"
            raise ValueError("4CX authentication failed")
        if response.status_code == 429:
            self._status, self._last_error_code = FourCXHealthStatus.RATE_LIMITED, "RATE_LIMITED"
            raise ValueError("4CX rate limited")
        response.raise_for_status()
        payload = response.json()
        user = ((payload.get("data") or {}).get("user") or {})
        token = str(user.get("auth") or "").strip()
        if not token:
            self._status, self._last_error_code = FourCXHealthStatus.ERROR, "MALFORMED_AUTH_RESPONSE"
            raise ValueError("4CX authentication response was invalid")
        with self._lock:
            self._token = token
            self._player_mode = str(user.get("playerMode") or "").strip() or None
            self._status, self._last_error_code = FourCXHealthStatus.CONNECTED, None
            self._last_successful_login = self._clock().isoformat()
        return token

    def _request(self, path: str, body: dict) -> dict:
        token = self._token or self._login()
        for attempt in range(2):
            response = self.session.post(
                f"{self.base_url}{path}", json=body,
                headers={"Authorization": token}, timeout=self.request_timeout,
            )
            if response.status_code == 401 and attempt == 0:
                self._token = None
                token = self._login()
                continue
            if response.status_code == 429:
                self._status, self._last_error_code = FourCXHealthStatus.RATE_LIMITED, "RATE_LIMITED"
                raise ValueError("4CX rate limited")
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("4CX response was invalid")
            self._status, self._last_error_code = FourCXHealthStatus.CONNECTED, None
            self._last_successful_request = self._clock().isoformat()
            return payload
        raise ValueError("4CX authentication retry failed")

    def _market_index(self, trades: list[CanonicalTrade]) -> _FourCXCache:
        with self._lock:
            if self._cache and time.monotonic() - self._cache.loaded_at < self.cache_ttl_seconds:
                return self._cache
        rows: list[NormalizedProviderMarket] = []
        depth: dict[str, list[dict]] = {}
        events = 0
        requested = sorted({(trade.sport_id, trade.league_id) for trade in trades})
        for sport, league in requested:
            sport_name = sport.lower()
            event_payload = self._request("/exchange/getEvents", {"sport": sport_name})
            available = ((event_payload.get("data") or {}).get("availableEvents") or [])
            events += len(available)
            games_payload = self._request("/exchange/v2/getGames", {"sport": sport_name, "league": league})
            games = ((games_payload.get("data") or {}).get("games") or [])
            for game in games:
                game_id = str(game.get("id") or "").strip()
                if not game_id:
                    continue
                orderbook = self._request("/exchange/getSingleOrderbook", {"gameID": game_id})
                full = (orderbook.get("data") or {}).get("game") or game
                normalized, book_depth = normalize_fourcx_game(full, self._clock())
                rows.extend(normalized)
                depth.update(book_depth)
        cache = _FourCXCache(time.monotonic(), self._clock(), ProviderMarketIndex(rows), depth)
        with self._lock:
            self._cache = cache
            self._active_event_count = events
            self._last_event_refresh = cache.fetched_at.isoformat()
        return cache


def normalize_fourcx_game(game: dict, fetched_at: datetime) -> tuple[list[NormalizedProviderMarket], dict[str, list[dict]]]:
    event_id = str(game.get("id") or "").strip()
    sport = _normalize_identifier(game.get("sport")).upper()
    league = _normalize_identifier(game.get("league"))
    start = _parse_datetime(game.get("start"))
    participants = game.get("participants") or []
    home = tuple(_participant_names(row) for row in participants if str(row.get("homeAway") or "").lower() == "home")
    away = tuple(_participant_names(row) for row in participants if str(row.get("homeAway") or "").lower() == "away")
    home_names = tuple(name for group in home for name in group)
    away_names = tuple(name for group in away for name in group)
    period = _fourcx_period(game.get("periodName"))
    if not all((event_id, sport, league, start, home_names, away_names, period)):
        return [], {}
    available = not bool(game.get("ended")) and not bool(game.get("live"))
    result: list[NormalizedProviderMarket] = []
    depths: dict[str, list[dict]] = {}
    containers = (
        ("awayMoneylines", "moneyline", "ml", "away", None),
        ("homeMoneylines", "moneyline", "ml", "home", None),
        ("awaySpreads", "spread", "sp", "away", "spread"),
        ("homeSpreads", "spread", "sp", "home", "spread"),
        ("over", "game_total", "ou", "over", "total"),
        ("under", "game_total", "ou", "under", "total"),
    )
    for field, market_name, bet_type, side, line_key in containers:
        offers = _offers(game.get(field))
        by_line: dict[float | None, list[dict]] = {}
        for offer in offers:
            line = float(offer.get(line_key)) if line_key and offer.get(line_key) is not None else None
            by_line.setdefault(line, []).append(offer)
        for line, levels in by_line.items():
            ordered = sorted(levels, key=lambda row: american_to_probability(_int_odds(row.get("odds"))) or 2)
            best = ordered[0]
            selection_id = str(best.get("id") or f"{event_id}:{field}:{line}")
            depths[selection_id] = [
                {"offer_id": str(row.get("id") or ""), "american_odds": _int_odds(row.get("odds")), "contract_price": american_to_probability(_int_odds(row.get("odds"))), "remaining": max(0.0, float(row.get("sumUntaken") or 0)), "created_at": row.get("createdAt")}
                for row in ordered if _int_odds(row.get("odds"))
            ]
            odds = _int_odds(best.get("odds"))
            rules = f"winner:{period}:draw_push" if market_name == "moneyline" else (f"spread:{period}:team" if market_name == "spread" else f"total:{period}:all")
            result.append(NormalizedProviderMarket(
                event_id=event_id, selection_id=selection_id, sport_id=sport, league_id=league,
                start_at=start, home_names=home_names, away_names=away_names,
                market_name=market_name, stat_id="points", stat_entity_id="all",
                period_id=period, bet_type_id=bet_type, side_id=side, line=line,
                is_alternative=False, display_odds=f"{odds:+d}" if odds else "Unavailable",
                american_odds=odds, deep_link=FOURCX_TRADE_URL,
                is_available=available and bool(odds) and bool(depths[selection_id]),
                last_updated=fetched_at.isoformat(), settlement_rules=rules,
            ))
    return result, depths


def _offers(value: object) -> list[dict]:
    if isinstance(value, list):
        return [row for item in value for row in _offers(item)]
    if isinstance(value, dict):
        if value.get("odds") is not None:
            return [value]
        return [row for item in value.values() for row in _offers(item)]
    return []


def _participant_names(row: dict) -> tuple[str, ...]:
    return tuple(_normalize_name(row.get(key)) for key in ("longName", "shortName") if _normalize_name(row.get(key)))


def _fourcx_period(value: object) -> str | None:
    name = str(value or "").strip().lower()
    return {"full time": "game", "game": "game", "first half": "1h", "1st half": "1h", "second half": "2h", "2nd half": "2h", "first quarter": "1q", "1st quarter": "1q", "first 5 innings": "1h"}.get(name)


def _int_odds(value: object) -> int | None:
    try:
        parsed = int(float(value))
        return parsed if parsed else None
    except (TypeError, ValueError):
        return None


def _recommended_stake(trade: dict) -> float:
    recommendation, card = trade.get("recommendation") or {}, trade.get("card") or {}
    try:
        return max(0.0, float(card.get("recommended_amount") or recommendation.get("recommended_amount") or 0))
    except (TypeError, ValueError):
        return 0.0


def _effective_price(levels: Iterable[dict], stake: float) -> tuple[float | None, float, bool]:
    rows = [row for row in levels if row.get("contract_price") is not None and float(row.get("remaining") or 0) > 0]
    liquidity = sum(float(row["remaining"]) for row in rows)
    if not rows:
        return None, 0.0, False
    if stake <= 0:
        return float(rows[0]["contract_price"]), liquidity, True
    remaining, cost = stake, 0.0
    for row in rows:
        fill = min(remaining, float(row["remaining"]))
        cost += fill * float(row["contract_price"])
        remaining -= fill
        if remaining <= 1e-9:
            return cost / stake, liquidity, True
    return None, liquidity, False
