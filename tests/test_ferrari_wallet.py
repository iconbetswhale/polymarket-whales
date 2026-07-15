from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from config import Settings
from database import TrackerDatabase
from position_tracker import TrackerService
from trade_scoring import build_trades_to_play
from wallet_activity import aggregate_trade_fills, normalize_trade_fills
from wallet_loader import load_wallets


FERRARI_ADDRESS = "0xfe787d2da716d60e8acff57fb87eb13cd4d10319"


def _raw_fill(
    *,
    side: str,
    size: float,
    price: float,
    timestamp: int,
    transaction_hash: str,
    asset: str = "outcome-a",
) -> dict:
    return {
        "proxyWallet": FERRARI_ADDRESS,
        "side": side,
        "asset": asset,
        "conditionId": "0xmarket",
        "size": size,
        "price": price,
        "timestamp": timestamp,
        "title": "Yankees vs Red Sox",
        "slug": "mlb-nyy-bos-2026-07-14-nyy",
        "eventSlug": "mlb-nyy-bos-2026-07-14",
        "outcome": "Yankees",
        "transactionHash": transaction_hash,
    }


def _position(
    *,
    amount: float,
    outcome: str = "Yankees",
    category: str = "MLB",
    wallet_address: str = FERRARI_ADDRESS,
    wallet_label: str = "ferrariChampions2026",
    **overrides,
) -> dict:
    row = {
        "wallet_address": wallet_address,
        "wallet_label": wallet_label,
        "condition_id": "0xmarket",
        "event_slug": "mlb-nyy-bos-2026-07-14",
        "market_slug": "mlb-nyy-bos-2026-07-14-nyy",
        "event_title": "Yankees vs Red Sox",
        "market_title": "Yankees vs Red Sox",
        "outcome": outcome,
        "category": category,
        "league": category,
        "canonical_category_id": category.lower(),
        "configured_top_category": "Baseball",
        "configured_top_category_ids": ["mlb", "tennis"],
        "configured_sub_top_categories": ["Tennis"],
        "configured_sub_top_category_ids": ["tennis"],
        "resolution_time": "2026-07-14T23:10:00Z",
        "first_detected_at": "2026-07-13T00:00:00+00:00",
        "last_changed_at": "2026-07-13T00:10:00+00:00",
        "average_entry_price": 0.4,
        "current_price": 0.42,
        "position_size_usd": amount,
        "signal_position_size_usd": amount,
        "market_url": "https://polymarket.com/event/test",
        "status": "open",
        "shares": 100,
        "minimum_position_units": 0.2,
        "actionable_position_units": 0.5,
        "minimum_actionable_exposure_dollars": 2500,
    }
    row.update(overrides)
    return row


def _settings(tmp_path: Path, wallets_file: Path) -> Settings:
    return Settings(
        dashboard_refresh=120,
        dashboard_port=5000,
        wallets_file=wallets_file,
        database_path=tmp_path / "tracker.db",
        sports_only=True,
        resolve_hours=168,
        min_american_odds=None,
        max_american_odds=None,
        request_timeout=15,
        max_retries=1,
        admin_password=None,
    )


def test_ferrari_wallet_identity_metadata_and_aliases_are_authoritative():
    result = load_wallets(Path("wallets.json"))
    matches = [wallet for wallet in result.valid_wallets if wallet.address == FERRARI_ADDRESS]

    assert len(matches) == 1
    wallet = matches[0]
    assert wallet.label == "ferrariChampions2026"
    assert wallet.enabled is True
    assert wallet.base_unit == 5000
    assert wallet.top_category == "Baseball"
    assert wallet.top_category_display == "MLB / Baseball"
    assert wallet.top_category_ids == ("mlb", "tennis")
    assert wallet.sub_top_categories == ("Tennis",)
    assert wallet.trader_type == "ULTRA_HFT_AUTOMATED_HEDGING"
    assert wallet.selectivity_code == "VERY_LOW"
    assert wallet.copyability_code == "LOW_WITHOUT_AGGREGATION"
    assert wallet.execution_style_code == "FRAGMENTED_HIGH_FREQUENCY"
    assert wallet.hold_profile == "UNKNOWN_OR_MIXED"
    assert wallet.typical_execution_tranche_dollars == 1000
    assert wallet.minimum_actionable_exposure_dollars == 2500
    assert wallet.requires_fill_aggregation is True
    assert wallet.hedge_detection_required is True


def test_repeated_fills_are_deduplicated_and_volume_weighted():
    raw = [
        _raw_fill(side="BUY", size=100, price=0.4, timestamp=1, transaction_hash="0x1"),
        _raw_fill(side="BUY", size=50, price=0.6, timestamp=2, transaction_hash="0x2"),
    ]
    fills, duplicates = normalize_trade_fills(FERRARI_ADDRESS.upper(), [*raw, raw[0]])
    aggregate = aggregate_trade_fills(fills)[("0xmarket", "outcome-a")]

    assert duplicates == 1
    assert len(fills) == 2
    assert aggregate["fill_count"] == 2
    assert aggregate["remaining_shares"] == pytest.approx(150)
    assert aggregate["remaining_cost_basis"] == pytest.approx(70)
    assert aggregate["volume_weighted_average_entry"] == pytest.approx(70 / 150)


