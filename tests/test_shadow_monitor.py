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
    config["sleeves"] = [
        next(item for item in config["sleeves"] if item["mode"] == "SHADOW")
    ]
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
    assert result["input_coverage"]["tracked_rows"] == 2
    assert result["input_coverage"]["observed_wallets"] == 1
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
    assert all(item["base_unit_usd"] == 900 for item in sleeves)
    assert all(item["minimum_units"] == 0.5 for item in sleeves)
    by_id = {item["id"]: item for item in sleeves}
    assert by_id["huntersmethdealer-nfl-ml"]["mode"] == "LIVE_BENCHMARK"
    assert by_id["huntersmethdealer-nfl-ml"]["overlay_weight"] == 0.25
    for sleeve_id in (
        "huntersmethdealer-nfl-total",
        "huntersmethdealer-soccer-ml",
        "huntersmethdealer-soccer-total",
    ):
        assert by_id[sleeve_id]["mode"] == "SHADOW"
        assert by_id[sleeve_id]["overlay_weight"] == 0.0


def test_new_segmented_wallets_are_zero_weight_shadow_only():
    config = load_shadow_config()
    positive = [
        item for item in config["sleeves"] if item["label"] == "Positive-Console"
    ]
    canoflanagan = [
        item for item in config["sleeves"] if item["label"] == "Canoflanagan"
    ]

    assert {item["id"] for item in positive} == {
        "positive-console-wnba-spread",
        "positive-console-mlb-spread",
        "positive-console-mlb-total",
        "positive-console-mlb-ml",
    }
    assert {item["id"] for item in canoflanagan} == {
        "canoflanagan-wnba-spread"
    }
    assert all(item["base_unit_usd"] == 6575 for item in positive)
    assert all(item["minimum_units"] == 0.5 for item in positive)
    assert canoflanagan[0]["base_unit_usd"] == 2175
    assert canoflanagan[0]["minimum_units"] == 0.5
    assert all(item["mode"] in {"SHADOW", "RESEARCH"} for item in [*positive, *canoflanagan])
    assert all(item["overlay_weight"] == 0.0 for item in [*positive, *canoflanagan])


def test_undisputa_is_limited_to_nba_and_soccer_moneyline_confirmation():
    config = load_shadow_config()
    sleeves = [item for item in config["sleeves"] if item["label"] == "Undisputa"]
    by_id = {item["id"]: item for item in sleeves}

    assert set(by_id) == {
        "undisputa-nba-ml",
        "undisputa-soccer-ml",
        "undisputa-nhl-ml",
        "undisputa-mlb-ml",
    }
    assert by_id["undisputa-nba-ml"]["minimum_units"] == 0.5
    assert by_id["undisputa-soccer-ml"]["minimum_units"] == 0.5
    assert by_id["undisputa-nhl-ml"]["minimum_units"] == 1.0
    assert by_id["undisputa-nba-ml"]["mode"] == "LIVE_BENCHMARK"
    assert by_id["undisputa-soccer-ml"]["mode"] == "LIVE_BENCHMARK"
    assert by_id["undisputa-nba-ml"]["overlay_weight"] == 0.25
    assert by_id["undisputa-soccer-ml"]["overlay_weight"] == 0.25
    assert by_id["undisputa-nhl-ml"]["mode"] == "SHADOW"
    assert by_id["undisputa-mlb-ml"]["mode"] == "RESEARCH"
    assert all(item["base_unit_usd"] == 1300 for item in sleeves)
    assert by_id["undisputa-nhl-ml"]["overlay_weight"] == 0.0
    assert by_id["undisputa-mlb-ml"]["overlay_weight"] == 0.0


def test_zero_pnl_closures_cannot_create_false_graduation_readiness():
    config = deepcopy(load_shadow_config())
    config["sleeves"] = [config["sleeves"][0]]
    config["promotion_policy"].update({
        "minimum_settled_bets": 2,
        "minimum_unit_profit": 1,
        "minimum_roi": 0.1,
        "minimum_hit_rate": 0.5,
        "maximum_drawdown_units": 8,
        "minimum_decided_rate": 0.8,
    })
    address = config["sleeves"][0]["address"]
    rows = [
        _row(address, pnl=100, entry=0.5, exposure=20000),
        _row(address, pnl=100, entry=0.5, exposure=20000),
        *[_row(address, pnl=0, entry=0.5, exposure=20000) for _ in range(8)],
    ]

    result = build_shadow_lab(rows, config)["sleeves"][0]

    assert result["settled_bets"] == 10
    assert result["decided_bets"] == 2
    assert result["decision_coverage"] == 0.2
    assert result["readiness_checks"]["data_quality"] is False
    assert result["promotion_status"] == "COLLECTING"


def test_team_names_containing_under_do_not_become_totals():
    config = deepcopy(load_shadow_config())
    config["sleeves"] = [config["sleeves"][0]]
    config["sleeves"][0].update({
        "sport": "NBA",
        "market_type": "Moneyline",
        "base_unit_usd": 1000,
        "minimum_units": 0.5,
    })
    address = config["sleeves"][0]["address"]
    row = _row(address, pnl=100, exposure=1000)
    row["snapshot"].update({
        "canonical_league_id": "nba",
        "canonical_category_id": "nba",
        "sports_market_type": None,
        "market_title": "Oklahoma City Thunder vs Boston Celtics",
    })

    result = build_shadow_lab([row], config)["sleeves"][0]

    assert result["tracked_rows"] == 1
    assert result["record"] == "1-0-0"


def test_live_benchmarks_never_emit_graduation_alerts():
    config = deepcopy(load_shadow_config())
    live = next(item for item in config["sleeves"] if item["mode"] == "LIVE_BENCHMARK")
    config["sleeves"] = [live]
    config["promotion_policy"].update({
        "minimum_settled_bets": 1,
        "minimum_unit_profit": 0,
        "minimum_roi": 0,
        "minimum_hit_rate": 0,
        "maximum_drawdown_units": 8,
        "minimum_decided_rate": 0,
    })
    row = _row(live["address"], pnl=100, exposure=live["base_unit_usd"])
    row["snapshot"].update({
        "canonical_league_id": live["sport"].lower(),
        "canonical_category_id": live["sport"].lower(),
        "sports_market_type": (
            "Moneyline" if live["market_type"] == "Main Markets" else live["market_type"]
        ),
    })

    result = build_shadow_lab([row], config)

    assert result["sleeves"][0]["eligible_for_promotion_review"] is False
    assert result["sleeves"][0]["promotion_status"] == "COLLECTING"
    assert result["alerts"] == []
