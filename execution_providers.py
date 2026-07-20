from __future__ import annotations

import logging
import math
import re
import threading
import time
import unicodedata
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Iterable
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

import requests

from fair_price_engine import no_vig_probabilities

LOGGER = logging.getLogger(__name__)

POLYMARKET_LOGO_URL = "https://polymarket.com/icons/favicon-32x32.png"
NOVIG_LOGO_URL = (
    "https://cdn.prod.website-files.com/642ae772b9f3360398a9d449/"
    "6436d7c4d343f31dbf62d683_favicon.png"
)
NOVIG_BOOKMAKER_ID = "novig"
PROPHETX_SANDBOX_BASE_URL = "https://api-ss-sandbox.betprophet.co/partner"
PROPHETX_SANDBOX_TRADE_URL = "https://ss-sandbox.betprophet.co/"
PROPHETX_PRODUCTION_TRADE_URL = "https://www.prophetx.co/lobby/"
PROPHETX_LOGO_URL = "https://www.prophetx.co/favicon.ico"
PROPHETX_TOKEN_REFRESH_SECONDS = 9 * 60
EVENT_TIME_TOLERANCE = timedelta(minutes=10)
EASTERN = ZoneInfo("America/New_York")
MAX_PROVIDER_PAGES = 10


class MatchConfidence(str, Enum):
    EXACT = "Exact"
    PROBABLE = "Probable"
    NO_MATCH = "No Match"


class ProviderHealthStatus(str, Enum):
    CONFIGURED = "configured"
    AUTHENTICATED = "authenticated"
    UNAUTHORIZED = "unauthorized"
    CONNECTION_FAILED = "connection failed"


PROVIDER_NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"
MARKET_NOT_FOUND = "MARKET_NOT_FOUND"
MARKET_MAPPING_UNCERTAIN = "MARKET_MAPPING_UNCERTAIN"
NO_LIQUIDITY = "NO_LIQUIDITY"
INSUFFICIENT_LIQUIDITY = "INSUFFICIENT_LIQUIDITY"
STALE_QUOTE = "STALE_QUOTE"
MARKET_CLOSED = "MARKET_CLOSED"
MARKET_SUSPENDED = "MARKET_SUSPENDED"
PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
RATE_LIMITED = "RATE_LIMITED"


@dataclass(frozen=True)
class ExecutionOption:
    provider_name: str
    provider_key: str
    market_id: str
    selection_id: str
    display_odds: str
    deep_link: str | None
    is_available: bool
    last_updated: str | None
    matching_confidence: MatchConfidence
    logo_url: str
    tooltip: str
    american_odds: int | None = None
    contract_price: float | None = None
    effective_price: float | None = None
    available_liquidity: float | None = None
    can_fill_recommended_stake: bool | None = None
    fee_rate: float | None = None
    is_best_price: bool = False
    quote_status: str | None = None
    provider_event_id: str | None = None
    selection: str | None = None
    native_price_format: str | None = None
    implied_probability: float | None = None
    decimal_odds: float | None = None
    best_executable_price: float | None = None
    recommended_stake: float | None = None
    estimated_fees: float | None = None
    quote_age_seconds: float | None = None
    market_status: str | None = None
    is_exact_match: bool = True
    is_stale: bool = False
    failure_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "providerName": self.provider_name,
            "providerKey": self.provider_key,
            "marketId": self.market_id,
            "selectionId": self.selection_id,
            "displayOdds": self.display_odds,
            "deepLink": self.deep_link,
            "isAvailable": self.is_available,
            "lastUpdated": self.last_updated,
            "matchingConfidence": self.matching_confidence.value,
            "logoUrl": self.logo_url,
            "tooltip": self.tooltip,
            "americanOdds": self.american_odds,
            "contractPrice": self.contract_price,
            "effectivePrice": self.effective_price,
            "availableLiquidity": self.available_liquidity,
            "canFillRecommendedStake": self.can_fill_recommended_stake,
            "feeRate": self.fee_rate,
            "isBestPrice": self.is_best_price,
            "quoteStatus": self.quote_status,
            "providerEventId": self.provider_event_id or self.market_id,
            "providerMarketId": self.market_id,
            "providerOutcomeId": self.selection_id,
            "selection": self.selection,
            "nativePrice": self.display_odds,
            "nativePriceFormat": self.native_price_format,
            "impliedProbability": self.implied_probability,
            "decimalOdds": self.decimal_odds,
            "contractCents": None if self.contract_price is None else self.contract_price * 100,
            "bestExecutablePrice": self.best_executable_price,
            "effectiveEntryPrice": self.effective_price,
            "recommendedStake": self.recommended_stake,
            "estimatedFees": self.estimated_fees,
            "quoteTimestamp": self.last_updated,
            "quoteAgeSeconds": self.quote_age_seconds,
            "marketStatus": self.market_status or self.quote_status,
            "directMarketUrl": self.deep_link,
            "mappingConfidence": self.matching_confidence.value,
            "isExactMatch": self.is_exact_match,
            "isStale": self.is_stale,
            "failureReason": self.failure_reason,
        }


class ExecutionProvider(ABC):
    provider_name: str
    provider_key: str

    @abstractmethod
    def options_for_trades(self, trades: list[dict]) -> dict[str, ExecutionOption]:
        raise NotImplementedError

    def fair_price_quotes(self, trades: list[dict]) -> dict[str, dict]:
        """Return independently sourced no-vig quotes when supported."""
        return {}


class PolymarketProvider(ExecutionProvider):
    provider_name = "Polymarket"
    provider_key = "polymarket"

    def options_for_trades(self, trades: list[dict]) -> dict[str, ExecutionOption]:
        options: dict[str, ExecutionOption] = {}
        for trade in trades:
            trade_id = str(trade.get("id") or "").strip()
            deep_link = _exact_polymarket_link(trade)
            if not trade_id or not _valid_deep_link(deep_link):
                continue
            recommendation = trade.get("recommendation") or {}
            card = trade.get("card") or {}
            live_quote = trade.get("execution_quote") or {}
            current_price = _float_or_none(
                live_quote.get("best_ask")
                if live_quote.get("best_ask") is not None
                else card.get("current_actionable_price")
                if card.get("current_actionable_price") is not None
                else recommendation.get("current_user_entry_price")
            )
            display_odds = _format_cents(current_price)
            american_odds = probability_to_american(current_price)
            options[trade_id] = ExecutionOption(
                provider_name=self.provider_name,
                provider_key=self.provider_key,
                market_id=str(
                    (trade.get("validation_ids") or {}).get("condition_id")
                    or trade.get("event_slug")
                    or trade_id
                ),
                selection_id=str(
                    trade.get("clob_token_id")
                    or (trade.get("validation_ids") or {}).get("outcome_token_id")
                    or trade_id
                ),
                display_odds=display_odds,
                deep_link=deep_link,
                is_available=display_odds != "Unavailable",
                last_updated=live_quote.get("timestamp") or (trade.get("orderbook_summary") or {}).get("timestamp"),
                matching_confidence=MatchConfidence.EXACT,
                logo_url=POLYMARKET_LOGO_URL,
                tooltip="Polymarket Current Best Price",
                american_odds=american_odds,
                contract_price=current_price,
                effective_price=_float_or_none(live_quote.get("effective_price")) or current_price,
                available_liquidity=_float_or_none(live_quote.get("available_liquidity")) if live_quote else _float_or_none(trade.get("polymarket_available_liquidity")),
                can_fill_recommended_stake=live_quote.get("can_fill_recommended_stake") if live_quote else None,
                quote_status="OPEN" if live_quote.get("can_fill_recommended_stake") is not False else "INSUFFICIENT_DEPTH",
                provider_event_id=str(trade.get("event_slug") or (trade.get("validation_ids") or {}).get("condition_id") or trade_id),
                native_price_format="CENTS",
            )
        return options


def _exact_polymarket_link(trade: dict) -> str:
    event_slug = str(trade.get("event_slug") or "").strip()
    market_slug = str(trade.get("market_slug") or "").strip()
    if event_slug and market_slug:
        link = f"https://polymarket.com/event/{quote(event_slug, safe='-')}"
        if market_slug != event_slug:
            link += f"/{quote(market_slug, safe='-')}"
        return link
    return str(trade.get("market_url") or "").strip()


