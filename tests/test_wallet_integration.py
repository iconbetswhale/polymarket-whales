from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import Settings
from database import TrackerDatabase
from position_tracker import (
    TrackerService,
    canonical_sports_market_type,
    category_signal_policy_for_market,
    scoped_category_signal_policy,
)
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
    "HomeRunHazard": "0x5268527977f700f9bf9b6d5cd843859e4e70135d",
    "Formal-Cupcake": "0xb8c842bc049bf208f73354c7b037b811d741d8a4",
    "DaBossHogg": "0x6157d529ae129fe08f22a27ed42e741d2eaa9fb4",
    "Portly-Derivation": "0x8a3ab8120807bd64a3de48695110e390fa2ceb9a",
    "HuntersMethDealer": "0x398900e95487c704ac3b52fd653e1697d32227b1",
    "EVhunter69": "0x8ce7eb8a3ad1d6907b24368865c8487a68fb3150",
    "Positive-Console": "0x684baa57c338c2549aec0aa3f034f695d72a8409",
    "Canoflanagan": "0x21468ad63a833f5f9ea5c2835fb4e9dec57ad41b",
    "Undisputa": "0x986c0ba5ae79c5cf171cfa8e85afe186412a3180",
    "SineNooneEI": "0x38337de21ff0bb0a11a40761507d51e318d633d1",
}

