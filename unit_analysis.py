from __future__ import annotations

import math
import statistics
from dataclasses import dataclass


ALLOWED_MULTIPLIERS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4, 5, 6, 8, 10]


@dataclass(frozen=True)
class UnitEstimate:
    wallet_address: str
    wallet_label: str
    estimated_base_unit: float | None
    estimated_base_unit_label: str
    confidence: str
    sample_size: int
    source: str
    matched_samples: int
    notes: str


def round_to_display_unit(value: float) -> float:
    if value < 100:
        return round(value / 5) * 5
    if value < 500:
        return round(value / 10) * 10
    return round(value / 25) * 25


def amount_to_units(amount: float, base_unit: float | None) -> float | None:
    if not base_unit or base_unit <= 0:
        return None
    return amount / base_unit


def estimate_unit_size(
    wallet_address: str,
    wallet_label: str,
    samples: list[float],
    manual_override: float | None = None,
) -> UnitEstimate:
    if manual_override:
        return UnitEstimate(
            wallet_address=wallet_address,
            wallet_label=wallet_label,
            estimated_base_unit=float(manual_override),
            estimated_base_unit_label=f"${float(manual_override):,.0f}",
            confidence="manual",
            sample_size=len(samples),
            source="wallets.json",
            matched_samples=len(samples),
            notes="Manual base_unit override from wallets.json",
        )

    clean_samples = [float(sample) for sample in samples if sample and sample > 0]
    if len(clean_samples) < 3:
        return UnitEstimate(
            wallet_address=wallet_address,
            wallet_label=wallet_label,
            estimated_base_unit=None,
            estimated_base_unit_label="Insufficient data to estimate unit size",
            confidence="insufficient",
            sample_size=len(clean_samples),
            source="recent sports trades",
            matched_samples=0,
            notes="Need at least 3 meaningful sports trade samples",
        )

    median = statistics.median(clean_samples)
    minimum_threshold = max(25.0, median * 0.15)
    meaningful = [sample for sample in clean_samples if sample >= minimum_threshold]
    if len(meaningful) < 3:
        return UnitEstimate(
            wallet_address=wallet_address,
            wallet_label=wallet_label,
            estimated_base_unit=None,
            estimated_base_unit_label="Insufficient data to estimate unit size",
            confidence="insufficient",
            sample_size=len(meaningful),
            source="recent sports trades",
            matched_samples=0,
            notes="Most recent trades look too small or inconsistent to infer a base unit",
        )

    best_score = float("-inf")
    best_candidate = None
    best_matches = 0
    best_error = 1.0

    for sample in meaningful:
        for multiplier in ALLOWED_MULTIPLIERS:
            candidate = sample / multiplier
            if candidate <= 0:
                continue

            errors: list[float] = []
            matches = 0
            for observed in meaningful:
                nearest = min(ALLOWED_MULTIPLIERS, key=lambda allowed: abs(observed - (allowed * candidate)))
                expected = nearest * candidate
                rel_error = abs(observed - expected) / max(observed, candidate)
                errors.append(rel_error)
                if rel_error <= 0.2:
                    matches += 1

            median_error = statistics.median(errors)
            variance_penalty = statistics.pstdev(errors) if len(errors) > 1 else 0.0
            median_multiplier = statistics.median(meaningful) / candidate
            multiplier_penalty = abs(median_multiplier - 1.5) * 0.2
            score = matches - (median_error * 6) - variance_penalty - multiplier_penalty
            if score > best_score:
                best_score = score
                best_candidate = candidate
                best_matches = matches
                best_error = median_error

    if not best_candidate or best_matches < 3 or best_matches / len(meaningful) < 0.5:
        return UnitEstimate(
            wallet_address=wallet_address,
            wallet_label=wallet_label,
            estimated_base_unit=None,
            estimated_base_unit_label="Insufficient data to estimate unit size",
            confidence="insufficient",
            sample_size=len(meaningful),
            source="recent sports trades",
            matched_samples=best_matches,
            notes="Recent sports trades do not cluster tightly enough around repeatable unit sizes",
        )

    estimated = round_to_display_unit(best_candidate)
    if estimated <= 0:
        estimated = round_to_display_unit(max(best_candidate, 1))

    if best_matches >= 6 and best_error <= 0.08:
        confidence = "high"
    elif best_matches >= 4 and best_error <= 0.14:
        confidence = "medium"
    else:
        confidence = "low"

    return UnitEstimate(
        wallet_address=wallet_address,
        wallet_label=wallet_label,
        estimated_base_unit=estimated,
        estimated_base_unit_label=f"${estimated:,.0f}",
        confidence=confidence,
        sample_size=len(meaningful),
        source="recent sports trades",
        matched_samples=best_matches,
        notes=(
            "Estimated from repeated sports stake sizes using clustered trade amounts and quarter-unit style sizing. "
            "Tiny test trades and obvious outliers are filtered out."
        ),
    )
