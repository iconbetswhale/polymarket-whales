from __future__ import annotations

from datetime import datetime, timezone

from trade_scoring import build_trades_to_play, filter_trades_to_play, sharps_badge


def _position(
    wallet: str,
    label: str,
    outcome: str = "Yankees",
    condition_id: str = "0xmarket",
    amount: float = 1000,
    avg: float = 0.4,
    current: float = 0.42,
    **overrides,
):
    payload = {
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
        "event_time_source": "event.startDate",
        "first_detected_at": "2026-07-13T00:00:00+00:00",
        "last_changed_at": "2026-07-13T00:10:00+00:00",
        "average_entry_price": avg,
        "current_price": current,
        "position_size_usd": amount,
        "market_url": "https://polymarket.com/event/test",
        "status": "open",
        "shares": 100,
    }
    payload.update(overrides)
    return payload


def _unit_map(*wallets: str, base: float = 1000):
    return {wallet.lower(): {"estimated_base_unit": base} for wallet in wallets}


def _now():
    return datetime(2026, 7, 13, tzinfo=timezone.utc)


def test_sharps_badge_starts_at_two():
    assert sharps_badge(1) is None
    assert sharps_badge(2) == "Two Sharps"
    assert sharps_badge(4) == "Four Sharps"


def test_groups_agreeing_wallets_and_selects_largest_primary():
    positions = [
        _position("0xa", "A", amount=500),
        _position("0xb", "B", amount=2200),
    ]
    plays = build_trades_to_play(positions, unit_map={"0xa": {"estimated_base_unit": 100}, "0xb": {"estimated_base_unit": 1000}}, now=_now())

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
    plays = build_trades_to_play(positions, unit_map=_unit_map("0xa", "0xb"), now=_now())

    assert plays == []


def test_unrelated_markets_same_event_do_not_conflict():
    positions = [
        _position("0xa", "A", outcome="Yankees", condition_id="0xmoneyline"),
        _position("0xb", "B", outcome="Over 8.5", condition_id="0xtotal"),
    ]
    plays = build_trades_to_play(positions, unit_map=_unit_map("0xa", "0xb"), now=_now())

    assert len(plays) == 2
    assert {play["canonical_market_key"] for play in plays} == {"0xmoneyline", "0xtotal"}


def test_confidence_score_breakdown_and_sorting():
    positions = [
        _position("0xa", "A", condition_id="0xsmall", amount=200),
        _position("0xb", "B", condition_id="0xbig", amount=2000),
        _position("0xc", "C", condition_id="0xbig", amount=2500),
    ]
    plays = build_trades_to_play(positions, unit_map={"0xb": {"estimated_base_unit": 500}, "0xc": {"estimated_base_unit": 500}}, now=_now())

    assert plays[0]["canonical_market_key"] == "0xbig"
    assert 50 <= plays[0]["confidence_score"] <= 100
    assert plays[0]["score_breakdown"]["architecture"] == "consensus_first"
    assert plays[0]["confidence_score"] >= plays[-1]["confidence_score"]


def test_event_time_is_converted_to_eastern_with_dst():
    plays = build_trades_to_play([_position("0xa", "A")], unit_map=_unit_map("0xa"), now=_now())

    assert plays[0]["event_time_et"] == "Jul 14, 2026 - 7:10 PM ET"


def test_started_or_closed_events_are_not_actionable():
    closed = _position("0xa", "A")
    closed["status"] = "closed"
    started = _position("0xb", "B", condition_id="0xstarted")
    started["resolution_time"] = "2026-07-12T20:00:00Z"

    plays = build_trades_to_play([closed, started], unit_map=_unit_map("0xa", "0xb"), now=_now())

    assert plays == []


