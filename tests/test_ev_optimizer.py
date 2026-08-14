from ev_optimizer import build_ev_board, build_ev_candidates
from database import TrackerDatabase


def _event():
    return {
        "id": "game-1",
        "sport_key": "baseball_mlb",
        "sport_title": "MLB",
        "commence_time": "2099-07-29T23:10:00Z",
        "away_team": "New York Mets",
        "home_team": "Philadelphia Phillies",
        "bookmakers": [
            {
                "key": "pinnacle",
                "title": "Pinnacle",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "New York Mets", "price": 120},
                            {"name": "Philadelphia Phillies", "price": -130},
                        ],
                    }
                ],
            },
            {
                "key": "novig",
                "title": "NoVIG",
                "link": "https://example.test/game-1",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "New York Mets", "price": 135, "bet_limit": 500},
                            {"name": "Philadelphia Phillies", "price": -125},
                        ],
                    }
                ],
            },
        ],
    }


def test_build_ev_candidates_is_sorted_and_uses_best_execution():
    rows = build_ev_candidates(
        [_event()],
        source_weights={"pinnacle": 100},
        execution_books=("novig",),
        min_ev=-100,
        min_source_books=1,
    )
    assert len(rows) == 2
    assert rows == sorted(rows, key=lambda row: row["evPercent"], reverse=True)
    mets = next(row for row in rows if row["selection"] == "New York Mets")
    assert mets["bestQuote"]["bookKey"] == "novig"
    assert mets["bestQuote"]["americanOdds"] == 135
    assert mets["sourceBooks"] == [
        {
            "bookKey": "pinnacle",
            "weight": 100.0,
            "fairProbability": mets["sourceBooks"][0]["fairProbability"],
        }
    ]


def test_missing_weighted_books_are_not_fabricated():
    rows = build_ev_candidates(
        [_event()],
        source_weights={"pinnacle": 40, "kalshi": 60},
        execution_books=("novig",),
        min_ev=-100,
        min_source_books=1,
    )
    assert rows
    assert all(
        [source["bookKey"] for source in row["sourceBooks"]] == ["pinnacle"]
        for row in rows
    )
    assert all(row["sourceCoverage"] == 40 for row in rows)


def test_invalid_extreme_quote_is_rejected_before_ev_calculation():
    event = _event()
    event["bookmakers"][1]["markets"][0]["outcomes"][0]["price"] = 99900
    board = build_ev_board(
        [event],
        source_weights={"pinnacle": 100},
        execution_books=("novig",),
        min_source_books=1,
    )
    assert board["data"] == []
    assert board["diagnostics"]["rejectionReasons"]["invalid_odds"] == 1


def test_started_events_are_never_presented_as_prematch_ev():
    event = _event()
    event["commence_time"] = "2020-01-01T00:00:00Z"
    board = build_ev_board(
        [event],
        source_weights={"pinnacle": 100},
        execution_books=("novig",),
        min_source_books=1,
    )
    assert board["data"] == []
    assert board["diagnostics"]["rejectionReasons"]["event_already_started"] == 1


def test_execution_book_is_left_out_of_its_own_fair_price():
    event = _event()
    for key, away_price, home_price in (
        ("betonlineag", 122, -132),
        ("fanduel", 118, -128),
        ("draftkings", 121, -131),
    ):
        event["bookmakers"].append(
            {
                "key": key,
                "title": key,
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "New York Mets", "price": away_price},
                            {"name": "Philadelphia Phillies", "price": home_price},
                        ],
                    }
                ],
            }
        )
    rows = build_ev_candidates(
        [event],
        source_weights={
            "pinnacle": 40,
            "betonlineag": 20,
            "fanduel": 10,
            "draftkings": 10,
            "novig": 1000,
        },
        execution_books=("novig",),
        min_ev=-100,
        min_source_books=3,
    )
    assert rows
    assert all("novig" not in {book["bookKey"] for book in row["sourceBooks"]} for row in rows)


def test_reported_liquidity_caps_recommended_stake():
    rows = build_ev_candidates(
        [_event()],
        source_weights={"pinnacle": 100},
        execution_books=("novig",),
        min_ev=-100,
        min_source_books=1,
        bankroll=1_000_000,
        max_stake_pct=1,
    )
    mets = next(row for row in rows if row["selection"] == "New York Mets")
    assert mets["recommendedStake"] <= 500


def test_top_price_drives_display_and_ev_while_depth_stays_diagnostic():
    event = _event()
    quote = event["bookmakers"][1]["markets"][0]["outcomes"][0]
    quote.update({
        "price": 138,
        "liquidity": 75,
        "bet_limit": 5000,
        "depth_vwap_price": 0.42735,
        "depth_executable_amount": 5000,
        "depth_levels_used": 3,
    })
    rows = build_ev_candidates(
        [event], source_weights={"pinnacle": 100}, execution_books=("novig",),
        min_ev=-100, min_source_books=1, bankroll=1_000_000, max_stake_pct=1,
    )
    mets = next(row for row in rows if row["selection"] == "New York Mets")
    best = mets["bestQuote"]
    assert best["americanOdds"] == best["topPriceAmericanOdds"] == 138
    assert best["topPriceLiquidity"] == 75
    assert best["marketLimit"] == 5000
    assert best["depthVwapPrice"] == 0.42735
    assert best["depthExecutableAmount"] == 5000
    assert best["depthLevelsUsed"] == 3
    assert best["effectiveDecimal"] == 2.38
    assert mets["evPercent"] == round((mets["fairProbability"] * 2.38 - 1) * 100, 2)
    assert mets["recommendedStake"] <= 75


def test_optimizer_snapshots_are_material_change_deduplicated(tmp_path):
    database = TrackerDatabase(tmp_path / "ev.db")
    rows = build_ev_candidates(
        [_event()],
        source_weights={"pinnacle": 100},
        execution_books=("novig",),
        min_ev=-100,
        min_source_books=1,
    )
    first = database.record_ev_board("user-1", rows)
    second = database.record_ev_board("user-1", rows)
    history = database.get_ev_optimizer_history("user-1")
    assert first["material_snapshots"] == len(rows)
    assert second["material_snapshots"] == 0
    assert history["summary"]["opportunities"] == len(rows)
