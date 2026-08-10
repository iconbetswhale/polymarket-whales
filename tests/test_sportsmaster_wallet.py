from pathlib import Path

import pytest

from position_tracker import TrackerService
from wallet_loader import load_wallets


SPORTSMASTER_ADDRESS = "0x32ed517a571c01b6e9adecf61ba81ca48ff2f960"


def _position(
    *,
    outcome: str,
    amount: float,
    market_slug: str = "mlb-nyy-bos-2026-07-27",
    market_title: str = "Yankees vs Red Sox",
) -> dict:
    return {
        "wallet_address": SPORTSMASTER_ADDRESS,
        "wallet_label": "sportmaster777",
        "condition_id": f"{market_slug}:{outcome}",
        "event_slug": "mlb-nyy-bos-2026-07-27",
        "market_slug": market_slug,
        "market_title": market_title,
        "outcome": outcome,
        "position_size_usd": amount,
        "signal_position_size_usd": amount,
        "net_directional_exposure_usd": amount,
        "directional_weight": 1.0,
        "two_sided_status": "CLEAN_DIRECTIONAL",
        "event_portfolio_netting_required": True,
    }


def _net(rows: list[dict]) -> list[dict]:
    service = TrackerService.__new__(TrackerService)
    service._apply_event_portfolio_netting(rows)
    return rows


def test_sportsmaster_registry_uses_measured_mlb_policy():
    result = load_wallets(Path("wallets.json"))
    wallet = next(
        wallet
        for wallet in result.valid_wallets
        if wallet.address == SPORTSMASTER_ADDRESS
    )

    assert wallet.label == "sportmaster777"
    assert wallet.registry_status == "MLB_LEAD_ELIGIBLE"
    assert wallet.base_unit == 6000
    assert wallet.provisional_unit is False
    assert wallet.supporting_weight == pytest.approx(0.7)
    assert wallet.minimum_meaningful_originator_position_usd == 1500
    assert wallet.actionable_position_units == pytest.approx(0.25)
    assert wallet.requires_fill_aggregation is True
    assert wallet.hedge_detection_required is True
    assert wallet.event_portfolio_netting_required is True
    assert wallet.category_signal_roles["mlb"]["quality_weight"] == pytest.approx(
        0.92
    )
    assert wallet.category_signal_roles["mlb"]["requires_clean_directional"] is True
    assert wallet.wallet_forensics["markets"] == 7559
    assert wallet.wallet_forensics["realized_pnl_usd"] == pytest.approx(1236213.78)
    assert wallet.wallet_forensics["gross_turnover_roi"] == pytest.approx(0.117)
    assert (
        wallet.wallet_forensics["clv_status"]
        == "UNAVAILABLE_NOT_FABRICATED"
    )


@pytest.mark.parametrize(
    ("amount", "units"),
    [(1500, 0.25), (3000, 0.5), (6000, 1.0), (12000, 2.0)],
)
def test_sportsmaster_measured_unit_math(amount, units):
    assert amount / 6000 == pytest.approx(units)


def test_event_netting_keeps_only_clean_dominant_team_direction():
    rows = _net(
        [
            _position(outcome="Yankees", amount=10000),
            _position(
                outcome="Red Sox",
                amount=500,
                market_slug="mlb-nyy-bos-2026-07-27-spread-away-1pt5",
                market_title="Spread: Red Sox +1.5",
            ),
        ]
    )

    assert rows[0]["event_portfolio_status"] == "CLEAN_AFTER_EVENT_NETTING"
    assert rows[0]["signal_position_size_usd"] == 10000
    assert rows[1]["signal_position_size_usd"] == 0
    assert rows[1]["signal_rejection_reason"] == "EVENT_PORTFOLIO_HEDGE_LEG"


def test_minor_event_hedge_can_support_but_cannot_originate():
    rows = _net(
        [
            _position(outcome="Yankees", amount=10000),
            _position(outcome="Red Sox", amount=1500),
        ]
    )

    assert rows[0]["event_portfolio_status"] == "MINOR_EVENT_HEDGE"
    assert rows[0]["two_sided_status"] == "MINOR_HEDGE"
    assert rows[0]["directional_weight"] == pytest.approx(0.75)
    assert rows[1]["signal_position_size_usd"] == 0


@pytest.mark.parametrize(
    ("opposing_amount", "expected_status"),
    [
        (3000, "MATERIAL_EVENT_HEDGE"),
        (6000, "TWO_SIDED_EVENT_PORTFOLIO"),
    ],
)
def test_unclear_event_portfolios_cannot_create_directional_signals(
    opposing_amount, expected_status
):
    rows = _net(
        [
            _position(outcome="Yankees", amount=10000),
            _position(outcome="Red Sox", amount=opposing_amount),
        ]
    )

    assert rows[0]["event_portfolio_status"] == expected_status
    assert rows[0]["signal_position_size_usd"] == 0
    assert rows[0]["signal_rejection_reason"] == "EVENT_PORTFOLIO_DIRECTION_UNCLEAR"
    assert rows[1]["signal_position_size_usd"] == 0


def test_opposing_totals_are_netted_as_one_event_portfolio():
    rows = _net(
        [
            _position(
                outcome="Over 8.5",
                amount=5000,
                market_slug="mlb-nyy-bos-2026-07-27-total-8pt5",
                market_title="O/U 8.5",
            ),
            _position(
                outcome="Under 9.5",
                amount=4000,
                market_slug="mlb-nyy-bos-2026-07-27-total-9pt5",
                market_title="O/U 9.5",
            ),
        ]
    )

    assert all(
        row["event_portfolio_status"] == "TWO_SIDED_EVENT_PORTFOLIO"
        for row in rows
    )
    assert all(row["signal_position_size_usd"] == 0 for row in rows)


def test_existing_wallets_do_not_inherit_sportsmaster_event_netting():
    result = load_wallets(Path("wallets.json"))
    ferrari_address = "0xfe787d2da716d60e8acff57fb87eb13cd4d10319"
    wordy_address = "0x3dfb153c197d4c19d3b31c1ecd2c7b6860eeabaf"
    homerunhazard_address = "0x5268527977f700f9bf9b6d5cd843859e4e70135d"
    others = [
        wallet
        for wallet in result.valid_wallets
        if wallet.address
        not in {
            SPORTSMASTER_ADDRESS,
            ferrari_address,
                wordy_address,
                "0xf1528f12e645462c344799b62b1b421a6a4c64aa",
                homerunhazard_address,
        }
    ]
    ferrari = next(
        wallet
        for wallet in result.valid_wallets
        if wallet.address == ferrari_address
    )
    wordy = next(
        wallet
        for wallet in result.valid_wallets
        if wallet.address == wordy_address
    )
    homerunhazard = next(
        wallet
        for wallet in result.valid_wallets
        if wallet.address == homerunhazard_address
    )

    assert others
    assert ferrari.event_portfolio_netting_required is True
    assert wordy.event_portfolio_netting_required is True
    assert homerunhazard.event_portfolio_netting_required is True
    assert all(wallet.event_portfolio_netting_required is False for wallet in others)
