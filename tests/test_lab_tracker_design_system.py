from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "templates" / "lab_tracker.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "static" / "lab-tracker.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "lab-tracker-v2.css").read_text(encoding="utf-8")


def test_lab_tracker_opts_into_v2_without_global_legacy_layers(app_client) -> None:
    response = app_client.get("/lab-tracker?demo=1")

    assert response.status_code == 200
    assert b'data-page="lab-tracker" data-design-system="v2"' in response.data
    assert b"design-system.css" in response.data
    assert b"lab-tracker-v2.css" in response.data
    assert b"lab-tracker.css" not in response.data
    for stylesheet in (
        b"legacy-design-system.css",
        b"stage2-art-direction.css",
        b"shared-shell.css",
        b"mobile-product.css",
        b"app-premium.css",
        b"sidebar-shell.css",
    ):
        assert stylesheet not in response.data


def test_lab_tracker_reuses_canonical_components_and_accessible_tabs() -> None:
    for hook in (
        "il-data-grid-page",
        "il-page-header",
        "il-page-title",
        "il-view-tabs",
        "il-kpi-strip",
        "il-kpi-metric",
    ):
        assert hook in TEMPLATE

    assert 'aria-selected="true"' in TEMPLATE
    assert "syncSourceTabs" in SCRIPT
    assert 'item.setAttribute("aria-selected", String(active))' in SCRIPT


def test_lab_tracker_v2_is_token_driven_and_flat() -> None:
    assert 'body[data-design-system="v2"][data-page="lab-tracker"]' in CSS
    assert "gradient(" not in CSS
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", CSS)
    assert not re.search(r"\brgba?\(", CSS)
    assert "!important" not in CSS

    for token in (
        "var(--il-bg-app)",
        "var(--il-surface-1)",
        "var(--il-border-subtle)",
        "var(--il-text-primary)",
        "var(--il-brand)",
        "var(--il-positive)",
        "var(--il-negative)",
        "var(--il-font-ui)",
    ):
        assert token in CSS


def test_lab_tracker_v2_preserves_dashboard_and_responsive_contracts() -> None:
    for selector in (
        ".lab-dashboard",
        ".lab-metrics",
        ".lab-chart-card",
        ".lab-ranking",
        ".lab-bet-card",
        ".lab-demo-notice",
    ):
        assert selector in CSS

    for breakpoint in (1320, 1120, 980, 760, 520):
        assert f"@media (max-width: {breakpoint}px)" in CSS

    assert "overflow-x: hidden" in CSS
    assert "scroll-snap-type: x proximity" in CSS
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in CSS


def test_lab_tracker_assets_load_after_foundation() -> None:
    foundation = BASE.index("filename='design-system.css'")
    canonical = BASE.index("filename='lab-tracker-v2.css'", foundation)

    assert canonical > foundation
    assert "-canonical-v1" in BASE[canonical : canonical + 190]
