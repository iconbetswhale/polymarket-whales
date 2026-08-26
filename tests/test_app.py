from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from config import Settings
from database import TrackerDatabase
from execution_providers import ProviderHealthStatus
from model_tracker_discord import DiscordDeliveryResult
from position_tracker import MODEL_TRACKER_USER_ID, TrackerService
from app import (
    _attach_historical_personal_sharps,
    _format_event_start,
    _has_positive_recommendation,
    _slippage_fraction,
    _trade_card_view,
    _wallet_roster_summary,
)
from three_sharp_strategy import SHARPS as THREE_SHARP_WALLETS


def test_historical_personal_sharp_backfill_requires_exact_earlier_snapshot():
    fill = {
        "canonical_event_id": "event-1",
        "canonical_market_id": "market-1",
        "market_line": "2.5",
        "canonical_outcome_id": "yes-token",
        "created_at": "2026-07-14T16:00:00+00:00",
        "sharp_snapshot_json": "{}",
    }
    matching_snapshot = {
        "canonical_event_id": "event-1",
        "canonical_market_id": "market-1",
        "market_line": 2.5,
        "outcome_id": "yes-token",
        "recommendation_timestamp": "2026-07-14T15:00:00+00:00",
        "primary_sharp": {"display_name": "Bagwell306", "wallet_address": "0xlead"},
        "agreeing_sharps": [
            {"display_name": "Bagwell306", "wallet_address": "0xlead"}
        ],
    }
    later_snapshot = {
        **matching_snapshot,
        "recommendation_timestamp": "2026-07-14T17:00:00+00:00",
        "primary_sharp": {"display_name": "Future Sharp", "wallet_address": "0xfuture"},
    }
    wrong_outcome = {
        **matching_snapshot,
        "outcome_id": "no-token",
        "primary_sharp": {"display_name": "Wrong Side", "wallet_address": "0xwrong"},
    }

    result = _attach_historical_personal_sharps(
        [fill],
        [
            {"snapshot": matching_snapshot},
            {"snapshot": later_snapshot},
            {"snapshot": wrong_outcome},
        ],
    )

    assert result[0]["sharp_snapshot"]["primary_sharp"]["display_name"] == "Bagwell306"
    assert result[0]["sharp_snapshot"]["sharp_source_status"] == "historical_signal_backfill"


def test_historical_personal_sharp_backfill_never_guesses_without_exact_identity():
    fill = {
        "canonical_event_id": "event-1",
        "canonical_market_id": "market-1",
        "market_line": "2.5",
        "canonical_outcome_id": "yes-token",
        "created_at": "2026-07-14T16:00:00+00:00",
        "sharp_snapshot_json": "{}",
    }
    unrelated = {
        "canonical_event_id": "event-1",
        "canonical_market_id": "different-market",
        "market_line": 2.5,
        "outcome_id": "yes-token",
        "recommendation_timestamp": "2026-07-14T15:00:00+00:00",
        "primary_sharp": {"display_name": "Wrong Sharp", "wallet_address": "0xwrong"},
    }

    result = _attach_historical_personal_sharps([fill], [{"snapshot": unrelated}])

    assert "sharp_snapshot" not in result[0]


def test_wallet_cards_show_complete_category_and_profile_fields():
    script = Path("static/app.js").read_text(encoding="utf-8")

    for label in (
        "Sub-top categories",
        "Sub-category record",
        "Category record",
        "Adjusted hit rate",
        "Category P/L",
        "Category source",
        "Half unit",
        "Actionable exposure",
        "Type",
        "Selectivity",
        "Hold",
        "Copyability",
        "Execution",
        "Strategy",
    ):
        assert f'walletMeta("{label}"' in script


def test_wallet_roster_summary_uses_audited_wallet_specific_metrics():
    row = _wallet_roster_summary(
        {
            "address": next(iter(THREE_SHARP_WALLETS)),
            "label": "Formal-Cupcake",
            "base_unit": 1300,
            "historical_position_count": 999,
            "wallet_forensics": {
                "corrected_roi": 0.1323,
                "corrected_win_rate": 0.4903,
                "settled_positions": 155,
                "stake_weighted_exchange_clv_probability": -0.00151,
                "exchange_clv_sample": 152,
            },
        }
    )

    assert row["is_active_sharp"] is True
    assert row["roster_summary"] == {
        "sport": "MLB",
        "provider": "Polymarket",
        "unit_size": 1300.0,
        "roi": 0.1323,
        "win_rate": 0.4903,
        "play_count": 155,
        "clv_probability_points": -0.00151,
        "clv_sample": 152,
        "clv_status": "CAPTURED",
        "clv_source": "Polymarket closing price",
    }


def test_wallet_api_separates_active_roster_from_preserved_hidden_wallets(
    app_client, monkeypatch
):
    service = app_client.application.extensions["tracker_service"]
    active_rows = [
        {
            "address": address,
            "label": config["label"],
            "base_unit": 1000,
            "wallet_forensics": {},
        }
        for address, config in reversed(list(THREE_SHARP_WALLETS.items()))
    ]
    hidden = {
        "address": "0x0000000000000000000000000000000000000001",
        "label": "Archived Sharp",
        "base_unit": 500,
        "wallet_forensics": {},
    }
    monkeypatch.setattr(
        service,
        "get_snapshot",
        lambda: {"wallets": [hidden, *active_rows], "status": {"ok": True}},
    )

    active_payload = app_client.get("/api/wallets").get_json()
    hidden_payload = app_client.get("/api/wallets?view=hidden").get_json()
    all_payload = app_client.get("/api/wallets?view=all").get_json()

    assert {row["address"] for row in active_payload["data"]} == set(
        THREE_SHARP_WALLETS
    )
    assert active_payload["view"] == "active"
    assert active_payload["active_total"] == len(THREE_SHARP_WALLETS)
    assert active_payload["hidden_total"] == 1
    assert [row["label"] for row in hidden_payload["data"]] == ["Archived Sharp"]
    assert hidden_payload["view"] == "hidden"
    assert len(all_payload["data"]) == len(THREE_SHARP_WALLETS) + 1


def test_wallet_roster_page_exposes_active_and_hidden_views():
    template = Path("templates/wallets.html").read_text(encoding="utf-8")
    script = Path("static/app.js").read_text(encoding="utf-8")

    assert 'data-wallet-view="active"' in template
    assert 'data-wallet-view="hidden"' in template
    assert "The three directional MLB wallets" in template
    assert "Polymarket CLV" in script
    assert 'view: walletRosterView' in script


def test_current_best_price_precedes_stale_selected_execution_snapshot():
    script = Path("static/app.js").read_text(encoding="utf-8")
    function_start = script.index("function bestExecutionOption(trade)")
    function_end = script.index("function executionVenueStack", function_start)
    function_source = script[function_start:function_end]

    assert function_source.index("if (ranked.length) return ranked[0]") < function_source.index(
        "const explicit = options.find"
    )
    assert function_source.index("const explicit = options.find") < function_source.index(
        "const selected = normalizeExecutionOption"
    )
    assert "EXECUTION_PRICE_TIE_TOLERANCE = 1e-3" in script
    assert 'canonicalExecutionProviderKey(left.providerKey) === "novig"' in function_source
    assert "option.canFillRecommendedStake === true" in function_source
    assert "number(option.availableLiquidity) === null || number(option.availableLiquidity) > 0" in function_source
    assert (
        'const supported = new Set(["polymarket", "4cx", "fourcx", "novig", "prophetx"]);'
        in function_source
    )
    assert '"oddsapi__novig"' in script


class CountingClient:
    def __init__(self):
        self.current_calls = []
        self.closed_calls = []

    def get_current_positions(self, wallet_address: str):
        self.current_calls.append(wallet_address)
        return []

    def get_closed_positions(self, wallet_address: str, limit: int = 50):
        self.closed_calls.append(wallet_address)
        return []

    def get_events(self, event_slugs, max_workers: int = 8):
        return {}

    def get_public_profile(self, wallet_address: str):
        return None


def _actionable_trade() -> dict:
    event_time = datetime.now(timezone.utc) + timedelta(days=1)
    return {
        "id": "market-1::outcome-a",
        "event_slug": "event-1",
        "event_title": "Spain vs France",
        "market_title": "To Advance",
        "market_line": None,
        "outcome": "Spain",
        "clob_token_id": "outcome-a",
        "event_date_et": event_time.isoformat(),
        "event_time_et": "Tomorrow, 3:00 PM ET",
        "market_url": "https://polymarket.com/event/example",
        "category": "Soccer",
        "canonical_category_id": "soccer",
        "canonical_sport_id": "soccer",
        "league": "World Cup",
        "sports_market_type": "to_advance",
        "search_blob": "spain france to-advance soccer world-cup sharp",
        "agreeing_wallet_count": 1,
        "raw_sharp_count": 1,
        "lead_sharp_count": 1,
        "supporting_sharp_count": 0,
        "weighted_sharp_count": 1.0,
        "has_lead_sharp": True,
        "confidence_score": 90,
        "combined_exposure_exact": 2000,
        "average_entry_price": 0.4,
        "primary_trader": {
            "amount": 2000,
            "relative_units": 2,
            "wallet_label": "Sharp",
            "is_lead_sharp": True,
        },
        "supporting_wallets": [],
        "evidence_inputs": {"adjusted_category_hit_rate": 0.6},
        "validation_ids": {
            "event_id": "event-1",
            "condition_id": "market-1",
            "outcome_token_id": "outcome-a",
            "event_slug": "event-1",
            "market_slug": "market-1",
        },
        "orderbook": {},
    }


def _positive_recommendation(*_args, **_kwargs) -> dict:
    return {
        "available": True,
        "final_recommended_fraction": 0.01,
        "recommended_amount": 100,
        "recommended_units": 1,
        "recommended_shares": 250,
        "current_user_entry_price": 0.4,
        "effective_entry_price": 0.4,
        "current_top_ask_price": 0.4,
        "sharp_average_entry_price": 0.4,
        "sharp_reference_entry_price": 0.4,
        "slippage_cents": 0,
        "price_slippage_fraction": 0,
        "unfavorable_slippage_pct": 0,
        "passes_slippage_rule": True,
        "slippage_rejection_reason": None,
    }


def _positive_evaluation(play: dict, *_args, **_kwargs) -> dict:
    return {
        "play": play,
        "recommendation": _positive_recommendation(),
        "model_tracker_eligible": False,
        "model_tracker_rejection_reason": "NOT_TODAY",
        "recommendation_snapshot_id": "snapshot-id",
        "recommendation_idempotency_key": "dedupe-key",
    }


def _evaluation_at(entry: float, *, passes: bool = True, reason: str | None = None):
    def evaluate(play: dict, *_args, **_kwargs) -> dict:
        recommendation = {
            **_positive_recommendation(),
            "current_user_entry_price": entry,
            "effective_entry_price": entry,
            "current_top_ask_price": entry,
            "unfavorable_slippage_pct": ((entry - 0.4) / 0.4) * 100,
            "passes_slippage_rule": passes,
            "slippage_rejection_reason": reason,
        }
        return {
            "play": play,
            "recommendation": recommendation,
            "model_tracker_eligible": False,
            "model_tracker_rejection_reason": "NOT_TODAY",
            "recommendation_snapshot_id": "snapshot-id",
            "recommendation_idempotency_key": f"dedupe-{entry}",
        }

    return evaluate


def test_health_endpoint(app_client):
    response = app_client.get("/health")
    assert response.status_code == 200
    payload = response.get_json()
    assert "app_status" in payload
    assert "database_status" in payload


def test_positive_ev_is_paused_before_any_paid_provider_request(app_client):
    response = app_client.get("/api/positive-ev")

    assert response.status_code == 200
    assert response.get_json() == {
        "configured": False,
        "data": [],
        "message": (
            "Positive EV scanning is paused. No paid odds requests are being made."
        ),
        "paused": True,
        "refreshSeconds": 0,
        "total": 0,
    }


