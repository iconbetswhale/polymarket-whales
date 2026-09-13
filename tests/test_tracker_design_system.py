from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "templates" / "tracker.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "tracker-v2.css").read_text(encoding="utf-8")


def test_tracker_opts_into_v2_without_global_legacy_layers(app_client) -> None:
    response = app_client.get("/tracker?preview=1")

    assert response.status_code == 200
    assert b'data-page="tracker" data-design-system="v2"' in response.data
    assert b"design-system.css" in response.data
    assert b"tracker-v2.css" in response.data
    assert b"legacy-design-system.css" not in response.data
    assert b"stage2-art-direction.css" not in response.data
    assert b"shared-shell.css" not in response.data
    assert b"mobile-product.css" not in response.data
    assert b"app-premium.css" not in response.data
    assert b"sidebar-shell.css" not in response.data


def test_tracker_preview_parameter_cannot_enable_fixture_rows(app_client) -> None:
    attempted_preview = app_client.get("/tracker?preview=1")
    regular = app_client.get("/tracker")

    assert attempted_preview.data == regular.data
    assert b"data-tracker-preview" not in regular.data
    assert b"temporary tracker bets" not in regular.data
    assert b"Preview bankroll" not in regular.data
    assert 'dataset.trackerPreview === "true"' in SCRIPT
    assert "data-tracker-preview" not in TEMPLATE


def test_tracker_reuses_canonical_primitives() -> None:
    for hook in (
        "il-data-grid-page",
        "il-page-header",
        "il-view-tabs",
        "il-filter-bar",
    ):
        assert hook in TEMPLATE


def test_tracker_v2_uses_shared_tokens_without_visual_shortcuts() -> None:
    assert 'body[data-design-system="v2"][data-page="tracker"]' in CSS
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
    # The requested recap border sheen is the only intentional gradient exception.
    for selector, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS):
        if "gradient(" in declarations:
            assert any(hook in selector for hook in (".tracker-period-recap", ".tracker-recap-hero", ".tracker-recap-metrics > div"))


def test_tracker_v2_keeps_responsive_and_interactive_contracts() -> None:
    assert "@media (max-width: 700px)" in CSS
    assert ".tracker-mobile-bet-list" in CSS
    assert ".responsive-table.tracker-table" in CSS
    assert "overflow: auto" in CSS
    assert "trackerPreviewPayload" in SCRIPT
    assert "loadTrackerView" in SCRIPT
    assert "selectTrackerSection" in SCRIPT
    assert "renderTrackerPerformance" in SCRIPT


def test_tracker_performance_chart_and_calendar_share_one_timeframe_filter() -> None:
    assert "trackerPeriodAnchor: null" in SCRIPT
    assert "trackerTimeframeDateBounds" in SCRIPT
    assert "trackerIsoDate" in SCRIPT
    assert "syncTrackerTimeframeControls" in SCRIPT
    assert 'graph_range: "all"' in SCRIPT
    assert 'tracker_range: "custom"' in SCRIPT
    assert "trackerDefaultPeriodAnchor" in SCRIPT
    assert "trackerWeekEnd" in SCRIPT
    assert "trackerShiftedPeriodAnchor" in SCRIPT
    assert "shiftTrackerPerformancePeriod(-1)" in SCRIPT
    assert "button.hidden = !navigableRange" in SCRIPT
    assert 'return `${startText}–${endText}, ${anchor.getFullYear()}`' in SCRIPT
    assert 'data-range="custom"' in TEMPLATE
    assert "Custom Dates" in TEMPLATE
    assert 'id="tracker-date-range"' not in TEMPLATE
    assert 'canvas.addEventListener("pointermove"' in SCRIPT
    assert 'canvas.addEventListener("keydown"' in SCRIPT
    assert 'drawExtrema(highest, "High", true)' in SCRIPT
    assert 'drawExtrema(lowest, "Low", false)' in SCRIPT
    assert ".tracker-chart-tooltip" in CSS
    assert '[data-performance-view="calendar"] .tracker-performance-frame' in CSS
    assert "height: auto !important;" in CSS
    assert "min-height: 0 !important;" in CSS
    assert "background: var(--il-surface-1) !important;" in CSS
    assert "font: 680 34px/1.12 var(--il-font-ui) !important;" in CSS
    assert "font: 700 11px/1.2 var(--il-font-ui);" in CSS
    assert "font: 650 14px/1 var(--il-font-ui);" in CSS
    assert "font: 700 14px/1.2 var(--il-font-ui);" in CSS
    assert "font: 700 22px/1.2 var(--il-font-ui);" in CSS
    assert "font: 650 11px/1.2 var(--il-font-ui);" in CSS
    assert "font-size: 11px;" in CSS
    assert "display: inline-block !important;" in CSS
    assert "align-items: center;" in CSS
    assert "border-left: 0;" in CSS
    assert "gap: 0;" in CSS
    assert "grid-template-columns: repeat(4, minmax(0, 1fr)) !important;" in CSS
    assert "min-height: 68px;" in CSS
    assert "border-top: 2px solid var(--il-brand);" in CSS
    assert "background: rgba(141, 68, 246, .045);" in CSS
    assert "font: 700 clamp(24px, 2vw, 28px)/1.2 var(--il-font-ui);" in CSS
    assert "min-height: 28px;" in CSS
    assert "border-radius: 0 0 var(--il-radius-control) var(--il-radius-control);" in CSS
    assert "rgba(141, 68, 246, 0.24)" in SCRIPT
    assert 'ctx.strokeStyle = "#9e5cff"' in SCRIPT
    assert 'ctx.font = `${14 * ratio}px Inter, system-ui, sans-serif`' in SCRIPT
    assert 'ctx.font = `${12 * ratio}px Inter, system-ui, sans-serif`' in SCRIPT


