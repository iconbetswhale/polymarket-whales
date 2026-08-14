from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol, runtime_checkable


_SPACE = re.compile(r"[^a-z0-9]+")


def _slug(value: object) -> str:
    return _SPACE.sub("-", str(value or "").strip().lower()).strip("-")


def _stable_id(prefix: str, *parts: object) -> str:
    payload = json.dumps(parts, ensure_ascii=True, separators=(",", ":"), default=str)
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def _utc(value: datetime | str | None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    else:
        parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def american_to_decimal(odds: int | float) -> float:
    value = float(odds)
    if value == 0:
        raise ValueError("American odds cannot be zero")
    return 1.0 + (value / 100.0 if value > 0 else 100.0 / abs(value))


def decimal_to_american(decimal_odds: float) -> int:
    value = float(decimal_odds)
    if value <= 1.0:
        raise ValueError("Decimal odds must be greater than one")
    return round((value - 1.0) * 100.0 if value >= 2.0 else -100.0 / (value - 1.0))


def probability_to_american(probability: float) -> int:
    value = float(probability)
    if not 0.0 < value < 1.0:
        raise ValueError("Implied probability must be between zero and one")
    return decimal_to_american(1.0 / value)


def canonical_event_id(
    *,
    sport: str,
    league: str,
    start_time: datetime | str,
    home_team: str | None,
    away_team: str | None,
    event_name: str | None = None,
) -> str:
    start = _utc(start_time).replace(second=0, microsecond=0).isoformat()
    return _stable_id(
        "evt",
        _slug(sport),
        _slug(league),
        start,
        _slug(home_team),
        _slug(away_team),
        _slug(event_name) if not home_team and not away_team else "",
    )


def canonical_market_id(
    *,
    event_id: str,
    market_type: str,
    market_family: str,
    period: str,
    is_alternate: bool,
    line: float | None,
) -> str:
    return _stable_id(
        "mkt",
        event_id,
        _slug(market_type),
        _slug(market_family),
        _slug(period),
        bool(is_alternate),
        None if line is None else round(float(line), 6),
    )


def canonical_selection_id(
    *, market_id: str, selection: str, side: str | None
) -> str:
    return _stable_id("sel", market_id, _slug(selection), _slug(side))


@dataclass(frozen=True)
class NormalizedMarketQuote:
    """Provider-neutral, immutable top-of-book market quote.

    Liquidity and limits are deliberately optional. A missing provider field is
    represented by ``None`` rather than inferred or fabricated.
    """

    provider: str
    provider_event_id: str
    provider_market_id: str
    provider_selection_id: str

    sport: str
    league: str

    event_id: str
    event_name: str
    home_team: str | None
    away_team: str | None
    start_time: datetime

    market_type: str
    market_family: str
    period: str
    is_alternate: bool
    line: float | None
    selection: str
    side: str | None

    american_odds: int
    decimal_odds: float
    implied_probability: float

    quote_timestamp: datetime
    received_timestamp: datetime

    available_liquidity: float | None = None
    market_limit: float | None = None
    mapping_confidence: float | None = None
    settlement_rule_key: str | None = None

    @classmethod
    def create(
        cls,
        *,
        provider: str,
        provider_event_id: object,
        provider_market_id: object,
        provider_selection_id: object,
        sport: str,
        league: str,
        event_name: str,
        home_team: str | None,
        away_team: str | None,
        start_time: datetime | str,
        market_type: str,
        market_family: str,
        period: str = "full_game",
        is_alternate: bool = False,
        line: float | None = None,
        selection: str,
        side: str | None = None,
        american_odds: int | float | None = None,
        decimal_odds: float | None = None,
        implied_probability: float | None = None,
        quote_timestamp: datetime | str | None = None,
        received_timestamp: datetime | str | None = None,
        available_liquidity: float | None = None,
        market_limit: float | None = None,
        mapping_confidence: float | None = None,
        settlement_rule_key: str | None = None,
        event_id: str | None = None,
    ) -> "NormalizedMarketQuote":
        provider_ids = {
            "provider": provider,
            "provider_event_id": provider_event_id,
            "provider_market_id": provider_market_id,
            "provider_selection_id": provider_selection_id,
        }
        missing_ids = [key for key, value in provider_ids.items() if not str(value or "").strip()]
        if missing_ids:
            raise ValueError(f"Normalized quote is missing required identity fields: {', '.join(missing_ids)}")
        if american_odds is None:
            if decimal_odds is not None:
                american_odds = decimal_to_american(decimal_odds)
            elif implied_probability is not None:
                american_odds = probability_to_american(implied_probability)
            else:
                raise ValueError("A real price is required to create a normalized quote")
        american = int(round(float(american_odds)))
        decimal = float(decimal_odds or american_to_decimal(american))
        probability = float(implied_probability or (1.0 / decimal))
        start = _utc(start_time)
        canonical_event = event_id or canonical_event_id(
            sport=sport,
            league=league,
            start_time=start,
            home_team=home_team,
            away_team=away_team,
            event_name=event_name,
        )
        market_id = canonical_market_id(
            event_id=canonical_event,
            market_type=market_type,
            market_family=market_family,
            period=period,
            is_alternate=is_alternate,
            line=line,
        )
        selection_id = canonical_selection_id(
            market_id=market_id, selection=selection, side=side
        )
        confidence = None if mapping_confidence is None else max(0.0, min(1.0, float(mapping_confidence)))
        return cls(
            provider=_slug(provider),
            provider_event_id=str(provider_event_id or ""),
            provider_market_id=str(provider_market_id or ""),
            provider_selection_id=str(provider_selection_id or ""),
            sport=str(sport),
            league=str(league),
            event_id=canonical_event,
            event_name=str(event_name),
            home_team=home_team,
            away_team=away_team,
            start_time=start,
            market_type=str(market_type),
            market_family=str(market_family),
            period=str(period),
            is_alternate=bool(is_alternate),
            line=None if line is None else float(line),
            selection=str(selection),
            side=None if side is None else str(side),
            american_odds=american,
            decimal_odds=decimal,
            implied_probability=probability,
            quote_timestamp=_utc(quote_timestamp),
            received_timestamp=_utc(received_timestamp),
            available_liquidity=None if available_liquidity is None else float(available_liquidity),
            market_limit=None if market_limit is None else float(market_limit),
            mapping_confidence=confidence,
            settlement_rule_key=settlement_rule_key,
        )

    @property
    def market_id(self) -> str:
        return canonical_market_id(
            event_id=self.event_id,
            market_type=self.market_type,
            market_family=self.market_family,
            period=self.period,
            is_alternate=self.is_alternate,
            line=self.line,
        )

    @property
    def selection_id(self) -> str:
        return canonical_selection_id(
            market_id=self.market_id, selection=self.selection, side=self.side
        )

    def with_received_timestamp(self, value: datetime | str) -> "NormalizedMarketQuote":
        return replace(self, received_timestamp=_utc(value))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["market_id"] = self.market_id
        payload["selection_id"] = self.selection_id
        for key in ("start_time", "quote_timestamp", "received_timestamp"):
            payload[key] = payload[key].isoformat()
        return payload


@runtime_checkable
class NormalizedQuoteAdapter(Protocol):
    provider_key: str

    def normalized_quotes(self, payload: Any) -> Iterable[NormalizedMarketQuote]:
        """Map a documented provider payload into canonical quotes."""
