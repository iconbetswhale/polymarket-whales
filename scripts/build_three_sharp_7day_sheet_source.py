from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import simulate_lead_cohorts_main_markets as base
from scripts._tmp_five_wallet_recap import weighted_median
from three_sharp_strategy import SHARPS, recommendation_units


AS_OF = date(2026, 8, 4)
START = AS_OF - timedelta(days=6)
SOURCE_DIR = ROOT / "outputs" / "three-sharp-7day-source-2026-08-04"
OUTPUT = ROOT / "outputs" / "three-sharp-7day-recap-2026-08-04.json"

WALLETS: dict[str, dict[str, Any]] = {
    "Formal-Cupcake": {
        "address": "0xb8c842bc049bf208f73354c7b037b811d741d8a4",
        "unit": 1300.0,
        "minimum_units": 1.0,
        "copy_weight": 1.00,
    },
    "Soarin22": {
        "address": "0x84dbb7103982e3617704a2ed7d5b39691952aeeb",
        "unit": 7800.0,
        "minimum_units": 0.5,
        "copy_weight": 0.95,
    },
    "phonesculptor": {
        "address": "0xf1528f12e645462c344799b62b1b421a6a4c64aa",
        "unit": 29000.0,
        "minimum_units": 0.5,
        "copy_weight": 0.80,
    },
}


def configure() -> None:
    base.THROUGH_DATE = AS_OF.isoformat()
    base.SEASON_START = START.isoformat()
    base.SOURCE_DIR = SOURCE_DIR
    base.EVENTS_FILE = SOURCE_DIR / "event-catalog.json"
    base.WALLETS = WALLETS


