from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import urlparse, urlunparse
from zoneinfo import ZoneInfo

import requests

from execution_providers import (
    EASTERN,
    MARKET_NOT_FOUND,
    PROVIDER_NOT_CONFIGURED,
    RATE_LIMITED,
    CanonicalTrade,
    ExecutionOption,
    ExecutionProvider,
    MatchConfidence,
    NormalizedProviderMarket,
    ProviderHealthStatus,
    ProviderMarketIndex,
    _match_exact_trade,
    american_to_probability,
    canonicalize_trade,
)

LOGGER = logging.getLogger(__name__)

SPORT_KEY_BY_LEAGUE = {
    "MLB": "baseball_mlb",
    "NFL": "americanfootball_nfl",
    "NCAAF": "americanfootball_ncaaf",
    "NBA": "basketball_nba",
    "WNBA": "basketball_wnba",
    "NCAAB": "basketball_ncaab",
    "NHL": "icehockey_nhl",
    "MLS": "soccer_usa_mls",
    "EPL": "soccer_epl",
    "MMA": "mma_mixed_martial_arts",
}

LEAGUE_BY_SPORT_KEY = {value: key for key, value in SPORT_KEY_BY_LEAGUE.items()}

DEFAULT_KEYS_BY_SPORT = {
    "BASEBALL": ("baseball_mlb",),
    "FOOTBALL": ("americanfootball_nfl", "americanfootball_ncaaf"),
    "BASKETBALL": ("basketball_nba", "basketball_wnba", "basketball_ncaab"),
    "HOCKEY": ("icehockey_nhl",),
    "SOCCER": ("soccer_usa_mls", "soccer_epl"),
    "MMA": ("mma_mixed_martial_arts",),
}

MARKET_KEY_BY_KIND = {
    "moneyline": "h2h",
    "spread": "spreads",
    "game_total": "totals",
    "alternate_spread": "alternate_spreads",
    "alternate_total": "alternate_totals",
}

FEATURED_MARKET_KEYS = {"h2h", "spreads", "totals"}
ALTERNATE_MARKET_KEYS = {"alternate_spreads", "alternate_totals"}
SUPPORTED_MARKET_KEYS = FEATURED_MARKET_KEYS | ALTERNATE_MARKET_KEYS

SPORT_ID_BY_PREFIX = {
    "americanfootball": "FOOTBALL",
    "baseball": "BASEBALL",
    "basketball": "BASKETBALL",
    "icehockey": "HOCKEY",
    "soccer": "SOCCER",
    "mma": "MMA",
}

KNOWN_SPORTSBOOKS = {
    "ballybet": ("Bally Bet", "https://play.ballybet.com/favicon.ico"),
    "betanysports": ("BetAnything", ""),
    "betmgm": ("BetMGM", "https://sports.betmgm.com/favicon.ico"),
    "betonlineag": ("BetOnline.ag", "https://sports.betonline.ag/favicon.ico"),
    "betparx": ("betPARX", "https://www.betparx.com/favicon.ico"),
    "betrivers": ("BetRivers", "https://www.betrivers.com/favicon.ico"),
    "betus": ("BetUS", "https://www.betus.com.pa/favicon.ico"),
    "bovada": ("Bovada", "https://www.bovada.lv/favicon.ico"),
    "williamhill_us": (
        "Caesars",
        "https://sportsbook.caesars.com/favicon.ico",
    ),
    "draftkings": (
        "DraftKings",
        "https://sportsbook.draftkings.com/favicon.ico",
    ),
    "fanatics": (
        "Fanatics",
        "https://sportsbook.fanatics.com/favicon.ico",
    ),
    "fanduel": ("FanDuel", "https://sportsbook.fanduel.com/favicon.ico"),
    "fliff": ("Fliff", "https://sports.getfliff.com/favicon.ico"),
    "hardrockbet": ("Hard Rock Bet", "https://app.hardrock.bet/favicon.ico"),
    "hardrockbet_oh": (
        "Hard Rock Bet (OH)",
        "https://app.hardrock.bet/favicon.ico",
    ),
    "lowvig": ("LowVig.ag", "https://sports.lowvig.ag/favicon.ico"),
    "mybookieag": ("MyBookie.ag", "https://www.mybookie.ag/favicon.ico"),
    "rebet": ("ReBet", "https://rebet.app/favicon.ico"),
    "espnbet": ("theScore Bet", "https://sportsbook.thescore.bet/favicon.ico"),
}


