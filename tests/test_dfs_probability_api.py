from datetime import datetime, timezone


def test_dfs_probability_api_returns_market_hit_rate(app_client):
    timestamp = datetime.now(timezone.utc).isoformat()
    response = app_client.post(
        "/api/dfs/fair-probability",
        json={
            "target_line": 6.5,
            "side": "over",
            "devig_method": "multiplicative",
            "dfs_breakeven_odds": -119,
            "weights": {"fanduel": 60, "pinnacle": 40},
            "quotes": [
                {
                    "provider": "fanduel",
                    "line": 6.5,
                    "over_odds": -130,
                    "under_odds": 110,
                    "quote_timestamp": timestamp,
                },
                {
                    "provider": "pinnacle",
                    "line": 6.5,
                    "over_odds": -120,
                    "under_odds": 100,
                    "quote_timestamp": timestamp,
                },
            ],
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "AVAILABLE"
    assert payload["source_count"] == 2
    assert 50 < payload["hit_rate_percent"] < 100
    assert payload["edge_probability"] is not None


def test_dfs_probability_api_rejects_incomplete_contract(app_client):
    response = app_client.post(
        "/api/dfs/fair-probability",
        json={"target_line": 6.5, "side": "over", "weights": {"fanduel": 100}},
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "UNAVAILABLE"


def test_dfs_probability_api_rejects_unknown_devig_method(app_client):
    response = app_client.post(
        "/api/dfs/fair-probability",
        json={
            "target_line": 6.5,
            "side": "over",
            "weights": {"fanduel": 100},
            "quotes": [],
            "devig_method": "secret-sauce",
        },
    )
    assert response.status_code == 400
