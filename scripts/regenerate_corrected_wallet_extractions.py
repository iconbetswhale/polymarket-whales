from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.wallet_full_extraction import (
    aggregate_closed,
    number,
    performance,
    percentile,
)
from polymarket_client import PolymarketClient


ET = ZoneInfo("America/New_York")
SOURCE = ROOT / "outputs" / "cross-sport-source"
OUTPUT_DIR = ROOT / "outputs" / "corrected-wallet-extractions-2026-08-09"
CONSOLIDATED = ROOT / "outputs" / "corrected-all-wallet-matrix-2026-08-09.json"


WALLETS = {
    "0x4f2": "0x4f29e103339919c4baaea2a60195cf1c8bb27a7e",
    "1winstreak1": "0xbca08c1bc204a34f2fddbe47b438b9bd42ac9705",
    "bagwell306": "0x9c76cdb43fb46454da005fbc82047a64a18ec926",
    "breakthebank": "0xf0318c32136c2db7fec88b84869aee6a1106c80c",
    "c63amg": "0xb31e41965df4ab8014de4c4d8da9deff0a6ac120",
    "ferrarichampions2026": "0xfe787d2da716d60e8acff57fb87eb13cd4d10319",
    "formal-cupcake": "0xb8c842bc049bf208f73354c7b037b811d741d8a4",
    "homerunhazard": "0x5268527977f700f9bf9b6d5cd843859e4e70135d",
    "ironclad-housework": "0x9703676286b93c2eca71ca96e8757104519a69c2",
    "kkookkoo": "0x26b46988d027c6c03cfa12a7c0c6d778be49b8a9",
    "lilybaeum": "0x01c78f8873c0c86d6b6b92ff627e3802237ee995",
    "overtimemarkets-singles": "0x93118ca14040b05c7a7d7c71cd4c2d6304a67c73",
    "phonesculptor": "0xf1528f12e645462c344799b62b1b421a6a4c64aa",
    "soarin22": "0x84dbb7103982e3617704a2ed7d5b39691952aeeb",
    "sportmaster777": "0x32ed517a571c01b6e9adecf61ba81ca48ff2f960",
    "surfandturf": "0x9f2fe025f84839ca81dd8e0338892605702d2ca8",
    "thornydevil": "0xa7590cd0d4a5620fe4651dc0e6569817e6b31119",
    "unkempt-image": "0xd106952ebf30a3125affd8a23b6c1f30c35fc79c",
    "unnamed-c4c1": "0xc4c1065d8dba0be248a3994fdefd97bd83ff6b32",
    "wordylittleneck": "0x3dfb153c197d4c19d3b31c1ecd2c7b6860eeabaf",
    "zealous-violence": "0xa697d0b3fff7d285a0f92d6ee03a7f97809e59d5",
}


