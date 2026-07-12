"""
Legacy utility for generating a top-wallet list from Polymarket Analytics.

This script is intentionally optional and is not used by the dashboard startup,
deployment, or refresh flow. The manual wallets.json file is the source of truth.
"""

import argparse
import json
import time
from pathlib import Path

import requests

PMA_URL = "https://legacy.polymarketanalytics.com/api/traders-tag-performance"
OUT_FILE = Path("top_wallets.json")

TAGS = [
    "Sports",
    "Politics",
    "Crypto",
    "Economics",
    "Entertainment",
    "Science",
    "Tech",
    "World",
    "Culture",
    "Business",
]


def fetch_tag(tag: str, limit: int = 100) -> list[dict]:
    response = requests.get(
        PMA_URL,
        params={
            "tag": tag,
            "limit": str(limit),
            "sortColumn": "overall_gain",
            "sortDirection": "DESC",
        },
        headers={"User-Agent": "iconbets-wallet-tracker/2.0"},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, list):
        return payload
    return payload.get("data") or []


def normalize(trader: dict, tag: str) -> dict:
    address = (
        trader.get("trader")
        or trader.get("proxyWalletAddress")
        or trader.get("address")
        or ""
    ).split("-")[0].lower()
    return {
        "address": address,
        "label": trader.get("trader_name") or trader.get("name") or "",
        "overall_gain": float(trader.get("overall_gain") or 0),
        "volume": float(trader.get("total_current_value") or trader.get("volume") or 0),
        "trades_count": int(trader.get("total_positions") or trader.get("trades_count") or 0),
        "best_tag": tag,
        "tags": [tag],
    }


def build_top_wallets(top_n: int = 50, per_tag: int = 100) -> list[dict]:
    merged: dict[str, dict] = {}
    for tag in TAGS:
        traders = fetch_tag(tag, per_tag)
        for trader in traders:
            record = normalize(trader, tag)
            if not record["address"]:
                continue
            existing = merged.setdefault(record["address"], record)
            if existing is not record:
                existing["overall_gain"] += record["overall_gain"]
                existing["tags"].append(tag)
        time.sleep(0.5)
    ranked = sorted(merged.values(), key=lambda item: item["overall_gain"], reverse=True)[:top_n]
    for index, wallet in enumerate(ranked, start=1):
        wallet["rank"] = index
    return ranked


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=50)
    parser.add_argument("--per-tag", type=int, default=100)
    parser.add_argument("--out", default=str(OUT_FILE))
    args = parser.parse_args()

    wallets = build_top_wallets(top_n=args.top, per_tag=args.per_tag)
    Path(args.out).write_text(json.dumps(wallets, indent=2), encoding="utf-8")
    print(f"Saved {len(wallets)} wallets to {args.out}")


if __name__ == "__main__":
    main()
