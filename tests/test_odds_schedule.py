from datetime import datetime, timezone

from odds_schedule import PolymarketScheduleFeed


def test_mlb_schedule_uses_slug_date_and_normalizes_main_markets():
    events = [{
        "id": "event-1",
        "slug": "mlb-lad-nyy-2026-07-17",
        "title": "Los Angeles Dodgers vs. New York Yankees",
        "markets": [{
            "id": "market-1",
            "conditionId": "condition-1",
            "slug": "mlb-lad-nyy-2026-07-17",
            "question": "Los Angeles Dodgers vs. New York Yankees",
            "sportsMarketType": "moneyline",
            "outcomes": '["Los Angeles Dodgers", "New York Yankees"]',
            "outcomePrices": '["0.515", "0.485"]',
            "clobTokenIds": '["away-token", "home-token"]',
            "endDate": "2026-07-24T23:05:00Z",
            "active": True,
            "closed": False,
        }],
    }]

    rows = PolymarketScheduleFeed._normalize(events, datetime(2026, 7, 16, 16, tzinfo=timezone.utc))

    assert len(rows) == 2
    assert rows[0]["schedule_date_et"] == "2026-07-17"
    assert rows[0]["resolution_time"] == "2026-07-17T23:05:00Z"
    assert rows[0]["canonical_sport_id"] == "baseball"
    assert rows[0]["canonical_league_id"] == "mlb"
    assert rows[0]["sports_market_type"] == "moneyline"
    assert rows[0]["current_price"] == 0.515


def test_mlb_schedule_excludes_dates_outside_today_and_tomorrow():
    events = [{"slug": "mlb-lad-nyy-2026-07-18", "markets": []}]
    rows = PolymarketScheduleFeed._normalize(events, datetime(2026, 7, 16, 16, tzinfo=timezone.utc))
    assert rows == []
