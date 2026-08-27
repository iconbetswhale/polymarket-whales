from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from execution_providers import (
    MatchConfidence,
    ProviderMarketIndex,
    _match_exact_trade,
    canonicalize_trade,
    probability_to_american,
)
from novig_feed_worker import NoVIGFeedWorker, websocket_smoke_test
from novig_provider import (
    NOVIG_CASH_QTY_PER_CONTRACT,
    NoVIGAuthClient,
    NoVIGError,
    NoVIGOrderBookState,
    NoVIGRestClient,
    NoVIGStateStore,
    _walk_depth,
    normalize_novig_snapshot,
)


class FakeResponse:
    def __init__(self, payload, status_code: int = 200, *, headers=None) -> None:
        self._payload = deepcopy(payload)
        self.status_code = status_code
        self.headers = dict(headers or {})

    def json(self):
        return deepcopy(self._payload)


class QueueSession:
    def __init__(self, *, tokens=None, responses=None, post_delay: float = 0.0) -> None:
        self.tokens = list(tokens or ["safe-token"])
        self.responses = list(responses or [])
        self.post_delay = post_delay
        self.post_calls = []
        self.request_calls = []
        self._lock = threading.Lock()

    def post(self, url, **kwargs):
        with self._lock:
            index = len(self.post_calls)
            self.post_calls.append((url, deepcopy(kwargs)))
        if self.post_delay:
            time.sleep(self.post_delay)
        token = self.tokens[min(index, len(self.tokens) - 1)]
        return FakeResponse({"access_token": token, "expires_in": 1800})

    def request(self, method, url, **kwargs):
        with self._lock:
            index = len(self.request_calls)
            self.request_calls.append((method, url, deepcopy(kwargs)))
        response = self.responses[min(index, len(self.responses) - 1)]
        return response


class FakeSocket:
    def __init__(self, messages) -> None:
        self.messages = [json.dumps(message) for message in messages]
        self.sent = []
        self.closed = False

    def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))

    def recv(self):
        if self.messages:
            return self.messages.pop(0)
        return ""

    def close(self) -> None:
        self.closed = True


class FakeWorkerRest:
    def __init__(self, market: dict) -> None:
        self.market = deepcopy(market)
        self.bootstrap_count = 0

    def list_open_markets(self):
        self.bootstrap_count += 1
        return [deepcopy(self.market)]

    def list_events(self):
        return [deepcopy(self.market["event"])]

    def get_markets_by_events(self, event_ids):
        assert list(event_ids) == ["event-1"]
        return [deepcopy(self.market)]

    def get_book(self, market_id):
        assert market_id == "market-1"
        return sample_book()


def sample_market(*, market_id: str = "market-1", market_type: str = "MONEY") -> dict:
    outcomes = [
        {"id": f"{market_id}-home", "index": 0, "description": "New York Yankees"},
        {"id": f"{market_id}-away", "index": 1, "description": "Boston Red Sox"},
    ]
    return {
        "id": market_id,
        "eventId": "event-1",
        "league": "MLB",
        "type": market_type,
        "status": "OPEN",
        "description": "New York Yankees vs Boston Red Sox",
        "outcomeIds": [row["id"] for row in outcomes],
        "outcomes": outcomes,
        "event": {
            "id": "event-1",
            "marketIds": [market_id],
            "league": "MLB",
            "status": "OPEN_PREGAME",
            "scheduledStart": "2026-07-14T23:00:00Z",
            "game": {
                "scheduledStart": "2026-07-14T23:00:00Z",
                "homeTeam": {
                    "name": "New York Yankees",
                    "shortName": "Yankees",
                    "symbol": "NYY",
                },
                "awayTeam": {
                    "name": "Boston Red Sox",
                    "shortName": "Red Sox",
                    "symbol": "BOS",
                },
            },
        },
    }