def pnl_for(price: float, won: bool, stake_units: float) -> float:
    return stake_units * base.position_return(price, won)


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    settled = [row for row in rows if row.get("decision") == "BET"]
    wins = sum(bool(row["won"]) for row in settled)
    losses = len(settled) - wins
    stake = sum(float(row["stake_units"]) for row in settled)
    profit = sum(float(row["profit_units"]) for row in settled)
    return {
        "bets": len(settled),
        "wins": wins,
        "losses": losses,
        "record": f"{wins}-{losses}",
        "hit_rate": wins / len(settled) if settled else None,
        "staked_units": stake,
        "profit_units": profit,
        "roi": profit / stake if stake else None,
        "average_bet_units": stake / len(settled) if settled else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    configure()
    if args.refresh:
        base.refresh_sources()

    events = json.loads(base.EVENTS_FILE.read_text(encoding="utf-8"))
    main_markets = base.build_main_market_map(events)
    market_meta: dict[str, dict[str, str]] = {}
    for event_slug, event in events.items():
        if not isinstance(event, dict):
            continue
        event_title = str(event.get("title") or event.get("question") or event_slug)
        for market in event.get("markets", []):
            if not isinstance(market, dict):
                continue
            condition_id = str(
                market.get("conditionId") or market.get("condition_id") or ""
            ).lower()
            if condition_id:
                market_meta[condition_id] = {
                    "event_title": event_title,
                    "market_title": str(
                        market.get("question") or market.get("title") or event_title
                    ),
                }
    signal_map: dict[str, list[dict[str, Any]]] = {}
    audits: dict[str, Any] = {}
    for label, config in WALLETS.items():
        closed, current = base.load_source_rows(label)
        reconciled, reconciliation = base.reconcile_positions(closed, current)
        signals, signal_audit = base.build_wallet_signals(
            label, config, reconciled, main_markets
        )
        signal_map[label] = signals
        audits[label] = {**reconciliation, **signal_audit}

    eligible: dict[str, list[dict[str, Any]]] = defaultdict(list)
    wallet_rows: list[dict[str, Any]] = []
    for label, signals in signal_map.items():
        for signal in signals:
            if not signal.get("eligible"):
                continue
            eligible[str(signal["condition_id"])].append(signal)
            wallet_rows.append(
                {
                    **signal,
                    "standardized_stake_units": 1.0,
                    "standardized_profit_units": pnl_for(
                        float(signal["price"]), bool(signal["won"]), 1.0
                    ),
                }
            )

    decisions: list[dict[str, Any]] = []
    decision_counts: Counter[str] = Counter()
    for condition_id, signals in eligible.items():
        outcomes: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for signal in signals:
            outcomes[str(signal["outcome"])].append(signal)
        sample = signals[0]
        meta = market_meta.get(condition_id, {})
        common = {
            "condition_id": condition_id,
            "date": sample["date"],
            "event_slug": sample["event_slug"],
            "market_slug": sample["market_slug"],
            "event_title": meta.get("event_title", str(sample["event_slug"])),
            "market_title": meta.get("market_title", str(sample["market_slug"])),
            "market_type": sample["market_type"],
        }
        if len(outcomes) > 1:
            decision_counts["DISAGREEMENT_VETO"] += 1
            decisions.append(
                {
                    **common,
                    "decision": "VETO",
                    "consensus_type": "Disagreement",
                    "supporter_count": len(signals),
                    "supporters": sorted(str(signal["wallet"]) for signal in signals),
                    "sides": " | ".join(
                        f"{outcome}: {', '.join(sorted(str(s['wallet']) for s in side))}"
                        for outcome, side in sorted(outcomes.items())
                    ),
                    "outcome": "",
                    "entry_price_proxy": None,
                    "stake_units": 0.0,
                    "won": None,
                    "profit_units": 0.0,
                }
            )
            continue

        outcome, selected = next(iter(outcomes.items()))
        won_values = {bool(signal["won"]) for signal in selected}
        if len(won_values) != 1:
            decision_counts["INCONSISTENT_SETTLEMENT"] += 1
            continue
        supporters = sorted(str(signal["wallet"]) for signal in selected)
        addresses = [str(WALLETS[label]["address"]) for label in supporters]
        relative = {
            str(WALLETS[str(signal["wallet"])]["address"]): float(
                signal.get("relative_units") or 0.0
            )
            for signal in selected
        }
        sizing = recommendation_units(addresses, relative)
        price = weighted_median(
            [
                (
                    float(signal["price"]),
                    float(WALLETS[str(signal["wallet"])]["copy_weight"]),
                )
                for signal in selected
            ]
        )
        won = won_values.pop()
        stake_units = float(sizing["units"])
        consensus_type = "Agreement" if len(supporters) >= 2 else "Single sharp"
        decision_counts["AGREEMENT" if len(supporters) >= 2 else "SINGLE_SHARP"] += 1
        decisions.append(
            {
                **common,
                "decision": "BET",
                "consensus_type": consensus_type,
                "supporter_count": len(supporters),
                "supporters": supporters,
                "sides": outcome,
                "outcome": outcome,
                "entry_price_proxy": price,
                "stake_units": stake_units,
                "won": won,
                "profit_units": pnl_for(price, won, stake_units),
                "relative_units_by_wallet": relative,
                "sizing": sizing,
            }
        )

    decisions.sort(
        key=lambda row: (
            str(row["date"]),
            str(row["event_slug"]),
            str(row["market_type"]),
            str(row["condition_id"]),
        )
    )
    wallet_rows.sort(
        key=lambda row: (
            str(row["date"]),
            str(row["wallet"]),
            str(row["event_slug"]),
            str(row["condition_id"]),
        )
    )

    by_market = {
        market_type: summary(
            [row for row in decisions if row.get("market_type") == market_type]
        )
        for market_type in ("moneyline", "spread", "total")
    }
    by_consensus = {
        label: summary(
            [row for row in decisions if row.get("consensus_type") == label]
        )
        for label in ("Single sharp", "Agreement", "Disagreement")
    }
    by_wallet: dict[str, Any] = {}
    for label in WALLETS:
        rows = [row for row in wallet_rows if row["wallet"] == label]
        wins = sum(bool(row["won"]) for row in rows)
        profit = sum(float(row["standardized_profit_units"]) for row in rows)
        by_wallet[label] = {
            "qualifying_positions": len(rows),
            "wins": wins,
            "losses": len(rows) - wins,
            "record": f"{wins}-{len(rows)-wins}",
            "hit_rate": wins / len(rows) if rows else None,
            "standardized_profit_units": profit,
            "standardized_roi": profit / len(rows) if rows else None,
            "agreements_supported": sum(
                row.get("decision") == "BET"
                and label in row.get("supporters", [])
                and int(row.get("supporter_count") or 0) >= 2
                for row in decisions
            ),
            "disagreements_involved": sum(
                row.get("decision") == "VETO" and label in row.get("supporters", [])
                for row in decisions
            ),
        }

    daily = {}
    for offset in range(7):
        value = (START + timedelta(days=offset)).isoformat()
        daily[value] = summary([row for row in decisions if row["date"] == value])

    payload = {
        "title": "Three-sharp seven-day performance recap",
        "generated_at": "2026-08-04",
        "period": {"start": START.isoformat(), "end": AS_OF.isoformat()},
        "scope": (
            "Settled MLB full-game moneylines, main +/-1.5 run lines, and the "
            "highest-volume full-game total for Formal-Cupcake, Soarin22, and "
            "phonesculptor. Qualifying cross-wallet opposition is vetoed."
        ),
        "performance_basis": (
            "Current THREE_SHARP_QK_CONVICTION_2X_V3 model sizing. Historical entry "
            "uses the copy-weighted median sharp entry price proxy; it is not a "
            "timestamp-perfect executable sportsbook quote."
        ),
        "wallets": WALLETS,
        "summary": summary(decisions),
        "agreement_counts": {
            "single_sharp_bets": int(decision_counts["SINGLE_SHARP"]),
            "agreed_bets": int(decision_counts["AGREEMENT"]),
            "disagreement_vetoes": int(decision_counts["DISAGREEMENT_VETO"]),
            "inconsistent_settlement_exclusions": int(
                decision_counts["INCONSISTENT_SETTLEMENT"]
            ),
        },
        "by_market_type": by_market,
        "by_consensus": by_consensus,
        "by_wallet": by_wallet,
        "daily": daily,
        "data_quality": audits,
        "decision_ledger": decisions,
        "wallet_signal_ledger": wallet_rows,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(OUTPUT)
    print(json.dumps({"summary": payload["summary"], "agreement_counts": payload["agreement_counts"], "by_market_type": by_market, "by_wallet": by_wallet}, indent=2))


if __name__ == "__main__":
    main()
