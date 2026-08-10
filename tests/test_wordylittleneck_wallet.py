from pathlib import Path

import pytest

from position_tracker import TrackerService
from wallet_activity import aggregate_trade_fills, normalize_trade_fills
from wallet_loader import load_wallets


WORDY_ADDRESS = "0x3dfb153c197d4c19d3b31c1ecd2c7b6860eeabaf"


def _fill(
    *,
    side: str,
    size: float,
    price: float,
    timestamp: int,
    transaction_hash: str,
) -> dict:
    return {
        "proxyWallet": WORDY_ADDRESS,
        "side": side,
        "asset": "outcome-a",
        "conditionId": "0xwordy-market",
        "size": size,
        "price": price,
        "timestamp": timestamp,
        "title": "Yankees vs Red Sox",
        "slug": "mlb-nyy-bos-2026-07-27",
        "eventSlug": "mlb-nyy-bos-2026-07-27",
        "outcome": "Yankees",
        "transactionHash": transaction_hash,
    }


def _position(*, outcome: str, amount: float, **overrides) -> dict:
    row = {
        "wallet_address": WORDY_ADDRESS,
        "wallet_label": "Wordylittleneck",
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


def test_wordylittleneck_registry_uses_measured_sport_policies():
    result = load_wallets(Path("wallets.json"))
    wallet = next(
        wallet
        for wallet in result.valid_wallets
        if wallet.address == WORDY_ADDRESS
    )

    assert wallet.label == "Wordylittleneck"
    assert wallet.base_unit == 20000
    assert wallet.registry_status == "MLB_LEAD_ELIGIBLE"
    assert wallet.provisional_unit is False
    assert wallet.supporting_weight == pytest.approx(0.8)
    assert wallet.actionable_position_units == pytest.approx(0.5)
    assert wallet.minimum_actionable_exposure_dollars == 10000
    assert wallet.requires_fill_aggregation is True
    assert wallet.hedge_detection_required is True
    assert wallet.event_portfolio_netting_required is True
    assert wallet.category_signal_roles["mlb"]["role"] == "CONDITIONAL_ORIGINATOR"
    assert wallet.category_signal_roles["mlb"]["quality_weight"] == pytest.approx(
        0.88
    )
    assert wallet.category_signal_roles["mlb"]["minimum_originator_units"] == 0.5
    assert wallet.category_signal_roles["mma"]["role"] == "CONDITIONAL_ORIGINATOR"
    assert wallet.category_signal_roles["mma"]["quality_weight"] == pytest.approx(
        0.7
    )
    assert wallet.category_signal_roles["mma"]["minimum_originator_units"] == 1.0
    assert wallet.wallet_forensics["markets"] == 786
    assert wallet.wallet_forensics["realized_pnl_usd"] == pytest.approx(2813072.61)
    assert wallet.wallet_forensics["gross_turnover_roi"] == pytest.approx(0.0525)
    assert wallet.wallet_forensics["clv_status"] == "UNAVAILABLE_NOT_FABRICATED"


@pytest.mark.parametrize(
    ("amount", "units"),
    [(10000, 0.5), (20000, 1.0), (40000, 2.0), (60000, 3.0)],
)
def test_wordylittleneck_measured_unit_math(amount, units):
    assert amount / 20000 == pytest.approx(units)


def test_sell_fills_reduce_remaining_position_before_unit_sizing():
    rows = [
        _fill(
            side="BUY",
            size=50000,
            price=0.4,
            timestamp=1,
            transaction_hash="0x1",
        ),
        _fill(
            side="SELL",
            size=10000,
            price=0.6,
            timestamp=2,
            transaction_hash="0x2",
        ),
    ]
    fills, duplicates = normalize_trade_fills(WORDY_ADDRESS, [*rows, rows[0]])
    aggregate = aggregate_trade_fills(fills)[("0xwordy-market", "outcome-a")]

    assert duplicates == 1
    assert aggregate["buy_fill_count"] == 1
    assert aggregate["sell_fill_count"] == 1
    assert aggregate["remaining_shares"] == pytest.approx(40000)
    assert aggregate["remaining_cost_basis"] == pytest.approx(16000)
    assert aggregate["remaining_cost_basis"] / 20000 == pytest.approx(0.8)


def test_material_event_conflict_blocks_wordy_signal():
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


def test_unrelated_wallets_keep_their_event_netting_configuration():
    result = load_wallets(Path("wallets.json"))
    by_label = {wallet.label: wallet for wallet in result.valid_wallets}

    assert by_label["Wordylittleneck"].event_portfolio_netting_required is True
    assert by_label["phonesculptor"].event_portfolio_netting_required is True
    assert by_label["Bagwell306"].event_portfolio_netting_required is False