def sample_book(*, market_id: str = "market-1") -> dict:
    return {
        "marketId": market_id,
        "marketDescription": "New York Yankees vs Boston Red Sox",
        "outcomeLadders": [
            {
                "outcomeId": f"{market_id}-home",
                "bids": [
                    {
                        "id": f"{market_id}-home-order",
                        "price": 0.48,
                        "qty": 1000,
                        "originalQty": 1000,
                        "currency": "CASH",
                        "marketId": market_id,
                        "outcomeId": f"{market_id}-home",
                        "status": "OPEN",
                    }
                ],
            },
            {
                "outcomeId": f"{market_id}-away",
                "bids": [
                    {
                        "id": f"{market_id}-away-order",
                        "price": 0.49,
                        "qty": 500,
                        "originalQty": 500,
                        "currency": "CASH",
                        "marketId": market_id,
                        "outcomeId": f"{market_id}-away",
                        "status": "OPEN",
                    }
                ],
            },
        ],
    }


def sample_trade(**overrides) -> dict:
    payload = {
        "id": "trade-1",
        "event_title": "New York Yankees vs Boston Red Sox",
        "market_title": "Moneyline",
        "outcome": "New York Yankees",
        "sports_market_type": "moneyline",
        "event_date_et": "2026-07-14T19:00:00-04:00",
        "canonical_sport_id": "baseball",
        "canonical_league_id": "mlb",
    }
    payload.update(overrides)
    return payload


def test_token_is_cached_and_refreshes_before_expiration() -> None:
    clock = [100.0]
    session = QueueSession(tokens=["token-one", "token-two"])
    auth = NoVIGAuthClient(
        "client-id",
        "client-secret",
        session=session,
        monotonic=lambda: clock[0],
    )

    assert auth.get_token() == "token-one"
    assert auth.get_token() == "token-one"
    assert len(session.post_calls) == 1

    clock[0] += 1741
    assert auth.get_token() == "token-two"
    assert len(session.post_calls) == 2


def test_token_refresh_is_single_flight() -> None:
    session = QueueSession(tokens=["shared-token"], post_delay=0.03)
    auth = NoVIGAuthClient("client-id", "client-secret", session=session)

    with ThreadPoolExecutor(max_workers=8) as executor:
        tokens = list(executor.map(lambda _: auth.get_token(), range(8)))

    assert tokens == ["shared-token"] * 8
    assert len(session.post_calls) == 1


def test_rest_reauthenticates_once_after_401() -> None:
    session = QueueSession(
        tokens=["token-one", "token-two"],
        responses=[
            FakeResponse({"error": "expired"}, 401),
            FakeResponse([sample_market()]),
        ],
    )
    auth = NoVIGAuthClient("client-id", "client-secret", session=session)
    rest = NoVIGRestClient(auth, session=session)

    markets = rest.list_open_markets()

    assert len(markets) == 1
    assert len(session.post_calls) == 2
    assert rest.reauthentication_count == 1
    assert session.request_calls[0][2]["headers"]["Authorization"] == "Bearer token-one"
    assert session.request_calls[1][2]["headers"]["Authorization"] == "Bearer token-two"


def test_rate_limit_retry_after_is_interpreted_as_milliseconds() -> None:
    sleeps = []
    session = QueueSession(
        responses=[
            FakeResponse({}, 429, headers={"Retry-After": "250"}),
            FakeResponse([sample_market()]),
        ]
    )
    auth = NoVIGAuthClient("client-id", "client-secret", session=session)
    rest = NoVIGRestClient(auth, session=session, sleep=sleeps.append)

    assert len(rest.list_open_markets()) == 1
    assert sleeps == [pytest.approx(0.25)]
    assert rest.rate_limit_count == 1


