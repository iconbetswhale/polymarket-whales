from pathlib import Path


TEMPLATE = Path("templates/low_hold.html").read_text(encoding="utf-8")
BASE = Path("templates/base.html").read_text(encoding="utf-8")
CSS = Path("static/low-hold.css").read_text(encoding="utf-8")
SCRIPT = Path("static/low-hold.js").read_text(encoding="utf-8")


def test_low_hold_is_a_canonical_v2_route_in_the_shared_shell() -> None:
    assert "page == 'low-hold'" in BASE
    assert "url_for('low_hold_page'" in BASE
    assert "ph-percent" in BASE
    assert "low-hold.css" in BASE
    assert "low-hold.js" in BASE
    assert "'arbitrage'" in BASE
    assert "'low-hold'" in BASE
    assert "'sharp-money'" in BASE


def test_low_hold_page_exposes_the_complete_master_detail_workflow() -> None:
    for required in (
        'id="lh-search"',
        'id="lh-stake"',
        'id="lh-stake-mode"',
        'id="lh-dialog-stake-label"',
        'id="lh-filter-dialog"',
        'id="lh-feed"',
        'id="lh-detail"',
        'id="lh-book-grid"',
        'id="lh-max-hold"',
        'id="lh-min-odds"',
        'id="lh-max-odds"',
        'id="lh-min-distance"',
        'id="lh-learn-dialog"',
        'id="lh-save-filter"',
        'id="lh-required-book-trigger"',
        'id="lh-required-book-menu"',
    ):
        assert required in TEMPLATE


def test_low_hold_visuals_use_iconlabs_tokens_and_phosphor_icons() -> None:
    assert "var(--il-bg-app" in CSS
    assert "var(--il-brand" in CSS
    assert "var(--il-positive" in CSS
    assert "var(--il-surface-1" in CSS
    assert "ph ph-" in TEMPLATE
    assert "<svg" not in TEMPLATE
    assert "linear-gradient" not in CSS
    assert "radial-gradient" not in CSS


def test_primary_interactions_and_visible_states_are_implemented() -> None:
    for required in (
        "function loadBoard",
        "function renderFeed",
        "function renderDetail",
        "function togglePause",
        "function renderBookGrid",
        "function renderSavedFilters",
        "function saveFilter",
        "function hideOpportunity",
        "function restoreOpportunity",
        "function syncStakeModeUI",
        "data-lh-start",
        "data-lh-retry",
        "data-lh-hide-opportunity",
        "data-lh-restore-opportunity",
        "data-lh-lock-leg",
        'params.set("stake_mode"',
        "showModal()",
    ):
        assert required in SCRIPT


def test_low_hold_comparison_always_sorts_each_side_by_best_price() -> None:
    assert "function quotePrice(quote)" in SCRIPT
    assert "function sortQuotesByBestPrice(quotes, selectedBookKey)" in SCRIPT
    assert "quotePrice(right.quote) - quotePrice(left.quote)" in SCRIPT
    assert "left.quote.bookKey === selectedBookKey" in SCRIPT
    assert "sortQuotesByBestPrice(group.quotes, selected?.bookKey)" in SCRIPT
    assert "best price first" in SCRIPT
    assert "IconLabsLineShopOrder?.sortRows" not in SCRIPT
    assert "IconLabsLineShopOrder?.bindDrag" not in SCRIPT
    assert 'draggable="true"' not in SCRIPT
    assert "quotes.slice(0, 8)" not in SCRIPT


def test_low_hold_comparison_highlight_and_market_label_are_resilient() -> None:
    assert 'body[data-page="low-hold"] .arb-quote-row.best' in CSS
    assert "box-shadow: inset 0 0 0 1px var(--arb-purple)" in CSS
    assert "background: rgba(141, 68, 246, .08)" in CSS
    assert "function marketName(row)" in SCRIPT
    assert ".toUpperCase()" in SCRIPT
    assert 'class="lh-market-fact"' in SCRIPT
    assert 'title="${renderedMarket}"' in SCRIPT
    assert "grid-template-columns: minmax(0, 1fr)" in CSS
    assert "overflow-wrap: break-word" in CSS
    assert "white-space: normal" in CSS
    assert "const context = row.marketContext" not in SCRIPT


