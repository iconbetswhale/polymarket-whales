from pathlib import Path


TEMPLATE = Path("templates/middles.html").read_text(encoding="utf-8")
BASE = Path("templates/base.html").read_text(encoding="utf-8")
CSS = Path("static/middles.css").read_text(encoding="utf-8")
SCRIPT = Path("static/middles.js").read_text(encoding="utf-8")


def test_middles_is_a_canonical_v2_route_in_the_shared_shell() -> None:
    assert "page == 'middles'" in BASE
    assert "url_for('middles_page'" in BASE
    assert "ph-arrows-in-line-horizontal" in BASE
    assert "middles.css" in BASE
    assert "middles.js" in BASE
    assert "'middles'" in BASE


def test_middles_exposes_the_complete_scan_plan_and_filter_workflow() -> None:
    for required in (
        'id="mid-search"',
        'id="mid-stake"',
        'id="mid-stake-mode"',
        'id="mid-filter-dialog"',
        'id="mid-feed"',
        'id="mid-detail"',
        'id="mid-book-grid"',
        'id="mid-required-book-trigger"',
        'id="mid-sport-trigger"',
        'id="mid-sort-trigger"',
        'id="mid-min-width"',
        'id="mid-max-cost"',
        'id="mid-commission"',
        'id="mid-distinct-books"',
        'id="mid-learn-dialog"',
        'id="mid-track-dialog"',
        'id="mid-track-legs"',
        'id="mid-recalculate-dialog"',
    ):
        assert required in TEMPLATE


def test_middles_visuals_use_iconlabs_tokens_and_real_icon_assets() -> None:
    assert "var(--il-bg-workspace" in CSS
    assert "var(--il-brand" in CSS
    assert "var(--il-positive" in CSS
    assert "--mid-card: var(--mid-bg)" in CSS
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
        "function openTracker",
        "function applyTrackerAction",
        "function restoreSelected",
        "showModal()",
        'data-mid-id',
    ):
        assert required in SCRIPT


def test_middles_comparison_always_sorts_each_side_by_best_price() -> None:
    assert "function quotePrice(quote)" in SCRIPT
    assert "function sortQuotesByBestPrice(quotes, selectedBookKey)" in SCRIPT
    assert "quotePrice(right.quote) - quotePrice(left.quote)" in SCRIPT
    assert "left.quote.bookKey === selectedBookKey" in SCRIPT
    assert "sortQuotesByBestPrice(group.quotes, group.bestBookKey)" in SCRIPT
    assert "Best price first" in SCRIPT
    assert "IconLabsLineShopOrder?.sortRows" not in SCRIPT
    assert "IconLabsLineShopOrder?.bindDrag" not in SCRIPT
    assert 'draggable="true"' not in SCRIPT


def test_middles_detail_matchup_and_bet_links_match_low_hold_behavior() -> None:
    assert 'class="mid-detail-matchup"' in SCRIPT
    assert 'rel="noopener noreferrer" aria-label="Bet ${esc(leg.selection)} at ${esc(leg.bookName)}"' in SCRIPT
    assert '.mid-detail-header .mid-detail-team > span' in CSS
    assert 'font: inherit' in CSS
    assert '.mid-book-link:hover' in CSS
    assert 'background: rgba(80, 217, 119, .08)' in CSS


def test_middles_polish_keeps_the_requested_information_hierarchy() -> None:
    assert "mid-summary-metrics" in TEMPLATE
    assert 'id="mid-summary-books"' in TEMPLATE
    assert "Books compared" in TEMPLATE
    assert TEMPLATE.count("mid-summary-count") == 1
    assert TEMPLATE.index('id="mid-detail"') < TEMPLATE.index('id="mid-feed"')
    assert 'class="mid-feed-footer"' in TEMPLATE
    assert 'id="mid-sort"' in TEMPLATE
    assert "mid-queue-rank" in SCRIPT
    assert "queueDateParts" in SCRIPT
    assert "Equalized Bets" in SCRIPT
    assert '<h3>Payout Scenarios</h3>' in SCRIPT
    assert '<h3>Available Odds</h3>' in SCRIPT
    assert "qualified windows" not in TEMPLATE
    assert "RANKED BY LOWEST BREAK-EVEN" not in TEMPLATE
    assert "BOTH WIN" not in SCRIPT
    assert '<dt>Best case</dt><dd class="positive">${signedMoney(row.middleProfit)}</dd>' in SCRIPT


