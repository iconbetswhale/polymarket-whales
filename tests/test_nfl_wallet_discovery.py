from scripts.discover_nfl_wallet_candidates import (
    aggregate_exact_markets,
    is_nfl_game_event,
    load_wallet_registry,
    merge_candidates,
    select_liquid_main_markets,
    settled_unredeemed_positions,
    summarize_markets,
)


def test_only_dated_nfl_games_are_discovery_events():
    assert is_nfl_game_event({"slug": "nfl-lv-hou-2026-08-21"})
    assert not is_nfl_game_event({"slug": "pro-football-2027-champion"})
    assert not is_nfl_game_event({"slug": "will-player-win-nfl-mvp"})


def test_selects_most_liquid_full_game_line_per_type():
    events = [
        {
            "id": "1",
            "slug": "nfl-lv-hou-2026-08-21",
            "title": "Raiders vs. Texans",
            "markets": [
                {
                    "conditionId": "0x1",
                    "slug": "nfl-lv-hou-2026-08-21",
                    "sportsMarketType": "moneyline",
                    "volume": "100",
                    "active": True,
                    "closed": False,
                    "clobTokenIds": '["token-1", "token-2"]',
                },
                {
                    "conditionId": "0x2",
                    "slug": "nfl-lv-hou-2026-08-21-total-37pt5",
                    "sportsMarketType": "totals",
                    "volume": "25",
                    "active": True,
                    "closed": False,
                    "clobTokenIds": '["token-3", "token-4"]',
                },
                {
                    "conditionId": "0x3",
                    "slug": "nfl-lv-hou-2026-08-21-total-38pt5",
                    "sportsMarketType": "totals",
                    "volume": "75",
                    "active": True,
                    "closed": False,
                    "clobTokenIds": '["token-5", "token-6"]',
                },
                {
                    "conditionId": "0x4",
                    "slug": "nfl-lv-hou-2026-08-21-1h-total-19pt5",
                    "sportsMarketType": "first_half_totals",
                    "volume": "200",
                    "active": True,
                    "closed": False,
                    "clobTokenIds": '["token-7", "token-8"]',
                },
            ],
        }
    ]
    selected = select_liquid_main_markets(events)
    assert {row["condition_id"] for row in selected} == {"0x1", "0x3"}
    assert next(row for row in selected if row["condition_id"] == "0x1")[
        "clob_token_ids"
    ] == ["token-1", "token-2"]


def test_exact_market_netting_rejects_two_sided_and_scores_clean_copy():
    rows = [
        {
            "conditionId": "clean",
            "eventSlug": "nfl-lv-hou-2026-08-21",
            "slug": "nfl-lv-hou-2026-08-21",
            "avgPrice": 0.5,
            "totalBought": 100,
            "curPrice": 1,
            "realizedPnl": 50,
            "timestamp": 1,
        },
        {
            "conditionId": "two-sided",
            "eventSlug": "nfl-bal-min-2026-08-22",
            "slug": "nfl-bal-min-2026-08-22-total-37pt5",
            "avgPrice": 0.5,
            "totalBought": 100,
            "curPrice": 1,
            "realizedPnl": 50,
            "timestamp": 2,
        },
        {
            "conditionId": "two-sided",
            "eventSlug": "nfl-bal-min-2026-08-22",
            "slug": "nfl-bal-min-2026-08-22-total-37pt5",
            "avgPrice": 0.5,
            "totalBought": 80,
            "curPrice": 0,
            "realizedPnl": -40,
            "timestamp": 2,
        },
    ]
    markets = aggregate_exact_markets(rows)
    clean = [row for row in markets if row["clean_directional"]]
    assert len(clean) == 1
    summary = summarize_markets(clean)
    assert summary["record"] == "1-0"
    assert summary["flat_copy_profit_units"] == 1.0
    assert summary["flat_copy_roi"] == 1.0


def test_terminal_unredeemed_losers_are_restored_to_settled_history():
    rows = [
        {
            "conditionId": "lost",
            "curPrice": 0,
            "cashPnl": -75,
            "realizedPnl": 5,
            "redeemable": False,
        },
        {
            "conditionId": "open",
            "curPrice": 0.4,
            "cashPnl": -10,
            "realizedPnl": 0,
            "redeemable": False,
        },
    ]
    settled = settled_unredeemed_positions(rows)
    assert len(settled) == 1
    assert settled[0]["conditionId"] == "lost"
    assert settled[0]["realizedPnl"] == -70


def test_registered_labels_override_holder_aliases_and_nfl_wallets_are_benchmarked(
    tmp_path,
):
    registry_path = tmp_path / "wallets.json"
    registry_path.write_text(
        """[
          {"address": "0xknown", "label": "Known", "top_category": "MLB", "registry_status": "LIVE"},
          {"address": "0xnfl", "label": "NFL Benchmark", "top_categories": ["NFL"], "registry_status": "SHADOW"}
        ]""",
        encoding="utf-8",
    )
    registry = load_wallet_registry(registry_path)
    merged = merge_candidates(
        {
            "0xknown": {
                "address": "0xknown",
                "label": "ugly-holder-alias",
                "active_nfl_balance": 10,
                "active_conditions": set(),
                "active_events": set(),
                "discovery_sources": {"holders"},
            }
        },
        {},
        registry,
    )
    by_address = {row["address"]: row for row in merged}
    assert by_address["0xknown"]["label"] == "Known"
    assert by_address["0xknown"]["already_registered"] is True
    assert by_address["0xnfl"]["label"] == "NFL Benchmark"
    assert "registry_nfl_benchmark" in by_address["0xnfl"]["discovery_sources"]