def test_low_hold_detail_uses_team_logos_and_streamlined_board_controls() -> None:
    assert "function detailMatchup(row)" in SCRIPT
    assert "function teamForSelection(row, selection, leg = {})" in SCRIPT
    assert "window.oddsTeamLogoUrl" in SCRIPT
    assert SCRIPT.count("detailTeamLogo(row,") >= 5
    assert 'class="lh-detail-matchup"' in SCRIPT
    assert ".lh-detail-team-logo" in CSS
    assert 'class="arb-plan-outcome lh-plan-outcome"' in SCRIPT
    assert '"lh-plan-team-logo"' in SCRIPT
    assert '"lh-scenario-team-logo"' in SCRIPT
    assert 'id="lh-market-filter"' not in TEMPLATE
    assert "elements.market" not in SCRIPT
    assert "state.market" not in SCRIPT


def test_low_hold_quick_controls_use_complete_borders_and_a_required_book_listbox() -> None:
    assert TEMPLATE.index('data-lh-quick-select="required-book"') < TEMPLATE.index('data-lh-quick-select="sport"')
    assert TEMPLATE.index('data-lh-quick-select="sport"') < TEMPLATE.index('data-lh-quick-select="sort"')
    assert "Any selected book" in TEMPLATE
    assert TEMPLATE.count('aria-haspopup="listbox"') == 3
    assert ".lh-quick-select-trigger" in CSS
    assert "border: 1px solid var(--arb-line)" in CSS
    assert "top: calc(100% + 5px)" in CSS
    assert ".lh-quick-select-menu img" in CSS
    assert "function renderQuickSelect(kind, options, selectedValue)" in SCRIPT
    assert "state.requiredBook" in SCRIPT
    assert 'params.set("required_book", state.requiredBook)' in SCRIPT
    assert '[data-lh-quick-select="required-book"] .lh-quick-select-menu button' in CSS
    assert "font-size: 14px" in CSS
    assert "width: max(100%, 225px)" in CSS
    assert '[data-lh-quick-select="required-book"] .lh-quick-select-menu img' in CSS
    assert "width: 21px" in CSS


def test_sport_quick_filter_uses_league_logos_and_only_distinct_sort_choices() -> None:
    for league in ("mlb", "nba", "wnba", "nfl", "nhl", "ncaa", "mls", "epl"):
        assert f'/static/assets/leagues/{league}.png' in SCRIPT
    assert "function leagueLogoUrl(sportKey, league)" in SCRIPT
    assert "logoUrl: leagueLogoUrl(value, label)" in SCRIPT
    assert '[data-lh-quick-select="sport"] .lh-quick-select-menu button' in CSS
    assert '[data-lh-quick-select="sport"] .lh-quick-select-menu img' in CSS
    assert '[data-lh-quick-select="sport"] .lh-quick-select-menu button > i:first-child' in CSS
    assert TEMPLATE.count('name="lh-dialog-sort"') == 2
    assert "Most retained" not in TEMPLATE
    assert "Best middle payoff" not in TEMPLATE
    assert '"retained-desc"' not in SCRIPT
    assert '"middle-desc"' not in SCRIPT


def test_low_hold_uses_bet_language_and_positive_hold_guardrails() -> None:
    assert '<span>Bet</span><span>Payout</span>' in SCRIPT
    assert '<span>Total bet</span>' in SCRIPT
    assert 'aria-label="Bet sizing mode"' in TEMPLATE
    assert '>Baseline Amount</option>' in TEMPLATE
    assert '>Total Bet</option>' in TEMPLATE
    assert "function lowHoldRows(value)" in SCRIPT
    assert "Number(row?.holdPercent) >= 0" in SCRIPT
    assert "state.rows = lowHoldRows(cached.data)" in SCRIPT
    assert "state.rows = lowHoldRows(payload.data)" in SCRIPT
    assert 'Number(row.holdPercent) <= 2' in SCRIPT
    assert 'return "is-low"' in SCRIPT
    assert ".lh-hold-cell.is-low strong" in CSS


def test_low_hold_balanced_outcome_values_are_two_pixels_larger() -> None:
    assert 'body[data-page="low-hold"] .arb-guaranteed-section .arb-profit-proof strong' in CSS
    assert "font-size: 16px" in CSS


