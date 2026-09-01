from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from dfs_odds import build_dfs_odds_board


def _market(
    book_key: str,
    *,
    dfs: bool = False,
    line: float = 1.5,
    player: str = "Aaron Judge",
    over_price: int = -110,
    under_price: int = -110,
    sides: tuple[str, ...] = ("over", "under"),
    is_alt: bool = False,
    multiplier: float | str | None = None,
    liquidity: float | None = None,
    deep_link: str = "",
) -> dict:
    observed = datetime.now(timezone.utc).isoformat()
    return {
        "key": book_key,
        "title": book_key.title(),
        "last_update": observed,
        "markets": [
            {
                "key": "batter_hits",
                "last_update": observed,
                "outcomes": [
                    {
                        "name": side.title(),
                        "price": (
                            None
                            if dfs
                            else over_price if side == "over" else under_price
                        ),
                        "point": line,
                        "description": player,
                        "is_alt": is_alt,
                        **({"multiplier": multiplier} if multiplier is not None else {}),
                        **({"liquidity": liquidity} if liquidity is not None else {}),
                        **({"link": deep_link} if deep_link else {}),
                    }
                    for side in sides
                ],
            }
        ],
    }


def _events() -> list[dict]:
    return [
        {
            "id": "mlb-event-1",
            "sport_key": "baseball_mlb",
            "sport_title": "MLB",
            "commence_time": (
                datetime.now(timezone.utc) + timedelta(hours=4)
            ).isoformat(),
            "home_team": "Boston Red Sox",
            "away_team": "New York Yankees",
            "bookmakers": [
                _market("fanduel"),
                _market("prizepicks", dfs=True),
            ],
        }
    ]


def test_live_dfs_board_uses_exact_line_probability_engine() -> None:
    events = _events()
    events[0]["bookmakers"].append(_market("pinnacle"))
    rows = build_dfs_odds_board(events)
    expected_event_date = (
        datetime.fromisoformat(events[0]["commence_time"])
        .astimezone(ZoneInfo("America/New_York"))
        .date()
        .isoformat()
    )

    assert len(rows) == 2
    assert {row["side"] for row in rows} == {"Over", "Under"}
    assert all(row["dfsLines"] == {"prizepicks": 1.5} for row in rows)
    assert all(row["hitByLine"]["1.5"] == 50.0 for row in rows)
    assert all(row["fairOddsByLine"]["1.5"] == -100.0 for row in rows)
    assert {row["oddsByBook"]["fanduel"]["odds"] for row in rows} == {"-110"}
    assert all(row["minimumSourcesByLine"]["1.5"] == 2 for row in rows)
    assert {row["awayTeam"] for row in rows} == {"New York Yankees"}
    assert {row["homeTeam"] for row in rows} == {"Boston Red Sox"}
    assert all(
        row["devigSourcesByLine"]["1.5"]["fanduel"][0] == 0.5
        and row["devigSourcesByLine"]["1.5"]["fanduel"][1]
        == pytest.approx(1, abs=0.001)
        for row in rows
    )
    assert {row["eventDate"] for row in rows} == {expected_event_date}


def test_live_dfs_board_exposes_zero_weight_sources_for_instant_reweighting() -> None:
    events = _events()
    events[0]["bookmakers"].append(_market("pinnacle"))

    rows = build_dfs_odds_board(events, weights={"fanduel": 100, "pinnacle": 0})

    assert all(
        set(row["devigSourcesByLine"]["1.5"]) == {"fanduel", "pinnacle"}
        for row in rows
    )


def test_live_dfs_board_keeps_pairs_together_and_formats_exchange_cents() -> None:
    events = _events()
    events[0]["bookmakers"].extend(
        [_market("pinnacle"), _market("polymarket")]
    )

    rows = build_dfs_odds_board(events)

    assert [row["side"] for row in rows] == ["Over", "Under"]
    assert all(row["sourceCount"] == 3 for row in rows)
    assert all(row["availableQuoteCount"] == 3 for row in rows)
    assert {row["oddsByBook"]["polymarket"]["odds"] for row in rows} == {"52.4\u00a2"}


def test_live_dfs_board_sorts_highest_hit_rate_first() -> None:
    events = _events()
    events[0]["bookmakers"].append(_market("pinnacle"))
    sportsbook_outcomes = events[0]["bookmakers"][0]["markets"][0]["outcomes"]
    sportsbook_outcomes[0]["price"] = -150
    sportsbook_outcomes[1]["price"] = 120

    rows = build_dfs_odds_board(events)

    hit_rates = [row["hit"] for row in rows if row["hit"] is not None]
    assert hit_rates == sorted(hit_rates, reverse=True)
    assert rows[0]["side"] == "Over"


