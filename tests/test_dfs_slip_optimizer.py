from __future__ import annotations

import pytest

from dfs_slip_optimizer import evaluate_dfs_slip, optimize_dfs_slips


def _leg(
    leg_id: str,
    probability: float,
    *,
    player: str | None = None,
    event_id: str | None = None,
) -> dict:
    return {
        "id": leg_id,
        "player": player or leg_id,
        "eventId": event_id or f"event-{leg_id}",
        "probability": probability,
        "sourceCount": 3,
        "modelStatus": "AVAILABLE",
    }


def test_independent_power_slip_uses_exact_hit_count_distribution() -> None:
    result = evaluate_dfs_slip(
        [_leg("a", 0.6), _leg("b", 0.6)],
        payout_by_hits={2: 3.0},
        stake=100,
        payout_confirmed=True,
        settlement_confirmed=True,
    )

    assert result["executionEligible"] is True
    assert result["expectedValuePercent"] == pytest.approx(8.0)
    assert result["expectedProfit"] == pytest.approx(8.0)
    assert result["allHitProbability"] == pytest.approx(36.0)
    assert result["correlationModel"]["method"] == "EXACT_POISSON_BINOMIAL"


def test_payout_and_settlement_are_hard_execution_confirmations() -> None:
    result = evaluate_dfs_slip(
        [_leg("a", 0.6), _leg("b", 0.6)],
        payout_by_hits={2: 3.0},
    )

    assert result["status"] == "BLOCKED"
    assert result["blockingReasons"] == [
        "PAYOUT_NOT_CONFIRMED",
        "SETTLEMENT_NOT_CONFIRMED",
    ]


def test_same_event_slip_requires_explicit_correlation() -> None:
    legs = [
        _leg("a", 0.6, event_id="same"),
        _leg("b", 0.6, event_id="same"),
    ]
    blocked = evaluate_dfs_slip(
        legs,
        payout_by_hits={2: 3.0},
        payout_confirmed=True,
        settlement_confirmed=True,
    )
    modeled = evaluate_dfs_slip(
        legs,
        payout_by_hits={2: 3.0},
        correlations={"a::b": 0.25},
        payout_confirmed=True,
        settlement_confirmed=True,
        simulation_samples=5_000,
    )

    assert "CORRELATION_REQUIRED" in blocked["blockingReasons"]
    assert modeled["executionEligible"] is True
    assert modeled["correlationModel"]["method"] == "GAUSSIAN_COPULA_MONTE_CARLO"
    assert modeled["correlationModel"]["simulationSamples"] == 5_000


def test_optimizer_enforces_unique_players_and_returns_ranked_slips() -> None:
    candidates = [
        _leg("a-over", 0.65, player="A"),
        _leg("a-under", 0.64, player="A"),
        _leg("b", 0.63, player="B"),
        _leg("c", 0.62, player="C"),
    ]
    result = optimize_dfs_slips(
        candidates,
        pick_count=2,
        payout_by_hits={2: 3.0},
        payout_confirmed=True,
        settlement_confirmed=True,
    )

    assert result["data"]
    best_players = [leg["player"] for leg in result["data"][0]["legs"]]
    assert len(best_players) == len(set(best_players))


def test_dfs_slip_api_exposes_validation_and_distribution(app_client) -> None:
    response = app_client.post(
        "/api/dfs/slips/evaluate",
        json={
            "legs": [_leg("a", 0.6), _leg("b", 0.6)],
            "payoutByHits": {"2": 3.0},
            "stake": 100,
            "payoutConfirmed": True,
            "settlementConfirmed": True,
        },
    )

    assert response.status_code == 200
    assert response.get_json()["expectedValuePercent"] == pytest.approx(8.0)