def test_low_hold_detail_typography_and_expansion_state_follow_the_requested_contract() -> None:
    assert ".lh-scenario-label > span:last-child" in CSS
    assert "font-size: 13px" in CSS
    assert ".lh-scenario-card strong" in CSS
    assert "font-size: 16px" in CSS
    assert ".lh-scenario-card small" in CSS
    assert "font-size: 12px" in CSS
    assert 'state.calculationOpen ? "open" : ""' in SCRIPT
    assert 'event.target.matches(".arb-calculation")' in SCRIPT
    assert "state.calculationOpen = event.target.open" in SCRIPT
    assert ".arb-quote-head span:nth-child(4)" in CSS
    assert ".arb-quote-row strong:first-of-type" in CSS
    assert ".arb-plan-head span:nth-child(3)" in CSS
    assert ".arb-quote-head span:nth-child(3)" in CSS
    assert ".arb-quote-row > b" in CSS
    assert ':has(.arb-calculation[open]) .arb-detail { overflow: visible; }' in CSS


def test_locked_first_leg_is_the_recommended_sizing_workflow() -> None:
    assert '<option value="first-leg">Baseline Amount</option>' in TEMPLATE
    assert '<strong>Lock baseline</strong>' in TEMPLATE
    assert "Recommended · calculate the exact hedge" in TEMPLATE
    assert 'stakeMode: "first-leg"' in SCRIPT
    assert "stake: 100" in SCRIPT
    assert "Baseline Amount · Locked" in SCRIPT
    assert "Use as Baseline" in SCRIPT


def test_bankroll_control_is_easy_to_select_and_edit() -> None:
    assert '<div class="arb-stake-control lh-stake-control">' in TEMPLATE
    assert 'autocomplete="off" aria-label="Baseline Amount"' in TEMPLATE
    assert ".lh-page .arb-toolbar" in CSS
    assert "minmax(210px, 1fr) 172px" in CSS
    assert ".lh-stake-control > span:first-child select" in CSS
    assert "max-height: 17px" in CSS
    assert ".lh-stake-control .arb-money-input input" in CSS
    assert "min-height: 0 !important" in CSS
    assert "cursor: text" in CSS


def test_calculation_details_remove_redundant_warnings_and_negative_cost_sign() -> None:
    assert "const warnings =" not in SCRIPT
    assert "${warnings}" not in SCRIPT
    assert "Worst Case Cost" in SCRIPT
    assert "money(Math.abs(Number(row.outsideNet)))" in SCRIPT
    assert "is the baseline amount" in SCRIPT
    assert "Confirm both displayed prices" in SCRIPT


def test_team_logos_have_unclipped_contrast_frames_and_original_book_styling() -> None:
    assert "body[data-page=\"low-hold\"] .lh-detail-team-logo" in CSS
    assert "lh-team-logo-frame" in SCRIPT
    assert "overflow: visible" in CSS
    assert "background: #f6f8fc" in CSS
    assert "box-shadow: 0 0 0 1px rgba(141, 68, 246, .3)" in CSS
    assert "width: calc(100% - 6px)" in CSS
    assert "height: calc(100% - 6px)" in CSS
    assert ".lh-team-logo-frame.is-wnba > img" in CSS
    assert "transform: scale(1.12)" in CSS
    assert "width: 34px" in CSS
    assert "width: 32px" in CSS
    assert ".lh-plan-team-logo {\n  width: 28px;" in CSS
    assert "width: 30px" in CSS
    assert "width: 26px" in CSS
    assert "body[data-page=\"low-hold\"] .arb-plan-book img" not in CSS


def test_player_props_resolve_the_player_team_logo_in_verification_plan() -> None:
    assert "leg?.playerTeam" in SCRIPT
    assert "teamForSelection(row, leg.selection, leg)" in SCRIPT
    assert '"playerTeam": player_team' in Path("low_hold.py").read_text(encoding="utf-8")


def test_low_hold_polish_matches_the_live_arbitrage_queue_and_detail_format() -> None:
    assert 'id="lh-kpi-opportunities"' in TEMPLATE
    assert 'id="lh-kpi-books"' in TEMPLATE
    assert TEMPLATE.count("arb-kpi-strip") == 1
    assert 'class="arb-queue-rank"' in SCRIPT
    assert 'class="arb-queue-date"' in SCRIPT
    assert 'class="arb-detail-main"' in SCRIPT
    assert 'class="arb-detail-facts"' in SCRIPT
    assert 'class="arb-plan-head"' in SCRIPT
    assert 'class="arb-guaranteed-layout"' in SCRIPT
    assert 'class="arb-quote-head"' in SCRIPT
    assert '<details class="arb-detail-section arb-calculation"' in SCRIPT
    assert "Odds Comparison" in SCRIPT
    assert "Calculation Details" in SCRIPT
    assert "Balanced Outcome" in SCRIPT
    assert '"ph-eye-slash"' in SCRIPT
    assert '"Hide Opportunity"' in SCRIPT
    assert '"Restore Opportunity"' in SCRIPT
    assert '>BET<i class="ph ph-arrow-up-right"></i>' in SCRIPT
    assert "Copy verification checklist" not in SCRIPT
    assert '>CHECK<i class="ph ph-arrow-up-right"></i>' not in SCRIPT
    assert "This is a mathematical low-hold pair, not an executable claim." in SCRIPT
    assert "Copy bet plan" not in SCRIPT
    assert "Lower is more efficient" not in TEMPLATE
    assert "Chance to win both legs" not in TEMPLATE