def test_search_matches_entire_event_not_only_selected_bet():
    positions = [
        _position(
            "0xa",
            "A",
            outcome="Yankees",
            condition_id="0xmoneyline",
            market_title="Yankees moneyline",
            event_title="Toronto Blue Jays vs New York Yankees",
            event_slug="mlb-blue-jays-yankees-2026-07-14",
        ),
        _position(
            "0xb",
            "B",
            outcome="Over 8.5",
            condition_id="0xtotal",
            market_title="Full game total",
            event_title="Toronto Blue Jays vs New York Yankees",
            event_slug="mlb-blue-jays-yankees-2026-07-14",
        ),
        _position(
            "0xc",
            "C",
            outcome="Red Sox",
            condition_id="0xother",
            market_title="Red Sox moneyline",
            event_title="Boston Red Sox vs Tampa Bay Rays",
            event_slug="mlb-red-sox-rays-2026-07-14",
        ),
    ]
    plays = build_trades_to_play(positions, unit_map=_unit_map("0xa", "0xb", "0xc"), now=_now())

    blue_jays = filter_trades_to_play(plays, search="Blue Jays", now=_now())
    tor = filter_trades_to_play(plays, search="TOR", now=_now())

    assert {play["canonical_market_key"] for play in blue_jays} == {"0xmoneyline", "0xtotal"}
    assert {play["canonical_market_key"] for play in tor} == {"0xmoneyline", "0xtotal"}


def test_sharps_filter_counts_unique_active_wallets_only():
    positions = [
        _position("0xa", "A", amount=500, last_changed_at="2026-07-13T00:10:00+00:00"),
        _position("0xa", "A", amount=700, last_changed_at="2026-07-13T00:20:00+00:00"),
        _position("0xb", "B", amount=800),
        _position("0xc", "C", amount=900),
        _position("0xd", "D", amount=0),
        _position("0xe", "E", status="closed"),
    ]
    plays = build_trades_to_play(positions, unit_map=_unit_map("0xa", "0xb", "0xc", "0xd", "0xe"), now=_now())

    assert len(plays) == 1
    assert plays[0]["agreeing_wallet_count"] == 3
    assert filter_trades_to_play(plays, min_sharps=3, now=_now()) == plays
    assert filter_trades_to_play(plays, min_sharps=4, now=_now()) == []
    assert plays[0]["combined_exposure_exact"] == sum(item["amount"] for item in plays[0]["supporting_wallets"])


def test_minimum_units_rule_is_strictly_greater_than_point_two():
    exact = _position("0xa", "A", amount=200, condition_id="0xexact")
    above = _position("0xb", "B", amount=201, condition_id="0xabove")

    plays = build_trades_to_play([exact, above], unit_map=_unit_map("0xa", "0xb"), now=_now())

    assert {play["canonical_market_key"] for play in plays} == {"0xabove"}
    assert plays[0]["primary_trader"]["amount"] == 201
    assert plays[0]["primary_trader"]["relative_units"] == 0.201


def test_exact_amounts_stay_attached_to_correct_traders():
    positions = [
        _position("0xa", "A", amount=4137.52),
        _position("0xb", "B", amount=4804.65),
    ]
    plays = build_trades_to_play(positions, unit_map=_unit_map("0xa", "0xb"), now=_now())
    supporters = {item["wallet_label"]: item["amount"] for item in plays[0]["supporting_wallets"]}

    assert supporters == {"A": 4137.52, "B": 4804.65}
    assert plays[0]["combined_exposure_exact"] == 8942.17


def test_date_filters_use_event_start_not_trade_entry_time():
    today_trade_tomorrow_event = _position(
        "0xa",
        "A",
        condition_id="0xtomorrow",
        resolution_time="2026-07-14T16:00:00Z",
        first_detected_at="2026-07-13T13:00:00+00:00",
    )
    midnight_event = _position(
        "0xb",
        "B",
        condition_id="0xtoday",
        resolution_time="2026-07-13T04:30:00Z",
        first_detected_at="2026-07-12T23:00:00+00:00",
    )
    plays = build_trades_to_play(
        [today_trade_tomorrow_event, midnight_event],
        unit_map=_unit_map("0xa", "0xb"),
        now=datetime(2026, 7, 13, 0, 1, tzinfo=timezone.utc),
    )

    today = filter_trades_to_play(plays, date_range="today", now=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc))
    next24 = filter_trades_to_play(plays, date_range="next24", now=datetime(2026, 7, 13, 20, 0, tzinfo=timezone.utc))

    assert {play["canonical_market_key"] for play in today} == {"0xtoday"}
    assert {play["canonical_market_key"] for play in next24} == {"0xtomorrow"}