def test_payout_scenarios_render_an_accessible_range_map() -> None:
    for required in (
        'class="mid-range-map" role="img"',
        'class="mid-range-labels"',
        'class="mid-range-zone mid-range-middle"',
        'class="mid-range-scale"',
        'class="ph ph-record mid-range-marker edge start"',
        'class="ph ph-record mid-range-marker low"',
        "function payoutRangeMap",
        "Both bets win",
    ):
        assert required in SCRIPT
    for required in (
        ".mid-range-layout",
        ".mid-range-track",
        "grid-template-columns: 3fr 4fr 3fr",
        "background: rgba(80, 217, 119, .10)",
        "background: rgba(255, 82, 91, .09)",
        "overflow-x: auto",
        ".mid-available-odds .mid-quote-groups",
        "grid-template-columns: repeat(2, minmax(0, 1fr))",
        ".mid-available-odds .mid-quote-row.best",
        "box-shadow: inset 0 0 0 1px var(--mid-purple), 0 0 12px rgba(141, 68, 246, .32)",
        ".mid-plan-head span:nth-child(3)",
        ".mid-plan-payout { color: var(--mid-green); text-align: center; font-size: 15px",
        ".mid-plan-odds { font-size: 16px; }",
        ".mid-plan-stake strong { color: var(--mid-text); font-size: 15px; }",
    ):
        assert required in CSS


def test_middles_filter_dialog_matches_the_low_hold_workspace_pattern() -> None:
    for required in (
        'class="mid-dialog mid-filter-dialog"',
        'class="mid-selection-summary"',
        'data-mid-filter-tab="saved"',
        'data-mid-filter-tab="sportsbooks"',
        'data-mid-filter-tab="middle"',
        'data-mid-filter-tab="markets"',
        'data-mid-filter-tab="warnings"',
        'data-mid-book-group="popular"',
        'id="mid-save-filter"',
        'id="mid-dialog-stake"',
        'id="mid-books-clear-top"',
        'Reset Defaults',
        'Show Opportunities',
    ):
        assert required in TEMPLATE
    for required in (
        ".mid-filter-shell",
        "grid-template-columns: 210px minmax(0, 1fr)",
        ".mid-filter-nav",
        ".mid-filter-panels",
        ".mid-book-pills",
        ".mid-stake-mode-grid",
        ".mid-saved-list",
    ):
        assert required in CSS
    for required in (
        "function filteredBookCatalog",
        "function renderSavedFilters",
        "function saveFilter",
        "function loadSaved",
        "function deleteSaved",
        "function openFilter",
    ):
        assert required in SCRIPT


def test_middles_matches_the_arbitrage_workspace_geometry_and_controls() -> None:
    for required in (
        'class="mid-eyebrow">MIDDLE WINDOWS',
        'class="mid-summary mid-summary-metrics il-kpi-strip"',
        'id="mid-result-copy"',
        'id="mid-stake" type="text" value="1,000"',
        '<option value="total">Total Bet</option>',
        '<option value="first-leg">Baseline Amount</option>',
        'aria-label="Total Bet"',
        'ph ph-faders-horizontal',
    ):
        assert required in TEMPLATE
    for required in (
        'padding: 14px 18px 16px',
        'grid-template-columns: minmax(420px, 1fr) minmax(550px, 720px)',
        'repeat(4, var(--il-control-height, 44px))',
        'grid-template-columns: repeat(4, minmax(0, 1fr))',
        'grid-template-columns: minmax(620px, 1.7fr) minmax(340px, .76fr)',
        '.mid-detail { grid-column: 1; grid-row: 1; }',
        'grid-template-rows: auto minmax(0, 1fr) auto',
        'grid-template-columns: 28px 74px minmax(130px, 1fr) 76px',
        'min-height: 76px',
        'grid-template-columns: minmax(520px, 1fr) 350px',
    ):
        assert required in CSS
    assert "function stakeInputValue" in SCRIPT
    assert "function stakeInputNumber" in SCRIPT
    assert "function syncStakeModeUI" in SCRIPT
    assert 'params.set("stake_mode", state.stakeMode)' in SCRIPT
    assert "function leagueLogoUrl" in SCRIPT
    assert "function detailMatchup" in SCRIPT
    assert "function queueLeagueVisual" in SCRIPT
    assert "function toggleAlerts" in SCRIPT
    assert '"cost-asc", "width-desc", "profit-desc", "time-asc"' in SCRIPT
    assert 'window.matchMedia("(max-width: 1080px)")' in SCRIPT
    assert "live-arbitrage-v6" in BASE