class ProphetXProvider(ExecutionProvider):
    provider_name = "ProphetX"
    provider_key = "prophetx"

    def __init__(
        self,
        access_key: str | None,
        secret_key: str | None,
        *,
        base_url: str = PROPHETX_SANDBOX_BASE_URL,
        trade_url: str | None = None,
        cache_ttl_seconds: int = 30,
        request_timeout: int = 15,
        session: requests.Session | None = None,
    ) -> None:
        self._access_key = str(access_key or "").strip() or None
        self._secret_key = str(secret_key or "").strip() or None
        self.base_url = base_url.rstrip("/")
        self.trade_url = str(trade_url or _default_prophetx_trade_url(base_url)).strip()
        self.cache_ttl_seconds = max(int(cache_ttl_seconds), 1)
        self.request_timeout = max(int(request_timeout), 1)
        self.session = session or requests.Session()
        self._health_status = (
            ProviderHealthStatus.CONFIGURED
            if self._access_key and self._secret_key
            else ProviderHealthStatus.CONNECTION_FAILED
        )
        self._health_lock = threading.RLock()
        self._bearer_token: str | None = None
        self._token_expires_at = 0.0
        self._market_cache: _CacheEntry | None = None
        self._last_matches: dict[str, ExecutionOption] = {}

    def __repr__(self) -> str:
        configured = bool(self._access_key and self._secret_key)
        return f"<ProphetXProvider configured={configured}>"

    def options_for_trades(self, trades: list[dict]) -> dict[str, ExecutionOption]:
        if not self._access_key or not self._secret_key or not trades:
            return {}
        canonical = [item for trade in trades if (item := canonicalize_trade(trade))]
        if not canonical:
            return {}

        try:
            index = self._prophetx_market_index()
        except (requests.RequestException, ValueError, TypeError):
            # Never log upstream response bodies because they may contain auth data.
            LOGGER.warning("ProphetX market refresh failed")
            return self._unavailable_last_matches(canonical)

        options: dict[str, ExecutionOption] = {}
        for trade in canonical:
            confidence, market = _match_exact_trade(trade, index)
            if confidence is not MatchConfidence.EXACT or market is None:
                continue
            available = bool(
                market.is_available
                and market.american_odds is not None
                and _valid_deep_link(market.deep_link)
            )
            options[trade.trade_id] = ExecutionOption(
                provider_name=self.provider_name,
                provider_key=self.provider_key,
                market_id=market.event_id,
                selection_id=market.selection_id,
                display_odds=market.display_odds if available else "Unavailable",
                deep_link=market.deep_link if available else None,
                is_available=available,
                last_updated=market.last_updated,
                matching_confidence=MatchConfidence.EXACT,
                logo_url=PROPHETX_LOGO_URL,
                tooltip="ProphetX Current Best Price",
                american_odds=market.american_odds if available else None,
            )

        with self._health_lock:
            self._last_matches.update(options)
        return options

    def fair_price_quotes(self, trades: list[dict]) -> dict[str, dict]:
        if not self._access_key or not self._secret_key or not trades:
            return {}
        canonical = [item for trade in trades if (item := canonicalize_trade(trade))]
        if not canonical:
            return {}
        try:
            return _fair_quotes_from_index(
                canonical, self._prophetx_market_index(), self.provider_key
            )
        except (requests.RequestException, ValueError, TypeError):
            LOGGER.warning("ProphetX fair-price refresh failed")
            return {}

    def _unavailable_last_matches(
        self, trades: list[CanonicalTrade]
    ) -> dict[str, ExecutionOption]:
        with self._health_lock:
            return {
                trade.trade_id: replace(
                    previous,
                    display_odds="Unavailable",
                    deep_link=None,
                    is_available=False,
                    american_odds=None,
                )
                for trade in trades
                if (previous := self._last_matches.get(trade.trade_id)) is not None
            }

    def _prophetx_market_index(self) -> ProviderMarketIndex:
        now = time.monotonic()
        with self._health_lock:
            if self._market_cache and now - self._market_cache.loaded_at < self.cache_ttl_seconds:
                return self._market_cache.index

        token = self._access_token()
        headers = {"Authorization": token, "Accept": "application/json"}
        tournaments = self._get_data("/affiliate/get_tournaments", headers)
        events = self._get_data("/affiliate/get_sport_events", headers)
        tournament_rows = _payload_list(tournaments, "tournaments")
        event_rows = _payload_list(events, "sport_events")
        event_ids = [str(row.get("event_id")) for row in event_rows if row.get("event_id") is not None]
        markets: object = {}
        if event_ids:
            markets = self._get_data(
                "/v3/affiliate/get_multiple_markets",
                headers,
                params=[("event_ids", event_id) for event_id in event_ids],
            )
        index = ProviderMarketIndex(
            normalize_prophetx_markets(
                tournament_rows,
                event_rows,
                markets,
                trade_url=self.trade_url,
            )
        )
        with self._health_lock:
            self._market_cache = _CacheEntry(loaded_at=now, index=index)
        return index

    def _get_data(self, path: str, headers: dict, *, params=None) -> object:
        response = self.session.get(
            f"{self.base_url}{path}",
            headers=headers,
            params=params,
            timeout=self.request_timeout,
        )
        if int(getattr(response, "status_code", 0)) == 401:
            with self._health_lock:
                self._bearer_token = None
                self._token_expires_at = 0.0
            headers = {**headers, "Authorization": self._access_token()}
            response = self.session.get(
                f"{self.base_url}{path}",
                headers=headers,
                params=params,
                timeout=self.request_timeout,
            )
        response.raise_for_status()
        payload = response.json()
        return payload.get("data") if isinstance(payload, dict) else None

    def _access_token(self) -> str:
        if self.health_status(authenticate=True) is not ProviderHealthStatus.AUTHENTICATED:
            raise ValueError("ProphetX authentication unavailable")
        with self._health_lock:
            if not self._bearer_token:
                raise ValueError("ProphetX authentication unavailable")
            return f"Bearer {self._bearer_token}"

    def health_status(self, *, authenticate: bool = False) -> ProviderHealthStatus:
        if not self._access_key or not self._secret_key:
            return ProviderHealthStatus.CONNECTION_FAILED
        if not authenticate:
            return self._health_status

        with self._health_lock:
            if self._bearer_token and time.monotonic() < self._token_expires_at:
                return ProviderHealthStatus.AUTHENTICATED

        try:
            response = self.session.post(
                f"{self.base_url}/auth/login",
                json={
                    "access_key": self._access_key,
                    "secret_key": self._secret_key,
                },
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=self.request_timeout,
            )
            status_code = int(getattr(response, "status_code", 0))
            if status_code in {400, 401, 403}:
                result = ProviderHealthStatus.UNAUTHORIZED
            elif status_code != 200:
                result = ProviderHealthStatus.CONNECTION_FAILED
            else:
                payload = response.json()
                token = ((payload or {}).get("data") or {}).get("access_token")
                result = (
                    ProviderHealthStatus.AUTHENTICATED
                    if isinstance(token, str) and token.strip()
                    else ProviderHealthStatus.CONNECTION_FAILED
                )
        except Exception:
            # This boundary deliberately suppresses provider exception details so
            # credentials and upstream response bodies can never reach logs or APIs.
            result = ProviderHealthStatus.CONNECTION_FAILED

        with self._health_lock:
            self._health_status = result
            if result is ProviderHealthStatus.AUTHENTICATED:
                self._bearer_token = token.strip()
                self._token_expires_at = (
                    time.monotonic() + PROPHETX_TOKEN_REFRESH_SECONDS
                )
            else:
                self._bearer_token = None
                self._token_expires_at = 0.0
        return result


@dataclass(frozen=True)
class CanonicalTrade:
    trade_id: str
    sport_id: str
    league_id: str
    start_at: datetime
    participants: tuple[str, str]
    outcome: str
    market_kind: str
    period_id: str
    line: float | None
    side_id: str
    settlement_rules: str
    is_alternative: bool


