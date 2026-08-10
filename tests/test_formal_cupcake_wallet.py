from datetime import datetime, timezone
from pathlib import Path

import pytest

from trade_scoring import build_trades_to_play
from wallet_loader import load_wallets


FORMAL_CUPCAKE_ADDRESS = "0xb8c842bc049bf208f73354c7b037b811d741d8a4"
CORE_ADDRESS = "0x84dbb7103982e3617704a2ed7d5b39691952aeeb"
NOW = datetime(2026, 7, 27, 16, 0, tzinfo=timezone.utc)


def _position(
    wallet: str,
    label: str,
    *,
    role: str,
    consensus_role: str,
    lead: bool,
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
        "average_entry_price": 0.45,
        "current_price": 0.46,
        "position_size_usd": 1300,
        "signal_position_size_usd": 1300,
        "status": "open",
        "market_open": True,
        "lifecycle_status": "upcoming",
        "configured_top_category_ids": ["mlb"],
        "category_signal_role": role,
        "category_consensus_role": consensus_role,
        "category_signal_quality_weight": 0 if role == "RESEARCH" else 0.78,
        "category_signal_minimum_originator_units": 1.0,
        "category_signal_requires_clean_directional": True,
        "supporting_sharp_eligible": role != "RESEARCH",
        "lead_sharp_eligible": lead,
        "standard_originator_eligible": lead,
        "supporting_weight": 0 if role == "RESEARCH" else 0.5,
        "two_sided_status": "CLEAN_DIRECTIONAL",
    }


def test_formal_cupcake_registry_is_conditional_mlb_lead():
    wallet = next(
        wallet
        for wallet in load_wallets(Path("wallets.json")).valid_wallets
        if wallet.address == FORMAL_CUPCAKE_ADDRESS
    )

    assert wallet.label == "Formal-Cupcake"
    assert wallet.registry_status == "MLB_LEAD_ELIGIBLE"
    assert wallet.base_unit == 1300
    assert wallet.provisional_unit is False
    assert wallet.supporting_sharp_eligible is True
    assert wallet.lead_sharp_eligible is True
    assert wallet.standard_originator_eligible is True
    assert wallet.research_candidate_originator_eligible is True
    assert wallet.supporting_weight == pytest.approx(0.8)
    assert (
        wallet.category_signal_roles["mlb"]["role"]
        == "CONDITIONAL_ORIGINATOR"
    )
    assert (
        wallet.category_signal_roles["mlb"]["consensus_role"]
        == "DIRECTIONAL_CORE"
    )
    assert wallet.category_signal_roles["mlb"]["quality_weight"] == pytest.approx(
        0.85
    )
    assert wallet.wallet_forensics["settled_wins"] == 76
    assert wallet.wallet_forensics["settled_losses"] == 79
    assert wallet.wallet_forensics["corrected_roi"] == pytest.approx(0.1323)
    assert wallet.wallet_forensics["positive_exchange_clv_rate"] == pytest.approx(
        0.4737
    )


@pytest.mark.parametrize(
    ("amount", "units"),
    [(650, 0.5), (1300, 1.0), (2600, 2.0), (6500, 5.0)],
)
def test_formal_cupcake_measured_unit_math(amount, units):
    assert amount / 1300 == pytest.approx(units)


def test_formal_cupcake_cannot_create_a_trade_without_confirmation():
    diagnostics: list[dict] = []
    positions = [
        _position(
            FORMAL_CUPCAKE_ADDRESS,
            "Formal-Cupcake",
            role="CONDITIONAL_ORIGINATOR",
            consensus_role="DIRECTIONAL_CORE",
            lead=True,
        )
    ]
    unit_map = {
        CORE_ADDRESS: {"estimated_base_unit": 1300},
        FORMAL_CUPCAKE_ADDRESS: {"estimated_base_unit": 1300},
    }

    assert (
        build_trades_to_play(
            positions,
            unit_map=unit_map,
            now=NOW,
            diagnostics=diagnostics,
        )
        == []
    )
    assert diagnostics[0]["reason"] == "MLB_HYBRID_REQUIRES_TWO_WALLETS"


def test_formal_cupcake_plus_independent_confirmer_qualifies():
    confirmer_address = "0x5268527977f700f9bf9b6d5cd843859e4e70135d"
    positions = [
        _position(
            FORMAL_CUPCAKE_ADDRESS,
            "Formal-Cupcake",
            role="CONDITIONAL_ORIGINATOR",
            consensus_role="DIRECTIONAL_CORE",
            lead=True,
        ),
        _position(
            confirmer_address,
            "HomeRunHazard",
            role="CONFIRMER",
            consensus_role="NETTED_CONFIRMER",
            lead=False,
        ),
    ]
    unit_map = {
        FORMAL_CUPCAKE_ADDRESS: {"estimated_base_unit": 1300},
        confirmer_address: {"estimated_base_unit": 1300},
    }

    play = build_trades_to_play(positions, unit_map=unit_map, now=NOW)[0]

    assert play["mlb_hybrid_strategy"]["qualified"] is True
    assert play["lead_sharp_count"] == 1
    assert play["supporting_sharp_count"] == 1
    formal = next(
        row
        for row in play["supporting_wallets"]
        if row["wallet_address"] == FORMAL_CUPCAKE_ADDRESS
    )
    assert formal["is_lead_sharp"] is True
