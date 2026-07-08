"""
ingest_top_wallets.py
Queries the Polymarket Analytics API across major categories to find the top 50
wallets by overall P&L. Saves results to top_wallets.json.
"""

import json, time, argparse
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

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}


def fetch_tag(tag: str, limit: int = 100) -> list[dict]:
    params = {
        "tag": tag,
        "limit": str(limit),
        "sortColumn": "overall_gain",
        "sortDirection": "DESC",
    }
    try:
        r = requests.get(PMA_URL, params=params, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"  {tag}: HTTP {r.status_code}")
            return []
        payload = r.json()
        # Response: {"data": [...], "totalCount": N, ...}  or bare list
        if isinstance(payload, list):
            traders = payload
        elif isinstance(payload, dict):
            traders = payload.get("data") or payload.get("traders") or []
        else:
            traders = []
        print(f"  {tag}: {len(traders)} traders")
        return traders
    except Exception as e:
        print(f"  {tag}: error — {e}")
        return []


def normalize(trader: dict, tag: str) -> dict:
    # PMA API fields: trader, trader_name, overall_gain, win_rate, total_positions, total_current_value
    raw_addr = (
        trader.get("trader") or
        trader.get("proxyWalletAddress") or
        trader.get("address") or ""
    )
    # Strip `-timestamp` suffixes sometimes appended by the API
    addr = raw_addr.split("-")[0].lower() if raw_addr else ""
    label = (
        trader.get("trader_name") or
        trader.get("name") or
        trader.get("username") or ""
    )
    gain = float(trader.get("overall_gain") or 0)
    volume = float(trader.get("total_current_value") or trader.get("volume") or 0)
    roi = float(trader.get("win_rate") or trader.get("roi") or 0)
    trades = int(trader.get("total_positions") or trader.get("trades_count") or 0)
    return {
        "address": addr,
        "label": label,
        "overall_gain": gain,
        "volume": volume,
        "roi": roi,
        "trades_count": trades,
        "best_tag": tag,
        "tags": [tag],
    }


def build_top_wallets(top_n: int = 50, per_tag: int = 100) -> list[dict]:
    seen: dict[str, dict] = {}  # address → merged record

    for tag in TAGS:
        print(f"Fetching {tag}...")
        traders = fetch_tag(tag, per_tag)
        for t in traders:
            rec = normalize(t, tag)
            addr = rec["address"]
            if not addr:
                continue
            if addr not in seen:
                seen[addr] = rec
            else:
                existing = seen[addr]
                # Accumulate gains across tags
                existing["overall_gain"] += rec["overall_gain"]
                existing["tags"].append(tag)
                if rec["overall_gain"] > existing.get("_best_tag_gain", 0):
                    existing["best_tag"] = tag
                    existing["_best_tag_gain"] = rec["overall_gain"]
        time.sleep(0.5)

    ranked = sorted(seen.values(), key=lambda x: x["overall_gain"], reverse=True)[:top_n]
    for i, w in enumerate(ranked, 1):
        w["rank"] = i
        w.pop("_best_tag_gain", None)

    return ranked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=50, help="Number of wallets to keep")
    ap.add_argument("--per-tag", type=int, default=100, help="Traders fetched per tag")
    ap.add_argument("--out", default=str(OUT_FILE), help="Output JSON file")
    args = ap.parse_args()

    print(f"Building top-{args.top} wallet list from {len(TAGS)} tags...\n")
    wallets = build_top_wallets(top_n=args.top, per_tag=args.per_tag)

    out = Path(args.out)
    out.write_text(json.dumps(wallets, indent=2))
    print(f"\nSaved {len(wallets)} wallets to {out}")
    for w in wallets[:10]:
        gain_str = f"${w['overall_gain']:,.0f}"
        display = w['label'] or w['address'][:12] + "…"
        print(f"  #{w['rank']:2d}  {display:<20s}  {gain_str}  [{w['best_tag']}]")


if __name__ == "__main__":
    main()
