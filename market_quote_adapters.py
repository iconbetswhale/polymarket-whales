from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable

from market_quotes import NormalizedMarketQuote


def _stable(*parts: object) -> str:
    raw = json.dumps(parts, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _number(value: object) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _market_shape(key: str) -> tuple[str, str, str, bool]:
    normalized = str(key or "").lower()
    alternate = normalized.startswith("alternate_")
    base = normalized.removeprefix("alternate_")
    if base == "h2h":
        return "moneyline", "main", "full_game", alternate
    if base == "spreads":
        return "spread", "main", "full_game", alternate
    if base == "totals":
        return "total", "main", "full_game", alternate
    if base == "outrights":
        return "outright", "main", "full_event", alternate
    family = "player_prop" if base.startswith(("player_", "batter_", "pitcher_")) else "other"
    return base, family, "full_game", alternate


def normalize_odds_api_events(
    events: Iterable[dict[str, Any]], *, received_timestamp: datetime | None = None
) -> list[NormalizedMarketQuote]:
    """Normalize only fields documented by The Odds API.

    Bookmaker keys remain the canonical provider names. ``bet_limit`` is a
    market limit, not order-book liquidity; it is never relabeled as depth.
    """
    received = received_timestamp or datetime.now(timezone.utc)
    quotes: list[NormalizedMarketQuote] = []
    for event in events:
        event_id = str(event.get("id") or "")
        sport = str(event.get("sport_key") or "")
        league = str(event.get("sport_title") or sport)
        home = event.get("home_team")
        away = event.get("away_team")
        starts = event.get("commence_time")
        if not event_id or not starts:
            continue
        event_name = f"{away} vs {home}" if away and home else str(home or away or event_id)
        for book in event.get("bookmakers") or ():
            provider = str(book.get("key") or "").strip().lower()
            if not provider:
                continue
            for market in book.get("markets") or ():
                market_key = str(market.get("key") or "")
                market_type, family, period, alternate = _market_shape(market_key)
                updated = market.get("last_update") or book.get("last_update") or received
                for outcome in market.get("outcomes") or ():
                    price = _number(outcome.get("price"))
                    selection = str(outcome.get("name") or "")
                    if not selection or price is None or price == 0:
                        continue
                    line = _number(outcome.get("point"))
                    description = str(outcome.get("description") or "")
                    side = selection if selection.lower() in {"over", "under", "yes", "no"} else None
                    provider_market_id = str(
                        market.get("id")
                        or _stable(event_id, provider, market_key, line, description)
                    )
                    provider_selection_id = str(
                        outcome.get("sid")
                        or outcome.get("id")
                        or _stable(provider_market_id, selection, description)
                    )
                    try:
                        quotes.append(
                            NormalizedMarketQuote.create(
                                provider=provider,
                                provider_event_id=event_id,
                                provider_market_id=provider_market_id,
                                provider_selection_id=provider_selection_id,
                                sport=sport,
                                league=league,
                                event_name=event_name,
                                home_team=None if home is None else str(home),
                                away_team=None if away is None else str(away),
                                start_time=starts,
                                market_type=market_type,
                                market_family=family,
                                period=period,
                                is_alternate=alternate,
                                line=line,
                                selection=selection if not description else f"{description} {selection}",
                                side=side,
                                american_odds=price,
                                quote_timestamp=updated,
                                received_timestamp=received,
                                available_liquidity=_number(outcome.get("liquidity")),
                                market_limit=_number(outcome.get("bet_limit")),
                                mapping_confidence=1.0,
                                settlement_rule_key=f"{sport}:{market_key}:{period}",
                            )
                        )
                    except (TypeError, ValueError):
                        continue
    return quotes
