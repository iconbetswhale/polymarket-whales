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


def test_dfs_header_is_compact_and_has_no_marketing_subtitle() -> None:
    assert "Find the strongest projection edge" not in TEMPLATE
    assert "padding: 8px var(--il-gutter-desktop) var(--il-gutter-desktop)" in CSS
    assert "min-height: 52px" in CSS
    assert "padding: 64px 0 0 !important" not in CSS
    assert "padding: 0 !important" in CSS


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
    assert "IconLabs Algo Odds active" in TEMPLATE
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
    assert "dfs-quality-prewarm" in BASE
    assert "prewarmFantasyOptimizer" in (ROOT / "static" / "app.js").read_text(encoding="utf-8")


def test_dfs_assets_load_after_the_v2_foundation() -> None:
    foundation = BASE.index("filename='design-system.css'")
    canonical = BASE.index("filename='dfs-v2.css'", foundation)
    script = BASE.index("filename='dfs.js'")

    assert canonical > foundation
    assert "-quality-guardrails-v3" in BASE[canonical : canonical + 160]
    assert "-quality-guardrails-v4" in BASE[script : script + 160]


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
    assert 'aria-label="IconLabs Algo Odds active"' in TEMPLATE
    assert 'id="dfs-iconalgo-tooltip"' in TEMPLATE
    assert ".dfs-iconalgo-tooltip-popover" in CSS
    assert "position: fixed;" in CSS
    assert "showIconAlgoTooltip" in SCRIPT
    assert "getBoundingClientRect()" in SCRIPT
    tooltip_start = CSS.index(".dfs-algo-tooltip {")
    tooltip_block = CSS[tooltip_start : CSS.index("}", tooltip_start)]
    assert "cursor: default;" in tooltip_block
    assert "cursor: help;" not in tooltip_block


def test_fantasy_app_selector_matches_grouped_reference_and_uses_brand_accents() -> None:
    assert 'class="dfs-app-selector"' in TEMPLATE
    assert 'id="dfs-fantasy-apps-label">Fantasy Apps' in TEMPLATE
    assert 'id="dfs-optimizer-label">Optimizer' in TEMPLATE
    assert 'class="dfs-optimizer-actions"' in TEMPLATE
    for book_key in ("prizepicks", "underdog", "dk-pick6", "betr", "dabble"):
        assert f'data-book-key="{{{{ logo }}}}"' in TEMPLATE or book_key in TEMPLATE
        assert f'.dfs-book[data-book-key="{book_key}"]' in CSS
    assert "--dfs-book-accent" in CSS
    assert "background: color-mix(in srgb, var(--dfs-book-accent" in CSS
    assert "padding-top: 14px;" in CSS


def test_compact_laptop_odds_columns_match_and_alternate_line_does_not_shift_odds() -> None:
    assert '.algo-odds-head,\nbody[data-design-system="v2"][data-page="dfs"] .algo-odds-cell' in CSS
    odds_start = CSS.index("#dfs-line-head,")
    odds_block = CSS[odds_start : CSS.index("}", odds_start)]
    assert "width: 80px;" in odds_block
    assert "min-width: 80px;" in odds_block
    assert "max-width: 80px;" in odds_block
    assert "alternateLine===null?'':'has-alternate'" in SCRIPT
    assert ".book-cell.has-alternate > strong" in CSS
    assert "top: 50%;" in CSS
    assert ".book-cell.has-alternate .alternate-line" in CSS
    assert "top: calc(50% + 12px);" in CSS


def test_cents_prices_include_american_odds_on_a_second_line() -> None:
    assert "function centsAmericanLabel(display,americanOdds)" in SCRIPT
    assert "isCentsPrice && Number.isFinite(american)" in SCRIPT
    assert "centsAmericanLabel(price,snapshot.american)" in SCRIPT
    assert "centsAmericanLabel(snapshot.display,snapshot.american)" in SCRIPT
    assert 'class="cents-american"' in SCRIPT
    assert ".book-cell .cents-american" in CSS
    assert ".dfs-detail-price small.cents-american" in CSS
    main_start = CSS.index(".book-cell .cents-american")
    main_block = CSS[main_start : CSS.index("}", main_start)]
    detail_start = CSS.index(".dfs-detail-price small.cents-american")
    detail_block = CSS[detail_start : CSS.index("}", detail_start)]
    assert "font: 700 12px/1" in main_block
    assert "font: 700 11px/1" in detail_block


