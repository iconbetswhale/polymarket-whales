from __future__ import annotations

from datetime import datetime, timezone

from trade_scoring import build_trades_to_play, sharps_badge


def _position(
    wallet: str,
    label: str,
    outcome: str = "Yankees",
    condition_id: str = "0xmarket",
    amount: float = 1000,
    avg: float = 0.4,
    current: float = 0.42,
):
    return {
        "wallet_address": wallet,
        "wallet_label": label,
        "wallet_profile_url": f"https://polymarket.com/profile/{wallet}",
        "condition_id": condition_id,
        "event_slug": "mlb-nyy-bos-2026-07-14",
        "market_slug": "mlb-nyy-bos-2026-07-14-nyy",
        "market_title": "Yankees vs Red Sox",
        "event_title": "Yankees vs Red Sox",
        "outcome": outcome,
        "category": "MLB",
        "league": "MLB",
        "resolution_time": "2026-07-14T23:10:00Z",
        "first_detected_at": "2026-07-13T00:00:00+00:00",
        "last_changed_at": "2026-07-13T00:10:00+00:00",
        "average_entry_price": avg,
        "current_price": current,
        "position_size_usd": amount,
        "market_url": "https://polymarket.com/event/test",
        "status": "open",
    }


def test_sharps_badge_starts_at_two():
    assert sharps_badge(1) is None
    assert sharps_badge(2) == "Two Sharps"
    assert sharps_badge(4) == "Four Sharps"


def test_groups_agreeing_wallets_and_selects_largest_primary():
    positions = [
        _position("0xa", "A", amount=500),
        _position("0xb", "B", amount=2200),
    ]
    plays = build_trades_to_play(positions, unit_map={"0xa": {"estimated_base_unit": 100}, "0xb": {"estimated_base_unit": 1000}}, now=datetime(2026, 7, 13, tzinfo=timezone.utc))

    assert len(plays) == 1
    play = plays[0]
    assert play["sharps_badge"] == "Two Sharps"
    assert play["agreeing_wallet_count"] == 2
    assert play["total_amount_bet"] == 2700
    assert play["primary_trader"]["wallet_label"] == "B"
    assert len(play["supporting_wallets"]) == 2


def test_opposite_sides_are_excluded_before_scoring():
    positions = [
        _position("0xa", "A", outcome="Yankees"),
        _position("0xb", "B", outcome="Red Sox"),
    ]
    plays = build_trades_to_play(positions, now=datetime(2026, 7, 13, tzinfo=timezone.utc))

    assert plays == []


def test_unrelated_markets_same_event_do_not_conflict():
    positions = [
        _position("0xa", "A", outcome="Yankees", condition_id="0xmoneyline"),
        _position("0xb", "B", outcome="Over 8.5", condition_id="0xtotal"),
    ]
    plays = build_trades_to_play(positions, now=datetime(2026, 7, 13, tzinfo=timezone.utc))

    assert len(plays) == 2
    assert {play["canonical_market_key"] for play in plays} == {"0xmoneyline", "0xtotal"}


def test_confidence_score_breakdown_and_sorting():
    positions = [
        _position("0xa", "A", condition_id="0xsmall", amount=200),
        _position("0xb", "B", condition_id="0xbig", amount=2000),
        _position("0xc", "C", condition_id="0xbig", amount=2500),
    ]
    plays = build_trades_to_play(positions, unit_map={"0xb": {"estimated_base_unit": 500}, "0xc": {"estimated_base_unit": 500}}, now=datetime(2026, 7, 13, tzinfo=timezone.utc))

    assert plays[0]["canonical_market_key"] == "0xbig"
    assert 0 <= plays[0]["confidence_score"] <= 100
    assert "sharps_consensus" in plays[0]["score_breakdown"]
    assert plays[0]["confidence_score"] >= plays[-1]["confidence_score"]


def test_event_time_is_converted_to_eastern_with_dst():
    plays = build_trades_to_play([_position("0xa", "A")], now=datetime(2026, 7, 13, tzinfo=timezone.utc))

    assert plays[0]["event_time_et"] == "Jul 14, 2026 · 7:10 PM ET"


def test_started_or_closed_events_are_not_actionable():
    closed = _position("0xa", "A")
    closed["status"] = "closed"
    started = _position("0xb", "B", condition_id="0xstarted")
    started["resolution_time"] = "2026-07-12T20:00:00Z"

    plays = build_trades_to_play([closed, started], now=datetime(2026, 7, 13, tzinfo=timezone.utc))

    assert plays == []
