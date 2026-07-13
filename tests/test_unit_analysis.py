from unit_analysis import amount_to_units, estimate_unit_size


def test_unit_size_estimation():
    result = estimate_unit_size(
        wallet_address="0xabc",
        wallet_label="Wallet",
        samples=[100, 200, 50, 150, 300],
        manual_override=None,
    )
    assert result.estimated_base_unit == 100
    assert result.confidence in {"medium", "high", "low"}


def test_manual_unit_override():
    result = estimate_unit_size(
        wallet_address="0xabc",
        wallet_label="Wallet",
        samples=[100, 200],
        manual_override=125,
    )
    assert result.confidence == "manual"
    assert result.estimated_base_unit == 125


def test_amount_to_units():
    assert amount_to_units(150, 100) == 1.5


def test_amount_to_units_keeps_full_precision():
    assert amount_to_units(2425, 2500) == 0.97
    assert amount_to_units(3895, 2500) == 1.558