def test_live_dfs_board_applies_the_selected_custom_book_weights() -> None:
    events = _events()
    events[0]["bookmakers"][0] = _market(
        "fanduel", over_price=-200, under_price=150
    )
    events[0]["bookmakers"].append(
        _market("pinnacle", over_price=150, under_price=-200)
    )

    fanduel_rows = build_dfs_odds_board(
        events, weights={"fanduel": 99, "pinnacle": 1}
    )
    pinnacle_rows = build_dfs_odds_board(
        events, weights={"fanduel": 1, "pinnacle": 99}
    )
    fanduel_over = next(row for row in fanduel_rows if row["side"] == "Over")
    pinnacle_over = next(row for row in pinnacle_rows if row["side"] == "Over")

    assert fanduel_over["hitByLine"]["1.5"] > 50
    assert pinnacle_over["hitByLine"]["1.5"] < 50
    assert fanduel_over["hitByLine"]["1.5"] > pinnacle_over["hitByLine"]["1.5"]


def test_live_dfs_board_only_returns_props_available_on_selected_app() -> None:
    events = _events()
    events[0]["bookmakers"].extend(
        [
            _market("fanduel", player="Juan Soto"),
            _market("underdog", dfs=True, line=2.5, player="Juan Soto"),
        ]
    )

    prizepicks_rows = build_dfs_odds_board(
        events,
        selected_dfs_book="prizepicks",
    )
    underdog_rows = build_dfs_odds_board(
        events,
        selected_dfs_book="underdog",
    )

    assert {row["player"] for row in prizepicks_rows} == {"Aaron Judge"}
    assert {row["player"] for row in underdog_rows} == {"Juan Soto"}
    assert all(row["line"] == 2.5 for row in underdog_rows)
    assert all("underdog" in row["dfsLines"] for row in underdog_rows)


def test_live_dfs_board_strictly_isolates_every_optimizer_app() -> None:
    events = _events()
    app_props = {
        "underdog": ("underdog", "Juan Soto", 2.5),
        "dk-pick6": ("pick6", "Mookie Betts", 3.5),
        "betr": ("betr_picks", "Shohei Ohtani", 4.5),
        "dabble": ("dabble", "Vladimir Guerrero Jr.", 5.5),
    }
    for provider_key, player, line in app_props.values():
        events[0]["bookmakers"].extend(
            [
                _market("fanduel", player=player, line=line),
                _market(provider_key, dfs=True, player=player, line=line),
            ]
        )

    expected_players = {
        "prizepicks": "Aaron Judge",
        **{ui_key: values[1] for ui_key, values in app_props.items()},
    }
    for ui_key, expected_player in expected_players.items():
        rows = build_dfs_odds_board(events, selected_dfs_book=ui_key)

        assert {row["player"] for row in rows} == {expected_player}
        assert {row["side"] for row in rows} == {"Over", "Under"}
        assert all(ui_key in row["dfsLines"] for row in rows)


@pytest.mark.parametrize(
    ("provider_key", "ui_key"),
    (
        ("underdog", "underdog"),
        ("pick6", "dk-pick6"),
        ("betr_picks", "betr"),
        ("dabble", "dabble"),
    ),
)
def test_live_dfs_board_rejects_incomplete_app_props(
    provider_key: str,
    ui_key: str,
) -> None:
    events = _events()
    events[0]["bookmakers"].extend(
        [
            _market("fanduel", player="Verified App Prop", line=2.5),
            _market(
                provider_key,
                dfs=True,
                player="Verified App Prop",
                line=2.5,
            ),
        ]
    )
    incomplete = _market(
        provider_key,
        dfs=True,
        player="Phantom Home Run",
        sides=("over",),
    )
    incomplete["markets"][0]["key"] = "batter_home_runs"
    events[0]["bookmakers"].append(incomplete)

    selected_rows = build_dfs_odds_board(events, selected_dfs_book=ui_key)
    prizepicks_rows = build_dfs_odds_board(
        events, selected_dfs_book="prizepicks"
    )

    assert {row["player"] for row in selected_rows} == {"Verified App Prop"}
    assert {row["side"] for row in selected_rows} == {"Over", "Under"}
    assert {row["player"] for row in prizepicks_rows} == {"Aaron Judge"}
    assert all(ui_key not in row["dfsLines"] for row in prizepicks_rows)


@pytest.mark.parametrize(
    ("provider_key", "ui_key"),
    (
        ("prizepicks", "prizepicks"),
        ("pick6", "dk-pick6"),
    ),
)
def test_live_dfs_board_keeps_verified_one_sided_provider_slates(
    provider_key: str,
    ui_key: str,
) -> None:
    events = _events()
    events[0]["bookmakers"] = [
        _market("fanduel"),
        _market(provider_key, dfs=True, sides=("over",)),
    ]

    rows = build_dfs_odds_board(events, selected_dfs_book=ui_key)

    assert {row["player"] for row in rows} == {"Aaron Judge"}
    assert {row["side"] for row in rows} == {"Over"}


