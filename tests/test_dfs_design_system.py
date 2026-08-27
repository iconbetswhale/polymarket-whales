from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "templates" / "dfs.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "static" / "dfs.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "dfs-v2.css").read_text(encoding="utf-8")


def test_dfs_opts_into_v2_without_legacy_layers(app_client) -> None:
    response = app_client.get("/dfs?preview=1")

    assert response.status_code == 200
    assert b'data-page="dfs" data-design-system="v2"' in response.data
    assert b"design-system.css" in response.data
    assert b"dfs.css" in response.data
    assert b"dfs-v2.css" in response.data
    assert b"legacy-design-system.css" not in response.data
    assert b"stage2-art-direction.css" not in response.data
    assert b"shared-shell.css" not in response.data
    assert b"mobile-product.css" not in response.data
    assert b"app-premium.css" not in response.data
    assert b"sidebar-shell.css" not in response.data


def test_dfs_preview_parameters_cannot_enable_fixture_rows(app_client) -> None:
    attempted_preview = app_client.get("/dfs?preview=1")
    demo = app_client.get("/dfs?demo=1")
    regular = app_client.get("/dfs")

    assert attempted_preview.data == regular.data
    assert demo.data == regular.data
    assert b"data-dfs-preview" not in regular.data
    assert b"temporary optimizer props" not in regular.data
    assert b"Visual fixtures only" not in regular.data
    assert "`/api/dfs/lines?${params}`" in SCRIPT
    assert "readPagePayloadCache(cacheKey" in SCRIPT
    assert "writePagePayloadCache(cacheKey,payload)" in SCRIPT
    assert "loadLiveRows();" in SCRIPT
    assert "isPreview" not in SCRIPT
    assert "supplementalPreviewRows" not in SCRIPT
    assert "Aaron Judge" not in SCRIPT
    assert "price === undefined" in SCRIPT
    assert "unavailable?'—'" in SCRIPT


def test_dfs_reuses_canonical_primitives() -> None:
    for hook in (
        "il-data-grid-page",
        "il-page-header",
        "il-page-title",
        "il-data-grid",
        "il-filter-bar",
        "icon-button",
    ):
        assert hook in TEMPLATE


def test_dfs_v2_uses_shared_tokens_and_real_assets() -> None:
    assert 'body[data-design-system="v2"][data-page="dfs"]' in CSS
    for token in (
        "--il-bg-app",
        "--il-surface-1",
        "--il-border-subtle",
        "--il-text-primary",
        "--il-brand",
        "--il-positive",
        "--il-font-ui",
        "--il-radius-panel",
    ):
        assert f"var({token})" in CSS
    assert "gradient(" not in CSS
    assert "assets/dfs-books/" in TEMPLATE
    assert "IconLabs Algo Odds using default weights" in TEMPLATE
    assert "fairAmericanOdds" in SCRIPT
    assert "americanOddsToProbability" in SCRIPT
    assert "positive-edge" in SCRIPT
    assert "near-threshold" in SCRIPT
    assert "negative-edge" in SCRIPT
    assert ".hit-rate.positive-edge" in CSS
    assert ".hit-rate.near-threshold" in CSS
    assert ".hit-rate.negative-edge" in CSS


def test_dfs_v2_keeps_responsive_and_interactive_contracts() -> None:
    assert "@media (max-width: 700px)" in CSS
    assert ".dfs-table-shell" in CSS
    assert "overflow: auto" in CSS
    assert "#dfs-devig-open" in SCRIPT
    assert "#dfs-discrepancies" not in SCRIPT
    assert "#dfs-search" in SCRIPT
    assert "#dfs-refresh').addEventListener('click', () => loadLiveRows())" in SCRIPT
    assert "devigDialog.showModal()" in SCRIPT


def test_dfs_live_pause_controls_refresh_immediately_and_never_overlap() -> None:
    assert 'id="dfs-live" aria-pressed="true"' in TEMPLATE
    assert 'id="dfs-pause" aria-pressed="false"' in TEMPLATE
    assert "250 live props" not in TEMPLATE
    assert "updated just now" not in SCRIPT
    assert "setLiveRefresh(true)" in SCRIPT
    assert "setLiveRefresh(false)" in SCRIPT
    assert "if (!enabled)" in SCRIPT
    assert "loadLiveRows();" in SCRIPT
    assert "if (activeLoad?.signature === signature) return activeLoad.promise;" in SCRIPT
    assert "window.setTimeout(loadLiveRows,refreshDelayMs)" in SCRIPT
    assert "window.setInterval" not in SCRIPT


