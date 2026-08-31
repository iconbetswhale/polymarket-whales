from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

import requests

from execution_providers import (
    EASTERN,
    MARKET_NOT_FOUND,
    PROVIDER_NOT_CONFIGURED,
    CanonicalTrade,
    ExecutionOption,
    ExecutionProvider,
    MatchConfidence,
    ProviderHealthStatus,
    ProviderMarketIndex,
    _fair_quotes_from_index,
    _match_exact_trade,
    american_to_probability,
    canonicalize_trade,
)
from sports_game_odds import (
    SPORTS_GAME_ODDS_BOOKMAKERS,
    SPORTS_GAME_ODDS_LOGOS,
    positive_ev_catalog_payload,
)
from the_odds_api_provider import normalize_the_odds_api_events


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
    "soccer_epl": "epl",
    "soccer_usa_mls": "mls",
}

SPORT_KEY_BY_LEAGUE = {
    league.upper(): sport_key for sport_key, league in SPORT_KEY_TO_LEAGUE.items()
}
DEFAULT_SPORT_KEYS_BY_SPORT = {
    "BASEBALL": ("baseball_mlb",),
    "FOOTBALL": ("americanfootball_nfl", "americanfootball_ncaaf"),
    "BASKETBALL": ("basketball_nba", "basketball_wnba", "basketball_ncaab"),
    "HOCKEY": ("icehockey_nhl",),
    "SOCCER": ("soccer_usa_mls", "soccer_epl"),
}

MARKET_KEY_BY_KIND = {
    "moneyline": "h2h",
    "spread": "spreads",
    "game_total": "totals",
    "alternate_spread": "alternate_spreads",
    "alternate_total": "alternate_totals",
}

FAIR_PRICE_BOOK_ALIASES = {
    "pinnacle": "pinnacle",
    "betonline": "betonline",
    "novig": "novig",
    "prophetexchange": "prophetx",
    "kalshi": "kalshi",
    "polymarket": "polymarket",
}

ODDSENGINE_BOOKMAKERS = {
    **SPORTS_GAME_ODDS_BOOKMAKERS,
    "pick6": {"name": "DraftKings Pick6", "type": "dfs"},
    "betr_picks": {"name": "Betr Picks", "type": "dfs"},
    "dabble": {"name": "Dabble", "type": "dfs"},
}
ODDSENGINE_LOGOS = {
    **SPORTS_GAME_ODDS_LOGOS,
    "pick6": "/static/assets/dfs-books/dk-pick6.png",
    "betr_picks": "/static/assets/dfs-books/betr.png",
    "dabble": "/static/assets/dfs-books/dabble.png",
}