def test_positive_ev_preview_returns_ten_isolated_visual_rows(app_client):
    response = app_client.get("/api/positive-ev?preview=1")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["previewOnly"] is True
    assert payload["total"] == 10
    assert payload["refreshSeconds"] == 0
    assert len(payload["data"]) == 10
    assert all(row["previewOnly"] is True for row in payload["data"])
    assert all(
        row["calculationVersion"] == "ev-visual-preview-v2-devig"
        for row in payload["data"]
    )
    assert payload["devigMethod"] == "power"
    assert all(row["devigMethod"] == "power" for row in payload["data"])
    assert all(len(row["sourceBooks"]) == 5 for row in payload["data"])
    assert {
        source["bookKey"] for source in payload["data"][0]["sourceBooks"]
    } == {
        "pinnacle",
        "circa",
        "bookmakereu",
        "betfairexchange",
        "fanduel",
    }

    sized_response = app_client.get(
        "/api/positive-ev",
        query_string={"preview": 1, "bankroll": 20_000},
    )
    assert sized_response.status_code == 200
    sized_payload = sized_response.get_json()
    assert sized_payload["bankroll"] == 20_000
    assert sized_payload["data"][0]["recommendedStake"] == pytest.approx(
        payload["data"][0]["recommendedStake"] * 2
    )
    assert sized_payload["data"][0]["kellyFraction"] == pytest.approx(
        payload["data"][0]["kellyFraction"]
    )

    filtered_response = app_client.get(
        "/api/positive-ev",
        query_string={
            "preview": 1,
            "sports": "baseball_mlb,basketball_wnba",
            "markets": "h2h,spreads",
        },
    )
    assert filtered_response.status_code == 200
    filtered_payload = filtered_response.get_json()
    assert filtered_payload["total"] == 2
    assert {row["marketKey"] for row in filtered_payload["data"]} == {
        "h2h",
        "spreads",
    }

    additive_response = app_client.get(
        "/api/positive-ev", query_string={"preview": 1, "devig_method": "additive"}
    )
    assert additive_response.status_code == 200
    additive_payload = additive_response.get_json()
    assert additive_payload["devigMethod"] == "additive"
    assert all(row["devigMethod"] == "additive" for row in additive_payload["data"])
    assert additive_payload["data"][0]["fairProbability"] != payload["data"][0]["fairProbability"]
    assert additive_payload["data"][0]["evPercent"] != payload["data"][0]["evPercent"]

    invalid_response = app_client.get(
        "/api/positive-ev", query_string={"preview": 1, "devig_method": "unsupported"}
    )
    assert invalid_response.status_code == 400
    assert invalid_response.get_json()["error"] == "INVALID_DEVIG_METHOD"

    required_available = app_client.get(
        "/api/positive-ev",
        query_string={"preview": 1, "required_books": "pinnacle,novig"},
    ).get_json()
    assert required_available["total"] == 10
    assert required_available["requiredBooks"] == ["pinnacle", "novig"]

    required_missing = app_client.get(
        "/api/positive-ev",
        query_string={"preview": 1, "required_books": "bet365"},
    ).get_json()
    assert required_missing["total"] == 0

    invalid_required_book = app_client.get(
        "/api/positive-ev",
        query_string={"preview": 1, "required_books": "not-a-book"},
    )
    assert invalid_required_book.status_code == 400
    assert invalid_required_book.get_json()["error"] == "INVALID_REQUIRED_BOOK"


def test_positive_ev_page_uses_live_85_book_catalog(app_client):
    response = app_client.get("/positive-ev")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'id="ev-config"' in body
    assert '"catalogVersion": 3' in body
    assert '"name": "Pinnacle"' in body
    assert '"name": "theScore Bet"' in body
    assert '"devigBooks"' in body
    assert "Devig Source Allocation" in body
    assert "Devig Method" in body
    assert 'role="radiogroup" aria-label="Devig Method"' in body
    assert 'name="devig-method" value="power" checked' in body
    assert 'name="devig-method" value="additive"' in body
    assert 'name="devig-method" value="multiplicative"' in body
    assert 'name="devig-method" value="shin"' in body
    assert "Positive EV Filter" in body
    assert 'id="ev-bankroll-popover-button"' in body
    assert 'id="ev-bankroll-toolbar-value"' in body
    assert 'id="ev-unit-toolbar-value"' in body
    assert 'id="ev-more-menu-toggle"' in body
    assert 'id="ev-more-menu"' in body
    assert 'id="ev-active-filter-count"' in body
    assert "Refresh opportunities" in body
    assert "Automatic refresh" in body
    assert 'data-market-group="main"' in body
    assert 'data-market-group="props"' in body
    assert 'data-market-group="alternate"' in body
    assert 'data-market-group-toggle="main"' in body
    assert 'data-market-group-toggle="props"' in body
    assert 'data-market-group-toggle="alternate"' in body
    assert 'data-market-group-count="props">0/43<' in body
    assert body.count('data-market-sport="baseball_mlb"') == 21
    assert body.count('data-market-sport="basketball_wnba"') == 22
    assert 'data-market-key="batter_total_bases"' in body
    assert 'data-market-key="batter_hits_runs_rbis"' in body
    assert 'data-market-key="batter_runs_rbis"' in body
    assert 'data-market-key="pitcher_pitches_thrown"' in body
    assert 'data-market-key="player_points_q1"' in body
    assert 'data-market-key="player_blocks_steals"' in body
    assert 'data-market-key="player_field_goals_attempted"' in body
    assert 'data-market-key="player_double_double"' in body
    assert 'data-market-key="alternate_totals"' in body
    assert "Selecting props or alternates" not in body
    assert "Multiplicative" in body
    assert "Opportunity thresholds" in body
    assert ">Min EV<" in body
    assert ">Kelly Multiplier<" in body
    assert ">Min # of Books<" in body
    assert "Required Books" in body
    assert 'id="ev-required-books-control"' in body
    assert 'id="ev-required-books-list"' in body
    assert 'id="ev-bankroll"' not in body
    assert 'id="ev-max-quote-age"' not in body
    assert 'id="ev-max-dispersion"' not in body
    assert 'id="ev-max-stake-pct"' not in body
    assert 'id="ev-max-event-pct"' not in body
    assert '"previewOnly": true' in body
    positive_ev_javascript = Path("static/positive-ev.js").read_text(
        encoding="utf-8"
    )
    assert "WHY IS THIS +EV?" in positive_ev_javascript
    assert "SHARP ODDS USED FOR FAIR VALUE" in positive_ev_javascript
    assert '<details class="ev-section ev-detail-accordion' in positive_ev_javascript
    assert "${marketOddsVisual(row)}" in positive_ev_javascript
    assert 'class="ev-track-button' in positive_ev_javascript
    assert 'class="ev-card-open"' in positive_ev_javascript
    assert 'fetch("/api/positive-ev/personal-bets"' in positive_ev_javascript
    assert "Rec Bet" in positive_ev_javascript
    assert 'class="ev-matchup-line"' in positive_ev_javascript
    assert "matchup(row)" in positive_ev_javascript
    assert 'class="ev-matchup-inline"' in positive_ev_javascript
    assert 'class="ev-team-logo"' in positive_ev_javascript
    assert "Total payout" in positive_ev_javascript
    assert "quotePayout(row.recommendedStake, quote)" in positive_ev_javascript
    assert "fullSelection(row)" in positive_ev_javascript
    assert "sportIcon(row)" in positive_ev_javascript
    assert 'return "ph-baseball"' in positive_ev_javascript
    assert 'return "ph-basketball"' in positive_ev_javascript
    assert 'return "ph-tennis-ball"' in positive_ev_javascript
    assert "iconlabs-ev-hidden-opportunities" in positive_ev_javascript
    assert 'event.submitter?.id === "ev-tracker-hide-submit"' in positive_ev_javascript
    assert "iconlabs-ev-tracked-opportunities" in positive_ev_javascript
    assert 'requestJson("/api/user-settings")' in positive_ev_javascript
    assert 'bankroll:bankrollConfig.amount' in positive_ev_javascript
    assert "loadBankrollSettings().finally(()=>load(true))" in positive_ev_javascript
    assert 'class="ev-book-option"' in positive_ev_javascript
    assert 'class="ev-book-name"' in positive_ev_javascript
    positive_ev_premium_css = Path("static/app-premium.css").read_text(
        encoding="utf-8"
    )
    assert (
        "grid-template-columns: minmax(0, 1fr) 550px !important"
        in positive_ev_premium_css
    )
    assert "width: calc(100% + 14px) !important" in positive_ev_premium_css
    assert "width: 550px !important" in positive_ev_premium_css
    assert "max-width: none !important" in positive_ev_premium_css
    assert "container-name: ev-play-feed" in positive_ev_premium_css
    assert "@container ev-play-feed (min-width: 680px)" in positive_ev_premium_css
    assert 'grid-template-areas: "score event pick execution" !important' in positive_ev_premium_css
    assert "grid-template-areas:" in positive_ev_premium_css
    assert ".ev-detail-accordion[open] > summary" in positive_ev_premium_css
    assert (
        "grid-template-columns: minmax(78px, 1fr) auto "
        "minmax(78px, auto) !important"
        in positive_ev_premium_css
    )
    assert "width: 22px !important" in positive_ev_premium_css
    assert "transform: translateY(3px)" in positive_ev_premium_css
    assert (
        "grid-template-columns: minmax(88px, 1fr) 164px 94px !important"
        in positive_ev_premium_css
    )
    assert "grid-template-columns: 70px 90px !important" in positive_ev_premium_css
    assert "align-items: center;\n  text-align: center;" in positive_ev_premium_css
    assert "width: 94px !important" in positive_ev_premium_css
    assert "grid-template-columns: 24px auto !important" in positive_ev_premium_css
    assert "justify-content: center !important" in positive_ev_premium_css
    assert "width: 24px !important" in positive_ev_premium_css
    assert (
        "grid-template-columns: 90px minmax(235px, 1.35fr) "
        "minmax(150px, 1fr) minmax(316px, 2.1fr) !important"
        in positive_ev_premium_css
    )
    assert "@container ev-play-feed (min-width: 910px)" in positive_ev_premium_css
    assert (
        "grid-template-columns: 202px minmax(186px, 1.35fr) "
        "minmax(120px, 1fr) minmax(401px, 2.1fr) !important"
        in positive_ev_premium_css
    )
    assert (
        "#ev-feed .ev-score strong {\n    flex: 0 0 auto;"
        in positive_ev_premium_css
    )
    assert "font-size: 30px !important" in positive_ev_premium_css
    assert "flex-direction: row !important" in positive_ev_premium_css
    assert "gap: 12px !important" in positive_ev_premium_css
    assert "flex: 0 0 72px" in positive_ev_premium_css
    assert "font-size: 20px !important" in positive_ev_premium_css
    assert "padding-left: 14px !important" in positive_ev_premium_css
    assert "overflow-wrap: normal !important" in positive_ev_premium_css
    assert "display: inline-block !important" in positive_ev_premium_css
    assert (
        "#ev-feed .ev-pick > strong {\n  font-size: 18px !important"
        in positive_ev_premium_css
    )
    assert (
        "#ev-feed .ev-bet-metric small {\n  font-size: 10px !important"
        in positive_ev_premium_css
    )
    assert (
        "#ev-feed .ev-bet-metric strong {\n  font-size: 16px !important"
        in positive_ev_premium_css
    )
    assert (
        "#ev-feed .ev-best-button > span:not(.ev-book-mark) {\n"
        "  font-size: 16px !important"
        in positive_ev_premium_css
    )

    assert 'id="ev-tracker-dialog"' in body
    assert 'id="ev-tracker-hide-submit"' in body
    assert "Track a sportsbook bet" in body
    assert "Track and Hide" in body
    assert "Bet Tracker and LabTracker" in body

    preview_response = app_client.get("/positive-ev?preview=1")
    assert preview_response.status_code == 200
    assert '"previewOnly": true' in preview_response.get_data(as_text=True)

    live_response = app_client.get("/positive-ev?preview=0")
    assert live_response.status_code == 200
    assert '"previewOnly": false' in live_response.get_data(as_text=True)


