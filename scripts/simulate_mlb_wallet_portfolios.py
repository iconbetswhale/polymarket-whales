from __future__ import annotations

import argparse
import json
import math
import random
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from polymarket_client import PolymarketClient
from wallet_loader import load_wallets


DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")
CORE_LABELS = {"Wordylittleneck", "phonesculptor", "Soarin22"}
PORTFOLIO_LABELS = {
    "0x4f2",
    "sportmaster777",
    "ferrariChampions2026",
    "HomeRunHazard",
}


def number(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * quantile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def event_date(row: dict[str, Any]) -> str | None:
    match = DATE_RE.search(str(row.get("eventSlug") or row.get("slug") or ""))
    return match.group(1) if match else None


def is_standard_mlb_moneyline(row: dict[str, Any]) -> bool:
    event_slug = str(row.get("eventSlug") or "").lower()
    market_slug = str(row.get("slug") or "").lower()
    return event_slug.startswith("mlb-") and market_slug == event_slug


def position_return(price: float, won: bool) -> float:
    if price <= 0 or price >= 1:
        return 0.0
    return (1.0 - price) / price if won else -1.0


def wallet_signals(
    rows: list[dict[str, Any]],
    *,
    label: str,
    unit: float,
    minimum_units: float,
    quality_weight: float,
    role: str,
    through_date: str,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        date = event_date(row)
        if (
            date
            and date <= through_date
            and is_standard_mlb_moneyline(row)
            and row.get("conditionId")
        ):
            grouped[str(row["conditionId"]).lower()].append(row)

    signals: list[dict[str, Any]] = []
    for condition_id, market_rows in grouped.items():
        ordered = sorted(
            market_rows,
            key=lambda row: number(row.get("totalBought")),
            reverse=True,
        )
        leader = ordered[0]
        leader_exposure = number(leader.get("totalBought"))
        opposing_exposure = sum(
            number(row.get("totalBought")) for row in ordered[1:]
        )
        if leader_exposure <= 0:
            continue
        opposing_ratio = opposing_exposure / leader_exposure
        net_exposure = max(0.0, leader_exposure - opposing_exposure)
        relative_units = net_exposure / unit if unit > 0 else 0.0
        status = (
            "CLEAN_DIRECTIONAL"
            if opposing_ratio < 0.10
            else "MINOR_HEDGE"
            if opposing_ratio <= 0.20
            else "MATERIAL_HEDGE"
            if opposing_ratio <= 0.50
            else "TWO_SIDED"
        )
        price = number(leader.get("avgPrice"))
        won = number(leader.get("curPrice")) >= 0.99
        signals.append(
            {
                "condition_id": condition_id,
                "event_slug": str(leader.get("eventSlug") or ""),
                "date": event_date(leader),
                "wallet": label,
                "outcome": str(leader.get("outcome") or ""),
                "price": price,
                "won": won,
                "return": position_return(price, won),
                "net_exposure": net_exposure,
                "relative_units": relative_units,
                "opposing_ratio": opposing_ratio,
                "status": status,
                "quality_weight": quality_weight,
                "role": role,
                "eligible": (
                    role in {"ORIGINATOR", "CONDITIONAL_ORIGINATOR"}
                    and status in {"CLEAN_DIRECTIONAL", "MINOR_HEDGE"}
                    and relative_units >= minimum_units
                    and 0 < price < 1
                ),
            }
        )
    return signals


def select_outcome(signals: list[dict[str, Any]]) -> tuple[str | None, bool]:
    votes = Counter(str(signal["outcome"]) for signal in signals)
    if not votes:
        return None, False
    ranked = votes.most_common()
    tied = len(ranked) > 1 and ranked[0][1] == ranked[1][1]
    return (None, True) if tied else (ranked[0][0], False)


def make_play(
    strategy: str, signals: list[dict[str, Any]]
) -> dict[str, Any] | None:
    eligible = [signal for signal in signals if signal["eligible"]]
    if not eligible:
        return None
    core = [signal for signal in eligible if signal["wallet"] in CORE_LABELS]
    portfolio = [
        signal for signal in eligible if signal["wallet"] in PORTFOLIO_LABELS
    ]

    if strategy in {"BROAD_EQUAL", "BROAD_CONSENSUS_2"}:
        outcome, tied = select_outcome(eligible)
        if tied or not outcome:
            return None
        selected = [signal for signal in eligible if signal["outcome"] == outcome]
        opposed = [signal for signal in eligible if signal["outcome"] != outcome]
        if strategy == "BROAD_CONSENSUS_2" and len(selected) < 2:
            return None
        margin = (len(selected) - len(opposed)) / len(eligible)
        stake = min(1.5, max(0.25, 0.5 + 0.5 * margin + 0.1 * (len(selected) - 1)))
    elif strategy == "PRECISION_ONLY":
        outcome, tied = select_outcome(core)
        if tied or not outcome:
            return None
        selected = [signal for signal in core if signal["outcome"] == outcome]
        opposed = [signal for signal in core if signal["outcome"] != outcome]
        stake = min(1.5, max(0.25, 0.5 + 0.25 * (len(selected) - len(opposed))))
    elif strategy == "STRICT_CORE_CONSENSUS":
        outcome, tied = select_outcome(core)
        if tied or not outcome:
            return None
        selected = [signal for signal in core if signal["outcome"] == outcome]
        opposed = [signal for signal in core if signal["outcome"] != outcome]
        if len(selected) < 2 or opposed:
            return None
        stake = min(1.5, 0.75 + 0.25 * (len(selected) - 2))
    elif strategy in {
        "HYBRID_CORE_WITH_CONFIRMERS",
        "HYBRID_CONSENSUS_2",
    }:
        outcome, tied = select_outcome(core)
        if tied or not outcome:
            return None
        selected = [signal for signal in core if signal["outcome"] == outcome]
        opposed = [signal for signal in core if signal["outcome"] != outcome]
        confirming_portfolio = [
            signal for signal in portfolio if signal["outcome"] == outcome
        ]
        opposing_portfolio = [
            signal for signal in portfolio if signal["outcome"] != outcome
        ]
        confirm_weight = sum(
            signal["quality_weight"]
            * min(2.0, math.sqrt(signal["relative_units"]))
            for signal in confirming_portfolio
        )
        oppose_weight = sum(
            signal["quality_weight"]
            * min(2.0, math.sqrt(signal["relative_units"]))
            for signal in opposing_portfolio
        )
        if opposed or oppose_weight > confirm_weight + 0.5:
            return None
        if (
            strategy == "HYBRID_CONSENSUS_2"
            and len(selected) + len(confirming_portfolio) < 2
        ):
            return None
        if strategy == "HYBRID_CONSENSUS_2":
            selected.extend(confirming_portfolio)
            opposed.extend(opposing_portfolio)
        stake = min(
            1.5,
            max(
                0.25,
                0.5
                + 0.25 * (len(selected) - 1)
                + 0.15 * confirm_weight
                - 0.15 * oppose_weight,
            ),
        )
    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    prices = [signal["price"] for signal in selected]
    price = statistics.median(prices)
    won = selected[0]["won"]
    return {
        "strategy": strategy,
        "condition_id": selected[0]["condition_id"],
        "event_slug": selected[0]["event_slug"],
        "date": selected[0]["date"],
        "outcome": selected[0]["outcome"],
        "price": price,
        "won": won,
        "flat_return": position_return(price, won),
        "stake_units": round(stake, 4),
        "sized_pnl_units": position_return(price, won) * stake,
        "supporters": [signal["wallet"] for signal in selected],
        "opponents": [signal["wallet"] for signal in opposed],
    }


def max_drawdown(pnls: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def summarize(plays: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(plays, key=lambda play: (play["date"], play["condition_id"]))
    flat = [number(play["flat_return"]) for play in ordered]
    sized = [number(play["sized_pnl_units"]) for play in ordered]
    stakes = [number(play["stake_units"]) for play in ordered]
    return {
        "bets": len(ordered),
        "wins": sum(bool(play["won"]) for play in ordered),
        "win_rate": (
            round(sum(bool(play["won"]) for play in ordered) / len(ordered), 4)
            if ordered
            else None
        ),
        "flat_stake_roi": round(sum(flat) / len(flat), 4) if flat else None,
        "flat_profit_units": round(sum(flat), 2),
        "sized_staked_units": round(sum(stakes), 2),
        "sized_profit_units": round(sum(sized), 2),
        "sized_roi": round(sum(sized) / sum(stakes), 4) if sum(stakes) else None,
        "maximum_drawdown_units": round(max_drawdown(sized), 2),
        "average_stake_units": round(statistics.mean(stakes), 3) if stakes else None,
        "active_days": len({play["date"] for play in ordered}),
    }


def price_stress(plays: list[dict[str, Any]], points: float) -> dict[str, Any]:
    stressed_pnls: list[float] = []
    stakes: list[float] = []
    for play in plays:
        price = min(0.99, number(play["price"]) + points)
        stake = number(play["stake_units"])
        stressed_pnls.append(position_return(price, bool(play["won"])) * stake)
        stakes.append(stake)
    return {
        "price_deterioration_points": points,
        "profit_units": round(sum(stressed_pnls), 2),
        "roi": (
            round(sum(stressed_pnls) / sum(stakes), 4) if sum(stakes) else None
        ),
        "maximum_drawdown_units": round(max_drawdown(stressed_pnls), 2),
    }


def bootstrap_days(
    plays: list[dict[str, Any]], *, iterations: int, seed: int
) -> dict[str, Any]:
    by_day: dict[str, float] = defaultdict(float)
    for play in plays:
        by_day[str(play["date"])] += number(play["sized_pnl_units"])
    daily = list(by_day.values())
    if not daily:
        return {}
    rng = random.Random(seed)
    finals: list[float] = []
    drawdowns: list[float] = []
    for _ in range(iterations):
        path = [rng.choice(daily) for _ in daily]
        finals.append(sum(path))
        drawdowns.append(max_drawdown(path))
    return {
        "iterations": iterations,
        "days_per_path": len(daily),
        "probability_profitable": round(
            sum(value > 0 for value in finals) / iterations, 4
        ),
        "final_units": {
            "worst_sampled": round(min(finals), 2),
            "p01": round(percentile(finals, 0.01) or 0, 2),
            "p05": round(percentile(finals, 0.05) or 0, 2),
            "median": round(percentile(finals, 0.50) or 0, 2),
            "p95": round(percentile(finals, 0.95) or 0, 2),
            "p99": round(percentile(finals, 0.99) or 0, 2),
            "best_sampled": round(max(finals), 2),
        },
        "maximum_drawdown_units": {
            "median": round(percentile(drawdowns, 0.50) or 0, 2),
            "p90": round(percentile(drawdowns, 0.90) or 0, 2),
            "p95": round(percentile(drawdowns, 0.95) or 0, 2),
            "p99": round(percentile(drawdowns, 0.99) or 0, 2),
            "worst_sampled": round(max(drawdowns), 2),
        },
    }


def wallet_summary(signals: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [signal for signal in signals if signal["eligible"]]
    flat = [number(signal["return"]) for signal in eligible]
    return {
        "moneyline_markets": len(signals),
        "eligible_signals": len(eligible),
        "eligible_win_rate": (
            round(sum(signal["won"] for signal in eligible) / len(eligible), 4)
            if eligible
            else None
        ),
        "eligible_flat_roi": round(sum(flat) / len(flat), 4) if flat else None,
        "two_sided_or_material_rate": (
            round(
                sum(
                    signal["status"] in {"MATERIAL_HEDGE", "TWO_SIDED"}
                    for signal in signals
                )
                / len(signals),
                4,
            )
            if signals
            else None
        ),
        "median_relative_units": (
            round(statistics.median(signal["relative_units"] for signal in signals), 3)
            if signals
            else None
        ),
    }


def run(
    wallet_path: Path,
    *,
    through_date: str,
    holdout_start: str,
    iterations: int,
    seed: int,
    include_play_ledger: bool = False,
    provider_cache_dir: Path | None = None,
) -> dict[str, Any]:
    wallets = load_wallets(wallet_path).enabled_wallets
    all_signals: list[dict[str, Any]] = []
    metadata: dict[str, dict[str, Any]] = {}

    scoped_wallets = []
    for wallet in wallets:
        policy = wallet.category_signal_roles.get("mlb")
        if not policy:
            continue
        unit = number(policy.get("unit_baseline_usd") or wallet.base_unit)
        if unit <= 0:
            continue
        scoped_wallets.append((wallet, policy, unit))

    closed_rows_by_address: dict[str, list[dict[str, Any]]] = {}
    if provider_cache_dir:
        provider_cache_dir.mkdir(parents=True, exist_ok=True)
    for wallet, _, _ in scoped_wallets:
        cache_path = (
            provider_cache_dir / f"{wallet.address.lower()}.json"
            if provider_cache_dir
            else None
        )
        if cache_path and cache_path.exists():
            closed_rows_by_address[wallet.address] = json.loads(
                cache_path.read_text(encoding="utf-8")
            )
            continue
        observed_count = int(
            number((wallet.wallet_forensics or {}).get("closed_rows"))
        )
        requested_count = observed_count + 100 if observed_count else 20_000
        rows = PolymarketClient(max_retries=8).get_closed_positions(
            wallet.address, requested_count
        )
        closed_rows_by_address[wallet.address] = rows
        if cache_path:
            cache_path.write_text(
                json.dumps(rows, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )

    for wallet, policy, unit in scoped_wallets:
        rows = closed_rows_by_address[wallet.address]
        signals = wallet_signals(
            rows,
            label=wallet.label,
            unit=unit,
            minimum_units=number(policy.get("minimum_originator_units")),
            quality_weight=number(policy.get("quality_weight")),
            role=str(policy.get("role") or ""),
            through_date=through_date,
        )
        all_signals.extend(signals)
        metadata[wallet.label] = {
            "address": wallet.address,
            "unit_baseline_usd": unit,
            "minimum_originator_units": number(
                policy.get("minimum_originator_units")
            ),
            "quality_weight": number(policy.get("quality_weight")),
            "role": policy.get("role"),
            "structural_cohort": (
                "PRECISION_CORE"
                if wallet.label in CORE_LABELS
                else "PORTFOLIO_CONFIRMER"
                if wallet.label in PORTFOLIO_LABELS
                else "OTHER"
            ),
            **wallet_summary(signals),
        }

    by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for signal in all_signals:
        by_condition[str(signal["condition_id"])].append(signal)

    strategy_names = (
        "BROAD_EQUAL",
        "BROAD_CONSENSUS_2",
        "PRECISION_ONLY",
        "STRICT_CORE_CONSENSUS",
        "HYBRID_CORE_WITH_CONFIRMERS",
        "HYBRID_CONSENSUS_2",
    )
    plays = {
        strategy: [
            play
            for market_signals in by_condition.values()
            if (play := make_play(strategy, market_signals)) is not None
        ]
        for strategy in strategy_names
    }
    report = {
        "methodology": {
            "scope": "Standard MLB moneylines only",
            "through_date": through_date,
            "holdout_start": holdout_start,
            "entry_price_proxy": "Median selected-wallet average entry price",
            "signal_grain": "Wallet x exact condition after opposing outcome netting",
            "eligibility": "Configured wallet unit and originator threshold; clean or minor hedge only",
            "known_limitation": (
                "Closed-position data does not reconstruct the exact signal visible "
                "two hours before first pitch. Results are strategy-screening evidence, "
                "not an executable forward return guarantee."
            ),
        },
        "cohorts": {
            "precision_core": sorted(CORE_LABELS),
            "portfolio_confirmers": sorted(PORTFOLIO_LABELS),
        },
        "wallets": metadata,
        "full_history": {
            strategy: {
                "performance": summarize(strategy_plays),
                "price_stress": {
                    "two_points": price_stress(strategy_plays, 0.02),
                    "five_points": price_stress(strategy_plays, 0.05),
                },
                "bootstrap": bootstrap_days(
                    strategy_plays, iterations=iterations, seed=seed
                ),
            }
            for strategy, strategy_plays in plays.items()
        },
        "holdout": {
            strategy: {
                "performance": summarize(holdout_plays),
                "price_stress": {
                    "two_points": price_stress(holdout_plays, 0.02),
                    "five_points": price_stress(holdout_plays, 0.05),
                },
                "bootstrap": bootstrap_days(
                    holdout_plays,
                    iterations=iterations,
                    seed=seed + 1,
                ),
            }
            for strategy, strategy_plays in plays.items()
            for holdout_plays in [
                [
                    play
                    for play in strategy_plays
                    if str(play["date"]) >= holdout_start
                ]
            ]
        },
        "play_samples": {
            strategy: sorted(
                strategy_plays,
                key=lambda play: (play["date"], play["condition_id"]),
                reverse=True,
            )[:10]
            for strategy, strategy_plays in plays.items()
        },
    }
    if include_play_ledger:
        report["play_ledger"] = {
            strategy: sorted(
                strategy_plays,
                key=lambda play: (play["date"], play["condition_id"]),
            )
            for strategy, strategy_plays in plays.items()
        }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wallets", type=Path, default=ROOT / "wallets.json")
    parser.add_argument("--through-date", default="2026-07-26")
    parser.add_argument("--holdout-start", default="2026-06-01")
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260727)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run(
        args.wallets,
        through_date=args.through_date,
        holdout_start=args.holdout_start,
        iterations=args.iterations,
        seed=args.seed,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
