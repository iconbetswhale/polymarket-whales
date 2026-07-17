from datetime import datetime, timezone

import pytest

from execution_providers import CanonicalTrade, MatchConfidence, ProviderMarketIndex, _match_exact_trade
from kalshi_provider import KalshiProvider, _normalize_market


def market():
    return {
        "ticker": "KXMLBGAME-26JUL172305NYMPHI-PHI",
        "event_ticker": "KXMLBGAME-26JUL172305NYMPHI",
        "title": "New York Mets vs Philadelphia Phillies",
        "yes_sub_title": "Philadelphia Phillies",
        "occurrence_datetime": "2026-07-17T23:05:00Z",
        "status": "active", "updated_time": "2026-07-16T23:00:00Z",
        "yes_ask_dollars": "0.6000", "yes_ask_size_fp": "250.00",
        "no_ask_dollars": "0.4200", "no_ask_size_fp": "175.00",
    }


def test_public_market_normalizes_both_executable_sides():
    rows = _normalize_market(market(), "BASEBALL", "MLB")
    assert len(rows) == 2
    assert {row.side_id for row in rows} == {"home", "away"}
    assert all(row.is_available for row in rows)


def test_kalshi_market_requires_exact_event_and_selection_match():
    rows = _normalize_market(market(), "BASEBALL", "MLB")
    trade = CanonicalTrade(
        "trade", "BASEBALL", "MLB", datetime(2026, 7, 17, 23, 5, tzinfo=timezone.utc),
        ("New York Mets", "Philadelphia Phillies"), "Philadelphia Phillies", "moneyline",
        "game", None, "team", "winner:game:draw_push", False,
    )
    confidence, matched = _match_exact_trade(trade, ProviderMarketIndex(rows))
    assert confidence is MatchConfidence.EXACT
    assert "|yes|" in matched.selection_id


def test_kalshi_trading_is_disabled():
    provider = KalshiProvider()
    with pytest.raises(PermissionError):
        provider.place_order({})
    with pytest.raises(PermissionError):
        provider.cancel_order("anything")
