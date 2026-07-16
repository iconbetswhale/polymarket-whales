from __future__ import annotations

import hashlib
import json
import math
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


RELEASE1_MIGRATION_VERSION = "001_release1_measurement_foundation"
CANDIDATE_LEDGER_VERSION = "candidate-ledger-v1"
TRADE_SCORING_VERSION = "confidence-v2-legacy"
FAIR_PRICE_VERSION = "fair-price-interface-v1-unavailable"
KELLY_VERSION = "kelly-v1-legacy"
RISK_POLICY_VERSION = "risk-policy-v1-legacy"
WALLET_REGISTRY_VERSION = "wallet-registry-v1"
EXECUTION_PLAN_VERSION = "execution-snapshot-v1"
COMPOSITE_CLV_VERSION = "composite-clv-v1-unavailable"
STANDARDIZED_PASSED_STAKE = 100.0


class CandidateDecision(str, Enum):
    APPROVED_STANDARD = "APPROVED_STANDARD"
    APPROVED_DISCOVERY = "APPROVED_DISCOVERY"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    PASSED = "PASSED"
    INVALID = "INVALID"


class CandidateReason(str, Enum):
    NO_INDEPENDENT_FAIR_PRICE = "NO_INDEPENDENT_FAIR_PRICE"
    NO_POSITIVE_COMPOSITE_EDGE = "NO_POSITIVE_COMPOSITE_EDGE"
    SLIPPAGE_ABOVE_LIMIT = "SLIPPAGE_ABOVE_LIMIT"
    MAX_AVERAGE_PRICE_EXCEEDED = "MAX_AVERAGE_PRICE_EXCEEDED"
    INSUFFICIENT_EXECUTABLE_DEPTH = "INSUFFICIENT_EXECUTABLE_DEPTH"
    ORDER_BOOK_INSTABILITY = "ORDER_BOOK_INSTABILITY"
    STRONG_OPPOSING_SPECIALIST = "STRONG_OPPOSING_SPECIALIST"
    MULTIPLE_OPPOSING_SPECIALISTS = "MULTIPLE_OPPOSING_SPECIALISTS"
    CORRELATION_CAP_EXCEEDED = "CORRELATION_CAP_EXCEEDED"
    DAILY_EXPOSURE_CAP_EXCEEDED = "DAILY_EXPOSURE_CAP_EXCEEDED"
    MARKET_MAPPING_UNCERTAIN = "MARKET_MAPPING_UNCERTAIN"
    SETTLEMENT_RULES_UNCERTAIN = "SETTLEMENT_RULES_UNCERTAIN"
    MATERIAL_NEWS_UNRESOLVED = "MATERIAL_NEWS_UNRESOLVED"
    EVENT_ALREADY_STARTED = "EVENT_ALREADY_STARTED"
    PROVIDER_DATA_UNAVAILABLE = "PROVIDER_DATA_UNAVAILABLE"
    BELOW_WALLET_ACTIONABLE_THRESHOLD = "BELOW_WALLET_ACTIONABLE_THRESHOLD"
    RESEARCH_ONLY_NON_CATEGORY = "RESEARCH_ONLY_NON_CATEGORY"
    RESEARCH_ONLY_CONTRADICTING = "RESEARCH_ONLY_CONTRADICTING"
    INVALID_EVENT_TIME = "INVALID_EVENT_TIME"
    NOT_TODAY = "NOT_TODAY"
    MARKET_NOT_ACTIONABLE = "MARKET_NOT_ACTIONABLE"
    MISSING_BANKROLL = "MISSING_BANKROLL"
    MISSING_ENTRY_PRICE = "MISSING_ENTRY_PRICE"
    INVALID_PROBABILITY_INPUT = "INVALID_PROBABILITY_INPUT"
    ZERO_KELLY = "ZERO_KELLY"
    SYNC_INCOMPLETE = "SYNC_INCOMPLETE"
    MISSING_LEAD_SHARP = "MISSING_LEAD_SHARP"
    RESEARCH_CLASSIFICATION = "RESEARCH_CLASSIFICATION"
    LEGACY_FILTER_REJECTION = "LEGACY_FILTER_REJECTION"
    APPROVED_BY_LEGACY_MODEL = "APPROVED_BY_LEGACY_MODEL"