def test_rest_snapshot_constructs_bid_ask_depth_and_verified_quantity_scale() -> None:
    engine = NoVIGOrderBookState()
    engine.bootstrap_market(sample_market(), book=sample_book())

    snapshot = engine.snapshot("market-1")
    home = snapshot["outcomes"][0]

    assert snapshot["qtyPerContract"] == NOVIG_CASH_QTY_PER_CONTRACT == 100.0
    assert home["bestBid"] == pytest.approx(0.48)
    assert home["bestAsk"] == pytest.approx(0.51)
    assert home["spread"] == pytest.approx(0.03)
    assert home["bids"][0]["contracts"] == pytest.approx(10)
    assert home["bids"][0]["liquidityDollars"] == pytest.approx(4.8)
    assert home["asks"][0]["contracts"] == pytest.approx(5)
    assert home["asks"][0]["liquidityDollars"] == pytest.approx(2.55)


def test_place_partial_fill_cancel_and_last_trade_are_deterministic() -> None:
    engine = NoVIGOrderBookState()
    engine.bootstrap_market(sample_market(), book=sample_book())
    partial = {
        "type": "PLACE",
        "market": {"id": "market-1", "eventId": "event-1"},
        "order": {
            "id": "market-1-away-order",
            "marketId": "market-1",
            "outcomeId": "market-1-away",
            "price": 0.49,
            "qty": 200,
            "originalQty": 500,
            "currency": "CASH",
            "status": "OPEN",
        },
        "fills": [{"outcomeId": "market-1-home", "price": 0.51}],
    }

    assert engine.apply_message(partial) == {"market-1"}
    home = engine.snapshot("market-1")["outcomes"][0]
    assert home["asks"][0]["contracts"] == pytest.approx(2)
    assert home["lastTradedPrice"] == pytest.approx(0.51)

    cancel = {
        "type": "CANCEL",
        "order": {
            "id": "market-1-away-order",
            "marketId": "market-1",
            "outcomeId": "market-1-away",
        },
    }
    assert engine.apply_message(cancel) == {"market-1"}
    assert engine.snapshot("market-1")["outcomes"][0]["asks"] == []
    assert engine.apply_message(cancel) == set()


def test_duplicate_and_out_of_order_ticks_cannot_resurrect_or_increase_order() -> None:
    engine = NoVIGOrderBookState()
    engine.bootstrap_market(sample_market(), book=sample_book())
    cancel = {
        "type": "CANCEL",
        "order": {
            "id": "late-order",
            "marketId": "market-1",
            "outcomeId": "market-1-away",
        },
    }
    place = {
        "type": "PLACE",
        "order": {
            "id": "late-order",
            "marketId": "market-1",
            "outcomeId": "market-1-away",
            "price": 0.5,
            "qty": 100,
            "currency": "CASH",
            "status": "OPEN",
        },
    }

    assert engine.apply_message(cancel) == {"market-1"}
    assert engine.apply_message(place) == set()

    existing_increase = deepcopy(place)
    existing_increase["order"]["id"] = "market-1-away-order"
    existing_increase["order"]["price"] = 0.49
    existing_increase["order"]["qty"] = 900
    assert engine.apply_message(existing_increase) == set()


def test_event_go_live_drains_all_event_markets() -> None:
    engine = NoVIGOrderBookState()
    engine.bootstrap_market(sample_market(), book=sample_book())
    engine.bootstrap_market(
        sample_market(market_id="market-2"),
        book=sample_book(market_id="market-2"),
    )

    changed = engine.apply_message(
        {"type": "EVENT_GOLIVE", "market": {"eventId": "event-1"}}
    )

    assert changed == {"market-1", "market-2"}
    assert engine.snapshot("market-1")["eventLive"] is True
    assert engine.snapshot("market-2")["eventLive"] is True
    assert all(not row["bids"] and not row["asks"] for row in engine.snapshot("market-1")["outcomes"])
    assert all(not row["bids"] and not row["asks"] for row in engine.snapshot("market-2")["outcomes"])


