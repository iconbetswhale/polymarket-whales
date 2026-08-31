from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable


DFS_PROBABILITY_VERSION = "dfs-market-consensus-v2-quality-guardrails"
SUPPORTED_DEVIG_METHODS = {"multiplicative", "additive", "power", "shin"}
EXCHANGE_EXECUTION_PROVIDERS = {"novig", "prophetx", "polymarket", "kalshi"}
REFERENCE_PROVIDERS = {"fanduel", "draftkings"}
EXTREME_FAVORITE_ODDS = -250.0
LOW_LIQUIDITY_FAVORITE_ODDS = -175.0
MIN_EXECUTABLE_LIQUIDITY = 25.0
MAX_REFERENCE_PROBABILITY_GAP = 0.10
MAX_TWO_WAY_OVERROUND = 1.30
ICONLABS_DFS_WEIGHTS = {
    "fanduel": 30.0,
    "novig": 20.0,
    "prophetx": 15.0,
    "draftkings": 10.0,
    "pinnacle": 10.0,
    "circa": 7.0,
    "kalshi": 5.0,
    "polymarket": 3.0,
}


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def american_to_probability(odds: Any) -> float | None:
    value = _finite(odds)
    if value is None or value == 0:
        return None
    probability = 100.0 / (value + 100.0) if value > 0 else -value / (-value + 100.0)
    return probability if 0.0 < probability < 1.0 else None


def probability_to_american(probability: Any) -> float | None:
    value = _finite(probability)
    if value is None or not 0.0 < value < 1.0:
        return None
    odds = -100.0 * value / (1.0 - value) if value >= 0.5 else 100.0 * (1.0 - value) / value
    return round(odds, 2)


def devig_two_way(over_odds: Any, under_odds: Any, method: str = "power") -> tuple[float, float] | None:
    """Return fair Over/Under probabilities from one paired two-way market."""
    selected_method = str(method or "power").strip().lower()
    if selected_method not in SUPPORTED_DEVIG_METHODS:
        raise ValueError(f"Unsupported devig method: {method}")
    over = american_to_probability(over_odds)
    under = american_to_probability(under_odds)
    if over is None or under is None:
        return None
    overround = over + under
    if overround <= 0:
        return None
    if selected_method == "multiplicative":
        return over / overround, under / overround
    if selected_method in {"additive", "shin"}:
        margin = (overround - 1.0) / 2.0
        fair_over = over - margin
        fair_under = under - margin
        if min(fair_over, fair_under) <= 0:
            return None
        total = fair_over + fair_under
        return fair_over / total, fair_under / total

    # Power devig: find k such that over**k + under**k = 1.
    low, high = 0.01, 20.0
    for _ in range(100):
        midpoint = (low + high) / 2.0
        total = over**midpoint + under**midpoint
        if total > 1.0:
            low = midpoint
        else:
            high = midpoint
    exponent = (low + high) / 2.0
    fair_over, fair_under = over**exponent, under**exponent
    total = fair_over + fair_under
    return fair_over / total, fair_under / total


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
class DfsProbabilityResult:
    status: str
    hit_probability: float | None
    hit_rate_percent: float | None
    fair_american_odds: float | None
    source_count: int
    source_dispersion: float | None
    reliability: float
    target_line: float
    side: str
    devig_method: str
    calculation_version: str
    contributions: tuple[dict[str, Any], ...]
    missing_reason: str | None = None
    breakeven_probability: float | None = None
    edge_probability: float | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["contributions"] = list(self.contributions)
        return payload


