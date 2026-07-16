from __future__ import annotations

from datetime import datetime, timezone

import pytest

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
    if not any(
        key in overrides
        for key in (
            "configured_top_category",
            "configured_top_categories",
            "configured_top_category_ids",
            "top_category",
            "top_category_ids",
        )
    ):
        payload["configured_top_category"] = payload["category"]
        payload["configured_top_category_ids"] = [payload["category"]]
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
    plays = build_trades_to_play(
        positions,
        unit_map={
            "0xa": {"estimated_base_unit": 100},
            "0xb": {"estimated_base_unit": 1000},
        },
        now=_now(),
    )

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
    plays = build_trades_to_play(
        positions, unit_map=_unit_map("0xa", "0xb"), now=_now()
    )

    assert plays == []


def test_same_wallet_is_netted_to_one_direction_before_consensus_scoring():
    positions = [
        _position("0xa", "Lead A", outcome="Phillies", amount=12500),
        _position("0xb", "Lead B", outcome="Phillies", amount=14693),
        _position("0xnet", "Net Sharp", outcome="Phillies", amount=3390),
        _position("0xnet", "Net Sharp", outcome="Mets", amount=2458),
    ]

    plays = build_trades_to_play(
        positions,
        unit_map=_unit_map("0xa", "0xb", "0xnet", base=100),
        now=_now(),
    )

    assert len(plays) == 1
    play = plays[0]
    net_sharp = next(
        row for row in play["supporting_wallets"] if row["wallet_label"] == "Net Sharp"
    )
    assert play["outcome"] == "Phillies"
    assert play["rawAgreeingSharpCount"] == 3
    assert play["rawContradictingSharpCount"] == 0
    assert play["contradicting_wallets"] == []
    assert net_sharp["amount"] == pytest.approx(932)
    assert net_sharp["gross_amount"] == pytest.approx(3390)
    assert net_sharp["opposing_amount"] == pytest.approx(2458)
    assert net_sharp["wallet_hedge_status"] == "directional_after_market_netting"
    assert play["agreeingExposureDollars"] == pytest.approx(28125)


def test_unrelated_markets_same_event_do_not_conflict():
    positions = [
        _position("0xa", "A", outcome="Yankees", condition_id="0xmoneyline"),
        _position("0xb", "B", outcome="Over 8.5", condition_id="0xtotal"),
    ]
    plays = build_trades_to_play(
        positions, unit_map=_unit_map("0xa", "0xb"), now=_now()
    )

    assert len(plays) == 2
    assert {play["canonical_market_key"] for play in plays} == {
        "0xmoneyline",
        "0xtotal",
    }


def test_confidence_score_breakdown_and_sorting():
    positions = [
        _position("0xa", "A", condition_id="0xsmall", amount=200),
        _position("0xb", "B", condition_id="0xbig", amount=2000),
        _position("0xc", "C", condition_id="0xbig", amount=2500),
    ]
    plays = build_trades_to_play(
        positions,
        unit_map={
            "0xb": {"estimated_base_unit": 500},
            "0xc": {"estimated_base_unit": 500},
        },
        now=_now(),
    )

    assert plays[0]["canonical_market_key"] == "0xbig"
    assert 50 <= plays[0]["confidence_score"] <= 100
    assert plays[0]["score_breakdown"]["architecture"] == "consensus_first"
    assert plays[0]["confidence_score"] >= plays[-1]["confidence_score"]


def test_event_time_is_converted_to_eastern_with_dst():
    plays = build_trades_to_play(
        [_position("0xa", "A")], unit_map=_unit_map("0xa"), now=_now()
    )

    assert plays[0]["event_time_et"] == "Jul 14, 2026 - 7:10 PM ET"


def test_date_only_event_time_does_not_render_fake_clock_time():
    position = _position(
        "0xa", "A", resolution_time="2026-07-14", event_time_source="position.endDate"
    )
    plays = build_trades_to_play([position], unit_map=_unit_map("0xa"), now=_now())

    assert plays[0]["event_time_et"] is None
    assert plays[0]["event_date_et"] is None
    assert filter_trades_to_play(plays, date_range="", now=_now()) == []
    assert filter_trades_to_play(plays, date_range="today", now=_now()) == []


