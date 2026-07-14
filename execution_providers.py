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
from urllib.parse import urlparse

import requests

LOGGER = logging.getLogger(__name__)

POLYMARKET_LOGO_URL = "https://polymarket.com/icons/favicon-32x32.png"
NOVIG_LOGO_URL = (
    "https://cdn.prod.website-files.com/642ae772b9f3360398a9d449/"
    "6436d7c4d343f31dbf62d683_favicon.png"
)
NOVIG_BOOKMAKER_ID = "novig"
PROPHETX_PRODUCTION_BASE_URL = "https://cash.api.prophetx.co/partner"
EVENT_TIME_TOLERANCE = timedelta(minutes=10)
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
        }


class ExecutionProvider(ABC):
    provider_name: str
    provider_key: str

    @abstractmethod
    def options_for_trades(self, trades: list[dict]) -> dict[str, ExecutionOption]:
        raise NotImplementedError


class PolymarketProvider(ExecutionProvider):
    provider_name = "Polymarket"
    provider_key = "polymarket"

    def options_for_trades(self, trades: list[dict]) -> dict[str, ExecutionOption]:
        options: dict[str, ExecutionOption] = {}
        for trade in trades:
            trade_id = str(trade.get("id") or "").strip()
            deep_link = str(trade.get("market_url") or "").strip()
            if not trade_id or not _valid_deep_link(deep_link):
                continue
            recommendation = trade.get("recommendation") or {}
            card = trade.get("card") or {}
            current_price = _float_or_none(
                card.get("current_actionable_price")
                if card.get("current_actionable_price") is not None
                else recommendation.get("current_user_entry_price")
            )
            display_odds = _format_cents(current_price)
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
                last_updated=(trade.get("orderbook_summary") or {}).get("timestamp"),
                matching_confidence=MatchConfidence.EXACT,
                logo_url=POLYMARKET_LOGO_URL,
                tooltip="Polymarket Current Best Price",
            )
        return options


class ProphetXProvider(ExecutionProvider):
    provider_name = "ProphetX"
    provider_key = "prophetx"

    def __init__(
        self,
        access_key: str | None,
        secret_key: str | None,
        *,
        base_url: str = PROPHETX_PRODUCTION_BASE_URL,
        request_timeout: int = 15,
        session: requests.Session | None = None,
    ) -> None:
        self._access_key = str(access_key or "").strip() or None
        self._secret_key = str(secret_key or "").strip() or None
        self.base_url = base_url.rstrip("/")
        self.request_timeout = max(int(request_timeout), 1)
        self.session = session or requests.Session()
        self._health_status = (
            ProviderHealthStatus.CONFIGURED
            if self._access_key and self._secret_key
            else ProviderHealthStatus.CONNECTION_FAILED
        )
        self._health_lock = threading.RLock()

    def __repr__(self) -> str:
        configured = bool(self._access_key and self._secret_key)
        return f"<ProphetXProvider configured={configured}>"

    def options_for_trades(self, trades: list[dict]) -> dict[str, ExecutionOption]:
        # Market normalization is intentionally deferred until exact settlement
        # matching is implemented for ProphetX.
        return {}

    def health_status(self, *, authenticate: bool = False) -> ProviderHealthStatus:
        if not self._access_key or not self._secret_key:
            return ProviderHealthStatus.CONNECTION_FAILED
        if not authenticate:
            return self._health_status

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
        self._by_sport_and_time: dict[
            tuple[str, int], list[NormalizedProviderMarket]
        ] = defaultdict(list)
        for market in markets:
            self._by_sport_and_time[
                (market.sport_id, _time_bucket(market.start_at))
            ].append(market)

    def candidates(self, trade: CanonicalTrade) -> list[NormalizedProviderMarket]:
        bucket = _time_bucket(trade.start_at)
        candidates: list[NormalizedProviderMarket] = []
        for offset in (-1, 0, 1):
            candidates.extend(
                self._by_sport_and_time.get((trade.sport_id, bucket + offset), [])
            )
        return candidates


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

    def match_trade(
        self, trade: CanonicalTrade, index: ProviderMarketIndex
    ) -> tuple[MatchConfidence, NormalizedProviderMarket | None]:
        probable = False
        exact_matches: list[NormalizedProviderMarket] = []
        for market in index.candidates(trade):
            if not _event_is_exact(trade, market):
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
    def __init__(self, providers: Iterable[ExecutionProvider]) -> None:
        self.providers = tuple(providers)

    def attach_options(self, trades: list[dict]) -> list[dict]:
        by_provider: list[dict[str, ExecutionOption]] = []
        for provider in self.providers:
            try:
                by_provider.append(provider.options_for_trades(trades))
            except Exception:
                LOGGER.exception("Execution provider %s failed", provider.provider_key)
                by_provider.append({})

        for trade in trades:
            trade_id = str(trade.get("id") or "")
            trade["executionOptions"] = [
                option.to_dict()
                for options in by_provider
                if (option := options.get(trade_id)) is not None
                and option.matching_confidence is MatchConfidence.EXACT
            ]
        return trades

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


def build_execution_provider_registry(settings) -> ExecutionProviderRegistry:
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
                    PROPHETX_PRODUCTION_BASE_URL,
                ),
                request_timeout=getattr(settings, "request_timeout", 15),
            ),
        )
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


def _event_is_exact(
    trade: CanonicalTrade, market: NormalizedProviderMarket
) -> bool:
    if trade.sport_id != market.sport_id:
        return False
    if abs(trade.start_at - market.start_at) > EVENT_TIME_TOLERANCE:
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
    normalized = _normalize_name(value)
    return bool(normalized and normalized in set(aliases))


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
