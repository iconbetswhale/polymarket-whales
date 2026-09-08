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
    assert "-canonical-v15" in BASE[canonical : canonical + 180]
    script = BASE.index("filename='app.js'")
    assert "-live-feeds-v16-tracker-share-card" in BASE[script : script + 190]