def test_positive_ev_live_scan_prefers_sports_game_odds(
    app_client, temp_settings, monkeypatch
):
    object.__setattr__(temp_settings, "positive_ev_enabled", True)
    object.__setattr__(temp_settings, "novig_api_key", "all-lines-key")
    registry = app_client.application.extensions["execution_providers"]
    provider = next(
        item for item in registry.providers if item.provider_key == "novig"
    )
    provider.api_key = "all-lines-key"
    calls = []

    def ev_events(*, sport_keys, market_keys):
        calls.append((tuple(sport_keys), tuple(market_keys)))
        return []

    monkeypatch.setattr(provider, "ev_events", ev_events)
    monkeypatch.setattr(
        provider,
        "diagnostics",
        lambda authenticate=False: {
            "provider": "sports_game_odds",
            "quota": {},
        },
    )

    response = app_client.get("/api/positive-ev")

    assert response.status_code == 200
    payload = response.get_json()
    assert calls == [
        (("baseball_mlb", "basketball_wnba"), ("h2h", "spreads", "totals"))
    ]
    assert payload["dataSource"] == "sports_game_odds"
    assert set(payload["sourceWeights"]) == {
        "pinnacle",
        "circa",
        "bookmakereu",
        "fanduel",
        "betfairexchange",
    }
    assert sum(payload["sourceWeights"].values()) == 100.0
    assert payload["devigMethod"] == "power"
    assert payload["minimumFairSources"] == 3
    assert "prizepicks" not in payload["executionBooks"]
    assert "pinnacle" in payload["executionBooks"]

    custom_response = app_client.get(
        "/api/positive-ev",
        query_string={
            "weights": json.dumps({"pinnacle": 100}),
            "min_sources": 5,
            "devig_method": "shin",
            "required_books": "pinnacle,circa",
        },
    )
    assert custom_response.status_code == 200
    custom_payload = custom_response.get_json()
    assert custom_payload["sourceWeights"] == {
        "pinnacle": 100.0,
        "circa": 0.0,
        "bookmakereu": 0.0,
        "fanduel": 0.0,
        "betfairexchange": 0.0,
    }
    assert custom_payload["minimumFairSources"] == 1
    assert custom_payload["devigMethod"] == "shin"
    assert custom_payload["requiredBooks"] == ["pinnacle", "circa"]

    custom_markets = app_client.get(
        "/api/positive-ev",
        query_string={
            "group": "custom",
            "markets": "h2h,batter_total_bases,alternate_totals",
        },
    )
    assert custom_markets.status_code == 200
    assert calls[-1] == (
        ("baseball_mlb", "basketball_wnba"),
        ("h2h", "batter_total_bases", "alternate_totals"),
    )

    expanded_props = app_client.get(
        "/api/positive-ev",
        query_string={
            "group": "custom",
            "markets": (
                "batter_hits_runs_rbis,pitcher_pitches_thrown,"
                "player_points_q1,player_blocks_steals,player_double_double"
            ),
        },
    )
    assert expanded_props.status_code == 200
    assert calls[-1] == (
        ("baseball_mlb", "basketball_wnba"),
        (
            "batter_hits_runs_rbis",
            "pitcher_pitches_thrown",
            "player_points_q1",
            "player_blocks_steals",
            "player_double_double",
        ),
    )

    missing_custom_markets = app_client.get(
        "/api/positive-ev", query_string={"group": "custom"}
    )
    assert missing_custom_markets.status_code == 400
    assert missing_custom_markets.get_json()["error"] == "INVALID_MARKETS"

    bad_total = app_client.get(
        "/api/positive-ev",
        query_string={"weights": json.dumps({"pinnacle": 99})},
    )
    assert bad_total.status_code == 400
    assert bad_total.get_json()["error"] == "INVALID_DEVIG_ALLOCATION"
    assert bad_total.get_json()["totalPercent"] == 99.0

    bad_source = app_client.get(
        "/api/positive-ev",
        query_string={
            "weights": json.dumps({"pinnacle": 100, "draftkings": 0})
        },
    )
    assert bad_source.status_code == 400
    assert bad_source.get_json()["error"] == "INVALID_DEVIG_SOURCE"
    assert len(calls) == 4


def test_app_starts_with_no_enabled_wallets(tmp_path):
    wallets_file = tmp_path / "wallets.json"
    wallets_file.write_text(
        json.dumps(
            [
                {
                    "address": "REPLACE_WITH_WALLET_ADDRESS",
                    "label": "Trader 1",
                    "enabled": False,
                    "base_unit": None,
                    "notes": "",
                }
            ]
        ),
        encoding="utf-8",
    )
    settings = Settings(
        dashboard_refresh=120,
        dashboard_port=5000,
        wallets_file=wallets_file,
        database_path=tmp_path / "tracker.db",
        sports_only=True,
        resolve_hours=168,
        min_american_odds=None,
        max_american_odds=None,
        request_timeout=15,
        max_retries=1,
        admin_password=None,
    )
    client = CountingClient()
    service = TrackerService(
        settings,
        client=client,
        database=TrackerDatabase(settings.database_path),
        auto_start=False,
    )
    service.refresh()
    snapshot = service.get_snapshot()
    assert snapshot["status"]["enabled_wallet_count"] == 0
    assert client.current_calls == []


def test_status_endpoints(app_client):
    assert app_client.get("/api/positions").status_code == 200
    assert app_client.get("/api/wallets").status_code == 200
    assert app_client.get("/api/trades").status_code == 200
    assert app_client.get("/api/trades-to-play").status_code == 200
    assert app_client.get("/api/history?page=1&per_page=25").status_code == 200
    assert app_client.get("/api/consensus").status_code == 200
    assert app_client.get("/api/unit-analysis").status_code == 404
    assert app_client.get("/api/status").status_code == 200
    assert app_client.get("/api/user-settings").status_code == 200
    assert app_client.get("/api/bet-tracker").status_code == 200
    assert app_client.get("/api/model-tracker").status_code == 200
    assert app_client.get("/api/personal-tracker").status_code == 200
    assert app_client.get("/api/provider-health/prophetx").status_code == 200


def test_versioned_static_assets_skip_auth_and_are_immutable(
    app_client, monkeypatch
):
    service = app_client.application.extensions["tracker_service"]
    monkeypatch.setattr(
        service.database,
        "get_auth_session",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("static assets must not open the auth store")
        ),
    )
    app_client.set_cookie("iconbets_session", "stale-session")

    response = app_client.get("/static/app.js?v=build-123")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == (
        "public, max-age=31536000, immutable"
    )
    assert "iconbets_user" not in response.headers.get("Set-Cookie", "")


def test_public_startup_routes_do_not_wait_for_auth_store(app_client, monkeypatch):
    service = app_client.application.extensions["tracker_service"]
    monkeypatch.setattr(
        service.database,
        "get_auth_session",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("public startup routes must not open the auth store")
        ),
    )
    app_client.set_cookie("iconbets_session", "stale-session")

    assert app_client.get("/trades").status_code == 200
    assert app_client.get("/sharp-money").status_code == 200
    assert app_client.get("/api/trades-to-play?fast=1").status_code == 200
    assert app_client.get("/api/sharp-money/live").status_code == 200


def test_trades_to_play_fast_mode_returns_snapshot_without_blocking_live_quotes(
    app_client, monkeypatch
):
    service = app_client.application.extensions["tracker_service"]
    providers = app_client.application.extensions["execution_providers"]
    monkeypatch.setattr(
        service,
        "get_snapshot",
        lambda: (_ for _ in ()).throw(
            AssertionError("fast mode must not refresh a stale snapshot")
        ),
    )
    monkeypatch.setattr(
        providers,
        "attach_options",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("fast mode must not wait for provider quotes")
        ),
    )

    response = app_client.get("/api/trades-to-play?fast=1")

    assert response.status_code == 200
    assert response.get_json()["fastMode"] is True


def test_tracker_service_serverless_start_does_not_refresh_providers(
    app_client, monkeypatch
):
    service = app_client.application.extensions["tracker_service"]
    service._started = False
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setattr(
        service,
        "refresh",
        lambda: (_ for _ in ()).throw(
            AssertionError("serverless cold start must not refresh providers")
        ),
    )
    monkeypatch.setattr(
        service.database,
        "get_or_create_user_settings",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("fast mode must not wait for durable user settings")
        ),
    )
    monkeypatch.setattr(
        service.database,
        "get_tracker_records",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("fast mode must not wait for tracker records")
        ),
    )

    service.start()

    assert service._started is True


def test_wallet_page_and_api_require_configured_passcode(app_client, monkeypatch):
    app = app_client.application
    monkeypatch.setitem(app.config, "WALLET_PAGE_PASSCODE", "1010")
    monkeypatch.setitem(app.config, "WALLET_PAGE_LOCK_SECRET", "test-wallet-secret")
    client = app.test_client()

    locked_page = client.get("/wallets")
    locked_api = client.get("/api/wallets")
    wrong_code = client.post(
        "/wallets/unlock",
        data={"passcode": "9999", "next": "/wallets"},
    )

    assert locked_page.status_code == 302
    assert "/wallets/unlock" in locked_page.headers["Location"]
    assert locked_api.status_code == 401
    assert locked_api.get_json()["error"] == "WALLET_PAGE_LOCKED"
    assert wrong_code.status_code == 401

    unlocked = client.post(
        "/wallets/unlock",
        data={"passcode": "1010", "next": "/wallets"},
    )

    assert unlocked.status_code == 302
    assert unlocked.headers["Location"] == "/wallets"
    assert "HttpOnly" in unlocked.headers["Set-Cookie"]
    assert "SameSite=Strict" in unlocked.headers["Set-Cookie"]
    assert client.get("/wallets").status_code == 200
    assert client.get("/api/wallets").status_code == 200


def test_vercel_cron_can_run_model_tracker_with_bearer_secret(
    app_client, monkeypatch
):
    service = app_client.application.extensions["tracker_service"]
    settings = app_client.application.config["SETTINGS"]
    object.__setattr__(settings, "tracker_job_secret", "test-cron-secret")
    refreshes = []
    monkeypatch.setattr(service, "refresh", lambda: refreshes.append(True))

    unauthorized = app_client.get("/api/admin/model-tracker/reconcile")
    authorized = app_client.get(
        "/api/admin/model-tracker/reconcile",
        headers={"Authorization": "Bearer test-cron-secret"},
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert refreshes == [True]


def test_trades_javascript_keeps_placeholder_fixtures_out_of_production_bundle():
    javascript = (Path(__file__).parents[1] / "static" / "app.js").read_text(
        encoding="utf-8"
    )
    render_payload = javascript.split("function renderTradesPayload", 1)[1].split(
        "async function loadTrades", 1
    )[0]
    assert 'get("preview") === "trade"' not in render_payload
    assert "VisualPreviewTrade" not in javascript
    assert "visualPreviewTrade" not in javascript
    assert "isVisualPreview" not in javascript
    assert "visual-preview" not in javascript
    assert "Design preview" not in javascript
    assert "const incomingTrades = payload.data || []" in render_payload
    assert "mergeOfficialTrackedTrades" in render_payload
    assert "stabilizeTradeFeed" in render_payload
    for fixture_id in ("qa-trade-1", "qa-trade-2", "qa-trade-3", "qa-trade-4", "qa-trade-5"):
        assert fixture_id not in javascript


def test_trades_preview_populates_all_workspace_tabs_without_touching_live_apis(
    app_client,
):
    regular = app_client.get("/trades")
    preview = app_client.get("/trades?preview=1")

    assert regular.status_code == 200
    assert preview.status_code == 200
    assert b'data-trades-preview="false"' in regular.data
    assert b"trades-preview.js" not in regular.data
    assert b'data-trades-preview="true"' in preview.data
    assert b"trades-preview.js" in preview.data

    root = Path(__file__).parents[1]
    fixture_bundle = (root / "static" / "trades-preview.js").read_text(
        encoding="utf-8"
    )
    app_bundle = (root / "static" / "app.js").read_text(encoding="utf-8")

    trade_specs = fixture_bundle.split("const tradeSpecs = [", 1)[1].split("];", 1)[0]
    assert trade_specs.count("score:") == 10
    assert "tradeSpecs.map(makeTrade)" in fixture_bundle
    assert "openPositionSpecs.map(makeOpenPosition)" in fixture_bundle
    assert "closedPositionSpecs.map(makeClosedPosition)" in fixture_bundle
    assert "window.ICONLABS_TRADES_PREVIEW_DATA" in fixture_bundle
    assert "/api/" not in fixture_bundle
    assert "TRADES_PREVIEW_DATA.openPositions" in app_bundle
    assert "TRADES_PREVIEW_DATA.closedPositions" in app_bundle
    assert "Preview mode is read-only" in app_bundle


def test_prophetx_health_endpoint_returns_only_safe_status(app_client):
    registry = app_client.application.extensions["execution_providers"]
    provider = next(
        item for item in registry.providers if item.provider_key == "prophetx"
    )
    provider._access_key = "test-access"
    provider._secret_key = "test-secret"
    provider._health_status = ProviderHealthStatus.CONFIGURED

    class HealthResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"data": {"access_token": "temporary-session-token"}}

    class HealthSession:
        @staticmethod
        def post(*_args, **_kwargs):
            return HealthResponse()

    provider.session = HealthSession()
    settings = app_client.application.config["SETTINGS"]
    object.__setattr__(settings, "tracker_job_secret", "test-job-secret")

    configured = app_client.get("/api/provider-health/prophetx")
    unauthorized = app_client.post("/api/provider-health/prophetx")
    authenticated = app_client.post(
        "/api/provider-health/prophetx",
        headers={"Authorization": "Bearer test-job-secret"},
    )

    assert configured.get_json() == {"status": "configured"}
    assert unauthorized.status_code == 401
    assert unauthorized.get_json() == {"status": "unauthorized"}
    assert authenticated.get_json() == {"status": "authenticated"}
    combined = "".join(
        response.get_data(as_text=True)
        for response in (configured, unauthorized, authenticated)
    )
    assert "test-access" not in combined
    assert "test-secret" not in combined