def test_stale_feed_detection_uses_current_age() -> None:
    now = [datetime(2026, 7, 14, 20, tzinfo=timezone.utc)]
    engine = NoVIGOrderBookState(clock=lambda: now[0])
    engine.bootstrap_market(sample_market(), book=sample_book())

    assert engine.snapshot("market-1", stale_after_seconds=30)["stale"] is False
    now[0] += timedelta(seconds=31)
    snapshot = engine.snapshot("market-1", stale_after_seconds=30)
    assert snapshot["stale"] is True
    assert snapshot["ageSeconds"] == pytest.approx(31)


def test_rest_normalization_and_exact_event_market_matching() -> None:
    engine = NoVIGOrderBookState()
    engine.bootstrap_market(sample_market(), book=sample_book())
    normalized = normalize_novig_snapshot(engine.snapshot("market-1"))
    trade = canonicalize_trade(sample_trade())

    assert trade is not None
    assert len(normalized) == 2
    assert normalized[0].event_id == "event-1"
    assert normalized[0].selection_id == "market-1|market-1-home"
    assert normalized[0].sport_id == "BASEBALL"
    assert normalized[0].league_id == "MLB"
    assert normalized[0].side_id == "home"
    assert normalized[0].american_odds == probability_to_american(0.51)
    confidence, match = _match_exact_trade(trade, ProviderMarketIndex(normalized))
    assert confidence is MatchConfidence.EXACT
    assert match == normalized[0]


def test_uncertain_event_match_is_not_silently_merged() -> None:
    engine = NoVIGOrderBookState()
    engine.bootstrap_market(sample_market(), book=sample_book())
    normalized = normalize_novig_snapshot(engine.snapshot("market-1"))
    trade = canonicalize_trade(
        sample_trade(event_title="New York Mets vs Boston Red Sox")
    )

    confidence, match = _match_exact_trade(trade, ProviderMarketIndex(normalized))
    assert confidence is MatchConfidence.NO_MATCH
    assert match is None


def test_websocket_reconnect_rebootstraps_and_resubscribes() -> None:
    session = QueueSession(tokens=["worker-token"])
    auth = NoVIGAuthClient("client-id", "client-secret", session=session)
    rest = FakeWorkerRest(sample_market())
    sockets = [
        FakeSocket([{"event": "book", "data": {"book": sample_book()}}]),
        FakeSocket([{"event": "book", "data": {"book": sample_book()}}]),
    ]

    worker = NoVIGFeedWorker(
        auth,
        rest,
        NoVIGStateStore(None),
        market_subscription_limit=1,
        socket_factory=lambda *_args, **_kwargs: sockets.pop(0),
    )
    connected_sockets = list(sockets)
    worker.connect_once(max_messages=1)
    worker.connect_once(max_messages=1)

    assert rest.bootstrap_count == 2
    expected = [
        {"event": "subscribe", "data": "tape"},
        {"event": "subscribe", "data": "lifecycle"},
        {"event": "subscribe", "data": "market-1"},
    ]
    assert connected_sockets[0].sent == expected
    assert connected_sockets[1].sent == expected
    assert all(socket.closed for socket in connected_sockets)


def test_websocket_smoke_requires_initial_book_but_not_a_random_live_tick() -> None:
    session = QueueSession(
        responses=[FakeResponse([sample_market()["event"]])]
    )
    auth = NoVIGAuthClient("client-id", "client-secret", session=session)
    rest = NoVIGRestClient(auth, session=session)
    socket = FakeSocket([{"event": "book", "data": {"book": sample_book()}}])

    result = websocket_smoke_test(
        auth,
        rest,
        socket_factory=lambda *_args, **_kwargs: socket,
    )

    assert result["success"] is True
    assert result["book_snapshot_received"] is True
    assert result["update_received"] is False
    assert session.request_calls[0][2]["params"] == {
        "status": "OPEN_INGAME",
        "limit": 1,
        "offset": 0,
    }
    assert len(session.request_calls) == 1
    assert socket.sent == [
        {"event": "subscribe", "data": "market-1"},
        {"event": "subscribe", "data": "tape"},
        {"event": "subscribe", "data": "lifecycle"},
    ]


