from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


PERCENTILES = (0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)


@dataclass(frozen=True)
class SimulationConfig:
    paths: int
    seed: int
    starting_bankroll: float
    horizon_calendar_days: int
    chunk_size: int
    execution_variants_per_day: int
    train_end: str
    validation_end: str
    test_end: str
    prior_sample_size: float
    maximum_calibrated_edge_points: float
    maximum_price_deterioration_points: float
    median_delay_minutes: float
    delay_lognormal_sigma: float
    slippage_points_median: float
    slippage_lognormal_sigma: float
    slippage_points_per_delay_minute: float
    fill_beta_alpha: float
    fill_beta_beta: float
    fee_fraction: float
    maximum_trade_fraction: float
    maximum_daily_fraction: float
    fixed_percentage: float
    fixed_unit_dollars: float
    kelly_cap: float
    output_directory: str

    @classmethod
    def from_json(cls, path: Path) -> "SimulationConfig":
        return cls(**json.loads(path.read_text(encoding="utf-8")))


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def binary_kelly_fraction(entry_price: float, win_probability: float) -> float:
    """Kelly fraction for a binary contract bought at price p with belief q."""
    if not 0 < entry_price < 1 or not 0 < win_probability < 1:
        return 0.0
    odds = (1.0 - entry_price) / entry_price
    return max(0.0, ((odds * win_probability) - (1.0 - win_probability)) / odds)


def chronological_split(
    plays: list[dict[str, Any]], config: SimulationConfig
) -> dict[str, list[dict[str, Any]]]:
    return {
        "train": [
            play for play in plays if str(play["date"]) <= config.train_end
        ],
        "validation": [
            play
            for play in plays
            if config.train_end < str(play["date"]) <= config.validation_end
        ],
        "test": [
            play
            for play in plays
            if config.validation_end < str(play["date"]) <= config.test_end
        ],
    }


def supporter_bucket(play: dict[str, Any]) -> str:
    count = len(play.get("supporters") or [])
    return "3_PLUS" if count >= 3 else "TWO"


def calibrate_edges(
    training_plays: list[dict[str, Any]], config: SimulationConfig
) -> dict[str, float]:
    """Estimate price residuals with a zero-edge Bayesian prior."""
    buckets: dict[str, list[float]] = {"ALL": []}
    for play in training_plays:
        price = float(play["price"])
        residual = float(bool(play["won"])) - price
        buckets["ALL"].append(residual)
        buckets.setdefault(supporter_bucket(play), []).append(residual)

    calibrated: dict[str, float] = {}
    for bucket, residuals in buckets.items():
        shrunk = sum(residuals) / (len(residuals) + config.prior_sample_size)
        calibrated[bucket] = clamp(
            shrunk,
            -config.maximum_calibrated_edge_points,
            config.maximum_calibrated_edge_points,
        )
    return calibrated


def estimated_probability(
    play: dict[str, Any],
    calibrated_edges: dict[str, float],
    edge_haircut: float,
) -> float:
    edge = calibrated_edges.get(
        supporter_bucket(play), calibrated_edges.get("ALL", 0.0)
    )
    return clamp(float(play["price"]) + edge * edge_haircut, 0.01, 0.99)


def sizing_fraction(
    model: str,
    *,
    entry_price: float,
    win_probability: float,
    play: dict[str, Any],
    config: SimulationConfig,
) -> float:
    if model == "FIXED_PERCENT":
        fraction = config.fixed_percentage
    elif model == "FIXED_UNIT":
        fraction = config.fixed_unit_dollars / config.starting_bankroll
    else:
        full_kelly = binary_kelly_fraction(entry_price, win_probability)
        multiplier = {
            "QUARTER_KELLY": 0.25,
            "HALF_KELLY": 0.50,
            "CONFIDENCE_HALF_KELLY": 0.50,
        }[model]
        fraction = full_kelly * multiplier
        if model == "CONFIDENCE_HALF_KELLY":
            supporter_count = len(play.get("supporters") or [])
            confidence_proxy = clamp(0.55 + 0.10 * (supporter_count - 2), 0.55, 0.85)
            fraction *= confidence_proxy
    return clamp(fraction, 0.0, min(config.maximum_trade_fraction, config.kelly_cap))


