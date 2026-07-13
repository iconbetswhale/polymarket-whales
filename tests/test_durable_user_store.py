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