def test_vercel_cron_runs_insider_reconciliation_every_minute():
    config = json.loads(
        (Path(__file__).resolve().parents[1] / "vercel.json").read_text(
            encoding="utf-8"
        )
    )

    assert {
        "path": "/api/admin/model-tracker/reconcile",
        "schedule": "* * * * *",
    } in config["crons"]


def test_sharp_money_live_page_is_available_and_paused_by_default(app_client):
    response = app_client.get("/sharp-money")

    assert response.status_code == 200
    assert b"Sharp Money" in response.data
    assert b"Feed paused" in response.data
    assert b"zero new requests" in response.data
    assert b"sharp-feed-toggle" in response.data
    assert b"sharp-sort" in response.data
    assert b"sharp-detail-toggle" in response.data
    assert b"sharp-money-initial-payload" not in response.data
    assert b"sharp-money-v2.css" in response.data


def test_sharp_money_cached_reads_never_touch_live_tracker_or_provider(
    app_client, monkeypatch
):
    service = app_client.application.extensions["tracker_service"]
    collector = app_client.application.extensions["sharp_money_collector"]
    lab_tracker = app_client.application.extensions["lab_tracker_service"]
    monkeypatch.setattr(
        service,
        "get_snapshot",
        lambda: (_ for _ in ()).throw(AssertionError("live tracker was called")),
    )
    monkeypatch.setattr(
        collector.prophetx,
        "live_market_snapshot",
        lambda: (_ for _ in ()).throw(AssertionError("provider was called")),
    )
    monkeypatch.setattr(
        lab_tracker,
        "observe_sharp_money",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("empty cached reads must not open the durable tracker")
        ),
    )

    page = app_client.get("/sharp-money")
    response = app_client.get("/api/sharp-money/live")
    payload = response.get_json()

    assert page.status_code == 200
    assert response.status_code == 200
    assert payload["mode"] == "paused"
    assert payload["paused"] is True
    assert payload["fabricatedData"] is False
    assert payload["executionEnabled"] is False
    assert payload["trackerWritesEnabled"] is False


def test_sharp_money_preview_returns_five_isolated_visual_signals(
    app_client, monkeypatch
):
    collector = app_client.application.extensions["sharp_money_collector"]
    lab_tracker = app_client.application.extensions["lab_tracker_service"]
    monkeypatch.setattr(
        collector,
        "payload",
        lambda: (_ for _ in ()).throw(AssertionError("collector was read")),
    )
    monkeypatch.setattr(
        lab_tracker,
        "observe_sharp_money",
        lambda *_: (_ for _ in ()).throw(AssertionError("tracker was written")),
    )

    response = app_client.get("/api/sharp-money/live?preview=1")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["previewOnly"] is True
    assert payload["trackerWritesEnabled"] is False
    assert payload["notificationsEnabled"] is False
    assert payload["executionEnabled"] is False
    assert payload["signalCount"] == 5
    assert len(payload["signals"]) == 5
    assert all(signal["previewOnly"] is True for signal in payload["signals"])
    assert {signal["market"]["kind"] for signal in payload["signals"]} == {
        "moneyline",
        "spread",
        "game_total",
    }
    for signal in payload["signals"]:
        pinnacle = next(
            row
            for row in signal["comparisonLines"]
            if row["providerKey"] == "pinnacle"
        )
        assert pinnacle["marketLimit"] > 0


def test_sharp_money_frontend_uses_explicit_control_gate():
    script = (
        Path(__file__).resolve().parents[1] / "static" / "sharp-money.js"
    ).read_text(encoding="utf-8")
    shell_script = (
        Path(__file__).resolve().parents[1] / "static" / "app.js"
    ).read_text(encoding="utf-8")

    assert '"/api/sharp-money/live"' in script
    assert '"/api/sharp-money/live?preview=1"' in script
    assert "fetch(endpoint" in script
    assert "state.placeholderSignals.length === 0" in script
    assert "state.payload.placeholderMode = true" in script
    assert "visual placeholder trades" in script
    assert 'fetch("/api/sharp-money/control"' in script
    assert 'control(state.payload?.running ? "pause" : "play")' in script
    assert "function combinedDepthLiquidity" in script
    assert 'title="Combined NoVIG + ProphetX liquidity"' in script
    assert "/api/odds-screen" not in script
    assert "active=1" not in script
    assert (
        'if (page !== "sharp-money") loadGlobalStatus();'
        in shell_script
    )


def test_sharp_money_combined_liquidity_keeps_decimal_for_even_thousands():
    script = (
        Path(__file__).resolve().parents[1] / "static" / "sharp-money.js"
    ).read_text(encoding="utf-8")

    assert "function liquidityMoney(value)" in script
    assert "(absolute / 1000).toFixed(1)" in script
    assert "liquidityMoney(combinedDepthLiquidity(signal))" in script


def test_sharp_money_frontend_separates_sportsbook_actions_from_depth_sources():
    script = (
        Path(__file__).resolve().parents[1] / "static" / "sharp-money.js"
    ).read_text(encoding="utf-8")

    assert '"novig", "prophetx", "4cx", "fourcx", "polymarket", "kalshi"' in script
    assert 'const DEPTH_PROVIDER_ORDER = ["novig", "prophetx"]' in script
    assert "rows.filter(row => !isMarketIntelligenceProvider(row))" in script
    assert 'aria-label="NoVIG and ProphetX liquidity intelligence"' in script
    assert "sportsbookAction(quote, signal.americanOdds)" in script


def test_sharp_money_control_routes_to_collector(app_client, monkeypatch):
    collector = app_client.application.extensions["sharp_money_collector"]
    actions = []
    monkeypatch.setattr(
        collector,
        "play",
        lambda: (actions.append("play") or True, "started"),
    )
    monkeypatch.setattr(
        collector,
        "pause",
        lambda: (actions.append("pause") or True, "paused"),
    )

    assert app_client.post(
        "/api/sharp-money/control", json={"action": "play"}
    ).status_code == 200
    assert app_client.post(
        "/api/sharp-money/control", json={"action": "pause"}
    ).status_code == 200
    assert actions == ["play", "pause"]


def test_sharp_money_control_rejects_unknown_action(app_client):
    response = app_client.post(
        "/api/sharp-money/control", json={"action": "execute"}
    )
    assert response.status_code == 400


def test_discord_connection_test_is_disabled_and_never_sends(app_client, monkeypatch):
    service = app_client.application.extensions["tracker_service"]
    settings = app_client.application.config["SETTINGS"]
    object.__setattr__(settings, "tracker_job_secret", "test-job-secret")
    sent_payloads = []

    def send(payload):
        sent_payloads.append(payload)
        return DiscordDeliveryResult(True, message_id="message-id", status_code=200)

    monkeypatch.setattr(service.model_discord_bot, "send", send)

    unauthorized = app_client.post("/api/admin/discord-notifications/test")
    delivered = app_client.post(
        "/api/admin/discord-notifications/test",
        headers={"Authorization": "Bearer test-job-secret"},
        json={"nonce": "one-time-test"},
    )

    assert unauthorized.status_code == 401
    assert delivered.status_code == 410
    assert delivered.get_json()["status"] == "private_only"
    assert delivered.get_json()["delivered"] is False
    assert delivered.get_json()["error"] == "test_messages_disabled"
    assert sent_payloads == []


def test_tracker_page_contains_real_job_status_and_admin_controls(app_client):
    html = app_client.get("/tracker?view=model").get_data(as_text=True)

    assert "Model Tracker" in html
    assert "Personal Tracker" in html
    assert 'id="tracker-view-toggle"' in html
    assert 'id="tracker-job-state"' in html
    assert 'id="tracker-bankroll-edit"' in html
    assert 'id="tracker-bankroll-dialog"' in html
    assert 'id="tracker-bankroll-form"' in html
    assert "Tracker profile" not in html
    assert 'id="tracker-reconcile"' in html
    assert 'id="tracker-pause-job"' in html
    assert 'id="tracker-rejection-body"' in html
    assert 'id="tracker-admin-form"' in html
    assert 'id="tracker-admin-password"' in html
    assert "/static/app.js?v=local" in html
    assert "/static/style.css?v=local" in html


def test_tracker_page_uses_one_shared_shell_for_both_trackers(app_client):
    html = app_client.get("/tracker?view=personal").get_data(as_text=True)

    assert html.count('href="/tracker"') == 1
    assert 'id="tracker-metrics"' in html
    assert 'id="tracker-chart"' in html
    assert 'id="tracker-summary-clv"' in html
    assert 'id="clv-chart"' not in html
    assert 'id="clv-period-strip"' not in html
    assert 'id="tracker-clv-status"' in html
    assert 'id="tracker-clv-sort"' in html
    assert 'id="tracker-clv-card"' in html
    assert 'id="tracker-clv-dialog"' in html
    assert 'id="tracker-clv-preferences-dialog"' in html
    assert 'id="tracker-clv-books-dialog"' in html
    assert "Best verified closing price captured for each bet" in html
    assert 'id="tracker-body"' in html
    assert 'id="personal-bankroll-control"' in html
    assert 'id="model-bankroll-control"' in html
    assert 'href="/model-tracker"' not in html
    assert 'href="/personal-tracking"' not in html


def test_model_tracker_history_is_shared_across_browser_users(app_client):
    service = app_client.application.extensions["tracker_service"]
    assert service.database.insert_tracker_snapshot(
        MODEL_TRACKER_USER_ID,
        {
            "snapshot_id": "shared-snapshot",
            "dedupe_key": "shared-event::shared-market::::shared-outcome::v2",
            "recommendation_version": "v2",
            "recommendation_timestamp": datetime.now(timezone.utc).isoformat(),
            "event_title": "Shared tennis match",
            "market_title": "Match winner",
            "recommended_side": "Player A",
            "effective_entry_price": 0.5,
            "final_recommended_fraction": 0.005,
            "original_displayed_amount": 50,
            "original_recommended_units": 0.5,
            "estimated_win_probability": 0.55,
            "sharps_count": 1,
        },
    )
    first_user = app_client.application.test_client()
    first_user.set_cookie("iconbets_user", "first-browser")
    second_user = app_client.application.test_client()
    second_user.set_cookie("iconbets_user", "second-browser")

    first_payload = first_user.get("/api/model-tracker").get_json()
    second_payload = second_user.get("/api/model-tracker").get_json()

    assert first_payload["pagination"]["total"] == 1
    assert second_payload["pagination"]["total"] == 1
    assert first_payload["data"][0]["snapshot"]["event_title"] == "Shared tennis match"
    assert second_payload["data"][0]["snapshot_id"] == "shared-snapshot"


def test_model_tracker_date_presets_and_custom_range(app_client):
    service = app_client.application.extensions["tracker_service"]
    now = datetime.now(timezone.utc)
    for label, age in (("recent", 3), ("month-old", 35), ("older", 120)):
        timestamp = (now - timedelta(days=age)).isoformat()
        assert service.database.insert_tracker_snapshot(
            MODEL_TRACKER_USER_ID,
            {
                "snapshot_id": f"date-{label}",
                "dedupe_key": f"date-event::{label}::::outcome::v2",
                "recommendation_version": "v2",
                "recommendation_timestamp": timestamp,
                "event_title": label,
                "market_title": "Moneyline",
                "recommended_side": "Example",
                "effective_entry_price": 0.5,
                "final_recommended_fraction": 0.005,
                "original_displayed_amount": 50,
                "original_recommended_units": 0.5,
                "estimated_win_probability": 0.55,
                "sharps_count": 1,
            },
        )

    assert app_client.get("/api/model-tracker?tracker_range=7").get_json()["pagination"]["total"] == 1
    assert app_client.get("/api/model-tracker?tracker_range=90").get_json()["pagination"]["total"] == 2
    start = (now - timedelta(days=40)).date().isoformat()
    end = (now - timedelta(days=30)).date().isoformat()
    custom = app_client.get(f"/api/model-tracker?tracker_range=custom&tracker_start={start}&tracker_end={end}")
    assert custom.status_code == 200
    assert custom.get_json()["data"][0]["snapshot"]["event_title"] == "month-old"
    assert app_client.get("/api/model-tracker?tracker_range=custom").status_code == 400