BOOK_ALIASES = {
    # OddsEngine exposes Betr's DFS product as `betr` and its sportsbook as
    # the separate `betrsportsbook` id. Keep those feeds isolated.
    "betr": "betr_picks",
    "hardrock": "hardrockbet",
    "prophetx": "prophetexchange",
    "sportsbettingag": "sportsbetting_ag",
    "thescore": "thescorebet",
    "betrpicks": "betr_picks",
    "betrusdfs": "betr_picks",
    "dkpick6": "pick6",
    "draftkingspick6": "pick6",
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

# Sharp Money consumes the complete priced catalog. OddsEngine returns all
# offers for an event in one /odds response; ``*`` is an internal normalization
# sentinel and is never sent upstream.
SHARP_MONEY_SPORT_KEYS = tuple(SPORT_KEY_TO_LEAGUE)
SHARP_MONEY_MARKET_KEYS = ("*",)

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


def _display_name(value: object) -> str:
    """Return a compact human label without inventing provider metadata."""

    return " ".join(str(value or "").replace("_", " ").split()).title()


def _future_book_key(value: object) -> str | None:
    """Keep every book returned by OddsEngine, including newly added books."""

    known = _book_key(value)
    if known:
        return known
    normalized = _slug(value).replace("_", "")
    return normalized or None


def _future_event_from_pointer(source_event: dict, pointer: object) -> dict | None:
    """Expand an OddsEngine outright parent pointer into a fetchable event."""

    if not isinstance(pointer, dict):
        return None
    event_id = next(
        (
            str(pointer.get(key) or "").strip()
            for key in (
                "event_id",
                "future_event_id",
                "outright_event_id",
                "parent_event_id",
                "canonical_event_id",
            )
            if str(pointer.get(key) or "").strip()
        ),
        "",
    )
    if not event_id:
        return None
    return {
        "event_id": event_id,
        "event": (
            pointer.get("event")
            or pointer.get("title")
            or pointer.get("name")
            or pointer.get("market")
            or "Futures"
        ),
        "event_start": (
            pointer.get("event_start")
            or pointer.get("resolution_time")
            or source_event.get("event_start")
        ),
        "league": pointer.get("league") or source_event.get("league"),
        "sport": pointer.get("sport") or source_event.get("sport"),
        "is_future": True,
        "future_type": (
            pointer.get("future_type")
            or pointer.get("type")
            or pointer.get("market_type")
            or ""
        ),
    }


def _ordered_future_events(events: Iterable[dict]) -> list[dict]:
    """Prioritize title futures and rotate leagues when quota is constrained."""

    groups: dict[str, list[dict]] = {}
    for event in events:
        league = str(event.get("league") or "").strip().lower()
        groups.setdefault(league, []).append(event)

    title_terms = (
        "champion",
        "championship",
        "winner",
        "world series",
        "super bowl",
        "finals",
        "title",
    )

    def event_key(event: dict) -> tuple:
        label = " ".join(
            str(event.get(key) or "")
            for key in ("event", "future_type")
        ).lower()
        return (
            0 if any(term in label for term in title_terms) else 1,
            str(event.get("event_start") or ""),
            str(event.get("event") or "").casefold(),
            str(event.get("event_id") or ""),
        )

    for league_events in groups.values():
        league_events.sort(key=event_key)

    league_priority = {"mlb": 0, "nba": 1, "nfl": 2, "wnba": 3}
    leagues = sorted(
        groups,
        key=lambda league: (league_priority.get(league, 4), league),
    )
    ordered: list[dict] = []
    for index in range(max((len(group) for group in groups.values()), default=0)):
        for league in leagues:
            if index < len(groups[league]):
                ordered.append(groups[league][index])
    return ordered


def normalize_odds_engine_future_event(
    payload: dict,
    *,
    schedule_event: dict | None = None,
) -> dict:
    """Flatten every priced outright in one OddsEngine future event.

    Futures are intentionally not filtered through ``SUPPORTED_MARKET_KEYS``.
    The API marks future events in discovery and can add new future types at any
    time, so this normalizer preserves every market, outcome, and sportsbook it
    receives.
    """

    schedule = schedule_event or {}
    event_id = str(payload.get("event_id") or schedule.get("event_id") or "").strip()
    if not event_id:
        return {"rows": [], "providers": []}

    event_title = " ".join(
        str(payload.get("event") or schedule.get("event") or "Futures").split()
    )
    league = str(payload.get("league") or schedule.get("league") or "").strip()
    sport = str(payload.get("sport") or schedule.get("sport") or league).strip()
    resolution_time = str(
        payload.get("event_start") or schedule.get("event_start") or ""
    ).strip()
    future_type = str(
        payload.get("future_type") or schedule.get("future_type") or ""
    ).strip()
    observed_at = datetime.now(timezone.utc).isoformat()
    rows: dict[tuple, dict] = {}
    providers: dict[str, dict] = {}

    for category in payload.get("market_categories") or []:
        if not isinstance(category, dict):
            continue
        category_name = " ".join(str(category.get("category") or "future").split())
        for offer in category.get("offers") or []:
            if not isinstance(offer, dict):
                continue
            market_title = " ".join(
                str(offer.get("market") or offer.get("market_key") or "Futures").split()
            )
            if not market_title:
                continue
            market_key = _slug(offer.get("market_key") or market_title)
            raw_market_id = str(
                offer.get("market_id") or f"{event_id}:{market_key}"
            ).strip()
            offer_line = offer.get("line")
            for raw_book in offer.get("books") or []:
                if not isinstance(raw_book, dict):
                    continue
                book_key = _future_book_key(raw_book.get("book"))
                if not book_key:
                    continue
                provider_key = _oddsengine_provider_key(book_key)
                metadata = ODDSENGINE_BOOKMAKERS.get(book_key, {})
                provider_name = metadata.get("name") or _display_name(
                    raw_book.get("book") or book_key
                )
                providers[provider_key] = {
                    "key": provider_key,
                    "name": provider_name,
                    "logoUrl": ODDSENGINE_LOGOS.get(book_key, ""),
                    "source": "odds_engine",
                    "region": "",
                }
                for selection in raw_book.get("selections") or []:
                    if not isinstance(selection, dict):
                        continue
                    american_odds = _american_odds(selection.get("odds_american"))
                    if american_odds is None:
                        continue
                    outcome = " ".join(
                        str(
                            selection.get("entity_name")
                            or selection.get("side")
                            or "Selection"
                        ).split()
                    )
                    outcome_key = str(selection.get("entity_name_std") or "").strip()
                    outcome_key = outcome_key or _slug(outcome)
                    line = selection.get("line")
                    if line is None:
                        line = offer_line
                    identity = (raw_market_id, outcome_key, str(line or ""))
                    row = rows.setdefault(
                        identity,
                        {
                            "id": (
                                f"oddsengine::future::{event_id}::{raw_market_id}::"
                                f"{outcome_key}::{line if line is not None else ''}"
                            ),
                            "event_id": event_id,
                            "event_title": event_title,
                            "market_id": (
                                f"oddsengine::future::{event_id}::{raw_market_id}::"
                                f"{line if line is not None else ''}"
                            ),
                            "provider_market_id": raw_market_id,
                            "market_key": market_key,
                            "market_title": market_title,
                            "sports_market_type": market_title,
                            "market_category": category_name,
                            "future_type": future_type or market_key,
                            "outcome": outcome,
                            "outcome_key": outcome_key,
                            "market_line": line,
                            "category": _display_name(sport),
                            "canonical_sport_id": sport.lower(),
                            "league": league.upper(),
                            "canonical_league_id": league.upper(),
                            "resolution_time": resolution_time,
                            "event_date_et": resolution_time,
                            "is_future": True,
                            "is_sports": True,
                            "odds_engine_event": True,
                            "executionOptions": [],
                        },
                    )
                    implied = american_to_probability(american_odds)
                    liquidity = _safe_nonnegative(selection.get("liquidity"))
                    bet_limit = _safe_nonnegative(selection.get("limit"))
                    last_update = str(
                        selection.get("odds_changed_at")
                        or selection.get("last_fetched")
                        or observed_at
                    )
                    row["executionOptions"].append(
                        {
                            "providerKey": provider_key,
                            "providerName": provider_name,
                            "logoUrl": ODDSENGINE_LOGOS.get(book_key, ""),
                            "americanOdds": american_odds,
                            "displayOdds": (
                                f"+{american_odds}"
                                if american_odds > 0
                                else str(american_odds)
                            ),
                            "bestExecutablePrice": implied,
                            "contractPrice": None,
                            "availableLiquidity": liquidity,
                            "betLimit": bet_limit,
                            "isAvailable": True,
                            "isStale": False,
                            "marketStatus": "OPEN",
                            "quoteStatus": "OPEN",
                            "matchingConfidence": "Exact",
                            "deepLink": str(selection.get("bet_link") or ""),
                            "lastUpdated": last_update,
                            "marketId": raw_market_id,
                            "selectionId": str(selection.get("selection_id") or ""),
                            "providerEventId": event_id,
                        }
                    )

    normalized_rows = list(rows.values())
    for row in normalized_rows:
        row["executionOptions"].sort(
            key=lambda option: (
                str(option.get("providerName") or "").casefold(),
                str(option.get("providerKey") or ""),
            )
        )
    normalized_rows.sort(
        key=lambda row: (
            str(row.get("market_title") or "").casefold(),
            str(row.get("outcome") or "").casefold(),
        )
    )
    return {
        "rows": normalized_rows,
        "providers": sorted(
            providers.values(), key=lambda provider: provider["name"].casefold()
        ),
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
    return normalized if normalized in ODDSENGINE_BOOKMAKERS else None


def _canonical_market_key(
    offer: dict,
    selections: list[dict],
    *,
    category: dict | None = None,
    allow_unlisted: bool = False,
) -> str | None:
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

    # The scanners currently model these three keys as full-game markets.  A
    # loose ``contains('total')`` fallback previously collapsed team totals,
    # first halves, quarters, periods, and innings into the same family.  That
    # produced impossible middle windows (for example a WNBA team total paired
    # with the full-game total) and crowded out real opportunities.
    if market_key in {"h2h", "spreads", "totals"}:
        scope = "_".join(
            value
            for value in (
                *candidates,
                _slug(offer.get("name")),
                _slug(offer.get("period")),
                _slug(offer.get("period_id")),
                _slug((category or {}).get("category")),
                _slug((category or {}).get("name")),
            )
            if value
        )
        non_full_game_scopes = (
            "team_total",
            "first_half",
            "1st_half",
            "second_half",
            "2nd_half",
            "first_quarter",
            "1st_quarter",
            "second_quarter",
            "2nd_quarter",
            "third_quarter",
            "3rd_quarter",
            "fourth_quarter",
            "4th_quarter",
            "first_period",
            "1st_period",
            "second_period",
            "2nd_period",
            "third_period",
            "3rd_period",
            "first_inning",
            "1st_inning",
            "first_5",
            "first_five",
            "_q1",
            "_q2",
            "_q3",
            "_q4",
            "_1h",
            "_2h",
            "_1p",
            "_2p",
            "_3p",
        )
        category_scope = _slug((category or {}).get("category"))
        if any(token in scope for token in non_full_game_scopes) or category_scope in {
            "half",
            "quarter",
            "period",
            "inning",
        }:
            if not allow_unlisted:
                return None
            market_key = None

    if market_key is None and allow_unlisted:
        market_key = next(
            (candidate for candidate in candidates if candidate), None
        )

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


def _oddsengine_provider_key(book_key: str) -> str:
    return f"oddsengine__{_slug(book_key)}"


def oddsengine_provider_catalog() -> list[dict]:
    """Return every OddsEngine book using line-shop provider identifiers."""

    return sorted(
        (
            {
                "key": _oddsengine_provider_key(book_key),
                "name": metadata["name"],
                "logoUrl": ODDSENGINE_LOGOS.get(book_key, ""),
                "source": "odds_engine",
                "region": "",
            }
            for book_key, metadata in ODDSENGINE_BOOKMAKERS.items()
        ),
        key=lambda item: item["name"].casefold(),
    )


def oddsengine_filter_catalog_payload() -> dict:
    """Return the complete raw-key catalog used by OddsEngine filter UIs."""

    base = positive_ev_catalog_payload()
    existing = {item["key"]: item for item in base["books"]}
    books = []
    for book_key, metadata in ODDSENGINE_BOOKMAKERS.items():
        current = existing.get(book_key, {})
        books.append(
            {
                "key": book_key,
                "name": metadata["name"],
                "type": metadata["type"],
                "logoUrl": ODDSENGINE_LOGOS.get(book_key, ""),
                "defaultExecution": bool(current.get("defaultExecution", False)),
            }
        )
    return {
        **base,
        "catalogVersion": 4,
        "catalogSource": "odds_engine",
        "bookCount": len(books),
        "books": books,
    }


def _safe_nonnegative(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _selection_outcome(
    selection: dict,
    *,
    event: dict,
    offer: dict,
    market_key: str,
    allow_missing_price: bool = False,
) -> dict | None:
    price = _american_odds(selection.get("odds_american"))
    if price is None and not allow_missing_price:
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
        "is_alt": bool(selection.get("is_alt")),
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
    allow_all_markets = "*" in allowed
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
                market_key = _canonical_market_key(
                    offer,
                    selections,
                    category=category,
                    allow_unlisted=allow_all_markets,
                )
                if not market_key or (
                    allowed
                    and not allow_all_markets
                    and market_key not in allowed
                ):
                    continue
                book_key = _book_key(raw_book.get("book"))
                if not book_key:
                    continue
                is_dfs_book = (
                    ODDSENGINE_BOOKMAKERS[book_key]["type"] == "dfs"
                )
                outcomes = [
                    outcome
                    for selection in selections
                    if (
                        outcome := _selection_outcome(
                            selection,
                            event=payload,
                            offer=offer,
                            market_key=market_key,
                            allow_missing_price=is_dfs_book,
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
                        "title": ODDSENGINE_BOOKMAKERS[book_key]["name"],
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
        cache_ttl_seconds: int = 15,
        max_events_per_league: int = 5,
        max_total_events: int = 20,
        max_parallel_requests: int = 16,
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
        self.max_parallel_requests = max(1, min(16, int(max_parallel_requests)))
        self.request_timeout = max(1, int(request_timeout))
        self.session = session or requests.Session()
        self._league_cache: dict[str, _TimedValue] = {}
        self._odds_cache: dict[str, _TimedValue] = {}
        self._last_screen_events: _TimedValue | None = None
        self._futures_screen_cache: _TimedValue | None = None
        self._quota: dict[str, str] = {}
        self._requests = 0
        self._last_success_at: str | None = None
        self._last_error_at: str | None = None
        self._advanced_access: bool | None = None
        self._lock = threading.RLock()
        self._scan_lock = threading.Lock()
        self.failure_reasons: dict[str, str] = {}

    def options_for_trades(
        self, trades: list[dict]
    ) -> dict[str, list[ExecutionOption]]:
        return self._options_for_trades(trades)

    def screen_options_for_trades(
        self, trades: list[dict]
    ) -> dict[str, list[ExecutionOption]]:
        return self._options_for_trades(trades, prefer_screen_cache=True)

    def _options_for_trades(
        self,
        trades: list[dict],
        *,
        prefer_screen_cache: bool = False,
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

        source_trades = {
            str(trade.get("id") or ""): trade for trade in trades
        }
        results: dict[str, list[ExecutionOption]] = {}
        for sport_key, sport_trades in grouped.items():
            requested_markets = tuple(
                dict.fromkeys(
                    market_key
                    for trade in sport_trades
                    for market_key in self._market_keys_for_trade(trade)
                )
            )
            if not requested_markets:
                continue
            events = (
                self._screen_events_for(sport_key, requested_markets)
                if prefer_screen_cache
                else []
            )
            if not events:
                events = self.ev_events(
                    sport_keys=(sport_key,), market_keys=requested_markets
                )
            by_book, metadata = normalize_the_odds_api_events(events)
            for book_key, markets in by_book.items():
                index = ProviderMarketIndex(markets)
                for trade in sport_trades:
                    confidence, matched = _match_exact_trade(
                        trade,
                        index,
                        allow_equivalent_line_class=True,
                    )
                    if confidence is not MatchConfidence.EXACT or matched is None:
                        continue
                    meta = metadata[matched.selection_id]
                    stake = self._recommended_stake(
                        source_trades.get(trade.trade_id, {})
                    )
                    can_fill = (
                        True
                        if meta.bet_limit is None
                        else meta.bet_limit + 1e-9 >= stake
                    )
                    implied = american_to_probability(matched.american_odds)
                    results.setdefault(trade.trade_id, []).append(
                        ExecutionOption(
                            provider_name=meta.name,
                            provider_key=_oddsengine_provider_key(book_key),
                            market_id=(
                                f"{matched.event_id}:{matched.market_name}:"
                                f"{matched.line}"
                            ),
                            selection_id=matched.selection_id,
                            display_odds=matched.display_odds,
                            deep_link=meta.direct_link,
                            is_available=matched.is_available,
                            last_updated=matched.last_updated,
                            matching_confidence=MatchConfidence.EXACT,
                            logo_url=(
                                ODDSENGINE_LOGOS.get(book_key)
                                or meta.logo_url
                            ),
                            tooltip=(
                                f"{meta.name} sportsbook quote via OddsEngine"
                            ),
                            american_odds=matched.american_odds,
                            available_liquidity=meta.bet_limit,
                            can_fill_recommended_stake=can_fill,
                            fee_rate=0.0,
                            quote_status="OPEN",
                            provider_event_id=matched.event_id,
                            native_price_format="AMERICAN",
                            quote_max_age_seconds=180,
                            implied_probability=implied,
                            best_executable_price=implied,
                            top_price=implied,
                            top_price_american_odds=matched.american_odds,
                            is_exact_match=True,
                            market_status="OPEN",
                        )
                    )
        for trade in canonical:
            if trade.trade_id not in results:
                self.failure_reasons.setdefault(trade.trade_id, MARKET_NOT_FOUND)
        return results

    def fair_price_quotes(self, trades: list[dict]) -> dict[str, list[dict]]:
        if not self.api_key or not trades:
            return {}
        canonical = [
            item for trade in trades if (item := canonicalize_trade(trade))
        ]
        grouped: dict[str, list[CanonicalTrade]] = {}
        for trade in canonical:
            sport_key = self._sport_key_for_trade(trade)
            if sport_key:
                grouped.setdefault(sport_key, []).append(trade)

        results: dict[str, list[dict]] = {}
        for sport_key, sport_trades in grouped.items():
            requested_markets = tuple(
                dict.fromkeys(
                    market_key
                    for trade in sport_trades
                    for market_key in self._market_keys_for_trade(trade)
                )
            )
            if not requested_markets:
                continue
            events = self.ev_events(
                sport_keys=(sport_key,), market_keys=requested_markets
            )
            by_book, _metadata = normalize_the_odds_api_events(events)
            for book_key, provider_alias in FAIR_PRICE_BOOK_ALIASES.items():
                markets = by_book.get(book_key)
                if not markets:
                    continue
                quotes = _fair_quotes_from_index(
                    sport_trades,
                    ProviderMarketIndex(markets),
                    provider_alias,
                    allow_equivalent_line_class=True,
                )
                for trade_id, quote in quotes.items():
                    results.setdefault(trade_id, []).append(quote)
        return results

    def invalidate_cache(self) -> None:
        with self._lock:
            self._league_cache.clear()
            self._odds_cache.clear()
            self._last_screen_events = None
            self._futures_screen_cache = None

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
        # The comparison screen must cover the selected league's full slate,
        # not only the small opportunity-scanner sample. OddsEngine exposes one
        # REST odds snapshot per event, so consume at most the documented plan
        # budget and retain the result for the exact option-matching pass below.
        with self._scan_lock:
            events = self._load_events(
                sport_keys,
                market_keys,
                max_events_per_league=50,
                max_total_events=50,
            )
        with self._lock:
            self._last_screen_events = _TimedValue(time.monotonic(), events)
        by_book, _metadata = normalize_the_odds_api_events(events)
        unique: dict[tuple, dict] = {}
        for market in (item for rows in by_book.values() for item in rows):
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
                    "Alternate Spread" if market.is_alternative else "Spread"
                ),
                "game_total": (
                    "Alternate Total" if market.is_alternative else "Game Total"
                ),
            }[market.market_name]
            market_variant = (
                f"alternate_{market.market_name}"
                if market.is_alternative
                else market.market_name
            )
            unique[identity] = {
                "id": (
                    f"oddsengine::{market.event_id}::{market_variant}::"
                    f"{market.side_id}::{market.line}"
                ),
                "event_id": market.event_id,
                "market_id": (
                    f"oddsengine::{market.event_id}::{market_variant}::"
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
                "schedule_date_et": (
                    market.start_at.astimezone(EASTERN).date().isoformat()
                ),
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
                "odds_engine_event": True,
            }
        return sorted(
            unique.values(),
            key=lambda row: (
                str(row.get("resolution_time") or ""),
                str(row.get("market_id") or ""),
                str(row.get("outcome") or ""),
            ),
        )

    def futures_screen_snapshot(self, *, force: bool = False) -> dict:
        """Discover and return every currently priced OddsEngine future."""

        if not self.api_key:
            return {
                "configured": False,
                "complete": False,
                "data": [],
                "providers": [],
                "leagues": [],
                "markets": [],
                "futureTypes": [],
                "message": "OddsEngine is not configured.",
            }

        cache_ttl = max(60, self.cache_ttl_seconds * 4)
        if not force:
            with self._lock:
                cached = self._futures_screen_cache
                if cached and time.monotonic() - cached.loaded_at < cache_ttl:
                    return dict(cached.value)

        started = time.monotonic()
        with self._scan_lock:
            if not force:
                with self._lock:
                    cached = self._futures_screen_cache
                    if cached and time.monotonic() - cached.loaded_at < cache_ttl:
                        return dict(cached.value)

            league_payload = self._request_json("/leagues")
            league_codes = tuple(
                dict.fromkeys(
                    str(item.get("league") or "").strip().lower()
                    for item in league_payload.get("data") or []
                    if isinstance(item, dict)
                    and str(item.get("league") or "").strip()
                )
            )
            discovery_errors: list[str] = []
            discovered_events: dict[str, dict] = {}
            if league_codes:
                with ThreadPoolExecutor(
                    max_workers=min(self.max_parallel_requests, len(league_codes))
                ) as executor:
                    futures = {
                        executor.submit(self._league_events, league): league
                        for league in league_codes
                    }
                    for future in as_completed(futures):
                        league = futures[future]
                        try:
                            events = future.result()
                        except Exception as exc:
                            discovery_errors.append(f"{league}:{type(exc).__name__}")
                            continue
                        for event in events:
                            if not isinstance(event, dict):
                                continue
                            event_id = str(event.get("event_id") or "").strip()
                            is_direct_future = event.get("is_future") or event.get(
                                "future_type"
                            )
                            if is_direct_future and event_id:
                                # A direct future record is richer than a parent
                                # pointer and must win if both forms are present.
                                discovered_events[event_id] = event
                            for pointer in event.get("outrights") or []:
                                parent = _future_event_from_pointer(event, pointer)
                                if parent is not None:
                                    discovered_events.setdefault(
                                        parent["event_id"], parent
                                    )

            ordered_events = _ordered_future_events(discovered_events.values())
            normalized_rows: list[dict] = []
            provider_catalog: dict[str, dict] = {}
            fetched_events = 0
            odds_errors: list[str] = []
            cursor = 0
            while cursor < len(ordered_events):
                remaining = self._quota_remaining()
                if remaining == 0:
                    break
                available = len(ordered_events) - cursor
                batch_size = min(
                    self.max_parallel_requests,
                    available,
                    available if remaining is None else remaining,
                )
                if batch_size <= 0:
                    break
                batch = ordered_events[cursor : cursor + batch_size]
                cursor += batch_size
                fetched: dict[int, tuple[dict | None, Exception | None]] = {}
                with ThreadPoolExecutor(max_workers=batch_size) as executor:
                    futures = {
                        executor.submit(
                            self._event_odds,
                            str(event.get("event_id") or "").strip(),
                        ): index
                        for index, event in enumerate(batch)
                    }
                    for future in as_completed(futures):
                        index = futures[future]
                        try:
                            fetched[index] = (future.result(), None)
                        except Exception as exc:
                            fetched[index] = (None, exc)
                for index, event in enumerate(batch):
                    odds, error = fetched[index]
                    if error is not None:
                        odds_errors.append(
                            f"{event.get('event_id')}:{type(error).__name__}"
                        )
                        continue
                    fetched_events += 1
                    normalized = normalize_odds_engine_future_event(
                        odds or {}, schedule_event=event
                    )
                    normalized_rows.extend(normalized["rows"])
                    for provider in normalized["providers"]:
                        provider_catalog[provider["key"]] = provider

            leagues = sorted(
                {
                    str(row.get("canonical_league_id") or "").upper()
                    for row in normalized_rows
                    if row.get("canonical_league_id")
                }
            )
            markets = sorted(
                {
                    str(row.get("market_title") or "").strip()
                    for row in normalized_rows
                    if row.get("market_title")
                },
                key=str.casefold,
            )
            future_types = sorted(
                {
                    str(row.get("future_type") or "").strip()
                    for row in normalized_rows
                    if row.get("future_type")
                },
                key=str.casefold,
            )
            complete = (
                not discovery_errors
                and not odds_errors
                and fetched_events == len(ordered_events)
            )
            payload = {
                "configured": True,
                "complete": complete,
                "data": normalized_rows,
                "providers": sorted(
                    provider_catalog.values(),
                    key=lambda provider: provider["name"].casefold(),
                ),
                "leagues": leagues,
                "markets": markets,
                "futureTypes": future_types,
                "meta": {
                    "activeLeagueCount": len(league_codes),
                    "futureEventCount": len(ordered_events),
                    "fetchedEventCount": fetched_events,
                    "selectionCount": len(normalized_rows),
                    "providerCount": len(provider_catalog),
                    "discoveryErrors": discovery_errors,
                    "oddsErrors": odds_errors,
                    "responseMs": int((time.monotonic() - started) * 1000),
                    "quota": dict(self._quota),
                },
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "refreshSeconds": 60,
                "message": (
                    "Every discovered future is loaded."
                    if complete
                    else "Showing the priced inventory returned before the current API limit."
                ),
            }
            with self._lock:
                self._futures_screen_cache = _TimedValue(time.monotonic(), payload)
            return dict(payload)

    def sharp_money_snapshot(self, *, limit: int = 100) -> dict:
        """Return OddsEngine's Advanced whale/depth snapshot for ProphetX.

        The endpoint is a single materialized read and includes the full
        two-sided exchange order book plus peer prices. Keeping this separate
        from ``ev_events`` avoids rebuilding depth from top-of-book quotes.
        """
        if not self.api_key:
            return {}
        cache_key = f"__sharp_money_whale__:{max(1, min(int(limit), 100))}"
        cached = self._cached(self._odds_cache, cache_key)
        if cached is not None:
            return cached
        try:
            payload = self._request_json(
                "/orderbook/top",
                params={
                    "sort": "whale",
                    # Keep ProphetX in OddsEngine's best-odds selection while
                    # retaining the full exchange depth carried on both sides.
                    "selected_books": "prophetx",
                    "limit": max(1, min(int(limit), 100)),
                },
            )
        except requests.HTTPError as exc:
            if getattr(exc.response, "status_code", None) == 403:
                with self._lock:
                    self._advanced_access = False
            raise
        with self._lock:
            self._advanced_access = True
        self._store(self._odds_cache, cache_key, payload)
        return payload

    def sharp_money_quote_snapshot(self, *, limit: int = 100) -> dict:
        """Return the standard-plan exact-price slate used for Sharp Money.

        Standard OddsEngine keys do not include materialized order books. This
        snapshot intentionally exposes only the same exact REST prices already
        used by line shopping so the collector can infer cross-book consensus
        and price movement without inventing depth or wager volume.
        """
        if not self.api_key:
            return {}
        # Keep this scan inside the same provider lock/cache used by the four
        # opportunity tools. The cap respects the standard 60-request plan:
        # ten league discovery calls leave up to fifty event-odds reads, and a
        # provider rate-limit still returns the truthful partial snapshot.
        with self._scan_lock:
            events = self._load_events(
                SHARP_MONEY_SPORT_KEYS,
                SHARP_MONEY_MARKET_KEYS,
                max_events_per_league=10,
                max_total_events=50,
            )
        return {
            "observedAt": datetime.now(timezone.utc).isoformat(),
            "events": events,
            "limit": max(1, min(int(limit), 100)),
            "transport": "rest_snapshot",
        }

    def provider_catalog(self, trades: list[dict]) -> list[dict]:
        catalog = {item["key"]: item for item in oddsengine_provider_catalog()}
        for trade in trades:
            for option in trade.get("executionOptions") or []:
                provider_key = str(option.get("providerKey") or "").strip().lower()
                if not provider_key.startswith("oddsengine__"):
                    continue
                book_key = provider_key.removeprefix("oddsengine__")
                metadata = ODDSENGINE_BOOKMAKERS.get(book_key, {})
                catalog[provider_key] = {
                    "key": provider_key,
                    "name": str(
                        metadata.get("name")
                        or option.get("providerName")
                        or book_key
                    ),
                    "logoUrl": str(
                        option.get("logoUrl")
                        or ODDSENGINE_LOGOS.get(book_key, "")
                    ),
                    "source": self.provider_key,
                    "region": "",
                }
        return sorted(catalog.values(), key=lambda item: item["name"].casefold())

    @staticmethod
    def _sport_key_for_trade(trade: CanonicalTrade) -> str | None:
        league = str(trade.league_id or "").upper().replace("-", "_")
        if league in SPORT_KEY_BY_LEAGUE:
            return SPORT_KEY_BY_LEAGUE[league]
        candidates = DEFAULT_SPORT_KEYS_BY_SPORT.get(trade.sport_id, ())
        return candidates[0] if len(candidates) == 1 else None

    @staticmethod
    def _market_keys_for_trade(trade: CanonicalTrade) -> tuple[str, ...]:
        if trade.market_kind == "spread":
            return (
                ("alternate_spreads",)
                if trade.is_alternative
                else ("spreads", "alternate_spreads")
            )
        if trade.market_kind == "game_total":
            return (
                ("alternate_totals",)
                if trade.is_alternative
                else ("totals", "alternate_totals")
            )
        market_key = MARKET_KEY_BY_KIND.get(trade.market_kind)
        return (market_key,) if market_key else ()

    @staticmethod
    def _recommended_stake(trade: dict) -> float:
        for source in (trade.get("card") or {}, trade.get("recommendation") or {}):
            value = _safe_nonnegative(source.get("recommended_amount"))
            if value is not None:
                return value
        return 0.0

    @staticmethod
    def _screen_sport_keys(*, sport: str, league: str) -> tuple[str, ...]:
        normalized_league = str(league or "").strip().upper()
        if normalized_league in SPORT_KEY_BY_LEAGUE:
            return (SPORT_KEY_BY_LEAGUE[normalized_league],)
        normalized_sport = str(sport or "").strip().upper()
        if normalized_sport in DEFAULT_SPORT_KEYS_BY_SPORT:
            return DEFAULT_SPORT_KEYS_BY_SPORT[normalized_sport]
        return ("baseball_mlb",)

    @staticmethod
    def _screen_market_keys(market_kind: str) -> tuple[str, ...]:
        normalized = str(market_kind or "").strip()
        if normalized and normalized not in MARKET_KEY_BY_KIND:
            return ()
        requested = MARKET_KEY_BY_KIND.get(normalized)
        return (requested,) if requested else ("h2h", "spreads", "totals")

    def _load_events(
        self,
        requested_sports: tuple[str, ...],
        requested_markets: tuple[str, ...],
        *,
        max_events_per_league: int | None = None,
        max_total_events: int | None = None,
    ) -> list[dict]:

        now = datetime.now(timezone.utc)
        candidates: list[tuple[datetime, str, dict]] = []
        league_results: dict[int, tuple[list[dict] | None, Exception | None]] = {}
        league_workers = min(self.max_parallel_requests, len(requested_sports))
        with ThreadPoolExecutor(max_workers=league_workers) as executor:
            futures = {
                executor.submit(
                    self._league_events,
                    _sport_key_league(sport_key),
                ): index
                for index, sport_key in enumerate(requested_sports)
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    league_results[index] = (future.result(), None)
                except Exception as exc:  # handled in requested sport order below
                    league_results[index] = (None, exc)

        league_retryable_error: requests.HTTPError | None = None
        per_league_limit = max(
            1,
            min(
                50,
                int(max_events_per_league or self.max_events_per_league),
            ),
        )
        total_limit = max(
            1,
            min(100, int(max_total_events or self.max_total_events)),
        )
        for index, sport_key in enumerate(requested_sports):
            events, error = league_results[index]
            if error is not None:
                if isinstance(error, requests.HTTPError):
                    status = getattr(error.response, "status_code", None)
                    if status not in {401, 403}:
                        league_retryable_error = error
                        LOGGER.warning(
                            "OddsEngine skipped %s schedule after HTTP %s",
                            sport_key,
                            status or "error",
                        )
                        continue
                raise error
            upcoming = []
            for event in events or []:
                start = _parse_time(event.get("event_start"))
                if start is not None and start > now:
                    upcoming.append((start, event))
            for start, event in sorted(upcoming, key=lambda item: item[0])[
                :per_league_limit
            ]:
                candidates.append((start, sport_key, event))
        if league_retryable_error is not None and not candidates:
            raise league_retryable_error

        pending = [
            item
            for item in sorted(candidates, key=lambda item: item[0])[
                :total_limit
            ]
            if str(item[2].get("event_id") or "").strip()
        ]
        normalized: list[dict] = []
        cursor = 0
        while cursor < len(pending):
            # Fetch independent event snapshots concurrently. OddsEngine's
            # standard endpoint is one request per event; doing these serially
            # made a ten-event Positive EV scan take several minutes even
            # though the same normalization/calculation work is inexpensive.
            remaining = self._quota_remaining()
            available = len(pending) - cursor
            quota_slots = available if remaining is None else max(1, remaining)
            batch_size = min(
                self.max_parallel_requests,
                available,
                quota_slots,
            )
            batch = pending[cursor : cursor + batch_size]
            cursor += batch_size
            fetched: dict[int, tuple[dict | None, Exception | None]] = {}
            with ThreadPoolExecutor(max_workers=batch_size) as executor:
                futures = {
                    executor.submit(
                        self._event_odds,
                        str(event.get("event_id") or "").strip(),
                    ): index
                    for index, (_start, _sport_key, event) in enumerate(batch)
                }
                for future in as_completed(futures):
                    index = futures[future]
                    try:
                        fetched[index] = (future.result(), None)
                    except Exception as exc:  # handled in stable event order below
                        fetched[index] = (None, exc)

            rate_limited: requests.HTTPError | None = None
            for index, (_start, sport_key, _event) in enumerate(batch):
                odds, error = fetched[index]
                if error is not None:
                    if isinstance(error, requests.HTTPError):
                        status = getattr(error.response, "status_code", None)
                        if status == 429:
                            rate_limited = error
                            continue
                        if status in {401, 403}:
                            raise error
                        LOGGER.warning(
                            "OddsEngine skipped event after HTTP %s",
                            status or "error",
                        )
                        continue
                    raise error
                converted = normalize_odds_engine_event(
                    odds or {},
                    sport_key=sport_key,
                    requested_markets=requested_markets,
                )
                if converted:
                    normalized.append(converted)

            # Preserve a usable partial snapshot when the plan limit is hit.
            # A fresh serverless invocation cannot share in-memory cache state,
            # so this is materially better than a page-wide 502.
            if rate_limited is not None:
                if normalized:
                    break
                raise rate_limited
            if normalized and self._quota_remaining() == 0:
                break
        return normalized

    def _screen_events_for(
        self,
        sport_key: str,
        requested_markets: Iterable[str],
    ) -> list[dict]:
        with self._lock:
            entry = self._last_screen_events
            if (
                entry is None
                or time.monotonic() - entry.loaded_at >= self.cache_ttl_seconds
            ):
                return []
            events = list(entry.value or [])
        required = {
            str(value).strip().lower()
            for value in requested_markets
            if str(value).strip()
        }
        matching = [
            event
            for event in events
            if str(event.get("sport_key") or "").strip().lower() == sport_key
        ]
        if not matching:
            return []
        available = {
            str(market.get("key") or "").strip().lower()
            for event in matching
            for book in event.get("bookmakers") or []
            for market in book.get("markets") or []
        }
        return matching if required.intersection(available) else []

    def _quota_remaining(self) -> int | None:
        with self._lock:
            value = self._quota.get("remaining")
        try:
            return max(0, int(str(value)))
        except (TypeError, ValueError):
            return None

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
                "metrics": {"requests": self._requests},
                "supportsOrderBook": self._advanced_access is not False,
                "supportsWebSocket": self._advanced_access is not False,
                "advancedAccess": self._advanced_access,
                "snapshotTransport": "rest",
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
            # Rate-limit headers are useful on both success and 429 responses.
            # Record them before raise_for_status() so the current scan can
            # stop cleanly and leave remaining quota for the other live tools.
            with self._lock:
                for header, key in (
                    ("X-RateLimit-Limit", "limit"),
                    ("X-RateLimit-Remaining", "remaining"),
                    ("X-RateLimit-Reset", "reset"),
                ):
                    value = response.headers.get(header)
                    if value is not None:
                        self._quota[key] = str(value)
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
        return payload