@dataclass(frozen=True)
class NormalizedProviderMarket:
    event_id: str
    selection_id: str
    sport_id: str
    league_id: str
    start_at: datetime
    home_names: tuple[str, ...]
    away_names: tuple[str, ...]
    market_name: str
    stat_id: str
    stat_entity_id: str
    period_id: str
    bet_type_id: str
    side_id: str
    line: float | None
    is_alternative: bool
    display_odds: str
    american_odds: int | None
    deep_link: str | None
    is_available: bool
    last_updated: str | None
    settlement_rules: str


class ProviderMarketIndex:
    def __init__(self, markets: Iterable[NormalizedProviderMarket]) -> None:
        self.markets = tuple(markets)
        self._by_sport_and_time: dict[
            tuple[str, int], list[NormalizedProviderMarket]
        ] = defaultdict(list)
        self._by_sport_and_day: dict[tuple[str, object], list[NormalizedProviderMarket]] = defaultdict(list)
        for market in self.markets:
            self._by_sport_and_time[
                (market.sport_id, _time_bucket(market.start_at))
            ].append(market)
            self._by_sport_and_day[(market.sport_id, market.start_at.astimezone(EASTERN).date())].append(market)

    def candidates(self, trade: CanonicalTrade, *, allow_same_day: bool = False) -> list[NormalizedProviderMarket]:
        bucket = _time_bucket(trade.start_at)
        candidates: list[NormalizedProviderMarket] = []
        for offset in (-1, 0, 1):
            candidates.extend(
                self._by_sport_and_time.get((trade.sport_id, bucket + offset), [])
            )
        if allow_same_day:
            candidates.extend(self._by_sport_and_day.get((trade.sport_id, trade.start_at.astimezone(EASTERN).date()), []))
        return list(dict.fromkeys(candidates))


def _equivalent_market_key(market: NormalizedProviderMarket) -> tuple:
    return (
        market.event_id,
        market.sport_id,
        market.league_id,
        market.market_name,
        market.stat_id,
        market.stat_entity_id,
        market.period_id,
        market.bet_type_id,
        market.line,
        market.is_alternative,
        market.settlement_rules,
    )


def _fair_quotes_from_index(
    trades: list[CanonicalTrade], index: ProviderMarketIndex, provider_key: str
) -> dict[str, dict]:
    results: dict[str, dict] = {}
    for trade in trades:
        confidence, matched = _match_exact_trade(trade, index)
        if confidence is not MatchConfidence.EXACT or matched is None:
            continue
        siblings = [
            row
            for row in index.markets
            if _equivalent_market_key(row) == _equivalent_market_key(matched)
            and row.is_available
            and row.american_odds is not None
        ]
        probabilities = no_vig_probabilities(row.american_odds for row in siblings)
        if probabilities is None:
            continue
        selected_index = next(
            (position for position, row in enumerate(siblings) if row.selection_id == matched.selection_id),
            None,
        )
        if selected_index is None:
            continue
        results[trade.trade_id] = {
            "provider": provider_key,
            "status": "AVAILABLE",
            "quote_timestamp": matched.last_updated,
            "mapping_confidence": "EXACT",
            "provider_event_id": matched.event_id,
            "provider_market_id": "::".join(str(item) for item in _equivalent_market_key(matched)),
            "provider_selection_id": matched.selection_id,
            "sport": matched.sport_id,
            "league": matched.league_id,
            "start_time": matched.start_at.isoformat(),
            "home_participant": matched.home_names[0] if matched.home_names else None,
            "away_participant": matched.away_names[0] if matched.away_names else None,
            "market_type": matched.market_name,
            "period": matched.period_id,
            "line": matched.line,
            "selection": matched.side_id,
            "settlement_rules": matched.settlement_rules,
            "native_odds": matched.display_odds,
            "american_odds": matched.american_odds,
            "raw_implied_probability": american_to_probability(matched.american_odds),
            "no_vig_probability": probabilities[selected_index],
            "outcome_count": len(siblings),
            "liquidity": None,
            "limits": None,
            "quality_metadata": {"liquidity_status": "UNAVAILABLE"},
            "fabricated_data": False,
        }
    return results


def american_to_probability(value: int | None) -> float | None:
    if value is None or value == 0:
        return None
    return 100.0 / (value + 100.0) if value > 0 else -value / (-value + 100.0)


@dataclass
class _CacheEntry:
    loaded_at: float
    index: ProviderMarketIndex