class DfsProbabilityEngine:
    """Build a transparent DFS hit rate from paired, exact-line market prices."""

    def __init__(
        self,
        provider_weights: dict[str, float],
        *,
        devig_method: str = "power",
        max_quote_age_seconds: int = 600,
        freshness_half_life_seconds: int = 300,
        minimum_sources: int = 1,
    ) -> None:
        if str(devig_method).lower() not in SUPPORTED_DEVIG_METHODS:
            raise ValueError(f"Unsupported devig method: {devig_method}")
        self.provider_weights = {
            str(provider).strip().lower(): max(0.0, float(weight))
            for provider, weight in provider_weights.items()
        }
        self.devig_method = str(devig_method).lower()
        self.max_quote_age_seconds = max(1, int(max_quote_age_seconds))
        self.freshness_half_life_seconds = max(1, int(freshness_half_life_seconds))
        self.minimum_sources = max(1, int(minimum_sources))

    def calculate(
        self,
        *,
        target_line: Any,
        side: str,
        quotes: Iterable[dict[str, Any]],
        now: datetime | None = None,
        dfs_breakeven_odds: Any = None,
    ) -> DfsProbabilityResult:
        line = _finite(target_line)
        normalized_side = str(side or "").strip().lower()
        if line is None:
            raise ValueError("target_line must be a finite number")
        if normalized_side not in {"over", "under"}:
            raise ValueError("side must be Over or Under")
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        contributions: list[dict[str, Any]] = []
        included: list[tuple[float, float]] = []

        # One provider gets one vote: keep its freshest exact-line quote.
        freshest_by_provider: dict[str, dict[str, Any]] = {}
        for quote in quotes:
            provider = str(quote.get("provider") or "").strip().lower()
            timestamp = _parse_timestamp(quote.get("quote_timestamp"))
            current = freshest_by_provider.get(provider)
            current_timestamp = _parse_timestamp(current.get("quote_timestamp")) if current else None
            quote_line = _finite(quote.get("line"))
            current_line = _finite(current.get("line")) if current else None
            quote_is_exact = quote_line is not None and math.isclose(quote_line, line, abs_tol=1e-9)
            current_is_exact = current_line is not None and math.isclose(current_line, line, abs_tol=1e-9)
            if (
                current is None
                or (quote_is_exact and not current_is_exact)
                or (
                    quote_is_exact == current_is_exact
                    and timestamp is not None
                    and (current_timestamp is None or timestamp > current_timestamp)
                )
            ):
                freshest_by_provider[provider] = quote

        # FanDuel and DraftKings are the reference check for exchange quotes.
        # Only fresh, exact, genuinely two-way prices can establish that check.
        reference_probabilities: list[tuple[float, float]] = []
        for provider in REFERENCE_PROVIDERS:
            quote = freshest_by_provider.get(provider)
            if not quote:
                continue
            quote_line = _finite(quote.get("line"))
            timestamp = _parse_timestamp(quote.get("quote_timestamp"))
            if quote_line is None or not math.isclose(quote_line, line, abs_tol=1e-9):
                continue
            if timestamp is None or (now - timestamp).total_seconds() > self.max_quote_age_seconds:
                continue
            if quote.get("status") is not None and str(quote.get("status")).upper() != "AVAILABLE":
                continue
            if quote.get("mapping_confidence") is not None and str(quote.get("mapping_confidence")).upper() != "EXACT":
                continue
            fair_pair = devig_two_way(
                quote.get("over_odds"), quote.get("under_odds"), self.devig_method
            )
            if fair_pair is not None:
                reference_probabilities.append(fair_pair)
        reference_pair = (
            (
                sum(pair[0] for pair in reference_probabilities) / len(reference_probabilities),
                sum(pair[1] for pair in reference_probabilities) / len(reference_probabilities),
            )
            if reference_probabilities
            else None
        )

        for provider, quote in freshest_by_provider.items():
            quote_line = _finite(quote.get("line"))
            timestamp = _parse_timestamp(quote.get("quote_timestamp"))
            base_weight = self.provider_weights.get(provider, 0.0)
            exclusion_reason: str | None = None
            fair_pair: tuple[float, float] | None = None
            age_seconds: float | None = None
            reference_divergence: float | None = None
            reported_liquidities = [
                value
                for value in (
                    _finite(quote.get("over_liquidity")),
                    _finite(quote.get("under_liquidity")),
                )
                if value is not None and value >= 0
            ]
            minimum_liquidity = min(reported_liquidities) if reported_liquidities else None
            if quote.get("status") is not None and str(quote.get("status")).upper() != "AVAILABLE":
                exclusion_reason = str(quote.get("missing_reason") or "PROVIDER_UNAVAILABLE")
            elif quote.get("mapping_confidence") is not None and str(quote.get("mapping_confidence")).upper() != "EXACT":
                exclusion_reason = "MARKET_MAPPING_UNCERTAIN"
            elif quote_line is None or not math.isclose(quote_line, line, abs_tol=1e-9):
                exclusion_reason = "LINE_MISMATCH"
            elif timestamp is None:
                exclusion_reason = "MISSING_QUOTE_TIMESTAMP"
            else:
                age_seconds = max(0.0, (now - timestamp).total_seconds())
                if age_seconds > self.max_quote_age_seconds:
                    exclusion_reason = "STALE_QUOTE"
                else:
                    fair_pair = devig_two_way(
                        quote.get("over_odds"), quote.get("under_odds"), self.devig_method
                    )
                    if fair_pair is None:
                        exclusion_reason = "INVALID_TWO_WAY_ODDS"
                    else:
                        over_implied = american_to_probability(quote.get("over_odds"))
                        under_implied = american_to_probability(quote.get("under_odds"))
                        overround = (
                            over_implied + under_implied
                            if over_implied is not None and under_implied is not None
                            else None
                        )
                        if reference_pair is not None:
                            reference_divergence = max(
                                abs(fair_pair[0] - reference_pair[0]),
                                abs(fair_pair[1] - reference_pair[1]),
                            )
                        favorite_price = min(
                            value
                            for value in (
                                _finite(quote.get("over_odds")),
                                _finite(quote.get("under_odds")),
                            )
                            if value is not None
                        )
                        if overround is not None and overround > MAX_TWO_WAY_OVERROUND:
                            exclusion_reason = "EXCESSIVE_TWO_WAY_OVERROUND"
                        elif (
                            provider in EXCHANGE_EXECUTION_PROVIDERS
                            and minimum_liquidity is not None
                            and minimum_liquidity < MIN_EXECUTABLE_LIQUIDITY
                            and favorite_price <= LOW_LIQUIDITY_FAVORITE_ODDS
                        ):
                            exclusion_reason = "LOW_LIQUIDITY_EXTREME_QUOTE"
                        elif (
                            provider in EXCHANGE_EXECUTION_PROVIDERS
                            and favorite_price <= EXTREME_FAVORITE_ODDS
                            and reference_divergence is not None
                            and reference_divergence > MAX_REFERENCE_PROBABILITY_GAP
                        ):
                            exclusion_reason = "MARKET_OUTLIER_AGAINST_REFERENCE"
                    if exclusion_reason is None and base_weight <= 0:
                        # Preserve a valid source probability even when its current
                        # weight is zero. The DFS UI can then apply a newly saved
                        # allocation immediately without waiting for another feed
                        # request, while the aggregate still excludes this source.
                        exclusion_reason = "PROVIDER_WEIGHT_NOT_CONFIGURED"
            probability = None if fair_pair is None else fair_pair[0 if normalized_side == "over" else 1]
            freshness_factor = 0.0 if age_seconds is None else 0.5 ** (age_seconds / self.freshness_half_life_seconds)
            effective_weight = base_weight * freshness_factor if exclusion_reason is None else 0.0
            if exclusion_reason is None and effective_weight > 0 and probability is not None:
                included.append((probability, effective_weight))
            contributions.append(
                {
                    "provider": provider,
                    "included": exclusion_reason is None,
                    "line": quote_line,
                    "over_odds": _finite(quote.get("over_odds")),
                    "under_odds": _finite(quote.get("under_odds")),
                    "over_liquidity": _finite(quote.get("over_liquidity")),
                    "under_liquidity": _finite(quote.get("under_liquidity")),
                    "minimum_liquidity": minimum_liquidity,
                    "reference_probability": (
                        reference_pair[0 if normalized_side == "over" else 1]
                        if reference_pair is not None
                        else None
                    ),
                    "reference_divergence": reference_divergence,
                    "no_vig_probability": probability,
                    "base_weight": base_weight,
                    "freshness_factor": round(freshness_factor, 8),
                    "effective_weight": round(effective_weight, 8),
                    "quote_timestamp": timestamp.isoformat() if timestamp else None,
                    "exclusion_reason": exclusion_reason,
                }
            )

        if len(included) < self.minimum_sources:
            return DfsProbabilityResult(
                status="UNAVAILABLE",
                hit_probability=None,
                hit_rate_percent=None,
                fair_american_odds=None,
                source_count=len(included),
                source_dispersion=None,
                reliability=0.0,
                target_line=line,
                side=normalized_side,
                devig_method=self.devig_method,
                calculation_version=DFS_PROBABILITY_VERSION,
                contributions=tuple(contributions),
                missing_reason="INSUFFICIENT_EXACT_LINE_SOURCES",
            )

        total_weight = sum(weight for _, weight in included)
        probability = sum(value * weight for value, weight in included) / total_weight
        variance = sum(weight * (value - probability) ** 2 for value, weight in included) / total_weight
        dispersion = math.sqrt(variance)
        coverage_weight = sum(
            item["base_weight"] for item in contributions if item["included"]
        ) / max(sum(self.provider_weights.values()), 1e-12)
        source_factor = min(1.0, len(included) / max(3, self.minimum_sources))
        agreement_factor = max(0.0, 1.0 - min(dispersion / 0.10, 1.0))
        reliability = max(0.0, min(1.0, coverage_weight * source_factor * agreement_factor))
        breakeven = american_to_probability(dfs_breakeven_odds)
        return DfsProbabilityResult(
            status="AVAILABLE",
            hit_probability=round(probability, 8),
            hit_rate_percent=round(probability * 100.0, 2),
            fair_american_odds=probability_to_american(probability),
            source_count=len(included),
            source_dispersion=round(dispersion, 8),
            reliability=round(reliability, 6),
            target_line=line,
            side=normalized_side,
            devig_method=self.devig_method,
            calculation_version=DFS_PROBABILITY_VERSION,
            contributions=tuple(contributions),
            breakeven_probability=round(breakeven, 8) if breakeven is not None else None,
            edge_probability=round(probability - breakeven, 8) if breakeven is not None else None,
        )