def test_live_and_hidden_views_persist_dismissed_opportunities_with_undo() -> None:
    assert 'aria-label="Opportunity visibility"' in TEMPLATE
    assert 'data-lh-view="live"' in TEMPLATE
    assert 'data-lh-view="hidden"' in TEMPLATE
    assert 'id="lh-live-count"' in TEMPLATE
    assert 'id="lh-hidden-count"' in TEMPLATE
    assert "data-lh-mode" not in TEMPLATE
    assert ">Exact</button>" not in TEMPLATE
    assert ">Middles</button>" not in TEMPLATE
    assert 'const hiddenKey = "iconlabsLowHoldHiddenOpportunitiesV1"' in SCRIPT
    assert "function opportunityKey(row)" in SCRIPT
    assert "function readHiddenOpportunities()" in SCRIPT
    assert "function saveHiddenOpportunities()" in SCRIPT
    assert "function pruneHiddenOpportunities()" in SCRIPT
    assert "function setOpportunityView(view)" in SCRIPT
    assert 'label: "Undo"' in SCRIPT
    assert 'data-lh-show-live' in SCRIPT
    assert ".lh-toast-action" in CSS
    assert 'body[data-page="low-hold"] .arb-detail-actions button' in CSS
    assert "white-space: nowrap" in CSS
    assert "grid-template-columns: minmax(318px, 1.55fr) minmax(194px, .7fr) 172px" in CSS
    assert "grid-template-columns: minmax(220px, 1.25fr) minmax(168px, .75fr) 168px" in CSS


def test_low_hold_inherits_arbitrage_sizing_and_formatting() -> None:
    assert "MARKET INEFFICIENCIES" in TEMPLATE
    assert TEMPLATE.count("arb-kpi-icon") == 4
    assert "--arb-card: var(--arb-bg)" in CSS
    assert "grid-template-columns: repeat(4, minmax(0, 1fr))" in CSS
    assert "padding: 14px 18px 16px" in CSS
    assert ".lh-page .arb-toolbar" in CSS
    assert ".lh-page .arb-opportunity" not in CSS
    assert ".lh-page .arb-workspace" not in CSS
    assert ".lh-page .arb-detail-hero" not in CSS
    assert TEMPLATE.index('id="lh-detail"') < TEMPLATE.index('id="lh-feed"')
    assert TEMPLATE.count('class="arb-board-actions"') == 1
    assert TEMPLATE.count('class="arb-board-footer"') == 1


def test_low_hold_rows_use_the_live_arbitrage_compact_queue_contract() -> None:
    assert "function queueDateParts" in SCRIPT
    assert "function queueLeagueVisual(row)" in SCRIPT
    assert '${queueLeagueVisual(row)}<span>${esc(row.eventTitle)}</span>' in SCRIPT
    assert 'class="lh-queue-league-logo"' in SCRIPT
    assert ".lh-queue-league-logo" in CSS
    assert "width: 28px" in CSS
    assert "flex: 0 0 28px" in CSS
    assert 'body[data-page="low-hold"] .lh-hold-cell' in CSS
    assert "padding-left: 4px" in CSS
    assert "padding-right: 12px" in CSS
    assert "lh-queue-league-watermark" not in SCRIPT
    assert "lh-queue-league-watermark" not in CSS
    assert 'grid-template-columns: repeat(4, minmax(0, 1fr))' in CSS
    assert 'class="arb-event-cell"' in SCRIPT
    assert 'class="arb-return-cell lh-hold-cell' in SCRIPT
    assert "arb-leg-summary" not in SCRIPT
    assert "arb-market-cell" not in SCRIPT
    assert "arb-legs-cell" not in SCRIPT