KNOWN_REASONS = {item.value for item in CandidateReason}
RESEARCH_CLASSIFICATIONS = {
    "CONTRADICTING_SHARPS",
    "SHARP_NON_CATEGORY",
    "CONTRADICTING_NON_CATEGORY",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any) -> str:
    return str(value or "").strip().lower()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def stable_hash(*parts: Any) -> str:
    return hashlib.sha256("::".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()


def normalize_reason(reason: Any) -> str:
    value = str(reason or "").strip().upper().replace(" ", "_").replace("-", "_")
    aliases = {
        "SLIPPAGE_ABOVE_MAX": CandidateReason.SLIPPAGE_ABOVE_LIMIT.value,
        "MISSING_EXECUTABLE_PRICE": CandidateReason.PROVIDER_DATA_UNAVAILABLE.value,
        "MISSING_SHARP_REFERENCE_PRICE": CandidateReason.PROVIDER_DATA_UNAVAILABLE.value,
        "UNRESOLVED_TRADE_CATEGORY": CandidateReason.MARKET_MAPPING_UNCERTAIN.value,
        "TIED_SHARPS": CandidateReason.STRONG_OPPOSING_SPECIALIST.value,
        "CONTRADICTING_SIDE_MAJORITY": CandidateReason.MULTIPLE_OPPOSING_SPECIALISTS.value,
        "INSUFFICIENT_AGREEING_MAJORITY": CandidateReason.STRONG_OPPOSING_SPECIALIST.value,
        "SINGLE_NON_CATEGORY_WALLET": CandidateReason.RESEARCH_ONLY_NON_CATEGORY.value,
        "CONTRADICTING_SHARPS_RESEARCH_ONLY": CandidateReason.RESEARCH_ONLY_CONTRADICTING.value,
        "NON_CATEGORY_CONSENSUS_RESEARCH_ONLY": CandidateReason.RESEARCH_ONLY_NON_CATEGORY.value,
        "CONTRADICTING_NON_CATEGORY_RESEARCH_ONLY": CandidateReason.RESEARCH_ONLY_CONTRADICTING.value,
    }
    return aliases.get(value, value if value in KNOWN_REASONS else CandidateReason.LEGACY_FILTER_REJECTION.value)


def candidate_identity(source: dict[str, Any]) -> dict[str, str]:
    validation = source.get("validation_ids") or {}
    event_id = _clean(validation.get("event_id") or source.get("event_id") or source.get("event_slug"))
    market_id = _clean(validation.get("condition_id") or source.get("condition_id") or source.get("market_id") or source.get("canonical_market_key"))
    outcome_id = _clean(validation.get("outcome_token_id") or source.get("outcome_id") or source.get("clob_token_id") or source.get("canonical_side_key"))
    period = _clean(source.get("period") or source.get("period_id"))
    line = str(source.get("market_line") or source.get("line") or "").strip()
    provider = _clean(source.get("provider") or "polymarket")
    settlement_scope = _clean(source.get("settlement_scope"))
    settlement_rules = _clean(source.get("settlement_rules"))
    return {
        "canonical_event_id": event_id,
        "canonical_market_id": market_id,
        "canonical_outcome_id": outcome_id,
        "period": period,
        "market_line": line,
        "provider": provider,
        "settlement_scope": settlement_scope,
        "settlement_rules": settlement_rules,
    }


def complete_identity(identity: dict[str, str]) -> bool:
    return bool(identity["canonical_event_id"] and identity["canonical_market_id"] and identity["canonical_outcome_id"] and identity["provider"])


def candidate_id(identity: dict[str, str], recommendation_version: str) -> str:
    return stable_hash(*(identity[key] for key in (
        "canonical_event_id", "canonical_market_id", "canonical_outcome_id", "period",
        "market_line", "provider", "settlement_scope", "settlement_rules",
    )), recommendation_version)


def correlation_id(identity: dict[str, str]) -> str:
    return "corr_" + stable_hash(identity["canonical_event_id"], identity["period"], identity["settlement_scope"])[:24]


def decision_for_evaluation(play: dict[str, Any], evaluation: dict[str, Any]) -> tuple[CandidateDecision, list[str]]:
    classification = str(play.get("tradeClassification") or play.get("trade_classification") or "STANDARD")
    rejection = evaluation.get("model_tracker_rejection_reason")
    if classification in RESEARCH_CLASSIFICATIONS:
        reasons = [
            CandidateReason.RESEARCH_ONLY_CONTRADICTING.value
            if "CONTRADICTING" in classification
            else CandidateReason.RESEARCH_ONLY_NON_CATEGORY.value
        ]
        return CandidateDecision.RESEARCH_ONLY, reasons
    if evaluation.get("model_tracker_eligible") is True:
        return CandidateDecision.APPROVED_STANDARD, [CandidateReason.APPROVED_BY_LEGACY_MODEL.value]
    reason = normalize_reason(rejection)
    invalid = reason in {
        CandidateReason.INVALID_EVENT_TIME.value,
        CandidateReason.MARKET_MAPPING_UNCERTAIN.value,
        CandidateReason.SETTLEMENT_RULES_UNCERTAIN.value,
    }
    return (CandidateDecision.INVALID if invalid else CandidateDecision.PASSED), [reason]


def execution_snapshot(play: dict[str, Any], recommendation: dict[str, Any]) -> dict[str, Any]:
    orderbook = play.get("orderbook") or {}
    bids = orderbook.get("bids") or []
    asks = orderbook.get("asks") or []
    best_bid = _finite((bids[0] or {}).get("price")) if bids else None
    best_ask = _finite((asks[0] or {}).get("price")) if asks else None
    spread = best_ask - best_bid if best_ask is not None and best_bid is not None else None
    return {
        "current_executable_entry": recommendation.get("effective_entry_price"),
        "sharp_reference_entry": recommendation.get("sharp_reference_entry_price") or play.get("sharp_reference_entry_price"),
        "current_bid": best_bid,
        "current_ask": best_ask,
        "spread": spread,
        "available_depth": sum((_finite(level.get("price")) or 0) * (_finite(level.get("size")) or 0) for level in asks),
        "current_slippage": recommendation.get("unfavorable_slippage_pct"),
        "orderbook_levels_used": recommendation.get("orderbook_levels_used"),
        "liquidity_limited": recommendation.get("liquidity_limited"),
        "unfilled_amount": recommendation.get("unfilled_amount"),
        "recommended_amount": recommendation.get("recommended_amount"),
        "recommended_shares": recommendation.get("recommended_shares"),
        "quote_timestamp": orderbook.get("timestamp"),
        "fees_included": recommendation.get("fees_included"),
    }


def build_candidate_record(play: dict[str, Any], evaluation: dict[str, Any], detected_at: str | None = None) -> dict[str, Any]:
    detected_at = detected_at or utc_now()
    recommendation = evaluation.get("recommendation") or {}
    identity = candidate_identity(play)
    recommendation_version = str(recommendation.get("recommendation_version") or "v1")
    decision, reasons = decision_for_evaluation(play, evaluation)
    if not complete_identity(identity):
        decision = CandidateDecision.INVALID
        reasons = [CandidateReason.MARKET_MAPPING_UNCERTAIN.value]
    cid = candidate_id(identity, recommendation_version)
    corr = correlation_id(identity)
    execution = execution_snapshot(play, recommendation)
    snapshot = {
        "candidate_id": cid,
        "correlation_id": corr,
        **identity,
        "detected_at": detected_at,
        "event_start_time": play.get("event_date_et"),
        "provider_event_slug": play.get("event_slug") or (play.get("validation_ids") or {}).get("event_slug"),
        "sport": play.get("category"),
        "league": play.get("league"),
        "event": play.get("event_title"),
        "market": play.get("market_title"),
        "selection": play.get("outcome"),
        "wallet_signal_source": play.get("source"),
        "primary_sharp": play.get("primary_sharp") or play.get("primary_lead_wallet_id"),
        "lead_sharps": play.get("lead_wallet_ids") or [],
        "supporting_sharps": play.get("supporting_wallet_ids") or [],
        "contradicting_sharps": play.get("contradicting_wallets") or [],
        "raw_agreeing_sharp_count": play.get("rawAgreeingSharpCount") or play.get("agreeing_wallet_count"),
        "independent_sharp_equivalent_count": play.get("weighted_sharp_count"),
        "lead_sharp_count": play.get("lead_sharp_count"),
        "supporting_sharp_count": play.get("supporting_sharp_count"),
        "contradicting_sharp_count": play.get("rawContradictingSharpCount"),
        "wallet_positions": play.get("supporting_wallets") or [],
        "trader_category_statistics": (play.get("evidence_inputs") or {}).get("category_details") or [],
        "initial_trade_quality_components": play.get("score_breakdown") or {},
        "decision": decision.value,
        "reason_codes": reasons,
        "execution_snapshot": execution,
        "versions": version_registry(recommendation_version),
        "composite_price": {"status": "UNAVAILABLE", "missing_reason": "NO_CONNECTED_INDEPENDENT_COMPOSITE_PROVIDER"},
    }
    return {
        "candidate_id": cid,
        "correlation_id": corr,
        **identity,
        "detected_at": detected_at,
        "event_start_time": play.get("event_date_et"),
        "sport": play.get("category"),
        "league": play.get("league"),
        "event_title": play.get("event_title"),
        "market_title": play.get("market_title"),
        "selection": play.get("outcome"),
        "decision": decision.value,
        "reason_codes": reasons,
        "execution_snapshot": execution,
        "candidate_snapshot": snapshot,
        "versions": version_registry(recommendation_version),
        "composite_price_status": "UNAVAILABLE",
        "composite_price_missing_reason": "NO_CONNECTED_INDEPENDENT_COMPOSITE_PROVIDER",
    }


def build_exclusion_record(exclusion: dict[str, Any], detected_at: str | None = None) -> dict[str, Any] | None:
    detected_at = detected_at or utc_now()
    identity = candidate_identity(exclusion)
    if not complete_identity(identity):
        return None
    reason = normalize_reason(exclusion.get("reason"))
    recommendation_version = "v2"
    cid = candidate_id(identity, recommendation_version)
    corr = correlation_id(identity)
    if reason == CandidateReason.MARKET_MAPPING_UNCERTAIN.value:
        decision = CandidateDecision.INVALID
    elif reason in {
        CandidateReason.RESEARCH_ONLY_NON_CATEGORY.value,
        CandidateReason.RESEARCH_ONLY_CONTRADICTING.value,
    }:
        decision = CandidateDecision.RESEARCH_ONLY
    else:
        decision = CandidateDecision.PASSED
    snapshot = {
        "candidate_id": cid,
        "correlation_id": corr,
        **identity,
        "detected_at": detected_at,
        "event_start_time": exclusion.get("event_start_time"),
        "sport": exclusion.get("category") or exclusion.get("canonical_category_id"),
        "league": exclusion.get("league"),
        "event": exclusion.get("event_title"),
        "provider_event_slug": exclusion.get("event_slug"),
        "market": exclusion.get("market_title"),
        "selection": exclusion.get("outcome"),
        "wallet_signal_source": "pre_eligibility_exclusion",
        "wallets": exclusion.get("wallets") or [],
        "decision": decision.value,
        "reason_codes": [reason],
        "legacy_exclusion": exclusion,
        "execution_snapshot": {},
        "versions": version_registry(recommendation_version),
        "composite_price": {"status": "UNAVAILABLE", "missing_reason": "NO_CONNECTED_INDEPENDENT_COMPOSITE_PROVIDER"},
    }
    return {
        "candidate_id": cid,
        "correlation_id": corr,
        **identity,
        "detected_at": detected_at,
        "event_start_time": exclusion.get("event_start_time"),
        "sport": exclusion.get("category") or exclusion.get("canonical_category_id"),
        "league": exclusion.get("league"),
        "event_title": exclusion.get("event_title"),
        "market_title": exclusion.get("market_title"),
        "selection": exclusion.get("outcome"),
        "decision": decision.value,
        "reason_codes": [reason],
        "execution_snapshot": {},
        "candidate_snapshot": snapshot,
        "versions": version_registry(recommendation_version),
        "composite_price_status": "UNAVAILABLE",
        "composite_price_missing_reason": "NO_CONNECTED_INDEPENDENT_COMPOSITE_PROVIDER",
    }


def version_registry(recommendation_version: str = "v2") -> dict[str, str]:
    return {
        "candidate_ledger": CANDIDATE_LEDGER_VERSION,
        "trade_scoring": TRADE_SCORING_VERSION,
        "recommendation": recommendation_version,
        "fair_price": FAIR_PRICE_VERSION,
        "kelly": KELLY_VERSION,
        "risk_policy": RISK_POLICY_VERSION,
        "wallet_registry": WALLET_REGISTRY_VERSION,
        "execution_plan": EXECUTION_PLAN_VERSION,
        "composite_clv": COMPOSITE_CLV_VERSION,
    }


def migration_sql(dialect: str) -> str:
    suffix = "postgres" if dialect == "postgres" else "sqlite"
    path = Path(__file__).resolve().parent / "migrations" / f"{RELEASE1_MIGRATION_VERSION}.{suffix}.sql"
    return path.read_text(encoding="utf-8")


@dataclass(frozen=True)
class CompositeQuote:
    provider: str
    status: str
    quote_timestamp: str | None = None
    fair_probability: float | None = None
    missing_reason: str | None = None
    provider_event_id: str | None = None
    provider_market_id: str | None = None
    provider_selection_id: str | None = None
    native_odds: str | None = None
    decimal_odds: float | None = None
    raw_implied_probability: float | None = None
    no_vig_probability: float | None = None
    liquidity: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CompositePriceProvider(ABC):
    provider_key: str

    @abstractmethod
    def quote(self, candidate: dict[str, Any]) -> CompositeQuote:
        raise NotImplementedError

    @abstractmethod
    def health(self) -> dict[str, Any]:
        raise NotImplementedError


class UnavailableCompositePriceProvider(CompositePriceProvider):
    def __init__(self, provider_key: str, reason: str = "PROVIDER_NOT_CONFIGURED") -> None:
        self.provider_key = provider_key
        self.reason = reason

    def quote(self, candidate: dict[str, Any]) -> CompositeQuote:
        return CompositeQuote(provider=self.provider_key, status="UNAVAILABLE", missing_reason=self.reason)

    def health(self) -> dict[str, Any]:
        return {"provider": self.provider_key, "status": "UNAVAILABLE", "reason": self.reason, "fabricated_data": False}


class CompositePriceProviderRegistry:
    def __init__(self, providers: Iterable[CompositePriceProvider]) -> None:
        self.providers = tuple(providers)

    @classmethod
    def release1_default(cls) -> "CompositePriceProviderRegistry":
        return cls(UnavailableCompositePriceProvider(key) for key in (
            "pinnacle", "circa", "bookmaker", "betonline", "novig", "prophetx", "4cx", "kalshi"
        ))

    def health(self) -> list[dict[str, Any]]:
        return [provider.health() for provider in self.providers]

    def quotes(self, candidate: dict[str, Any]) -> list[dict[str, Any]]:
        return [provider.quote(candidate).to_dict() for provider in self.providers]


def decision_id(record: dict[str, Any]) -> str:
    return stable_hash(record["candidate_id"], record["decision"], _json(record["reason_codes"]), record["versions"]["recommendation"])


def model_version_rows() -> list[dict[str, str]]:
    now = utc_now()
    rows = []
    for component, version in version_registry().items():
        status = "OBSERVATIONAL" if component in {"candidate_ledger", "fair_price", "composite_clv", "execution_plan"} else "ACTIVE_LEGACY"
        rows.append({
            "version_key": f"{component}:{version}",
            "component": component,
            "version": version,
            "status": status,
            "description": "Release 1 measurement foundation; live decision behavior unchanged.",
            "registered_at": now,
        })
    return rows


def unavailable_composite_snapshot(
    record: dict[str, Any], provider_health: list[dict[str, Any]]
) -> dict[str, Any]:
    timestamp = record["detected_at"]
    snapshot_id = stable_hash(
        record["candidate_id"], FAIR_PRICE_VERSION, "UNAVAILABLE"
    )
    contributions = [
        {
            "provider": item["provider"],
            "included": False,
            "exclusion_reason": item.get("reason") or "PROVIDER_UNAVAILABLE",
            "source_snapshot": item,
        }
        for item in provider_health
    ]
    return {
        "snapshot_id": snapshot_id,
        "candidate_id": record["candidate_id"],
        "correlation_id": record["correlation_id"],
        "quote_timestamp": timestamp,
        "composite_fair_probability": None,
        "source_count": 0,
        "source_dispersion": None,
        "mapping_confidence": "UNAVAILABLE",
        "status": "UNAVAILABLE",
        "missing_reason": "NO_CONNECTED_INDEPENDENT_COMPOSITE_PROVIDER",
        "calculation_version": FAIR_PRICE_VERSION,
        "snapshot": {
            "status": "UNAVAILABLE",
            "candidate_id": record["candidate_id"],
            "providers": provider_health,
            "fabricated_data": False,
        },
        "contributions": contributions,
        "created_at": timestamp,
    }
