from __future__ import annotations

import math
import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable


FAIR_PRICE_VERSION = "fair-price-v2"
DEFAULT_MAX_QUOTE_AGE_SECONDS = 180
DEFAULT_PROVIDER_WEIGHTS = {
    "pinnacle": 0.35,
    "circa": 0.25,
    "bookmaker": 0.20,
    "betonline": 0.10,
    "novig": 0.05,
    "prophetx": 0.05,
    "4cx": 0.05,
    "kalshi": 0.05,
}


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def american_to_implied_probability(odds: Any) -> float | None:
    value = _finite(odds)
    if value is None or value == 0:
        return None
    probability = value / (value + 100.0) if value > 0 else -value / (-value + 100.0)
    return probability if 0 < probability < 1 else None


def no_vig_probabilities(american_odds: Iterable[Any]) -> list[float] | None:
    raw = [american_to_implied_probability(item) for item in american_odds]
    if len(raw) < 2 or any(item is None for item in raw):
        return None
    total = sum(item for item in raw if item is not None)
    if total <= 0:
        return None
    return [item / total for item in raw if item is not None]


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class FairPriceResult:
    status: str
    fair_probability: float | None
    source_count: int
    source_dispersion: float | None
    quote_timestamp: str
    mapping_confidence: str
    missing_reason: str | None
    calculation_version: str
    contributions: tuple[dict[str, Any], ...]
    composite_fair_price: float | None = None
    oldest_included_quote: str | None = None
    newest_included_quote: str | None = None
    reliability: float = 0.0
    fabricated_data: bool = False

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["contributions"] = list(self.contributions)
        result["source_weights"] = {
            item["provider"]: item.get("weight")
            for item in self.contributions
            if item.get("included")
        }
        result["excluded_sources"] = [
            {"provider": item["provider"], "reason": item.get("exclusion_reason")}
            for item in self.contributions
            if not item.get("included")
        ]
        return result


class FairPriceEngine:
    """Combines independently sourced, no-vig probabilities without inventing data."""

    def __init__(
        self,
        provider_weights: dict[str, float] | None = None,
        max_quote_age_seconds: int = DEFAULT_MAX_QUOTE_AGE_SECONDS,
    ) -> None:
        self.provider_weights = {
            str(key).lower(): max(0.0, float(value))
            for key, value in (provider_weights or DEFAULT_PROVIDER_WEIGHTS).items()
        }
        self.max_quote_age_seconds = max(1, int(max_quote_age_seconds))

    def calculate(
        self, quotes: Iterable[dict[str, Any]], now: datetime | None = None
    ) -> FairPriceResult:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        included: list[tuple[float, float]] = []
        included_timestamps: list[datetime] = []
        contributions: list[dict[str, Any]] = []
        freshest: datetime | None = None
        for source in quotes:
            provider = str(source.get("provider") or "").strip().lower()
            probability = _finite(source.get("no_vig_probability"))
            timestamp = _parse_timestamp(source.get("quote_timestamp"))
            reason: str | None = None
            if provider == "polymarket":
                reason = "DEPENDENT_EXECUTION_MARKET"
            elif str(source.get("status") or "").upper() != "AVAILABLE":
                reason = str(source.get("missing_reason") or "PROVIDER_UNAVAILABLE")
            elif str(source.get("mapping_confidence") or "").upper() != "EXACT":
                reason = "MARKET_MAPPING_UNCERTAIN"
            elif probability is None or not 0 < probability < 1:
                reason = "INVALID_NO_VIG_PROBABILITY"
            elif timestamp is None:
                reason = "MISSING_QUOTE_TIMESTAMP"
            elif (now - timestamp).total_seconds() > self.max_quote_age_seconds:
                reason = "STALE_QUOTE"
            weight = self.provider_weights.get(provider, 0.0)
            if reason is None and weight <= 0:
                reason = "PROVIDER_WEIGHT_NOT_CONFIGURED"
            included_flag = reason is None
            if included_flag:
                included.append((probability, weight))
                included_timestamps.append(timestamp)
                freshest = timestamp if freshest is None or timestamp > freshest else freshest
            contributions.append(
                {
                    "provider": provider,
                    "included": included_flag,
                    "weight": weight,
                    "no_vig_probability": probability,
                    "quote_timestamp": timestamp.isoformat() if timestamp else None,
                    "exclusion_reason": reason,
                    "source_snapshot": source,
                }
            )
        if not included:
            reasons = {item["exclusion_reason"] for item in contributions if item["exclusion_reason"]}
            missing = "STALE_QUOTES" if reasons and reasons <= {"STALE_QUOTE"} else "NO_CONNECTED_INDEPENDENT_FAIR_PRICE"
            return FairPriceResult(
                status="UNAVAILABLE",
                fair_probability=None,
                source_count=0,
                source_dispersion=None,
                quote_timestamp=now.isoformat(),
                mapping_confidence="UNAVAILABLE",
                missing_reason=missing,
                calculation_version=FAIR_PRICE_VERSION,
                contributions=tuple(contributions),
            )
        total_weight = sum(weight for _, weight in included)
        fair = sum(probability * weight for probability, weight in included) / total_weight
        variance = sum(weight * ((probability - fair) ** 2) for probability, weight in included) / total_weight
        dispersion = math.sqrt(variance)
        reliability = _clamp_reliability(len(included), dispersion)
        return FairPriceResult(
            status="AVAILABLE",
            fair_probability=round(fair, 8),
            source_count=len(included),
            source_dispersion=round(dispersion, 8),
            quote_timestamp=(freshest or now).isoformat(),
            mapping_confidence="EXACT",
            missing_reason=None,
            calculation_version=FAIR_PRICE_VERSION,
            contributions=tuple(contributions),
            composite_fair_price=round(fair, 8),
            oldest_included_quote=min(included_timestamps).isoformat(),
            newest_included_quote=max(included_timestamps).isoformat(),
            reliability=round(reliability, 6),
        )