def test_partial_exit_reduces_remaining_cost_and_full_exit_is_excluded():
    raw = [
        _raw_fill(side="BUY", size=100, price=0.4, timestamp=1, transaction_hash="0x1"),
        _raw_fill(side="BUY", size=50, price=0.6, timestamp=2, transaction_hash="0x2"),
        _raw_fill(side="SELL", size=30, price=0.7, timestamp=3, transaction_hash="0x3"),
    ]
    fills, _ = normalize_trade_fills(FERRARI_ADDRESS, raw)
    aggregate = aggregate_trade_fills(fills)[("0xmarket", "outcome-a")]

    assert aggregate["remaining_shares"] == pytest.approx(120)
    assert aggregate["remaining_cost_basis"] == pytest.approx(56)
    assert aggregate["volume_weighted_average_entry"] == pytest.approx(70 / 150)
    assert aggregate["sell_fill_count"] == 1

    exit_fill = _raw_fill(
        side="SELL", size=120, price=0.5, timestamp=4, transaction_hash="0x4"
    )
    exited, _ = normalize_trade_fills(FERRARI_ADDRESS, [*raw, exit_fill])
    exited_aggregate = aggregate_trade_fills(exited)[("0xmarket", "outcome-a")]
    assert exited_aggregate["fully_exited"] is True
    assert exited_aggregate["remaining_shares"] == 0
    assert exited_aggregate["remaining_cost_basis"] == 0


def test_wallet_fill_ledger_and_registry_are_idempotent(tmp_path):
    database = TrackerDatabase(tmp_path / "tracker.db")
    wallet = load_wallets(Path("wallets.json")).valid_wallets[-1]
    database.sync_wallet_registry([wallet.__dict__])
    database.sync_wallet_registry([{**wallet.__dict__, "label": "ferrariChampions2026"}])
    fills, _ = normalize_trade_fills(
        FERRARI_ADDRESS,
        [_raw_fill(side="BUY", size=100, price=0.4, timestamp=1, transaction_hash="0x1")],
    )

    assert database.insert_wallet_execution_fills(fills) == 1
    assert database.insert_wallet_execution_fills(fills) == 0
    assert len(database.get_wallet_execution_fills(FERRARI_ADDRESS)) == 1
    with database.connection() as conn:
        registry_count = conn.execute(
            "SELECT COUNT(*) AS count FROM tracked_wallet_registry WHERE normalized_address = ?",
            (FERRARI_ADDRESS,),
        ).fetchone()["count"]
    assert registry_count == 1


def test_wallet_specific_unit_math_and_exact_actionable_threshold():
    diagnostics: list[dict] = []
    below = _position(amount=2499.99, condition_id="0xbelow")
    exact = _position(amount=2500, condition_id="0xexact")
    plays = build_trades_to_play(
        [below, exact],
        unit_map={FERRARI_ADDRESS: {"estimated_base_unit": 5000}},
        now=datetime(2026, 7, 13, tzinfo=timezone.utc),
        diagnostics=diagnostics,
    )

    assert {play["canonical_market_key"] for play in plays} == {"0xexact"}
    assert plays[0]["primary_trader"]["relative_units"] == 0.5
    assert diagnostics[0]["reason"] == "BELOW_WALLET_ACTIONABLE_THRESHOLD"
    assert diagnostics[0]["aggregated_cost_basis"] == 2499.99
    assert diagnostics[0]["signal_cost_basis"] == 2499.99
    assert 1000 / 5000 == 0.2
    assert 2500 / 5000 == 0.5
    assert 5000 / 5000 == 1.0


def test_tennis_sub_category_can_originate_at_full_weight():
    ferrari = _position(
        amount=5000,
        category="Tennis",
        canonical_category_id="tennis",
        event_slug="atp-example",
    )
    diagnostics: list[dict] = []
    alone = build_trades_to_play(
        [ferrari],
        unit_map={FERRARI_ADDRESS: {"estimated_base_unit": 5000}},
        now=datetime(2026, 7, 13, tzinfo=timezone.utc),
        diagnostics=diagnostics,
    )
    assert len(alone) == 1
    assert diagnostics == []
    assert alone[0]["lead_sharp_count"] == 1
    assert alone[0]["supporting_wallets"][0]["sharp_role"] == "Lead Sharp"
    assert alone[0]["supporting_wallets"][0]["category_weight"] == 1.0

    tennis_lead = _position(
        amount=3000,
        category="Tennis",
        canonical_category_id="tennis",
        wallet_address="0xlead",
        wallet_label="TennisLead",
        configured_top_category="Tennis",
        configured_top_category_ids=["tennis"],
    )
    mixed = build_trades_to_play(
        [ferrari, tennis_lead],
        unit_map={
            FERRARI_ADDRESS: {"estimated_base_unit": 5000},
            "0xlead": {"estimated_base_unit": 1000},
        },
        now=datetime(2026, 7, 13, tzinfo=timezone.utc),
    )[0]
    assert mixed["primary_trader"]["wallet_label"] == "ferrariChampions2026"
    assert mixed["weighted_sharp_count"] == 2.0
    ferrari_support = next(
        supporter
        for supporter in mixed["supporting_wallets"]
        if supporter["wallet_address"] == FERRARI_ADDRESS
    )
    assert ferrari_support["sharp_role"] == "Lead Sharp"
    assert ferrari_support["category_weight"] == 1.0


