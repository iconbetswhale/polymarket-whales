from __future__ import annotations

from copy import deepcopy

import pytest

from shadow_monitor import build_shadow_lab, load_shadow_config


def _row(address: str, *, pnl: float, entry: float = 0.5, exposure: float = 1000.0):
    return {
        "wallet_address": address,
        "status": "closed",
        "closed_at": "2026-08-10T12:00:00Z",
        "snapshot": {
            "status": "closed",
            "canonical_league_id": "mlb",
            "canonical_category_id": "mlb",
            "sports_market_type": "Moneyline",
            "position_size_usd": exposure,
            "average_entry_price": entry,
            "realized_pnl": pnl,
            "clv_pct": 0.01,
        },
    }


def test_shadow_config_refuses_automatic_promotion(tmp_path):
    config = load_shadow_config()
    changed = deepcopy(config)
    changed["promotion_policy"]["automatic_promotion"] = True
    path = tmp_path / "shadow.json"
    import json
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="never auto-promote"):
        load_shadow_config(path)


def test_breakthebank_uses_mlb_specific_unit_and_exact_market():
    config = load_shadow_config()
    sleeve = next(item for item in config["sleeves"] if item["id"] == "breakthebank-mlb-ml")
    address = sleeve["address"]
    rows = [
        _row(address, pnl=100, exposure=7249),
        _row(address, pnl=100, exposure=7250),
        {
            **_row(address, pnl=100, exposure=14500),
            "snapshot": {
                **_row(address, pnl=100, exposure=14500)["snapshot"],
                "sports_market_type": "Spread",
            },
        },
    ]
    result = build_shadow_lab(rows, config)
    tracked = next(item for item in result["sleeves"] if item["id"] == sleeve["id"])
    assert sleeve["base_unit_usd"] == 14500
    assert tracked["settled_bets"] == 1
    assert tracked["record"] == "1-0-0"
    assert tracked["unit_profit"] == 1.0


def test_ready_wallet_only_creates_manual_review_alert():
    config = load_shadow_config()
    config = deepcopy(config)
    config["sleeves"] = [config["sleeves"][0]]
    config["promotion_policy"].update({
        "minimum_settled_bets": 2,
        "minimum_unit_profit": 1,
        "minimum_roi": 0.1,
        "minimum_hit_rate": 0.5,
        "maximum_drawdown_units": 8,
    })
    address = config["sleeves"][0]["address"]
    rows = [
        _row(address, pnl=100, entry=0.5, exposure=20000),
        _row(address, pnl=100, entry=0.5, exposure=20000),
    ]
    result = build_shadow_lab(rows, config)
    assert result["sleeves"][0]["promotion_status"] == "READY_FOR_REVIEW"
    assert "clv" not in result["sleeves"][0]["readiness_checks"]
    assert result["sleeves"][0]["positive_clv_rate"] == 1.0
    assert len(result["alerts"]) == 1
    assert result["automatic_promotion"] is False


def test_huntersmethdealer_is_split_into_high_conviction_shadow_sleeves():
    config = load_shadow_config()
    sleeves = [
        item for item in config["sleeves"] if item["label"] == "HuntersMethDealer"
    ]
    assert {item["id"] for item in sleeves} == {
        "huntersmethdealer-nfl-ml",
        "huntersmethdealer-nfl-total",
        "huntersmethdealer-soccer-ml",
        "huntersmethdealer-soccer-total",
    }
    assert all(item["base_unit_usd"] == 400 for item in sleeves)
    assert all(item["minimum_units"] == 1.0 for item in sleeves)
    assert all(item["mode"] == "SHADOW" for item in sleeves)
    assert all(item["overlay_weight"] == 0.0 for item in sleeves)