def test_dfs_initial_request_uses_loading_state_and_sorts_displayed_hit_rate() -> None:
    assert 'id="dfs-loading" role="status"' in TEMPLATE
    assert 'id="dfs-error" hidden' in TEMPLATE
    assert "loadingState.hidden = hasLoadedRows || loadFailed;" in SCRIPT
    assert "emptyState.hidden = !hasLoadedRows || loadFailed || visible.length > 0;" in SCRIPT
    assert ".sort(compareByHitRate)" in SCRIPT
    assert "if (aHit !== null && bHit !== null && bHit !== aHit) return bHit-aHit;" in SCRIPT


def test_dfs_is_prewarmed_before_navigation_when_possible() -> None:
    assert "dfs-prewarm-v1" in BASE
    assert "prewarmFantasyOptimizer" in (ROOT / "static" / "app.js").read_text(encoding="utf-8")


def test_dfs_assets_load_after_the_v2_foundation() -> None:
    foundation = BASE.index("filename='design-system.css'")
    canonical = BASE.index("filename='dfs-v2.css'", foundation)
    script = BASE.index("filename='dfs.js'")

    assert canonical > foundation
    assert "-filters-v2" in BASE[canonical : canonical + 160]
    assert "-live-only-v2-undefined-guard" in BASE[script : script + 160]


def test_dfs_rows_use_the_same_alternating_purple_treatment_as_odds_screen() -> None:
    assert ".dfs-table tbody tr:nth-child(even) td" in CSS
    assert "background: rgba(141, 68, 246, .08)" in CSS
    assert ".dfs-table tbody tr:hover td" in CSS
    assert "background: rgba(139, 92, 246, .32)" in CSS


def test_prizepicks_and_iconlabs_columns_inherit_the_row_backgrounds() -> None:
    assert '.selected-line {\n  background: var(--il-surface-1) !important;' in CSS
    assert ".dfs-table tbody tr td.algo-odds-cell" in CSS
    assert ".dfs-table tbody tr:nth-child(even) td.selected-line" in CSS
    assert ".dfs-table tbody tr:nth-child(even) td.algo-odds-cell" in CSS
    assert ".dfs-table tbody tr:hover td.selected-line" in CSS
    assert ".dfs-table tbody tr:hover td.algo-odds-cell" in CSS


def test_iconlabs_fair_odds_uses_the_current_white_mark() -> None:
    assert "assets/iconlabs-mark-transparent-v3.png" in TEMPLATE
    assert '.algo-odds-head img,\nbody[data-design-system="v2"][data-page="dfs"] .compare-book img' in CSS


def test_iconlabs_fair_odds_logo_explains_the_weightings_on_hover() -> None:
    assert 'class="dfs-algo-tooltip"' in TEMPLATE
    assert 'aria-label="IconLabs Algo Odds using default weights"' in TEMPLATE
    assert 'id="dfs-iconalgo-tooltip"' in TEMPLATE
    assert ".dfs-iconalgo-tooltip-popover" in CSS
    assert "position: fixed;" in CSS
    assert "showIconAlgoTooltip" in SCRIPT
    assert "getBoundingClientRect()" in SCRIPT


def test_fantasy_app_selector_matches_grouped_reference_and_uses_brand_accents() -> None:
    assert 'class="dfs-app-selector"' in TEMPLATE
    assert 'id="dfs-fantasy-apps-label">Fantasy Apps' in TEMPLATE
    assert 'id="dfs-optimizer-label">Optimizer' in TEMPLATE
    assert 'class="dfs-optimizer-actions"' in TEMPLATE
    for book_key in ("prizepicks", "underdog", "dk-pick6", "betr", "dabble"):
        assert f'data-book-key="{{{{ logo }}}}"' in TEMPLATE or book_key in TEMPLATE
        assert f'.dfs-book[data-book-key="{book_key}"]' in CSS
    assert "--dfs-book-accent" in CSS
    assert "background: var(--dfs-book-accent-soft" in CSS
    assert "padding-top: 14px;" in CSS


def test_iconlabs_column_matches_book_width_and_alternate_line_does_not_shift_odds() -> None:
    assert '.algo-odds-head,\nbody[data-design-system="v2"][data-page="dfs"] .algo-odds-cell' in CSS
    assert "width: 88px;" in CSS
    assert "min-width: 88px;" in CSS
    assert "max-width: 88px;" in CSS
    assert "alternateLine===null?'':'has-alternate'" in SCRIPT
    assert ".book-cell.has-alternate > strong" in CSS
    assert "top: 50%;" in CSS
    assert ".book-cell.has-alternate .alternate-line" in CSS
    assert "top: calc(50% + 12px);" in CSS


