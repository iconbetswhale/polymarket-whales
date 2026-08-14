from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.simulate_two_wallet_mlb_5000 import (
    OUTPUT as INVALID_OUTPUT,
    position_return,
    simulate,
    stake_from_conviction,
    summarize_actual,
)


UNKEPT_SOURCE = Path(
    r"C:\Users\15617\.codex\codex-remote-attachments\019f63cc-fa15-7ff3-aab8-b15eddcb9a08\271DAA48-97D8-4A50-B239-88DFA6BEA078\1-api-response-32-1-.json"
)
ZEALOUS_SOURCE = Path(
    r"C:\Users\15617\.codex\codex-remote-attachments\019f63cc-fa15-7ff3-aab8-b15eddcb9a08\271DAA48-97D8-4A50-B239-88DFA6BEA078\2-api-response-33-.json"
)
EVENTS = ROOT / "outputs" / "two-wallet-mlb-sim-source" / "unkempt-event-catalog.json"
CLOSED = ROOT / "outputs" / "two-wallet-mlb-sim-source" / "unkempt_image-closed.json"
OUTPUT = ROOT / "outputs" / "unkempt-mlb-2h-checkpoint-5000-corrected-2026-08-08.json"
UNIT_USD = 3_000.0


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def iso_timestamp(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def main() -> None:
    rows = json.loads(UNKEPT_SOURCE.read_text(encoding="utf-8-sig"))
    zealous = json.loads(ZEALOUS_SOURCE.read_text(encoding="utf-8-sig"))
    events = json.loads(EVENTS.read_text(encoding="utf-8"))
    closed = json.loads(CLOSED.read_text(encoding="utf-8"))
    starts = {
        slug: iso_timestamp(
            str(event.get("startTime") or event.get("markets", [{}])[0].get("gameStartTime"))
        )
        for slug, event in events.items()
    }
    resolutions: dict[str, dict[str, float]] = defaultdict(dict)
    for row in closed:
        event_slug = str(row.get("eventSlug") or "")
        if event_slug.startswith("mlb-") and str(row.get("slug") or "") == event_slug:
            resolutions[str(row.get("conditionId") or "").lower()][str(row.get("asset") or "")] = number(row.get("curPrice"))

    mlb_rows = [
        row
        for row in rows
        if str(row.get("eventSlug") or "").startswith("mlb-")
        and str(row.get("slug") or "") == str(row.get("eventSlug") or "")
    ]
    timing = Counter()
    grouped: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"cost": 0.0, "shares": 0.0})
    )
    metadata: dict[str, dict[str, Any]] = {}
    for row in mlb_rows:
        start = starts[str(row["eventSlug"])]
        delta = start - int(row["timestamp"])
        timing["over_2h_before"] += int(delta >= 7_200)
        timing["inside_2h_pregame"] += int(0 <= delta < 7_200)
        timing["after_start"] += int(delta < 0)
        if delta < 7_200:
            continue
        condition = str(row.get("conditionId") or "").lower()
        asset = str(row.get("asset") or "")
        shares = number(row.get("size"))
        grouped[condition][asset]["shares"] += shares
        grouped[condition][asset]["cost"] += shares * number(row.get("price"))
        metadata[condition] = row

    plays: list[dict[str, Any]] = []
    audit = Counter()
    for condition, outcomes in grouped.items():
        audit["markets_at_checkpoint"] += 1
        ordered = sorted(outcomes.items(), key=lambda pair: pair[1]["cost"], reverse=True)
        asset, leader = ordered[0]
        opposition = sum(values["cost"] for _, values in ordered[1:])
        ratio = opposition / leader["cost"] if leader["cost"] else 0.0
        net = leader["cost"] - opposition
        if ratio > 0.20:
            audit["material_or_two_sided"] += 1
            continue
        if net < 0.25 * UNIT_USD:
            audit["below_quarter_unit"] += 1
            continue
        resolved = resolutions.get(condition) or {}
        if asset in resolved and resolved[asset] in (0.0, 1.0):
            won = resolved[asset] == 1.0
        elif sum(value == 1.0 for value in resolved.values()) == 1:
            won = False
        else:
            audit["unresolved_or_missing"] += 1
            continue
        price = leader["cost"] / leader["shares"]
        relative = net / UNIT_USD
        stake = stake_from_conviction(relative)
        row = metadata[condition]
        plays.append(
            {
                "condition_id": condition,
                "event_slug": row["eventSlug"],
                "date": str(row["eventSlug"])[-10:],
                "outcome": row["outcome"],
                "price": price,
                "won": won,
                "net_cost_usd": net,
                "relative_units": relative,
                "stake_units": stake,
                "pnl_units": stake * position_return(price, won),
            }
        )
    audit["eligible_signals"] = len(plays)
    zealous_mlb_fills = sum(
        str(row.get("eventSlug") or "").startswith("mlb-") for row in zealous
    )
    result = {
        "status": "CORRECTED_TWO_HOUR_CHECKPOINT_REPLAY",
        "supersedes": str(INVALID_OUTPUT),
        "method": {
            "checkpoint": "Only fills timestamped at least two hours before scheduled first pitch are visible.",
            "scope": "MLB moneylines only; BUY fills in the supplied recent export.",
            "netting": "Both outcomes are netted; opposing ratio above 20% and net exposure below 0.25 measured units are excluded.",
            "settlement": "Winner is determined from settled token curPrice 1/0, never from realizedPnl sign.",
            "sizing": "Conviction ladder with no maximum cap, using a $3,000 measured net unit.",
            "simulation": "5,000 calendar-day block-bootstrap paths, including zero-play days.",
        },
        "data_quality": {
            "unkempt_attached_mlb_moneyline_fills": len(mlb_rows),
            "fill_timing": dict(timing),
            "zealous_attached_mlb_fills": zealous_mlb_fills,
            "zealous_checkpoint_simulation_available": zealous_mlb_fills > 0,
            "warning": "The Unkempt export is capped at 10,000 rows and BUY-only. Results are a recent-window checkpoint reconstruction, not a complete lifetime executable backtest.",
        },
        "signal_audit": dict(audit),
        "historical_sample": summarize_actual(plays),
        "simulations": {
            str(days): simulate(plays, days, 9200 + days) for days in (7, 30, 60)
        },
    }
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