def normalize_settled_current(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    settled: list[dict[str, Any]] = []
    for row in rows:
        cur_price = number(row.get("curPrice"))
        if not (bool(row.get("redeemable")) or cur_price <= 0.001 or cur_price >= 0.999):
            continue
        normalized = dict(row)
        normalized["realizedPnl"] = number(row.get("cashPnl")) + number(row.get("realizedPnl"))
        settled.append(normalized)
    return settled


def fetch_current_bounded(
    client: PolymarketClient, address: str, max_rows: int = 20_000
) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    offset = 0
    limit = 500
    signatures: set[tuple[str, str]] = set()
    while len(rows) < max_rows:
        page = client._get_json(
            "https://data-api.polymarket.com/positions",
            {
                "user": address,
                "limit": min(limit, max_rows - len(rows)),
                "offset": offset,
                "sizeThreshold": 0,
                "sortBy": "CURRENT",
                "sortDirection": "DESC",
            },
        )
        if not isinstance(page, list):
            raise RuntimeError("Unexpected current-position payload")
        if not page:
            return rows, False
        signature = (
            str(page[0].get("asset") or page[0].get("conditionId") or ""),
            str(page[-1].get("asset") or page[-1].get("conditionId") or ""),
        )
        if signature in signatures:
            return rows, True
        signatures.add(signature)
        rows.extend(row for row in page if isinstance(row, dict))
        if len(page) < limit:
            return rows, False
        offset += limit
    return rows, True


def extract(name: str, address: str) -> tuple[str, dict[str, Any]]:
    client = PolymarketClient(max_retries=7)
    closed_path = SOURCE / f"{name}-closed.json"
    if not closed_path.exists():
        raise FileNotFoundError(f"Missing closed-position source: {closed_path}")
    closed = json.loads(closed_path.read_text(encoding="utf-8"))
    if not isinstance(closed, list):
        raise ValueError(f"Closed-position source is not a list: {closed_path}")
    if len(closed) == 5_000:
        closed = client.get_closed_positions(address, 20_000)
        closed_path.write_text(
            json.dumps(closed, indent=2) + "\n", encoding="utf-8"
        )
    current, current_capped = fetch_current_bounded(client, address)
    settled_current = normalize_settled_current(current)

    # Persist raw source buckets so every aggregate remains auditable.
    SOURCE.mkdir(parents=True, exist_ok=True)
    (SOURCE / f"{name}-current.json").write_text(
        json.dumps(current, indent=2) + "\n", encoding="utf-8"
    )

    markets = aggregate_closed([*closed, *settled_current])
    by_sport = {
        sport: performance([row for row in markets if row["sport"] == sport])
        for sport in sorted({str(row["sport"]) for row in markets})
    }
    by_segment = {
        f"{sport} / {market_type}": performance(
            [
                row
                for row in markets
                if row["sport"] == sport and row["market_type"] == market_type
            ]
        )
        for sport, market_type in sorted(
            {(str(row["sport"]), str(row["market_type"])) for row in markets}
        )
    }
    clean = [row for row in markets if row["direction_status"] == "CLEAN_DIRECTIONAL"]
    clean_sizes = [
        number(row["net_directional_cost_usd"])
        for row in clean
        if number(row["net_directional_cost_usd"]) >= 100
    ]
    statuses: dict[str, int] = {}
    for row in markets:
        status = str(row["direction_status"])
        statuses[status] = statuses.get(status, 0) + 1

    result = {
        "identity": {"name": name, "address": address},
        "generated_at_et": datetime.now(ET).isoformat(),
        "data_quality": {
            "redeemed_closed_rows": len(closed),
            "settled_unredeemed_rows": len(settled_current),
            "current_rows_total": len(current),
            "current_history_capped_or_repeated": current_capped,
            "settled_source_rows": len(closed) + len(settled_current),
            "exact_markets": len(markets),
            "closed_history_capped_at_source_limit": len(closed) >= 20_000,
            "settlement_scope": "redeemed closed plus all settled unredeemed current positions",
        },
        "directionality": {
            "status_counts": statuses,
            "clean_directional_rate": len(clean) / len(markets) if markets else None,
        },
        "sizing": {
            "estimated_base_unit_usd": None,
            "unit_confidence": "preserve_existing_wallet_specific_unit",
            "matched_samples": None,
            "p25_clean_net_risk_usd": percentile(clean_sizes, 0.25),
            "median_clean_net_risk_usd": percentile(clean_sizes, 0.50),
            "p75_clean_net_risk_usd": percentile(clean_sizes, 0.75),
            "p90_clean_net_risk_usd": percentile(clean_sizes, 0.90),
        },
        "settled_performance": {
            "overall": performance(markets),
            "clean_directional": performance(clean),
            "by_sport": by_sport,
            "by_sport_and_market": by_segment,
        },
        "method": {
            "position_aggregation": "Exact condition and outcome aggregation",
            "unredeemed_pnl": "cashPnl + realizedPnl",
            "flat_tail": "One unit at dominant outcome average entry",
            "limitation": "Historical average-entry settlement analysis, not a timestamp-perfect follower backtest",
        },
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / f"{name}.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return name, result


def main() -> None:
    results: dict[str, Any] = {}
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            pool.submit(extract, name, address): name
            for name, address in WALLETS.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                _, result = future.result()
                results[name] = result
                print(f"completed {name}", flush=True)
            except Exception as exc:  # Preserve successful wallets for audit.
                errors[name] = str(exc)
                print(f"failed {name}: {exc}", flush=True)
    payload = {
        "generated_at_et": datetime.now(ET).isoformat(),
        "wallet_count": len(results),
        "errors": errors,
        "wallets": dict(sorted(results.items())),
    }
    CONSOLIDATED.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(CONSOLIDATED)


if __name__ == "__main__":
    main()
