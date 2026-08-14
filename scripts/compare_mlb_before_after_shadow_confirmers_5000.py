from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from polymarket_client import PolymarketClient
from wallet_activity import normalize_trade_fills
from scripts._tmp_wallet_full_extraction import build_markets, snapshots
from scripts.simulate_corrected_mlb_weighted_model_5000 import (
    WALLETS,
    build_play,
    conviction_multiplier,
    load_signals,
)


HORIZONS = (7, 30, 60)
AS_OF = date(2026, 8, 10)
OUTPUT = ROOT / "outputs" / "mlb-before-after-dingwin-breakthebank-5000-2026-08-11.json"
OVERLAY_CACHE = ROOT / "analysis" / "outputs" / "dingwin-breakthebank-mlb-signals-2026-08-11.json"
DINGWIN_ATTACHMENT = Path(
    r"C:\Users\15617\.codex\codex-remote-attachments\019f682e-d751-7700-85f8-61e86956cf9d"
    r"\AA8F5042-B777-44F8-AECE-98BC756053E8\7-api-response-45-.json"
)

OVERLAYS: dict[str, dict[str, Any]] = {
    "Dingwin": {
        "address": "0x9fad8308ef6b6ed5320e53a290a3bd4ad91f5a9f",
        "unit": 1075.0,
        "minimum": 0.5,
        "weight": 0.20,
    },
    "BreakTheBank": {
        "address": "0xf0318c32136c2db7fec88b84869aee6a1106c80c",
        "unit": 14500.0,
        "minimum": 0.5,
        "weight": 0.10,
    },
}


def number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def summary(values: np.ndarray) -> dict[str, float]:
    return {
        "minimum_observed": float(np.min(values)),
        "p05": float(np.quantile(values, 0.05)),
        "p25": float(np.quantile(values, 0.25)),
        "median": float(np.median(values)),
        "mean": float(np.mean(values)),
        "p75": float(np.quantile(values, 0.75)),
        "p95": float(np.quantile(values, 0.95)),
        "maximum_observed": float(np.max(values)),
    }


def fetch_breakthebank_fills() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = OVERLAYS["BreakTheBank"]
    address = str(config["address"])
    client = PolymarketClient(request_timeout=20, max_retries=5)
    raw: list[dict[str, Any]] = []
    start = int(datetime(2026, 4, 10, tzinfo=timezone.utc).timestamp())
    window_end = int(datetime(2026, 8, 11, tzinfo=timezone.utc).timestamp())
    while window_end >= start:
        window_rows: list[dict[str, Any]] = []
        exhausted = False
        for offset in (0, 1000, 2000, 3000):
            rows = client._get_json(
                "https://data-api.polymarket.com/trades",
                {
                    "user": address,
                    "limit": 1000,
                    "offset": offset,
                    "takerOnly": "false",
                    "start": start,
                    "end": window_end,
                },
            )
            if not isinstance(rows, list):
                raise RuntimeError("Unexpected BreakTheBank trade payload")
            window_rows.extend(rows)
            if len(rows) < 1000:
                exhausted = True
                break
        raw.extend(window_rows)
        if exhausted or not window_rows:
            break
        next_end = min(int(row.get("timestamp") or 0) for row in window_rows) - 1
        if next_end >= window_end:
            break
        window_end = next_end
    fills, duplicates = normalize_trade_fills(address, raw)
    return fills, {"raw_rows": len(raw), "normalized_fills": len(fills), "duplicates": duplicates}