def test_middles_track_hide_workflow_and_feed_views_match_the_requested_contract() -> None:
    for required in (
        'data-mid-view="live"',
        'data-mid-view="hidden"',
        'id="mid-live-count"',
        'id="mid-hidden-count"',
        'id="mid-track-dialog"',
        'id="mid-track-summary"',
        'id="mid-track-legs"',
        'id="mid-track-proof"',
        'data-mid-track-action="track"',
        'data-mid-track-action="hide"',
        'data-mid-track-action="track-hide"',
        'id="mid-recalculate-dialog"',
        'id="mid-recalculate-mode"',
        'id="mid-recalculate-total"',
        'id="mid-recalculate-legs"',
        'id="mid-recalculate-proof"',
        "Track</button>",
        "Hide</button>",
        "Track and Hide</button>",
        "Keep total bet fixed</option>",
        "Lock one side</option>",
    ):
        assert required in TEMPLATE
    assert "Pre-Match" not in TEMPLATE
    for required in (
        'const hiddenKey = "iconlabsHiddenMiddlesV1"',
        'const trackedPlanKey = "iconlabsTrackedMiddlePlansV1"',
        'view: "live"',
        "function setView",
        "function calculateEditablePlan",
        "function refreshTrackPlan",
        "function applyTrackerAction",
        "function openRecalculateDialog",
        "function refreshCalculatorPlan",
        "function resetCalculator",
        'state.hidden.add(id)',
        'state.hidden.delete(String(state.selectedId))',
        "Track/Hide</button>",
        "Recalculate</button>",
        "Restore</button>",
    ):
        assert required in SCRIPT
    for required in (
        ".mid-action-dialog",
        "width: min(920px, calc(100vw - 32px))",
        ".mid-action-summary",
        ".mid-leg-editor-row",
        ".mid-action-proof",
        ".mid-action-footer",
        ".mid-recalculate-editor .mid-leg-editor-row",
        ".mid-leg-editor-row.is-locked",
        "justify-content: flex-end",
    ):
        assert required in CSS


def test_middles_kpis_actions_and_surfaces_use_the_requested_layout() -> None:
    for required in (
        'body[data-page="middles"] .mid-summary article,',
        'justify-content: flex-start',
        'grid-template-columns: repeat(3, minmax(0, 1fr))',
        '.mid-detail-actions .mid-button',
        'width: 100%',
        'background: var(--mid-bg)',
    ):
        assert required in CSS


def test_middles_uses_low_hold_quick_selects_and_matchup_identity() -> None:
    for required in (
        'data-mid-quick-select="required-book"',
        'aria-label="Required sportsbook"',
        'data-mid-quick-select="sport"',
        'data-mid-quick-select="sort"',
        "Any selected book",
    ):
        assert required in TEMPLATE
    for required in (
        "function renderQuickSelect",
        "function toggleQuickSelect",
        "function chooseQuickOption",
        'params.set("required_book", state.requiredBook)',
        '(row.booksUsed || []).includes(state.requiredBook)',
        "data-mid-quick-option",
        "mid-queue-league-logo",
        "mid-team-logo-frame",
    ):
        assert required in SCRIPT
    for required in (
        "grid-template-columns: minmax(0, 1.3fr) minmax(0, .8fr) minmax(0, 1fr)",
        ".mid-quick-select-trigger",
        ".mid-quick-select-menu",
        ".mid-queue-league-logo",
        ".mid-detail-matchup",
        ".mid-team-logo-frame > img",
        "white-space: nowrap",
    ):
        assert required in CSS
    assert "Scan status" not in TEMPLATE
    assert "Equalized Stakes" not in SCRIPT
    assert ">Stake<" not in SCRIPT


def test_middles_stake_control_and_payout_type_follow_the_requested_scale() -> None:
    for required in (
        'grid-template-columns: minmax(210px, 1fr) 172px repeat(4, var(--il-control-height, 44px))',
        'grid-template-rows: 17px minmax(0, 1fr)',
        '.mid-stake-control > span:first-child select',
        'font: 700 17px/19px "DM Sans", sans-serif',
        '.mid-range-summary span { font-size: 12px; }',
        '.mid-range-summary strong { font-size: 17px; }',
        '.mid-range-summary small { font-size: 12px; }',
        'font-size: 13px',
        'margin: 0 1px 13px',
        '.mid-range-scale .low { left: 30%; color: var(--mid-text); font-size: 14px; }',
    ):
        assert required in CSS


def test_sportsbook_logos_are_normalized_and_fail_safely() -> None:
    assert 'decoding="async"' in SCRIPT
    assert "mid-book-logo-fallback" in SCRIPT
    assert "onerror=" in SCRIPT
    assert "object-fit: contain" in CSS
    assert "object-position: center" in CSS
    assert ".mid-book-logo {" in CSS
    assert "background: transparent" in CSS
    assert "border: 0" in CSS
    assert "padding: 0" in CSS
    assert ".mid-book-logo-fallback" in CSS
    assert "background: var(--il-surface-selected-badge)" in CSS