def test_websocket_smoke_reports_only_sanitized_provider_http_status() -> None:
    class FailingRest:
        @staticmethod
        def list_events_page(**_filters):
            raise NoVIGError("NOVIG_AUTH_REQUEST_FAILED", status_code=429)

    result = websocket_smoke_test(object(), FailingRest())

    assert result["success"] is False
    assert result["error_code"] == "NOVIG_AUTH_REQUEST_FAILED"
    assert result["http_status"] == 429
    assert result["credentials_exposed"] is False
    assert result["token_exposed"] is False


def test_websocket_smoke_can_use_preselected_market_without_rest_round_trip() -> None:
    session = QueueSession()
    auth = NoVIGAuthClient("client-id", "client-secret", session=session)
    rest = NoVIGRestClient(auth, session=session)
    socket = FakeSocket([{"event": "book", "data": {"book": sample_book()}}])

    result = websocket_smoke_test(
        auth,
        rest,
        market_id="market-1",
        socket_factory=lambda *_args, **_kwargs: socket,
    )

    assert result["success"] is True
    assert session.request_calls == []
    assert socket.sent[0] == {"event": "subscribe", "data": "market-1"}


def test_american_odds_and_live_fee_depth_math() -> None:
    levels = [
        {"price": 0.4, "contracts": 10, "liquidityDollars": 4.0},
        {"price": 0.5, "contracts": 10, "liquidityDollars": 5.0},
    ]

    assert probability_to_american(0.4) == 150
    assert probability_to_american(0.6) == -150
    pregame = _walk_depth(levels, 6.0, event_live=False)
    live = _walk_depth(levels, 6.0, event_live=True)
    assert pregame["effective_price"] == pytest.approx(6 / 14)
    assert pregame["estimated_fee"] == 0
    assert live["effective_price"] == pytest.approx(pregame["effective_price"])
    assert live["estimated_fee"] == pytest.approx(
        0.4 * 0.6 * 0.03 * 10 + 0.5 * 0.5 * 0.03 * 4
    )


def test_direct_sharp_money_snapshot_uses_verified_two_sided_depth() -> None:
    from novig_provider import NoVIGNBXProvider

    provider = NoVIGNBXProvider("client-id", "client-secret")
    provider.rest = FakeWorkerRest(sample_market())

    payload = provider.sharp_money_direct_snapshot(limit=10)

    assert payload["transport"] == "novig_nbx_direct"
    assert len(payload["snapshots"]) == 1
    snapshot = payload["snapshots"][0]
    assert snapshot["marketId"] == "market-1"
    assert len(snapshot["outcomes"]) == 2
    assert snapshot["stale"] is False


def test_direct_sharp_money_filters_catalog_before_applying_limit() -> None:
    from novig_provider import NoVIGNBXProvider

    final_market = sample_market(market_id="market-final", market_type="TOTAL")
    final_market["eventId"] = "event-final"
    final_market["event"]["id"] = "event-final"
    final_market["event"]["status"] = "FINAL"
    prop_market = sample_market(
        market_id="market-player-prop", market_type="RUSHING_YARDS"
    )
    prop_market["eventId"] = "event-prop"
    prop_market["event"]["id"] = "event-prop"
    current_market = sample_market()
    current_event = deepcopy(current_market["event"])
    current_market["event"] = {"id": "event-1"}

    class SelectiveRest:
        def __init__(self):
            self.event_page_calls = []

        def list_open_markets(self):
            return [
                deepcopy(final_market),
                deepcopy(prop_market),
                deepcopy(current_market),
            ]

        def list_events_page(
            self, *, event_status=None, limit=100, offset=0
        ):
            self.event_page_calls.append((event_status, limit, offset))
            events = [
                final_market["event"],
                prop_market["event"],
                current_event,
            ]
            if event_status:
                events = [
                    event
                    for event in events
                    if event.get("status") == event_status
                ]
            return deepcopy(events)

        def list_events(self, **_filters):
            raise AssertionError("direct snapshots must not paginate every event")

        def get_markets_by_events(self, event_ids):
            assert list(event_ids) == ["event-1"]
            return [deepcopy(current_market)]

        def get_book(self, market_id):
            assert market_id == "market-1"
            return sample_book()

    rest = SelectiveRest()
    provider = NoVIGNBXProvider("client-id", "client-secret")
    provider.rest = rest

    payload = provider.sharp_money_direct_snapshot(limit=1)

    assert [row["marketId"] for row in payload["snapshots"]] == ["market-1"]
    assert rest.event_page_calls == [
        ("OPEN_INGAME", 100, 0),
        ("OPEN_PREGAME", 100, 0),
    ]


