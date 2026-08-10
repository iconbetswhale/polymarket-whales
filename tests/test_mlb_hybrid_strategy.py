from datetime import datetime, timezone

from trade_scoring import build_trades_to_play


NOW = datetime(2026, 7, 13, tzinfo=timezone.utc)


def _position(
    wallet: str,
    label: str,
    role: str,
    *,
    outcome: str = "Yankees",
    amount: float = 1500,
    status: str = "CLEAN_DIRECTIONAL",
) -> dict:
    return {
        "wallet_address": wallet,
        "wallet_label": label,
        "condition_id": "mlb-moneyline",
        "event_slug": "mlb-nyy-bos-2026-07-14",
        "market_slug": "mlb-nyy-bos-moneyline",
        "market_title": "Yankees vs Red Sox",
        "event_title": "Yankees vs Red Sox",
        "outcome": outcome,
        "category": "MLB",
        "league": "MLB",
        "resolution_time": "2026-07-14T23:10:00Z",
        "event_time_source": "event.startDate",
        "first_detected_at": "2026-07-13T00:00:00+00:00",
        "last_changed_at": "2026-07-13T00:10:00+00:00",
        "average_entry_price": 0.4,
        "current_price": 0.42,
        "position_size_usd": amount,
        "status": "open",
        "shares": 100,
        "configured_top_category_ids": ["MLB"],
        "category_signal_role": "CONDITIONAL_ORIGINATOR",
        "category_consensus_role": role,
        "category_signal_quality_weight": 0.9,
        "category_signal_minimum_originator_units": 0.5,
        "category_signal_requires_clean_directional": True,
        "supporting_sharp_eligible": True,
        "lead_sharp_eligible": True,
        "two_sided_status": status,
    }


def _units(*wallets: str) -> dict:
    return {
        wallet.lower(): {"estimated_base_unit": 1000}
        for wallet in wallets
    }


def test_single_core_wallet_stays_out_of_production():
    diagnostics = []
    positions = [_position("0xcore", "Core", "DIRECTIONAL_CORE")]

    assert build_trades_to_play(
        positions,
        unit_map=_units("0xcore"),
        now=NOW,
        diagnostics=diagnostics,
    ) == []
    assert diagnostics[0]["reason"] == "MLB_HYBRID_REQUIRES_TWO_WALLETS"


def test_core_plus_netted_confirmer_qualifies():
    positions = [
        _position("0xcore", "Core", "DIRECTIONAL_CORE"),
        _position("0xconfirm", "Confirmer", "NETTED_CONFIRMER"),
    ]

    play = build_trades_to_play(
        positions,
        unit_map=_units("0xcore", "0xconfirm"),
        now=NOW,
    )[0]

    strategy = play["mlb_hybrid_strategy"]
    assert strategy["qualified"] is True
    assert strategy["eligible_wallet_count"] == 2
    assert strategy["core_wallet_count"] == 1
    assert strategy["confirmer_wallet_count"] == 1
    assert play["lead_sharp_count"] == 1
    assert play["supporting_sharp_count"] == 1
    roles = {
        wallet["wallet_label"]: wallet["sharp_role"]
        for wallet in play["supporting_wallets"]
    }
    assert roles == {"Core": "Lead Sharp", "Confirmer": "Supporting Sharp"}
    assert play["strategy_version"] == "mlb-hybrid-consensus-v1"


def test_two_confirmers_cannot_replace_directional_core():
    diagnostics = []
    positions = [
        _position("0xone", "One", "NETTED_CONFIRMER"),
        _position("0xtwo", "Two", "NETTED_CONFIRMER"),
    ]

    assert build_trades_to_play(
        positions,
        unit_map=_units("0xone", "0xtwo"),
        now=NOW,
        diagnostics=diagnostics,
    ) == []
    assert diagnostics[0]["reason"] == "MLB_HYBRID_REQUIRES_DIRECTIONAL_CORE"


def test_opposing_core_is_a_hard_veto():
    diagnostics = []
    positions = [
        _position("0xcore", "Core", "DIRECTIONAL_CORE"),
        _position("0xconfirm", "Confirmer", "NETTED_CONFIRMER"),
        _position(
            "0xopposing",
            "Opposing core",
            "DIRECTIONAL_CORE",
            outcome="Red Sox",
        ),
    ]

    assert build_trades_to_play(
        positions,
        unit_map=_units("0xcore", "0xconfirm", "0xopposing"),
        now=NOW,
        diagnostics=diagnostics,
    ) == []
    assert {
        row["reason"] for row in diagnostics
    } >= {"MLB_HYBRID_OPPOSING_CORE_VETO"}


def test_two_sided_confirmer_does_not_count_as_second_wallet():
    diagnostics = []
    positions = [
        _position("0xcore", "Core", "DIRECTIONAL_CORE"),
        _position(
            "0xconfirm",
            "Two-sided confirmer",
            "NETTED_CONFIRMER",
            status="TWO_SIDED",
        ),
    ]

    assert build_trades_to_play(
        positions,
        unit_map=_units("0xcore", "0xconfirm"),
        now=NOW,
        diagnostics=diagnostics,
    ) == []
    assert diagnostics[0]["reason"] == "MLB_HYBRID_REQUIRES_TWO_WALLETS"