def test_tracker_calendar_combines_day_details_with_monthly_pulse() -> None:
    assert 'new URLSearchParams(window.location.search).get("preview") === "1"' in SCRIPT
    assert '["127.0.0.1", "localhost"].includes(window.location.hostname)' in SCRIPT
    for contract in (
        "trackerCalendarSelectedDay: null",
        "trackerCalendarFitObserver: null",
        "function trackerCalendarRowsByDay",
        "function trackerCalendarDetailMarkup",
        "function trackerCompactBetLabel",
        "function trackerCompactMatchup",
        "function trackerDirectionAndLine",
        "function trackerCalendarPulseMarkup",
        "function drawTrackerWeekdayPulse",
        "function openTrackerCalendarDayBets",
        "function fitTrackerCalendarDayValues",
        "Day of Week Performance",
        'class="tracker-calendar-weekday-tooltip"',
        "canvas.onmousemove",
        "bar.value !== 0",
        "Math.min(42, Math.max(16, slot * 0.74))",
        "rows.map(trackerCalendarBetMarkup)",
        "rows.length > 2",
        "absoluteAmount.toFixed(2)",
        'class="tracker-calendar-layout"',
        'class="tracker-calendar-insights"',
        'data-tracker-calendar-day="${day}"',
        'renderTrackerCalendar(points, payload)',
        'title="${escapeHtml(`${selection} · ${marketTitle}`)}"',
    ):
        assert contract in SCRIPT

    for selector in (
        ".tracker-calendar-layout",
        ".tracker-calendar-insights",
        ".tracker-calendar-detail",
        ".tracker-calendar-bet-row",
        ".tracker-calendar-pulse",
        ".tracker-calendar-weekday-pulse canvas",
        ".tracker-calendar-day.selected",
    ):
        assert selector in CSS

    assert "background: rgba(21, 92, 61, .46);" in CSS
    assert "background: rgba(92, 36, 48, .58);" in CSS
    assert "background: #141c27;" in CSS
    assert 'outside-month" aria-hidden="true"></span>' in SCRIPT
    assert "font: 650 13px/1 var(--il-font-ui);" in CSS
    assert "font: 600 16px/1 var(--il-font-ui);" in CSS
    assert "font: 700 26px/1 var(--il-font-data);" in CSS
    assert "letter-spacing: 0;" in CSS
    assert "top: 24px;" in CSS
    assert "align-items: center;" in CSS
    assert "fitTrackerCalendarDayValues(container);" in SCRIPT
    assert "const centeredContentWidth = (reportedWidth * 2) - availableWidth;" in SCRIPT
    assert "font: 700 38px/1 var(--il-font-data);" in CSS
    assert "font: 700 24px/1 var(--il-font-data);" in CSS
    assert ".tracker-calendar-bet-list.scrollable" in CSS
    assert "max-height: 131px;" in CSS
    assert "height: 586px;" in CSS
    assert "min-height: 586px;" in CSS
    assert "font: 700 19px/1.1 var(--il-font-data);" in CSS
    assert "grid-template-columns: 34px minmax(0, 1fr) minmax(52px, auto) minmax(64px, auto);" in CSS
    assert "width: 30px;" in CSS
    assert "justify-self: stretch;" in CSS
    assert '"PRA"' in SCRIPT
    assert '"Total Bases"' in SCRIPT
    assert '"Strikeouts"' in SCRIPT
    assert '[singleSideLabel(subject), "ML", period]' in SCRIPT
    assert "function trackerTeamWithLocation" in SCRIPT
    assert '"buffalo": "BUF"' in SCRIPT
    assert '[matchup || trackerSelectionSubject(side), totalLabel, period]' in SCRIPT