def test_started_or_closed_events_are_not_actionable():
    closed = _position("0xa", "A")
    closed["status"] = "closed"
    started = _position("0xb", "B", condition_id="0xstarted")
    started["resolution_time"] = "2026-07-12T20:00:00Z"

    plays = build_trades_to_play(
        [closed, started], unit_map=_unit_map("0xa", "0xb"), now=_now()
    )

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
    plays = build_trades_to_play(
        positions, unit_map=_unit_map("0xa", "0xb", "0xc"), now=_now()
    )

    blue_jays = filter_trades_to_play(plays, search="Blue Jays", now=_now())
    tor = filter_trades_to_play(plays, search="TOR", now=_now())

    assert {play["canonical_market_key"] for play in blue_jays} == {
        "0xmoneyline",
        "0xtotal",
    }
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
    plays = build_trades_to_play(
        positions, unit_map=_unit_map("0xa", "0xb", "0xc", "0xd", "0xe"), now=_now()
    )

    assert len(plays) == 1
    assert plays[0]["agreeing_wallet_count"] == 3
    assert filter_trades_to_play(plays, min_sharps=3, now=_now()) == plays
    assert filter_trades_to_play(plays, min_sharps=4, now=_now()) == []
    assert plays[0]["combined_exposure_exact"] == sum(
        item["amount"] for item in plays[0]["supporting_wallets"]
    )


def test_minimum_units_rule_is_strictly_greater_than_point_two():
    exact = _position("0xa", "A", amount=200, condition_id="0xexact")
    above = _position("0xb", "B", amount=201, condition_id="0xabove")

    plays = build_trades_to_play(
        [exact, above], unit_map=_unit_map("0xa", "0xb"), now=_now()
    )

    assert {play["canonical_market_key"] for play in plays} == {"0xabove"}
    assert plays[0]["primary_trader"]["amount"] == 201
    assert plays[0]["primary_trader"]["relative_units"] == 0.201


def test_exact_amounts_stay_attached_to_correct_traders():
    positions = [
        _position("0xa", "A", amount=4137.52),
        _position("0xb", "B", amount=4804.65),
    ]
    plays = build_trades_to_play(
        positions, unit_map=_unit_map("0xa", "0xb"), now=_now()
    )
    supporters = {
        item["wallet_label"]: item["amount"] for item in plays[0]["supporting_wallets"]
    }

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

    today = filter_trades_to_play(
        plays, date_range="today", now=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    )
    next24 = filter_trades_to_play(
        plays,
        date_range="next24",
        now=datetime(2026, 7, 13, 20, 0, tzinfo=timezone.utc),
    )

    assert today == []
    assert {play["canonical_market_key"] for play in next24} == {"0xtomorrow"}


def test_rescheduled_event_uses_updated_start_time():
    position = _position("0xa", "A", resolution_time="2026-07-15T23:10:00Z")
    plays = build_trades_to_play([position], unit_map=_unit_map("0xa"), now=_now())

    tomorrow = filter_trades_to_play(
        plays,
        date_range="tomorrow",
        now=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
    )
    custom = filter_trades_to_play(
        plays,
        date_range="custom",
        custom_start="2026-07-15",
        custom_end="2026-07-15",
        now=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
    )

    assert tomorrow == []
    assert custom == plays


def test_next_seven_days_is_rolling_and_excludes_the_exact_past():
    soon = _position(
        "0xa", "A", condition_id="0xsoon", resolution_time="2026-07-20T11:59:59Z"
    )
    too_late = _position(
        "0xb", "B", condition_id="0xlate", resolution_time="2026-07-20T12:00:01Z"
    )
    already_started = _position(
        "0xc", "C", condition_id="0xpast", resolution_time="2026-07-13T11:59:59Z"
    )
    plays = build_trades_to_play(
        [soon, too_late, already_started],
        unit_map=_unit_map("0xa", "0xb", "0xc"),
        now=datetime(2026, 7, 13, 11, 0, tzinfo=timezone.utc),
    )

    filtered = filter_trades_to_play(
        plays, date_range="next7", now=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    )

    assert {play["canonical_market_key"] for play in filtered} == {"0xsoon"}


def test_custom_datetime_boundaries_are_exact_and_eastern():
    inside = _position(
        "0xa", "A", condition_id="0xinside", resolution_time="2026-07-14T16:30:00Z"
    )
    outside = _position(
        "0xb", "B", condition_id="0xoutside", resolution_time="2026-07-14T16:31:00Z"
    )
    plays = build_trades_to_play(
        [inside, outside],
        unit_map=_unit_map("0xa", "0xb"),
        now=_now(),
    )

    filtered = filter_trades_to_play(
        plays,
        date_range="custom",
        custom_start="2026-07-14T12:00",
        custom_end="2026-07-14T12:30",
        now=_now(),
    )

    assert {play["canonical_market_key"] for play in filtered} == {"0xinside"}


