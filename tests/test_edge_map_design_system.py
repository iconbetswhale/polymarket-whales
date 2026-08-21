from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "templates" / "edge_map.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "edge-map-v2.css").read_text(encoding="utf-8")


def test_edge_map_opts_into_v2_without_global_legacy_layers(app_client) -> None:
    response = app_client.get("/edge-map")

    assert response.status_code == 200
    assert b'data-page="edge-map" data-design-system="v2"' in response.data
    assert b"design-system.css" in response.data
    assert b"edge-map-v2.css" in response.data
    for stylesheet in (
        b"legacy-design-system.css",
        b"stage2-art-direction.css",
        b"shared-shell.css",
        b"mobile-product.css",
        b"app-premium.css",
        b"sidebar-shell.css",
    ):
        assert stylesheet not in response.data


def test_edge_map_uses_v2_primitives_and_preserves_controls() -> None:
    for hook in (
        "edge-map-page",
        "il-dashboard-page",
        "il-page-header",
        "il-page-title",
        "il-stat-grid",
        "il-toolbar",
        "il-panel",
        "edge-map-table",
    ):
        assert hook in TEMPLATE

    assert 'id="edge-map-dimension"' in TEMPLATE
    assert 'for="edge-map-dimension"' in TEMPLATE
    for option in (
        "wallet",
        "wallet_type",
        "sport",
        "league",
        "market_type",
        "provider",
        "entry_price_range",
        "time_to_event_bucket",
        "trade_grade",
        "liquidity_grade",
        "execution_method",
        "decision_class",
    ):
        assert f'value="{option}"' in TEMPLATE


def test_edge_map_v2_is_flat_and_token_driven() -> None:
    assert 'body[data-design-system="v2"][data-page="edge-map"]' in CSS
    assert "gradient(" not in CSS
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", CSS)
    assert not re.search(r"\brgba?\(", CSS)
    assert "!important" not in CSS

    for token in (
        "var(--il-bg-app)",
        "var(--il-surface-1)",
        "var(--il-surface-2)",
        "var(--il-border-subtle)",
        "var(--il-text-primary)",
        "var(--il-brand-hover)",
    ):
        assert token in CSS


def test_edge_map_table_becomes_labeled_mobile_cards() -> None:
    assert "min-width: 960px" in CSS
    assert "table-layout: fixed" in CSS
    assert "overflow-x: auto" in CSS
    assert "@media (max-width: 760px)" in CSS
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in CSS
    assert "content: attr(data-label)" in CSS
    assert ".edge-map-table thead" in CSS

    for label in (
        "Segment",
        "Status",
        "Candidates",
        "Played / Passed",
        "Settled",
        "ROI",
        "Exchange CLV",
        "Composite CLV",
        "Reliability",
    ):
        assert f'data-label="{label}"' in SCRIPT


def test_edge_map_retains_data_and_filter_workflow() -> None:
    for hook in (
        "renderEdgeMap",
        "loadEdgeMap",
        "bindEdgeMap",
        "/api/edge-map",
        'addEventListener("change", loadEdgeMap)',
    ):
        assert hook in SCRIPT


def test_edge_map_asset_loads_after_foundation() -> None:
    foundation = BASE.index("filename='design-system.css'")
    canonical = BASE.index("filename='edge-map-v2.css'", foundation)

    assert canonical > foundation
    assert "-canonical-v1" in BASE[canonical : canonical + 200]