def test_live_dfs_board_prefers_the_app_headline_line_over_alternates() -> None:
    events = _events()
    events[0]["bookmakers"].extend(
        [
            _market("underdog", dfs=True, line=2.5, is_alt=True),
            _market("underdog", dfs=True, line=1.5),
        ]
    )

    rows = build_dfs_odds_board(events, selected_dfs_book="underdog")

    assert rows
    assert all(row["line"] == 1.5 for row in rows)


@pytest.mark.parametrize(
    ("provider_key", "ui_key"),
    (("underdog", "underdog"), ("pick6", "dk-pick6")),
)
def test_live_dfs_board_rejects_nonstandard_multiplier_props(
    provider_key: str,
    ui_key: str,
) -> None:
    events = _events()
    events[0]["bookmakers"] = [
        _market("fanduel"),
        _market(provider_key, dfs=True, is_alt=True, multiplier="0.7x"),
    ]

    assert build_dfs_odds_board(events, selected_dfs_book=ui_key) == []


def test_live_dfs_board_exposes_exchange_liquidity_links_and_quality_flags() -> None:
    events = _events()
    events[0]["bookmakers"].extend(
        [
            _market("draftkings"),
            _market(
                "novig",
                over_price=-9900,
                under_price=-110,
                liquidity=9,
                deep_link="https://example.test/novig-bet",
            ),
        ]
    )

    rows = build_dfs_odds_board(events)
    novig = rows[0]["oddsByBook"]["novig"]

    assert novig["liquidity"] == 9
    assert novig["deepLink"] == "https://example.test/novig-bet"
    assert novig["modelExcluded"] is True
    assert novig["modelExclusionReason"] == "EXCESSIVE_TWO_WAY_OVERROUND"
    assert "novig" not in rows[0]["devigSourcesByLine"]["1.5"]


def test_live_dfs_board_models_one_exact_two_way_source_but_not_mismatched_lines() -> None:
    events = _events()
    events[0]["bookmakers"] = [
        _market("prizepicks", dfs=True, line=0.5),
        _market("prophetexchange", line=0.5, over_price=-138, under_price=-104),
        _market("fanduel", line=1.5, over_price=130, under_price=None, sides=("over",)),
        _market("draftkings", line=1.5, over_price=168, under_price=None, sides=("over",)),
    ]

    rows = build_dfs_odds_board(events)
    over = next(row for row in rows if row["side"] == "Over")

    assert over["hitByLine"]["0.5"] is None
    assert over["fairOddsByLine"]["0.5"] is None
    assert over["minimumSourcesByLine"]["0.5"] == 2
    assert over["sourceCount"] == 1
    assert over["modelStatus"] == "WATCH_ONLY"
    assert over["oddsByBook"]["fanduel"]["line"] == 1.5
    assert over["oddsByBook"]["fanduel"]["modelExclusionReason"] == "LINE_MISMATCH"


def test_live_dfs_board_rejects_unknown_selected_app() -> None:
    try:
        build_dfs_odds_board(_events(), selected_dfs_book="not-a-dfs-app")
    except ValueError as exc:
        assert "supported DFS book" in str(exc)
    else:
        raise AssertionError("unknown DFS apps must be rejected")


