from __future__ import annotations

from wallet_loader import load_wallets, normalize_wallet_address


def test_wallet_validation_and_normalization(tmp_path):
    wallet_file = tmp_path / "wallets.json"
    wallet_file.write_text(
        """
[
  {"address": "0xABCDEFabcdefABCDEFabcdefABCDEFabcdefabcd", "label": "One", "enabled": true, "base_unit": null, "notes": ""},
  {"address": "0x1234567890abcdef1234567890abcdef12345678", "label": "Two", "enabled": false, "base_unit": 100, "notes": ""}
]
        """.strip(),
        encoding="utf-8",
    )
    result = load_wallets(wallet_file)
    assert len(result.valid_wallets) == 2
    assert result.wallets[0].address == "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd"
    assert result.wallets[1].address == "0x1234567890abcdef1234567890abcdef12345678"
    assert result.enabled_wallets[0].address == "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd"


def test_duplicate_wallets_are_rejected(tmp_path):
    wallet_file = tmp_path / "wallets.json"
    wallet_file.write_text(
        """
[
  {"address": "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd", "label": "One", "enabled": true, "base_unit": null, "notes": ""},
  {"address": "0xABCDEFabcdefabcdefabcdefabcdefabcdefabcd", "label": "Two", "enabled": true, "base_unit": null, "notes": ""}
]
        """.strip(),
        encoding="utf-8",
    )
    result = load_wallets(wallet_file)
    assert len(result.valid_wallets) == 1
    assert any("Duplicate wallet address" in error.message for error in result.invalid_entries)


def test_missing_wallet_file():
    result = load_wallets(__import__("pathlib").Path("missing-wallets.json"))
    assert result.file_errors


def test_invalid_json(tmp_path):
    wallet_file = tmp_path / "wallets.json"
    wallet_file.write_text("{not json}", encoding="utf-8")
    result = load_wallets(wallet_file)
    assert result.file_errors


def test_disabled_wallets_not_enabled(tmp_path):
    wallet_file = tmp_path / "wallets.json"
    wallet_file.write_text(
        """
[
  {"address": "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd", "label": "One", "enabled": false, "base_unit": null, "notes": ""}
]
        """.strip(),
        encoding="utf-8",
    )
    result = load_wallets(wallet_file)
    assert len(result.enabled_wallets) == 0


def test_normalize_wallet_rejects_bad_input():
    try:
      normalize_wallet_address("bad-wallet")
    except ValueError as exc:
      assert "must start with 0x" in str(exc)
    else:
      raise AssertionError("Expected ValueError")


def test_wallet_metadata_and_thresholds_are_loaded(tmp_path):
    wallet_file = tmp_path / "wallets.json"
    wallet_file.write_text(
        """
[
  {
    "address": "0x9C76CdB43fb46454Da005FBc82047a64A18eC926",
    "label": "Bagwell306",
    "enabled": true,
    "base_unit": 2500,
    "notes": "Manual override",
    "top_category": "Tennis",
    "bettor_type": "Automated systematic directional bettor",
    "selectivity": "Low",
    "selectivity_score": 2,
    "hold_tendency": "High",
    "copyability": "Medium",
    "execution_style": "Fragmented entries and repeated fills",
    "general_strategy": "Broad, model-driven, multi-sport directional betting",
    "minimum_position_units": 0.2,
    "actionable_position_units": 0.5
  }
]
        """.strip(),
        encoding="utf-8",
    )

    result = load_wallets(wallet_file)

    assert len(result.valid_wallets) == 1
    wallet = result.valid_wallets[0]
    assert wallet.address == "0x9c76cdb43fb46454da005fbc82047a64a18ec926"
    assert wallet.display_address == "0x9C76CdB43fb46454Da005FBc82047a64A18eC926"
    assert wallet.base_unit == 2500
    assert wallet.top_category == "Tennis"
    assert wallet.top_categories == ("Tennis",)
    assert wallet.top_category_ids == ("tennis",)
    assert wallet.primary_top_category_id == "tennis"
    assert wallet.top_category_source == "manual_config"
    assert wallet.bettor_type == "Automated systematic directional bettor"
    assert wallet.selectivity == "Low"
    assert wallet.selectivity_score == 2
    assert wallet.minimum_position_units == 0.2
    assert wallet.actionable_position_units == 0.5


def test_wallet_loader_supports_multiple_verified_top_categories(tmp_path):
    wallet_file = tmp_path / "wallets.json"
    wallet_file.write_text(
        """
[
  {
    "address": "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
    "label": "Multi-sport",
    "enabled": true,
    "top_categories": ["MLB", "ATP"],
    "primary_top_category": "MLB",
    "top_category_source": "manually_reviewed_locked",
    "top_category_verified_at": "2026-07-13T12:00:00Z"
  }
]
        """.strip(),
        encoding="utf-8",
    )

    wallet = load_wallets(wallet_file).valid_wallets[0]

    assert wallet.top_categories == ("MLB", "ATP")
    assert wallet.top_category_ids == ("mlb", "tennis")
    assert wallet.primary_top_category_id == "mlb"
    assert wallet.top_category_source == "manually_reviewed_locked"
    assert wallet.top_category_verified_at == "2026-07-13T12:00:00Z"


def test_wallet_loader_keeps_primary_and_sub_top_categories_distinct(tmp_path):
    wallet_file = tmp_path / "wallets.json"
    wallet_file.write_text(
        """
[
  {
    "address": "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
    "label": "Primary and secondary",
    "enabled": true,
    "top_category": "MLB",
    "top_categories": ["MLB"],
    "sub_top_categories": ["Soccer"],
    "primary_top_category": "MLB"
  }
]
        """.strip(),
        encoding="utf-8",
    )

    wallet = load_wallets(wallet_file).valid_wallets[0]

    assert wallet.top_category == "MLB"
    assert wallet.primary_top_category_id == "mlb"
    assert wallet.sub_top_categories == ("Soccer",)
    assert wallet.sub_top_category_ids == ("soccer",)
    assert wallet.top_category_ids == ("mlb", "soccer")


def test_wallet_loader_normalizes_category_specific_signal_roles(tmp_path):
    wallet_file = tmp_path / "wallets.json"
    wallet_file.write_text(
        """
[
  {
    "address": "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
    "label": "MLB specialist",
    "enabled": true,
    "top_category": "MLB",
    "category_signal_roles": {
      "Baseball": {
        "role": "conditional_originator",
        "quality_weight": 0.85,
        "minimum_originator_units": 1.5,
        "requires_clean_directional": true
      }
    }
  }
]
        """.strip(),
        encoding="utf-8",
    )

    wallet = load_wallets(wallet_file).valid_wallets[0]

    assert wallet.category_signal_roles["mlb"] == {
        "role": "CONDITIONAL_ORIGINATOR",
        "quality_weight": 0.85,
        "minimum_originator_units": 1.5,
        "unit_baseline_usd": None,
        "requires_clean_directional": True,
        "source": "provisional_category_review",
    }
