from __future__ import annotations

from datetime import datetime, timedelta, timezone

from dfs_odds import build_dfs_odds_board


def _market(book_key: str, *, dfs: bool = False) -> dict:
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
                        "name": "Over",
                        "price": None if dfs else -110,
                        "point": 1.5,
                        "description": "Aaron Judge",
                    },
                    {
                        "name": "Under",
                        "price": None if dfs else -110,
                        "point": 1.5,
                        "description": "Aaron Judge",
                    },
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
    rows = build_dfs_odds_board(_events())

    assert len(rows) == 2
    assert {row["side"] for row in rows} == {"Over", "Under"}
    assert all(row["dfsLines"] == {"prizepicks": 1.5} for row in rows)
    assert all(row["hitByLine"]["1.5"] == 50.0 for row in rows)
    assert all(row["fairOddsByLine"]["1.5"] == -100.0 for row in rows)
    assert {row["oddsByBook"]["fanduel"] for row in rows} == {"-110"}


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
    assert payload["total"] == 2
    assert payload["data"][0]["hitByLine"]["1.5"] == 50.0


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