class NoVIGProvider(ExecutionProvider):
    provider_name = "NoVIG"
    provider_key = "novig"

    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str = "https://api.sportsgameodds.com/v2",
        cache_ttl_seconds: int = 45,
        request_timeout: int = 15,
        session: requests.Session | None = None,
    ) -> None:
        self.api_key = str(api_key or "").strip() or None
        self.base_url = base_url.rstrip("/")
        self.cache_ttl_seconds = max(int(cache_ttl_seconds), 1)
        self.request_timeout = max(int(request_timeout), 1)
        self.session = session or requests.Session()
        self._cache: dict[tuple[str, str], _CacheEntry] = {}
        self._last_matches: dict[str, ExecutionOption] = {}
        self._lock = threading.RLock()

    def options_for_trades(self, trades: list[dict]) -> dict[str, ExecutionOption]:
        if not self.api_key or not trades:
            return {}

        canonical = [item for trade in trades if (item := canonicalize_trade(trade))]
        if not canonical:
            return {}

        try:
            index = self._market_index(canonical)
        except (requests.RequestException, ValueError, TypeError) as exc:
            LOGGER.warning("NoVIG odds refresh failed: %s", exc)
            return self._unavailable_last_matches(canonical)

        options: dict[str, ExecutionOption] = {}
        for trade in canonical:
            confidence, market = self.match_trade(trade, index)
            if confidence is not MatchConfidence.EXACT or market is None:
                continue
            option = self._execution_option(market)
            options[trade.trade_id] = option

        with self._lock:
            for trade_id, option in options.items():
                self._last_matches[trade_id] = option
        return options

    def fair_price_quotes(self, trades: list[dict]) -> dict[str, dict]:
        if not self.api_key or not trades:
            return {}
        canonical = [item for trade in trades if (item := canonicalize_trade(trade))]
        if not canonical:
            return {}
        try:
            return _fair_quotes_from_index(
                canonical, self._market_index(canonical), self.provider_key
            )
        except (requests.RequestException, ValueError, TypeError):
            LOGGER.warning("NoVIG fair-price refresh failed")
            return {}

    def match_trade(
        self, trade: CanonicalTrade, index: ProviderMarketIndex
    ) -> tuple[MatchConfidence, NormalizedProviderMarket | None]:
        return _match_exact_trade(trade, index)

    def _execution_option(self, market: NormalizedProviderMarket) -> ExecutionOption:
        available = bool(
            market.is_available
            and market.american_odds is not None
            and _valid_deep_link(market.deep_link)
        )
        return ExecutionOption(
            provider_name=self.provider_name,
            provider_key=self.provider_key,
            market_id=market.event_id,
            selection_id=market.selection_id,
            display_odds=market.display_odds if available else "Unavailable",
            deep_link=market.deep_link if available else None,
            is_available=available,
            last_updated=market.last_updated,
            matching_confidence=MatchConfidence.EXACT,
            logo_url=NOVIG_LOGO_URL,
            tooltip="NoVIG Current Best Price",
            american_odds=market.american_odds if available else None,
        )

    def _unavailable_last_matches(
        self, trades: list[CanonicalTrade]
    ) -> dict[str, ExecutionOption]:
        with self._lock:
            return {
                trade.trade_id: replace(
                    previous,
                    display_odds="Unavailable",
                    deep_link=None,
                    is_available=False,
                    american_odds=None,
                )
                for trade in trades
                if (previous := self._last_matches.get(trade.trade_id)) is not None
            }

    def _market_index(self, trades: list[CanonicalTrade]) -> ProviderMarketIndex:
        first_start = min(trade.start_at for trade in trades)
        last_start = max(trade.start_at for trade in trades)
        starts_after = (first_start - timedelta(hours=6)).astimezone(timezone.utc)
        starts_before = (last_start + timedelta(hours=6)).astimezone(timezone.utc)
        cache_key = (starts_after.date().isoformat(), starts_before.date().isoformat())
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and now - cached.loaded_at < self.cache_ttl_seconds:
                return cached.index

            events = self._fetch_events(starts_after, starts_before)
            index = ProviderMarketIndex(normalize_novig_events(events))
            self._cache[cache_key] = _CacheEntry(loaded_at=now, index=index)
            return index

    def _fetch_events(
        self, starts_after: datetime, starts_before: datetime
    ) -> list[dict]:
        events: list[dict] = []
        cursor: str | None = None
        for _page in range(MAX_PROVIDER_PAGES):
            params = {
                "bookmakerID": NOVIG_BOOKMAKER_ID,
                "oddsPresent": "true",
                "started": "false",
                "includeAltLines": "true",
                "startsAfter": _iso_utc(starts_after),
                "startsBefore": _iso_utc(starts_before),
                "limit": 100,
            }
            if cursor:
                params["cursor"] = cursor
            response = self.session.get(
                f"{self.base_url}/events",
                params=params,
                headers={"x-api-key": self.api_key},
                timeout=self.request_timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("success") is False:
                raise ValueError(payload.get("message") or "Provider returned an error")
            page_events = payload.get("data") or []
            if not isinstance(page_events, list):
                raise ValueError("Provider response data must be a list")
            events.extend(item for item in page_events if isinstance(item, dict))
            cursor = str(payload.get("nextCursor") or "").strip() or None
            if not cursor:
                return events
        raise ValueError("Provider response exceeded the pagination safety limit")


class ExecutionProviderRegistry:
    def __init__(
        self,
        providers: Iterable[ExecutionProvider],
        *,
        max_quote_age_seconds: int = 60,
        min_liquidity: float = 0.0,
        include_fees: bool = True,
        comparison_provider_keys: Iterable[str] = ("polymarket", "kalshi", "fourcx"),
    ) -> None:
        self.providers = tuple(providers)
        self.max_quote_age_seconds = max(1, int(max_quote_age_seconds))
        self.min_liquidity = max(0.0, float(min_liquidity))
        self.include_fees = bool(include_fees)
        self.comparison_provider_keys = frozenset(str(key).lower() for key in comparison_provider_keys)

    def attach_options(self, trades: list[dict]) -> list[dict]:
        by_provider: list[tuple[ExecutionProvider, dict[str, ExecutionOption]]] = []
        provider_failures: dict[str, str] = {}
        for provider in self.providers:
            try:
                by_provider.append((provider, provider.options_for_trades(trades)))
            except requests.HTTPError as exc:
                LOGGER.exception("Execution provider %s failed", provider.provider_key)
                status = getattr(exc.response, "status_code", None)
                provider_failures[provider.provider_key] = RATE_LIMITED if status == 429 else PROVIDER_UNAVAILABLE
                by_provider.append((provider, {}))
            except Exception:
                LOGGER.exception("Execution provider %s failed", provider.provider_key)
                provider_failures[provider.provider_key] = PROVIDER_UNAVAILABLE
                by_provider.append((provider, {}))

        for trade in trades:
            trade_id = str(trade.get("id") or "")
            found: list[ExecutionOption] = []
            failures: dict[str, str] = {}
            for provider, options in by_provider:
                option = options.get(trade_id)
                if option is None:
                    failures[provider.provider_key] = provider_failures.get(provider.provider_key) or getattr(provider, "failure_reasons", {}).get(trade_id, MARKET_NOT_FOUND)
                    continue
                if option.matching_confidence is not MatchConfidence.EXACT:
                    failures[provider.provider_key] = MARKET_MAPPING_UNCERTAIN
                    continue
                finalized = (
                    _finalize_execution_option(
                        option,
                        trade,
                        max_quote_age_seconds=self.max_quote_age_seconds,
                        min_liquidity=self.min_liquidity,
                        include_fees=self.include_fees,
                    )
                    if option.provider_key in self.comparison_provider_keys
                    else option
                )
                found.append(finalized)
                if finalized.failure_reason:
                    failures[provider.provider_key] = finalized.failure_reason
            executable = [
                item for item in found
                if item.provider_key in self.comparison_provider_keys
                and item.is_available
                and item.is_exact_match
                and not item.is_stale
                and item.market_status == "OPEN"
                and item.can_fill_recommended_stake is True
                and item.best_executable_price is not None
                and _valid_deep_link(item.deep_link)
            ]
            if executable:
                best = min(executable, key=lambda item: item.best_executable_price)
                found = [replace(item, is_best_price=item is best) for item in found]
            trade["executionOptions"] = [item.to_dict() for item in found]
            trade["lineShopFailures"] = failures
        return trades

    def fair_price_quotes(self, trades: list[dict]) -> dict[str, list[dict]]:
        quotes: dict[str, list[dict]] = defaultdict(list)
        for provider in self.providers:
            if provider.provider_key == "polymarket":
                continue
            try:
                rows = provider.fair_price_quotes(trades)
            except Exception:
                LOGGER.exception("Fair-price provider %s failed", provider.provider_key)
                rows = {}
            for trade_id, quote in rows.items():
                quotes[trade_id].append(quote)
        return dict(quotes)

    def fair_price_provider_health(self) -> list[dict]:
        rows = []
        for provider in self.providers:
            if provider.provider_key == "polymarket":
                continue
            checker = getattr(provider, "health_status", None)
            if callable(checker):
                status = checker(authenticate=False).value
            elif provider.provider_key == "novig":
                status = "configured" if bool(getattr(provider, "api_key", None)) else "unavailable"
            else:
                status = "unavailable"
            rows.append(
                {
                    "provider": provider.provider_key,
                    "status": status,
                    "supports_fair_price": True,
                    "fabricated_data": False,
                }
            )
        return rows

    def provider_health(
        self, provider_key: str, *, authenticate: bool = False
    ) -> ProviderHealthStatus:
        provider = next(
            (
                item
                for item in self.providers
                if item.provider_key == str(provider_key or "").strip().lower()
            ),
            None,
        )
        checker = getattr(provider, "health_status", None)
        if not callable(checker):
            return ProviderHealthStatus.CONNECTION_FAILED
        try:
            return checker(authenticate=authenticate)
        except Exception:
            return ProviderHealthStatus.CONNECTION_FAILED

    def provider_diagnostics(self, provider_key: str, *, authenticate: bool = False) -> dict:
        provider = next((item for item in self.providers if item.provider_key == str(provider_key or "").strip().lower()), None)
        diagnostics = getattr(provider, "diagnostics", None)
        if not callable(diagnostics):
            return {"provider": provider_key, "status": "NOT_CONFIGURED"}
        try:
            return diagnostics(authenticate=authenticate)
        except Exception:
            return {"provider": provider_key, "status": "ERROR", "last_error_code": "DIAGNOSTIC_FAILED"}


def _recommended_stake(trade: dict) -> float:
    recommendation = trade.get("recommendation") or {}
    card = trade.get("card") or {}
    return max(
        0.0,
        _float_or_none(card.get("recommended_amount"))
        or _float_or_none(recommendation.get("recommended_amount"))
        or 0.0,
    )


def _quote_age_seconds(value: str | None, now: datetime) -> float | None:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds())


