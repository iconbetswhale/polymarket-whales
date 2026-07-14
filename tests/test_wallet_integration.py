from __future__ import annotations

import json
from pathlib import Path

from config import Settings
from database import TrackerDatabase
from position_tracker import TrackerService
from wallet_loader import load_wallets


REQUESTED_WALLETS = {
    "0x4f2": "0x4f29e103339919c4baaea2a60195cf1c8bb27a7e",
    "Weflyhigh": "0x03e8a544e97eeff5753bc1e90d46e5ef22af1697",
    "sportmaster777": "0x32ed517a571c01b6e9adecf61ba81ca48ff2f960",
    "Wordylittleneck": "0x3dfb153c197d4c19d3b31c1ecd2c7b6860eeabaf",
    "phonesculptor": "0xf1528f12e645462c344799b62b1b421a6a4c64aa",
    "Surfandturf": "0x9f2fe025f84839ca81dd8e0338892605702d2ca8",
    "Bagwell306": "0x9c76cdb43fb46454da005fbc82047a64a18ec926",
    "ferrariChampions2026": "0xfe787d2da716d60e8acff57fb87eb13cd4d10319",
}


class PartialFailureClient:
    def __init__(self, good_wallet: str, failing_wallet: str) -> None:
        self.good_wallet = good_wallet
        self.failing_wallet = failing_wallet

    def get_current_positions(self, wallet_address: str):
        if wallet_address == self.failing_wallet:
            raise RuntimeError("simulated current-position sync failure")
        if wallet_address != self.good_wallet:
            return []
        return [
            {
                "conditionId": "0x1111111111111111111111111111111111111111111111111111111111111111",
                "size": 1000,
                "avgPrice": 0.5,
                "initialValue": 500,
                "currentValue": 550,
                "cashPnl": 50,
                "realizedPnl": 0,
                "curPrice": 0.55,
                "title": "Will France win on 2026-07-14?",
                "slug": "fifwc-fra-esp-2026-07-14-fra",
                "eventSlug": "fifwc-fra-esp-2026-07-14",
                "eventId": "691040",
                "outcome": "No",
                "oppositeOutcome": "Yes",
                "startTime": "2026-07-14T19:00:00Z",
                "endDate": "2026-07-14T19:00:00Z",
            }
        ]

    def get_closed_positions(self, wallet_address: str, limit: int = 50):
        return []

    def get_events(self, event_slugs, max_workers: int = 8):
        return {}

    def get_public_profile(self, wallet_address: str):
        return None


def _settings(tmp_path: Path, wallets_file: Path) -> Settings:
    return Settings(
        dashboard_refresh=120,
        dashboard_port=5000,
        wallets_file=wallets_file,
        database_path=tmp_path / "tracker.db",
        sports_only=True,
        resolve_hours=168000,
        min_american_odds=None,
        max_american_odds=None,
        request_timeout=15,
        max_retries=1,
        admin_password=None,
    )


def test_authoritative_wallet_file_contains_requested_normalized_mappings():
    result = load_wallets(Path("wallets.json"))
    by_label = {wallet.label: wallet.address for wallet in result.valid_wallets}

    for label, address in REQUESTED_WALLETS.items():
        assert by_label[label] == address
    assert not result.invalid_entries
    assert len({wallet.address for wallet in result.valid_wallets}) == len(
        result.valid_wallets
    )

    bagwell = next(
        wallet for wallet in result.valid_wallets if wallet.label == "Bagwell306"
    )
    assert bagwell.base_unit == 2500
    assert bagwell.top_category == "Tennis"
    assert bagwell.actionable_position_units == 0.5

    wallet_4f2 = next(
        wallet for wallet in result.valid_wallets if wallet.label == "0x4f2"
    )
    assert wallet_4f2.top_category == "MLB"
    assert wallet_4f2.top_category_ids == ("mlb",)
    assert wallet_4f2.primary_top_category_id == "mlb"
    assert wallet_4f2.top_category_source == "manually_reviewed_locked"

    ferrari = next(
        wallet
        for wallet in result.valid_wallets
        if wallet.label == "ferrariChampions2026"
    )
    assert ferrari.base_unit == 5000
    assert ferrari.top_category_ids == ("mlb",)
    assert ferrari.minimum_actionable_exposure_dollars == 2500
    assert ferrari.requires_fill_aggregation is True


def test_case_insensitive_duplicate_request_is_rejected(tmp_path):
    wallet_file = tmp_path / "wallets.json"
    wallet_file.write_text(
        json.dumps(
            [
                {
                    "address": REQUESTED_WALLETS["Wordylittleneck"],
                    "label": "Wordylittleneck",
                    "enabled": True,
                    "base_unit": None,
                    "notes": "",
                },
                {
                    "address": "0x3DFb153c197D4C19D3B31c1ecD2c7B6860eeabAf",
                    "label": "Duplicate",
                    "enabled": True,
                    "base_unit": None,
                    "notes": "",
                },
            ]
        ),
        encoding="utf-8",
    )

    result = load_wallets(wallet_file)

    assert len(result.valid_wallets) == 1
    assert result.valid_wallets[0].label == "Wordylittleneck"
    assert any(
        error.message == "Duplicate wallet address" for error in result.invalid_entries
    )


def test_failed_wallet_sync_is_visible_and_excluded_from_positions(tmp_path):
    good_wallet = REQUESTED_WALLETS["Weflyhigh"]
    failing_wallet = REQUESTED_WALLETS["Surfandturf"]
    wallet_file = tmp_path / "wallets.json"
    wallet_file.write_text(
        json.dumps(
            [
                {
                    "address": good_wallet,
                    "label": "Weflyhigh",
                    "enabled": True,
                    "base_unit": 1000,
                    "notes": "",
                },
                {
                    "address": failing_wallet,
                    "label": "Surfandturf",
                    "enabled": True,
                    "base_unit": 1000,
                    "notes": "",
                },
            ]
        ),
        encoding="utf-8",
    )
    settings = _settings(tmp_path, wallet_file)
    service = TrackerService(
        settings,
        client=PartialFailureClient(good_wallet, failing_wallet),
        database=TrackerDatabase(settings.database_path),
        auto_start=False,
    )

    service.refresh()
    snapshot = service.get_snapshot()
    wallets = {wallet["label"]: wallet for wallet in snapshot["wallets"]}

    assert wallets["Weflyhigh"]["sync_status"] == "ready"
    assert wallets["Surfandturf"]["sync_status"] == "failed"
    assert [position["wallet_label"] for position in snapshot["positions"]] == [
        "Weflyhigh"
    ]
    assert all(
        trade["primary_trader"]["wallet_label"] == "Weflyhigh"
        for trade in snapshot["trades_to_play"]
    )
