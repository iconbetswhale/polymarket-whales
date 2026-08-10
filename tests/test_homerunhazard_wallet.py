from datetime import datetime, timezone
from pathlib import Path

import pytest

from trade_scoring import build_trades_to_play
from wallet_loader import load_wallets


HOMERUNHAZARD_ADDRESS = "0x5268527977f700f9bf9b6d5cd843859e4e70135d"
CORE_ADDRESS = "0x84dbb7103982e3617704a2ed7d5b39691952aeeb"
NOW = datetime(2026, 7, 27, 16, 0, tzinfo=timezone.utc)


def _position(
    wallet: str,
    label: str,
    consensus_role: str,
    *,
    amount: float,
    status: str = "CLEAN_AFTER_EVENT_NETTING",
    lead: bool = False,
) -> dict:
    return {
        "wallet_address": wallet,
        "wallet_label": label,
        "condition_id": "mlb-moneyline",
        "event_slug": "mlb-nyy-bos-2026-07-28",
        "market_slug": "mlb-nyy-bos-2026-07-28",
        "market_title": "Yankees vs Red Sox",
        "event_title": "Yankees vs Red Sox",
        "outcome": "Yankees",
        "category": "MLB",
        "league": "MLB",
        "canonical_category_id": "mlb",
        "resolution_time": "2026-07-28T23:10:00Z",
        "event_time_source": "event.startDate",
        "average_entry_price": 0.45,
        "current_price": 0.46,
        "position_size_usd": amount,
        "signal_position_size_usd": amount,
        "status": "open",
        "market_open": True,
        "lifecycle_status": "upcoming",
        "configured_top_category_ids": ["mlb"],
        "category_signal_role": (
            "CONDITIONAL_ORIGINATOR" if lead else "CONFIRMER"
        ),
        "category_consensus_role": consensus_role,
        "category_signal_quality_weight": 0.65,
        "category_signal_minimum_originator_units": 0.25,
        "category_signal_requires_clean_directional": True,
        "supporting_sharp_eligible": True,
        "lead_sharp_eligible": lead,
        "standard_originator_eligible": lead,
        "supporting_weight": 0.65,
        "event_portfolio_status": status,
        "two_sided_status": status,
    }


def _unit_map() -> dict:
    return {
        CORE_ADDRESS: {"estimated_base_unit": 7800},
        HOMERUNHAZARD_ADDRESS: {"estimated_base_unit": 9750},
    }


def test_homerunhazard_registry_policy_is_support_only():
    wallet = next(
        wallet
        for wallet in load_wallets(Path("wallets.json")).valid_wallets
        if wallet.address == HOMERUNHAZARD_ADDRESS
    )

    assert wallet.label == "HomeRunHazard"
    assert wallet.registry_status == "SUPPORTING_ONLY"
    assert wallet.base_unit == 9750
    assert wallet.provisional_unit is False
    assert wallet.supporting_sharp_eligible is True
    assert wallet.lead_sharp_eligible is False
    assert wallet.standard_originator_eligible is False
    assert wallet.supporting_weight == pytest.approx(0.65)
    assert wallet.actionable_position_units == pytest.approx(0.25)
    assert wallet.minimum_actionable_exposure_dollars == pytest.approx(2437.5)
    assert wallet.requires_fill_aggregation is True
    assert wallet.hedge_detection_required is True
    assert wallet.event_portfolio_netting_required is True
    assert wallet.category_signal_roles["mlb"]["role"] == "CONFIRMER"
    assert (
        wallet.category_signal_roles["mlb"]["consensus_role"]
        == "NETTED_CONFIRMER"
    )
    assert wallet.wallet_forensics["clv_status"] == "UNAVAILABLE_NOT_FABRICATED"


@pytest.mark.parametrize(
    ("amount", "units"),
    [(2437.5, 0.25), (4875, 0.5), (9750, 1.0), (19500, 2.0)],
)
def test_homerunhazard_measured_unit_math(amount, units):
    assert amount / 9750 == pytest.approx(units)


def test_homerunhazard_can_confirm_core_but_is_not_a_lead():
    positions = [
        _position(
            CORE_ADDRESS,
            "Soarin22",
            "DIRECTIONAL_CORE",
            amount=3900,
            status="CLEAN_DIRECTIONAL",
            lead=True,
        ),
        _position(
            HOMERUNHAZARD_ADDRESS,
            "HomeRunHazard",
            "NETTED_CONFIRMER",
            amount=2437.5,
        ),
    ]

    play = build_trades_to_play(positions, unit_map=_unit_map(), now=NOW)[0]

    assert play["mlb_hybrid_strategy"]["qualified"] is True
    assert play["lead_sharp_count"] == 1
    assert play["supporting_sharp_count"] == 1
    homerun = next(
        row
        for row in play["supporting_wallets"]
        if row["wallet_address"] == HOMERUNHAZARD_ADDRESS
    )
    assert homerun["sharp_role"] == "Supporting Sharp"
    assert homerun["is_lead_sharp"] is False


@pytest.mark.parametrize(
    "status",
    ["MATERIAL_HEDGE", "TWO_SIDED", "MARKET_MAKING_OR_UNCERTAIN"],
)
def test_unclear_homerunhazard_portfolio_cannot_confirm(status):
    diagnostics: list[dict] = []
    positions = [
        _position(
            CORE_ADDRESS,
            "Soarin22",
            "DIRECTIONAL_CORE",
            amount=3900,
            status="CLEAN_DIRECTIONAL",
            lead=True,
        ),
        _position(
            HOMERUNHAZARD_ADDRESS,
            "HomeRunHazard",
            "NETTED_CONFIRMER",
            amount=10000,
            status=status,
        ),
    ]

    assert (
        build_trades_to_play(
            positions,
            unit_map=_unit_map(),
            now=NOW,
            diagnostics=diagnostics,
        )
        == []
    )
    assert diagnostics[0]["reason"] == "MLB_HYBRID_REQUIRES_TWO_WALLETS"


def test_below_threshold_homerunhazard_position_cannot_confirm():
    diagnostics: list[dict] = []
    positions = [
        _position(
            CORE_ADDRESS,
            "Soarin22",
            "DIRECTIONAL_CORE",
            amount=3900,
            status="CLEAN_DIRECTIONAL",
            lead=True,
        ),
        _position(
            HOMERUNHAZARD_ADDRESS,
            "HomeRunHazard",
            "NETTED_CONFIRMER",
            amount=2437.49,
        ),
    ]

    assert (
        build_trades_to_play(
            positions,
            unit_map=_unit_map(),
            now=NOW,
            diagnostics=diagnostics,
        )
        == []
    )
    assert diagnostics[0]["reason"] == "MLB_HYBRID_REQUIRES_TWO_WALLETS"


def test_homerunhazard_cannot_originate_without_a_core_wallet():
    diagnostics: list[dict] = []
    positions = [
        _position(
            HOMERUNHAZARD_ADDRESS,
            "HomeRunHazard",
            "NETTED_CONFIRMER",
            amount=19500,
        )
    ]

    assert (
        build_trades_to_play(
            positions,
            unit_map=_unit_map(),
            now=NOW,
            diagnostics=diagnostics,
        )
        == []
    )
    assert diagnostics[0]["reason"] == "MLB_HYBRID_REQUIRES_TWO_WALLETS"