def _finalize_execution_option(
    option: ExecutionOption,
    trade: dict,
    *,
    max_quote_age_seconds: int,
    min_liquidity: float,
    include_fees: bool,
    now: datetime | None = None,
) -> ExecutionOption:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stake = _recommended_stake(trade)
    age = _quote_age_seconds(option.last_updated, now)
    stale = age is None or age > max_quote_age_seconds
    market_status = str(option.quote_status or ("OPEN" if option.is_available else "UNAVAILABLE")).upper()
    failure = option.failure_reason
    liquidity = option.available_liquidity
    can_fill = option.can_fill_recommended_stake
    if stake <= 0 and can_fill is None:
        can_fill = liquidity is not None and liquidity > 0

    if market_status in {"CLOSED", MARKET_CLOSED}:
        market_status, failure = "CLOSED", MARKET_CLOSED
    elif market_status in {"SUSPENDED", MARKET_SUSPENDED}:
        market_status, failure = "SUSPENDED", MARKET_SUSPENDED
    elif stale:
        failure = STALE_QUOTE
    elif liquidity is not None and liquidity <= 0:
        failure = NO_LIQUIDITY
    elif liquidity is not None and liquidity < min_liquidity:
        failure = INSUFFICIENT_LIQUIDITY
    elif can_fill is False or (stake > 0 and can_fill is not True) or market_status == "INSUFFICIENT_DEPTH":
        failure = INSUFFICIENT_LIQUIDITY
    elif not option.is_available:
        failure = failure or PROVIDER_UNAVAILABLE

    raw_price = (
        option.effective_price
        if option.effective_price is not None
        else option.contract_price
        if option.contract_price is not None
        else american_to_probability(option.american_odds)
    )
    estimated_fees = option.estimated_fees
    if estimated_fees is None and option.fee_rate is not None and stake > 0:
        estimated_fees = stake * max(0.0, option.fee_rate)
    all_in_price = raw_price
    if (
        include_fees
        and raw_price is not None
        and estimated_fees is not None
        and stake > 0
    ):
        all_in_price = raw_price * (1.0 + estimated_fees / stake)
    if all_in_price is not None and not 0 < all_in_price < 1:
        all_in_price = None

    provider_key = option.provider_key.lower()
    native_format = option.native_price_format or (
        "CENTS" if provider_key in {"polymarket", "kalshi"} else "AMERICAN"
    )
    contract_price = option.contract_price
    display = option.display_odds
    if provider_key in {"polymarket", "kalshi"} and contract_price is not None:
        display = _format_cents(contract_price)
    elif provider_key == "fourcx" and option.american_odds is not None:
        display = f"{option.american_odds:+d}"

    executable = bool(
        failure is None
        and option.is_available
        and option.matching_confidence is MatchConfidence.EXACT
        and market_status == "OPEN"
        and can_fill is True
        and all_in_price is not None
        and _valid_deep_link(option.deep_link)
    )
    return replace(
        option,
        display_odds=display,
        is_available=executable,
        selection=str(trade.get("outcome") or ""),
        native_price_format=native_format,
        implied_probability=all_in_price,
        decimal_odds=(1.0 / all_in_price) if all_in_price else None,
        best_executable_price=all_in_price,
        recommended_stake=stake,
        estimated_fees=estimated_fees,
        quote_age_seconds=age,
        market_status=market_status,
        is_exact_match=option.matching_confidence is MatchConfidence.EXACT,
        is_stale=stale,
        can_fill_recommended_stake=can_fill,
        failure_reason=failure,
        is_best_price=False,
    )


def build_execution_provider_registry(settings) -> ExecutionProviderRegistry:
    from fourcx_provider import FourCXProvider
    from kalshi_provider import KalshiProvider

    return ExecutionProviderRegistry(
        (
            PolymarketProvider(),
            NoVIGProvider(
                getattr(settings, "novig_api_key", None),
                base_url=getattr(
                    settings,
                    "novig_api_base_url",
                    "https://api.sportsgameodds.com/v2",
                ),
                cache_ttl_seconds=getattr(settings, "novig_cache_ttl_seconds", 45),
                request_timeout=getattr(settings, "request_timeout", 15),
            ),
            ProphetXProvider(
                getattr(settings, "prophetx_access_key", None),
                getattr(settings, "prophetx_secret_key", None),
                base_url=getattr(
                    settings,
                    "prophetx_api_base_url",
                    PROPHETX_SANDBOX_BASE_URL,
                ),
                trade_url=getattr(settings, "prophetx_trade_url", None),
                cache_ttl_seconds=getattr(
                    settings, "prophetx_cache_ttl_seconds", 30
                ),
                request_timeout=getattr(settings, "request_timeout", 15),
            ),
            FourCXProvider(
                getattr(settings, "fourcx_username", None),
                getattr(settings, "fourcx_password", None),
                enabled=getattr(settings, "fourcx_enabled", False),
                trading_enabled=getattr(settings, "fourcx_trading_enabled", False),
                base_url=getattr(settings, "fourcx_api_base_url", "https://api.4cx.io"),
                cache_ttl_seconds=getattr(settings, "fourcx_cache_ttl_seconds", 30),
                request_timeout=getattr(settings, "request_timeout", 15),
                max_quote_age_seconds=getattr(settings, "execution_quote_max_age_seconds", 60),
            ),
            KalshiProvider(
                enabled=getattr(settings, "kalshi_enabled", True),
                base_url=getattr(settings, "kalshi_api_base_url", "https://external-api.kalshi.com/trade-api/v2"),
                cache_ttl_seconds=getattr(settings, "kalshi_cache_ttl_seconds", 1),
                request_timeout=getattr(settings, "request_timeout", 15),
            ),
        ),
        max_quote_age_seconds=getattr(settings, "line_shop_max_quote_age_seconds", 60),
        min_liquidity=getattr(settings, "line_shop_min_liquidity", 0.0),
        include_fees=getattr(settings, "line_shop_include_fees", True),
    )


def canonicalize_trade(trade: dict) -> CanonicalTrade | None:
    trade_id = str(trade.get("id") or "").strip()
    sport_id = _canonical_sport_id(
        trade.get("canonical_sport_id") or trade.get("category")
    )
    league_id = _normalize_identifier(
        trade.get("canonical_league_id") or trade.get("league")
    )
    start_at = _parse_datetime(trade.get("event_date_et"))
    participants = _event_participants(
        trade.get("event_title") or trade.get("market_title")
    )
    outcome = str(trade.get("outcome") or "").strip()
    market_kind = _canonical_market_kind(trade)
    if not all((trade_id, sport_id, league_id, start_at, participants, outcome, market_kind)):
        return None

    period_id = _canonical_period_id(trade, sport_id, market_kind)
    line = _source_line(trade, market_kind)
    side_id = _source_side(trade, market_kind, outcome)
    settlement_rules = _source_settlement_rules(
        market_kind, sport_id, period_id
    )
    if not side_id or not settlement_rules:
        return None
    if market_kind in {"spread", "game_total", "team_total"} and line is None:
        return None

    title_blob = " ".join(
        str(trade.get(key) or "")
        for key in ("sports_market_type", "market_title", "outcome")
    )
    return CanonicalTrade(
        trade_id=trade_id,
        sport_id=sport_id,
        league_id=league_id,
        start_at=start_at,
        participants=participants,
        outcome=outcome,
        market_kind=market_kind,
        period_id=period_id,
        line=line,
        side_id=side_id,
        settlement_rules=settlement_rules,
        is_alternative=bool(re.search(r"\b(?:alt|alternative)\b", title_blob, re.I)),
    )