def _calendar_days(start: str, end: str) -> list[str]:
    first = np.datetime64(start)
    last = np.datetime64(end)
    return [
        str(value)
        for value in np.arange(first, last + np.timedelta64(1, "D"))
    ]


def _best_training_supporter(plays: list[dict[str, Any]]) -> str | None:
    pnl: dict[str, float] = {}
    for play in plays:
        for wallet in play.get("supporters") or []:
            pnl[wallet] = pnl.get(wallet, 0.0) + float(play["flat_return"])
    return max(pnl, key=pnl.get) if pnl else None


def build_daily_execution_samples(
    plays: list[dict[str, Any]],
    *,
    model: str,
    calibrated_edges: dict[str, float],
    config: SimulationConfig,
    rng: np.random.Generator,
    stress: dict[str, Any],
) -> tuple[np.ndarray, dict[str, Any]]:
    days = _calendar_days(
        str(stress.get("period_start") or config.validation_end),
        config.test_end,
    )
    by_day: dict[str, list[dict[str, Any]]] = {day: [] for day in days}
    excluded_wallet = stress.get("exclude_wallet")
    for play in plays:
        if excluded_wallet and excluded_wallet in (play.get("supporters") or []):
            continue
        by_day.setdefault(str(play["date"]), []).append(play)

    variants = config.execution_variants_per_day
    daily_returns = np.zeros((len(days), variants), dtype=np.float64)
    attempted = 0
    filled_equivalents = 0.0
    rejected = 0
    delay_multiplier = float(stress.get("delay_multiplier", 1.0))
    slippage_multiplier = float(stress.get("slippage_multiplier", 1.0))
    fill_multiplier = float(stress.get("fill_multiplier", 1.0))
    edge_haircut = float(stress.get("edge_haircut", 1.0))
    outcome_edge_multiplier = stress.get("outcome_edge_multiplier")
    forced_loss_multiplier = float(stress.get("loss_multiplier", 1.0))

    for day_index, day in enumerate(days):
        day_stakes = np.zeros(variants, dtype=np.float64)
        for play in by_day.get(day, []):
            attempted += variants
            delays = rng.lognormal(
                mean=math.log(max(config.median_delay_minutes, 0.01)),
                sigma=config.delay_lognormal_sigma,
                size=variants,
            ) * delay_multiplier
            random_slippage = rng.lognormal(
                mean=math.log(max(config.slippage_points_median, 0.00001)),
                sigma=config.slippage_lognormal_sigma,
                size=variants,
            )
            slippage = (
                random_slippage
                + delays * config.slippage_points_per_delay_minute
            ) * slippage_multiplier
            executable = slippage <= config.maximum_price_deterioration_points
            rejected += int(np.count_nonzero(~executable))
            fill = np.minimum(
                1.0,
                rng.beta(
                    config.fill_beta_alpha,
                    config.fill_beta_beta,
                    size=variants,
                )
                * fill_multiplier,
            )
            fill *= executable
            filled_equivalents += float(fill.sum())

            entry = np.minimum(0.99, float(play["price"]) + slippage)
            q = estimated_probability(
                play, calibrated_edges, edge_haircut=edge_haircut
            )
            fractions = np.array(
                [
                    sizing_fraction(
                        model,
                        entry_price=float(value),
                        win_probability=q,
                        play=play,
                        config=config,
                    )
                    for value in entry
                ],
                dtype=np.float64,
            )
            remaining = np.maximum(0.0, config.maximum_daily_fraction - day_stakes)
            fractions = np.minimum(fractions * fill, remaining)
            day_stakes += fractions
            if outcome_edge_multiplier is None:
                won = np.full(variants, bool(play["won"]), dtype=bool)
            else:
                historical_edge = (
                    calibrated_edges.get(
                        supporter_bucket(play),
                        calibrated_edges.get("ALL", 0.0),
                    )
                    * float(outcome_edge_multiplier)
                )
                actual_probability = clamp(
                    float(play["price"]) + historical_edge,
                    0.01,
                    0.99,
                )
                won = rng.random(variants) < actual_probability
            contract_return = np.where(
                won,
                (1.0 - entry) / entry,
                -forced_loss_multiplier,
            )
            daily_returns[day_index] += (
                fractions * contract_return
                - fractions * config.fee_fraction
            )

    return daily_returns, {
        "calendar_days": len(days),
        "historical_signals": sum(len(rows) for rows in by_day.values()),
        "attempted_execution_variants": attempted,
        "mean_fill_percentage": (
            filled_equivalents / attempted if attempted else 0.0
        ),
        "rejection_rate": rejected / attempted if attempted else 0.0,
        "stress": stress,
    }