def test_model_tracker_search_filter_and_closed_rows_use_frozen_sharps(app_client):
    service = app_client.application.extensions["tracker_service"]
    dedupe = "sharp-event::sharp-market::::sharp-outcome::v2"
    frozen = {
        "primary_sharp": {
            "display_name": "Bagwell306",
            "wallet_address": "0xlead",
            "role": "Lead Sharp",
            "is_lead_sharp": True,
            "top_category": "Tennis",
            "amount": 3400,
            "units": 1.36,
            "average_entry": 0.4,
        },
        "agreeing_sharps": [
            {
                "display_name": "Bagwell306",
                "wallet_address": "0xlead",
                "role": "Lead Sharp",
                "is_lead_sharp": True,
            },
            {
                "display_name": "Wordylittleneck",
                "wallet_address": "0xsupport",
                "role": "Supporting Sharp",
                "is_lead_sharp": False,
            },
        ],
        "sharp_source_status": "recommendation_snapshot",
        "sharp_count_snapshot": 2,
    }
    assert service.database.insert_tracker_snapshot(
        MODEL_TRACKER_USER_ID,
        {
            "snapshot_id": "sharp-snapshot",
            "dedupe_key": dedupe,
            "recommendation_version": "v2",
            "recommendation_timestamp": "2026-07-14T15:00:00+00:00",
            "event_title": "Frozen Sharp match",
            "market_title": "Match winner",
            "recommended_side": "Player A",
            "effective_entry_price": 0.4,
            "final_recommended_fraction": 0.01,
            "original_displayed_amount": 100,
            "original_recommended_units": 1,
            "estimated_win_probability": 0.55,
            "sharps_count": 2,
            "sharp_snapshot": frozen,
        },
    )
    service.database.update_tracker_status(
        MODEL_TRACKER_USER_ID,
        dedupe,
        "won",
        "Won",
        "2026-07-15T01:00:00+00:00",
    )

    searched = app_client.get(
        "/api/model-tracker?q=Bagwell306&tracker_range=all"
    ).get_json()
    filtered = app_client.get(
        "/api/model-tracker?sharp=Wordylittleneck&tracker_range=all"
    ).get_json()

    assert searched["pagination"]["total"] == 1
    assert searched["data"][0]["status"] == "won"
    returned_snapshot = searched["data"][0]["sharp_snapshot"]
    assert returned_snapshot["primary_sharp"] == frozen["primary_sharp"]
    assert returned_snapshot["agreeing_sharps"] == frozen["agreeing_sharps"]
    assert returned_snapshot["sharp_source_status"] == "recommendation_snapshot"
    assert returned_snapshot["lead_sharp_wallet_ids"] == ["0xlead"]
    assert returned_snapshot["supporting_sharp_wallet_ids"] == ["0xsupport"]
    assert filtered["pagination"]["total"] == 1
    assert filtered["filter_options"]["sharps"] == [
        "Bagwell306",
        "Wordylittleneck",
    ]


def test_personal_tracker_search_filter_manual_source_and_privacy(app_client):
    service = app_client.application.extensions["tracker_service"]
    app_client.set_cookie("iconbets_user", "sharp-owner")
    frozen = {
        "primary_sharp": {
            "display_name": "Bagwell306",
            "wallet_address": "0xlead",
            "role": "Lead Sharp",
        },
        "agreeing_sharps": [
            {
                "display_name": "Bagwell306",
                "wallet_address": "0xlead",
                "role": "Lead Sharp",
            },
            {
                "display_name": "Wordylittleneck",
                "wallet_address": "0xsupport",
                "role": "Supporting Sharp",
            },
        ],
        "sharp_source_status": "recommendation_snapshot",
    }
    base_fill = {
        "fill_id": "sharp-personal-fill",
        "canonical_event_id": "personal-event",
        "canonical_market_id": "personal-market",
        "market_line": "",
        "canonical_outcome_id": "personal-outcome",
        "event_title": "Personal Sharp match",
        "market_title": "Winner",
        "selection": "Player A",
        "entry_price": 0.4,
        "shares": 100,
        "position_cost": 40,
        "fees": 0,
        "total_paid": 40,
        "sharp_snapshot": frozen,
    }
    service.database.insert_personal_bet_fill("sharp-owner", base_fill)
    service.database.insert_personal_bet_fill(
        "sharp-owner",
        {
            **base_fill,
            "fill_id": "manual-personal-fill",
            "canonical_event_id": "manual-event",
            "canonical_market_id": "manual-market",
            "canonical_outcome_id": "manual-outcome",
            "event_title": "Manual bet",
            "sharp_snapshot": {"sharp_source_status": "manual_entry"},
        },
    )

    searched = app_client.get("/api/personal-tracker?q=Wordylittleneck").get_json()
    filtered = app_client.get(
        "/api/personal-tracker?sharp=Bagwell306"
    ).get_json()
    all_rows = app_client.get("/api/personal-tracker").get_json()

    assert searched["pagination"]["total"] == 1
    assert filtered["pagination"]["total"] == 1
    assert filtered["filter_options"]["sharps"] == [
        "Bagwell306",
        "Wordylittleneck",
    ]
    manual = next(row for row in all_rows["data"] if row["fill_id"] == "manual-personal-fill")
    assert manual["sharp_snapshot"]["sharp_source_status"] == "manual_entry"

    other_user = app_client.application.test_client()
    other_user.set_cookie("iconbets_user", "sharp-other-user")
    assert other_user.get("/api/personal-tracker?q=Bagwell306").get_json()[
        "pagination"
    ]["total"] == 0


def test_model_tracker_api_joins_immutable_clv_and_period_analytics(app_client):
    service = app_client.application.extensions["tracker_service"]
    dedupe = "clv-event::clv-market::::clv-token::v2"
    assert service.database.insert_tracker_snapshot(
        MODEL_TRACKER_USER_ID,
        {
            "snapshot_id": "clv-snapshot",
            "dedupe_key": dedupe,
            "recommendation_version": "v2",
            "recommendation_timestamp": datetime.now(timezone.utc).isoformat(),
            "event_title": "CLV test match",
            "market_title": "Match winner",
            "recommended_side": "Player A",
            "effective_entry_price": 0.343,
            "final_recommended_fraction": 0.01,
            "original_displayed_amount": 100,
            "original_recommended_units": 1,
            "estimated_win_probability": 0.5,
            "sharps_count": 1,
        },
    )
    assert service.database.insert_closing_line(
        {
            "tracker_type": "model",
            "tracker_record_id": dedupe,
            "user_id": MODEL_TRACKER_USER_ID,
            "provider": "polymarket",
            "provider_event_id": "clv-event",
            "provider_market_id": "clv-market",
            "provider_selection_id": "clv-token",
            "entry_price": 0.343,
            "entry_implied_probability": 0.343,
            "entry_stake": 100,
            "closing_snapshot_timestamp": datetime.now(timezone.utc).isoformat(),
            "official_event_start_timestamp": datetime.now(timezone.utc).isoformat(),
            "closing_effective_price": 0.43,
            "closing_midpoint": 0.426,
            "clv_cents": 8.7,
            "clv_probability_points": 8.7,
            "clv_pct": 25.3644314869,
            "midpoint_clv_pct": 24.1982507289,
            "clv_status": "captured",
            "clv_unavailable_reason": None,
            "calculation_version": "clv-v1",
        }
    )

    payload = app_client.get("/api/model-tracker?clv_status=positive").get_json()
    assert payload["data"][0]["clv"]["provider"] == "polymarket"
    assert payload["data"][0]["clv"]["clv_pct"] == pytest.approx(25.3644314869)
    assert payload["clv"]["periods"]["all"]["stake_weighted_clv_pct"] == pytest.approx(25.3644314869)


def test_model_tracker_filters_multiple_books_and_recalculates_combined_pnl(app_client):
    service = app_client.application.extensions["tracker_service"]
    now = datetime.now(timezone.utc).isoformat()
    for index, book in enumerate(("FanDuel", "DraftKings", "Polymarket"), start=1):
        dedupe = f"book-event-{index}::book-market-{index}::::book-token-{index}::v2"
        assert service.database.insert_tracker_snapshot(
            MODEL_TRACKER_USER_ID,
            {
                "snapshot_id": f"book-snapshot-{index}",
                "dedupe_key": dedupe,
                "recommendation_version": "v2",
                "recommendation_timestamp": now,
                "event_title": f"Book test {index}",
                "market_title": "Winner",
                "recommended_side": "Home",
                "sportsbook": book,
                "effective_entry_price": 0.5,
                "final_recommended_fraction": 0.01,
                "original_displayed_amount": 100,
                "original_recommended_units": 1,
                "sharps_count": 1,
            },
        )
        service.database.update_tracker_status(
            MODEL_TRACKER_USER_ID,
            dedupe,
            "won" if book != "DraftKings" else "lost",
            "Won" if book != "DraftKings" else "Lost",
            now,
        )

    combined = app_client.get(
        "/api/model-tracker?sportsbook=FanDuel,DraftKings"
    ).get_json()

    assert combined["pagination"]["total"] == 2
    assert combined["summary"]["wins"] == 1
    assert combined["summary"]["losses"] == 1
    assert combined["filter_options"]["sportsbooks"] == [
        "DraftKings",
        "FanDuel",
        "Polymarket",
    ]
    by_book = {
        item["sportsbook"]: item for item in combined["sportsbook_summaries"]
    }
    assert by_book["FanDuel"]["wins"] == 1
    assert by_book["DraftKings"]["losses"] == 1
    assert combined["selected_sportsbooks"] == ["draftkings", "fanduel"]


def test_tracker_bankroll_api_is_independent_from_trade_bankroll(app_client):
    app_client.set_cookie("iconbets_user", "bankroll-user")
    trade_settings = app_client.get("/api/user-settings").get_json()["data"]

    response = app_client.put(
        "/api/model-tracker/settings",
        json={"tracker_bankroll": 25000},
    )

    assert response.status_code == 200
    tracker_settings = response.get_json()["data"]
    assert tracker_settings["tracker_bankroll"] == 25000
    assert tracker_settings["starting_bankroll"] == trade_settings["starting_bankroll"]

    tracker_payload = app_client.get("/api/model-tracker").get_json()
    assert tracker_payload["summary"]["starting_bankroll"] == 25000
    assert (
        app_client.get("/api/user-settings").get_json()["data"]["starting_bankroll"]
        == trade_settings["starting_bankroll"]
    )


def test_tracker_bankroll_api_rejects_non_positive_values(app_client):
    response = app_client.put(
        "/api/model-tracker/settings",
        json={"tracker_bankroll": 0},
    )

    assert response.status_code == 400
    assert "greater than zero" in response.get_json()["error"]


def test_account_bankroll_persists_across_login_and_is_user_owned(app_client):
    default_bankroll = app_client.application.config["SETTINGS"].default_bankroll
    owner = app_client.application.test_client()
    initial = owner.get("/api/user-settings").get_json()["data"]
    saved = owner.put(
        "/api/user-settings",
        json={
            "trades_to_play_bankroll": 25000,
            "expected_version": initial["settings_version"],
        },
    )
    assert saved.status_code == 200
    assert saved.get_json()["data"]["unit_value"] == 250

    registered = owner.post(
        "/api/auth/register",
        json={"email": "owner@example.com", "password": "strong-pass-1"},
    )
    assert registered.status_code == 201

    another_device = app_client.application.test_client()
    assert another_device.post(
        "/api/auth/login",
        json={"email": "owner@example.com", "password": "strong-pass-1"},
    ).status_code == 200
    synced = another_device.get("/api/user-settings").get_json()["data"]
    assert synced["trades_to_play_bankroll"] == 25000
    assert synced["sizing_bankroll_configured"] is True

    other_account = app_client.application.test_client()
    other_account.get("/api/user-settings")
    assert other_account.post(
        "/api/auth/register",
        json={"email": "other@example.com", "password": "strong-pass-2"},
    ).status_code == 201
    other_settings = other_account.get("/api/user-settings").get_json()["data"]
    assert other_settings["trades_to_play_bankroll"] == default_bankroll
    assert other_settings["trades_to_play_bankroll"] != synced["trades_to_play_bankroll"]

    assert another_device.post("/api/auth/logout").status_code == 200
    signed_out_settings = another_device.get("/api/user-settings").get_json()["data"]
    assert signed_out_settings["trades_to_play_bankroll"] == default_bankroll


