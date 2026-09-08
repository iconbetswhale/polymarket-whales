from __future__ import annotations

from pathlib import Path


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
    assert "gradient(" not in CSS


def test_tracker_v2_keeps_responsive_and_interactive_contracts() -> None:
    assert "@media (max-width: 700px)" in CSS
    assert ".tracker-mobile-bet-list" in CSS
    assert ".responsive-table.tracker-table" in CSS
    assert "overflow: auto" in CSS
    assert "trackerPreviewPayload" in SCRIPT
    assert "loadTrackerView" in SCRIPT
    assert "selectTrackerSection" in SCRIPT
    assert "renderTrackerPerformance" in SCRIPT


def test_tracker_performance_chart_and_calendar_share_a_persistent_month() -> None:
    assert "trackerPeriodAnchor: null" in SCRIPT
    assert "params.graph_month" in SCRIPT
    assert "trackerLocalMonthPayload" in SCRIPT
    assert "shiftTrackerPerformanceMonth(-1)" in SCRIPT
    assert 'button.hidden = appState.graphRange !== "month"' in SCRIPT
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


def test_tracker_monthly_recap_can_be_exported_and_shared() -> None:
    for element_id in (
        "tracker-share-open",
        "tracker-share-dialog",
        "tracker-share-canvas",
        "tracker-share-download",
        "tracker-share-copy-link",
        "tracker-share-social",
    ):
        assert f'id="{element_id}"' in TEMPLATE

    assert 'id="tracker-share-copy-image"' not in TEMPLATE
    assert "Monthly Recap" in TEMPLATE
    assert "Ready to Share" in TEMPLATE
    assert "Save Image" in TEMPLATE
    assert "Copy Image Link" in TEMPLATE
    assert "Share to Social" in TEMPLATE

    assert "iconlabs-mark-transparent-v3.png" in TEMPLATE
    assert "function trackerShareSnapshot()" in SCRIPT
    assert "async function renderTrackerShareCard()" in SCRIPT
    assert "function drawTrackerShareChart(ctx, snapshot)" in SCRIPT
    assert 'const chart = { x: 72, y: 495, width: 936, height: 598 };' in SCRIPT
    assert 'drawExtrema(highest, "High", true);' in SCRIPT
    assert 'drawExtrema(lowest, "Low", false);' in SCRIPT
    assert "clv_month_summaries" in SCRIPT
    assert 'canvas.toBlob(' in SCRIPT
    assert "copyTrackerShareImage" not in SCRIPT
    assert 'rendered.canvas.toDataURL("image/png")' in SCRIPT
    assert "await navigator.share(shareData)" in SCRIPT
    assert ".tracker-share-trigger" in CSS
    assert ".tracker-share-dialog" in CSS
    assert ".tracker-share-actions" in CSS


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
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in CSS
    assert "border-color: var(--il-border-subtle) !important;" in CSS
    assert "background: var(--il-surface-2) !important;" in CSS


def test_tracker_global_toolbar_orders_bankroll_filters_and_range() -> None:
    toolbar = TEMPLATE.split('<section class="tracker-primary-toolbar"', 1)[1].split(
        '<section class="tracker-switcher-shell"', 1
    )[0]
    assert toolbar.index('id="tracker-section-tabs"') < toolbar.index(
        'id="model-bankroll-control"'
    )
    assert toolbar.index('id="model-bankroll-control"') < toolbar.index(
        'id="tracker-dashboard-tag-filter"'
    )
    assert toolbar.index('id="tracker-dashboard-tag-filter"') < toolbar.index(
        'id="tracker-book-filter"'
    )
    assert toolbar.index('id="tracker-book-filter"') < toolbar.index(
        'id="tracker-date-range"'
    )
    assert toolbar.index('id="tracker-date-range"') < toolbar.index(
        'id="graph-range"'
    )
    assert 'id="tracker-share-open"' not in toolbar
    assert 'Search Sportsbooks, Exchanges, And DFS' in toolbar
    assert 'class="segmented tracker-graph-range"' in toolbar
    performance_controls = TEMPLATE.split(
        '<div class="tracker-performance-controls">', 1
    )[1].split('</div>', 2)[0]
    assert performance_controls.index('id="tracker-share-open"') < performance_controls.index(
        'class="tracker-visual-toggle"'
    )
    assert ".tracker-primary-toolbar" in CSS
    assert ".tracker-global-controls" in CSS
    assert ".tracker-global-bankroll" in CSS
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
    assert "-canonical-v20d-share-period-buttons" in BASE[canonical : canonical + 220]
    script = BASE.index("filename='app.js'")
    assert "-live-feeds-v21-global-toolbar" in BASE[script : script + 220]
