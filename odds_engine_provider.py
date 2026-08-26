from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import requests

from execution_providers import ExecutionProvider, ProviderHealthStatus
from sports_game_odds import SPORTS_GAME_ODDS_BOOKMAKERS


LOGGER = logging.getLogger(__name__)
DEFAULT_BASE_URL = "https://api.oddsengine.dev/v1"

SPORT_KEY_TO_LEAGUE = {
    "americanfootball_ncaaf": "ncaaf",
    "americanfootball_nfl": "nfl",
    "baseball_mlb": "mlb",
    "basketball_nba": "nba",
    "basketball_ncaab": "ncaab",
    "basketball_ncaaw": "ncaaw",
    "basketball_wnba": "wnba",
    "icehockey_nhl": "nhl",
}

BOOK_ALIASES = {
    "betr": "betrsportsbook",
    "hardrock": "hardrockbet",
    "prophetx": "prophetexchange",
    "sportsbettingag": "sportsbetting_ag",
    "thescore": "thescorebet",
}

SUPPORTED_MARKET_KEYS = {
    "h2h",
    "spreads",
    "totals",
    "alternate_spreads",
    "alternate_totals",
    "batter_hits",
    "batter_total_bases",
    "batter_home_runs",
    "batter_first_home_run",
    "batter_rbis",
    "batter_runs_scored",
    "batter_hits_runs_rbis",
    "batter_runs_rbis",
    "batter_singles",
    "batter_doubles",
    "batter_triples",
    "batter_walks",
    "batter_strikeouts",
    "batter_stolen_bases",
    "pitcher_strikeouts",
    "pitcher_hits_allowed",
    "pitcher_walks",
    "pitcher_earned_runs",
    "pitcher_outs",
    "pitcher_pitches_thrown",
    "pitcher_record_a_win",
    "player_points",
    "player_points_q1",
    "player_rebounds",
    "player_rebounds_q1",
    "player_assists",
    "player_assists_q1",
    "player_threes",
    "player_blocks",
    "player_steals",
    "player_blocks_steals",
    "player_turnovers",
    "player_points_rebounds_assists",
    "player_points_rebounds",
    "player_points_assists",
    "player_rebounds_assists",
    "player_field_goals",
    "player_field_goals_attempted",
    "player_frees_made",
    "player_frees_attempts",
    "player_first_basket",
    "player_double_double",
    "player_triple_double",
}

MARKET_ALIASES = {
    "ml": "h2h",
    "money_line": "h2h",
    "moneyline": "h2h",
    "point_spread": "spreads",
    "spread": "spreads",
    "game_total": "totals",
    "total": "totals",
    "player_three_pointers": "player_threes",
    "player_three_pointers_made": "player_threes",
    "player_3_pointers": "player_threes",
    "player_free_throws_made": "player_frees_made",
    "player_free_throws_attempted": "player_frees_attempts",
    "pitcher_walks_allowed": "pitcher_walks",
    "pitcher_outs_recorded": "pitcher_outs",
    "pitcher_to_record_a_win": "pitcher_record_a_win",
}


@dataclass
class _TimedValue:
    loaded_at: float
    value: object