def test_account_registration_persists_username_and_rejects_duplicates(app_client):
    first = app_client.post(
        "/api/auth/register",
        json={
            "username": "line_shopper",
            "email": "first@example.com",
            "password": "strong-pass-1",
        },
    )

    assert first.status_code == 201
    assert first.get_json()["username"] == "line_shopper"
    session = app_client.get("/api/auth/session").get_json()
    assert session["authenticated"] is True
    assert session["username"] == "line_shopper"

    other = app_client.application.test_client()
    duplicate = other.post(
        "/api/auth/register",
        json={
            "username": "LINE_SHOPPER",
            "email": "second@example.com",
            "password": "strong-pass-2",
        },
    )

    assert duplicate.status_code == 409
    assert duplicate.get_json()["error"] == "That username is already taken."


def test_google_auth_start_requires_configured_credentials(app_client, monkeypatch):
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)

    response = app_client.get("/api/auth/google/start")

    assert response.status_code == 302
    assert response.headers["Location"].endswith(
        "/trades?auth_error=google_not_configured"
    )


def test_subscription_portal_requires_login_and_configuration(app_client, monkeypatch):
    monkeypatch.delenv("STRIPE_CUSTOMER_PORTAL_URL", raising=False)

    signed_out = app_client.get("/api/account/subscription")
    assert signed_out.status_code == 302
    assert signed_out.headers["Location"].endswith("/trades?account=signin")

    assert app_client.post(
        "/api/auth/register",
        json={
            "username": "portal_tester",
            "email": "portal@example.com",
            "password": "strong-pass-1",
        },
    ).status_code == 201
    unavailable = app_client.get("/api/account/subscription")
    assert unavailable.status_code == 302
    assert unavailable.headers["Location"].endswith(
        "/trades?account=subscription_unavailable"
    )
    assert (
        app_client.get("/api/auth/session")
        .get_json()["subscription_management_available"]
        is False
    )


def test_failed_and_stale_bankroll_saves_preserve_confirmed_value(app_client):
    app_client.set_cookie("iconbets_user", "versioned-user")
    initial = app_client.get("/api/user-settings").get_json()["data"]
    first = app_client.put(
        "/api/user-settings",
        json={
            "trades_to_play_bankroll": 1000,
            "expected_version": initial["settings_version"],
        },
    )
    assert first.status_code == 200
    assert first.get_json()["data"]["unit_value"] == 10

    invalid = app_client.put(
        "/api/user-settings", json={"trades_to_play_bankroll": 0}
    )
    stale = app_client.put(
        "/api/user-settings",
        json={
            "trades_to_play_bankroll": 50000,
            "expected_version": initial["settings_version"],
        },
    )

    assert invalid.status_code == 400
    assert stale.status_code == 409
    assert stale.get_json()["data"]["trades_to_play_bankroll"] == 1000
    current = app_client.get("/api/user-settings").get_json()["data"]
    assert current["trades_to_play_bankroll"] == 1000


def test_personal_bankroll_and_view_preference_are_separate_per_user(app_client):
    first = app_client.application.test_client()
    second = app_client.application.test_client()
    first.set_cookie("iconbets_user", "first-preferences")
    second.set_cookie("iconbets_user", "second-preferences")
    first.get("/api/user-settings")
    second.get("/api/user-settings")

    assert first.put(
        "/api/personal-tracker/settings",
        json={"personal_tracker_bankroll": 5000},
    ).status_code == 200
    assert first.put(
        "/api/tracker-preference", json={"view": "personal"}
    ).status_code == 200

    first_settings = first.get("/api/user-settings").get_json()["data"]
    second_settings = second.get("/api/user-settings").get_json()["data"]
    assert first_settings["personal_tracker_bankroll"] == 5000
    assert first_settings["tracker_view"] == "personal"
    assert second_settings["personal_tracker_bankroll"] != 5000
    assert second_settings["tracker_view"] == "model"
    assert first.get("/api/personal-tracker").get_json()["summary"][
        "starting_bankroll"
    ] == 5000


def test_tracker_shell_script_supports_query_memory_and_keyboard_navigation():
    script = (Path(__file__).parents[1] / "static" / "app.js").read_text()

    assert 'params.get("view")' in script
    assert 'fetchJson("/api/tracker-preference"' in script
    assert '"ArrowLeft", "ArrowRight", "Home", "End"' in script
    assert 'appState.trackerCache = ' not in script
    assert 'trackerCache: { model: null, personal: null }' in script


def test_frontend_storage_failures_cannot_block_trade_startup():
    script = (Path(__file__).parents[1] / "static" / "app.js").read_text()
    server = (Path(__file__).parents[1] / "app.py").read_text()

    assert "const safeStorage = {" in script
    assert 'paused: safeStorage.getItem("iconbets-refresh-paused")' in script
    assert "localStorage.getItem" not in script
    assert "localStorage.setItem" not in script
    assert "document.currentScript" not in script
    assert "live_snapshot_endpoints = {" in server
    assert 'if request.endpoint not in live_snapshot_endpoints' in server
    assert "tradeRequestInFlight: false" in script
    assert "if (appState.tradeRequestInFlight)" in script
    assert "appState.tradeRefreshQueued = true" in script


def test_scheduled_tracker_record_appears_after_api_revalidation(app_client):
    service = app_client.application.extensions["tracker_service"]
    app_client.set_cookie("iconbets_user", "render-user")
    assert app_client.get("/api/model-tracker").get_json()["pagination"]["total"] == 0
    snapshot = {
        "snapshot_id": "render-snapshot",
        "dedupe_key": "event::market::::outcome::v2",
        "recommendation_version": "v2",
        "recommendation_timestamp": datetime.now(timezone.utc).isoformat(),
        "event_title": "Spain vs France",
        "market_title": "To Advance",
        "recommended_side": "Spain",
        "event_start_time": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "effective_entry_price": 0.4,
        "final_recommended_fraction": 0.005,
        "original_displayed_amount": 50,
        "original_recommended_units": 0.5,
        "estimated_win_probability": 0.42,
        "sharps_count": 1,
    }
    assert service.database.insert_tracker_snapshot(MODEL_TRACKER_USER_ID, snapshot) is True

    payload = app_client.get("/api/model-tracker").get_json()
    assert payload["pagination"]["total"] == 1
    assert payload["data"][0]["status"] == "scheduled"


def test_official_tracker_play_remains_in_trades_feed_when_live_signal_is_absent(
    app_client,
):
    service = app_client.application.extensions["tracker_service"]
    event_start = datetime.now(timezone.utc) + timedelta(hours=1)
    snapshot = {
        "snapshot_id": "locked-official-snapshot",
        "dedupe_key": "locked-event::locked-market::::locked-outcome::v2",
        "recommendation_version": "v2",
        "recommendation_timestamp": datetime.now(timezone.utc).isoformat(),
        "canonical_event_id": "locked-event",
        "canonical_market_id": "locked-market",
        "outcome_id": "locked-outcome",
        "event_title": "Locked MLB game",
        "market_title": "Moneyline",
        "recommended_side": "Away team",
        "category": "MLB",
        "league": "MLB",
        "canonical_category_id": "mlb",
        "event_start_time": event_start.isoformat(),
        "effective_entry_price": 0.4,
        "confidence_score": 83,
        "final_recommended_fraction": 0.04,
        "original_displayed_amount": 400,
        "original_recommended_units": 4,
        "sharps_count": 3,
        "lead_sharp_count": 1,
        "supporting_sharp_count": 2,
    }
    assert service.database.insert_tracker_snapshot(
        MODEL_TRACKER_USER_ID, snapshot
    )

    payload = app_client.get(
        "/api/trades-to-play",
        query_string={
            "date_range": "custom",
            "custom_start": (
                datetime.now(timezone.utc) - timedelta(days=1)
            ).date().isoformat(),
            "custom_end": (event_start + timedelta(days=1)).date().isoformat(),
        },
    ).get_json()

    official = payload["officialTracked"]
    assert len(official) == 1
    assert official[0]["snapshot"]["snapshot_id"] == "locked-official-snapshot"
    assert official[0]["snapshot"]["original_displayed_amount"] == 400


def test_dedicated_pages_and_tracker_redirects(app_client):
    for route in (
        "/trades",
        "/live-positions",
        "/wallets",
        "/position-history",
        "/tracker",
    ):
        response = app_client.get(route)
        assert response.status_code == 200
        assert response.request.path == route

    home = app_client.get("/")
    assert home.status_code == 200
    assert b"The Most" in home.data
    assert b"Efficient Software" in home.data
    assert b'aria-label="IconLabs home"' in home.data
    assert b'href="/overview"' not in home.data

    legacy_dashboard = app_client.get("/overview")
    assert legacy_dashboard.status_code == 302
    assert legacy_dashboard.headers["Location"].endswith("/")
    assert app_client.get("/history").status_code == 301
    redirects = {
        "/model-tracker": "/tracker?view=model",
        "/bet-tracker": "/tracker?view=model",
        "/personal-tracking": "/tracker?view=personal",
        "/personal-tracker": "/tracker?view=personal",
    }
    for route, target in redirects.items():
        response = app_client.get(route)
        assert response.status_code == 301
        assert response.headers["Location"].endswith(target)


def test_trade_date_presets_reject_removed_modes(app_client):
    for mode in ("tomorrow", "next48", "week", "all"):
        assert (
            app_client.get(f"/api/trades-to-play?date_range={mode}").status_code == 400
        )


def test_only_positive_executable_recommendations_are_actionable():
    positive = {
        "recommendation": {
            "available": True,
            "final_recommended_fraction": 0.001,
            "recommended_amount": 10,
        }
    }
    zero_stake = {
        "recommendation": {
            "available": True,
            "final_recommended_fraction": 0,
            "recommended_amount": 0,
        }
    }
    unavailable = {
        "recommendation": {
            "available": False,
            "final_recommended_fraction": 0.001,
            "recommended_amount": 10,
        }
    }

    assert _has_positive_recommendation(positive) is True
    assert _has_positive_recommendation(zero_stake) is False
    assert _has_positive_recommendation(unavailable) is False


def test_event_start_display_uses_eastern_today_tomorrow_and_future_dates():
    now = datetime(2026, 7, 13, 16, 0, tzinfo=timezone.utc)

    assert _format_event_start("2026-07-13T19:10:00-04:00", now) == "Today, 7:10 PM"
    assert _format_event_start("2026-07-14T15:00:00-04:00", now) == "Tomorrow, 3 PM"
    assert _format_event_start("2026-07-19T23:59:00-04:00", now) == "Jul 19, 11:59 PM"
    assert (
        _format_event_start("2027-01-03T14:00:00-05:00", now)
        == "Jan 3, 2027 \u00b7 2 PM"
    )
    assert _format_event_start(None, now) == "Time unavailable"


def test_trade_card_view_uses_real_metric_and_recommendation_values():
    play = {
        "event_date_et": "2026-07-14T15:00:00-04:00",
        "average_entry_price": 0.405,
        "primary_trader": {"amount": 2036.42, "relative_units": 3.5},
        "evidence_inputs": {"adjusted_category_hit_rate": 0.5908},
    }
    recommendation = {
        "sharp_average_entry_price": 0.405,
        "current_user_entry_price": 0.4,
        "recommended_shares": 385,
        "recommended_amount": 154,
        "recommended_units": 1.54,
    }
    now = datetime(2026, 7, 13, 16, 0, tzinfo=timezone.utc)

    card = _trade_card_view(play, recommendation, now)

    assert card == {
        "event_time": "Tomorrow, 3 PM",
        "trader_bet_amount": 2036.42,
        "trader_average_entry_price": 0.405,
        "relative_bet_size": 3.5,
        "category_hit_rate": 0.5908,
        "recommended_shares": 385,
        "recommended_amount": 154,
        "recommended_units": 1.54,
        "current_actionable_price": 0.4,
        "slippage_fraction": (0.4 - 0.405) / 0.405,
    }


