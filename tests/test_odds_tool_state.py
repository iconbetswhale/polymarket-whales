from datetime import datetime, timezone

from database import TrackerDatabase
from sharp_money_live import SharpMoneyCollector


def test_odds_tool_snapshot_is_durable_and_reports_age(tmp_path) -> None:
    path = tmp_path / "odds-state.db"
    first = TrackerDatabase(path)
    first.save_odds_tool_snapshot(
        "positive-ev:key",
        "positive-ev",
        {"data": [{"id": "ev-1"}], "generatedAt": "2026-08-31T12:00:00+00:00"},
        ttl_seconds=900,
        source_updated_at="2026-08-31T12:00:00+00:00",
    )

    second = TrackerDatabase(path)
    snapshot = second.get_odds_tool_snapshot("positive-ev:key", max_age_seconds=900)

    assert snapshot is not None
    assert snapshot["payload"]["data"] == [{"id": "ev-1"}]
    assert snapshot["sourceUpdatedAt"] == "2026-08-31T12:00:00+00:00"
    assert snapshot["ageSeconds"] >= 0


def test_provider_health_upsert_keeps_latest_verified_counts(tmp_path) -> None:
    db = TrackerDatabase(tmp_path / "health.db")
    now = datetime.now(timezone.utc).isoformat()
    db.record_odds_provider_health(
        "odds_engine",
        {
            "status": "ok",
            "transport": "rest",
            "observedAt": now,
            "lastSuccessAt": now,
            "latencyMs": 145.2,
            "quoteCount": 120,
            "executableQuoteCount": 108,
            "staleQuoteCount": 4,
            "missingTimestampCount": 0,
            "details": {"revision": "test"},
        },
    )

    row = db.get_odds_provider_health()[0]
    assert row["provider_key"] == "odds_engine"
    assert row["quote_count"] == 120
    assert row["executable_quote_count"] == 108
    assert row["missing_timestamp_count"] == 0
    assert row["details"] == {"revision": "test"}


def test_sharp_money_collector_state_survives_a_cold_process() -> None:
    first = SharpMoneyCollector(None, local_control=True)
    first._previous = {"market": {"liquidity": 250}}
    first._history["market"].append({"observedAt": "2026-08-31T12:00:00Z"})
    first._signals = [{"id": "signal-1", "depthAvailable": True}]
    first._cycles = 4

    second = SharpMoneyCollector(None, local_control=True)
    assert second.restore_state(first.state_snapshot()) is True
    restored = second.state_snapshot()

    assert restored["previous"] == {"market": {"liquidity": 250}}
    assert restored["history"]["market"] == [
        {"observedAt": "2026-08-31T12:00:00Z"}
    ]
    assert restored["signals"][0]["id"] == "signal-1"
    assert restored["cycles"] == 4