def test_one_sharp_score_stays_in_one_sharp_band_even_with_strong_metrics():
    position = _position("0xa", "A", amount=100000, current=0.4, avg=0.4)
    plays = build_trades_to_play(
        [position],
        unit_map=_unit_map("0xa", base=1000),
        tracked_wallet_count=5,
        now=_now(),
    )

    assert len(plays) == 1
    assert 50 <= plays[0]["confidence_score"] <= 69
    assert plays[0]["score_breakdown"]["band_start"] == 50
    assert plays[0]["score_breakdown"]["band_end"] == 69


def test_two_sharp_score_stays_in_two_sharp_band_even_with_strong_metrics():
    positions = [
        _position("0xa", "A", amount=100000, current=0.4, avg=0.4),
        _position("0xb", "B", amount=90000, current=0.4, avg=0.4),
    ]
    plays = build_trades_to_play(
        positions,
        unit_map=_unit_map("0xa", "0xb", base=1000),
        tracked_wallet_count=5,
        now=_now(),
    )

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
    plays = build_trades_to_play(
        positions,
        unit_map=_unit_map("0xa", "0xb", "0xc"),
        tracked_wallet_count=5,
        now=_now(),
    )

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
    plays = build_trades_to_play(
        positions,
        unit_map=_unit_map("0xa", "0xb", "0xc"),
        tracked_wallet_count=3,
        now=_now(),
    )

    assert len(plays) == 1
    assert plays[0]["confidence_score"] == 100
    assert (
        plays[0]["score_breakdown"]["consensus_band"]
        == "Complete tracked-wallet agreement"
    )


def test_missing_wallet_prevents_one_hundred_and_opposing_minority_is_research():
    non_unanimous = [
        _position("0xa", "A", amount=500),
        _position("0xb", "B", amount=600),
    ]
    plays = build_trades_to_play(
        non_unanimous,
        unit_map=_unit_map("0xa", "0xb"),
        tracked_wallet_count=3,
        now=_now(),
    )
    assert len(plays) == 1
    assert plays[0]["confidence_score"] < 100

    opposing = non_unanimous + [_position("0xc", "C", outcome="Red Sox", amount=700)]
    research = build_trades_to_play(
        opposing,
        unit_map=_unit_map("0xa", "0xb", "0xc"),
        tracked_wallet_count=3,
        now=_now(),
    )
    assert research[0]["tradeClassification"] == "CONTRADICTING_SHARPS"
    assert research[0]["confidence_score"] <= 69


def test_duplicate_and_inactive_wallets_do_not_create_unanimity():
    positions = [
        _position("0xa", "A", amount=500, last_changed_at="2026-07-13T00:10:00+00:00"),
        _position("0xa", "A", amount=600, last_changed_at="2026-07-13T00:20:00+00:00"),
        _position("0xb", "B", amount=700),
        _position("0xc", "C", amount=0),
        _position("0xd", "D", status="closed"),
    ]
    plays = build_trades_to_play(
        positions,
        unit_map=_unit_map("0xa", "0xb", "0xc", "0xd"),
        tracked_wallet_count=3,
        now=_now(),
    )

    assert len(plays) == 1
    assert plays[0]["agreeing_wallet_count"] == 2
    assert 70 <= plays[0]["confidence_score"] <= 79


def test_wallet_specific_actionable_threshold_gates_small_bagwell_positions():
    bagwell = _position(
        "0x9c76cdb43fb46454da005fbc82047a64a18ec926",
        "Bagwell306",
        amount=1249.99,
        condition_id="0xbagwell-small",
        minimum_position_units=0.2,
        actionable_position_units=0.5,
    )
    qualifying = _position(
        "0x9c76cdb43fb46454da005fbc82047a64a18ec926",
        "Bagwell306",
        amount=1250,
        condition_id="0xbagwell-qualifying",
        minimum_position_units=0.2,
        actionable_position_units=0.5,
    )
    plays = build_trades_to_play(
        [bagwell, qualifying],
        unit_map={
            "0x9c76cdb43fb46454da005fbc82047a64a18ec926": {
                "estimated_base_unit": 2500
            }
        },
        now=_now(),
    )

    assert {play["canonical_market_key"] for play in plays} == {"0xbagwell-qualifying"}
    assert plays[0]["primary_trader"]["relative_units"] == 0.5


