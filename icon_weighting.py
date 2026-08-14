from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence

from market_quotes import NormalizedMarketQuote


class ProviderRole(str, Enum):
    PRICE_DISCOVERY = "price_discovery"
    CONFIRMATION = "confirmation"
    EXECUTION = "execution"


class ExecutionSourcePolicy(str, Enum):
    EXCLUDE = "exclude"
    ALLOW = "allow"
    LEAVE_ONE_OUT = "leave_one_out"


class MissingSourceBehavior(str, Enum):
    REJECT = "reject"
    PENALIZE = "penalize"
    ALLOW = "allow"


@dataclass(frozen=True)
class MarketWeightingProfile:
    profile_id: str
    sport: str
    league: str | None
    market_family: str
    market_type: str | None = None
    period: str | None = None
    source_base_weights: Mapping[str, float] = field(default_factory=dict)
    critical_sources: frozenset[str] = frozenset()
    minimum_sources: int = 1
    max_quote_age: int = 180
    max_dispersion: float | None = None
    missing_source_behavior: MissingSourceBehavior = MissingSourceBehavior.REJECT
    execution_source_policy: ExecutionSourcePolicy = ExecutionSourcePolicy.LEAVE_ONE_OUT
    provider_roles: Mapping[str, ProviderRole] = field(default_factory=dict)

    @classmethod
    def from_config(cls, value: Mapping[str, object]) -> "MarketWeightingProfile":
        """Load a profile from configuration without embedding production weights."""
        roles = {
            str(provider).lower(): (
                role if isinstance(role, ProviderRole) else ProviderRole(str(role))
            )
            for provider, role in dict(value.get("provider_roles") or {}).items()
        }
        return cls(
            profile_id=str(value["profile_id"]),
            sport=str(value["sport"]),
            league=None if value.get("league") is None else str(value["league"]),
            market_family=str(value["market_family"]),
            market_type=None if value.get("market_type") is None else str(value["market_type"]),
            period=None if value.get("period") is None else str(value["period"]),
            source_base_weights={
                str(provider).lower(): float(weight)
                for provider, weight in dict(value.get("source_base_weights") or {}).items()
            },
            critical_sources=frozenset(
                str(provider).lower()
                for provider in value.get("critical_sources") or ()
            ),
            minimum_sources=max(1, int(value.get("minimum_sources") or 1)),
            max_quote_age=max(1, int(value.get("max_quote_age") or 180)),
            max_dispersion=(
                None
                if value.get("max_dispersion") is None
                else float(value["max_dispersion"])
            ),
            missing_source_behavior=MissingSourceBehavior(
                str(value.get("missing_source_behavior") or MissingSourceBehavior.REJECT.value)
            ),
            execution_source_policy=ExecutionSourcePolicy(
                str(value.get("execution_source_policy") or ExecutionSourcePolicy.LEAVE_ONE_OUT.value)
            ),
            provider_roles=roles,
        )


@dataclass(frozen=True)
class WeightingFactors:
    sport_market_trust: float = 1.0
    freshness: float = 1.0
    maturity: float = 1.0
    provider_reliability: float = 1.0
    mapping_confidence: float = 1.0
    agreement_quality: float = 1.0

    @property
    def multiplier(self) -> float:
        values = (
            self.sport_market_trust,
            self.freshness,
            self.maturity,
            self.provider_reliability,
            self.mapping_confidence,
            self.agreement_quality,
        )
        result = 1.0
        for value in values:
            result *= max(0.0, float(value))
        return result


@dataclass(frozen=True)
class WeightingContext:
    quote_age_seconds: float | None = None
    freshness_multiplier: float | None = None
    maturity_score: float | None = None
    market_limit: float | None = None
    limit_history: Sequence[float] | None = None
    provider_reliability: float | None = None
    agreement_quality: float | None = None
    sport_market_trust: float | None = None


@dataclass(frozen=True)
class EffectiveSourceWeight:
    provider: str
    role: ProviderRole
    base_weight: float
    factors: WeightingFactors
    effective_weight: float