def test_devig_custom_weights_replace_iconlabs_odds_and_hit_rate() -> None:
    assert "return {...defaultWeights};" in SCRIPT
    assert "validKeys && total === 100" in SCRIPT
    assert "total === 0 || total === 100" not in SCRIPT
    assert "const fairHitRate = fairProbability(r,activeLine);" in SCRIPT
    assert "fairAmericanOdds(fairHitRate)" in SCRIPT
    assert "Your Odds using custom Devig Settings" in SCRIPT
    assert "Your Odds from custom Devig weights" in SCRIPT
    assert "You’re changing IconLabs Algo Odds to Your Odds." in TEMPLATE
    assert "recalculates both Chance to Hit and the fair odds" in TEMPLATE
    assert 'class="ph ph-warning"' in TEMPLATE
    assert ".dfs-devig-impact" in CSS
    assert "white-space: nowrap;" in CSS
    assert "background: rgba(255, 193, 40, .2);" in CSS
    assert "color: #ffdd67;" in CSS


def test_selected_dfs_line_never_renders_slip_odds_underneath() -> None:
    assert "selectedSlipOdds" not in SCRIPT
    assert "selected-slip-odds" not in SCRIPT
    assert "selected-slip-odds" not in CSS
    assert '<td class="selected-line"><strong>${esc(lineDisplay)}</strong></td>' in SCRIPT


def test_parlay_type_guide_matches_the_supplied_rankings_and_is_interactive() -> None:
    assert 'id="dfs-parlay-guide-open"' in TEMPLATE
    assert 'aria-label="Best Parlay Type To Build?"' in TEMPLATE
    assert 'id="dfs-parlay-guide-dialog"' in TEMPLATE
    assert "4 Man Flex (Underdog) (-107)" in TEMPLATE
    assert "51.7%" in TEMPLATE
    assert "2 Man Flex (Underdog) (-116)" in TEMPLATE
    assert "3 Man Flex (Underdog) (-116)" in TEMPLATE
    assert "53.7%" in TEMPLATE
    assert "5 Pick Flex (-119)" in TEMPLATE
    assert "6 Pick Flex (-119)" in TEMPLATE
    assert "6 Pick Power (-121)" in TEMPLATE
    assert "3 Pick Power (-122)" in TEMPLATE
    assert "4 Pick Power (-128)" in TEMPLATE
    assert "2 Pick Power (-136)" in TEMPLATE
    assert "3 Pick Flex (-137)" in TEMPLATE
    assert "57.8%" in TEMPLATE
    assert "parlayGuideDialog.showModal()" in SCRIPT
    assert "event.target === parlayGuideDialog" in SCRIPT
    assert "event.key === 'Escape' && parlayGuideDialog.open" in SCRIPT
    assert ".dfs-parlay-guide-button" in CSS
    assert ".dfs-parlay-rankings" in CSS


def test_parlay_equivalent_odds_match_each_required_hit_rate() -> None:
    rows = (
        (51.7, -107),
        (53.7, -116),
        (53.7, -116),
        (54.3, -119),
        (54.3, -119),
        (54.8, -121),
        (55.0, -122),
        (55.0, -122),
        (55.0, -122),
        (56.1, -128),
        (57.6, -136),
        (57.8, -137),
    )

    for hit_rate, displayed_odds in rows:
        equivalent_odds = round(-100 * hit_rate / (100 - hit_rate))
        assert equivalent_odds == displayed_odds


def test_dfs_removes_summary_row_and_prizepicks_line_odds() -> None:
    assert "dfs-summary-row" not in TEMPLATE
    assert "Line discrepancies only" not in TEMPLATE
    assert "PrizePicks lines ranked by model edge" not in TEMPLATE
    assert "selected-slip-odds" not in SCRIPT


def test_dfs_filter_controls_share_equal_columns_and_alignment() -> None:
    assert "grid-template-columns: repeat(6, minmax(0, 1fr));" in CSS
    assert "align-items: end;" in CSS
    assert "justify-content: center;" in CSS
    assert "min-height: var(--il-control-height-compact);" in CSS


def test_dfs_prop_typography_and_stat_alignment() -> None:
    assert "font: 700 15px/1.2 var(--il-font-ui);" in CSS
    assert "font: 500 12px/1.2 var(--il-font-ui);" in CSS
    assert "font: 500 11px/1.2 var(--il-font-ui);" in CSS
    assert "font: 700 13px/1 var(--il-font-data);" in CSS
    assert "font: 650 14px/1.25 var(--il-font-ui);" in CSS
    assert "margin-inline: auto;" in CSS
    assert "text-align: center;" in CSS

