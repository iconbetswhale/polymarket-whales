from pathlib import Path

import pytest

from position_tracker import TrackerService
from trade_scoring import _relative_units
from wallet_activity import aggregate_trade_fills, normalize_trade_fills
from wallet_loader import load_wallets


PHONESCULPTOR_ADDRESS = "0xf1528f12e645462c344799b62b1b421a6a4c64aa"


def _fill(*, side: str, size: float, price: float, transaction_hash: str) -> dict:
    return {
        "proxyWallet": PHONESCULPTOR_ADDRESS,
        "side": side,
        "asset": "outcome-a",
        "conditionId": "0xphonesculptor-market",
        "size": size,
        "price": price,
        "timestamp": 1 if side == "BUY" else 2,
        "title": "Yankees vs Red Sox",
        "slug": "mlb-nyy-bos-2026-07-27",
        "eventSlug": "mlb-nyy-bos-2026-07-27",
        "outcome": "Yankees",
        "transactionHash": transaction_hash,
    }


def _position(*, outcome: str, amount: float, **overrides) -> dict:
    row = {
        "wallet_address": PHONESCULPTOR_ADDRESS,
        "wallet_label": "phonesculptor",
        "condition_id": f"0x{outcome.lower().replace(' ', '-')}",
        "event_slug": "mlb-nyy-bos-2026-07-27",
        "market_slug": "mlb-nyy-bos-2026-07-27",
        "market_title": "Yankees vs Red Sox",
        "outcome": outcome,
        "position_size_usd": amount,
        "signal_position_size_usd": amount,
        "net_directional_exposure_usd": amount,
        "directional_weight": 1.0,
        "two_sided_status": "CLEAN_DIRECTIONAL",
        "event_portfolio_netting_required": True,
    }
    row.update(overrides)
    return row


def test_phonesculptor_registry_uses_provider_backed_multi_sport_policy():
    wallet = next(
        wallet
        for wallet in load_wallets(Path("wallets.json")).valid_wallets
        if wallet.address == PHONESCULPTOR_ADDRESS
    )

    assert wallet.label == "phonesculptor"
    assert wallet.base_unit == 29000
    assert wallet.registry_status == "MLB_LEAD_ELIGIBLE"
    assert wallet.provisional_unit is False
    assert wallet.supporting_weight == pytest.approx(0.8)
    assert wallet.lead_sharp_eligible is True
    assert wallet.standard_originator_eligible is True
    assert wallet.requires_fill_aggregation is True
    assert wallet.hedge_detection_required is True
    assert wallet.event_portfolio_netting_required is True
    assert wallet.category_signal_roles["mlb"] == {
        "role": "CONDITIONAL_ORIGINATOR",
        "consensus_role": "DIRECTIONAL_CORE",
        "quality_weight": 0.76,
        "minimum_originator_units": 0.5,
        "unit_baseline_usd": 29000.0,
        "requires_clean_directional": True,
        "source": "provider_backed_mlb_forensics_2026_07_26",
    }
    assert wallet.category_signal_roles["soccer"] == {
        "role": "CONDITIONAL_ORIGINATOR",
        "quality_weight": 0.86,
        "minimum_originator_units": 0.5,
        "unit_baseline_usd": 38750.0,
        "requires_clean_directional": True,
        "source": "provider_backed_soccer_forensics_2026_07_26",
    }
    assert wallet.wallet_forensics["markets"] == 687
    assert wallet.wallet_forensics["realized_pnl_usd"] == pytest.approx(655642.51)
    assert wallet.wallet_forensics["gross_turnover_roi"] == pytest.approx(0.0284)
    assert wallet.wallet_forensics["clv_status"] == "UNAVAILABLE_NOT_FABRICATED"


@pytest.mark.parametrize(
    ("amount", "units"),
    [(14500, 0.5), (29000, 1.0), (58000, 2.0), (87000, 3.0)],
)
def test_phonesculptor_measured_mlb_unit_math(amount, units):
    assert amount / 29000 == pytest.approx(units)


def test_soccer_uses_its_own_measured_unit_in_scoring():
    position = {
        "wallet_address": PHONESCULPTOR_ADDRESS,
        "signal_position_size_usd": 19375,
        "category_unit_baseline_usd": 38750,
    }

    units = _relative_units(
        position,
        {
            PHONESCULPTOR_ADDRESS: {
                "estimated_base_unit": 29000,
            }
        },
        {},
    )

    assert units == pytest.approx(0.5)


def test_sell_fills_reduce_phonesculptor_position_before_unit_sizing():
    rows = [
        _fill(side="BUY", size=50000, price=0.58, transaction_hash="0x1"),
        _fill(side="SELL", size=10000, price=0.62, transaction_hash="0x2"),
    ]
    fills, duplicates = normalize_trade_fills(
        PHONESCULPTOR_ADDRESS, [*rows, rows[0]]
    )
    aggregate = aggregate_trade_fills(fills)[
        ("0xphonesculptor-market", "outcome-a")
    ]

    assert duplicates == 1
    assert aggregate["buy_fill_count"] == 1
    assert aggregate["sell_fill_count"] == 1
    assert aggregate["remaining_shares"] == pytest.approx(40000)
    assert aggregate["remaining_cost_basis"] == pytest.approx(23200)
    assert aggregate["remaining_cost_basis"] / 29000 == pytest.approx(0.8)


def test_material_event_conflict_cannot_originate_for_phonesculptor():
    rows = [
        _position(outcome="Yankees", amount=30000),
        _position(
            outcome="Red Sox",
            amount=10000,
            market_slug="mlb-nyy-bos-2026-07-27-spread-away-1pt5",
            market_title="Spread: Red Sox +1.5",
        ),
    ]

    TrackerService._apply_event_portfolio_netting(rows)

    assert rows[0]["event_portfolio_status"] == "MATERIAL_EVENT_HEDGE"
    assert rows[0]["signal_position_size_usd"] == 0
    assert rows[0]["signal_rejection_reason"] == "EVENT_PORTFOLIO_DIRECTION_UNCLEAR"
    assert rows[1]["signal_position_size_usd"] == 0


def test_phonesculptor_clv_is_not_fabricated():
    wallet = next(
        wallet
        for wallet in load_wallets(Path("wallets.json")).valid_wallets
        if wallet.address == PHONESCULPTOR_ADDRESS
    )
    soccer = wallet.wallet_forensics["secondary_category_forensics"]

    assert soccer["clv_status"] == "UNAVAILABLE_NOT_FABRICATED"
    assert "exchange_clv" not in soccer
    assert "composite_clv" not in soccer