def test_tracker_monthly_recap_can_be_exported_and_shared() -> None:
    for element_id in (
        "tracker-share-open",
        "tracker-share-dialog",
        "tracker-share-canvas",
        "tracker-share-calendar-canvas",
        "tracker-share-pulse-canvas",
        "tracker-share-clv-canvas",
        "tracker-share-profit-canvas",
        "tracker-share-download",
        "tracker-share-copy-link",
        "tracker-share-social",
    ):
        assert f'id="{element_id}"' in TEMPLATE

    assert 'id="tracker-share-copy-image"' not in TEMPLATE
    assert "Share Dashboard" in TEMPLATE
    assert "Monthly Pulse" in TEMPLATE
    assert "Ready to Share" in TEMPLATE
    assert "Save Image" in TEMPLATE
    assert "Copy Image Link" in TEMPLATE
    assert "Share to Social" in TEMPLATE

    assert "iconlabs-mark-transparent-v3.png" in TEMPLATE
    assert "function trackerShareSnapshot()" in SCRIPT
    assert "const TRACKER_SHARE_SECTIONS" in SCRIPT
    assert "async function renderTrackerShareCard(section = appState.trackerShareSection)" in SCRIPT
    assert "async function renderTrackerShareGallery()" in SCRIPT
    assert "function setTrackerShareSection(section)" in SCRIPT
    assert SCRIPT.count("ctx.fillText(snapshot.profitText, 992, 285);") >= 2
    assert "const TRACKER_SHARE_DESKTOP_PREVIEW_SCALE = 610 / 1350;" in SCRIPT
    assert "const TRACKER_SHARE_MONTHLY_PROFIT_FONT_PX = Math.round(22 / TRACKER_SHARE_DESKTOP_PREVIEW_SCALE);" in SCRIPT
    assert SCRIPT.count("ctx.font = `800 ${TRACKER_SHARE_MONTHLY_PROFIT_FONT_PX}px Inter, system-ui, sans-serif`;") >= 2
    assert 'ctx.fillText("DAY OF WEEK PERFORMANCE", 88, weekdayHeadingY);' in SCRIPT
    assert "const valueText = signedMoney(value);" in SCRIPT
    assert "ctx.fillText(valueText, x + barWidth / 2, valueY);" in SCRIPT
    assert "Math.max(weekdayHeadingY + 35, y - 13)" in SCRIPT
    assert 'ctx.fillText("DAILY PROFIT / LOSS"' not in SCRIPT
    assert "let periodSize = 27;" in SCRIPT
    assert "ctx.font = \"600 21px Inter, system-ui, sans-serif\";" in SCRIPT
    assert "slide.hidden = slide.dataset.trackerShareSlide !== section;" in SCRIPT
    assert "function drawTrackerShareChart(ctx, snapshot)" in SCRIPT
    assert 'const chart = { x: 72, y: 495, width: 936, height: 598 };' in SCRIPT
    assert 'drawExtrema(highest, "High", true);' in SCRIPT
    assert 'drawExtrema(lowest, "Low", false);' in SCRIPT
    assert "payload.clv?.periods?.all" in SCRIPT
    assert 'canvas.toBlob(' in SCRIPT
    assert "copyTrackerShareImage" not in SCRIPT
    assert 'rendered.canvas.toDataURL("image/png")' in SCRIPT
    assert "await navigator.share(shareData)" in SCRIPT
    assert ".tracker-share-trigger" in CSS
    assert ".tracker-share-dialog" in CSS
    assert ".tracker-share-actions" in CSS
    assert ".tracker-share-sections" in CSS
    assert ".tracker-share-slide" in CSS
    assert "scroll-snap-type: x mandatory;" not in CSS


