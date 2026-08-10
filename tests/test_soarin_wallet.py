from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from database import TrackerDatabase
from position_tracker import TrackerService
from trade_scoring import build_trades_to_play
from wallet_activity import (
    aggregate_trade_fills,
    normalize_trade_fills,
    summarize_aggregated_positions,
)
from wallet_loader import load_wallets


SOARIN_ADDRESS = "0x84dbb7103982e3617704a2ed7d5b39691952aeeb"


def _raw_fill(
    *,
    asset: str,
    outcome: str,
    size: float,
    price: float,
    timestamp: int,
    transaction_hash: str,
    side: str = "BUY",
) -> dict:
    return {
        "proxyWallet": SOARIN_ADDRESS,
        "side": side,
        "asset": asset,
        "conditionId": "0xsoarin-market",
        "size": size,
        "price": price,
        "timestamp": timestamp,
        "title": "Yankees vs Red Sox",
        "slug": "mlb-nyy-bos-2026-07-27",
        "eventSlug": "mlb-nyy-bos-2026-07-27",
        "outcome": outcome,
        "transactionHash": transaction_hash,
    }


def _position(
    *,
    wallet_address: str = SOARIN_ADDRESS,
    wallet_label: str = "Soarin22",
    amount: float = 5000,
    outcome: str = "Yankees",
    **overrides,
) -> dict:
    row = {
        "wallet_address": wallet_address,
        "wallet_label": wallet_label,
        "condition_id": "0xsoarin-market",
        "event_slug": "mlb-nyy-bos-2026-07-27",
        "market_slug": "mlb-nyy-bos-2026-07-27",
        "event_title": "Yankees vs Red Sox",
        "market_title": "Yankees vs Red Sox",
        "outcome": outcome,
        "category": "MLB",
        "league": "MLB",
        "canonical_category_id": "mlb",
        "configured_top_category": "MLB",
        "configured_top_category_ids": ["mlb"],
        "primary_top_category_id": "mlb",
        "top_category_source": "admin_approved_mlb_lead",
        "resolution_time": "2026-07-27T23:10:00Z",
        "average_entry_price": 0.4,
        "current_price": 0.41,
        "position_size_usd": amount,
        "signal_position_size_usd": amount,
        "market_open": True,
        "lifecycle_status": "upcoming",
        "status": "open",
        "shares": amount / 0.4,
        "minimum_position_units": 0.1,
        "actionable_position_units": 0.5,
        "minimum_actionable_exposure_dollars": 2500,
        "lead_sharp_eligible": True,
        "supporting_sharp_eligible": True,
        "supporting_weight": 0.5,
        "standard_originator_eligible": True,
        "research_candidate_originator_eligible": True,
        "wallet_registry_status": "MLB_LEAD_ELIGIBLE",
        "shadow_rejection_reason": None,
        "directional_weight": 1.0,
    }
    row.update(overrides)
    return row


def test_soarin_registry_policy_is_authoritative():
    result = load_wallets(Path("wallets.json"))
    wallet = next(
        wallet for wallet in result.valid_wallets if wallet.address == SOARIN_ADDRESS
    )

    assert wallet.label == "Soarin22"
    assert wallet.registry_status == "MLB_LEAD_ELIGIBLE"
    assert wallet.base_unit == 7800
    assert wallet.provisional_unit is False
    assert wallet.lead_sharp_eligible is True
    assert wallet.supporting_sharp_eligible is True
    assert wallet.standard_originator_eligible is True
    assert wallet.research_candidate_originator_eligible is True
    assert wallet.supporting_weight == 0.5
    assert wallet.bettor_type == "Selective automated MLB directional bettor"
    assert wallet.minimum_meaningful_originator_position_usd == 3900
    assert wallet.requires_fill_aggregation is True
    assert wallet.hedge_detection_required is True
    assert wallet.wallet_forensics["markets"] == 233
    assert wallet.wallet_forensics["clean_directional_roi"] == pytest.approx(0.1244)
    assert wallet.wallet_forensics["clv_status"] == "UNAVAILABLE_NOT_FABRICATED"


@pytest.mark.parametrize(
    ("amount", "units"),
    [(3900, 0.5), (7800, 1.0), (15600, 2.0), (39000, 5.0)],
)
def test_measured_unit_math(amount, units):
    assert amount / 7800 == pytest.approx(units)


def test_multiple_fills_aggregate_before_unit_calculation():
    raw = [
        _raw_fill(
            asset="outcome-a",
            outcome="Yankees",
            size=5000,
            price=0.4,
            timestamp=1,
            transaction_hash="0x1",
        ),
        _raw_fill(
            asset="outcome-a",
            outcome="Yankees",
            size=5000,
            price=0.6,
            timestamp=2,
            transaction_hash="0x2",
        ),
    ]
    fills, duplicates = normalize_trade_fills(SOARIN_ADDRESS, [*raw, raw[0]])
    aggregates = aggregate_trade_fills(fills)
    aggregate = aggregates[("0xsoarin-market", "outcome-a")]
    summary = summarize_aggregated_positions(aggregates, unit_baseline=5000)

    assert duplicates == 1
    assert aggregate["fill_count"] == 2
    assert aggregate["gross_amount_purchased"] == pytest.approx(5000)
    assert summary["aggregated_position_count"] == 1
    assert summary["aggregated_positions"][0]["relative_units"] == pytest.approx(1)


