from datetime import datetime, timezone

import pytest

from execution_providers import CanonicalTrade, MatchConfidence, ProviderMarketIndex, _match_exact_trade
from fourcx_provider import FourCXHealthStatus, FourCXProvider, _effective_price, normalize_fourcx_game


class Response:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("upstream failure")


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def game():
    return {
        "id": "game-1", "sport": "baseball", "league": "MLB",
        "start": "2026-07-17T23:05:00Z", "periodName": "Full Time",
        "live": False, "ended": False,
        "participants": [
            {"homeAway": "home", "longName": "Philadelphia Phillies", "shortName": "Phillies"},
            {"homeAway": "away", "longName": "New York Mets", "shortName": "Mets"},
        ],
        "homeMoneylines": [{"id": "phl-1", "odds": -120, "sumUntaken": 100}, {"id": "phl-2", "odds": -110, "sumUntaken": 50}],
        "awayMoneylines": [{"id": "nym-1", "odds": 105, "sumUntaken": 80}],
        "homeSpreads": [{"id": "phl-sp", "odds": 140, "spread": -1.5, "sumUntaken": 20}],
        "awaySpreads": [{"id": "nym-sp", "odds": -150, "spread": 1.5, "sumUntaken": 20}],
        "over": [{"id": "over", "odds": -105, "total": 8.5, "sumUntaken": 40}],
        "under": [{"id": "under", "odds": -105, "total": 8.5, "sumUntaken": 40}],
    }


def test_normalization_and_exact_matching():
    markets, depth = normalize_fourcx_game(game(), datetime(2026, 7, 16, tzinfo=timezone.utc))
    trade = CanonicalTrade(
        "trade-1", "BASEBALL", "MLB", datetime(2026, 7, 17, 23, 5, tzinfo=timezone.utc),
        ("New York Mets", "Philadelphia Phillies"), "Philadelphia Phillies",
        "moneyline", "game", None, "team", "winner:game:draw_push", False,
    )
    confidence, matched = _match_exact_trade(trade, ProviderMarketIndex(markets))
    assert confidence is MatchConfidence.EXACT
    assert matched.selection_id == "phl-2"
    assert matched.deep_link == "https://4cx.io/exchange-single/game-1"
    assert depth["phl-2"][0]["remaining"] == 50


def test_line_and_period_mismatch_are_not_exact():
    markets, _ = normalize_fourcx_game(game(), datetime.now(timezone.utc))
    wrong = CanonicalTrade(
        "trade-1", "BASEBALL", "MLB", datetime(2026, 7, 17, 23, 5, tzinfo=timezone.utc),
        ("New York Mets", "Philadelphia Phillies"), "Philadelphia Phillies -2.5",
        "spread", "1h", -2.5, "team", "spread:1h:team", False,
    )
    assert _match_exact_trade(wrong, ProviderMarketIndex(markets))[0] is not MatchConfidence.EXACT


def test_depth_weighted_price_requires_full_stake():
    levels = [{"contract_price": .5, "remaining": 10}, {"contract_price": .6, "remaining": 20}]
    price, liquidity, fillable = _effective_price(levels, 20)
    assert price == pytest.approx(.55)
    assert liquidity == 30
    assert fillable is True
    assert _effective_price(levels, 40)[2] is False


def test_auth_token_is_raw_cached_and_reauthenticated_once():
    session = Session([
        Response({"data": {"user": {"auth": "token-one", "playerMode": "cash"}}}),
        Response({}, 401),
        Response({"data": {"user": {"auth": "token-two", "playerMode": "cash"}}}),
        Response({"data": {"availableEvents": []}}),
    ])
    provider = FourCXProvider("user", "secret", enabled=True, session=session)
    provider._request("/exchange/getEvents", {"sport": "baseball"})
    assert session.calls[1][1]["headers"]["Authorization"] == "token-one"
    assert session.calls[3][1]["headers"]["Authorization"] == "token-two"
    assert provider.health_status() is FourCXHealthStatus.CONNECTED
    assert "secret" not in repr(provider) and "token" not in repr(provider)


def test_trading_is_unconditionally_disabled_without_http_calls():
    session = Session([])
    provider = FourCXProvider("user", "secret", enabled=True, trading_enabled=True, session=session)
    with pytest.raises(PermissionError):
        provider.place_order({"anything": True})
    with pytest.raises(PermissionError):
        provider.cancel_order("order")
    assert session.calls == []