def test_tracker_clv_card_uses_requested_type_scale_and_contextual_help() -> None:
    assert 'aria-describedby="tracker-clv-help-tooltip"' in TEMPLATE
    assert 'id="tracker-clv-help-tooltip" role="tooltip"' in TEMPLATE
    assert "Positive CLV means you beat the market." in TEMPLATE
    assert ".tracker-clv-help-wrap:hover .tracker-clv-help-tooltip" in CSS
    assert ".tracker-clv-help-wrap:focus-within .tracker-clv-help-tooltip" in CSS
    assert "font-size: 22px;" in CSS
    assert "font: 700 27px/1 var(--il-font-data);" in CSS
    assert "font: 650 14px/1.2 var(--il-font-ui);" in CSS
    assert "font: 650 12px/1 var(--il-font-ui);" in CSS
    assert "font: 600 14px/1.2 var(--il-font-ui);" in CSS
    assert "inset 3px 0 0 var(--il-brand-hover)" in CSS
    assert "button:not(.active):hover" in CSS


def test_tracker_clv_supports_three_and_six_month_ranges_and_majority_tones() -> None:
    for value, card_label, dialog_label in (
        ("3m", "3M", "3 Months"),
        ("6m", "6M", "6 Months"),
    ):
        assert f'data-clv-range="{value}">{card_label}</button>' in TEMPLATE
        assert f'data-clv-range="{value}">{dialog_label}</button>' in TEMPLATE
    assert 'range === "3m"' in SCRIPT
    assert 'range === "6m"' in SCRIPT
    assert "function setClvMajorityTone(node, summary)" in SCRIPT
    assert 'node.classList.toggle("positive", tone === "positive")' in SCRIPT
    assert 'node.classList.toggle("negative", tone === "negative")' in SCRIPT
    assert "repeat(8, minmax(0, 1fr))" in CSS
    assert "repeat(4, minmax(0, 1fr))" in CSS
    assert "white-space: nowrap;" in CSS
    assert "border-color: rgba(158, 92, 255, .46);" in CSS
    assert "overflow: visible;" in CSS


def test_dashboard_uses_global_tags_and_searchable_multibook_filters(app_client) -> None:
    assert 'id="tracker-book-catalog" type="application/json"' in TEMPLATE
    assert 'id="tracker-dashboard-tag-filter"' in TEMPLATE
    assert "Live bets" not in TEMPLATE
    assert "Wins</option>" not in TEMPLATE
    assert "Losses</option>" not in TEMPLATE
    assert 'id="tracker-book-filter-search" type="search"' in TEMPLATE
    assert 'id="tracker-book-filter-count"' in TEMPLATE
    assert "Select All" in TEMPLATE
    assert "Apply Books" in TEMPLATE

    assert "const TRACKER_BOOK_CATALOG" in SCRIPT
    assert 'return Array.isArray(catalog) ? catalog : [];' in SCRIPT
    assert 'book?.type !== "dfs"' not in SCRIPT
    rendered = app_client.get("/tracker").data
    for dfs_book in (b"PrizePicks", b"Underdog", b"DraftKings Pick6", b"Betr Picks", b"Dabble"):
        assert dfs_book in rendered
    assert "function renderTrackerDashboardTagFilter" in SCRIPT
    assert 'const TRACKER_PRESET_TAGS = ["Prediction Traders", "Sharp Money", "Positive EV", "Arbitrage", "Middles"]' in SCRIPT
    assert 'optgroup label="Tool Filters"' in SCRIPT
    assert 'class="tracker-tag-filter"' in TEMPLATE
    assert "function trackerCalendarSportIcon" in SCRIPT
    assert "[snapshot.sports_market_type, snapshot.market_type, snapshot.market_kind, marketTitle, row.sports_market_type, row.market_type]" in SCRIPT
    assert 'sports_market_type: "Moneyline"' in SCRIPT
    assert 'sports_market_type: "Spread"' in SCRIPT
    assert ".tracker-calendar-detail-meta" in CSS
    assert "font: 700 18px/1.1 var(--il-font-data);" in CSS
    assert "font-size: 14px;\n  line-height: 1;" in CSS
    assert '["Active Days", String(active.length), "", "#f5f7fb"]' in SCRIPT
    assert "<b>Settled Days</b>" not in SCRIPT
    assert "function trackerPreviewFilteredGraph" in SCRIPT
    assert "const filtersActive = Boolean(search || status || result || sharp || tag || selectedBooks.size);" in SCRIPT
    assert "function trackerBookChoices" in SCRIPT
    assert "function trackerBookOptionLogo" in SCRIPT
    assert 'windcreekbetfredpa: "windcreek"' in SCRIPT
    assert 'params.tag = selectedTag' in SCRIPT
    assert 'tracker-book-filter-options input:checked' in SCRIPT
    assert 'tracker-book-filter-search' in SCRIPT

    for declaration in (
        "font: 700 22px/1.2 var(--il-font-ui);",
        "font: 600 14px/1 var(--il-font-ui);",
        "font: 650 14px/1 var(--il-font-ui);",
        "font: 650 14px/1.2 var(--il-font-ui);",
        "font: 700 22px/1.15 var(--il-font-data);",
        "font: 700 12px/1.2 var(--il-font-ui);",
        "font: 600 12px/1.2 var(--il-font-ui);",
    ):
        assert declaration in CSS
    assert ".tracker-book-filter-options label:has(input:checked)" in CSS
    assert ".tracker-book-filter-logo img" in CSS
    assert ".tracker-tag-filter:focus-within" in CSS
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in CSS
    assert "border-color: var(--il-border-subtle) !important;" in CSS
    assert "background: var(--il-surface-2) !important;" in CSS


