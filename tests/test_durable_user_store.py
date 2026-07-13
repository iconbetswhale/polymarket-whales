from __future__ import annotations

from contextlib import contextmanager

from durable_user_store import PostgresUserStore


class FakeCursor:
    def __init__(self) -> None:
        self.batches = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def executemany(self, query, values) -> None:
        self.batches.append((query, values))


class FakeConnection:
    def __init__(self) -> None:
        self.queries = []
        self.fake_cursor = FakeCursor()

    def execute(self, query, values=()) -> None:
        self.queries.append((query, values))

    def cursor(self) -> FakeCursor:
        return self.fake_cursor


class ReturningResult:
    def __init__(self, row) -> None:
        self.row = row

    def fetchone(self):
        return self.row


class ReturningConnection(FakeConnection):
    def __init__(self, row) -> None:
        super().__init__()
        self.row = row

    def execute(self, query, values=()):
        self.queries.append((query, values))
        return ReturningResult(self.row)


def _store_with_connection(connection: FakeConnection) -> PostgresUserStore:
    store = object.__new__(PostgresUserStore)

    @contextmanager
    def open_connection():
        yield connection

    store.connection = open_connection
    return store


def test_postgres_rejection_replacement_handles_empty_batch():
    connection = FakeConnection()
    store = _store_with_connection(connection)

    store.replace_tracking_rejections("user-1", [])

    assert len(connection.queries) == 1
    assert connection.fake_cursor.batches == []


def test_postgres_rejection_replacement_uses_cursor_batch():
    connection = FakeConnection()
    store = _store_with_connection(connection)
    rejection = {
        "recommendation_idempotency_key": "event::market::::outcome::v2",
        "rejection_reason": "ZERO_KELLY",
        "last_evaluated_at": "2026-07-13T12:00:00+00:00",
    }

    store.replace_tracking_rejections("user-1", [rejection])

    assert len(connection.fake_cursor.batches) == 1
    assert connection.fake_cursor.batches[0][1][0][0] == "user-1"


def test_postgres_tracker_bankroll_update_preserves_trade_bankroll():
    connection = ReturningConnection(
        {
            "user_id": "user-1",
            "starting_bankroll": 10000,
            "tracker_bankroll": 25000,
            "unit_percentage": 0.01,
            "updated_at": "2026-07-13T12:00:00+00:00",
        }
    )
    store = _store_with_connection(connection)

    settings = store.update_tracker_bankroll("user-1", 25000)

    query, values = connection.queries[0]
    assert "SET tracker_bankroll = %s" in query
    assert values[0] == 25000
    assert settings["starting_bankroll"] == 10000
    assert settings["tracker_bankroll"] == 25000


def test_postgres_trade_bankroll_update_preserves_tracker_bankroll():
    connection = ReturningConnection(
        {
            "user_id": "user-1",
            "starting_bankroll": 15000,
            "tracker_bankroll": 25000,
            "unit_percentage": 0.01,
            "updated_at": "2026-07-13T12:00:00+00:00",
        }
    )
    store = _store_with_connection(connection)

    settings = store.update_user_settings("user-1", 15000, 0.01)

    query, _values = connection.queries[0]
    conflict_update = query.split("ON CONFLICT", 1)[1]
    assert "tracker_bankroll = EXCLUDED.tracker_bankroll" not in conflict_update
    assert settings["starting_bankroll"] == 15000
    assert settings["tracker_bankroll"] == 25000