def _clamp_reliability(source_count: int, dispersion: float) -> float:
    source_factor = min(1.0, max(0.25, source_count / 3.0))
    dispersion_factor = max(0.25, min(1.0, 1.0 - dispersion * 5.0))
    return source_factor * dispersion_factor


def composite_snapshot(
    record: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    fingerprint = "::".join(
        (
            str(record["candidate_id"]),
            str(result.get("calculation_version") or FAIR_PRICE_VERSION),
            str(result.get("quote_timestamp")),
            str(result.get("fair_probability")),
        )
    )
    snapshot_id = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    contributions = []
    for item in result.get("contributions") or []:
        source = item.get("source_snapshot") or {}
        contributions.append(
            {
                **item,
                "provider_event_id": source.get("provider_event_id"),
                "provider_market_id": source.get("provider_market_id"),
                "provider_selection_id": source.get("provider_selection_id"),
                "native_odds": source.get("native_odds"),
                "raw_implied_probability": source.get("raw_implied_probability"),
                "no_vig_probability": source.get("no_vig_probability"),
                "contribution_weight": item.get("weight"),
                "quote_freshness": "FRESH" if item.get("included") else None,
            }
        )
    return {
        "snapshot_id": snapshot_id,
        "candidate_id": record["candidate_id"],
        "correlation_id": record["correlation_id"],
        "quote_timestamp": result.get("quote_timestamp") or record["detected_at"],
        "composite_fair_probability": result.get("fair_probability"),
        "source_count": result.get("source_count", 0),
        "source_dispersion": result.get("source_dispersion"),
        "mapping_confidence": result.get("mapping_confidence", "UNAVAILABLE"),
        "status": result.get("status", "UNAVAILABLE"),
        "missing_reason": result.get("missing_reason"),
        "calculation_version": result.get("calculation_version", FAIR_PRICE_VERSION),
        "snapshot": {**result, "fabricated_data": False},
        "contributions": contributions,
        "created_at": record["detected_at"],
    }