def test_tracker_global_toolbar_orders_filters_and_range_without_bankroll() -> None:
    toolbar = TEMPLATE.split('<section class="tracker-primary-toolbar"', 1)[1].split(
        '<section class="tracker-switcher-shell"', 1
    )[0]
    assert toolbar.index('id="tracker-section-tabs"') < toolbar.index(
        'id="tracker-dashboard-tag-filter"'
    )
    assert toolbar.index('id="tracker-dashboard-tag-filter"') < toolbar.index(
        'id="tracker-book-filter"'
    )
    assert toolbar.index('id="tracker-book-filter"') < toolbar.index(
        'id="graph-range"'
    )
    assert 'id="tracker-share-open"' not in toolbar
    assert 'Search Sportsbooks, Exchanges, And DFS' in toolbar
    assert 'id="tracker-date-range"' not in toolbar
    assert 'id="tracker-group-by-control"' not in toolbar
    assert 'aria-label="Tracker timeframe"' in toolbar
    assert 'data-range="custom"' in toolbar
    assert 'Custom Dates' in toolbar
    assert 'class="segmented tracker-graph-range"' in toolbar
    performance_controls = TEMPLATE.split(
        '<div class="tracker-performance-controls">', 1
    )[1].split('</div>', 2)[0]
    assert performance_controls.index('id="tracker-share-open"') < performance_controls.index(
        'class="tracker-visual-toggle"'
    )
    assert ".tracker-primary-toolbar" in CSS
    assert ".tracker-global-controls" in CSS
    assert ".tracker-global-bankroll" not in CSS
    assert ".tracker-toolbar-custom-dates" in CSS
    assert "border: 1px solid var(--il-border-standard) !important;" in CSS
    assert "padding: 3px;" in CSS
    assert "gap: 3px;" in CSS
    assert "border: 1px solid var(--il-border-subtle) !important;" in CSS
    assert "color: var(--il-text-secondary) !important;" in CSS


def test_profit_metric_cards_match_clv_surface_language() -> None:
    profit_grid_rule = CSS[
        CSS.index('.tracker-profit-grid {') : CSS.index('.tracker-profit-grid {') + 760
    ]
    assert "gap: 10px;" in profit_grid_rule
    assert "border: 1px solid var(--il-border-subtle);" in profit_grid_rule
    assert "border-radius: var(--il-radius-control);" in profit_grid_rule
    assert "background: var(--il-bg-workspace);" in profit_grid_rule
    assert "overflow: visible;" in profit_grid_rule


def test_tracker_book_picker_is_compact_and_opens_below_the_global_toolbar() -> None:
    popover_rule = CSS[
        CSS.index('.tracker-book-filter-popover {') :
        CSS.index('.tracker-book-filter-popover {') + 620
    ]
    assert "top: calc(100% + 8px);" in popover_rule
    assert "bottom: auto;" in popover_rule
    assert "width: min(440px, calc(100vw - 36px));" in popover_rule
    assert "max-height: min(460px, calc(100vh - 150px));" in popover_rule


def test_tracker_v2_uses_the_full_desktop_workspace() -> None:
    app_shell_rule = CSS[CSS.index('.app-shell {') : CSS.index('.app-shell {') + 180]
    fluid_workspace_rule = CSS[
        CSS.index('/* Keep the desktop tracker workspace fluid.') :
        CSS.index('/* Keep the desktop tracker workspace fluid.') + 620
    ]

    assert "padding-top: 0 !important;" in app_shell_rule
    assert ".tracker-page-header" in fluid_workspace_rule
    assert ".tracker-dashboard-grid" in fluid_workspace_rule
    assert ".tracker-bets-view" in fluid_workspace_rule
    assert ".tracker-toolbar" in fluid_workspace_rule
    assert ".table-panel" in fluid_workspace_rule
    assert "width: 100%;" in fluid_workspace_rule
    assert "max-width: none;" in fluid_workspace_rule


