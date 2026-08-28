"""Build sportsbook-screen rows directly from normalized all-book events.

The opportunity providers already expose a shared event shape (the same shape
consumed by the EV, arbitrage, middle, and low-hold engines).  Building the
screen from that shape avoids a second canonical matching pass and, more
importantly, preserves every bookmaker quote returned in the original batch.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from execution_providers import american_to_probability
from sports_game_odds import SPORTS_GAME_ODDS_BOOKMAKERS, SPORTS_GAME_ODDS_LOGOS


EASTERN = ZoneInfo("America/New_York")
SPORT_ID_BY_PREFIX = {
    "americanfootball": "FOOTBALL",
    "baseball": "BASEBALL",
    "basketball": "BASKETBALL",
    "icehockey": "HOCKEY",
    "soccer": "SOCCER",
    "mma": "MMA",
    "tennis": "TENNIS",
}
MARKET_LABELS = {
    "h2h": "Moneyline",
    "spreads": "Spread",
    "totals": "Game Total",
    "alternate_spreads": "Alternate Spread",
    "alternate_totals": "Alternate Total",
}


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


def _american(value: object) -> int | None:
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return parsed if parsed else None


def _nonnegative(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _market_label(market_key: str) -> str:
    if market_key in MARKET_LABELS:
        return MARKET_LABELS[market_key]
    replacements = {
        "Rbis": "RBIs",
        "Q1": "1st Quarter",
        "H2h": "Moneyline",
    }
    label = market_key.replace("_", " ").title()
    for source, replacement in replacements.items():
        label = label.replace(source, replacement)
    return label


def _provider_key(book_key: str, namespace: str) -> str:
    return f"{_slug(namespace) or 'oddsengine'}__{_slug(book_key)}"


def _row_hash(parts: tuple[object, ...]) -> str:
    raw = "::".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def build_all_book_odds_screen_rows(
    events: Iterable[dict],
    *,
    now: datetime | None = None,
    max_quote_age_seconds: int = 1800,
    provider_namespace: str = "oddsengine",
) -> list[dict]:
    """Return one screen row per exact selection with every observed book.

    Quotes are grouped only when event, market, participant, side, and line all
    agree.  That strict identity prevents team totals, periods, or separate
    player props from being presented as the same executable market.
    """

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    eastern_today = current.astimezone(EASTERN).date()
    allowed_days = {eastern_today, eastern_today + timedelta(days=1)}
    rows: dict[tuple[object, ...], dict] = {}

    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id") or "").strip()
        sport_key = str(event.get("sport_key") or "").strip().lower()
        league = str(event.get("sport_title") or sport_key.rsplit("_", 1)[-1]).strip().upper()
        starts_at = _parse_time(event.get("commence_time"))
        home = str(event.get("home_team") or "").strip()
        away = str(event.get("away_team") or "").strip()
        if not all((event_id, sport_key, league, starts_at, home, away)):
            continue
        if starts_at.astimezone(EASTERN).date() not in allowed_days:
            continue
        sport_id = SPORT_ID_BY_PREFIX.get(sport_key.split("_", 1)[0], sport_key.split("_", 1)[0].upper())

        for bookmaker in event.get("bookmakers") or []:
            if not isinstance(bookmaker, dict):
                continue
            raw_book_key = _slug(bookmaker.get("key"))
            if not raw_book_key:
                continue
            metadata = SPORTS_GAME_ODDS_BOOKMAKERS.get(raw_book_key, {})
            book_name = str(bookmaker.get("title") or metadata.get("name") or raw_book_key).strip()
            logo_url = str(
                bookmaker.get("logo")
                or SPORTS_GAME_ODDS_LOGOS.get(raw_book_key, "")
            ).strip()
            book_link = str(bookmaker.get("link") or "").strip()

            for market in bookmaker.get("markets") or []:
                if not isinstance(market, dict):
                    continue
                market_key = str(market.get("key") or "").strip().lower()
                if not market_key:
                    continue
                market_label = _market_label(market_key)
                is_alternative = market_key.startswith("alternate_")
                market_updated = market.get("last_update") or bookmaker.get("last_update")

                for position, outcome in enumerate(market.get("outcomes") or []):
                    if not isinstance(outcome, dict):
                        continue
                    outcome_name = " ".join(str(outcome.get("name") or "").split())
                    description = " ".join(str(outcome.get("description") or "").split())
                    american = _american(outcome.get("price"))
                    if not outcome_name or american is None:
                        continue
                    point = _nonnegative(outcome.get("point"))
                    if outcome.get("point") is not None:
                        try:
                            point = float(outcome.get("point"))
                        except (TypeError, ValueError):
                            continue
                    identity = (
                        event_id,
                        market_key,
                        description.casefold(),
                        outcome_name.casefold(),
                        point,
                    )
                    group_identity = (
                        event_id,
                        market_key,
                        description.casefold(),
                        point,
                    )
                    row = rows.get(identity)
                    if row is None:
                        row_id = f"allbooks::{_row_hash(identity)}"
                        market_id = f"allbooks::{_row_hash(group_identity)}"
                        implied = american_to_probability(american)
                        row = {
                            "id": row_id,
                            "event_id": event_id,
                            "market_id": market_id,
                            "event_title": f"{away} vs {home}",
                            "market_title": market_label,
                            "odds_market_key": market_key,
                            "sports_market_type": (
                                market_label
                                if market_key in MARKET_LABELS
                                else market_key
                            ),
                            "outcome": outcome_name,
                            "player_name": description or None,
                            "category": sport_id.title(),
                            "canonical_sport_id": sport_id,
                            "league": league,
                            "canonical_league_id": league,
                            "resolution_time": starts_at.isoformat(),
                            "event_date_et": starts_at.isoformat(),
                            "schedule_date_et": starts_at.astimezone(EASTERN).date().isoformat(),
                            "market_line": point,
                            "is_alternative": is_alternative,
                            "is_sports": True,
                            "card": {
                                "current_actionable_price": implied,
                                "recommended_amount": 0,
                            },
                            "recommendation": {
                                "current_user_entry_price": implied,
                                "recommended_amount": 0,
                            },
                            "all_book_event": True,
                            "executionOptions": [],
                        }
                        rows[identity] = row

                    implied = american_to_probability(american)
                    updated_text = str(
                        outcome.get("last_update") or market_updated or ""
                    ).strip()
                    updated_at = _parse_time(updated_text)
                    quote_age = (
                        max(0.0, (current - updated_at).total_seconds())
                        if updated_at is not None
                        else None
                    )
                    deep_link = str(
                        outcome.get("link")
                        or outcome.get("deeplink")
                        or market.get("link")
                        or book_link
                        or ""
                    ).strip()
                    selection_id = str(
                        outcome.get("sid")
                        or outcome.get("id")
                        or f"{position}:{outcome_name}:{point}"
                    )
                    liquidity = _nonnegative(outcome.get("liquidity"))
                    market_limit = _nonnegative(
                        outcome.get("bet_limit")
                        if outcome.get("bet_limit") is not None
                        else outcome.get("limit")
                    )
                    row["executionOptions"].append(
                        {
                            "providerName": book_name,
                            "providerKey": _provider_key(
                                raw_book_key, provider_namespace
                            ),
                            "displayOdds": f"{american:+d}",
                            "deepLink": deep_link or None,
                            "isAvailable": True,
                            "matchingConfidence": "Exact",
                            "logoUrl": logo_url,
                            "americanOdds": american,
                            "contractPrice": implied,
                            "bestExecutablePrice": implied,
                            "availableLiquidity": (
                                liquidity if liquidity is not None else market_limit
                            ),
                            "isBestPrice": False,
                            "lastUpdated": updated_text or None,
                            "quoteAgeSeconds": round(quote_age, 1) if quote_age is not None else None,
                            "isStale": bool(
                                quote_age is not None
                                and quote_age > max(1, int(max_quote_age_seconds))
                            ),
                            "marketStatus": "OPEN",
                            "quoteStatus": "OPEN",
                            "marketId": row["market_id"],
                            "selectionId": selection_id,
                            "providerEventId": event_id,
                            "topPrice": implied,
                            "topPriceLiquidity": liquidity,
                        }
                    )

    for row in rows.values():
        deduplicated: dict[str, dict] = {}
        for option in row["executionOptions"]:
            key = str(option.get("providerKey") or "")
            current_option = deduplicated.get(key)
            if current_option is None:
                deduplicated[key] = option
                continue
            current_time = _parse_time(current_option.get("lastUpdated"))
            candidate_time = _parse_time(option.get("lastUpdated"))
            if candidate_time and (not current_time or candidate_time > current_time):
                deduplicated[key] = option
        options = list(deduplicated.values())
        executable = [
            option
            for option in options
            if option.get("isAvailable")
            and not option.get("isStale")
            and option.get("bestExecutablePrice") is not None
        ]
        if executable:
            best = min(executable, key=lambda option: float(option["bestExecutablePrice"]))
            best["isBestPrice"] = True
        row["executionOptions"] = sorted(
            options, key=lambda option: str(option.get("providerName") or "").casefold()
        )

    return sorted(
        rows.values(),
        key=lambda row: (
            str(row.get("resolution_time") or ""),
            str(row.get("event_title") or ""),
            str(row.get("market_id") or ""),
            str(row.get("outcome") or ""),
        ),
    )