def test_exact_matching_reads_only_active_events_in_requested_league() -> None:
    from novig_provider import NoVIGNBXProvider

    class PagedRest(FakeWorkerRest):
        def __init__(self, market):
            super().__init__(market)
            self.event_page_calls = []

        def list_open_markets(self, *, league=None):
            assert league == "MLB"
            return [deepcopy(self.market)]

        def list_events_page(
            self, *, league=None, event_status=None, limit=100, offset=0
        ):
            self.event_page_calls.append(
                (league, event_status, limit, offset)
            )
            event = self.market["event"]
            return [deepcopy(event)] if event["status"] == event_status else []

        def list_events(self, **_filters):
            raise AssertionError("exact matching must not scan historical events")

    rest = PagedRest(sample_market())
    provider = NoVIGNBXProvider("client-id", "client-secret")
    provider.rest = rest

    options = provider.options_for_trades([sample_trade()])

    assert options["trade-1"].matching_confidence is MatchConfidence.EXACT
    assert rest.event_page_calls == [
        ("MLB", "OPEN_INGAME", 100, 0),
        ("MLB", "OPEN_PREGAME", 100, 0),
    ]


def test_credentials_and_tokens_never_appear_in_status_errors_or_repr() -> None:
    client_id = "super-sensitive-client-id"
    client_secret = "super-sensitive-client-secret"
    token = "super-sensitive-jwt"
    session = QueueSession(
        tokens=[token],
        responses=[FakeResponse({"message": f"{client_secret} {token}"}, 500)],
    )
    auth = NoVIGAuthClient(client_id, client_secret, session=session)
    rest = NoVIGRestClient(auth, session=session)

    with pytest.raises(NoVIGError) as caught:
        rest.list_open_markets()

    public_text = json.dumps(
        {
            "auth": auth.status(),
            "auth_repr": repr(auth),
            "store_repr": repr(NoVIGStateStore("postgresql://sensitive@host/db")),
            "error": str(caught.value),
        },
        sort_keys=True,
    )
    assert client_id not in public_text
    assert client_secret not in public_text
    assert token not in public_text
    assert "postgresql://" not in public_text


def test_read_only_provider_methods_reject_trading() -> None:
    from novig_provider import NoVIGNBXProvider

    provider = NoVIGNBXProvider("client-id", "client-secret")
    with pytest.raises(PermissionError, match="read-only"):
        provider.place_order({})
    with pytest.raises(PermissionError, match="read-only"):
        provider.cancel_order("order-id")


