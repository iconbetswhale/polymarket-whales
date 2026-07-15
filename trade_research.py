from __future__ import annotations

from dataclasses import dataclass


STANDARD = "STANDARD"
CONTRADICTING_SHARPS = "CONTRADICTING_SHARPS"
SHARP_NON_CATEGORY = "SHARP_NON_CATEGORY"
CONTRADICTING_NON_CATEGORY = "CONTRADICTING_NON_CATEGORY"

RESEARCH_CLASSIFICATIONS = {
    CONTRADICTING_SHARPS,
    SHARP_NON_CATEGORY,
    CONTRADICTING_NON_CATEGORY,
}


@dataclass(frozen=True)
class ResearchPolicy:
    score_min: int
    score_max: int
    probability_adjustment_cap: float
    risk_cap: float
    model_tracker_rejection_reason: str | None


POLICIES = {
    STANDARD: ResearchPolicy(50, 100, 0.12, 0.05, None),
    CONTRADICTING_SHARPS: ResearchPolicy(
        50, 69, 0.02, 0.0075, "CONTRADICTING_SHARPS_RESEARCH_ONLY"
    ),
    SHARP_NON_CATEGORY: ResearchPolicy(
        50, 59, 0.01, 0.005, "NON_CATEGORY_CONSENSUS_RESEARCH_ONLY"
    ),
    CONTRADICTING_NON_CATEGORY: ResearchPolicy(
        50, 54, 0.005, 0.0025, "CONTRADICTING_NON_CATEGORY_RESEARCH_ONLY"
    ),
}


def classify_trade(
    agreeing_count: int, contradicting_count: int, lead_count: int
) -> str | None:
    agreeing = max(0, int(agreeing_count))
    opposing = max(0, int(contradicting_count))
    leads = max(0, int(lead_count))
    has_majority = agreeing >= 2 and agreeing > opposing
    non_category = leads == 0
    if opposing:
        if not has_majority:
            return None
        return (
            CONTRADICTING_NON_CATEGORY
            if non_category
            else CONTRADICTING_SHARPS
        )
    if non_category:
        return SHARP_NON_CATEGORY if agreeing >= 2 else None
    return STANDARD


def classification_fields(
    classification: str,
    agreeing_count: int,
    contradicting_count: int,
) -> dict:
    policy = POLICIES[classification]
    agreeing = max(0, int(agreeing_count))
    opposing = max(0, int(contradicting_count))
    total = agreeing + opposing
    research_only = classification in RESEARCH_CLASSIFICATIONS
    return {
        "tradeClassification": classification,
        "trade_classification": classification,
        "isStandardRecommendation": classification == STANDARD,
        "is_standard_recommendation": classification == STANDARD,
        "isResearchOnly": research_only,
        "is_research_only": research_only,
        "hasContradictingSharps": opposing > 0,
        "has_contradicting_sharps": opposing > 0,
        "isNonCategoryConsensus": classification
        in {SHARP_NON_CATEGORY, CONTRADICTING_NON_CATEGORY},
        "is_non_category_consensus": classification
        in {SHARP_NON_CATEGORY, CONTRADICTING_NON_CATEGORY},
        "modelTrackerEligible": not research_only,
        "model_tracker_eligible": not research_only,
        "modelTrackerRejectionReason": policy.model_tracker_rejection_reason,
        "model_tracker_rejection_reason": policy.model_tracker_rejection_reason,
        "netSharpMajority": agreeing - opposing,
        "net_sharp_majority": agreeing - opposing,
        "majorityRatio": agreeing / total if total else 0.0,
        "majority_ratio": agreeing / total if total else 0.0,
        "confidenceScoreMin": policy.score_min,
        "confidenceScoreMax": policy.score_max,
        "confidenceScoreCap": policy.score_max,
        "probabilityAdjustmentCap": policy.probability_adjustment_cap,
        "riskCap": policy.risk_cap,
    }


def research_confidence(
    classification: str,
    agreeing_count: int,
    contradicting_count: int,
    evidence_quality: float,
) -> int:
    policy = POLICIES[classification]
    if classification == STANDARD:
        raise ValueError("Standard confidence uses the normal consensus bands")
    agreeing = max(0, int(agreeing_count))
    opposing = max(0, int(contradicting_count))
    total = max(1, agreeing + opposing)
    ratio = agreeing / total
    net = max(0, agreeing - opposing)
    quality = max(0.0, min(1.0, float(evidence_quality)))
    majority_quality = max(0.0, min(1.0, ((ratio - 0.5) * 2 * 0.7) + (min(net, 4) / 4 * 0.3)))
    combined = (majority_quality * 0.7 + quality * 0.3) if opposing else quality
    return min(
        policy.score_max,
        max(policy.score_min, round(policy.score_min + (policy.score_max - policy.score_min) * combined)),
    )