@dataclass(frozen=True)
class _BookMetadata:
    key: str
    name: str
    logo_url: str
    direct_link: str | None
    bet_limit: float | None


@dataclass
class _OddsCacheEntry:
    loaded_at: float
    events: list[dict]


def _safe_float(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


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


def _bookmaker_key(value: object) -> str:
    return "".join(
        character if character.isalnum() else "_"
        for character in str(value or "").strip().lower()
    ).strip("_")


def _provider_key(bookmaker_key: str) -> str:
    return f"oddsapi__{_bookmaker_key(bookmaker_key)}"


def _first_link(*objects: object) -> str | None:
    for item in objects:
        if not isinstance(item, dict):
            continue
        for key in ("link", "event_link", "market_link", "betslip_link"):
            value = str(item.get(key) or "").strip()
            if value.startswith(("https://", "http://")):
                return value
        links = item.get("links")
        if isinstance(links, dict):
            for value in links.values():
                text = str(value or "").strip()
                if text.startswith(("https://", "http://")):
                    return text
    return None


def _favicon_url(link: str | None) -> str:
    if not link:
        return ""
    parsed = urlparse(link)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return urlunparse((parsed.scheme, parsed.netloc, "/favicon.ico", "", "", ""))


def _bet_limit(*objects: object) -> float | None:
    for item in objects:
        if not isinstance(item, dict):
            continue
        for key in ("bet_limit", "betLimit", "max_bet", "maxBet", "limit"):
            value = _safe_float(item.get(key))
            if value is not None:
                return value
    return None


def _american_odds(value: object) -> int | None:
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return parsed if parsed != 0 else None


def _sport_id(sport_key: str) -> str:
    prefix = str(sport_key or "").split("_", 1)[0].lower()
    return SPORT_ID_BY_PREFIX.get(prefix, prefix.upper())


def _period_id(sport_id: str, market_key: str) -> str:
    return "reg" if sport_id == "SOCCER" and market_key == "h2h" else "game"


def _featured_market_key(market_key: str) -> str:
    return {
        "alternate_spreads": "spreads",
        "alternate_totals": "totals",
    }.get(market_key, market_key)


def _settlement_rules(sport_id: str, market_key: str) -> str | None:
    market_key = _featured_market_key(market_key)
    period_id = _period_id(sport_id, market_key)
    if market_key == "h2h":
        if sport_id == "SOCCER":
            return "winner:regulation:three_way"
        return f"winner:{period_id}:draw_push"
    if market_key == "spreads":
        return f"spread:{period_id}:team"
    if market_key == "totals":
        return f"total:{period_id}:all"
    return None


def _side_for_outcome(
    market_key: str, outcome_name: str, home_team: str, away_team: str
) -> tuple[str | None, str]:
    market_key = _featured_market_key(market_key)
    normalized = outcome_name.strip().casefold()
    if market_key == "totals":
        if normalized in {"over", "under"}:
            return normalized, "all"
        return None, ""
    if normalized in {"draw", "tie"}:
        return "draw", "all"
    if normalized == home_team.strip().casefold():
        return "home", "home"
    if normalized == away_team.strip().casefold():
        return "away", "away"
    return None, ""


def normalize_the_odds_api_events(
    events: Iterable[dict],
) -> tuple[
    dict[str, list[NormalizedProviderMarket]],
    dict[str, _BookMetadata],
]:
    by_book: dict[str, list[NormalizedProviderMarket]] = {}
    metadata: dict[str, _BookMetadata] = {}
    for event in events:
        event_id = str(event.get("id") or "").strip()
        sport_key = str(event.get("sport_key") or "").strip()
        league_id = LEAGUE_BY_SPORT_KEY.get(
            sport_key, str(event.get("sport_title") or sport_key).strip().upper()
        )
        start_at = _parse_datetime(event.get("commence_time"))
        home_team = str(event.get("home_team") or "").strip()
        away_team = str(event.get("away_team") or "").strip()
        sport_id = _sport_id(sport_key)
        if not all((event_id, sport_key, league_id, start_at, home_team, away_team)):
            continue

        for bookmaker in event.get("bookmakers") or []:
            if not isinstance(bookmaker, dict):
                continue
            book_key = _bookmaker_key(bookmaker.get("key"))
            book_name = str(bookmaker.get("title") or book_key).strip()
            if not book_key or not book_name:
                continue
            book_rows = by_book.setdefault(book_key, [])
            for market in bookmaker.get("markets") or []:
                if not isinstance(market, dict):
                    continue
                market_key = str(market.get("key") or "").strip().lower()
                if market_key not in SUPPORTED_MARKET_KEYS:
                    continue
                featured_key = _featured_market_key(market_key)
                is_alternative = market_key in ALTERNATE_MARKET_KEYS
                settlement_rules = _settlement_rules(sport_id, market_key)
                if not settlement_rules:
                    continue
                last_updated = str(
                    market.get("last_update")
                    or bookmaker.get("last_update")
                    or ""
                ).strip() or None
                for position, outcome in enumerate(market.get("outcomes") or []):
                    if not isinstance(outcome, dict):
                        continue
                    outcome_name = str(outcome.get("name") or "").strip()
                    american = _american_odds(outcome.get("price"))
                    side_id, stat_entity_id = _side_for_outcome(
                        market_key, outcome_name, home_team, away_team
                    )
                    if not outcome_name or american is None or side_id is None:
                        continue
                    line = (
                        _safe_float(outcome.get("point"))
                        if featured_key in {"spreads", "totals"}
                        else None
                    )
                    if featured_key == "spreads":
                        try:
                            line = float(outcome.get("point"))
                        except (TypeError, ValueError):
                            continue
                    if featured_key == "totals" and line is None:
                        continue
                    direct_link = _first_link(outcome, market, bookmaker)
                    native_selection_id = str(
                        outcome.get("sid")
                        or outcome.get("id")
                        or f"{position}:{side_id}:{line}"
                    )
                    selection_id = (
                        f"{book_key}:{event_id}:{market_key}:"
                        f"{native_selection_id}"
                    )
                    limit = _bet_limit(outcome, market, bookmaker)
                    metadata[selection_id] = _BookMetadata(
                        key=book_key,
                        name=book_name,
                        logo_url=_favicon_url(direct_link),
                        direct_link=direct_link,
                        bet_limit=limit,
                    )
                    bet_type_id = {
                        "h2h": "ml3way" if sport_id == "SOCCER" else "ml",
                        "spreads": "sp",
                        "totals": "ou",
                    }[featured_key]
                    book_rows.append(
                        NormalizedProviderMarket(
                            event_id=event_id,
                            selection_id=selection_id,
                            sport_id=sport_id,
                            league_id=league_id,
                            start_at=start_at,
                            home_names=(home_team,),
                            away_names=(away_team,),
                            market_name={
                                "h2h": "moneyline",
                                "spreads": "spread",
                                "totals": "game_total",
                            }[featured_key],
                            stat_id="points",
                            stat_entity_id=stat_entity_id,
                            period_id=_period_id(sport_id, featured_key),
                            bet_type_id=bet_type_id,
                            side_id=side_id,
                            line=line,
                            is_alternative=is_alternative,
                            display_odds=f"{american:+d}",
                            american_odds=american,
                            deep_link=direct_link,
                            is_available=True,
                            last_updated=last_updated,
                            settlement_rules=settlement_rules,
                        )
                    )
    return by_book, metadata


class TheOddsAPIProvider(ExecutionProvider):
    provider_name = "The Odds API"
    provider_key = "the_odds_api"

    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str = "https://api.the-odds-api.com/v4",
        regions: Iterable[str] = ("us", "us2"),
        markets: Iterable[str] = ("h2h", "spreads", "totals"),
        default_sports: Iterable[str] = ("baseball_mlb",),
        cache_ttl_seconds: int = 300,
        alternate_cache_ttl_seconds: int = 600,
        max_quote_age_seconds: int = 180,
        request_timeout: int = 15,
        session: requests.Session | None = None,
    ) -> None:
        self.api_key = str(api_key or "").strip() or None
        self.base_url = str(base_url).rstrip("/")
        self.regions = tuple(dict.fromkeys(str(item).strip() for item in regions if str(item).strip()))
        self.markets = tuple(
            item
            for item in dict.fromkeys(
                str(value).strip().lower() for value in markets if str(value).strip()
            )
            if item in FEATURED_MARKET_KEYS
        )
        self.alternate_markets = ("alternate_spreads", "alternate_totals")
        self.default_sports = tuple(
            dict.fromkeys(
                str(item).strip() for item in default_sports if str(item).strip()
            )
        )
        self.cache_ttl_seconds = max(60, int(cache_ttl_seconds))
        self.alternate_cache_ttl_seconds = max(
            self.cache_ttl_seconds, int(alternate_cache_ttl_seconds)
        )
        self.max_quote_age_seconds = max(60, int(max_quote_age_seconds))
        self.request_timeout = max(1, int(request_timeout))
        self.session = session or requests.Session()
        self.failure_reasons: dict[str, str] = {}
        self._cache: dict[tuple[str, tuple[str, ...]], _OddsCacheEntry] = {}
        self._lock = threading.RLock()
        self._quota = {
            "remaining": None,
            "used": None,
            "last": None,
            "last_request_at": None,
        }

    def options_for_trades(
        self, trades: list[dict]
    ) -> dict[str, list[ExecutionOption]]:
        self.failure_reasons = {}
        if not self.api_key or not trades:
            reason = PROVIDER_NOT_CONFIGURED if not self.api_key else MARKET_NOT_FOUND
            self.failure_reasons = {
                str(trade.get("id") or ""): reason
                for trade in trades
                if trade.get("id")
            }
            return {}

        canonical = [
            item for trade in trades if (item := canonicalize_trade(trade))
        ]
        grouped: dict[str, list[CanonicalTrade]] = {}
        for trade in canonical:
            sport_key = self._sport_key_for_trade(trade)
            if sport_key:
                grouped.setdefault(sport_key, []).append(trade)
            else:
                self.failure_reasons[trade.trade_id] = MARKET_NOT_FOUND

        results: dict[str, list[ExecutionOption]] = {}
        for sport_key, sport_trades in grouped.items():
            requested_keys = {
                self._market_key_for_trade(trade) for trade in sport_trades
            }
            market_keys = tuple(
                key
                for key in (*self.markets, *self.alternate_markets)
                if key in requested_keys
            )
            if not market_keys:
                continue
            events = self._events(sport_key, market_keys)
            by_book, metadata = normalize_the_odds_api_events(events)
            for book_key, markets in by_book.items():
                index = ProviderMarketIndex(markets)
                for trade in sport_trades:
                    confidence, matched = _match_exact_trade(trade, index)
                    if confidence is not MatchConfidence.EXACT or matched is None:
                        continue
                    meta = metadata[matched.selection_id]
                    stake = self._recommended_stake(
                        next(
                            row
                            for row in trades
                            if str(row.get("id") or "") == trade.trade_id
                        )
                    )
                    can_fill = (
                        True
                        if meta.bet_limit is None
                        else meta.bet_limit + 1e-9 >= stake
                    )
                    results.setdefault(trade.trade_id, []).append(
                        ExecutionOption(
                            provider_name=meta.name,
                            provider_key=_provider_key(book_key),
                            market_id=f"{matched.event_id}:{matched.market_name}:{matched.line}",
                            selection_id=matched.selection_id,
                            display_odds=matched.display_odds,
                            deep_link=meta.direct_link,
                            is_available=matched.is_available,
                            last_updated=matched.last_updated,
                            matching_confidence=MatchConfidence.EXACT,
                            logo_url=meta.logo_url,
                            tooltip=f"{meta.name} sportsbook quote via The Odds API",
                            american_odds=matched.american_odds,
                            available_liquidity=meta.bet_limit,
                            can_fill_recommended_stake=can_fill,
                            fee_rate=0.0,
                            quote_status="OPEN",
                            provider_event_id=matched.event_id,
                            native_price_format="AMERICAN",
                            quote_max_age_seconds=self.max_quote_age_seconds,
                        )
                    )
        for trade in canonical:
            if trade.trade_id not in results:
                self.failure_reasons.setdefault(trade.trade_id, MARKET_NOT_FOUND)
        return results

    def odds_screen_rows(
        self,
        *,
        sport: str = "",
        league: str = "",
        market_kind: str = "",
        now: datetime | None = None,
    ) -> list[dict]:
        if not self.api_key:
            return []
        sport_keys = self._screen_sport_keys(sport=sport, league=league)
        market_keys = self._screen_market_keys(market_kind)
        if not market_keys:
            return []
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        allowed_days = {
            current.astimezone(EASTERN).date(),
            (current + timedelta(days=1)).astimezone(EASTERN).date(),
        }
        unique: dict[tuple, dict] = {}
        for sport_key in sport_keys:
            events = self._events(sport_key, market_keys)
            by_book, _metadata = normalize_the_odds_api_events(events)
            for market in (
                item for rows in by_book.values() for item in rows
            ):
                if market.start_at.astimezone(EASTERN).date() not in allowed_days:
                    continue
                group_line = (
                    abs(float(market.line))
                    if market.market_name == "spread" and market.line is not None
                    else market.line
                )
                identity = (
                    market.event_id,
                    market.market_name,
                    market.is_alternative,
                    group_line,
                    market.side_id,
                    market.line,
                )
                if identity in unique:
                    continue
                outcome = {
                    "home": market.home_names[0],
                    "away": market.away_names[0],
                    "over": "Over",
                    "under": "Under",
                    "draw": "Draw",
                }.get(market.side_id, market.side_id)
                implied = american_to_probability(market.american_odds)
                market_title = {
                    "moneyline": "Moneyline",
                    "spread": (
                        "Alternate Spread"
                        if market.is_alternative
                        else "Spread"
                    ),
                    "game_total": (
                        "Alternate Total"
                        if market.is_alternative
                        else "Game Total"
                    ),
                }[market.market_name]
                market_variant = (
                    f"alternate_{market.market_name}"
                    if market.is_alternative
                    else market.market_name
                )
                unique[identity] = {
                    "id": (
                        f"oddsapi::{market.event_id}::{market_variant}::"
                        f"{market.side_id}::{market.line}"
                    ),
                    "event_id": market.event_id,
                    "market_id": (
                        f"oddsapi::{market.event_id}::{market_variant}::"
                        f"{group_line}"
                    ),
                    "event_title": (
                        f"{market.away_names[0]} vs {market.home_names[0]}"
                    ),
                    "market_title": market_title,
                    "sports_market_type": market_title,
                    "outcome": outcome,
                    "category": market.sport_id.title(),
                    "canonical_sport_id": market.sport_id,
                    "league": market.league_id,
                    "canonical_league_id": market.league_id,
                    "resolution_time": market.start_at.isoformat(),
                    "event_date_et": market.start_at.isoformat(),
                    "schedule_date_et": market.start_at.astimezone(EASTERN)
                    .date()
                    .isoformat(),
                    "market_line": market.line,
                    "is_alternative": market.is_alternative,
                    "is_sports": True,
                    "card": {
                        "current_actionable_price": implied,
                        "recommended_amount": 0,
                    },
                    "recommendation": {
                        "current_user_entry_price": implied,
                        "recommended_amount": 0,
                    },
                    "odds_api_event": True,
                }
        return sorted(
            unique.values(),
            key=lambda row: (
                str(row.get("resolution_time") or ""),
                str(row.get("market_id") or ""),
                str(row.get("outcome") or ""),
            ),
        )

    def provider_catalog(self, trades: list[dict]) -> list[dict]:
        catalog: dict[str, dict] = {
            _provider_key(book_key): {
                "key": _provider_key(book_key),
                "name": name,
                "logoUrl": logo_url,
                "source": self.provider_key,
            }
            for book_key, (name, logo_url) in KNOWN_SPORTSBOOKS.items()
        }
        for trade in trades:
            for option in trade.get("executionOptions") or []:
                provider_key = str(option.get("providerKey") or "")
                if not provider_key.startswith("oddsapi__"):
                    continue
                catalog[provider_key] = {
                    "key": provider_key,
                    "name": str(option.get("providerName") or provider_key),
                    "logoUrl": str(option.get("logoUrl") or ""),
                    "source": self.provider_key,
                }
        return sorted(catalog.values(), key=lambda item: item["name"].casefold())

    def health_status(
        self, *, authenticate: bool = False
    ) -> ProviderHealthStatus:
        if not self.api_key:
            return ProviderHealthStatus.UNAUTHORIZED
        if not authenticate:
            return ProviderHealthStatus.CONFIGURED
        try:
            response = self.session.get(
                f"{self.base_url}/sports/",
                params={"apiKey": self.api_key},
                timeout=self.request_timeout,
            )
            self._capture_quota(response)
            response.raise_for_status()
            return ProviderHealthStatus.AUTHENTICATED
        except requests.RequestException:
            return ProviderHealthStatus.CONNECTION_FAILED

    def diagnostics(self, *, authenticate: bool = False) -> dict:
        status = self.health_status(authenticate=authenticate)
        with self._lock:
            quota = dict(self._quota)
            cache_entries = len(self._cache)
        return {
            "provider": self.provider_key,
            "status": status.value,
            "configured": bool(self.api_key),
            "read_only": True,
            "regions": list(self.regions),
            "markets": list(self.markets),
            "alternate_markets": list(self.alternate_markets),
            "default_sports": list(self.default_sports),
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "alternate_cache_ttl_seconds": self.alternate_cache_ttl_seconds,
            "cache_entries": cache_entries,
            "quota": quota,
            "credentials_exposed": False,
        }

    def _events(
        self, sport_key: str, market_keys: tuple[str, ...]
    ) -> list[dict]:
        cache_key = (sport_key, tuple(market_keys))
        now = time.monotonic()
        ttl = (
            self.alternate_cache_ttl_seconds
            if any(key in ALTERNATE_MARKET_KEYS for key in market_keys)
            else self.cache_ttl_seconds
        )
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and now - cached.loaded_at < ttl:
                return cached.events
        featured_keys = tuple(
            key for key in market_keys if key in FEATURED_MARKET_KEYS
        )
        alternate_keys = tuple(
            key for key in market_keys if key in ALTERNATE_MARKET_KEYS
        )
        events: list[dict] = []
        if featured_keys:
            events.extend(self._featured_events(sport_key, featured_keys))
        if alternate_keys:
            events.extend(self._alternate_events(sport_key, alternate_keys))
        with self._lock:
            self._cache[cache_key] = _OddsCacheEntry(
                loaded_at=now, events=events
            )
        return events

    def _featured_events(
        self, sport_key: str, market_keys: tuple[str, ...]
    ) -> list[dict]:
        response = self.session.get(
            f"{self.base_url}/sports/{sport_key}/odds/",
            params={
                "apiKey": self.api_key,
                "regions": ",".join(self.regions),
                "markets": ",".join(market_keys),
                "oddsFormat": "american",
                "dateFormat": "iso",
                "includeLinks": "true",
                "includeSids": "true",
                "includeBetLimits": "true",
            },
            timeout=self.request_timeout,
        )
        self._capture_quota(response)
        if response.status_code == 429:
            error = requests.HTTPError(RATE_LIMITED, response=response)
            raise error
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("The Odds API response must be a list")
        return [item for item in payload if isinstance(item, dict)]

    def _alternate_events(
        self, sport_key: str, market_keys: tuple[str, ...]
    ) -> list[dict]:
        schedule = self.session.get(
            f"{self.base_url}/sports/{sport_key}/events",
            params={
                "apiKey": self.api_key,
                "dateFormat": "iso",
            },
            timeout=self.request_timeout,
        )
        self._capture_quota(schedule)
        if schedule.status_code == 429:
            raise requests.HTTPError(RATE_LIMITED, response=schedule)
        schedule.raise_for_status()
        payload = schedule.json()
        if not isinstance(payload, list):
            raise ValueError("The Odds API events response must be a list")
        now = datetime.now(timezone.utc)
        allowed_days = {
            now.astimezone(EASTERN).date(),
            (now + timedelta(days=1)).astimezone(EASTERN).date(),
        }
        events = [
            item
            for item in payload
            if isinstance(item, dict)
            and item.get("id")
            and (start := _parse_datetime(item.get("commence_time")))
            and start.astimezone(EASTERN).date() in allowed_days
        ][:40]
        if not events:
            LOGGER.info(
                (
                    "The Odds API alternate refresh sport=%s markets=%s "
                    "eligible_events=0 returned_events=0 bookmakers=0 "
                    "market_groups=0"
                ),
                sport_key,
                ",".join(market_keys),
            )
            return []

        def fetch_event(event: dict) -> dict | None:
            response = self.session.get(
                (
                    f"{self.base_url}/sports/{sport_key}/events/"
                    f"{event['id']}/odds"
                ),
                params={
                    "apiKey": self.api_key,
                    "regions": ",".join(self.regions),
                    "markets": ",".join(market_keys),
                    "oddsFormat": "american",
                    "dateFormat": "iso",
                    "includeLinks": "true",
                    "includeSids": "true",
                    "includeBetLimits": "true",
                },
                timeout=self.request_timeout,
            )
            self._capture_quota(response)
            if response.status_code == 429:
                raise requests.HTTPError(RATE_LIMITED, response=response)
            response.raise_for_status()
            item = response.json()
            if not isinstance(item, dict):
                return None
            filtered = dict(item)
            filtered["bookmakers"] = [
                {
                    **bookmaker,
                    "markets": [
                        market
                        for market in bookmaker.get("markets") or []
                        if isinstance(market, dict)
                        and str(market.get("key") or "").lower()
                        in market_keys
                    ],
                }
                for bookmaker in item.get("bookmakers") or []
                if isinstance(bookmaker, dict)
            ]
            return filtered

        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=min(6, len(events))) as executor:
            futures = {
                executor.submit(fetch_event, event): str(event["id"])
                for event in events
            }
            for future in as_completed(futures):
                item = future.result()
                if item is not None:
                    results.append(item)
        LOGGER.info(
            (
                "The Odds API alternate refresh sport=%s markets=%s "
                "eligible_events=%d returned_events=%d bookmakers=%d "
                "market_groups=%d"
            ),
            sport_key,
            ",".join(market_keys),
            len(events),
            len(results),
            sum(
                len(item.get("bookmakers") or [])
                for item in results
            ),
            sum(
                len(bookmaker.get("markets") or [])
                for item in results
                for bookmaker in item.get("bookmakers") or []
                if isinstance(bookmaker, dict)
            ),
        )
        return results

    def _capture_quota(self, response: requests.Response) -> None:
        with self._lock:
            self._quota = {
                "remaining": response.headers.get("x-requests-remaining"),
                "used": response.headers.get("x-requests-used"),
                "last": response.headers.get("x-requests-last"),
                "last_request_at": datetime.now(timezone.utc).isoformat(),
            }

    def _sport_key_for_trade(self, trade: CanonicalTrade) -> str | None:
        league = str(trade.league_id or "").upper().replace("-", "_")
        if league in SPORT_KEY_BY_LEAGUE:
            return SPORT_KEY_BY_LEAGUE[league]
        candidates = DEFAULT_KEYS_BY_SPORT.get(trade.sport_id, ())
        return candidates[0] if len(candidates) == 1 else None

    def _screen_sport_keys(
        self, *, sport: str, league: str
    ) -> tuple[str, ...]:
        normalized_league = str(league or "").strip().upper()
        if normalized_league in SPORT_KEY_BY_LEAGUE:
            return (SPORT_KEY_BY_LEAGUE[normalized_league],)
        normalized_sport = str(sport or "").strip().upper()
        if normalized_sport in DEFAULT_KEYS_BY_SPORT:
            return DEFAULT_KEYS_BY_SPORT[normalized_sport]
        return self.default_sports

    def _screen_market_keys(self, market_kind: str) -> tuple[str, ...]:
        normalized = str(market_kind or "").strip()
        if normalized and normalized not in MARKET_KEY_BY_KIND:
            return ()
        requested = MARKET_KEY_BY_KIND.get(normalized)
        return (requested,) if requested else self.markets

    @staticmethod
    def _market_key_for_trade(trade: CanonicalTrade) -> str | None:
        if trade.market_kind == "spread":
            return (
                "alternate_spreads" if trade.is_alternative else "spreads"
            )
        if trade.market_kind == "game_total":
            return (
                "alternate_totals" if trade.is_alternative else "totals"
            )
        return MARKET_KEY_BY_KIND.get(trade.market_kind)

    @staticmethod
    def _recommended_stake(trade: dict) -> float:
        for source in (
            trade.get("card") or {},
            trade.get("recommendation") or {},
        ):
            value = _safe_float(source.get("recommended_amount"))
            if value is not None:
                return value
        return 0.0
