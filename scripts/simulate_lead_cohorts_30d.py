from __future__ import annotations

import json
import math
import random
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from simulate_mlb_wallet_portfolios import (
    event_date,
    number,
    position_return,
    wallet_signals,
)


ROOT = Path(__file__).resolve().parents[1]
THROUGH_DATE = "2026-07-26"
SEASON_START = "2026-03-01"
STARTING_BANKROLL = 10_000.0
SIMULATIONS = 5_000
HORIZON_DAYS = 30
SEED = 20260728

WALLETS = {
    "Soarin22": {
        "address": "0x84dbb7103982e3617704a2ed7d5b39691952aeeb",
        "unit": 7_800.0,
        "minimum_units": 0.5,
        "quality_weight": 0.78,
        "source": ROOT
        / "outputs/mlb-hybrid-monte-carlo/provider-cache/"
        "0x84dbb7103982e3617704a2ed7d5b39691952aeeb.json",
    },
    "Wordylittleneck": {
        "address": "0x3dfb153c197d4c19d3b31c1ecd2c7b6860eeabaf",
        "unit": 20_000.0,
        "minimum_units": 0.5,
        "quality_weight": 0.88,
        "source": ROOT
        / "outputs/mlb-hybrid-monte-carlo/provider-cache/"
        "0x3dfb153c197d4c19d3b31c1ecd2c7b6860eeabaf.json",
    },
    "phonesculptor": {
        "address": "0xf1528f12e645462c344799b62b1b421a6a4c64aa",
        "unit": 29_000.0,
        "minimum_units": 0.5,
        "quality_weight": 0.76,
        "source": ROOT
        / "outputs/mlb-hybrid-monte-carlo/provider-cache/"
        "0xf1528f12e645462c344799b62b1b421a6a4c64aa.json",
    },
    "Formal-Cupcake": {
        "address": "0xb8c842bc049bf208f73354c7b037b811d741d8a4",
        "unit": 1_300.0,
        "minimum_units": 1.0,
        "quality_weight": 0.85,
        "source": ROOT / "outputs/formal-cupcake-provider-closed.json",
    },
}

COHORTS = {
    "THREE_LEADS": ("Soarin22", "Wordylittleneck", "phonesculptor"),
    "FOUR_LEADS": (
        "Soarin22",
        "Wordylittleneck",
        "phonesculptor",
        "Formal-Cupcake",
    ),
}


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def season_days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1


def build_signals() -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for label, config in WALLETS.items():
        rows = json.loads(Path(config["source"]).read_text(encoding="utf-8"))
        signals = wallet_signals(
            rows,
            label=label,
            unit=float(config["unit"]),
            minimum_units=float(config["minimum_units"]),
            quality_weight=float(config["quality_weight"]),
            role="CONDITIONAL_ORIGINATOR",
            through_date=THROUGH_DATE,
        )
        result[label] = [
            signal
            for signal in signals
            if signal["eligible"]
            and SEASON_START <= str(signal["date"]) <= THROUGH_DATE
        ]
    return result


def build_plays(
    signal_map: dict[str, list[dict[str, Any]]], labels: tuple[str, ...]
) -> list[dict[str, Any]]:
    by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for label in labels:
        for signal in signal_map[label]:
            by_condition[str(signal["condition_id"])].append(signal)

    plays: list[dict[str, Any]] = []
    for condition_id, signals in by_condition.items():
        outcomes: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for signal in signals:
            outcomes[str(signal["outcome"])].append(signal)
        ranked = sorted(outcomes.items(), key=lambda item: len(item[1]), reverse=True)
        if len(ranked) > 1 and len(ranked[0][1]) == len(ranked[1][1]):
            continue
        selected_outcome, selected = ranked[0]
        opposed = [
            signal for signal in signals if str(signal["outcome"]) != selected_outcome
        ]
        if opposed:
            continue

        price = statistics.median(number(signal["price"]) for signal in selected)
        if not 0 < price < 1:
            continue
        supporter_count = len(selected)
        # This is the established replay sizing proxy: 0.50u for one clean lead,
        # plus 0.25u for each additional agreeing lead, capped at 1.50u.
        stake_units = min(1.5, 0.5 + 0.25 * (supporter_count - 1))
        won = bool(selected[0]["won"])
        plays.append(
            {
                "condition_id": condition_id,
                "date": selected[0]["date"],
                "event_slug": selected[0]["event_slug"],
                "outcome": selected_outcome,
                "supporters": sorted(signal["wallet"] for signal in selected),
                "supporter_count": supporter_count,
                "price": price,
                "won": won,
                "stake_units": stake_units,
                "return_per_dollar": position_return(price, won),
            }
        )
    return sorted(plays, key=lambda row: (str(row["date"]), row["condition_id"]))


def historical_summary(plays: list[dict[str, Any]]) -> dict[str, Any]:
    stakes = [number(play["stake_units"]) for play in plays]
    pnl_units = [
        number(play["stake_units"]) * number(play["return_per_dollar"])
        for play in plays
    ]
    calendar_days = season_days(SEASON_START, THROUGH_DATE)
    return {
        "bets": len(plays),
        "calendar_days": calendar_days,
        "bets_per_calendar_day": len(plays) / calendar_days,
        "active_days": len({str(play["date"]) for play in plays}),
        "win_rate": sum(bool(play["won"]) for play in plays) / len(plays),
        "median_stake_units": statistics.median(stakes),
        "average_stake_units": statistics.mean(stakes),
        "median_bet_per_100_bankroll": statistics.median(stakes),
        "median_bet_on_10000_bankroll": statistics.median(stakes) * 100,
        "stake_weighted_roi": sum(pnl_units) / sum(stakes),
        "historical_profit_units": sum(pnl_units),
    }