def normalize_novig_events(events: Iterable[dict]) -> list[NormalizedProviderMarket]:
    normalized: list[NormalizedProviderMarket] = []
    for event in events:
        event_id = str(event.get("eventID") or "").strip()
        sport_id = _canonical_sport_id(event.get("sportID"))
        league_id = _normalize_identifier(event.get("leagueID"))
        start_at = _parse_datetime((event.get("status") or {}).get("startsAt"))
        home_names = _provider_team_names((event.get("teams") or {}).get("home"))
        away_names = _provider_team_names((event.get("teams") or {}).get("away"))
        event_link = ((event.get("links") or {}).get("bookmakers") or {}).get(
            NOVIG_BOOKMAKER_ID
        )
        if not all((event_id, sport_id, league_id, start_at, home_names, away_names)):
            continue

        for odd_id, odd in (event.get("odds") or {}).items():
            if not isinstance(odd, dict):
                continue
            book = (odd.get("byBookmaker") or {}).get(NOVIG_BOOKMAKER_ID)
            if not isinstance(book, dict):
                continue
            snapshots = [(book, False)]
            snapshots.extend(
                (alt, True)
                for alt in book.get("altLines") or []
                if isinstance(alt, dict)
            )
            for snapshot, is_alternative in snapshots:
                period_id = _normalize_period_id(odd.get("periodID"))
                bet_type_id = _normalize_identifier(odd.get("betTypeID")).lower()
                side_id = _normalize_identifier(odd.get("sideID")).lower()
                stat_entity_id = _normalize_identifier(
                    odd.get("statEntityID")
                ).lower()
                market_name = str(odd.get("marketName") or "").strip()
                settlement_rules = _provider_settlement_rules(
                    bet_type_id,
                    sport_id,
                    period_id,
                    stat_entity_id,
                    market_name,
                )
                if not settlement_rules:
                    continue
                american_odds, display_odds = _american_odds(snapshot.get("odds"))
                line = _provider_line(bet_type_id, snapshot)
                deep_link = snapshot.get("deeplink") or book.get("deeplink") or event_link
                selection_id = str(odd.get("oddID") or odd_id)
                if is_alternative and line is not None:
                    selection_id = f"{selection_id}@{line:g}"
                normalized.append(
                    NormalizedProviderMarket(
                        event_id=event_id,
                        selection_id=selection_id,
                        sport_id=sport_id,
                        league_id=league_id,
                        start_at=start_at,
                        home_names=home_names,
                        away_names=away_names,
                        market_name=market_name,
                        stat_id=_normalize_identifier(odd.get("statID")).lower(),
                        stat_entity_id=stat_entity_id,
                        period_id=period_id,
                        bet_type_id=bet_type_id,
                        side_id=side_id,
                        line=line,
                        is_alternative=is_alternative,
                        display_odds=display_odds,
                        american_odds=american_odds,
                        deep_link=str(deep_link or "").strip() or None,
                        is_available=snapshot.get("available") is True,
                        last_updated=str(
                            snapshot.get("lastUpdatedAt")
                            or book.get("lastUpdatedAt")
                            or ""
                        ).strip()
                        or None,
                        settlement_rules=settlement_rules,
                    )
                )
    return normalized


def normalize_prophetx_markets(
    tournaments: Iterable[dict],
    events: Iterable[dict],
    markets_payload: object,
    *,
    trade_url: str,
) -> list[NormalizedProviderMarket]:
    tournament_map = {
        str(row.get("id")): row
        for row in tournaments
        if isinstance(row, dict) and row.get("id") is not None
    }
    markets_by_event = _prophetx_markets_by_event(markets_payload)
    normalized: list[NormalizedProviderMarket] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("event_id") or "").strip()
        tournament = tournament_map.get(str(event.get("tournament_id")), {})
        sport_id = _canonical_sport_id(
            tournament.get("sport") or event.get("sport")
        )
        league_id = _prophetx_league_id(
            tournament.get("name") or event.get("league")
        )
        start_at = _parse_datetime(event.get("start_time"))
        home_names = _provider_names(event.get("home_team"))
        away_names = _provider_names(event.get("away_team"))
        if not all((event_id, sport_id, league_id, start_at, home_names, away_names)):
            continue

        event_link = str(
            event.get("deep_link")
            or event.get("deeplink")
            or event.get("url")
            or trade_url
            or ""
        ).strip() or None
        for market in markets_by_event.get(event_id, []):
            if not isinstance(market, dict):
                continue
            market_type = _normalize_name(
                market.get("market_type") or market.get("type")
            )
            period_id = _prophetx_period_id(market)
            is_alternative = bool(market.get("is_alternative")) or bool(
                re.search(
                    r"\b(?:alt|alternative)\b",
                    " ".join(
                        str(market.get(key) or "")
                        for key in ("name", "category_name", "sub_type")
                    ),
                    re.I,
                )
            )
            for selection in _flatten_prophetx_selections(market.get("selections")):
                selection_name = str(selection.get("name") or "").strip()
                side_id, stat_entity_id = _prophetx_selection_side(
                    market_type,
                    selection_name,
                    home_names,
                    away_names,
                )
                if not side_id:
                    continue
                line = _float_or_none(selection.get("line"))
                rules, bet_type_id, stat_id = _prophetx_settlement_rules(
                    market_type,
                    sport_id,
                    period_id,
                    stat_entity_id,
                )
                if not rules:
                    continue
                american_odds, display_odds = _decimal_to_american_odds(
                    selection.get("odds")
                )
                selection_link = str(
                    selection.get("deep_link")
                    or selection.get("deeplink")
                    or market.get("deep_link")
                    or market.get("deeplink")
                    or event_link
                    or ""
                ).strip() or None
                selection_id = str(
                    selection.get("id")
                    or selection.get("selection_id")
                    or selection.get("strike_id")
                    or ""
                ).strip()
                if not selection_id:
                    continue
                normalized.append(
                    NormalizedProviderMarket(
                        event_id=str(market.get("market_id") or event_id),
                        selection_id=selection_id,
                        sport_id=sport_id,
                        league_id=league_id,
                        start_at=start_at,
                        home_names=home_names,
                        away_names=away_names,
                        market_name=str(market.get("name") or market_type),
                        stat_id=stat_id,
                        stat_entity_id=stat_entity_id,
                        period_id=period_id,
                        bet_type_id=bet_type_id,
                        side_id=side_id,
                        line=line,
                        is_alternative=is_alternative,
                        display_odds=display_odds,
                        american_odds=american_odds,
                        deep_link=selection_link,
                        is_available=bool(
                            american_odds is not None
                            and (_float_or_none(selection.get("liquidity")) or 0) > 0
                        ),
                        last_updated=str(
                            selection.get("updated_at")
                            or market.get("updated_at")
                            or ""
                        ).strip()
                        or None,
                        settlement_rules=rules,
                    )
                )
    return normalized


def _payload_list(payload: object, key: str) -> list[dict]:
    if isinstance(payload, dict):
        payload = payload.get(key, [])
    return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def _prophetx_markets_by_event(payload: object) -> dict[str, list[dict]]:
    if isinstance(payload, list):
        grouped: dict[str, list[dict]] = defaultdict(list)
        for market in payload:
            if isinstance(market, dict) and market.get("event_id") is not None:
                grouped[str(market["event_id"])].append(market)
        return grouped
    if not isinstance(payload, dict):
        return {}
    return {
        str(event_id): [market for market in markets if isinstance(market, dict)]
        for event_id, markets in payload.items()
        if isinstance(markets, list)
    }