def test_units_are_based_on_dollars_not_share_count():
    same_shares_low_price = _position(
        "0xa",
        "Bagwell306",
        amount=2425,
        shares=5000,
        condition_id="0xshares-low",
    )
    same_shares_high_price = _position(
        "0xb",
        "Bagwell306",
        amount=3895,
        shares=5000,
        condition_id="0xshares-high",
    )
    plays = build_trades_to_play(
        [same_shares_low_price, same_shares_high_price],
        unit_map={
            "0xa": {"estimated_base_unit": 2500},
            "0xb": {"estimated_base_unit": 2500},
        },
        now=_now(),
    )
    units_by_market = {
        play["canonical_market_key"]: play["primary_trader"]["relative_units"]
        for play in plays
    }

    assert units_by_market["0xshares-low"] == 0.97
    assert units_by_market["0xshares-high"] == 1.558
    assert units_by_market["0xshares-low"] != units_by_market["0xshares-high"]


def test_failed_wallets_do_not_count_toward_unanimous_consensus():
    positions = [
        _position("0xa", "A", amount=500),
        _position("0xb", "B", amount=600),
    ]
    plays = build_trades_to_play(
        positions,
        unit_map=_unit_map("0xa", "0xb"),
        tracked_wallet_count=2,
        now=_now(),
    )
    assert plays[0]["confidence_score"] == 100

    not_ready_plays = build_trades_to_play(
        positions,
        unit_map=_unit_map("0xa", "0xb"),
        tracked_wallet_count=3,
        now=_now(),
    )
    assert not_ready_plays[0]["confidence_score"] < 100


def test_two_supporting_sharps_create_non_category_research_trade():
    lead = _position("0xa", "Lead", configured_top_category="MLB")
    supporting = _position(
        "0xb", "Supporting", configured_top_category="Tennis"
    )
    other_supporting = _position(
        "0xc", "Other Supporting", configured_top_category="Soccer"
    )
    unit_map = _unit_map("0xa", "0xb", "0xc")

    lead_only = build_trades_to_play([lead], unit_map=unit_map, now=_now())
    supporting_only = build_trades_to_play(
        [supporting], unit_map=unit_map, now=_now()
    )
    supporting_pair = build_trades_to_play(
        [supporting, other_supporting], unit_map=unit_map, now=_now()
    )
    mixed = build_trades_to_play(
        [lead, supporting], unit_map=unit_map, now=_now()
    )

    assert lead_only[0]["lead_sharp_count"] == 1
    assert supporting_only == []
    assert supporting_pair[0]["tradeClassification"] == "SHARP_NON_CATEGORY"
    assert supporting_pair[0]["primary_trader"]["sharp_role"] == "Research Anchor"
    assert mixed[0]["raw_sharp_count"] == 2
    assert mixed[0]["lead_sharp_count"] == 1
    assert mixed[0]["supporting_sharp_count"] == 1
    assert mixed[0]["weighted_sharp_count"] == 1.5


def test_missing_top_category_cannot_create_a_lead_sharp():
    unresolved = _position(
        "0xa",
        "Unresolved",
        configured_top_category=None,
        top_category=None,
    )

    assert (
        build_trades_to_play(
            [unresolved], unit_map=_unit_map("0xa"), now=_now()
        )
        == []
    )


def test_supporting_wallet_keeps_raw_amount_but_uses_half_weighted_signals():
    lead = _position(
        "0xa", "Lead", amount=1000, configured_top_category="MLB"
    )
    supporting = _position(
        "0xb", "Supporting", amount=6000, configured_top_category="Tennis"
    )
    play = build_trades_to_play(
        [lead, supporting],
        unit_map=_unit_map("0xa", "0xb"),
        now=_now(),
    )[0]
    wallets = {wallet["wallet_label"]: wallet for wallet in play["supporting_wallets"]}

    assert play["combined_exposure_exact"] == 7000
    assert play["evidence_inputs"]["actual_combined_amount"] == 7000
    assert play["evidence_inputs"]["weighted_combined_amount"] == 4000
    assert wallets["Supporting"]["amount"] == 6000
    assert wallets["Supporting"]["category_weight"] == 0.5
    assert wallets["Supporting"]["weighted_amount_contribution"] == 3000