def period_summary(plays: list[dict[str, Any]], start: str, end: str) -> dict[str, Any]:
    selected = [play for play in plays if start <= str(play["date"]) <= end]
    stakes = [number(play["stake_units"]) for play in selected]
    pnl_units = [
        number(play["stake_units"]) * number(play["return_per_dollar"])
        for play in selected
    ]
    return {
        "start": start,
        "end": end,
        "bets": len(selected),
        "win_rate": (
            sum(bool(play["won"]) for play in selected) / len(selected)
            if selected
            else None
        ),
        "stake_weighted_roi": (
            sum(pnl_units) / sum(stakes) if sum(stakes) else None
        ),
    }


def stressed_roi(plays: list[dict[str, Any]], price_points: float) -> float:
    stakes = [number(play["stake_units"]) for play in plays]
    pnl_units = [
        number(play["stake_units"])
        * position_return(
            min(0.99, number(play["price"]) + price_points), bool(play["won"])
        )
        for play in plays
    ]
    return sum(pnl_units) / sum(stakes)


def simulate(
    plays: list[dict[str, Any]],
    *,
    bets_per_day: float,
    seed: int,
) -> dict[str, Any]:
    rng = random.Random(seed)
    paths: list[list[float]] = []
    total_staked: list[float] = []
    total_profit: list[float] = []
    bet_counts: list[int] = []

    daily_count_floor = math.floor(bets_per_day)
    daily_count_probability = bets_per_day - daily_count_floor
    for _ in range(SIMULATIONS):
        bankroll = STARTING_BANKROLL
        path = [bankroll]
        staked = 0.0
        count = 0
        for _day in range(HORIZON_DAYS):
            daily_bets = daily_count_floor + (
                1 if rng.random() < daily_count_probability else 0
            )
            day_plays = [rng.choice(plays) for _ in range(daily_bets)]
            for play in day_plays:
                stake = bankroll * number(play["stake_units"]) / 100
                bankroll += stake * number(play["return_per_dollar"])
                staked += stake
                count += 1
            path.append(bankroll)
        paths.append(path)
        total_staked.append(staked)
        total_profit.append(bankroll - STARTING_BANKROLL)
        bet_counts.append(count)

    percentiles = {
        "p05": [],
        "p25": [],
        "p50": [],
        "p75": [],
        "p95": [],
    }
    for day_index in range(HORIZON_DAYS + 1):
        values = [path[day_index] for path in paths]
        for label, q in (
            ("p05", 0.05),
            ("p25", 0.25),
            ("p50", 0.50),
            ("p75", 0.75),
            ("p95", 0.95),
        ):
            percentiles[label].append(percentile(values, q))

    final_bankrolls = [path[-1] for path in paths]
    rois = [(value / STARTING_BANKROLL) - 1 for value in final_bankrolls]
    return {
        "simulations": SIMULATIONS,
        "horizon_days": HORIZON_DAYS,
        "starting_bankroll": STARTING_BANKROLL,
        "median_bets": percentile([float(value) for value in bet_counts], 0.50),
        "probability_profitable": sum(value > STARTING_BANKROLL for value in final_bankrolls)
        / SIMULATIONS,
        "final_bankroll": {
            "p05": percentile(final_bankrolls, 0.05),
            "p25": percentile(final_bankrolls, 0.25),
            "p50": percentile(final_bankrolls, 0.50),
            "p75": percentile(final_bankrolls, 0.75),
            "p95": percentile(final_bankrolls, 0.95),
        },
        "roi": {
            "p05": percentile(rois, 0.05),
            "p25": percentile(rois, 0.25),
            "p50": percentile(rois, 0.50),
            "p75": percentile(rois, 0.75),
            "p95": percentile(rois, 0.95),
        },
        "median_staked_dollars": percentile(total_staked, 0.50),
        "median_profit_dollars": percentile(total_profit, 0.50),
        "daily_bankroll_percentiles": percentiles,
    }


def main() -> None:
    signals = build_signals()
    output: dict[str, Any] = {
        "methodology": {
            "generated_on": "2026-07-28",
            "scope": "Settled 2026 MLB standard moneyline positions through July 26, 2026",
            "cohort_rule": "Play a clean eligible lead direction; skip an exact tie or any eligible lead opposition.",
            "entry_price_proxy": "Median average entry price among agreeing lead wallets.",
            "sizing_proxy": "0.50u for one clean lead plus 0.25u per additional agreeing lead, capped at 1.50u; 1u is 1% of current bankroll.",
            "simulation": "5,000 bootstrap paths over 30 calendar days, sampling historical settled plays with replacement at the observed in-season bets/day rate.",
            "important_limit": "Closed positions do not reconstruct the exact two-hour executable price, available liquidity, or the live model's composite fair price. These are scenario estimates, not forward guarantees.",
        },
        "cohorts": {},
    }
    for index, (name, labels) in enumerate(COHORTS.items()):
        plays = build_plays(signals, labels)
        historical = historical_summary(plays)
        output["cohorts"][name] = {
            "wallets": list(labels),
            "historical": historical,
            "july_holdout": period_summary(
                plays, "2026-07-01", THROUGH_DATE
            ),
            "price_stress": {
                "two_cents_worse_roi": stressed_roi(plays, 0.02),
                "five_cents_worse_roi": stressed_roi(plays, 0.05),
            },
            "simulation": simulate(
                plays,
                bets_per_day=historical["bets_per_calendar_day"],
                seed=SEED + index,
            ),
            "play_ledger": plays,
        }
    target = ROOT / "outputs/lead-cohort-30-day-simulation-2026-07-28.json"
    target.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