class WeightingProfileRegistry:
    def __init__(self, profiles: Sequence[MarketWeightingProfile] = ()) -> None:
        self._profiles = {profile.profile_id: profile for profile in profiles}

    def register(self, profile: MarketWeightingProfile) -> None:
        self._profiles[profile.profile_id] = profile

    def get(self, profile_id: str) -> MarketWeightingProfile:
        return self._profiles[profile_id]

    def match(
        self,
        *,
        sport: str,
        league: str | None,
        market_family: str,
        period: str | None,
        market_type: str | None = None,
    ) -> MarketWeightingProfile | None:
        candidates = [
            profile
            for profile in self._profiles.values()
            if profile.sport.lower() == sport.lower()
            and profile.market_family.lower() == market_family.lower()
            and (
                profile.market_type is None
                or (market_type and profile.market_type.lower() == market_type.lower())
            )
            and (profile.league is None or (league and profile.league.lower() == league.lower()))
            and (profile.period is None or (period and profile.period.lower() == period.lower()))
        ]
        return max(
            candidates,
            key=lambda row: (
                row.league is not None,
                row.market_type is not None,
                row.period is not None,
            ),
            default=None,
        )


class IconWeightingEngine:
    """Computes source weights without inventing feed-specific maturity curves."""

    def effective_weight(
        self,
        quote: NormalizedMarketQuote,
        profile: MarketWeightingProfile,
        context: WeightingContext | None = None,
    ) -> EffectiveSourceWeight:
        context = context or WeightingContext()
        provider = quote.provider.lower()
        role = profile.provider_roles.get(provider, ProviderRole.CONFIRMATION)
        base_weight = max(0.0, float(profile.source_base_weights.get(provider, 0.0)))
        # Quote expiry is a guardrail, not an invented decay curve. A future
        # profile/feed may provide an explicit freshness multiplier.
        freshness = (
            max(0.0, float(context.freshness_multiplier))
            if context.freshness_multiplier is not None
            else 1.0
        )
        if (
            context.quote_age_seconds is not None
            and profile.max_quote_age > 0
            and context.quote_age_seconds > profile.max_quote_age
        ):
            freshness = 0.0
        factors = WeightingFactors(
            sport_market_trust=context.sport_market_trust if context.sport_market_trust is not None else 1.0,
            freshness=freshness,
            maturity=context.maturity_score if context.maturity_score is not None else 1.0,
            provider_reliability=context.provider_reliability if context.provider_reliability is not None else 1.0,
            mapping_confidence=quote.mapping_confidence if quote.mapping_confidence is not None else 1.0,
            agreement_quality=context.agreement_quality if context.agreement_quality is not None else 1.0,
        )
        return EffectiveSourceWeight(
            provider=provider,
            role=role,
            base_weight=base_weight,
            factors=factors,
            effective_weight=base_weight * factors.multiplier,
        )

    def eligible_for_fair_value(
        self,
        *,
        provider: str,
        execution_provider: str | None,
        profile: MarketWeightingProfile,
    ) -> bool:
        key = provider.lower()
        role = profile.provider_roles.get(key, ProviderRole.CONFIRMATION)
        if role is not ProviderRole.EXECUTION:
            return True
        if profile.execution_source_policy is ExecutionSourcePolicy.EXCLUDE:
            return False
        if profile.execution_source_policy is ExecutionSourcePolicy.LEAVE_ONE_OUT:
            return execution_provider is None or key != execution_provider.lower()
        return True

    def missing_source_multiplier(
        self, present_sources: set[str], profile: MarketWeightingProfile
    ) -> float:
        present = {item.lower() for item in present_sources}
        critical = {item.lower() for item in profile.critical_sources}
        missing = critical - present
        source_shortfall = max(0, profile.minimum_sources - len(present))
        if not missing and source_shortfall == 0:
            return 1.0
        if profile.missing_source_behavior is MissingSourceBehavior.REJECT:
            return 0.0
        if profile.missing_source_behavior is MissingSourceBehavior.PENALIZE:
            required_count = max(profile.minimum_sources, len(critical), 1)
            missing_count = max(len(missing), source_shortfall)
            return max(0.0, 1.0 - missing_count / required_count)
        return 1.0