def signals_from_fills(
    label: str,
    fills: list[dict[str, Any]],
    event_cache_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cache = json.loads(event_cache_path.read_text(encoding="utf-8"))
    slugs = sorted({str(row.get("event_slug") or "") for row in fills if row.get("event_slug")})
    missing = [slug for slug in slugs if slug not in cache]
    if missing:
        client = PolymarketClient(request_timeout=20, max_retries=5)
        for offset in range(0, len(missing), 250):
            cache.update(client.get_events(missing[offset : offset + 250], max_workers=6))
            event_cache_path.write_text(json.dumps(cache), encoding="utf-8")
    plays, excluded = snapshots(fills, build_markets(cache))
    config = OVERLAYS[label]
    selected = []
    for row in plays:
        relative_units = number(row.get("net_exposure")) / float(config["unit"])
        if (
            row.get("sport") == "MLB"
            and row.get("market") == "Moneyline"
            and number(row.get("opposing_ratio")) < 0.10
            and relative_units + 0.01 >= float(config["minimum"])
        ):
            selected.append(
                {
                    "condition_id": str(row["condition_id"]),
                    "event_slug": str(row["event_slug"]),
                    "date": datetime.fromtimestamp(int(row["start"]), timezone.utc).date().isoformat(),
                    "wallet": label,
                    "outcome": str(row["selection"]),
                    "relative_units": relative_units,
                    "weight": float(config["weight"]),
                }
            )
    audit = {
        "resolved_positions": len(plays),
        "qualified_mlb_moneylines": len(selected),
        "exclusions": dict(excluded),
        "fill_start": datetime.fromtimestamp(min(int(row["timestamp"]) for row in fills), timezone.utc).isoformat(),
        "fill_end": datetime.fromtimestamp(max(int(row["timestamp"]) for row in fills), timezone.utc).isoformat(),
    }
    return selected, audit


def load_overlay_signals() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if OVERLAY_CACHE.exists():
        payload = json.loads(OVERLAY_CACHE.read_text(encoding="utf-8"))
        return list(payload["signals"]), dict(payload["audit"])

    dingwin_raw = json.loads(DINGWIN_ATTACHMENT.read_text(encoding="utf-8-sig"))
    dingwin_fills, dingwin_duplicates = normalize_trade_fills(
        str(OVERLAYS["Dingwin"]["address"]), dingwin_raw
    )
    dingwin, dingwin_audit = signals_from_fills(
        "Dingwin",
        dingwin_fills,
        ROOT / "analysis" / "outputs" / "batch-seven-wallet-events-2026-08-10.json",
    )
    dingwin_audit.update({"raw_rows": len(dingwin_raw), "duplicates": dingwin_duplicates})

    break_fills, break_fetch = fetch_breakthebank_fills()
    break_signals, break_audit = signals_from_fills(
        "BreakTheBank",
        break_fills,
        ROOT / "analysis" / "outputs" / "breakthebank-events-2026-08-10.json",
    )
    break_audit.update(break_fetch)

    payload = {
        "generated_on": date.today().isoformat(),
        "method": "Wallet positions reconstructed 30 minutes before event start; exact settled MLB full-game moneyline; <10% opposing exposure; wallet-specific minimum size.",
        "signals": [*dingwin, *break_signals],
        "audit": {"Dingwin": dingwin_audit, "BreakTheBank": break_audit},
    }
    OVERLAY_CACHE.parent.mkdir(parents=True, exist_ok=True)
    OVERLAY_CACHE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return list(payload["signals"]), dict(payload["audit"])


def confirmer_weight(rows: list[dict[str, Any]]) -> float:
    return sum(
        float(row["weight"]) * min(2.0, math.sqrt(max(0.0, float(row["relative_units"]))))
        for row in rows
    )


def build_paired_play(
    base_signals: list[dict[str, Any]], overlay_signals: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, str | None]:
    old_play, reason = build_play(base_signals)
    if old_play is None:
        return None, reason

    eligible = [row for row in base_signals if row["eligible"]]
    primary = [row for row in eligible if row["role"] == "PRIMARY"]
    conditional = [row for row in eligible if row["role"] == "CONDITIONAL"]
    confirmers = [row for row in eligible if row["role"] == "CONFIRMER"]
    outcome = str(old_play["outcome"])
    agreeing_conditional = [row for row in conditional if row["outcome"] == outcome]
    opposing_conditional = [row for row in conditional if row["outcome"] != outcome]
    old_agree = [row for row in confirmers if row["outcome"] == outcome]
    old_oppose = [row for row in confirmers if row["outcome"] != outcome]
    new_agree = [row for row in overlay_signals if row["outcome"] == outcome]
    new_oppose = [row for row in overlay_signals if row["outcome"] != outcome]

    adjusted_primary = [
        float(row["weight"]) * conviction_multiplier(float(row["relative_units"]))
        for row in primary
    ]
    base_consensus = 1.0
    if len(primary) == 2:
        base_consensus += 0.25
    if agreeing_conditional:
        base_consensus += 0.15
    if opposing_conditional:
        base_consensus -= 0.15

    old_confirm = confirmer_weight(old_agree)
    old_oppose_weight = confirmer_weight(old_oppose)
    overlay_confirm = confirmer_weight(new_agree)
    overlay_oppose = confirmer_weight(new_oppose)
    old_portfolio = max(0.50, 1.0 + 0.12 * old_confirm - 0.15 * old_oppose_weight)
    new_portfolio = max(
        0.50,
        1.0 + 0.12 * (old_confirm + overlay_confirm) - 0.15 * (old_oppose_weight + overlay_oppose),
    )
    pre_portfolio = mean(adjusted_primary) * base_consensus
    old_units = min(3.0, max(0.25, pre_portfolio * old_portfolio))
    new_units = min(3.0, max(0.25, pre_portfolio * new_portfolio))
    recorded_old_units = float(old_play["stake_units"])
    if abs(old_units - recorded_old_units) > 1e-9:
        raise AssertionError(
            f"Old-model stake reconstruction drifted: {old_units} != {recorded_old_units}"
        )
    price = median([float(row["price"]) for row in primary])
    won = bool(primary[0]["won"])
    return_per_unit = (1.0 - price) / price if won else -1.0
    return {
        **old_play,
        "old_stake_units": recorded_old_units,
        "updated_stake_units": new_units,
        "return_per_unit": return_per_unit,
        "overlay_agree": [row["wallet"] for row in new_agree],
        "overlay_oppose": [row["wallet"] for row in new_oppose],
        "overlay_confirm_weight": overlay_confirm,
        "overlay_oppose_weight": overlay_oppose,
    }, None


def max_drawdown_units(rows: list[dict[str, Any]], stake_field: str) -> float:
    equity = peak = drawdown = 0.0
    for row in rows:
        equity += float(row[stake_field]) * float(row["return_per_unit"])
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def replay(rows: list[dict[str, Any]], stake_field: str) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (row["date"], row["condition_id"]))
    stakes = sum(float(row[stake_field]) for row in ordered)
    profit = sum(float(row[stake_field]) * float(row["return_per_unit"]) for row in ordered)
    wins = sum(bool(row["won"]) for row in ordered)
    return {
        "bets": len(ordered),
        "record": f"{wins}-{len(ordered) - wins}",
        "win_rate": wins / len(ordered) if ordered else None,
        "staked_units": stakes,
        "profit_units": profit,
        "betting_roi": profit / stakes if stakes else None,
        "average_stake_units": stakes / len(ordered) if ordered else None,
        "maximum_drawdown_units": max_drawdown_units(ordered, stake_field),
    }