EXPECTED_TOP_CATEGORIES = {
    "0x4f2": "mlb",
    "1winstreak1": "mlb",
    "Weflyhigh": "nba",
    "sportmaster777": "mlb",
    "Wordylittleneck": "mlb",
    "phonesculptor": "mlb",
    "Surfandturf": "nba",
    "Bagwell306": "tennis",
    "Lilybaeum": "tennis",
    "ferrariChampions2026": "mlb",
    "Soarin22": "mlb",
    "HomeRunHazard": "mlb",
    "Formal-Cupcake": "mlb",
    "BreakTheBank": "soccer",
    "DaBossHogg": "tennis",
    "Portly-Derivation": "nba",
    "Dingwin": "mlb",
    "mlbman": "mlb",
    "Talvez10": "mlb",
    "jtwyslljy": "soccer",
    "BaccaratRoulette": "tennis",
    "UpTheBlues": "mlb",
    "SnakeBall": "mlb",
    "HuntersMethDealer": "nfl",
    "EVhunter69": "mlb",
    "Positive-Console": "mlb",
    "Canoflanagan": "wnba",
    "Undisputa": "nba",
    "SineNooneEI": "tennis",
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
        event_time = datetime.now(timezone.utc) + timedelta(days=1)
        event_date = event_time.date().isoformat()
        event_time_iso = event_time.isoformat().replace("+00:00", "Z")
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
                "title": f"Will France win on {event_date}?",
                "slug": f"fifwc-fra-esp-{event_date}-fra",
                "eventSlug": f"fifwc-fra-esp-{event_date}",
                "eventId": "691040",
                "outcome": "No",
                "oppositeOutcome": "Yes",
                "startTime": event_time_iso,
                "endDate": event_time_iso,
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
    assert bagwell.base_unit == 875
    assert bagwell.top_category == "Tennis"
    assert bagwell.actionable_position_units == 1.0

    daboss = next(
        wallet for wallet in result.valid_wallets if wallet.label == "DaBossHogg"
    )
    assert daboss.base_unit == 5050
    assert daboss.top_category == "Tennis"
    assert daboss.actionable_position_units == 1.0
    assert daboss.category_signal_roles["tennis"]["role"] == "CONDITIONAL_ORIGINATOR"
    assert daboss.category_signal_roles["tennis"]["minimum_originator_units"] == 1.0

    portly = next(
        wallet for wallet in result.valid_wallets if wallet.label == "Portly-Derivation"
    )
    assert portly.base_unit == 9450
    assert portly.primary_top_category_id == "nba"
    assert portly.actionable_position_units == 1.0
    assert portly.category_signal_roles["nba"]["unit_baseline_usd"] == 10200
    assert portly.category_signal_roles["mma"]["unit_baseline_usd"] == 8400
    assert portly.category_signal_roles["tennis"]["role"] == "RESEARCH"
    assert portly.wallet_forensics["two_sided_markets"] == 0

    hunters = next(
        wallet for wallet in result.valid_wallets if wallet.label == "HuntersMethDealer"
    )
    assert hunters.base_unit == 900
    assert hunters.primary_top_category_id == "nfl"
    assert hunters.actionable_position_units == 0.5
    assert hunters.minimum_actionable_exposure_dollars == 450
    assert hunters.lead_sharp_eligible is False
    assert hunters.supporting_sharp_eligible is True
    assert hunters.supporting_weight == 0.25
    assert hunters.category_signal_roles["nfl"]["role"] == "CONFIRMER"
    assert (
        hunters.category_signal_roles["nfl"]["consensus_role"]
        == "NETTED_CONFIRMER"
    )
    assert hunters.category_signal_roles["nfl"]["quality_weight"] == 0.25
    assert hunters.category_signal_roles["soccer"]["role"] == "RESEARCH"
    assert hunters.category_signal_roles["nfl"]["allowed_market_types"] == (
        "Moneyline",
    )
    assert hunters.wallet_forensics["measured_unit_usd"] == 900
    assert hunters.wallet_forensics["policy"].startswith("LIMITED_CONFIRMER_0_25")

    evhunter = next(
        wallet for wallet in result.valid_wallets if wallet.label == "EVhunter69"
    )
    assert evhunter.base_unit == 575
    assert evhunter.top_category_ids == ("mlb", "tennis")
    assert evhunter.supporting_weight == 0.5
    assert evhunter.standard_originator_eligible is True
    assert evhunter.minimum_actionable_exposure_dollars == 575
    for category in ("mlb", "tennis"):
        policy = evhunter.category_signal_roles[category]
        assert policy["role"] == "CONDITIONAL_ORIGINATOR"
        assert policy["quality_weight"] == 0.5
        assert policy["minimum_originator_units"] == 1.0
        assert policy["allowed_market_types"] == ("Moneyline",)

    sinenooneei = next(
        wallet for wallet in result.valid_wallets if wallet.label == "SineNooneEI"
    )
    assert sinenooneei.base_unit == 10475
    assert sinenooneei.top_category_ids == ("tennis",)
    assert sinenooneei.standard_originator_eligible is True
    assert sinenooneei.lead_sharp_eligible is True
    assert sinenooneei.minimum_actionable_exposure_dollars == 10475
    assert set(sinenooneei.category_signal_roles) == {"tennis"}
    tennis_policy = sinenooneei.category_signal_roles["tennis"]
    assert tennis_policy["role"] == "CONDITIONAL_ORIGINATOR"
    assert tennis_policy["quality_weight"] == 1.0
    assert tennis_policy["minimum_originator_units"] == 1.0
    assert tennis_policy["unit_baseline_usd"] == 10475
    assert tennis_policy["allowed_market_types"] == ("Moneyline",)
    assert "EXCLUDE_ALL_ESPORTS" in sinenooneei.wallet_forensics["policy"]

    positive_console = next(
        wallet for wallet in result.valid_wallets if wallet.label == "Positive-Console"
    )
    assert positive_console.base_unit == 6575
    assert positive_console.top_category_ids == ("mlb", "wnba")
    assert positive_console.lead_sharp_eligible is False
    assert positive_console.supporting_sharp_eligible is False
    assert positive_console.minimum_actionable_exposure_dollars == 3287.5
    assert positive_console.category_signal_roles["wnba"]["allowed_market_types"] == (
        "Spread",
    )
    assert positive_console.wallet_forensics["policy"].startswith("SHADOW_ONLY")

    canoflanagan = next(
        wallet for wallet in result.valid_wallets if wallet.label == "Canoflanagan"
    )
    assert canoflanagan.base_unit == 2175
    assert canoflanagan.primary_top_category_id == "wnba"
    assert canoflanagan.lead_sharp_eligible is False
    assert canoflanagan.supporting_sharp_eligible is False
    assert canoflanagan.minimum_actionable_exposure_dollars == 1087.5
    assert canoflanagan.category_signal_roles["wnba"]["allowed_market_types"] == (
        "Spread",
    )
    assert canoflanagan.wallet_forensics["two_sided_markets"] == 72

    undisputa = next(
        wallet for wallet in result.valid_wallets if wallet.label == "Undisputa"
    )
    assert undisputa.base_unit == 1300
    assert undisputa.top_category_ids == ("nba", "soccer", "nhl")
    assert undisputa.lead_sharp_eligible is False
    assert undisputa.supporting_sharp_eligible is True
    assert undisputa.supporting_weight == 0.25
    assert undisputa.minimum_actionable_exposure_dollars == 650
    for category in ("nba", "soccer"):
        assert undisputa.category_signal_roles[category]["role"] == "CONFIRMER"
        assert (
            undisputa.category_signal_roles[category]["consensus_role"]
            == "NETTED_CONFIRMER"
        )
        assert undisputa.category_signal_roles[category]["quality_weight"] == 0.25
        assert undisputa.category_signal_roles[category]["allowed_market_types"] == (
            "Moneyline",
        )
    assert undisputa.category_signal_roles["nba"]["minimum_originator_units"] == 0.5
    assert undisputa.category_signal_roles["soccer"]["minimum_originator_units"] == 0.5
    assert undisputa.category_signal_roles["nhl"]["role"] == "RESEARCH"
    assert undisputa.category_signal_roles["nhl"]["minimum_originator_units"] == 1.0
    assert undisputa.wallet_forensics["one_unit_clean_nhl_moneyline_markets"] == 66
    assert undisputa.wallet_forensics["nfl_moneyline_markets"] == 3
    assert undisputa.wallet_forensics["policy"].startswith("LIMITED_CONFIRMER_0_25")

    wallet_4f2 = next(
        wallet for wallet in result.valid_wallets if wallet.label == "0x4f2"
    )
    assert wallet_4f2.top_category == "MLB"
    assert wallet_4f2.top_category_ids == ("mlb",)
    assert wallet_4f2.primary_top_category_id == "mlb"
    assert wallet_4f2.top_category_source == "manually_reviewed_locked"
    assert wallet_4f2.base_unit == 8000
    assert wallet_4f2.requires_fill_aggregation is True
    assert wallet_4f2.hedge_detection_required is True
    assert wallet_4f2.actionable_position_units == 0.2
    assert wallet_4f2.minimum_actionable_exposure_dollars == 1600
    assert wallet_4f2.category_signal_roles["mlb"][
        "requires_clean_directional"
    ] is True
    assert wallet_4f2.category_signal_roles["mlb"][
        "minimum_originator_units"
    ] == 0.2
    assert wallet_4f2.wallet_forensics["clean_directional_markets"] == 322
    assert wallet_4f2.wallet_forensics["two_sided_markets"] == 527

    ferrari = next(
        wallet
        for wallet in result.valid_wallets
        if wallet.label == "ferrariChampions2026"
    )
    assert ferrari.base_unit == 17000
    assert ferrari.top_category_ids == ("mlb", "tennis")
    assert ferrari.sub_top_categories == ("Tennis",)
    assert ferrari.sub_top_category_ids == ("tennis",)
    assert ferrari.actionable_position_units == 0.2
    assert ferrari.minimum_actionable_exposure_dollars == 3400
    assert ferrari.requires_fill_aggregation is True
    assert ferrari.event_portfolio_netting_required is True

    phonesculptor = next(
        wallet for wallet in result.valid_wallets if wallet.label == "phonesculptor"
    )
    assert phonesculptor.top_category == "MLB"
    assert phonesculptor.primary_top_category_id == "mlb"
    assert phonesculptor.sub_top_categories == ("Soccer",)
    assert phonesculptor.sub_top_category_ids == ("soccer",)
    assert phonesculptor.top_category_ids == ("mlb", "soccer")
    assert phonesculptor.base_unit == 29000
    assert phonesculptor.actionable_position_units == 0.5
    assert phonesculptor.minimum_actionable_exposure_dollars == 14500
    assert phonesculptor.requires_fill_aggregation is True
    assert phonesculptor.hedge_detection_required is True
    assert phonesculptor.event_portfolio_netting_required is True
    assert (
        phonesculptor.category_signal_roles["soccer"]["unit_baseline_usd"]
        == 38750
    )

    weflyhigh = next(
        wallet for wallet in result.valid_wallets if wallet.label == "Weflyhigh"
    )
    assert weflyhigh.primary_top_category_id == "nba"
    assert weflyhigh.sub_top_categories == ("NHL", "MLB")
    assert weflyhigh.sub_top_category_ids == ("nhl", "mlb")
    assert weflyhigh.top_category_ids == ("nba", "nhl", "mlb")

    sportmaster = next(
        wallet for wallet in result.valid_wallets if wallet.label == "sportmaster777"
    )
    assert sportmaster.primary_top_category_id == "mlb"
    assert sportmaster.sub_top_categories == ("NBA", "NHL", "Soccer")
    assert sportmaster.sub_top_category_ids == ("nba", "nhl", "soccer")
    assert sportmaster.top_category_ids == ("mlb", "nba", "nhl", "soccer")
    assert sportmaster.base_unit == 6000
    assert sportmaster.actionable_position_units == 0.25
    assert sportmaster.minimum_actionable_exposure_dollars == 1500
    assert sportmaster.requires_fill_aggregation is True
    assert sportmaster.hedge_detection_required is True
    assert sportmaster.event_portfolio_netting_required is True

    wordylittleneck = next(
        wallet for wallet in result.valid_wallets if wallet.label == "Wordylittleneck"
    )
    assert wordylittleneck.primary_top_category_id == "mlb"
    assert wordylittleneck.sub_top_categories == ("UFC",)
    assert wordylittleneck.sub_top_category_ids == ("mma",)
    assert wordylittleneck.top_category_ids == ("mlb", "mma")
    assert wordylittleneck.base_unit == 20000
    assert wordylittleneck.actionable_position_units == 0.5
    assert wordylittleneck.minimum_actionable_exposure_dollars == 10000
    assert wordylittleneck.requires_fill_aggregation is True
    assert wordylittleneck.event_portfolio_netting_required is True

    surfandturf = next(
        wallet for wallet in result.valid_wallets if wallet.label == "Surfandturf"
    )
    assert surfandturf.primary_top_category_id == "nba"
    assert surfandturf.sub_top_categories == ("UFC",)
    assert surfandturf.sub_top_category_ids == ("mma",)
    assert surfandturf.top_category_ids == ("nba", "mma")


def test_market_type_restrictions_are_enforced_fail_closed():
    policy = {
        "role": "CONFIRMER",
        "consensus_role": "NETTED_CONFIRMER",
        "quality_weight": 0.25,
        "allowed_market_types": ("Moneyline",),
        "source": "test",
    }

    assert canonical_sports_market_type("money_line") == "Moneyline"
    assert canonical_sports_market_type("game_total") == "Total"
    assert scoped_category_signal_policy(policy, "Moneyline") is policy

    for market_type in ("Total", "Spread", None):
        restricted = scoped_category_signal_policy(policy, market_type)
        assert restricted["role"] == "RESEARCH"
        assert restricted["consensus_role"] == "RESEARCH"
        assert restricted["quality_weight"] == 0.0
        assert restricted["source"].endswith(":market_type_excluded")

    excluded_category = category_signal_policy_for_market(
        {"nfl": policy}, "nba", "Moneyline"
    )
    assert excluded_category["role"] == "RESEARCH"
    assert excluded_category["quality_weight"] == 0.0
    assert excluded_category["source"] == "registry:category_excluded"


def test_every_enabled_wallet_has_an_authoritative_top_category():
    result = load_wallets(Path("wallets.json"))
    by_label = {wallet.label: wallet for wallet in result.enabled_wallets}

    assert set(by_label) == set(EXPECTED_TOP_CATEGORIES)
    for label, category_id in EXPECTED_TOP_CATEGORIES.items():
        wallet = by_label[label]
        assert wallet.primary_top_category_id == category_id
        assert category_id in wallet.top_category_ids
        assert wallet.top_category_source
        assert wallet.top_category_verified_at


def test_wallet_payload_includes_live_stats_for_primary_and_sub_top_categories(tmp_path):
    wallet = next(
        item
        for item in load_wallets(Path("wallets.json")).enabled_wallets
        if item.label == "phonesculptor"
    )
    service = object.__new__(TrackerService)
    service.database = TrackerDatabase(tmp_path / "tracker.db")
    service.database.sync_wallet_registry([wallet.__dict__])
    payload = [
        {
            "address": wallet.address,
            "label": wallet.label,
            "status": "enabled",
            "top_category": "MLB",
            "primary_top_category_id": "mlb",
            "sub_top_category_ids": ["soccer"],
        }
    ]
    category_metrics = {
        wallet.address: {
            "top_category": "MLB",
            "top_category_source": "statistically_verified",
            "categories": {
                "MLB": {
                    "sample_size": 24,
                    "wins": 17,
                    "losses": 7,
                    "raw_hit_rate": 17 / 24,
                    "adjusted_hit_rate": 69 / 124,
                    "profit_loss": 1250,
                },
                "Soccer": {
                    "sample_size": 18,
                    "wins": 12,
                    "losses": 6,
                    "raw_hit_rate": 2 / 3,
                    "adjusted_hit_rate": 62 / 118,
                    "profit_loss": 740,
                },
            },
        }
    }

    service._apply_wallet_sync_status(
        payload,
        [wallet],
        {wallet.address: []},
        {wallet.address: [object()] * 24},
        [],
        "2026-07-15T12:00:00+00:00",
        {},
        category_metrics,
    )

    assert payload[0]["top_category_stats"]["category"] == "MLB"
    assert payload[0]["top_category_stats"]["sample_size"] == 24
    assert payload[0]["top_category_stats"]["profit_loss"] == 1250
    assert payload[0]["sub_top_category_stats"] == [
        {
            "category": "Soccer",
            "sample_size": 18,
            "wins": 12,
            "losses": 6,
            "raw_hit_rate": 2 / 3,
            "adjusted_hit_rate": 62 / 118,
            "profit_loss": 740,
        }
    ]


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