def test_backend_routes_expose_only_sanitized_novig_market_data(
    app_client, monkeypatch
) -> None:
    class FakeApiProvider:
        configured = True

        @staticmethod
        def diagnostics(*, authenticate=False):
            return {
                "provider": "novig",
                "status": "CONNECTED" if authenticate else "CONFIGURED",
                "credentials_exposed": False,
                "token_exposed": False,
            }

        @staticmethod
        def market_catalog(**_filters):
            return [{"marketId": "market-1", "outcomes": [{"bestAsk": 0.51}]}]

        @staticmethod
        def public_book(market_id, *, outcome_id=None):
            return {
                "provider": "novig",
                "marketId": market_id,
                "outcomes": [{"outcomeId": outcome_id or "market-1-home"}],
                "stale": False,
            }

        @staticmethod
        def unmatched_report():
            return {
                "provider": "novig",
                "count": 0,
                "records": [],
                "credentials_exposed": False,
                "token_exposed": False,
            }

    secret = "must-never-reach-browser"
    app = app_client.application
    app.extensions["novig_nbx_provider"] = FakeApiProvider()
    settings = app.config["SETTINGS"]
    object.__setattr__(settings, "tracker_job_secret", "test-job-secret")
    object.__setattr__(settings, "novig_client_secret", secret)

    health = app_client.get("/api/provider-health/novig")
    markets = app_client.get("/api/providers/novig/markets?league=MLB")
    book = app_client.get(
        "/api/providers/novig/book/market-1?outcome_id=market-1-home"
    )
    unmatched_unauthorized = app_client.get("/api/providers/novig/unmatched")
    unmatched = app_client.get(
        "/api/providers/novig/unmatched",
        headers={"Authorization": "Bearer test-job-secret"},
    )

    assert health.status_code == 200
    assert markets.get_json()["count"] == 1
    assert book.get_json()["marketId"] == "market-1"
    assert unmatched_unauthorized.status_code == 401
    assert unmatched.status_code == 200
    combined = "".join(
        response.get_data(as_text=True)
        for response in (health, markets, book, unmatched_unauthorized, unmatched)
    )
    assert secret not in combined
    assert "access_token" not in combined


def test_novig_authenticated_health_smoke_requires_job_authorization(app_client) -> None:
    provider = app_client.application.extensions["novig_nbx_provider"]
    calls = []
    provider.diagnostics = lambda *, authenticate=False: (
        calls.append(authenticate)
        or {
            "provider": "novig",
            "status": "AUTHENTICATED" if authenticate else "CONFIGURED",
        }
    )
    settings = app_client.application.config["SETTINGS"]
    object.__setattr__(settings, "tracker_job_secret", "test-job-secret")

    assert app_client.post("/api/provider-health/novig").status_code == 401
    authorized = app_client.post(
        "/api/provider-health/novig",
        headers={"Authorization": "Bearer test-job-secret"},
    )

    assert authorized.status_code == 200
    assert authorized.get_json()["status"] == "AUTHENTICATED"
    assert calls == [True]


def test_novig_websocket_smoke_is_job_authorized_and_sanitized(
    app_client, monkeypatch
) -> None:
    import app as app_module

    class FakeProvider:
        configured = True
        auth = object()
        rest = object()
        websocket_url = "wss://api.novig.us/tape"

    app = app_client.application
    app.extensions["novig_nbx_provider"] = FakeProvider()
    settings = app.config["SETTINGS"]
    object.__setattr__(settings, "tracker_job_secret", "test-job-secret")
    captured = {}

    def fake_websocket_smoke(*_args, **kwargs):
        captured.update(kwargs)
        return {
            "success": True,
            "connected": True,
            "book_snapshot_received": True,
            "update_received": True,
            "message_types": ["book", "PLACE"],
            "error_code": None,
            "credentials_exposed": False,
            "token_exposed": False,
        }

    monkeypatch.setattr(
        app_module,
        "websocket_smoke_test",
        fake_websocket_smoke,
    )

    unauthorized = app_client.post("/api/provider-health/novig/websocket")
    authorized = app_client.post(
        "/api/provider-health/novig/websocket?market_id=market-1",
        headers={"Authorization": "Bearer test-job-secret"},
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    payload = authorized.get_json()
    assert payload["success"] is True
    assert payload["book_snapshot_received"] is True
    assert payload["credentials_exposed"] is False
    assert payload["token_exposed"] is False
    assert captured["market_id"] == "market-1"
