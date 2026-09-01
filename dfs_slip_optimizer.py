"""Payout-aware DFS slip evaluation and constrained portfolio selection.

The evaluator never multiplies same-event legs silently.  Independent slips
use an exact Poisson-binomial distribution; slips with supplied pairwise
correlations use a deterministic Gaussian-copula simulation.  Payout and
settlement confirmations remain explicit execution gates because pick'em apps
can change tables and house rules without notice.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
from statistics import NormalDist
from typing import Iterable, Mapping


DFS_SLIP_CALCULATION_VERSION = "iconlabs-dfs-slip-v1-payout-correlation-gates"
MAX_LEGS = 12
MAX_CANDIDATES = 80
MAX_EVALUATED_SLIPS = 250
SIMULATION_SAMPLES = 20_000


def _probability(value: object, *, percent_allowed: bool = True) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Every leg requires a numeric hit probability.") from exc
    if percent_allowed and parsed > 1.0:
        parsed /= 100.0
    if not math.isfinite(parsed) or not 0.0 < parsed < 1.0:
        raise ValueError("Leg probabilities must be between zero and one.")
    return parsed


def _nonnegative_probability(value: object) -> float:
    if value in {None, ""}:
        return 0.0
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Push and void probabilities must be numeric.") from exc
    if parsed > 1.0:
        parsed /= 100.0
    if not math.isfinite(parsed) or not 0.0 <= parsed < 1.0:
        raise ValueError("Push and void probabilities must be from zero to one.")
    return parsed


def _normalize_leg(raw: Mapping[str, object], index: int) -> dict:
    probability = _probability(
        raw.get("probability", raw.get("hitProbability", raw.get("hit")))
    )
    push_probability = _nonnegative_probability(raw.get("pushProbability"))
    void_probability = _nonnegative_probability(raw.get("voidProbability"))
    if probability + push_probability + void_probability >= 1.0:
        raise ValueError("Hit, push, and void probabilities must sum to less than one.")
    leg_id = str(raw.get("id") or f"leg-{index + 1}").strip()
    if not leg_id:
        raise ValueError("Every leg requires a stable id.")
    return {
        "id": leg_id,
        "player": " ".join(str(raw.get("player") or "").split()),
        "eventId": str(raw.get("eventId") or raw.get("event_id") or "").strip(),
        "team": " ".join(str(raw.get("team") or "").split()),
        "sport": " ".join(str(raw.get("sport") or "").split()),
        "stat": " ".join(str(raw.get("stat") or "").split()),
        "side": " ".join(str(raw.get("side") or "").split()),
        "line": raw.get("line"),
        "probability": probability,
        "pushProbability": push_probability,
        "voidProbability": void_probability,
        "sourceCount": int(raw.get("sourceCount") or 0),
        "modelStatus": str(raw.get("modelStatus") or "").strip().upper(),
        "settlementRuleKey": str(raw.get("settlementRuleKey") or "").strip() or None,
    }


def _normalize_payouts(raw: Mapping[object, object], pick_count: int) -> dict[int, float]:
    payouts: dict[int, float] = {}
    for hits, multiplier in raw.items():
        try:
            hit_count = int(hits)
            value = float(multiplier)
        except (TypeError, ValueError) as exc:
            raise ValueError("Payouts must map hit counts to numeric return multipliers.") from exc
        if not 0 <= hit_count <= pick_count or not math.isfinite(value) or value < 0:
            raise ValueError("Payout hit counts or multipliers are outside the valid range.")
        payouts[hit_count] = value
    if pick_count not in payouts:
        raise ValueError("The payout table must include the all-picks-hit multiplier.")
    return payouts


def _pair_key(left: str, right: str) -> str:
    return "::".join(sorted((left, right)))


def _normalize_correlations(
    raw: Mapping[str, object] | None, leg_ids: set[str]
) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for key, value in (raw or {}).items():
        parts = str(key).split("::")
        if len(parts) != 2 or parts[0] not in leg_ids or parts[1] not in leg_ids:
            raise ValueError("Correlation keys must use 'leg-id::leg-id' for legs in the slip.")
        try:
            correlation = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Correlation values must be numeric.") from exc
        if not math.isfinite(correlation) or not -0.95 <= correlation <= 0.95:
            raise ValueError("Correlation values must be between -0.95 and 0.95.")
        normalized[_pair_key(parts[0], parts[1])] = correlation
    return normalized


def _dependent_pairs(legs: list[dict]) -> list[dict]:
    dependencies = []
    for left, right in itertools.combinations(legs, 2):
        reasons = []
        if left["eventId"] and left["eventId"] == right["eventId"]:
            reasons.append("SAME_EVENT")
        if left["player"] and left["player"].casefold() == right["player"].casefold():
            reasons.append("SAME_PLAYER")
        if left["team"] and left["team"].casefold() == right["team"].casefold():
            reasons.append("SAME_TEAM")
        if reasons:
            dependencies.append(
                {
                    "leftId": left["id"],
                    "rightId": right["id"],
                    "key": _pair_key(left["id"], right["id"]),
                    "reasons": reasons,
                }
            )
    return dependencies


def _exact_count_distribution(legs: list[dict]) -> dict[tuple[int, int], float]:
    """Return probability by (active picks, hits); pushes/voids remove a pick."""

    distribution = {(0, 0): 1.0}
    for leg in legs:
        next_distribution: dict[tuple[int, int], float] = {}
        removed = leg["pushProbability"] + leg["voidProbability"]
        miss = 1.0 - leg["probability"] - removed
        for (active, hits), probability in distribution.items():
            states = (
                ((active + 1, hits + 1), leg["probability"]),
                ((active + 1, hits), miss),
                ((active, hits), removed),
            )
            for key, state_probability in states:
                if state_probability <= 0.0:
                    continue
                next_distribution[key] = (
                    next_distribution.get(key, 0.0)
                    + probability * state_probability
                )
        distribution = next_distribution
    return distribution


def _cholesky(matrix: list[list[float]]) -> list[list[float]]:
    size = len(matrix)
    result = [[0.0] * size for _ in range(size)]
    for row in range(size):
        for column in range(row + 1):
            value = matrix[row][column] - sum(
                result[row][offset] * result[column][offset]
                for offset in range(column)
            )
            if row == column:
                if value <= 1e-10:
                    raise ValueError("The supplied correlation matrix is not positive definite.")
                result[row][column] = math.sqrt(value)
            else:
                result[row][column] = value / result[column][column]
    return result


def _simulated_count_distribution(
    legs: list[dict], correlations: dict[str, float], samples: int
) -> dict[tuple[int, int], float]:
    size = len(legs)
    matrix = [[1.0 if row == column else 0.0 for column in range(size)] for row in range(size)]
    for left_index, right_index in itertools.combinations(range(size), 2):
        value = correlations.get(
            _pair_key(legs[left_index]["id"], legs[right_index]["id"]), 0.0
        )
        matrix[left_index][right_index] = value
        matrix[right_index][left_index] = value
    factor = _cholesky(matrix)
    seed_material = json.dumps(
        {
            "legs": [(leg["id"], leg["probability"]) for leg in legs],
            "correlations": correlations,
            "samples": samples,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    seed = int(hashlib.sha256(seed_material).hexdigest()[:16], 16)
    generator = random.Random(seed)
    normal = NormalDist()
    counts: dict[tuple[int, int], int] = {}
    for _ in range(samples):
        independent = [generator.gauss(0.0, 1.0) for _ in range(size)]
        correlated = [
            sum(factor[row][column] * independent[column] for column in range(row + 1))
            for row in range(size)
        ]
        active = 0
        hits = 0
        for index, leg in enumerate(legs):
            draw = normal.cdf(correlated[index])
            if draw <= leg["probability"]:
                active += 1
                hits += 1
            elif draw <= leg["probability"] + leg["pushProbability"] + leg["voidProbability"]:
                continue
            else:
                active += 1
        counts[(active, hits)] = counts.get((active, hits), 0) + 1
    return {key: count / samples for key, count in counts.items()}


def _payout_for_state(
    *,
    active: int,
    hits: int,
    original_count: int,
    payout_by_hits: dict[int, float],
    payout_by_active_count: Mapping[str, object] | None,
) -> float | None:
    if active == original_count:
        return float(payout_by_hits.get(hits, 0.0))
    if active == 0:
        return 1.0
    active_table = (payout_by_active_count or {}).get(str(active))
    if not isinstance(active_table, Mapping):
        return None
    normalized = _normalize_payouts(active_table, active)
    return float(normalized.get(hits, 0.0))


def evaluate_dfs_slip(
    legs: Iterable[Mapping[str, object]],
    *,
    payout_by_hits: Mapping[object, object],
    stake: float = 100.0,
    payout_by_active_count: Mapping[str, object] | None = None,
    correlations: Mapping[str, object] | None = None,
    payout_confirmed: bool = False,
    settlement_confirmed: bool = False,
    simulation_samples: int = SIMULATION_SAMPLES,
) -> dict:
    normalized_legs = [_normalize_leg(raw, index) for index, raw in enumerate(legs)]
    if not 2 <= len(normalized_legs) <= MAX_LEGS:
        raise ValueError(f"A slip requires between 2 and {MAX_LEGS} legs.")
    if len({leg["id"] for leg in normalized_legs}) != len(normalized_legs):
        raise ValueError("Slip leg ids must be unique.")
    if any(
        left["player"]
        and left["player"].casefold() == right["player"].casefold()
        for left, right in itertools.combinations(normalized_legs, 2)
    ):
        duplicate_player = True
    else:
        duplicate_player = False
    try:
        normalized_stake = float(stake)
    except (TypeError, ValueError) as exc:
        raise ValueError("Stake must be numeric.") from exc
    if not math.isfinite(normalized_stake) or normalized_stake <= 0:
        raise ValueError("Stake must be positive.")

    payouts = _normalize_payouts(payout_by_hits, len(normalized_legs))
    leg_ids = {leg["id"] for leg in normalized_legs}
    normalized_correlations = _normalize_correlations(correlations, leg_ids)
    dependencies = _dependent_pairs(normalized_legs)
    missing_correlations = [
        pair for pair in dependencies if pair["key"] not in normalized_correlations
    ]
    use_simulation = bool(normalized_correlations)
    sample_count = max(2_000, min(100_000, int(simulation_samples)))
    distribution = (
        _simulated_count_distribution(
            normalized_legs, normalized_correlations, sample_count
        )
        if use_simulation
        else _exact_count_distribution(normalized_legs)
    )

    missing_active_payouts = set()
    expected_multiplier = 0.0
    count_distribution: dict[str, float] = {}
    for (active, hits), probability in distribution.items():
        multiplier = _payout_for_state(
            active=active,
            hits=hits,
            original_count=len(normalized_legs),
            payout_by_hits=payouts,
            payout_by_active_count=payout_by_active_count,
        )
        if multiplier is None:
            missing_active_payouts.add(active)
            multiplier = 0.0
        expected_multiplier += probability * multiplier
        key = f"{active}:{hits}"
        count_distribution[key] = count_distribution.get(key, 0.0) + probability

    evidence_failures = [
        leg["id"]
        for leg in normalized_legs
        if leg["modelStatus"] not in {"AVAILABLE", "QUALIFIED"}
        or leg["sourceCount"] < 2
    ]
    settlement_keys = [leg["settlementRuleKey"] for leg in normalized_legs]
    reasons = []
    if not payout_confirmed:
        reasons.append("PAYOUT_NOT_CONFIRMED")
    if not settlement_confirmed:
        reasons.append("SETTLEMENT_NOT_CONFIRMED")
    if missing_correlations:
        reasons.append("CORRELATION_REQUIRED")
    if duplicate_player:
        reasons.append("DUPLICATE_PLAYER")
    if missing_active_payouts:
        reasons.append("VOID_PUSH_PAYOUT_TABLE_MISSING")
    if evidence_failures:
        reasons.append("INSUFFICIENT_MODEL_EVIDENCE")
    if any(settlement_keys) and len({key for key in settlement_keys if key}) > 1:
        reasons.append("SETTLEMENT_RULE_MISMATCH")

    expected_return = normalized_stake * expected_multiplier
    expected_profit = expected_return - normalized_stake
    all_hit_probability = distribution.get((len(normalized_legs), len(normalized_legs)), 0.0)
    method = "GAUSSIAN_COPULA_MONTE_CARLO" if use_simulation else "EXACT_POISSON_BINOMIAL"
    return {
        "status": "BLOCKED" if reasons else "EXECUTABLE",
        "executionEligible": not reasons,
        "blockingReasons": reasons,
        "legs": normalized_legs,
        "pickCount": len(normalized_legs),
        "stake": round(normalized_stake, 2),
        "payoutByHits": {str(key): value for key, value in sorted(payouts.items())},
        "expectedReturn": round(expected_return, 2),
        "expectedProfit": round(expected_profit, 2),
        "expectedValuePercent": round((expected_multiplier - 1.0) * 100.0, 2),
        "allHitProbability": round(all_hit_probability * 100.0, 4),
        "maximumLoss": round(normalized_stake, 2),
        "outcomeDistribution": {
            key: round(value * 100.0, 6)
            for key, value in sorted(count_distribution.items())
        },
        "correlationModel": {
            "method": method,
            "providedPairCount": len(normalized_correlations),
            "dependentPairs": dependencies,
            "missingPairs": missing_correlations,
            "simulationSamples": sample_count if use_simulation else 0,
        },
        "settlementModel": {
            "confirmed": bool(settlement_confirmed),
            "ruleKeys": settlement_keys,
            "missingActivePickTables": sorted(missing_active_payouts),
        },
        "payoutConfirmed": bool(payout_confirmed),
        "calculationVersion": DFS_SLIP_CALCULATION_VERSION,
    }


def optimize_dfs_slips(
    candidates: Iterable[Mapping[str, object]],
    *,
    pick_count: int,
    payout_by_hits: Mapping[object, object],
    stake: float = 100.0,
    correlations: Mapping[str, object] | None = None,
    payout_confirmed: bool = False,
    settlement_confirmed: bool = False,
    result_limit: int = 10,
) -> dict:
    pick_count = int(pick_count)
    if not 2 <= pick_count <= MAX_LEGS:
        raise ValueError(f"pick_count must be between 2 and {MAX_LEGS}.")
    normalized = [_normalize_leg(raw, index) for index, raw in enumerate(candidates)]
    eligible = [
        leg
        for leg in normalized
        if leg["modelStatus"] in {"AVAILABLE", "QUALIFIED"}
        and leg["sourceCount"] >= 2
    ]
    eligible.sort(key=lambda leg: leg["probability"], reverse=True)
    eligible = eligible[:MAX_CANDIDATES]

    # Bounded beam search avoids combinatorial blow-ups on large live boards.
    beam: list[tuple[tuple[int, ...], float]] = [((), 0.0)]
    for _ in range(pick_count):
        expanded = []
        for indices, score in beam:
            start = indices[-1] + 1 if indices else 0
            selected_players = {
                eligible[index]["player"].casefold()
                for index in indices
                if eligible[index]["player"]
            }
            for index in range(start, len(eligible)):
                player_key = eligible[index]["player"].casefold()
                if player_key and player_key in selected_players:
                    continue
                expanded.append(
                    (
                        indices + (index,),
                        score + math.log(eligible[index]["probability"]),
                    )
                )
        expanded.sort(key=lambda item: item[1], reverse=True)
        beam = expanded[:1_500]
        if not beam:
            break

    evaluations = []
    for indices, _score in beam[:MAX_EVALUATED_SLIPS]:
        slip_legs = [eligible[index] for index in indices]
        dependency_keys = {pair["key"] for pair in _dependent_pairs(slip_legs)}
        available_correlations = {
            key: value
            for key, value in (correlations or {}).items()
            if key in dependency_keys
        }
        result = evaluate_dfs_slip(
            slip_legs,
            payout_by_hits=payout_by_hits,
            stake=stake,
            correlations=available_correlations,
            payout_confirmed=payout_confirmed,
            settlement_confirmed=settlement_confirmed,
        )
        evaluations.append(result)
    evaluations.sort(
        key=lambda row: (
            row["executionEligible"],
            row["expectedValuePercent"],
            row["allHitProbability"],
        ),
        reverse=True,
    )
    limit = max(1, min(25, int(result_limit)))
    return {
        "data": evaluations[:limit],
        "total": min(len(evaluations), limit),
        "candidatesReceived": len(normalized),
        "candidatesEligible": len(eligible),
        "combinationsEvaluated": len(evaluations),
        "calculationVersion": DFS_SLIP_CALCULATION_VERSION,
    }