def paired_simulation(
    rows: list[dict[str, Any]], *, days: int, paths: int, seed: int, start: date, end: date
) -> dict[str, Any]:
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_day[str(row["date"])].append(row)
    blocks = [
        by_day[(start + timedelta(days=offset)).isoformat()]
        for offset in range((end - start).days + 1)
    ]
    rng = np.random.default_rng(seed)
    sampled = rng.integers(0, len(blocks), size=(paths, days))
    arms: dict[str, dict[str, np.ndarray]] = {}
    for arm, stake_field in (
        ("old_model", "old_stake_units"),
        ("updated_model", "updated_stake_units"),
    ):
        profits = np.zeros(paths)
        staked = np.zeros(paths)
        draws = np.zeros(paths)
        bets = np.zeros(paths)
        for index in range(paths):
            path_rows: list[dict[str, Any]] = []
            for block_index in sampled[index]:
                path_rows.extend(blocks[int(block_index)])
            bets[index] = len(path_rows)
            equity = peak = worst = 0.0
            for row in path_rows:
                stake = float(row[stake_field])
                pnl = stake * float(row["return_per_unit"])
                staked[index] += stake
                equity += pnl
                peak = max(peak, equity)
                worst = max(worst, peak - equity)
            profits[index] = equity
            draws[index] = worst
        arms[arm] = {"profit": profits, "staked": staked, "drawdown": draws, "bets": bets}

    rendered = {}
    for arm, values in arms.items():
        roi = np.divide(
            values["profit"], values["staked"], out=np.zeros_like(values["profit"]), where=values["staked"] > 0
        )
        rendered[arm] = {
            "bets": summary(values["bets"]),
            "profit_units": summary(values["profit"]),
            "betting_roi": summary(roi),
            "maximum_drawdown_units": summary(values["drawdown"]),
            "probability_profitable": float(np.mean(values["profit"] > 0)),
        }
    delta = arms["updated_model"]["profit"] - arms["old_model"]["profit"]
    return {
        "arms": rendered,
        "paired_updated_minus_old": {
            "profit_units": summary(delta),
            "probability_updated_more_profitable": float(np.mean(delta > 1e-12)),
            "probability_old_more_profitable": float(np.mean(delta < -1e-12)),
            "probability_equal": float(np.mean(np.abs(delta) <= 1e-12)),
        },
    }


