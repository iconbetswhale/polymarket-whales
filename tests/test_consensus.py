from position_tracker import TrackerService


def test_consensus_grouping(temp_settings, db, sample_wallet_file):
    positions = [
        {
            "wallet_address": "0x1",
            "wallet_label": "A",
            "condition_id": "0xabc",
            "outcome": "Yes",
            "category": "Soccer",
            "league": "Soccer",
            "market_title": "France vs Spain",
            "position_size_usd": 100,
            "current_value": 120,
            "average_entry_price": 0.5,
            "current_price": 0.6,
            "market_url": "https://polymarket.com/event/test",
            "first_detected_at": "2026-01-01T00:00:00+00:00",
            "position_key": "0xabc::Yes",
        },
        {
            "wallet_address": "0x2",
            "wallet_label": "B",
            "condition_id": "0xabc",
            "outcome": "Yes",
            "category": "Soccer",
            "league": "Soccer",
            "market_title": "France vs Spain",
            "position_size_usd": 200,
            "current_value": 210,
            "average_entry_price": 0.55,
            "current_price": 0.61,
            "market_url": "https://polymarket.com/event/test",
            "first_detected_at": "2026-01-02T00:00:00+00:00",
            "position_key": "0xabc::Yes",
        },
    ]
    service = TrackerService(temp_settings, database=db, auto_start=False)
    consensus = service._build_consensus(positions, [], {"0x1": {"estimated_base_unit": 100}, "0x2": {"estimated_base_unit": 100}})
    assert consensus[0]["wallet_count"] == 2
    assert consensus[0]["combined_position_value"] == 330
