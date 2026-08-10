from pathlib import Path

import numpy as np
import pytest

from mlb_monte_carlo import (
    SimulationConfig,
    binary_kelly_fraction,
    build_daily_execution_samples,
    calibrate_edges,
    chronological_split,
    simulate_paths,
)


CONFIG_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "mlb_hybrid_monte_carlo_100k.json"
)


def config(**overrides) -> SimulationConfig:
    values = SimulationConfig.from_json(CONFIG_PATH).__dict__ | overrides
    return SimulationConfig(**values)


def play(
    date: str,
    *,
    price: float = 0.5,
    won: bool = True,
    supporters: list[str] | None = None,
) -> dict:
    return {
        "date": date,
        "condition_id": f"market-{date}-{won}",
        "price": price,
        "won": won,
        "flat_return": (1 - price) / price if won else -1,
        "supporters": supporters or ["Core", "Confirmer"],
    }


def test_binary_kelly_matches_manual_contract_formula():
    assert binary_kelly_fraction(0.50, 0.60) == pytest.approx(0.20)
    assert binary_kelly_fraction(0.60, 0.50) == 0.0


def test_chronological_split_never_puts_future_rows_in_training():
    rows = [
        play("2026-05-31"),
        play("2026-06-01"),
        play("2026-06-30"),
        play("2026-07-01"),
    ]
    split = chronological_split(rows, config(paths=10))
    assert [row["date"] for row in split["train"]] == ["2026-05-31"]
    assert [row["date"] for row in split["validation"]] == [
        "2026-06-01",
        "2026-06-30",
    ]
    assert [row["date"] for row in split["test"]] == ["2026-07-01"]


def test_calibration_uses_training_rows_and_shrinks_edge():
    cfg = config(paths=10, prior_sample_size=10.0)
    edge = calibrate_edges(
        [play("2026-05-01", price=0.5, won=True)] * 10,
        cfg,
    )
    assert edge["ALL"] == pytest.approx(0.05)


def test_blocked_trade_produces_no_execution_return():
    cfg = config(
        paths=10,
        execution_variants_per_day=16,
        median_delay_minutes=1000,
        slippage_points_per_delay_minute=1.0,
    )
    samples, diagnostics = build_daily_execution_samples(
        [play("2026-07-01")],
        model="FIXED_PERCENT",
        calibrated_edges={"ALL": 0.05, "TWO": 0.05},
        config=cfg,
        rng=np.random.default_rng(1),
        stress={"period_start": "2026-07-01"},
    )
    assert np.all(samples == 0)
    assert diagnostics["rejection_rate"] == 1.0


def test_parametric_edge_disappearance_keeps_bets_but_changes_outcomes():
    cfg = config(
        paths=10,
        execution_variants_per_day=1000,
        median_delay_minutes=0,
        slippage_points_median=0.00001,
        slippage_points_per_delay_minute=0,
    )
    samples, diagnostics = build_daily_execution_samples(
        [play("2026-07-01", price=0.5, won=True)],
        model="FIXED_PERCENT",
        calibrated_edges={"ALL": 0.05, "TWO": 0.05},
        config=cfg,
        rng=np.random.default_rng(4),
        stress={
            "period_start": "2026-07-01",
            "outcome_edge_multiplier": 0.0,
        },
    )
    assert diagnostics["mean_fill_percentage"] > 0
    assert np.any(samples > 0)
    assert np.any(samples < 0)


def test_simulation_is_reproducible_and_bankroll_never_negative():
    cfg = config(
        paths=100,
        horizon_calendar_days=20,
        chunk_size=17,
    )
    samples = np.array([[0.01, -0.01], [0.02, -0.02]])
    first = simulate_paths(samples, config=cfg, seed=42)
    second = simulate_paths(samples, config=cfg, seed=42)
    assert first["roi_percentiles"] == second["roi_percentiles"]
    assert first["final_bankroll_percentiles"]["p01"] >= 0
    assert first["paths"] == 100


def test_chunking_does_not_drop_paths():
    cfg = config(paths=103, horizon_calendar_days=2, chunk_size=20)
    result = simulate_paths(
        np.array([[0.01], [-0.01]]),
        config=cfg,
        seed=7,
    )
    assert result["paths"] == 103


def test_fixed_dollar_staking_does_not_compound_the_stake():
    cfg = config(
        paths=1,
        horizon_calendar_days=2,
        chunk_size=1,
        starting_bankroll=10_000,
    )
    result = simulate_paths(
        np.array([[0.01]]),
        config=cfg,
        seed=7,
        fixed_dollar_staking=True,
    )
    assert result["median_final_bankroll"] == 10_200