def test_rescheduled_event_uses_updated_start_time():
    position = _position("0xa", "A", resolution_time="2026-07-15T23:10:00Z")
    plays = build_trades_to_play([position], unit_map=_unit_map("0xa"), now=_now())

    tomorrow = filter_trades_to_play(plays, date_range="tomorrow", now=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc))
    custom = filter_trades_to_play(plays, date_range="custom", custom_start="2026-07-15", custom_end="2026-07-15", now=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc))

    assert tomorrow == []
    assert custom == plays


def test_one_sharp_score_stays_in_one_sharp_band_even_with_strong_metrics():
    position = _position("0xa", "A", amount=100000, current=0.4, avg=0.4)
    plays = build_trades_to_play([position], unit_map=_unit_map("0xa", base=1000), tracked_wallet_count=5, now=_now())

    assert len(plays) == 1
    assert 50 <= plays[0]["confidence_score"] <= 69
    assert plays[0]["score_breakdown"]["band_start"] == 50
    assert plays[0]["score_breakdown"]["band_end"] == 69


def test_two_sharp_score_stays_in_two_sharp_band_even_with_strong_metrics():
    positions = [
        _position("0xa", "A", amount=100000, current=0.4, avg=0.4),
        _position("0xb", "B", amount=90000, current=0.4, avg=0.4),
    ]
    plays = build_trades_to_play(positions, unit_map=_unit_map("0xa", "0xb", base=1000), tracked_wallet_count=5, now=_now())

    assert len(plays) == 1
    assert 70 <= plays[0]["confidence_score"] <= 79
    assert plays[0]["score_breakdown"]["band_start"] == 70
    assert plays[0]["score_breakdown"]["band_end"] == 79


def test_three_or_more_sharps_start_at_eighty():
    positions = [
        _position("0xa", "A", amount=201),
        _position("0xb", "B", amount=202),
        _position("0xc", "C", amount=203),
    ]
    plays = build_trades_to_play(positions, unit_map=_unit_map("0xa", "0xb", "0xc"), tracked_wallet_count=5, now=_now())

    assert len(plays) == 1
    assert 80 <= plays[0]["confidence_score"] <= 99
    assert plays[0]["score_breakdown"]["band_start"] == 80
    assert plays[0]["score_breakdown"]["band_end"] == 99


def test_every_enabled_wallet_agreeing_scores_exactly_one_hundred():
    positions = [
        _position("0xa", "A", amount=500),
        _position("0xb", "B", amount=600),
        _position("0xc", "C", amount=700),
    ]
    plays = build_trades_to_play(positions, unit_map=_unit_map("0xa", "0xb", "0xc"), tracked_wallet_count=3, now=_now())

    assert len(plays) == 1
    assert plays[0]["confidence_score"] == 100
    assert plays[0]["score_breakdown"]["consensus_band"] == "Complete tracked-wallet agreement"


def test_missing_wallet_prevents_one_hundred_and_opposing_wallet_excludes_trade():
    non_unanimous = [
        _position("0xa", "A", amount=500),
        _position("0xb", "B", amount=600),
    ]
    plays = build_trades_to_play(non_unanimous, unit_map=_unit_map("0xa", "0xb"), tracked_wallet_count=3, now=_now())
    assert len(plays) == 1
    assert plays[0]["confidence_score"] < 100

    opposing = non_unanimous + [_position("0xc", "C", outcome="Red Sox", amount=700)]
    assert build_trades_to_play(opposing, unit_map=_unit_map("0xa", "0xb", "0xc"), tracked_wallet_count=3, now=_now()) == []


def test_duplicate_and_inactive_wallets_do_not_create_unanimity():
    positions = [
        _position("0xa", "A", amount=500, last_changed_at="2026-07-13T00:10:00+00:00"),
        _position("0xa", "A", amount=600, last_changed_at="2026-07-13T00:20:00+00:00"),
        _position("0xb", "B", amount=700),
        _position("0xc", "C", amount=0),
        _position("0xd", "D", status="closed"),
    ]
    plays = build_trades_to_play(positions, unit_map=_unit_map("0xa", "0xb", "0xc", "0xd"), tracked_wallet_count=3, now=_now())

    assert len(plays) == 1
    assert plays[0]["agreeing_wallet_count"] == 2
    assert 70 <= plays[0]["confidence_score"] <= 79