def run(paths: int, seed: int) -> dict[str, Any]:
    base_signals = [signal for label, policy in WALLETS.items() for signal in load_signals(label, policy)]
    overlay_signals, overlay_audit = load_overlay_signals()
    base_by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    overlay_by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in base_signals:
        base_by_condition[str(row["condition_id"])].append(row)
    for row in overlay_signals:
        overlay_by_condition[str(row["condition_id"])].append(row)

    plays = []
    exclusions: dict[str, int] = defaultdict(int)
    for condition, rows in base_by_condition.items():
        play, reason = build_paired_play(rows, overlay_by_condition.get(condition, []))
        if play:
            plays.append(play)
        elif reason:
            exclusions[str(reason)] += 1

    end = min(AS_OF, max(date.fromisoformat(str(row["date"])) for row in plays))
    start = end - timedelta(days=59)
    evaluation = [row for row in plays if start <= date.fromisoformat(str(row["date"])) <= end]
    if not evaluation:
        raise RuntimeError("No common recent MLB plays available")

    changed = [row for row in evaluation if abs(float(row["updated_stake_units"]) - float(row["old_stake_units"])) > 1e-12]
    overlap = {
        "evaluation_plays": len(evaluation),
        "plays_resized": len(changed),
        "same_side_dingwin": sum("Dingwin" in row["overlay_agree"] for row in evaluation),
        "opposite_dingwin": sum("Dingwin" in row["overlay_oppose"] for row in evaluation),
        "same_side_breakthebank": sum("BreakTheBank" in row["overlay_agree"] for row in evaluation),
        "opposite_breakthebank": sum("BreakTheBank" in row["overlay_oppose"] for row in evaluation),
        "both_same_side": sum(set(row["overlay_agree"]) == {"Dingwin", "BreakTheBank"} for row in evaluation),
    }

    windows: dict[str, Any] = {}
    for days in HORIZONS:
        observed_start = end - timedelta(days=days - 1)
        observed = [row for row in evaluation if date.fromisoformat(str(row["date"])) >= observed_start]
        windows[str(days)] = {
            "historical_replay": {
                "old_model": replay(observed, "old_stake_units"),
                "updated_model": replay(observed, "updated_stake_units"),
            },
            "simulation": paired_simulation(
                evaluation, days=days, paths=paths, seed=seed + days, start=start, end=end
            ),
        }

    return {
        "title": "MLB old model vs Dingwin + BreakTheBank shadow sizing overlays",
        "generated_on": date.today().isoformat(),
        "simulations_per_horizon": paths,
        "seed": seed,
        "source_date_range": {"start": start.isoformat(), "end": end.isoformat()},
        "scope": "Settled MLB full-game moneylines. Existing production eligibility is unchanged; Dingwin and BreakTheBank can only resize an already-qualified play.",
        "old_model": "Existing weighted-directional MLB model before Dingwin and BreakTheBank.",
        "updated_model": "Same model plus Dingwin (0.20) and BreakTheBank (0.10) exact-market shadow sizing overlays; no origination and no veto power.",
        "method": "Paired seeded calendar-day block bootstrap including zero-play days. Both arms receive identical dates, markets, outcomes, and price proxies; only stake sizing differs.",
        "limitations": [
            "Base-model historical positions use final settled wallet positions and wallet average entry proxies.",
            "Dingwin and BreakTheBank overlays are reconstructed at 30 minutes before start, so overlay timing is stricter than the base source.",
            "No sportsbook execution slippage, limits, fees, or missed fills are modeled.",
            "Results quantify the observed sizing overlay sample and are not a guarantee of future profitability.",
        ],
        "overlap_audit": overlap,
        "overlay_source_audit": overlay_audit,
        "exclusions": dict(sorted(exclusions.items())),
        "stake_distribution": {
            "old_model": summary(np.asarray([row["old_stake_units"] for row in evaluation], dtype=float)),
            "updated_model": summary(np.asarray([row["updated_stake_units"] for row in evaluation], dtype=float)),
        },
        "windows": windows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20260811)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    payload = run(args.paths, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    print(json.dumps({"overlap_audit": payload["overlap_audit"], "windows": payload["windows"]}, indent=2))


if __name__ == "__main__":
    main()
