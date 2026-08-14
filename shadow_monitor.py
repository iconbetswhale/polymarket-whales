from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(__file__).with_name("shadow_wallets.json")


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def load_shadow_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    policy = payload.get("promotion_policy") or {}
    if policy.get("automatic_promotion") is not False:
        raise ValueError("Shadow Lab must never auto-promote wallets")
    seen: set[str] = set()
    for sleeve in payload.get("sleeves") or []:
        sleeve_id = str(sleeve.get("id") or "").strip()
        if not sleeve_id or sleeve_id in seen:
            raise ValueError("Shadow sleeve ids must be present and unique")
        seen.add(sleeve_id)
        if _number(sleeve.get("base_unit_usd")) <= 0:
            raise ValueError(f"Invalid base unit for {sleeve_id}")
    return payload


def _sport_matches(snapshot: dict[str, Any], sport: str) -> bool:
    text = " ".join(str(snapshot.get(key) or "") for key in (
        "canonical_league_id", "canonical_category_id", "league", "category"
    )).lower()
    target = sport.lower()
    if target == "mlb":
        return "mlb" in text or "baseball" in text
    return target in text


def _market_type(snapshot: dict[str, Any]) -> str:
    text = " ".join(str(snapshot.get(key) or "") for key in (
        "sports_market_type", "market_slug", "market_title"
    )).lower()
    if any(token in text for token in ("total", "over", "under", "o/u")):
        return "Total"
    if any(token in text for token in ("spread", "run line", "handicap")):
        return "Spread"
    return "Moneyline"


def _row_result(snapshot: dict[str, Any]) -> str | None:
    pnl = _number(snapshot.get("realized_pnl") or snapshot.get("realizedPnl"))
    if pnl > 0:
        return "WIN"
    if pnl < 0:
        return "LOSS"
    status = str(snapshot.get("status") or "").upper()
    return "PUSH" if status == "CLOSED" else None


def build_shadow_lab(rows: list[dict[str, Any]], config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_shadow_config()
    policy = config["promotion_policy"]
    sleeves: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    for sleeve in config.get("sleeves") or []:
        address = str(sleeve["address"]).lower()
        accepted: list[dict[str, Any]] = []
        for row in rows:
            if str(row.get("wallet_address") or "").lower() != address:
                continue
            snapshot = row.get("snapshot") or row
            if not _sport_matches(snapshot, sleeve["sport"]):
                continue
            actual_market = _market_type(snapshot)
            if sleeve["market_type"] != "Main Markets" and actual_market != sleeve["market_type"]:
                continue
            exposure = _number(snapshot.get("position_size_usd") or snapshot.get("reported_initial_value") or snapshot.get("initialValue"))
            relative_units = exposure / _number(sleeve["base_unit_usd"], 1.0)
            if relative_units + 1e-9 < _number(sleeve.get("minimum_units"), 0.5):
                continue
            entry = _number(
                snapshot.get("average_entry_price")
                or snapshot.get("avg_price")
                or snapshot.get("avgPrice")
            )
            result = _row_result(snapshot) if str(row.get("status") or snapshot.get("status") or "").lower() == "closed" else None
            profit_units = None
            if result == "WIN" and 0 < entry < 1:
                profit_units = (1.0 - entry) / entry
            elif result == "LOSS":
                profit_units = -1.0
            elif result == "PUSH":
                profit_units = 0.0
            accepted.append({"row": row, "snapshot": snapshot, "relative_units": relative_units, "result": result, "profit_units": profit_units})
        settled = [item for item in accepted if item["result"]]
        wins = sum(item["result"] == "WIN" for item in settled)
        losses = sum(item["result"] == "LOSS" for item in settled)
        pushes = sum(item["result"] == "PUSH" for item in settled)
        unit_profit = sum(_number(item["profit_units"]) for item in settled)
        roi = unit_profit / len(settled) if settled else None
        hit_rate = wins / (wins + losses) if wins + losses else None
        running = peak = max_drawdown = 0.0
        for item in sorted(settled, key=lambda x: str(x["row"].get("closed_at") or x["snapshot"].get("closed_at") or "")):
            running += _number(item["profit_units"])
            peak = max(peak, running)
            max_drawdown = max(max_drawdown, peak - running)
        clvs = [_number(item["snapshot"].get("clv_pct")) for item in settled if item["snapshot"].get("clv_pct") is not None]
        positive_clv_rate = sum(value > 0 for value in clvs) / len(clvs) if clvs else None
        checks = {
            "sample": len(settled) >= int(policy["minimum_settled_bets"]),
            "profit": unit_profit >= _number(policy["minimum_unit_profit"]),
            "roi": roi is not None and roi >= _number(policy["minimum_roi"]),
            "hit_rate": hit_rate is not None and hit_rate >= _number(policy["minimum_hit_rate"]),
            "drawdown": max_drawdown <= _number(policy["maximum_drawdown_units"]),
        }
        ready = all(checks.values())
        result = {
            **sleeve,
            "open_signals": len(accepted) - len(settled),
            "settled_bets": len(settled),
            "record": f"{wins}-{losses}-{pushes}",
            "unit_profit": round(unit_profit, 3),
            "roi": round(roi, 4) if roi is not None else None,
            "hit_rate": round(hit_rate, 4) if hit_rate is not None else None,
            "max_drawdown_units": round(max_drawdown, 3),
            "positive_clv_rate": round(positive_clv_rate, 4) if positive_clv_rate is not None else None,
            "readiness_checks": checks,
            "readiness_progress": round(sum(checks.values()) / len(checks), 3),
            "promotion_status": "READY_FOR_REVIEW" if ready else "COLLECTING",
        }
        sleeves.append(result)
        if ready:
            alerts.append({"sleeve_id": sleeve["id"], "label": sleeve["label"], "message": f"{sleeve['label']} {sleeve['sport']} {sleeve['market_type']} reached every promotion-review threshold."})
    return {"version": config["version"], "policy": policy, "sleeves": sleeves, "alerts": alerts, "automatic_promotion": False}
