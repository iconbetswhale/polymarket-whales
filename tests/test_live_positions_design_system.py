from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "templates" / "live_positions.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "live-positions-v2.css").read_text(encoding="utf-8")


def test_live_positions_opts_into_v2_without_global_legacy_layers(app_client) -> None:
    response = app_client.get("/live-positions")

    assert response.status_code == 200
    assert b'data-page="live-positions" data-design-system="v2"' in response.data
    assert b"design-system.css" in response.data
    assert b"live-positions-v2.css" in response.data
    for stylesheet in (
        b"legacy-design-system.css",
        b"stage2-art-direction.css",
        b"shared-shell.css",
        b"mobile-product.css",
        b"app-premium.css",
        b"sidebar-shell.css",
    ):
        assert stylesheet not in response.data


def test_live_positions_uses_v2_primitives_and_preserves_filters() -> None:
    for hook in (
        "live-page",
        "il-data-grid-page",
        "il-page-header",
        "il-page-title",
        "il-toolbar",
        "il-panel",
        "live-positions-table",
        "positions-cards",
    ):
        assert hook in TEMPLATE

    for control_id in (
        "position-search",
        "position-wallet",
        "position-sport",
        "position-league",
        "position-market",
        "position-sort",
    ):
        assert f'id="{control_id}"' in TEMPLATE


def test_live_positions_v2_is_flat_and_token_driven() -> None:
    assert 'body[data-design-system="v2"][data-page="live-positions"]' in CSS
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
        "var(--il-positive)",
        "var(--il-negative)",
    ):
        assert token in CSS


def test_live_positions_has_table_mobile_card_and_empty_state_contracts() -> None:
    assert "min-width: 980px" in CSS
    assert "overflow-x: auto" in CSS
    assert "@media (max-width: 700px)" in CSS
    assert ".responsive-table" in CSS
    assert ".card-results" in CSS
    assert ".mobile-result-card" in CSS
    assert ".live-empty-mobile" in CSS
    assert 'class="live-empty-mobile"' in SCRIPT
    assert 'class="${pnl >= 0 ? "positive" : "negative"}"' in SCRIPT


def test_live_positions_asset_loads_after_foundation() -> None:
    foundation = BASE.index("filename='design-system.css'")
    canonical = BASE.index("filename='live-positions-v2.css'", foundation)

    assert canonical > foundation
    assert "-canonical-v1" in BASE[canonical : canonical + 200]
