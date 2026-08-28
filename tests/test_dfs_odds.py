from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from dfs_odds import DFS_OPTIMIZER_BOOK_KEYS, build_dfs_odds_board


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
    assert {row["oddsByBook"]["fanduel"] for row in rows} == {"-110"}
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
    assert {row["oddsByBook"]["polymarket"] for row in rows} == {"52.4\u00a2"}


def test_live_dfs_board_sorts_highest_hit_rate_first() -> None:
    events = _events()
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

    fanduel_rows = build_dfs_odds_board(events, weights={"fanduel": 100})
    pinnacle_rows = build_dfs_odds_board(events, weights={"pinnacle": 100})
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

    assert selected_rows == []
    assert {row["player"] for row in prizepicks_rows} == {"Aaron Judge"}
    assert all(ui_key not in row["dfsLines"] for row in prizepicks_rows)


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
    assert payload["data"][0]["hitByLine"]["1.5"] == 50.0
    assert set(payload["dataByBook"]) == set(DFS_OPTIMIZER_BOOK_KEYS)
    assert payload["dataByBook"]["prizepicks"] == payload["data"]
    assert payload["totalsByBook"] == {
        "prizepicks": 2,
        "underdog": 0,
        "dk-pick6": 0,
        "betr": 0,
        "dabble": 0,
    }


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
    assert response.get_json()["refreshSeconds"] == 15
    assert "s-maxage=15" in response.headers["Cache-Control"]
    assert not response.headers.getlist("Set-Cookie")


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
    assert {row["player"] for row in payload["dataByBook"]["prizepicks"]} == {
        "Aaron Judge"
    }
    for book_key, book_rows in payload["dataByBook"].items():
        assert all(book_key in row["dfsLines"] for row in book_rows)


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