def test_opposite_sides_are_classified_and_never_double_counted():
    raw = [
        _raw_fill(
            asset="outcome-a",
            outcome="Yankees",
            size=10000,
            price=0.4,
            timestamp=1,
            transaction_hash="0x1",
        ),
        _raw_fill(
            asset="outcome-b",
            outcome="Red Sox",
            size=5000,
            price=0.6,
            timestamp=2,
            transaction_hash="0x2",
        ),
    ]
    fills, _ = normalize_trade_fills(SOARIN_ADDRESS, raw)
    summary = summarize_aggregated_positions(
        aggregate_trade_fills(fills), unit_baseline=5000
    )

    assert summary["aggregated_position_count"] == 1
    assert summary["two_sided_sample"] == 1
    assert summary["aggregated_positions"][0]["two_sided_status"] == "TWO_SIDED"


def test_approved_wallet_can_originate_clean_mlb_trade():
    solo = build_trades_to_play(
        [_position()],
        unit_map={SOARIN_ADDRESS: {"estimated_base_unit": 5000}},
        now=datetime(2026, 7, 26, tzinfo=timezone.utc),
    )
    assert len(solo) == 1
    play = solo[0]
    assert play["primary_trader"]["wallet_address"] == SOARIN_ADDRESS
    assert play["has_lead_sharp"] is True
    assert play["primary_trader"]["is_lead_sharp"] is True


def test_two_sided_and_material_hedge_controls():
    two_sided_a = _position(
        amount=5000,
        outcome="Yankees",
        opposite_outcome="Red Sox",
        hedge_detection_required=True,
        raw_fill_count=4,
        sell_fill_count=1,
    )
    two_sided_b = _position(
        amount=4000,
        outcome="Red Sox",
        opposite_outcome="Yankees",
        hedge_detection_required=True,
        raw_fill_count=4,
        sell_fill_count=1,
    )
    TrackerService._apply_wallet_hedge_controls(None, [two_sided_a, two_sided_b])
    assert two_sided_a["two_sided_status"] == "MARKET_MAKING_OR_UNCERTAIN"
    assert two_sided_a["signal_position_size_usd"] == 0
    assert two_sided_a["signal_rejection_reason"] == "MARKET_MAKING_OR_UNCERTAIN"

    material_a = _position(
        amount=10000,
        outcome="Yankees",
        opposite_outcome="Red Sox",
        hedge_detection_required=True,
    )
    material_b = _position(
        amount=3000,
        outcome="Red Sox",
        opposite_outcome="Yankees",
        hedge_detection_required=True,
    )
    TrackerService._apply_wallet_hedge_controls(None, [material_a, material_b])
    assert material_a["two_sided_status"] == "MATERIAL_HEDGE"
    assert material_a["directional_weight"] == 0.5


def test_tiny_positions_are_stored_but_cannot_originate(tmp_path):
    database = TrackerDatabase(tmp_path / "tracker.db")
    raw = _raw_fill(
        asset="outcome-a",
        outcome="Yankees",
        size=100,
        price=0.4,
        timestamp=1,
        transaction_hash="0xtiny",
    )
    fills, _ = normalize_trade_fills(SOARIN_ADDRESS, [raw])
    assert database.insert_wallet_execution_fills(fills) == 1
    assert len(database.get_wallet_execution_fills(SOARIN_ADDRESS)) == 1

    diagnostics: list[dict] = []
    assert (
        build_trades_to_play(
            [_position(amount=40)],
            unit_map={SOARIN_ADDRESS: {"estimated_base_unit": 5000}},
            now=datetime(2026, 7, 26, tzinfo=timezone.utc),
            diagnostics=diagnostics,
        )
        == []
    )


def test_ferrari_audit_policy_and_unavailable_clv_are_explicit():
    result = load_wallets(Path("wallets.json"))
    ferrari = next(
        wallet
        for wallet in result.valid_wallets
        if wallet.address == "0xfe787d2da716d60e8acff57fb87eb13cd4d10319"
    )
    assert ferrari.registry_status == "MLB_LEAD_ELIGIBLE"
    assert ferrari.lead_sharp_eligible is True
    assert ferrari.standard_originator_eligible is True
    assert ferrari.supporting_weight == 0.9
    assert ferrari.wallet_forensics["clv_status"] == "UNAVAILABLE_NOT_FABRICATED"

    empty = summarize_aggregated_positions({}, unit_baseline=5000)
    assert "exchange_clv" not in empty
    assert "composite_clv" not in empty


def test_historical_backfill_is_scoped_to_verified_mlb_market_ids(tmp_path):
    wallet = next(
        wallet
        for wallet in load_wallets(Path("wallets.json")).valid_wallets
        if wallet.address == SOARIN_ADDRESS
    )

    class BackfillClient:
        requested_market_ids = None

        def get_current_positions(self, _address):
            return [
                {
                    "conditionId": "0xmlb-current",
                    "eventSlug": "mlb-nyy-bos-2026-07-27",
                }
            ]

        def get_closed_positions(self, _address, limit=50):
            assert limit == 5000
            return [
                {
                    "conditionId": "0xmlb-closed",
                    "eventSlug": "mlb-lad-sd-2026-07-26",
                },
                {
                    "conditionId": "0xnba-closed",
                    "eventSlug": "nba-bos-nyk-2026-07-26",
                },
            ]

        def get_user_trades(self, _address, market_ids):
            self.requested_market_ids = market_ids
            return []

    service = object.__new__(TrackerService)
    service.client = BackfillClient()
    service.database = TrackerDatabase(tmp_path / "tracker.db")

    result = service._fetch_wallet_data([wallet])

    assert result["errors"] == []
    assert service.client.requested_market_ids == [
        "0xmlb-closed",
        "0xmlb-current",
    ]