def test_tracker_assets_load_after_the_v2_foundation() -> None:
    foundation = BASE.index("filename='design-system.css'")
    canonical = BASE.index("filename='tracker-v2.css'", foundation)

    assert canonical > foundation
    assert "-canonical-v57-no-bankroll-control" in BASE[canonical : canonical + 220]
    script = BASE.index("filename='app.js'")
    assert "-live-feeds-v74-shared-odds" in BASE[script : script + 220]
    assert BASE.index("filename='odds-format.js'") < script


def test_tracker_period_recap_replaces_the_summary_strip_and_shares_the_date_filter() -> None:
    assert 'class="tracker-period-recap" id="tracker-performance-summary"' in TEMPLATE
    assert 'class="tracker-performance-summary"' not in TEMPLATE
    assert 'id="tracker-recap-stake"' in TEMPLATE
    for offset in (-1, 0, 1):
        assert f'data-tracker-recap-day="{offset}"' in TEMPLATE
    assert "function trackerRecapSnapshot(" in SCRIPT
    assert "Number(summary.settled_wagered)" in SCRIPT
    assert 'appState.graphRange = "today";' in SCRIPT
    assert "function selectTrackerRecapDay(offset)" in SCRIPT
    assert "renderTrackerPeriodRecap(payload, points)" in SCRIPT
    assert "coverageText: `${measured} Of ${total} Bets Priced`" in SCRIPT
    assert ".tracker-recap-metrics" in CSS
    assert 'button[aria-pressed="true"]' in CSS


def test_tracker_recap_is_a_share_gallery_and_export_option() -> None:
    assert 'data-tracker-share-section="recap"' in TEMPLATE
    assert 'data-tracker-share-slide="recap"' in TEMPLATE
    assert 'id="tracker-share-recap-canvas" width="1080" height="1350"' in TEMPLATE
    assert 'recap: { label: "Period Recap", canvasId: "tracker-share-recap-canvas" }' in SCRIPT
    assert "recap: trackerRecapSnapshot(payload, points)" in SCRIPT
    assert 'if (section === "recap") drawTrackerShareRecap(ctx, snapshot)' in SCRIPT
    assert "ctx.fillText(recap.coverageText" in SCRIPT


def test_tracker_bet_rows_match_the_positions_alternating_surfaces() -> None:
    for parity, token in (("odd", "--il-surface-1"), ("even", "--il-bg-workspace")):
        selector = f".tracker-table tbody tr:nth-child({parity}) td"
        rule = CSS[CSS.index(selector):].split("}", 1)[0]
        assert f"background: var({token});" in rule
    stripe_start = CSS.index("/* Match the Positions ledger")
    hover_rule = CSS[stripe_start:][CSS[stripe_start:].index(".tracker-table tbody tr:hover td"):].split("}", 1)[0]
    assert "background: var(--il-surface-hover);" in hover_rule


def test_tracker_share_tabs_and_previews_do_not_need_horizontal_scrolling() -> None:
    for selector in (".tracker-share-sections {", ".tracker-share-preview {", ".tracker-share-track {"):
        rule = CSS[CSS.index(selector):].split("}", 1)[0]
        assert "overflow-x: auto" not in rule
        assert "min-width: 100%" not in rule
    tabs_rule = CSS[CSS.index(".tracker-share-sections {"):].split("}", 1)[0]
    assert "grid-template-columns: repeat(6, minmax(0, 1fr));" in tabs_rule
    assert "grid-column: 1 / -1;" in tabs_rule
    assert ".tracker-share-tab-compact" in CSS
    assert 'aria-label="Period Recap"' in TEMPLATE
    assert ".tracker-share-slide[hidden]" in CSS
    assert 'data-tracker-share-slide="recap" hidden' in TEMPLATE
    assert "slide.hidden = slide.dataset.trackerShareSlide !== section;" in SCRIPT
    assert "syncTrackerShareSectionFromScroll" not in SCRIPT
    assert "Scroll or choose a section" not in TEMPLATE


