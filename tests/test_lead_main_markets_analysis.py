from scripts.simulate_lead_cohorts_main_markets import (
    build_main_market_map,
    classify_market,
    position_cost,
    reconcile_positions,
)


def test_position_cost_uses_initial_value_then_share_cost_fallback():
    assert position_cost({"initialValue": 125, "totalBought": 999, "avgPrice": 0.5}) == 125
    assert position_cost({"totalBought": 100, "avgPrice": 0.42}) == 42


def test_reconciliation_preserves_settled_current_loss_missing_from_closed():
    closed = [
        {
            "asset": "winner",
            "eventSlug": "mlb-a-b-2026-07-01",
            "redeemable": True,
            "curPrice": 1,
        }
    ]
    current = [
        {
            "asset": "loss",
            "eventSlug": "mlb-c-d-2026-07-02",
            "redeemable": True,
            "curPrice": 0,
        }
    ]

    rows, audit = reconcile_positions(closed, current)

    assert {row["asset"] for row in rows} == {"winner", "loss"}
    assert audit["settled_current_rows_added"] == 1


def test_main_market_map_selects_full_game_run_line_and_highest_volume_total():
    event_slug = "mlb-a-b-2026-07-01"
    mapping = build_main_market_map(
        {
            event_slug: {
                "markets": [
                    {
                        "slug": f"{event_slug}-spread-away-1pt5",
                        "sportsMarketType": "spreads",
                        "line": 1.5,
                        "volume": 100,
                    },
                    {
                        "slug": f"{event_slug}-f5-spread-away-1pt5",
                        "sportsMarketType": "spreads",
                        "line": 1.5,
                        "volume": 500,
                    },
                    {
                        "slug": f"{event_slug}-total-8pt5",
                        "sportsMarketType": "totals",
                        "line": 8.5,
                        "volume": 400,
                    },
                    {
                        "slug": f"{event_slug}-total-9pt5",
                        "sportsMarketType": "totals",
                        "line": 9.5,
                        "volume": 200,
                    },
                ]
            }
        }
    )

    assert mapping[event_slug]["spread"] == f"{event_slug}-spread-away-1pt5"
    assert mapping[event_slug]["total"] == f"{event_slug}-total-8pt5"


def test_market_classification_excludes_alternate_or_first_five_markets():
    event_slug = "mlb-a-b-2026-07-01"
    main_markets = {
        event_slug: {
            "moneyline": event_slug,
            "spread": f"{event_slug}-spread-away-1pt5",
            "total": f"{event_slug}-total-8pt5",
        }
    }

    assert (
        classify_market(
            {"eventSlug": event_slug, "slug": event_slug},
            main_markets,
        )
        == "moneyline"
    )
    assert (
        classify_market(
            {
                "eventSlug": event_slug,
                "slug": f"{event_slug}-spread-away-1pt5",
            },
            main_markets,
        )
        == "spread"
    )
    assert (
        classify_market(
            {"eventSlug": event_slug, "slug": f"{event_slug}-total-8pt5"},
            main_markets,
        )
        == "total"
    )
    assert (
        classify_market(
            {"eventSlug": event_slug, "slug": f"{event_slug}-f5-total-4pt5"},
            main_markets,
        )
        is None
    )