def test_primary_trader_is_always_selected_from_lead_sharps():
    lead = _position(
        "0xa", "Lead", amount=1000, configured_top_category="MLB"
    )
    larger_supporting = _position(
        "0xb", "Larger Supporting", amount=9000, configured_top_category="Tennis"
    )
    play = build_trades_to_play(
        [lead, larger_supporting],
        unit_map=_unit_map("0xa", "0xb"),
        now=_now(),
    )[0]

    assert play["primary_trader"]["wallet_label"] == "Lead"
    assert play["primary_trader"]["is_lead_sharp"] is True
    assert {wallet["wallet_label"] for wallet in play["supporting_wallets"]} == {
        "Lead",
        "Larger Supporting",
    }


def test_lead_and_supporting_composition_controls_ranking_inside_raw_bands():
    positions = [
        _position("0xa", "Full A", condition_id="0xfull2", amount=1000),
        _position("0xb", "Full B", condition_id="0xfull2", amount=1000),
        _position("0xc", "Mixed Lead", condition_id="0xmixed2", amount=1000),
        _position(
            "0xd",
            "Mixed Supporting",
            condition_id="0xmixed2",
            amount=1000,
            configured_top_category="Tennis",
        ),
        _position("0xe", "Single Lead", condition_id="0xsingle", amount=1000),
    ]
    plays = build_trades_to_play(
        positions,
        unit_map=_unit_map("0xa", "0xb", "0xc", "0xd", "0xe"),
        tracked_wallet_count=6,
        now=_now(),
    )
    by_market = {play["canonical_market_key"]: play for play in plays}

    assert by_market["0xfull2"]["confidence_score"] > by_market["0xmixed2"][
        "confidence_score"
    ]
    assert by_market["0xmixed2"]["confidence_score"] > by_market["0xsingle"][
        "confidence_score"
    ]
    assert 70 <= by_market["0xmixed2"]["confidence_score"] <= 79


def test_three_leads_rank_above_two_leads_plus_supporting():
    positions = [
        _position("0xa", "A", condition_id="0xfull3"),
        _position("0xb", "B", condition_id="0xfull3"),
        _position("0xc", "C", condition_id="0xfull3"),
        _position("0xd", "D", condition_id="0xmixed3"),
        _position("0xe", "E", condition_id="0xmixed3"),
        _position(
            "0xf",
            "F",
            condition_id="0xmixed3",
            configured_top_category="Tennis",
        ),
    ]
    plays = build_trades_to_play(
        positions,
        unit_map=_unit_map("0xa", "0xb", "0xc", "0xd", "0xe", "0xf"),
        tracked_wallet_count=7,
        now=_now(),
    )
    by_market = {play["canonical_market_key"]: play for play in plays}

    assert by_market["0xfull3"]["confidence_score"] > by_market["0xmixed3"][
        "confidence_score"
    ]
    assert by_market["0xmixed3"]["confidence_score"] >= 80
    assert by_market["0xmixed3"]["weighted_sharp_count"] == 2.5


def test_opposing_supporting_wallet_creates_majority_research_trade():
    lead = _position(
        "0xa", "Lead", outcome="Yankees", configured_top_category="MLB"
    )
    supporting_agreement = _position(
        "0xb",
        "Supporting",
        outcome="Yankees",
        configured_top_category="Tennis",
    )
    opposing = _position(
        "0xc",
        "Opposing Supporting",
        outcome="Red Sox",
        configured_top_category="Soccer",
    )

    plays = build_trades_to_play(
        [lead, supporting_agreement, opposing],
        unit_map=_unit_map("0xa", "0xb", "0xc"),
        now=_now(),
    )
    assert plays[0]["tradeClassification"] == "CONTRADICTING_SHARPS"
    assert plays[0]["rawAgreeingSharpCount"] == 2
    assert plays[0]["rawContradictingSharpCount"] == 1


def test_complete_raw_agreement_scores_one_hundred_when_a_lead_exists():
    positions = [
        _position("0xa", "Lead", configured_top_category="MLB"),
        _position("0xb", "Supporting", configured_top_category="Tennis"),
    ]
    play = build_trades_to_play(
        positions,
        unit_map=_unit_map("0xa", "0xb"),
        tracked_wallet_count=2,
        now=_now(),
    )[0]

    assert play["confidence_score"] == 100
    assert play["lead_sharp_count"] == 1
    assert play["supporting_sharp_count"] == 1
    assert play["weighted_sharp_count"] == 1.5
    assert play["score_breakdown"]["category_composition"] == 0.75