def test_live_dfs_endpoint_prefers_odds_engine(app_client, monkeypatch) -> None:
    application = app_client.application
    registry = application.extensions["execution_providers"]
    provider = next(
        item for item in registry.providers if item.provider_key == "odds_engine"
    )
    provider.api_key = "configured-in-test"
    monkeypatch.setattr(provider, "ev_events", lambda **_kwargs: _events())

    response = app_client.post(
        "/api/dfs/lines",
        json={"weights": {"fanduel": 100}},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["dataSource"] == "odds_engine"
    assert payload["selectedBook"] == "prizepicks"
    assert payload["total"] == 2
    assert payload["data"][0]["hitByLine"]["1.5"] is None
    assert payload["data"][0]["modelStatus"] == "WATCH_ONLY"
    assert set(payload["dataByBook"]) == {"prizepicks"}
    assert payload["dataByBook"]["prizepicks"] == payload["data"]
    assert payload["totalsByBook"] == {"prizepicks": 2}


def test_live_dfs_get_is_cacheable_and_accepts_weight_query(
    app_client, monkeypatch
) -> None:
    application = app_client.application
    registry = application.extensions["execution_providers"]
    provider = next(
        item for item in registry.providers if item.provider_key == "odds_engine"
    )
    provider.api_key = "configured-in-test"
    monkeypatch.setattr(provider, "ev_events", lambda **_kwargs: _events())

    response = app_client.get(
        "/api/dfs/lines",
        query_string={"weights": '{"fanduel":100}'},
    )

    assert response.status_code == 200
    assert response.get_json()["refreshSeconds"] == 60
    assert "s-maxage=60" in response.headers["Cache-Control"]
    assert not response.headers.getlist("Set-Cookie")


def test_live_dfs_endpoint_reuses_last_verified_board_during_provider_failure(
    app_client, monkeypatch
) -> None:
    application = app_client.application
    registry = application.extensions["execution_providers"]
    provider = next(
        item for item in registry.providers if item.provider_key == "odds_engine"
    )
    provider.api_key = "configured-in-test"
    calls = 0

    def ev_events(**_kwargs):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise ValueError("upstream unavailable")
        return _events()

    monkeypatch.setattr(provider, "ev_events", ev_events)

    live = app_client.get(
        "/api/dfs/lines",
        query_string={"weights": '{"fanduel":100}'},
    )
    degraded = app_client.get(
        "/api/dfs/lines",
        query_string={"weights": '{"fanduel":100}'},
    )
    payload = degraded.get_json()

    assert live.status_code == 200
    assert live.get_json()["degraded"] is False
    assert degraded.status_code == 200
    assert payload["degraded"] is True
    assert payload["stale"] is True
    assert payload["upstreamStatus"] == "PROVIDER_ERROR"
    assert payload["data"] == live.get_json()["data"]
    assert payload["message"] == (
        "Recent verified props shown while the live feed reconnects."
    )


def test_live_dfs_endpoint_scopes_results_to_requested_app(
    app_client, monkeypatch
) -> None:
    application = app_client.application
    registry = application.extensions["execution_providers"]
    provider = next(
        item for item in registry.providers if item.provider_key == "odds_engine"
    )
    provider.api_key = "configured-in-test"
    events = _events()
    events[0]["bookmakers"].extend(
        [
            _market("fanduel", player="Juan Soto"),
            _market("underdog", dfs=True, line=2.5, player="Juan Soto"),
        ]
    )
    monkeypatch.setattr(provider, "ev_events", lambda **_kwargs: events)

    response = app_client.get(
        "/api/dfs/lines",
        query_string={"book": "underdog"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["selectedBook"] == "underdog"
    assert {row["player"] for row in payload["data"]} == {"Juan Soto"}
    assert all(row["line"] == 2.5 for row in payload["data"])
    assert set(payload["dataByBook"]) == {"underdog"}
    for book_key, book_rows in payload["dataByBook"].items():
        assert all(book_key in row["dfsLines"] for row in book_rows)


def test_live_dfs_endpoint_can_warm_every_app_board_in_one_request(
    app_client, monkeypatch
) -> None:
    application = app_client.application
    registry = application.extensions["execution_providers"]
    provider = next(
        item for item in registry.providers if item.provider_key == "odds_engine"
    )
    provider.api_key = "configured-in-test"
    events = _events()
    app_props = {
        "underdog": ("underdog", "Juan Soto", 2.5),
        "dk-pick6": ("pick6", "Mookie Betts", 3.5),
        "betr": ("betr_picks", "Shohei Ohtani", 4.5),
        "dabble": ("dabble", "Vladimir Guerrero Jr.", 5.5),
    }
    for provider_key, player, line in app_props.values():
        events[0]["bookmakers"].extend(
            [
                _market("fanduel", player=player, line=line),
                _market(provider_key, dfs=True, player=player, line=line),
            ]
        )
    monkeypatch.setattr(provider, "ev_events", lambda **_kwargs: events)

    response = app_client.get("/api/dfs/lines?book=all")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["selectedBook"] == "all"
    assert set(payload["dataByBook"]) == {
        "prizepicks", "underdog", "dk-pick6", "betr", "dabble"
    }
    assert {row["player"] for row in payload["dataByBook"]["prizepicks"]} == {
        "Aaron Judge"
    }
    for ui_key, (_, player, _) in app_props.items():
        assert {row["player"] for row in payload["dataByBook"][ui_key]} == {
            player
        }


def test_live_dfs_endpoint_rejects_unknown_app(app_client) -> None:
    response = app_client.get("/api/dfs/lines?book=not-a-dfs-app")

    assert response.status_code == 400
    assert response.get_json()["error"] == "book must be a supported DFS app"


def test_live_dfs_endpoint_rejects_partial_custom_weight_allocation(app_client) -> None:
    response = app_client.get(
        "/api/dfs/lines",
        query_string={"weights": '{"fanduel":60,"pinnacle":20}'},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "weights must total exactly 100 percent"