def _summarize_array(values: np.ndarray) -> dict[str, float]:
    quantiles = np.quantile(values, PERCENTILES)
    return {
        f"p{int(percentile * 100):02d}": round(float(value), 6)
        for percentile, value in zip(PERCENTILES, quantiles)
    }


def simulate_paths(
    daily_return_samples: np.ndarray,
    *,
    config: SimulationConfig,
    seed: int,
    fixed_dollar_staking: bool = False,
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    final_bankrolls = np.empty(config.paths, dtype=np.float64)
    maximum_drawdowns = np.empty(config.paths, dtype=np.float64)
    longest_losing_streaks = np.empty(config.paths, dtype=np.int16)
    completed = 0
    started = time.perf_counter()
    day_count, variants = daily_return_samples.shape

    while completed < config.paths:
        size = min(config.chunk_size, config.paths - completed)
        day_indices = rng.integers(
            0, day_count, size=(size, config.horizon_calendar_days)
        )
        variant_indices = rng.integers(
            0, variants, size=(size, config.horizon_calendar_days)
        )
        returns = daily_return_samples[day_indices, variant_indices]
        bankroll = np.full(size, config.starting_bankroll, dtype=np.float64)
        peak = bankroll.copy()
        max_drawdown = np.zeros(size, dtype=np.float64)
        current_streak = np.zeros(size, dtype=np.int16)
        longest_streak = np.zeros(size, dtype=np.int16)

        for day in range(config.horizon_calendar_days):
            day_return = np.maximum(-1.0, returns[:, day])
            if fixed_dollar_staking:
                bankroll = np.maximum(
                    0.0,
                    bankroll + config.starting_bankroll * day_return,
                )
            else:
                bankroll *= 1.0 + day_return
            peak = np.maximum(peak, bankroll)
            drawdown = np.divide(
                peak - bankroll,
                peak,
                out=np.zeros_like(bankroll),
                where=peak > 0,
            )
            max_drawdown = np.maximum(max_drawdown, drawdown)
            losing = day_return < 0
            current_streak = np.where(losing, current_streak + 1, 0)
            longest_streak = np.maximum(longest_streak, current_streak)

        end = completed + size
        final_bankrolls[completed:end] = bankroll
        maximum_drawdowns[completed:end] = max_drawdown
        longest_losing_streaks[completed:end] = longest_streak
        completed = end

    rois = final_bankrolls / config.starting_bankroll - 1.0
    losses = 1.0 - final_bankrolls / config.starting_bankroll
    elapsed = time.perf_counter() - started
    return {
        "paths": config.paths,
        "horizon_calendar_days": config.horizon_calendar_days,
        "runtime_seconds": round(elapsed, 3),
        "paths_per_second": round(config.paths / max(elapsed, 1e-9), 1),
        "expected_roi": round(float(rois.mean()), 6),
        "median_roi": round(float(np.median(rois)), 6),
        "probability_profitable": round(float(np.mean(rois > 0)), 6),
        "expected_final_bankroll": round(float(final_bankrolls.mean()), 2),
        "median_final_bankroll": round(float(np.median(final_bankrolls)), 2),
        "final_bankroll_percentiles": _summarize_array(final_bankrolls),
        "roi_percentiles": _summarize_array(rois),
        "maximum_drawdown": {
            "median": round(float(np.median(maximum_drawdowns)), 6),
            "p90": round(float(np.quantile(maximum_drawdowns, 0.90)), 6),
            "p95": round(float(np.quantile(maximum_drawdowns, 0.95)), 6),
            "p99": round(float(np.quantile(maximum_drawdowns, 0.99)), 6),
            "worst": round(float(maximum_drawdowns.max()), 6),
        },
        "probability_losing": {
            "10_percent": round(float(np.mean(losses >= 0.10)), 6),
            "20_percent": round(float(np.mean(losses >= 0.20)), 6),
            "30_percent": round(float(np.mean(losses >= 0.30)), 6),
            "50_percent": round(float(np.mean(losses >= 0.50)), 6),
            "entire_bankroll": round(float(np.mean(final_bankrolls <= 0.01)), 6),
        },
        "value_at_risk_roi_95": round(float(np.quantile(rois, 0.05)), 6),
        "conditional_value_at_risk_roi_95": round(
            float(rois[rois <= np.quantile(rois, 0.05)].mean()), 6
        ),
        "longest_losing_day_streak": {
            "median": float(np.median(longest_losing_streaks)),
            "p95": float(np.quantile(longest_losing_streaks, 0.95)),
            "worst": int(longest_losing_streaks.max()),
        },
    }


def deterministic_replay(
    plays: list[dict[str, Any]],
    *,
    model: str,
    calibrated_edges: dict[str, float],
    config: SimulationConfig,
) -> dict[str, Any]:
    bankroll = config.starting_bankroll
    peak = bankroll
    max_drawdown = 0.0
    total_staked = 0.0
    filled = 0
    rejected = 0
    for play in sorted(plays, key=lambda row: (row["date"], row["condition_id"])):
        entry = min(
            0.99,
            float(play["price"])
            + config.slippage_points_median
            + config.median_delay_minutes
            * config.slippage_points_per_delay_minute,
        )
        if entry - float(play["price"]) > config.maximum_price_deterioration_points:
            rejected += 1
            continue
        q = estimated_probability(play, calibrated_edges, 1.0)
        fraction = sizing_fraction(
            model,
            entry_price=entry,
            win_probability=q,
            play=play,
            config=config,
        )
        stake = min(
            bankroll,
            config.fixed_unit_dollars
            if model == "FIXED_UNIT"
            else bankroll * fraction,
        )
        if stake <= 0:
            rejected += 1
            continue
        total_staked += stake
        filled += 1
        profit = (
            stake * ((1.0 - entry) / entry)
            if play["won"]
            else -stake
        ) - stake * config.fee_fraction
        bankroll = max(0.0, bankroll + profit)
        peak = max(peak, bankroll)
        max_drawdown = max(
            max_drawdown, (peak - bankroll) / peak if peak else 0.0
        )
    return {
        "signals": len(plays),
        "filled": filled,
        "rejected_or_zero_edge": rejected,
        "ending_bankroll": round(bankroll, 2),
        "roi": round(bankroll / config.starting_bankroll - 1.0, 6),
        "stake_weighted_roi": round(
            (bankroll - config.starting_bankroll) / total_staked, 6
        )
        if total_staked
        else None,
        "maximum_drawdown": round(max_drawdown, 6),
    }


def run_analysis(
    plays: list[dict[str, Any]], config: SimulationConfig
) -> dict[str, Any]:
    split = chronological_split(plays, config)
    development_edges = calibrate_edges(split["train"], config)
    final_edges = calibrate_edges(
        split["train"] + split["validation"], config
    )
    best_supporter = _best_training_supporter(split["train"])
    models = (
        "FIXED_PERCENT",
        "FIXED_UNIT",
        "QUARTER_KELLY",
        "HALF_KELLY",
        "CONFIDENCE_HALF_KELLY",
    )
    replay = {
        period: {
            model: deterministic_replay(
                period_plays,
                model=model,
                calibrated_edges=(
                    final_edges if period == "test" else development_edges
                ),
                config=config,
            )
            for model in models
        }
        for period, period_plays in split.items()
    }
    stresses = {
        "BASELINE": {},
        "DELAY_2X": {"delay_multiplier": 2.0},
        "SLIPPAGE_3X": {"slippage_multiplier": 3.0},
        "FILL_RATE_50_PERCENT": {"fill_multiplier": 0.5},
        "EDGE_HAIRCUT_25_PERCENT": {"edge_haircut": 0.75},
        "EDGE_HAIRCUT_50_PERCENT": {"edge_haircut": 0.50},
        "EDGE_DISAPPEARS": {"edge_haircut": 0.0},
        "REALIZED_EDGE_DECAYS_50_PERCENT": {
            "outcome_edge_multiplier": 0.50,
        },
        "REALIZED_EDGE_DISAPPEARS_BUT_MODEL_BETS": {
            "outcome_edge_multiplier": 0.0,
        },
        "REALIZED_EDGE_REVERSES": {
            "outcome_edge_multiplier": -0.50,
        },
        "BEST_TRAINING_SUPPORTER_REMOVED": {
            "exclude_wallet": best_supporter,
        },
        "SEVERE_LOSS_AMPLIFICATION": {"loss_multiplier": 1.5},
    }

    monte_carlo: dict[str, Any] = {}
    for model_index, model in enumerate(models):
        monte_carlo[model] = {}
        for stress_index, (stress_name, stress) in enumerate(stresses.items()):
            sample_rng = np.random.default_rng(
                config.seed + model_index * 10_000 + stress_index * 101
            )
            daily_samples, execution = build_daily_execution_samples(
                split["test"],
                model=model,
                calibrated_edges=final_edges,
                config=config,
                rng=sample_rng,
                stress={
                    "period_start": str(
                        np.datetime64(config.validation_end)
                        + np.timedelta64(1, "D")
                    ),
                    **stress,
                },
            )
            monte_carlo[model][stress_name] = {
                "execution": execution,
                "portfolio": simulate_paths(
                    daily_samples,
                    config=config,
                    seed=config.seed + model_index * 100_000 + stress_index,
                    fixed_dollar_staking=model == "FIXED_UNIT",
                ),
            }

    return {
        "scope": {
            "strategy": "HYBRID_CONSENSUS_2",
            "market": "Standard MLB moneylines",
            "observed_fields": [
                "resolved outcome",
                "wallet average entry price",
                "wallet/event consensus",
                "wallet-relative position size",
                "event date",
            ],
            "modeled_fields": [
                "execution delay",
                "slippage",
                "fill percentage",
                "fees",
                "probability calibration",
            ],
            "unavailable_fields": [
                "exact historical alert timestamp",
                "as-of executable order book",
                "closing line",
                "historical multi-exchange depth",
                "historical rejected candidate ledger",
            ],
        },
        "configuration": config.__dict__,
        "sample": {
            "total": len(plays),
            **{key: len(value) for key, value in split.items()},
        },
        "calibration": {
            "method": (
                "Development calibration uses training only. Final test "
                "calibration refits on training plus validation, with binary "
                "outcome minus entry price shrunk toward zero edge."
            ),
            "development_edge_points": development_edges,
            "final_test_edge_points": final_edges,
            "best_training_supporter": best_supporter,
        },
        "historical_replay": replay,
        "monte_carlo": monte_carlo,
    }