def test_same_wallet_opposing_exposure_is_netted_before_signal_scoring():
    leader = _position(
        amount=4000,
        outcome="Yankees",
        shares=10000,
        average_entry_price=0.4,
        opposite_outcome="Red Sox",
        hedge_detection_required=True,
        wallet_base_unit=5000,
    )
    opponent = _position(
        amount=1200,
        outcome="Red Sox",
        shares=2000,
        average_entry_price=0.6,
        opposite_outcome="Yankees",
        hedge_detection_required=True,
        wallet_base_unit=5000,
    )

    TrackerService._apply_wallet_hedge_controls(None, [leader, opponent])

    assert leader["wallet_hedge_status"] == "directional_after_hedge"
    assert leader["signal_position_size_usd"] == pytest.approx(3200)
    assert leader["opposing_exposure_usd"] == 1200
    assert opponent["signal_rejection_reason"] == "HEDGED_WALLET_POSITION"
    diagnostics: list[dict] = []
    plays = build_trades_to_play(
        [leader, opponent],
        unit_map={FERRARI_ADDRESS: {"estimated_base_unit": 5000}},
        now=datetime(2026, 7, 13, tzinfo=timezone.utc),
        diagnostics=diagnostics,
    )
    assert len(plays) == 1
    assert plays[0]["agreeing_wallet_count"] == 1
    assert plays[0]["primary_trader"]["amount"] == pytest.approx(3200)
    assert any(row["reason"] == "HEDGED_WALLET_POSITION" for row in diagnostics)


def test_substantially_hedged_wallet_has_no_clear_directional_signal():
    first = _position(
        amount=2000,
        outcome="Yankees",
        shares=5000,
        opposite_outcome="Red Sox",
        hedge_detection_required=True,
        wallet_base_unit=5000,
    )
    second = _position(
        amount=2000,
        outcome="Red Sox",
        shares=5000,
        opposite_outcome="Yankees",
        hedge_detection_required=True,
        wallet_base_unit=5000,
    )

    TrackerService._apply_wallet_hedge_controls(None, [first, second])
    assert first["signal_rejection_reason"] == "NO_CLEAR_DIRECTIONAL_EXPOSURE"
    assert second["signal_rejection_reason"] == "HEDGED_WALLET_POSITION"


class NoFillSyncClient:
    def get_current_positions(self, wallet_address: str):
        return [
            {
                "conditionId": "0x" + ("1" * 64),
                "asset": "outcome-a",
                "size": 10000,
                "avgPrice": 0.4,
                "initialValue": 4000,
                "currentValue": 4200,
                "curPrice": 0.42,
                "title": "Yankees vs Red Sox",
                "slug": "mlb-nyy-bos-2026-07-14-nyy",
                "eventSlug": "mlb-nyy-bos-2026-07-14",
                "eventId": "1",
                "outcome": "Yankees",
                "oppositeOutcome": "Red Sox",
                "endDate": "2026-07-14T23:10:00Z",
            }
        ]

    def get_closed_positions(self, wallet_address: str, limit: int = 50):
        return []

    def get_events(self, event_slugs, max_workers: int = 3):
        return {}

    def get_public_profile(self, wallet_address: str):
        return None


def test_required_fill_sync_failure_gates_wallet_from_all_signals(tmp_path):
    wallet_file = tmp_path / "wallets.json"
    source = next(
        item
        for item in json.loads(Path("wallets.json").read_text(encoding="utf-8"))
        if item["address"] == FERRARI_ADDRESS
    )
    wallet_file.write_text(json.dumps([source]), encoding="utf-8")
    settings = _settings(tmp_path, wallet_file)
    service = TrackerService(
        settings,
        client=NoFillSyncClient(),
        database=TrackerDatabase(settings.database_path),
        auto_start=False,
    )

    service.refresh()
    snapshot = service.get_snapshot()
    assert snapshot["wallets"][0]["sync_status"] == "failed"
    assert snapshot["positions"] == []
    assert snapshot["trades_to_play"] == []