def test_devig_custom_weights_replace_iconlabs_odds_and_hit_rate() -> None:
    assert "return {...defaultWeights};" in SCRIPT
    assert "validKeys && total === 100" in SCRIPT
    assert "total === 0 || total === 100" not in SCRIPT
    assert "const fairHitRate = fairProbability(r,activeLine);" in SCRIPT
    assert "fairAmericanOdds(fairHitRate)" in SCRIPT
    assert "Your Odds using custom Devig Settings" in SCRIPT
    assert "Your Odds from custom Devig weights" in SCRIPT
    assert "function weightedDevigConsensus(row,targetLine)" in SCRIPT
    assert "configuredWeight * freshness" in SCRIPT
    assert "if (consensus) return consensus.probability;" in SCRIPT
    assert "sourceCount < minimumSources" in SCRIPT
    assert "reliability < 0.08" not in SCRIPT
    assert "updateDevigSummary();\n    render();" in SCRIPT
    assert "schema:'quality-guardrails-v3'" in SCRIPT
    assert 'schema:"quality-guardrails-v3"' in (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "IconLabs Algo Odds is selected." in TEMPLATE
    assert "internal book allocation stays private" in TEMPLATE
    assert 'class="ph ph-shield-check"' in TEMPLATE
    assert ".dfs-devig-impact" in CSS
    assert ".dfs-devig-impact.algo-active" in CSS
    assert "white-space: normal;" in CSS
    assert "background: rgba(255, 193, 40, .2);" in CSS
    assert "color: #ffdd67;" in CSS


def test_dfs_player_column_scrolls_with_the_rest_of_the_odds_grid() -> None:
    start = CSS.index('.dfs-table .player-col {')
    block = CSS[start : CSS.index("}", start)]

    assert "position: sticky" not in block
    assert "position: static" in block
    assert "left: 0" not in block
    assert "left: auto" in block
    assert "width: 260px" in block


def test_dfs_rows_expand_into_an_oddsjam_style_two_sided_book_grid() -> None:
    assert 'class="dfs-prop-row${expanded?' in SCRIPT
    assert "data-row-id" in SCRIPT
    assert "aria-expanded" in SCRIPT
    assert "renderOddsDetail(r,activeLine)" in SCRIPT
    assert "detailPair(row)" in SCRIPT
    assert "sideLane('Over'" in SCRIPT
    assert "sideLane('Under'" in SCRIPT
    assert '${esc(row.player)} ${esc(activeLine)} ${esc(row.stat)}' in SCRIPT
    assert "all sportsbook prices" not in SCRIPT
    assert "ph-trend-up" not in SCRIPT
    assert "ph-trend-down" not in SCRIPT
    assert "Best odds" in SCRIPT
    assert "Avg odds" in SCRIPT
    assert ".dfs-odds-detail-grid" in CSS
    assert "grid-template-columns: 204px 72px 72px repeat(var(--dfs-detail-book-count, 16), 74px)" in CSS
    assert "--dfs-detail-book-count:${orderedBooks.length}" in SCRIPT
    assert "min-height: 44px" in CSS
    assert "min-height: 46px" in CSS
    assert ".dfs-detail-title {" in CSS
    assert "align-items: center;" in CSS
    assert "text-align: center;" in CSS
    assert ".dfs-detail-price.best" in CSS


def test_dfs_detail_over_under_labels_are_centered() -> None:
    start = CSS.index(".dfs-detail-side {")
    block = CSS[start : CSS.index("}", start)]

    assert "justify-content: center;" in block


def test_dfs_detail_uses_and_syncs_the_main_saved_sportsbook_order() -> None:
    assert "function detailBookOrder()" in SCRIPT
    assert "detailBookSet.has(key) || optionalComparisonBookMap.has(key)" in SCRIPT
    assert "detailBookOrder().map(key=>marketSnapshot(row,key))" in SCRIPT
    assert "syncCompareOrderFromAccount()" in SCRIPT
    assert "persistCompareOrder()" in SCRIPT
    assert "'/api/dfs/preferences'" in SCRIPT
    assert "accountOrderSyncEnabled" in SCRIPT


def test_iconlabs_algo_hides_internal_weights_and_slider_input_switches_to_custom() -> None:
    assert "draftWeights=usingIconLabs?{...zeroWeights}:{...savedWeights}" in SCRIPT
    assert "draftWeights={...zeroWeights}; activePreset='iconlabs'" in SCRIPT
    assert "selectedDevigTotal() { return activePreset === 'iconlabs' ? 100" in SCRIPT
    assert "activePreset='';" in SCRIPT
    assert "savedWeights=activePreset==='iconlabs'?{...defaultWeights}:{...draftWeights}" in SCRIPT
    assert "IconLabs private model is on. Move any slider" in TEMPLATE
    assert "IconLabs Algo · 100%" in TEMPLATE


def test_selected_dfs_line_moves_into_stat_and_app_column_shows_best_odds() -> None:
    assert "selectedSlipOdds" not in SCRIPT
    assert "selected-slip-odds" not in SCRIPT
    assert "selected-slip-odds" not in CSS
    assert "const selectedAppOdds = activeParlayOdds;" in SCRIPT
    assert 'class="dfs-stat-number">${esc(activeLine)}</strong>' in SCRIPT
    assert 'class="dfs-stat-label">${esc(r.stat)}</span>' in SCRIPT
    assert 'class="selected-line" title="${esc(selectedOddsTitle)}"><strong>${esc(selectedAppOdds)}</strong>' in SCRIPT


def test_selected_app_only_shows_its_real_available_props() -> None:
    assert "function selectedDfsLine(row)" in SCRIPT
    assert ".filter(r => selectedDfsLine(r) !== null" in SCRIPT
    assert "function applyLivePayload(payload)" in SCRIPT
    assert "payload?.dataByBook" in SCRIPT
    assert "rowsByBook[selectedBookKeys[activeBook]]" in SCRIPT
    assert "...rowsByBook" in SCRIPT
    assert "if (changed) loadLiveRows();" in SCRIPT
    assert "book:selectedBookKeys[activeBook]" in SCRIPT
    assert "function parlayOddsTitle(book=activeBook)" in SCRIPT
    assert "PrizePicks 6 Pick Flex equivalent odds" in TEMPLATE
    for book in ("PrizePicks", "Underdog", "DK Pick6", "Betr", "Dabble"):
        assert f"{book}: [" in SCRIPT or f"'{book}': [" in SCRIPT


def test_parlay_type_guide_matches_the_supplied_rankings_and_is_interactive() -> None:
    assert 'id="dfs-parlay-guide-open"' in TEMPLATE
    assert 'aria-label="Best Parlay Type To Build?"' in TEMPLATE
    assert 'id="dfs-parlay-guide-dialog"' in TEMPLATE
    assert "Underdog · 2 Pick Standard (-115)" in TEMPLATE
    assert "PrizePicks · 6 Pick Flex (-118)" in TEMPLATE
    assert "Betr · 8 Pick Flex (-118)" in TEMPLATE
    assert "Dabble · 6 Pick Hedge (-122)" in TEMPLATE
    assert "DK Pick6 · 3 Pick base (-122)" in TEMPLATE
    assert "parlayGuideDialog.showModal()" in SCRIPT
    assert "event.target === parlayGuideDialog" in SCRIPT
    assert "event.key === 'Escape' && parlayGuideDialog.open" in SCRIPT
    assert ".dfs-parlay-guide-button" in CSS
    assert ".dfs-parlay-rankings" in CSS


def test_parlay_equivalent_odds_match_each_required_hit_rate() -> None:
    rows = (
        (53.5, -115),
        (54.2, -118),
        (54.1, -118),
        (55.0, -122),
        (55.0, -122),
    )

    for hit_rate, displayed_odds in rows:
        equivalent_odds = round(-100 * hit_rate / (100 - hit_rate))
        assert equivalent_odds == displayed_odds


def test_each_fantasy_app_has_a_persistent_parlay_type_dropdown() -> None:
    assert 'id="dfs-parlay-config"' in TEMPLATE
    assert 'role="listbox"' in TEMPLATE
    assert "const parlayTypes = {" in SCRIPT
    assert "dfsParlaySelectionsV1" in SCRIPT
    assert "function bestParlayProfile(book)" in SCRIPT
    assert "function selectedParlayProfile(book=activeBook)" in SCRIPT
    assert "function syncParlayPicker()" in SCRIPT
    assert "function parlayOptionLabel(profile)" in SCRIPT
    assert "option.dataset.parlayId = profile.id;" in SCRIPT
    assert "option.textContent = parlayOptionLabel(profile);" in SCRIPT
    assert "`${label}: ${formatAmericanOdds(profile?.odds)} (${parlayMaxPayout(profile)})`" in SCRIPT
    assert "parlayConfig.addEventListener('click'" in SCRIPT
    assert "americanOddsToProbability(activeParlay?.odds)" in SCRIPT
    assert "const selectedAppOdds = activeParlayOdds;" in SCRIPT
    assert "syncParlayPicker();" in SCRIPT


def test_selected_fantasy_app_opens_parlay_picker_on_second_click() -> None:
    app_row = TEMPLATE.split('class="dfs-book-row"', 1)[1].split("</div>", 1)[0]

    assert 'draggable="true"' not in app_row
    assert 'aria-expanded="false"' in app_row
    assert 'aria-haspopup="listbox"' in app_row
    assert "enableDrag(document.querySelector('.dfs-book-row')" not in SCRIPT
    assert "if (activeBook !== btn.dataset.dfsBook)" in SCRIPT
    assert "setParlayPickerOpen(parlayConfig.hidden,btn);" in SCRIPT
    assert "function positionParlayPicker(button)" in SCRIPT
    assert "buttonRect.left" in SCRIPT
    assert "buttonRect.bottom+2" in SCRIPT
    assert "--parlay-picker-accent" in SCRIPT
    assert ".dfs-parlay-config[hidden]" in CSS


def test_parlay_picker_uses_the_selected_app_card_color_and_width() -> None:
    menu_start = CSS.index(".dfs-parlay-config {")
    menu_block = CSS[menu_start : CSS.index("}", menu_start)]

    assert "position: fixed;" in menu_block
    assert "z-index: 60;" in menu_block
    assert "box-sizing: border-box;" in menu_block
    assert "var(--parlay-picker-accent" in menu_block
    assert "var(--il-sidebar-active)" in menu_block
    assert ".dfs-parlay-config button[aria-selected=\"true\"]" in CSS


def test_prizepicks_two_pick_power_uses_three_x_equivalent_odds() -> None:
    assert "{id:'2-power',label:'2 Pick Power',odds:-137,payout:'3x'}" in SCRIPT
    required_probability = 137 / (137 + 100)
    assert round(required_probability * required_probability * 3, 2) == 1.0


def test_dk_pick6_uses_numeric_base_payouts() -> None:
    for profile in (
        "{id:'2-pick',label:'2 Pick',odds:-137,payout:'3x base + extra winnings'}",
        "{id:'3-pick',label:'3 Pick',odds:-122,payout:'6x base + extra winnings'}",
        "{id:'4-pick',label:'4 Pick',odds:-128,payout:'10x base + extra winnings'}",
        "{id:'5-pick',label:'5 Pick',odds:-122,payout:'20x base + extra winnings'}",
        "{id:'6-pick',label:'6 Pick',odds:-124,payout:'35x base + extra winnings'}",
    ):
        assert profile in SCRIPT
    assert "Confirm live prize table" not in SCRIPT


def test_dabble_includes_every_all_in_and_hedge_parlay_type() -> None:
    dabble = SCRIPT.split("Dabble: [", 1)[1].split("\n    ],", 1)[0]

    for picks in range(2, 13):
        assert f"id:'{picks}-all-in'" in dabble
    assert "id:'2-hedge'" not in dabble
    for picks in range(3, 13):
        assert f"id:'{picks}-hedge'" in dabble

    for payout in (
        "payout:'3x'",
        "payout:'6x'",
        "payout:'10x'",
        "payout:'20x'",
        "payout:'35x'",
        "payout:'60x'",
        "payout:'100x'",
        "payout:'175x'",
        "payout:'300x'",
        "payout:'500x'",
        "payout:'1000x'",
        "payout:'250x / 40x / 7.5x / 1x'",
    ):
        assert payout in dabble


def test_prizepicks_parlay_change_moves_the_hit_rate_value_band() -> None:
    fair_hit_rate = 55.0
    default_requirement = 118 / (118 + 100) * 100
    two_power_requirement = 137 / (137 + 100) * 100

    assert fair_hit_rate > default_requirement
    assert fair_hit_rate - two_power_requirement < -2
    assert "const requiredProbability = americanOddsToProbability(activeParlay?.odds);" in SCRIPT
    assert "probabilityEdgePoints > 0" in SCRIPT
    assert "probabilityEdgePoints >= -2" in SCRIPT


def test_dfs_rebalances_side_chance_and_odds_column_widths() -> None:
    side_start = CSS.index(".dfs-side {")
    side_block = CSS[side_start : CSS.index("}", side_start)]
    chance_start = CSS.index(".hit-rate {")
    chance_block = CSS[chance_start : CSS.index("}", chance_start)]
    odds_start = CSS.index("#dfs-line-head,")
    odds_block = CSS[odds_start : CSS.index("}", odds_start)]

    assert "min-width: 64px;" in side_block
    assert ".dfs-table th:nth-child(2)" in CSS
    assert "min-width: 63px;" in chance_block
    assert ".dfs-table th:nth-child(5)" in CSS
    assert "width: 93px;" in CSS
    assert "width: 80px;" in odds_block
    assert "min-width: 80px;" in odds_block


def test_dfs_removes_summary_row_and_prizepicks_line_odds() -> None:
    assert "dfs-summary-row" not in TEMPLATE
    assert "Line discrepancies only" not in TEMPLATE
    assert "PrizePicks lines ranked by model edge" not in TEMPLATE
    assert "selected-slip-odds" not in SCRIPT


def test_dfs_filter_controls_share_equal_columns_and_alignment() -> None:
    assert "grid-template-columns: repeat(7, minmax(0, 1fr));" in CSS
    assert "align-items: end;" in CSS
    assert "justify-content: center;" in CSS
    assert "min-height: var(--il-control-height-compact);" in CSS


def test_dfs_team_filter_follows_date_sport_team_stat_order() -> None:
    filter_start = TEMPLATE.index('<div class="dfs-filter-bar il-filter-bar" id="dfs-filter-bar">')
    filter_end = TEMPLATE.index("</div>", filter_start)
    filter_markup = TEMPLATE[filter_start:filter_end]

    assert filter_markup.index('id="dfs-date"') < filter_markup.index('id="dfs-sport"')
    assert filter_markup.index('id="dfs-sport"') < filter_markup.index('id="dfs-team"')
    assert filter_markup.index('id="dfs-team"') < filter_markup.index('id="dfs-stat"')
    assert '<span>Teams</span><select id="dfs-team"><option value="">All teams</option>' in filter_markup
    assert "const teamSelect = document.querySelector('#dfs-team');" in SCRIPT
    assert "function rowTeams(row)" in SCRIPT
    assert "function updateTeams()" in SCRIPT
    assert "rows.filter(row => !sport || row.sport === sport).flatMap(rowTeams)" in SCRIPT
    assert "(!team || rowTeams(r).includes(team))" in SCRIPT
    assert "sportSelect.addEventListener('change', () => { updateStats(); updateTeams(); render(); });" in SCRIPT


def test_dfs_date_filter_supports_presets_and_inclusive_custom_ranges() -> None:
    assert '<option value="today">Today</option>' in TEMPLATE
    assert '<option value="tomorrow">Tomorrow</option>' in TEMPLATE
    assert '<option value="next_7_days" selected>Next 7 days</option>' in TEMPLATE
    assert '<option value="custom">Custom</option>' in TEMPLATE
    assert 'id="dfs-custom-date-range" hidden' in TEMPLATE
    assert 'id="dfs-date-from" type="date"' in TEMPLATE
    assert 'id="dfs-date-to" type="date"' in TEMPLATE
    assert 'id="dfs-date-error" role="alert"' in TEMPLATE
    assert "function easternDateKey(date = new Date())" in SCRIPT
    assert "function selectedDateRange()" in SCRIPT
    assert "return {start:today,end:shiftDateKey(today,6)};" in SCRIPT
    assert "eventDate >= dateRange.start && eventDate <= dateRange.end" in SCRIPT
    assert "matchesDateRange(r,dateRange)" in SCRIPT
    assert "schema:'quality-guardrails-v3'" in SCRIPT
    assert 'schema:"quality-guardrails-v3"' in (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "date === 'this_week'" not in SCRIPT
    assert "dateSelect.value='next_7_days'" in SCRIPT
    assert ".dfs-custom-date-range[hidden]" in CSS
    assert "grid-template-columns: minmax(150px, 190px) auto minmax(150px, 190px);" in CSS
    assert "color-scheme: dark;" in CSS


def test_dfs_prop_typography_and_stat_alignment() -> None:
    assert "font: 700 15px/1.2 var(--il-font-ui);" in CSS
    assert "font: 500 12px/1.2 var(--il-font-ui);" in CSS
    assert "font: 500 11px/1.2 var(--il-font-ui);" in CSS
    assert "font: 800 13px/1 var(--il-font-data);" in CSS
    assert "font: 650 14px/1.25 var(--il-font-ui);" in CSS
    assert ".dfs-stat-number" in CSS
    assert "font-size: 18px;" in CSS
    assert "font-weight: 800;" in CSS
    assert ".dfs-stat-label" in CSS
    assert "font-size: 12px;" in CSS
    assert "flex-direction: column;" in CSS
    assert "align-items: center;" in CSS
    assert "margin-inline: auto;" in CSS
    assert "text-align: center;" in CSS


def test_dfs_prop_rows_have_more_vertical_breathing_room() -> None:
    cell_start = CSS.index(".dfs-table td {")
    cell_block = CSS[cell_start : CSS.index("}", cell_start)]

    assert "height: 78px;" in cell_block


def test_dfs_chance_to_hit_number_is_fifteen_pixels() -> None:
    chance_number_start = CSS.index(".hit-rate strong {")
    chance_number_block = CSS[
        chance_number_start : CSS.index("}", chance_number_start)
    ]

    assert "font: 700 15px/1 var(--il-font-data);" in chance_number_block


def test_dfs_app_parlay_summary_is_two_pixels_larger() -> None:
    summary_start = CSS.index(".dfs-book small {")
    summary_block = CSS[summary_start : CSS.index("}", summary_start)]

    assert "font-size: 11px;" in summary_block


def test_dfs_side_badge_has_a_stronger_border_and_bold_label() -> None:
    side_start = CSS.index(".dfs-side {")
    side_block = CSS[side_start : CSS.index("}", side_start)]

    assert "border: 2px solid transparent;" in side_block
    assert "font: 800 13px/1 var(--il-font-data);" in side_block
    assert "rgba(98, 238, 158, .72)" in CSS
    assert "color: #6effaa;" in CSS
    assert "rgba(177, 91, 255, .74)" in CSS
    assert "color: #b75cff;" in CSS
    assert "text-shadow: 0 0 8px" in CSS


def test_optional_comparison_books_are_searchable_removable_and_persistent() -> None:
    assert 'id="dfs-comparison-book-catalog"' in TEMPLATE
    assert 'id="dfs-add-book-open"' in TEMPLATE
    assert 'id="dfs-add-book-picker"' in TEMPLATE
    assert 'id="dfs-add-book-search"' in TEMPLATE
    assert 'id="dfs-add-book-apply"' in TEMPLATE
    assert "optionalComparisonBookMap" in SCRIPT
    assert "function toggleOptionalComparisonBook(key)" in SCRIPT
    assert "function positionComparisonBookPicker()" in SCRIPT
    assert "position: fixed;" in CSS
    assert "draftOptionalBookKeys" in SCRIPT
    assert "function applyOptionalComparisonBooks()" in SCRIPT
    assert "data-remove-comparison-book" not in SCRIPT
    assert "requiredComparisonBookKeys" in SCRIPT
    assert "defaults.every(key => order.includes(key))" in SCRIPT
    assert "order.every(key => allowedComparisonBookKeys.has(key))" in SCRIPT
    assert "persistCompareOrder();" in SCRIPT

    static_headers = TEMPLATE.split('id="dfs-head-row"', 1)[1].split("</tr>", 1)[0]
    assert "data-remove-comparison-book" not in static_headers


def test_comparison_odds_expose_liquidity_quality_state_and_deep_links() -> None:
    assert "const liquidityBookKeys" in SCRIPT
    assert "formatLiquidity(snapshot.liquidity)" in SCRIPT
    assert "modelExclusionLabel" in SCRIPT
    assert 'target="_blank"' in SCRIPT
    assert 'rel="noopener noreferrer"' in SCRIPT
    assert ".dfs-book-liquidity" in CSS
    assert ".dfs-model-excluded" in CSS


def test_expanded_odds_fill_the_row_and_use_logo_only_headers() -> None:
    assert "dfs-detail-book-head\" role=\"columnheader\"" in SCRIPT
    assert "<span>${esc(bookName(key))}</span>" not in SCRIPT
    detail_start = CSS.index(".dfs-odds-detail {")
    detail_block = CSS[detail_start : CSS.index("}", detail_start)]
    assert "padding: 0;" in detail_block
    assert "background: transparent;" in detail_block


def test_optional_comparison_book_menu_uses_larger_title_case_labels() -> None:
    assert "<strong>Comparison Books</strong>" in TEMPLATE
    title_start = CSS.index(".dfs-add-book-picker header strong {")
    title_block = CSS[title_start : CSS.index("}", title_start)]
    subtitle_start = CSS.index(".dfs-add-book-picker header small {")
    subtitle_block = CSS[subtitle_start : CSS.index("}", subtitle_start)]
    option_start = CSS.index(".dfs-add-book-option {")
    option_block = CSS[option_start : CSS.index("}", option_start)]

    assert "font: 750 13px/1.2 var(--il-font-ui);" in title_block
    assert "font: 500 11px/1.2 var(--il-font-ui);" in subtitle_block
    assert "font: 650 13px/1.2 var(--il-font-ui);" in option_block


def test_dfs_stat_and_matchup_text_never_truncate() -> None:
    player_start = CSS.index('.dfs-table .player-col {')
    player_block = CSS[player_start : CSS.index("}", player_start)]
    matchup_start = CSS.index(".dfs-player small {")
    matchup_block = CSS[matchup_start : CSS.index("}", matchup_start)]
    stat_start = CSS.index(".dfs-stat {")
    stat_block = CSS[stat_start : CSS.index("}", stat_start)]

    assert "width: 260px;" in player_block
    assert "min-width: 260px;" in player_block
    assert "overflow: visible;" in matchup_block
    assert "overflow-wrap: anywhere;" in matchup_block
    assert "text-overflow: clip;" in matchup_block
    assert "white-space: normal;" in matchup_block
    assert "min-width: 180px;" in stat_block
    assert "max-width: none;" in stat_block
    assert "overflow-wrap: anywhere;" in stat_block
    assert "white-space: normal;" in stat_block
    assert ".dfs-table th:nth-child(3)" in CSS
    assert ".dfs-table td:nth-child(3)" in CSS


def test_optimizer_buttons_use_the_glass_action_card_treatment() -> None:
    assert ".dfs-devig-button,\nbody[data-design-system=\"v2\"][data-page=\"dfs\"] .dfs-parlay-guide-button" in CSS
    assert "height: 64px;" in CSS
    assert "border-color: #7f5aa7;" in CSS
    assert "border-radius: 10px;" in CSS
    assert "background: #171321;" in CSS
    assert "inset 0 1px 0 rgba(237, 217, 255, .42)" in CSS
    assert "0 3px 0 #452764" in CSS
    assert "0 8px 16px rgba(0, 0, 0, .5)" in CSS
    assert "0 0 14px rgba(173, 81, 255, .25)" in CSS
    assert "transform: translateY(-1px);" in CSS
    assert ".dfs-action-icon" in CSS
    assert ".dfs-action-arrow" in CSS
    assert 'ph ph-arrow-right dfs-action-arrow' in TEMPLATE
    assert ".dfs-devig-button:active" in CSS
    assert ".dfs-parlay-guide-button:active" in CSS
    assert ".dfs-devig-button:focus-visible" in CSS

    title_start = CSS.rindex('.dfs-devig-button strong,')
    title_block = CSS[title_start : CSS.index("}", title_start)]
    subtitle_start = CSS.rindex('.dfs-devig-button small,')
    subtitle_block = CSS[subtitle_start : CSS.index("}", subtitle_start)]
    assert "font: 700 12px/1.2 var(--il-font-ui);" in title_block
    assert "font: 500 9px/1.15 var(--il-font-data);" in subtitle_block


def test_selected_fantasy_app_uses_branded_sidebar_depth_treatment() -> None:
    active_start = CSS.index('.dfs-book.active {')
    active_block = CSS[active_start : CSS.index("}", active_start)]

    assert "position: relative;" in active_block
    assert "inset 3px 0 0 var(--dfs-book-accent" in active_block
    assert "inset 0 1px 0 rgba(255, 255, 255, .22)" in active_block
    assert "0 3px 0 color-mix" in active_block
    assert "0 8px 16px rgba(0, 0, 0, .42)" in active_block
    assert "0 0 14px color-mix" in active_block
    assert "transform: translateY(-1px);" in active_block
    assert ".dfs-book.active:hover" in CSS
    assert ".dfs-book.active:active" in CSS