def _slug(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")


def _parse_time(value: object) -> datetime | None:
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


def _sport_key_league(sport_key: str) -> str:
    normalized = str(sport_key or "").strip().lower()
    if normalized in SPORT_KEY_TO_LEAGUE:
        return SPORT_KEY_TO_LEAGUE[normalized]
    return normalized.rsplit("_", 1)[-1]


def _book_key(value: object) -> str | None:
    normalized = _slug(value).replace("_", "")
    normalized = BOOK_ALIASES.get(normalized, normalized)
    return normalized if normalized in SPORTS_GAME_ODDS_BOOKMAKERS else None


def _canonical_market_key(offer: dict, selections: list[dict]) -> str | None:
    candidates = (
        _slug(offer.get("market_key")),
        _slug(offer.get("market")),
    )
    market_key = None
    for candidate in candidates:
        if not candidate:
            continue
        if candidate in SUPPORTED_MARKET_KEYS:
            market_key = candidate
            break
        direct = MARKET_ALIASES.get(candidate)
        if direct:
            market_key = direct
            break
        suffix = next(
            (
                supported
                for supported in sorted(SUPPORTED_MARKET_KEYS, key=len, reverse=True)
                if candidate.endswith(supported)
            ),
            None,
        )
        if suffix:
            market_key = suffix
            break
        if "moneyline" in candidate or candidate.endswith("_money_line"):
            market_key = "h2h"
            break
        if "spread" in candidate:
            market_key = "spreads"
            break
        if candidate in {"over_under", "game_over_under"} or (
            "total" in candidate and not candidate.startswith(("player_", "batter_", "pitcher_"))
        ):
            market_key = "totals"
            break

    alternate_line = any(bool(selection.get("is_alt")) for selection in selections)
    alternate_line = alternate_line or any(
        "alternate" in candidate or candidate.startswith("alt_")
        for candidate in candidates
    )
    if market_key in {"spreads", "totals"} and alternate_line:
        return f"alternate_{market_key}"
    return market_key


def _american_odds(value: object) -> int | None:
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return parsed if parsed != 0 else None


def _selection_outcome(
    selection: dict,
    *,
    event: dict,
    offer: dict,
    market_key: str,
) -> dict | None:
    price = _american_odds(selection.get("odds_american"))
    if price is None:
        return None

    side = str(selection.get("side") or "").strip().lower()
    entity = " ".join(
        str(selection.get("entity_name") or offer.get("entity_name") or "").split()
    )
    if side in {"over", "under"}:
        name = side.title()
    elif side == "home":
        name = entity or str(event.get("home_team") or "Home")
    elif side == "away":
        name = entity or str(event.get("away_team") or "Away")
    else:
        name = entity or side.title()
    if not name:
        return None

    line = selection.get("line")
    if line is None:
        line = offer.get("line")
    outcome = {
        "name": name,
        "price": price,
        "sid": str(selection.get("selection_id") or ""),
        "id": str(selection.get("selection_id") or ""),
        "link": str(selection.get("bet_link") or ""),
    }
    if market_key != "h2h" and line is not None:
        try:
            outcome["point"] = float(line)
        except (TypeError, ValueError):
            pass
    if market_key.startswith(("player_", "batter_", "pitcher_")) and entity:
        outcome["description"] = entity
    if selection.get("liquidity") is not None:
        outcome["liquidity"] = selection.get("liquidity")
    if selection.get("limit") is not None:
        outcome["bet_limit"] = selection.get("limit")
    return outcome


def normalize_odds_engine_event(
    payload: dict,
    *,
    sport_key: str,
    requested_markets: Iterable[str],
    received_at: datetime | None = None,
) -> dict | None:
    """Convert one documented OddsEngine odds response to IconLabs' feed shape."""
    event_id = str(payload.get("event_id") or "").strip()
    commence_time = str(payload.get("event_start") or "").strip()
    if not event_id or not commence_time:
        return None
    allowed = {
        str(value).strip().lower() for value in requested_markets if str(value).strip()
    }
    observed_at = (received_at or datetime.now(timezone.utc)).isoformat()
    bookmakers: dict[str, dict] = {}

    for category in payload.get("market_categories") or []:
        if not isinstance(category, dict):
            continue
        for offer in category.get("offers") or []:
            if not isinstance(offer, dict):
                continue
            for raw_book in offer.get("books") or []:
                if not isinstance(raw_book, dict):
                    continue
                selections = [
                    selection
                    for selection in raw_book.get("selections") or []
                    if isinstance(selection, dict)
                ]
                market_key = _canonical_market_key(offer, selections)
                if not market_key or (allowed and market_key not in allowed):
                    continue
                book_key = _book_key(raw_book.get("book"))
                if not book_key:
                    continue
                outcomes = [
                    outcome
                    for selection in selections
                    if (
                        outcome := _selection_outcome(
                            selection,
                            event=payload,
                            offer=offer,
                            market_key=market_key,
                        )
                    )
                ]
                if not outcomes:
                    continue
                last_update = max(
                    (
                        str(
                            selection.get("odds_changed_at")
                            or selection.get("last_fetched")
                            or observed_at
                        )
                        for selection in selections
                    ),
                    default=observed_at,
                )
                book = bookmakers.setdefault(
                    book_key,
                    {
                        "key": book_key,
                        "title": SPORTS_GAME_ODDS_BOOKMAKERS[book_key]["name"],
                        "last_update": last_update,
                        "markets": [],
                    },
                )
                book["last_update"] = max(str(book["last_update"]), last_update)
                book["markets"].append(
                    {
                        "id": (
                            f"oddsengine::{event_id}::"
                            f"{offer.get('market_id') or _slug(offer.get('market'))}::"
                            f"{offer.get('line')}"
                        ),
                        "key": market_key,
                        "last_update": last_update,
                        "outcomes": outcomes,
                    }
                )

    if not bookmakers:
        return None
    return {
        "id": event_id,
        "sport_key": sport_key,
        "sport_title": str(payload.get("league") or _sport_key_league(sport_key)).upper(),
        "commence_time": commence_time,
        "home_team": payload.get("home_team"),
        "away_team": payload.get("away_team"),
        "bookmakers": sorted(bookmakers.values(), key=lambda item: item["key"]),
    }


class OddsEngineProvider(ExecutionProvider):
    provider_name = "OddsEngine"
    provider_key = "odds_engine"

    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        cache_ttl_seconds: int = 45,
        max_events_per_league: int = 12,
        max_total_events: int = 48,
        request_timeout: int = 15,
        session: requests.Session | None = None,
    ) -> None:
        self.api_key = str(api_key or "").strip() or None
        normalized_base = str(base_url or DEFAULT_BASE_URL).rstrip("/")
        self.base_url = (
            normalized_base if normalized_base.endswith("/v1") else f"{normalized_base}/v1"
        )
        self.cache_ttl_seconds = max(15, int(cache_ttl_seconds))
        self.max_events_per_league = max(1, min(50, int(max_events_per_league)))
        self.max_total_events = max(1, min(100, int(max_total_events)))
        self.request_timeout = max(1, int(request_timeout))
        self.session = session or requests.Session()
        self._league_cache: dict[str, _TimedValue] = {}
        self._odds_cache: dict[str, _TimedValue] = {}
        self._quota: dict[str, str] = {}
        self._requests = 0
        self._last_success_at: str | None = None
        self._last_error_at: str | None = None
        self._lock = threading.RLock()
        self._scan_lock = threading.Lock()

    def options_for_trades(self, trades: list[dict]) -> dict:
        # OddsEngine is an all-book read-only feed for the four calculator
        # tools. Execution routing remains with the venue-specific adapters.
        return {}

    def invalidate_cache(self) -> None:
        with self._lock:
            self._league_cache.clear()
            self._odds_cache.clear()

    def ev_events(
        self,
        *,
        sport_keys: Iterable[str],
        market_keys: Iterable[str],
    ) -> list[dict]:
        if not self.api_key:
            return []
        requested_sports = tuple(
            dict.fromkeys(
                str(key).strip().lower() for key in sport_keys if str(key).strip()
            )
        )
        requested_markets = tuple(
            dict.fromkeys(
                str(key).strip().lower() for key in market_keys if str(key).strip()
            )
        )
        if not requested_sports or not requested_markets:
            return []

        # A single process can serve all four tools concurrently. Serialize the
        # first cache fill so those requests share one upstream schedule/odds scan.
        with self._scan_lock:
            return self._load_events(requested_sports, requested_markets)

    def _load_events(
        self,
        requested_sports: tuple[str, ...],
        requested_markets: tuple[str, ...],
    ) -> list[dict]:

        now = datetime.now(timezone.utc)
        candidates: list[tuple[datetime, str, dict]] = []
        for sport_key in requested_sports:
            league = _sport_key_league(sport_key)
            events = self._league_events(league)
            upcoming = []
            for event in events:
                start = _parse_time(event.get("event_start"))
                if start is not None and start > now:
                    upcoming.append((start, event))
            for start, event in sorted(upcoming, key=lambda item: item[0])[
                : self.max_events_per_league
            ]:
                candidates.append((start, sport_key, event))

        normalized: list[dict] = []
        for _start, sport_key, event in sorted(candidates, key=lambda item: item[0])[
            : self.max_total_events
        ]:
            event_id = str(event.get("event_id") or "").strip()
            if not event_id:
                continue
            try:
                odds = self._event_odds(event_id)
            except requests.HTTPError as exc:
                status = getattr(exc.response, "status_code", None)
                if status in {401, 403, 429}:
                    raise
                LOGGER.warning("OddsEngine skipped event after HTTP %s", status or "error")
                continue
            converted = normalize_odds_engine_event(
                odds,
                sport_key=sport_key,
                requested_markets=requested_markets,
            )
            if converted:
                normalized.append(converted)
        return normalized

    def diagnostics(self, *, authenticate: bool = False) -> dict:
        status = self.health_status(authenticate=authenticate).value
        with self._lock:
            return {
                "provider": self.provider_key,
                "status": status,
                "configured": bool(self.api_key),
                "read_only": True,
                "cache_entries": len(self._league_cache) + len(self._odds_cache),
                "quota": dict(self._quota),
                "requests": self._requests,
                "lastSuccessAt": self._last_success_at,
                "lastErrorAt": self._last_error_at,
                "credentials_exposed": False,
            }

    def health_status(self, *, authenticate: bool = False) -> ProviderHealthStatus:
        if not self.api_key:
            return ProviderHealthStatus.CONNECTION_FAILED
        if not authenticate:
            return ProviderHealthStatus.CONFIGURED
        try:
            self._request_json("/leagues")
        except requests.HTTPError as exc:
            if getattr(exc.response, "status_code", None) == 401:
                return ProviderHealthStatus.UNAUTHORIZED
            return ProviderHealthStatus.CONNECTION_FAILED
        except (requests.RequestException, ValueError, TypeError):
            return ProviderHealthStatus.CONNECTION_FAILED
        return ProviderHealthStatus.AUTHENTICATED

    def _league_events(self, league: str) -> list[dict]:
        cached = self._cached(self._league_cache, league)
        if cached is not None:
            return cached
        payload = self._request_json("/events", params={"league": league})
        events = payload.get("data") or []
        if not isinstance(events, list):
            raise ValueError("OddsEngine events response data must be a list")
        rows = [event for event in events if isinstance(event, dict)]
        self._store(self._league_cache, league, rows)
        return rows

    def _event_odds(self, event_id: str) -> dict:
        cached = self._cached(self._odds_cache, event_id)
        if cached is not None:
            return cached
        payload = self._request_json("/odds", params={"event_id": event_id})
        odds = payload.get("data") or {}
        if not isinstance(odds, dict):
            raise ValueError("OddsEngine odds response data must be an object")
        self._store(self._odds_cache, event_id, odds)
        return odds

    def _cached(self, cache: dict[str, _TimedValue], key: str):
        now = time.monotonic()
        with self._lock:
            entry = cache.get(key)
            if entry and now - entry.loaded_at < self.cache_ttl_seconds:
                return entry.value
        return None

    def _store(self, cache: dict[str, _TimedValue], key: str, value: object) -> None:
        with self._lock:
            cache[key] = _TimedValue(time.monotonic(), value)

    def _request_json(self, path: str, *, params: dict | None = None) -> dict:
        with self._lock:
            self._requests += 1
        try:
            response = self.session.get(
                f"{self.base_url}{path}",
                params=params,
                headers={"X-API-Key": self.api_key},
                timeout=self.request_timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("OddsEngine response must be an object")
        except Exception:
            with self._lock:
                self._last_error_at = datetime.now(timezone.utc).isoformat()
            raise

        with self._lock:
            self._last_success_at = datetime.now(timezone.utc).isoformat()
            for header, key in (
                ("X-RateLimit-Limit", "limit"),
                ("X-RateLimit-Remaining", "remaining"),
                ("X-RateLimit-Reset", "reset"),
            ):
                value = response.headers.get(header)
                if value is not None:
                    self._quota[key] = str(value)
        return payload