def test_slippage_fraction_uses_whale_entry_as_the_percentage_baseline():
    worse = _slippage_fraction(0.4, 0.389)
    better = _slippage_fraction(0.389, 0.4)

    assert round(worse * 100, 1) == 2.8
    assert round(better * 100, 1) == -2.8
    assert _slippage_fraction(0.4, 0) is None


def test_trade_feed_bulk_loads_personal_exposure_once(app_client, monkeypatch):
    service = app_client.application.extensions["tracker_service"]
    service._cache["trades_to_play"] = [
        _actionable_trade(),
        {
            **_actionable_trade(),
            "id": "market-2::outcome-b",
            "market_title": "Moneyline",
            "clob_token_id": "outcome-b",
            "validation_ids": {
                **_actionable_trade()["validation_ids"],
                "condition_id": "market-2",
                "outcome_token_id": "outcome-b",
            },
        },
    ]
    monkeypatch.setattr(service, "evaluate_recommendation", _positive_evaluation)
    monkeypatch.setattr(service, "track_recommendations_for_user", lambda *_args: 0)
    calls = 0
    original = service.database.get_personal_bet_fills

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(service.database, "get_personal_bet_fills", counted)

    response = app_client.get("/api/trades-to-play?date_range=next7")

    assert response.status_code == 200
    assert response.get_json()["pagination"]["total"] == 2
    assert calls == 1


def test_today_dashboard_shows_qualified_play_before_two_hour_tracking_gate(
    app_client, monkeypatch
):
    import trade_scoring

    fixed_now = datetime(2026, 7, 13, 16, 0, tzinfo=timezone.utc)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    monkeypatch.setattr(trade_scoring, "datetime", FixedDateTime)
    service = app_client.application.extensions["tracker_service"]
    trade = {
        **_actionable_trade(),
        "event_date_et": "2026-07-13T19:00:00-04:00",
        "event_time_et": "2026-07-13T19:00:00-04:00",
    }
    service._cache["trades_to_play"] = [trade]
    monkeypatch.setattr(service, "evaluate_recommendation", _positive_evaluation)

    response = app_client.get("/api/trades-to-play?date_range=today")
    tracking = service.reconcile_model_tracker([trade], fixed_now)

    assert response.status_code == 200
    assert response.get_json()["pagination"]["total"] == 1
    assert response.get_json()["data"][0]["id"] == trade["id"]
    assert tracking["records_inserted"] == 0
    assert tracking["deferred_until_pregame"] == 1


def test_trade_feed_includes_polymarket_execution_option(app_client, monkeypatch):
    service = app_client.application.extensions["tracker_service"]
    service._cache["trades_to_play"] = [_actionable_trade()]
    monkeypatch.setattr(service, "evaluate_recommendation", _positive_evaluation)

    response = app_client.get("/api/trades-to-play?date_range=next7")

    assert response.status_code == 200
    options = response.get_json()["data"][0]["executionOptions"]
    assert [option["providerName"] for option in options] == ["Polymarket"]
    assert options[0]["matchingConfidence"] == "Exact"
    assert options[0]["deepLink"] == "https://polymarket.com/event/example"


def test_shadow_status_reports_active_tracking_and_storage_backend(app_client):
    response = app_client.get("/api/shadow-test")

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["shadow"]["enabled"] is True
    assert payload["shadow"]["status"] == "ACTIVE_FORWARD_TRACKING"
    assert payload["persistence"] == {
        "position_history_persistent": False,
        "backend": "sqlite",
    }


@pytest.mark.parametrize(
    ("query", "entry", "expected_total"),
    [
        ("minEntryCents=20", 0.2, 1),
        ("minEntryCents=20", 0.199, 0),
        ("maxEntryCents=80", 0.8, 1),
        ("maxEntryCents=80", 0.801, 0),
        ("minEntryCents=20&maxEntryCents=80", 0.507, 1),
    ],
)
def test_entry_cents_filters_are_inclusive_and_backend_enforced(
    app_client, monkeypatch, query, entry, expected_total
):
    service = app_client.application.extensions["tracker_service"]
    service._cache["trades_to_play"] = [_actionable_trade()]
    monkeypatch.setattr(service, "evaluate_recommendation", _evaluation_at(entry))

    response = app_client.get(f"/api/trades-to-play?date_range=next7&{query}")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["pagination"]["total"] == expected_total
    if expected_total:
        trade = payload["data"][0]
        assert trade["effectiveEntryCents"] == pytest.approx(entry * 100)
        assert {
            "sharpReferenceEntryCents",
            "currentTopAskCents",
            "effectiveEntryCents",
            "slippageCents",
            "unfavorableSlippagePct",
            "passesSlippageRule",
            "slippageRejectionReason",
        } <= trade.keys()


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ("minEntryCents=80&maxEntryCents=20", "cannot exceed"),
        ("minEntryCents=0", "greater than 0"),
        ("maxEntryCents=100", "less than 100"),
        ("minEntryCents=20.11", "one decimal"),
        ("maxEntryCents=not-a-price", "must be a number"),
    ],
)
def test_entry_cents_filter_validation_returns_clear_backend_error(
    app_client, query, message
):
    response = app_client.get(f"/api/trades-to-play?date_range=next7&{query}")

    assert response.status_code == 400
    assert message in response.get_json()["error"]


def test_excess_slippage_is_absent_from_backend_feed(app_client, monkeypatch):
    service = app_client.application.extensions["tracker_service"]
    service._cache["trades_to_play"] = [_actionable_trade()]
    monkeypatch.setattr(
        service,
        "evaluate_recommendation",
        _evaluation_at(0.421, passes=False, reason="SLIPPAGE_ABOVE_MAX"),
    )

    response = app_client.get("/api/trades-to-play?date_range=next7")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["pagination"]["total"] == 0
    assert payload["liveRejectedTradeIds"] == ["market-1::outcome-a"]


def test_second_live_quote_rejects_then_restores_candidate(app_client, monkeypatch):
    service = app_client.application.extensions["tracker_service"]
    service._cache["trades_to_play"] = [_actionable_trade()]
    evaluations = [
        _evaluation_at(0.4),
        _evaluation_at(0.491, passes=False, reason="SLIPPAGE_ABOVE_MAX"),
        _evaluation_at(0.4),
        _evaluation_at(0.418),
    ]

    def evaluate(*args, **kwargs):
        return evaluations.pop(0)(*args, **kwargs)

    monkeypatch.setattr(service, "evaluate_recommendation", evaluate)

    rejected = app_client.get("/api/trades-to-play?date_range=next7").get_json()
    restored = app_client.get("/api/trades-to-play?date_range=next7").get_json()

    assert rejected["data"] == []
    assert rejected["pagination"]["total"] == 0
    assert rejected["liveRejectedTradeIds"] == ["market-1::outcome-a"]
    assert [trade["id"] for trade in restored["data"]] == ["market-1::outcome-a"]
    assert restored["pagination"]["total"] == 1
    assert restored["liveRejectedTradeIds"] == []


def test_search_date_sharps_and_entry_price_filters_compose(app_client, monkeypatch):
    service = app_client.application.extensions["tracker_service"]
    service._cache["trades_to_play"] = [_actionable_trade()]
    monkeypatch.setattr(service, "evaluate_recommendation", _evaluation_at(0.507))

    matching = app_client.get(
        "/api/trades-to-play?date_range=next7&q=Spain&min_sharps=1"
        "&minEntryCents=20&maxEntryCents=80"
    )
    too_many_sharps = app_client.get(
        "/api/trades-to-play?date_range=next7&q=Spain&min_sharps=2"
        "&minEntryCents=20&maxEntryCents=80"
    )
    unrestricted = app_client.get("/api/trades-to-play?date_range=next7")

    assert matching.get_json()["pagination"]["total"] == 1
    assert too_many_sharps.get_json()["pagination"]["total"] == 0
    assert unrestricted.get_json()["pagination"]["total"] == 1


def test_hide_restore_and_show_hidden_are_user_specific(app_client, monkeypatch):
    service = app_client.application.extensions["tracker_service"]
    service._cache["trades_to_play"] = [_actionable_trade()]
    monkeypatch.setattr(service, "evaluate_recommendation", _positive_evaluation)
    monkeypatch.setattr(service, "track_recommendations_for_user", lambda *_args: 0)
    app_client.set_cookie("iconbets_user", "user-1")

    hidden = app_client.post(
        "/api/hidden-trades", json={"trade_id": "market-1::outcome-a"}
    )
    visible = app_client.get("/api/trades-to-play?date_range=next7")
    shown = app_client.get("/api/trades-to-play?date_range=next7&show_hidden=true")
    other_user = app_client.application.test_client()
    other_user.set_cookie("iconbets_user", "user-2")
    other_visible = other_user.get("/api/trades-to-play?date_range=next7")

    assert hidden.status_code == 201
    assert visible.get_json()["pagination"]["total"] == 0
    assert shown.get_json()["data"][0]["isHidden"] is True
    assert other_visible.get_json()["pagination"]["total"] == 1

    hidden_id = hidden.get_json()["data"]["id"]
    assert other_user.delete(f"/api/hidden-trades/{hidden_id}").status_code == 404
    assert app_client.delete(f"/api/hidden-trades/{hidden_id}").status_code == 200
    assert (
        app_client.get("/api/trades-to-play?date_range=next7").get_json()["pagination"][
            "total"
        ]
        == 1
    )


def test_confirmed_personal_fill_warns_and_duplicate_requires_confirmation(
    app_client, monkeypatch
):
    service = app_client.application.extensions["tracker_service"]
    service._cache["trades_to_play"] = [_actionable_trade()]
    monkeypatch.setattr(service, "evaluate_recommendation", _positive_evaluation)
    monkeypatch.setattr(service, "track_recommendations_for_user", lambda *_args: 0)
    app_client.set_cookie("iconbets_user", "personal-user")
    purchase = {
        "trade_id": "market-1::outcome-a",
        "entry_price": 0.4,
        "shares": 100,
        "fees": 1,
    }

    first = app_client.post("/api/personal-bets", json=purchase)
    duplicate = app_client.post("/api/personal-bets", json=purchase)
    second = app_client.post(
        "/api/personal-bets", json={**purchase, "confirm_duplicate": True}
    )
    feed = app_client.get("/api/trades-to-play?date_range=next7").get_json()
    personal_tracker = app_client.get("/api/personal-tracker").get_json()

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.get_json()["confirmationRequired"] == "duplicate"
    assert second.status_code == 201
    assert feed["data"][0]["personalExposureType"] == "exact"
    assert feed["data"][0]["personalEntryCount"] == 2
    assert personal_tracker["pagination"]["total"] == 2
    assert personal_tracker["summary"]["total_tracked_bets"] == 2
    assert personal_tracker["data"][0]["selection"] == "Spain"

    other_user = app_client.application.test_client()
    other_user.set_cookie("iconbets_user", "another-user")
    other_feed = other_user.get("/api/trades-to-play?date_range=next7").get_json()
    assert other_feed["data"][0]["personalExposureType"] == "none"
    assert other_user.get("/api/personal-tracker").get_json()["pagination"]["total"] == 0


def test_manual_personal_bet_is_saved_without_model_recommendation(app_client):
    app_client.set_cookie("iconbets_user", "manual-personal-user")
    response = app_client.post(
        "/api/personal-bets/manual",
        json={
            "event_title": "New York Mets vs. Philadelphia Phillies",
            "market_title": "New York Mets vs. Philadelphia Phillies",
            "selection": "Philadelphia Phillies",
            "entry_price": 0.665,
            "stake": 250,
            "fees": 0,
            "sportsbook": "Polymarket",
            "tags": ["Legacy 3-0 Sharp simulation"],
            "status": "live",
            "market_url": "https://polymarket.com/event/mlb-nym-phi-2026-07-16",
            "canonical_event_id": "687903",
            "canonical_market_id": "0xmarket",
            "canonical_outcome_id": "phillies-token",
        },
    )

    assert response.status_code == 201
    saved = response.get_json()["data"]
    assert saved["position_cost"] == pytest.approx(250)
    assert saved["shares"] == pytest.approx(250 / 0.665)
    assert saved["status"] == "live"
    assert json.loads(saved["tags_json"]) == [
        "Legacy 3-0 Sharp simulation",
        "Manual Entry",
    ]
    tracker = app_client.get("/api/personal-tracker").get_json()
    assert tracker["pagination"]["total"] == 1
    assert tracker["data"][0]["position_cost"] == pytest.approx(250)