def test_tracker_recap_has_padded_rounded_metric_cards() -> None:
    for selector in (".tracker-recap-hero {", ".tracker-recap-metrics > div {"):
        rule = CSS[CSS.index(selector):].split("}", 1)[0]
        assert "border: 2px solid transparent;" in rule
        assert "border-radius: var(--il-radius-control);" in rule
        assert "linear-gradient(var(--il-bg-workspace), var(--il-bg-workspace)) padding-box" in rule
        assert "var(--tracker-recap-gloss) border-box;" in rule
        assert "padding:" in rule
    hero_rule = CSS[CSS.index(".tracker-recap-hero {"):].split("}", 1)[0]
    assert "padding: 20px;" in hero_rule
    assert "inset 60px -18px 80px -76px" not in CSS
    assert "ctx.roundRect(88, 378, 904, 316, 24);" in SCRIPT
    assert "ctx.roundRect(cardX, cardY, 444, 178, 20);" in SCRIPT


def test_dashboard_recap_uses_share_border_palettes_without_changing_title_layout() -> None:
    for palette in (
        "#8e95a3 0%, #596170 35%, #232a35 100%",
        "#79d995 0%, #348450 35%, #163a28 100%",
        "#ef8894 0%, #9f4858 35%, #401e28 100%",
    ):
        assert f"linear-gradient(180deg, {palette})" in CSS
    for state in ("positive", "negative"):
        selector = f".tracker-period-recap.is-{state} .tracker-recap-hero {{"
        rule = CSS[CSS.index(selector):].split("}", 1)[0]
        assert "--tracker-recap-gloss:" in rule
        assert "border-color:" not in rule
    assert '<div class="title-line"><h1 id="tracker-page-title">' in TEMPLATE


def test_dashboard_clv_border_adapts_and_sections_keep_silver_gloss() -> None:
    assert 'id="tracker-recap-clv-card"' in TEMPLATE
    assert 'clvCard.classList.toggle("is-positive", recap.clv !== null && recap.clv > 0);' in SCRIPT
    assert 'clvCard.classList.toggle("is-negative", recap.clv !== null && recap.clv < 0);' in SCRIPT
    for state in ("positive", "negative"):
        selector = f".tracker-recap-metrics > div.is-{state} {{"
        assert "--tracker-recap-gloss:" in CSS[CSS.index(selector):].split("}", 1)[0]
    shared = CSS[CSS.index("/* The recap replaces"):].split("}", 1)[0]
    for selector in (".tracker-profit-panel,", ".tracker-clv-card,", ".tracker-period-recap {"):
        assert selector in shared
    assert "#8e95a3 0%, #596170 35%, #232a35 100%" in shared
    assert "border: 2px solid transparent;" in shared
    assert "linear-gradient(var(--il-surface-1), var(--il-surface-1)) padding-box" in shared


def test_tracker_bankroll_controls_and_dead_handlers_are_removed() -> None:
    for hook in ("model-bankroll-control", "personal-bankroll-control", "tracker-bankroll-edit", "tracker-starting-bankroll", "personal-starting-bankroll", "tracker-bankroll-dialog", "personal-bankroll-dialog"):
        assert hook not in TEMPLATE
        assert hook not in SCRIPT
    assert ".tracker-bankroll-control" not in CSS
    for handler in ("openTrackerBankrollDialog", "closeTrackerBankrollDialog", "saveTrackerBankroll", "openPersonalBankrollDialog", "closePersonalBankrollDialog", "savePersonalTrackerBankroll"):
        assert handler not in SCRIPT


def test_tracker_timeframe_switches_use_cached_and_prewarmed_payloads() -> None:
    assert "TRACKER_PAYLOAD_CACHE_MAX_AGE_MS = 5 * 60 * 1000" in SCRIPT
    assert "TRACKER_MEMORY_CACHE_LIMIT = 12" in SCRIPT
    assert "function readTrackerPayloadCache(key)" in SCRIPT
    assert "function writeTrackerPayloadCache(key, payload)" in SCRIPT
    assert "trackerTimeframeDateBounds(range = appState.graphRange, anchorOverride = null)" in SCRIPT
    assert "function trackerPayloadRequest(view, params)" in SCRIPT
    assert "appState.trackerRequestPromises.has(requestKey)" in SCRIPT
    assert "function prewarmTrackerTimeframes(view)" in SCRIPT
    assert 'Number(params.get("min_sharps") || 0) > 0' in SCRIPT
    assert 'month: ["week", "today", "year"]' in SCRIPT
    assert "trackerRequestParamsForRange(view, range, currentParams)" in SCRIPT
    assert "readTrackerPayloadCache(cacheKey)" in SCRIPT
    assert 'requestSequence !== appState.trackerRequestSequence.model || appState.trackerView !== "model"' in SCRIPT
    assert 'if (nextRange === previousRange && nextRange !== "custom") return;' in SCRIPT


