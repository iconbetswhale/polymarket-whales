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


def test_tracker_assets_load_after_the_v2_foundation() -> None:
    foundation = BASE.index("filename='design-system.css'")
    canonical = BASE.index("filename='tracker-v2.css'", foundation)

    assert canonical > foundation
    assert "-canonical-v1" in BASE[canonical : canonical + 170]