def _flatten_prophetx_selections(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    flattened: list[dict] = []
    for item in value:
        if isinstance(item, dict):
            flattened.append(item)
        elif isinstance(item, list):
            flattened.extend(child for child in item if isinstance(child, dict))
    return flattened


def _provider_names(value: object) -> tuple[str, ...]:
    normalized = _normalize_name(value)
    return (normalized,) if normalized else ()


def _prophetx_league_id(value: object) -> str:
    normalized = _normalize_name(value)
    known = ("NFL", "NCAAF", "MLB", "NBA", "WNBA", "NCAAB", "NHL", "MLS", "ATP", "WTA", "ITF")
    tokens = set(normalized.upper().split())
    for league in known:
        if league in tokens:
            return league
    return _normalize_identifier(value)


def _prophetx_period_id(market: dict) -> str:
    value = _normalize_name(
        market.get("period")
        or market.get("period_name")
        or market.get("sub_type")
        or market.get("name")
    )
    for labels, period_id in (
        (("first half", "1st half"), "1h"),
        (("second half", "2nd half"), "2h"),
        (("first quarter", "1st quarter"), "1q"),
        (("first period", "1st period"), "1p"),
        (("first set", "1st set"), "1s"),
        (("regulation", "90 minutes"), "reg"),
    ):
        if any(label in value for label in labels):
            return period_id
    return "game"


def _prophetx_selection_side(
    market_type: str,
    selection_name: str,
    home_names: tuple[str, ...],
    away_names: tuple[str, ...],
) -> tuple[str | None, str]:
    normalized = _normalize_name(selection_name)
    if market_type in {"total", "totals", "over under"}:
        if normalized.startswith("over"):
            return "over", "all"
        if normalized.startswith("under"):
            return "under", "all"
        return None, "all"
    if normalized in {"draw", "tie"}:
        return "draw", "all"
    if _name_matches(_selection_name(selection_name), home_names):
        return "home", "home"
    if _name_matches(_selection_name(selection_name), away_names):
        return "away", "away"
    return None, ""


def _prophetx_settlement_rules(
    market_type: str,
    sport_id: str,
    period_id: str,
    stat_entity_id: str,
) -> tuple[str | None, str, str]:
    if market_type in {"moneyline", "money line", "sup moneyline"}:
        if sport_id == "SOCCER" and period_id in {"game", "reg"}:
            return "winner:regulation:three_way", "ml3way", "points"
        return f"winner:{period_id}:draw_push", "ml", "points"
    if market_type in {"spread", "handicap"}:
        return f"spread:{period_id}:team", "sp", "points"
    if market_type in {"total", "totals", "over under"}:
        return f"total:{period_id}:all", "ou", "points"
    return None, "", ""


def _decimal_to_american_odds(value: object) -> tuple[int | None, str]:
    decimal = _float_or_none(value)
    if decimal is None or decimal <= 1:
        return None, "Unavailable"
    american = round((decimal - 1) * 100) if decimal >= 2 else round(-100 / (decimal - 1))
    return american, f"{american:+d}"


def _default_prophetx_trade_url(base_url: str) -> str:
    return (
        PROPHETX_SANDBOX_TRADE_URL
        if "sandbox" in str(base_url).lower()
        else PROPHETX_PRODUCTION_TRADE_URL
    )


def _event_is_exact(
    trade: CanonicalTrade, market: NormalizedProviderMarket, *, allow_same_day: bool = False
) -> bool:
    if trade.sport_id != market.sport_id:
        return False
    if abs(trade.start_at - market.start_at) > EVENT_TIME_TOLERANCE:
        if not (allow_same_day and trade.start_at.astimezone(EASTERN).date() == market.start_at.astimezone(EASTERN).date()):
            return False
    if not _league_matches(trade.league_id, market.league_id, trade.sport_id):
        return False
    first, second = trade.participants
    return (
        _name_matches(first, market.home_names)
        and _name_matches(second, market.away_names)
    ) or (
        _name_matches(first, market.away_names)
        and _name_matches(second, market.home_names)
    )


def _match_exact_trade(
    trade: CanonicalTrade, index: ProviderMarketIndex, *, allow_same_day: bool = False
) -> tuple[MatchConfidence, NormalizedProviderMarket | None]:
    probable = False
    exact_matches: list[NormalizedProviderMarket] = []
    for market in index.candidates(trade, allow_same_day=allow_same_day):
        if not _event_is_exact(trade, market, allow_same_day=allow_same_day):
            continue
        probable = True
        if _market_is_exact(trade, market):
            exact_matches.append(market)
    if len(exact_matches) != 1:
        return (
            MatchConfidence.PROBABLE if probable else MatchConfidence.NO_MATCH,
            None,
        )
    return MatchConfidence.EXACT, exact_matches[0]


def _market_is_exact(
    trade: CanonicalTrade, market: NormalizedProviderMarket
) -> bool:
    if trade.market_kind in {"moneyline", "spread", "game_total", "team_total"}:
        if market.stat_id != "points":
            return False
    if trade.settlement_rules != market.settlement_rules:
        return False
    if trade.period_id != market.period_id:
        return False
    if trade.is_alternative != market.is_alternative:
        return False
    if trade.line is None:
        if market.line is not None:
            return False
    elif market.line is None or not math.isclose(trade.line, market.line, abs_tol=1e-9):
        return False

    expected_side = _provider_side_for_trade(trade, market)
    if expected_side is None:
        return False
    if trade.market_kind == "to_advance":
        return expected_side == market.stat_entity_id and market.side_id in {
            "yes",
            "side1",
        }
    return expected_side == market.side_id


def _provider_side_for_trade(
    trade: CanonicalTrade, market: NormalizedProviderMarket
) -> str | None:
    if trade.side_id in {"over", "under", "yes", "no", "draw"}:
        return trade.side_id
    selection = _selection_name(trade.outcome)
    if _name_matches(selection, market.home_names):
        return "home"
    if _name_matches(selection, market.away_names):
        return "away"
    return None


def _source_settlement_rules(
    market_kind: str, sport_id: str, period_id: str
) -> str | None:
    if market_kind == "to_advance":
        return "to_advance:event"
    if market_kind == "moneyline":
        if sport_id == "SOCCER":
            return "winner:regulation:three_way"
        return f"winner:{period_id}:draw_push"
    if market_kind == "spread":
        return f"spread:{period_id}:team"
    if market_kind == "game_total":
        return f"total:{period_id}:all"
    if market_kind == "team_total":
        return f"total:{period_id}:team"
    if market_kind == "yes_no":
        return f"yes_no:{period_id}"
    return None


def _provider_settlement_rules(
    bet_type_id: str,
    sport_id: str,
    period_id: str,
    stat_entity_id: str,
    market_name: str,
) -> str | None:
    normalized_name = _normalize_name(market_name)
    if bet_type_id in {"yn", "prop"} and (
        "to advance" in normalized_name or "qualify" in normalized_name
    ):
        return "to_advance:event"
    if bet_type_id == "ml3way" and sport_id == "SOCCER" and period_id == "reg":
        return "winner:regulation:three_way"
    if bet_type_id == "ml":
        return f"winner:{period_id}:draw_push"
    if bet_type_id == "sp":
        return f"spread:{period_id}:team"
    if bet_type_id == "ou":
        entity = "all" if stat_entity_id == "all" else "team"
        return f"total:{period_id}:{entity}"
    if bet_type_id == "yn":
        return f"yes_no:{period_id}"
    return None


def _canonical_market_kind(trade: dict) -> str | None:
    raw = _normalize_name(trade.get("sports_market_type"))
    title = _normalize_name(trade.get("market_title"))
    combined = f"{raw} {title}"
    if "to advance" in combined or "to qualify" in combined:
        return "to_advance"
    if "team total" in combined:
        return "team_total"
    if "spread" in raw or "handicap" in raw:
        return "spread"
    if raw in {"total", "game total", "over under", "overunder"}:
        return "game_total"
    if raw in {"moneyline", "money line", "match winner", "winner"}:
        return "moneyline"
    if raw in {"yes no", "yesno"}:
        return "yes_no"
    return None


def _canonical_period_id(trade: dict, sport_id: str, market_kind: str) -> str:
    blob = _normalize_name(
        " ".join(
            str(trade.get(key) or "")
            for key in ("sports_market_type", "market_title")
        )
    )
    periods = (
        (("first half", "1st half", "first 5 innings", "1st 5 innings"), "1h"),
        (("second half", "2nd half"), "2h"),
        (("first quarter", "1st quarter"), "1q"),
        (("second quarter", "2nd quarter"), "2q"),
        (("third quarter", "3rd quarter"), "3q"),
        (("fourth quarter", "4th quarter"), "4q"),
        (("first period", "1st period"), "1p"),
        (("second period", "2nd period"), "2p"),
        (("third period", "3rd period"), "3p"),
        (("first set", "1st set"), "1s"),
        (("second set", "2nd set"), "2s"),
        (("third set", "3rd set"), "3s"),
        (("regulation", "90 minutes"), "reg"),
    )
    for labels, period_id in periods:
        if any(label in blob for label in labels):
            return period_id
    if sport_id == "SOCCER" and market_kind == "moneyline":
        return "reg"
    return "game"


def _normalize_period_id(value: object) -> str:
    period_id = _normalize_identifier(value).lower()
    return "1h" if period_id == "1ix5" else period_id


def _source_side(trade: dict, market_kind: str, outcome: str) -> str | None:
    normalized = _normalize_name(outcome)
    if market_kind in {"game_total", "team_total"}:
        if normalized.startswith("over ") or normalized == "over":
            return "over"
        if normalized.startswith("under ") or normalized == "under":
            return "under"
        return None
    if market_kind == "yes_no":
        return normalized if normalized in {"yes", "no"} else None
    if market_kind == "to_advance":
        return "team"
    if market_kind in {"moneyline", "spread"}:
        return "team"
    return None


def _source_line(trade: dict, market_kind: str) -> float | None:
    if market_kind not in {"spread", "game_total", "team_total"}:
        return None
    direct = _float_or_none(trade.get("market_line"))
    if direct is not None:
        return direct
    texts = [str(trade.get("outcome") or ""), str(trade.get("market_title") or "")]
    if market_kind in {"game_total", "team_total"}:
        pattern = re.compile(r"\b(?:over|under|total)\s*([+-]?\d+(?:\.\d+)?)\b", re.I)
    else:
        pattern = re.compile(r"(?:^|\s)([+-]\d+(?:\.\d+)?)\b")
    for text in texts:
        match = pattern.search(text)
        if match:
            return _float_or_none(match.group(1))
    return None


def _provider_line(bet_type_id: str, snapshot: dict) -> float | None:
    if bet_type_id == "sp":
        return _float_or_none(snapshot.get("spread"))
    if bet_type_id == "ou":
        return _float_or_none(snapshot.get("overUnder"))
    return None


def _event_participants(value: object) -> tuple[str, str] | None:
    title = str(value or "").strip()
    segments = [segment.strip() for segment in title.split(":") if segment.strip()]
    for segment in reversed(segments or [title]):
        parts = re.split(r"\s+(?:vs?\.?|@)\s+", segment, maxsplit=1, flags=re.I)
        if len(parts) == 2 and all(_normalize_name(part) for part in parts):
            return parts[0].strip(), parts[1].strip()
    return None


def _provider_team_names(team: object) -> tuple[str, ...]:
    if not isinstance(team, dict):
        return ()
    names = team.get("names") or {}
    candidates = [
        names.get("long"),
        names.get("medium"),
        names.get("short"),
        team.get("name"),
        str(team.get("teamID") or "").replace("_", " "),
    ]
    return tuple(
        dict.fromkeys(
            normalized
            for value in candidates
            if (normalized := _normalize_name(value))
        )
    )


def _selection_name(value: str) -> str:
    selection = re.sub(r"\s+[+-]\d+(?:\.\d+)?\s*$", "", value).strip()
    selection = re.sub(
        r"\s+(?:moneyline|money line|to advance|to qualify|yes)$",
        "",
        selection,
        flags=re.I,
    ).strip()
    return selection


def _name_matches(value: object, aliases: Iterable[str]) -> bool:
    normalized = _canonical_team_name(value)
    return bool(normalized and normalized in {_canonical_team_name(alias) for alias in aliases})


MLB_TEAM_ALIASES = {
    "arizona diamondbacks": "ari", "diamondbacks": "ari", "arizona": "ari",
    "atlanta braves": "atl", "braves": "atl", "atlanta": "atl",
    "baltimore orioles": "bal", "orioles": "bal", "baltimore": "bal",
    "boston red sox": "bos", "red sox": "bos", "boston": "bos",
    "chicago cubs": "chc", "cubs": "chc", "chicago c": "chc",
    "chicago white sox": "chw", "white sox": "chw", "chicago w": "chw",
    "cincinnati reds": "cin", "reds": "cin", "cincinnati": "cin",
    "cleveland guardians": "cle", "guardians": "cle", "cleveland": "cle",
    "colorado rockies": "col", "rockies": "col", "colorado": "col",
    "detroit tigers": "det", "tigers": "det", "detroit": "det",
    "houston astros": "hou", "astros": "hou", "houston": "hou",
    "kansas city royals": "kc", "royals": "kc", "kansas city": "kc",
    "los angeles angels": "laa", "angels": "laa", "los angeles a": "laa",
    "los angeles dodgers": "lad", "dodgers": "lad", "los angeles d": "lad",
    "miami marlins": "mia", "marlins": "mia", "miami": "mia",
    "milwaukee brewers": "mil", "brewers": "mil", "milwaukee": "mil",
    "minnesota twins": "min", "twins": "min", "minnesota": "min",
    "new york mets": "nym", "mets": "nym", "new york m": "nym",
    "new york yankees": "nyy", "yankees": "nyy", "new york y": "nyy",
    "athletics": "ath", "oakland athletics": "ath", "a s": "ath",
    "philadelphia phillies": "phi", "phillies": "phi", "philadelphia": "phi",
    "pittsburgh pirates": "pit", "pirates": "pit", "pittsburgh": "pit",
    "san diego padres": "sd", "padres": "sd", "san diego": "sd",
    "san francisco giants": "sf", "giants": "sf", "san francisco": "sf",
    "seattle mariners": "sea", "mariners": "sea", "seattle": "sea",
    "st louis cardinals": "stl", "cardinals": "stl", "st louis": "stl",
    "tampa bay rays": "tb", "rays": "tb", "tampa bay": "tb",
    "texas rangers": "tex", "rangers": "tex", "texas": "tex",
    "toronto blue jays": "tor", "blue jays": "tor", "toronto": "tor",
    "washington nationals": "wsh", "nationals": "wsh", "washington": "wsh",
}


def _canonical_team_name(value: object) -> str:
    normalized = _normalize_name(value)
    return MLB_TEAM_ALIASES.get(normalized, normalized)


def probability_to_american(price: object) -> int | None:
    probability = _float_or_none(price)
    if probability is None or probability <= 0 or probability >= 1:
        return None
    return round(-100 * probability / (1 - probability)) if probability >= 0.5 else round(100 * (1 - probability) / probability)


def _league_matches(source: str, provider: str, sport_id: str) -> bool:
    if source == provider:
        return True
    source_key = source.replace("_", " ")
    provider_key = provider.replace("_", " ")
    if _normalize_name(source_key) == _normalize_name(provider_key):
        return True
    source_tokens = set(_normalize_name(source_key).split())
    provider_tokens = set(_normalize_name(provider_key).split())
    if {"world", "cup"} <= source_tokens and {"world", "cup"} <= provider_tokens:
        return True
    if sport_id == "TENNIS" and source in {"TENNIS", "ATP", "WTA", "ITF"}:
        return provider.startswith(("ATP", "WTA", "ITF", "UTR", "TENNIS"))
    return False


def _canonical_sport_id(value: object) -> str:
    normalized = _normalize_name(value)
    aliases = {
        "american football": "FOOTBALL",
        "football": "FOOTBALL",
        "nfl": "FOOTBALL",
        "college football": "FOOTBALL",
        "soccer": "SOCCER",
        "association football": "SOCCER",
        "baseball": "BASEBALL",
        "basketball": "BASKETBALL",
        "hockey": "HOCKEY",
        "ice hockey": "HOCKEY",
        "tennis": "TENNIS",
        "golf": "GOLF",
        "mma": "MMA",
        "mixed martial arts": "MMA",
        "boxing": "BOXING",
    }
    return aliases.get(normalized, _normalize_identifier(value))


def _normalize_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _normalize_identifier(value: object) -> str:
    return "_".join(_normalize_name(value).upper().split())


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        try:
            timestamp = float(text)
            if timestamp > 10_000_000_000:
                timestamp /= 1000.0
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _float_or_none(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _american_odds(value: object) -> tuple[int | None, str]:
    text = str(value or "").strip().upper()
    if text in {"EVEN", "EVENS"}:
        return 100, "+100"
    if not re.fullmatch(r"[+-]?\d+", text):
        return None, "Unavailable"
    parsed = int(text)
    if parsed == 0:
        return None, "Unavailable"
    return parsed, f"{parsed:+d}"


def _format_cents(value: float | None) -> str:
    if value is None or value <= 0 or value >= 1:
        return "Unavailable"
    cents = value * 100
    return f"{cents:.0f}\u00a2" if cents.is_integer() else f"{cents:.1f}\u00a2"


def _valid_deep_link(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if parsed.netloc.lower() in {"novig.us", "www.novig.us"} and parsed.path in {"", "/"}:
        return False
    return True


def _time_bucket(value: datetime) -> int:
    return int(value.timestamp() // (15 * 60))


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