def test_tracked_bets_uses_readable_ledger_and_compact_clv_popover() -> None:
    assert '>Overview</button>' in TEMPLATE
    assert '>Tracked Bets</button>' in TEMPLATE
    assert '.tracker-section-tabs button {' in CSS
    assert 'font-size: 14px !important;' in CSS
    assert 'title.textContent = "Bet Tracker";' in SCRIPT
    assert '"<th>Bet</th><th>Source</th><th>Wager</th><th>Result</th><th>P&amp;L</th><th>CLV</th><th>Tracked</th>"' in SCRIPT
    assert 'class="tracker-bet-cell"' in SCRIPT
    assert 'class="tracker-wager-cell"' in SCRIPT
    assert 'class="clv-popover"' in SCRIPT
    assert 'View Full Calculation' in SCRIPT
    assert 'data-clv-close' in SCRIPT
    assert '.tracker-table tr.clv-row-open td' in CSS
    assert '.clv-details.open-up > .clv-popover' in CSS
    assert 'position: fixed;' in CSS
    assert 'top: var(--clv-popover-top, 18px);' in CSS
    assert 'overflow: visible;' in CSS
    assert 'positionClvPopover' in SCRIPT
    assert 'window.innerHeight - popoverRect.height - margin' in SCRIPT
    assert '<small>${escapeHtml(formatAmericanOdds(closingOdds))}</small>' in SCRIPT
    assert 'Search Bets, Teams, Markets, or Sportsbooks' in SCRIPT
    assert 'function trackerSourceCompact(snapshot = {})' in SCRIPT
    assert 'positiveev: { label: "Positive EV", icon: "ph-trend-up" }' in SCRIPT
    assert '<td data-label="Source">${trackerSourceCompact(sharpSnapshot)}</td>' in SCRIPT
    assert 'trackerMobileDetail("Source", trackerSourceCompact(sharpSnapshot))' in SCRIPT
    assert 'font-size: 18px;' in CSS
    assert 'font-size: 14px;' in CSS
    assert '.tracker-model-bets td[data-label="Source"] .tracker-sharp-compact > strong {' in CSS
    assert 'font-size: 14px !important;' in CSS
    assert 'font: 700 20px/1.2 var(--il-font-data);' in CSS
    assert 'font: 700 14px/1 var(--il-font-ui);' in CSS
    assert 'font-size: 15px;' in CSS
    assert 'font-size: 16px;' in CSS


def test_sportsbook_summaries_use_compact_logo_cards_and_preview_ten_books() -> None:
    assert 'class="tracker-book-summary-name"' in SCRIPT
    assert 'providerLogoMarkup(meta, sportsbook)' in SCRIPT
    assert 'grid-template-columns: repeat(5, minmax(0, 1fr));' in CSS
    assert 'padding: var(--il-space-4);' in CSS
    assert 'border: 1px solid var(--il-border-standard) !important;' in CSS
    assert 'border-radius: var(--il-radius-control) !important;' in CSS
    assert 'const performanceClass = pnl > 0 ? "is-positive" : pnl < 0 ? "is-negative" : "is-neutral";' in SCRIPT
    assert '.tracker-book-summary article.is-positive {' in CSS
    assert '.tracker-book-summary article.is-negative {' in CSS
    assert 'rgba(255, 77, 101, .3)' in CSS
    assert 'background: var(--il-bg-workspace) !important;' in CSS
    assert 'inset -56px 0 64px -60px rgba(80, 217, 119, .34)' in CSS
    assert 'background: var(--il-surface-1) !important;' in CSS
    assert 'grid-template-columns: minmax(0, 1fr) auto;' in CSS
    assert 'grid-row: 1 / span 2;' in CSS
    assert 'flex-basis: 32px;' in CSS
    assert 'font-size: 20px;' in CSS
    assert 'const TRACKER_PREVIEW_BOOK_SUMMARIES = [' in SCRIPT
    assert 'function trackerPreviewBookSummaries()' in SCRIPT
    assert 'get("preview_books")' in SCRIPT
    preview_summaries = SCRIPT[
        SCRIPT.index('const TRACKER_PREVIEW_BOOK_SUMMARIES = [') :
        SCRIPT.index('function trackerPreviewAnchor()')
    ]
    assert preview_summaries.count('sportsbook:') == 10
    assert 'sportsbook_summaries: sportsbookSummaries' in SCRIPT
    assert 'sportsbooks: previewBookSummaries.map' in SCRIPT
    assert '!selectedBooks.size || selectedBooks.has' in SCRIPT