def test_positive_ev_bet_is_shared_with_bet_tracker_and_lab_my_bets(app_client):
    app_client.set_cookie("iconbets_user", "positive-ev-personal-user")
    purchase = {
        "source_id": "positive-ev-phillies-118",
        "event_title": "New York Mets vs Philadelphia Phillies",
        "market_title": "Moneyline",
        "selection": "Philadelphia Phillies",
        "event_start_time": "2026-08-20T23:10:00+00:00",
        "sport_key": "baseball_mlb",
        "league": "MLB",
        "market_key": "h2h",
        "canonical_event_id": "mlb-nym-phi-2026-08-20",
        "american_odds": 118,
        "stake": 84,
        "fees": 0,
        "sportsbook": "DraftKings",
        "sportsbook_logo": "/static/assets/sportsbooks/draftkings.png",
        "market_url": "https://sportsbook.example/positive-ev-play",
        "ev_percent": 5.62,
        "tags": ["Evening card"],
    }

    response = app_client.post("/api/positive-ev/personal-bets", json=purchase)

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["source"] == "positive_ev"
    assert payload["destinations"] == {
        "betTracker": "/tracker?view=personal",
        "labTracker": "/lab-tracker?scope=personal",
    }
    assert payload["data"]["entry_price"] == pytest.approx(100 / 218)
    assert payload["data"]["position_cost"] == pytest.approx(84)

    bet_tracker = app_client.get("/api/personal-tracker?tracker_range=all").get_json()
    assert bet_tracker["pagination"]["total"] == 1
    assert bet_tracker["data"][0]["selection"] == "Philadelphia Phillies"
    assert bet_tracker["data"][0]["sportsbook"] == "DraftKings"

    lab_tracker = app_client.get(
        "/api/lab-tracker?scope=personal&window=all"
    ).get_json()["data"]
    assert lab_tracker["summary"]["tracked"] == 1
    assert lab_tracker["summary"]["open"] == 1
    assert lab_tracker["openBets"][0]["selection"] == "Philadelphia Phillies"
    assert lab_tracker["openBets"][0]["league"] == "MLB"
    assert lab_tracker["openBets"][0]["entry_american_odds"] == 118
    assert lab_tracker["openBets"][0]["stake"] == pytest.approx(84)

    duplicate = app_client.post("/api/positive-ev/personal-bets", json=purchase)
    assert duplicate.status_code == 409
    assert duplicate.get_json()["confirmationRequired"] == "duplicate"


def test_positive_ev_track_and_hide_persists_without_shrinking_preview_fixture(
    app_client,
):
    app_client.set_cookie("iconbets_user", "positive-ev-track-and-hide-user")
    preview = app_client.get("/api/positive-ev?preview=1").get_json()
    row = preview["data"][2]
    quote = row["bestQuote"]
    purchase = {
        "source_id": row["id"],
        "event_title": row["eventTitle"],
        "market_title": row["marketLabel"],
        "selection": row["selection"],
        "event_start_time": row["commenceTime"],
        "sport_key": row["sportKey"],
        "league": row["league"],
        "market_key": row.get("marketKey") or row["marketLabel"],
        "market_line": quote.get("point") or row.get("line"),
        "canonical_event_id": row["eventId"],
        "american_odds": quote["topPriceAmericanOdds"],
        "stake": row["recommendedStake"],
        "fees": 0,
        "sportsbook": quote["bookName"],
        "ev_percent": row["evPercent"],
        "hide_after_track": True,
    }

    tracked = app_client.post("/api/positive-ev/personal-bets", json=purchase)

    assert tracked.status_code == 201
    assert tracked.get_json()["hidden"]["selection"] == row["selection"]
    refreshed = app_client.get("/api/positive-ev?preview=1").get_json()
    assert refreshed["total"] == 10
    assert row["id"] in {item["id"] for item in refreshed["data"]}
    hidden = app_client.get("/api/hidden-trades").get_json()
    assert hidden["total"] == 1
    assert hidden["data"][0]["selection"] == row["selection"]


def test_manual_personal_bet_rejects_invalid_price(app_client):
    response = app_client.post(
        "/api/personal-bets/manual",
        json={
            "event_title": "Example",
            "selection": "Selection",
            "entry_price": 1,
            "stake": 250,
        },
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "Entry price must be between 0 and 1."


def test_personal_tracker_filters_books_and_tags_with_separate_stats(
    app_client, monkeypatch
):
    service = app_client.application.extensions["tracker_service"]
    service._cache["trades_to_play"] = [_actionable_trade()]
    monkeypatch.setattr(service, "evaluate_recommendation", _positive_evaluation)
    monkeypatch.setattr(service, "track_recommendations_for_user", lambda *_args: 0)
    app_client.set_cookie("iconbets_user", "metadata-user")
    base = {
        "trade_id": "market-1::outcome-a",
        "entry_price": 0.4,
        "shares": 100,
        "fees": 1,
    }

    first = app_client.post(
        "/api/personal-bets",
        json={**base, "sportsbook": "DraftKings", "tags": ["Tennis", "Value"]},
    )
    second = app_client.post(
        "/api/personal-bets",
        json={
            **base,
            "sportsbook": "FanDuel",
            "tags": ["Tennis", "Live"],
            "confirm_duplicate": True,
        },
    )
    assert first.status_code == 201
    assert second.status_code == 201
    service.database.update_personal_bet_status(
        first.get_json()["data"]["fill_id"], "won", "Won", "2026-07-14T20:00:00+00:00"
    )
    service.database.update_personal_bet_status(
        second.get_json()["data"]["fill_id"], "lost", "Lost", "2026-07-14T21:00:00+00:00"
    )

    combined = app_client.get("/api/personal-tracker").get_json()
    draftkings = app_client.get(
        "/api/personal-tracker?sportsbook=DraftKings"
    ).get_json()
    live_tag = app_client.get("/api/personal-tracker?tag=Live").get_json()
    options = app_client.get("/api/personal-tracker/options").get_json()["data"]

    assert combined["summary"]["total_tracked_bets"] == 2
    assert combined["summary"]["wins"] == 1
    assert combined["summary"]["losses"] == 1
    assert draftkings["pagination"]["total"] == 1
    assert draftkings["summary"]["wins"] == 1
    assert draftkings["summary"]["losses"] == 0
    assert draftkings["data"][0]["sportsbook"] == "DraftKings"
    assert live_tag["pagination"]["total"] == 1
    assert live_tag["summary"]["losses"] == 1
    assert live_tag["data"][0]["tags"] == ["Tennis", "Live"]
    assert options["sportsbooks"] == ["DraftKings", "FanDuel"]
    assert options["tags"] == ["Live", "Tennis", "Value"]


def test_personal_tracker_rejects_invalid_tag_metadata(app_client, monkeypatch):
    service = app_client.application.extensions["tracker_service"]
    service._cache["trades_to_play"] = [_actionable_trade()]
    monkeypatch.setattr(service, "evaluate_recommendation", _positive_evaluation)
    monkeypatch.setattr(service, "track_recommendations_for_user", lambda *_args: 0)

    response = app_client.post(
        "/api/personal-bets",
        json={
            "trade_id": "market-1::outcome-a",
            "entry_price": 0.4,
            "shares": 100,
            "tags": [f"tag-{index}" for index in range(9)],
        },
    )

    assert response.status_code == 400
    assert "no more than 8 tags" in response.get_json()["error"]


def test_opposing_personal_fill_requires_explicit_confirmation(app_client, monkeypatch):
    service = app_client.application.extensions["tracker_service"]
    recommended = _actionable_trade()
    opposing = {
        **_actionable_trade(),
        "id": "market-1::outcome-b",
        "outcome": "France",
        "clob_token_id": "outcome-b",
        "validation_ids": {
            **_actionable_trade()["validation_ids"],
            "outcome_token_id": "outcome-b",
        },
    }
    service._cache["trades_to_play"] = [recommended, opposing]
    monkeypatch.setattr(service, "evaluate_recommendation", _positive_evaluation)
    monkeypatch.setattr(service, "track_recommendations_for_user", lambda *_args: 0)
    app_client.set_cookie("iconbets_user", "conflict-user")
    payload = {"entry_price": 0.4, "shares": 100, "fees": 0}
    assert (
        app_client.post(
            "/api/personal-bets",
            json={**payload, "trade_id": "market-1::outcome-b"},
        ).status_code
        == 201
    )

    blocked = app_client.post(
        "/api/personal-bets",
        json={**payload, "trade_id": "market-1::outcome-a"},
    )
    confirmed = app_client.post(
        "/api/personal-bets",
        json={
            **payload,
            "trade_id": "market-1::outcome-a",
            "confirm_conflict": True,
        },
    )

    assert blocked.status_code == 409
    assert blocked.get_json()["confirmationRequired"] == "conflict"
    assert confirmed.status_code == 201
def test_personal_workspace_positions_sell_and_ownership(app_client, monkeypatch):
    service = app_client.application.extensions["tracker_service"]
    service._cache["trades_to_play"] = [_actionable_trade()]
    monkeypatch.setattr(service, "evaluate_recommendation", _positive_evaluation)
    monkeypatch.setattr(service, "track_recommendations_for_user", lambda *_args: 0)
    monkeypatch.setattr(
        service.client,
        "get_order_books",
        lambda _ids: {
            "outcome-a": {
                "bids": [{"price": 0.5, "size": 200}],
                "timestamp": "2026-07-15T12:00:00+00:00",
            }
        },
        raising=False,
    )
    monkeypatch.setattr(
        service.client,
        "get_price_history",
        lambda *_args, **_kwargs: [{"t": 1, "p": "0.5"}],
        raising=False,
    )
    app_client.set_cookie("iconbets_user", "workspace-user")
    purchase = app_client.post(
        "/api/personal-bets",
        json={"trade_id": "market-1::outcome-a", "entry_price": 0.4, "shares": 100, "fees": 1},
    )
    assert purchase.status_code == 201

    open_payload = app_client.get("/api/personal-positions?state=open").get_json()
    position = open_payload["data"][0]
    assert open_payload["counts"] == {"positions": 1, "closed": 0}
    assert position["quote"]["effectiveSellPrice"] == 0.5
    assert position["unrealizedPnl"] == 9
    assert (
        app_client.get(
            f"/api/personal-positions/{position['positionId']}/price-history"
        ).status_code
        == 200
    )

    other_user = app_client.application.test_client()
    other_user.set_cookie("iconbets_user", "other-workspace-user")
    assert other_user.get("/api/personal-positions?state=all").get_json()["data"] == []
    forbidden = other_user.post(
        f"/api/personal-positions/{position['positionId']}/exits",
        json={"shares": 100, "sell_price": 0.5, "fees": 0, "idempotency_key": "other-1"},
    )
    assert forbidden.status_code == 404
    assert (
        other_user.get(
            f"/api/personal-positions/{position['positionId']}/price-history"
        ).status_code
        == 404
    )

    partial = app_client.post(
        f"/api/personal-positions/{position['positionId']}/exits",
        json={"shares": 25, "sell_price": 0.5, "fees": 0.5, "idempotency_key": "sell-1"},
    )
    assert partial.status_code == 201
    remaining = app_client.get("/api/personal-positions?state=open").get_json()["data"][0]
    assert remaining["remainingShares"] == 75
    assert remaining["status"] == "partially_sold"

    full = app_client.post(
        f"/api/personal-positions/{position['positionId']}/exits",
        json={"shares": 75, "sell_price": 0.6, "fees": 0, "idempotency_key": "sell-2"},
    )
    assert full.status_code == 201
    assert app_client.get("/api/personal-positions?state=open").get_json()["data"] == []
    closed = app_client.get("/api/personal-positions?state=closed&closure=sold").get_json()
    assert closed["counts"] == {"positions": 0, "closed": 1}
    assert closed["data"][0]["realizedPnl"] == 16
    summary = app_client.get("/api/personal-pnl?period=all").get_json()["data"]
    assert summary["realizedPnl"] == pytest.approx(16)
    assert summary["timezone"] == "America/New_York"