@pytest.mark.parametrize(
    ("category", "league"),
    (("MLB", "MLB"), ("Soccer", "Premier League")),
)
def test_primary_and_sub_top_categories_are_full_weight_lead_sharps(
    category, league
):
    wallet = "0xf1528f12e645462c344799b62b1b421a6a4c64aa"
    position = _position(
        wallet,
        "phonesculptor",
        category=category,
        league=league,
        configured_top_category="MLB",
        configured_top_category_ids=["MLB", "Soccer"],
        configured_sub_top_categories=["Soccer"],
        configured_sub_top_category_ids=["Soccer"],
    )

    play = build_trades_to_play(
        [position], unit_map=_unit_map(wallet), now=_now()
    )[0]
    sharp = play["supporting_wallets"][0]

    assert play["lead_sharp_count"] == 1
    assert play["supporting_sharp_count"] == 0
    assert sharp["is_lead_sharp"] is True
    assert sharp["sharp_role"] == "Lead Sharp"
    assert sharp["category_weight"] == 1.0
    assert sharp["top_category"] == "MLB"
    assert sharp["sub_top_categories"] == ["Soccer"]


def test_unconfigured_category_does_not_become_a_phonesculptor_lead():
    wallet = "0xf1528f12e645462c344799b62b1b421a6a4c64aa"
    position = _position(
        wallet,
        "phonesculptor",
        category="Tennis",
        league="ATP",
        configured_top_category="MLB",
        configured_top_category_ids=["MLB", "Soccer"],
        configured_sub_top_categories=["Soccer"],
        configured_sub_top_category_ids=["Soccer"],
    )
    diagnostics = []

    assert build_trades_to_play(
        [position],
        unit_map=_unit_map(wallet),
        now=_now(),
        diagnostics=diagnostics,
    ) == []
    assert diagnostics[0]["reason"] == "SINGLE_NON_CATEGORY_WALLET"


def test_0x4f2_is_mlb_lead_but_never_a_tennis_lead():
    wallet = "0x4f29e103339919c4baaea2a60195cf1c8bb27a7e"
    mlb = _position(
        wallet,
        "0x4f2",
        configured_top_category="MLB",
        configured_top_category_ids=["MLB"],
    )
    tennis = _position(
        wallet,
        "0x4f2",
        category="Tennis",
        league="WTA",
        configured_top_category="MLB",
        configured_top_category_ids=["MLB"],
    )
    diagnostics = []

    assert build_trades_to_play([mlb], unit_map=_unit_map(wallet), now=_now())
    assert (
        build_trades_to_play(
            [tennis],
            unit_map=_unit_map(wallet),
            now=_now(),
            diagnostics=diagnostics,
        )
        == []
    )
    assert diagnostics[0]["reason"] == "SINGLE_NON_CATEGORY_WALLET"
    assert diagnostics[0]["canonical_category_id"] == "tennis"


def test_0x4f2_remains_half_weight_supporting_behind_a_tennis_lead():
    wallet = "0x4f29e103339919c4baaea2a60195cf1c8bb27a7e"
    tennis_lead = _position(
        "0xtennis",
        "Tennis Lead",
        amount=1000,
        category="Tennis",
        league="ATP",
        configured_top_category="Tennis",
    )
    supporting = _position(
        wallet,
        "0x4f2",
        amount=9000,
        category="Tennis",
        league="ATP",
        configured_top_category="MLB",
        configured_top_category_ids=["MLB"],
    )

    play = build_trades_to_play(
        [tennis_lead, supporting],
        unit_map=_unit_map("0xtennis", wallet),
        now=_now(),
    )[0]
    wallets = {item["wallet_label"]: item for item in play["supporting_wallets"]}

    assert play["primary_trader"]["wallet_label"] == "Tennis Lead"
    assert play["lead_sharp_count"] == 1
    assert play["supporting_sharp_count"] == 1
    assert wallets["0x4f2"]["is_lead_sharp"] is False
    assert wallets["0x4f2"]["category_weight"] == 0.5


def test_sharp_reference_uses_amount_weighted_leads_only():
    lead_a = _position("0xa", "Lead A", amount=1000, avg=0.4)
    lead_b = _position("0xb", "Lead B", amount=500, avg=0.5)
    tiny_support = _position(
        "0xc",
        "Tiny Supporting",
        amount=100,
        avg=0.1,
        configured_top_category="Tennis",
    )

    play = build_trades_to_play(
        [lead_a, lead_b, tiny_support],
        unit_map=_unit_map("0xa", "0xb", "0xc", base=100),
        now=_now(),
    )[0]

    assert play["sharp_reference_method"] == "amount_weighted_lead_sharps"
    assert play["sharp_reference_entry_price"] == pytest.approx(
        ((0.4 * 1000) + (0.5 * 500)) / 1500
    )
