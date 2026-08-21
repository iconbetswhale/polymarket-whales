from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "templates" / "shadow_test.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "shadow-lab-v2.css").read_text(encoding="utf-8")


def test_shadow_lab_opts_into_v2_without_global_legacy_layers(app_client) -> None:
    response = app_client.get("/shadow-test")

    assert response.status_code == 200
    assert b'data-page="shadow-test" data-design-system="v2"' in response.data
    assert b"design-system.css" in response.data
    assert b"shadow-lab-v2.css" in response.data
    for stylesheet in (
        b"legacy-design-system.css",
        b"stage2-art-direction.css",
        b"shared-shell.css",
        b"mobile-product.css",
        b"app-premium.css",
        b"sidebar-shell.css",
    ):
        assert stylesheet not in response.data


def test_shadow_lab_uses_v2_primitives_and_preserves_workflow() -> None:
    for hook in (
        "shadow-page",
        "il-data-grid-page",
        "il-page-header",
        "il-page-title",
        "il-kpi-strip",
        "shadow-lab-panel",
        "shadow-policy-panel",
        "shadow-legacy-panel",
    ):
        assert hook in TEMPLATE

    for hook in (
        "loadShadowTest",
        "shadow-wallet-sleeves",
        "shadow-readiness",
        'data-label="Wallet"',
        'data-label="Review"',
    ):
        assert hook in SCRIPT + TEMPLATE


def test_shadow_lab_v2_is_flat_and_token_driven() -> None:
    assert 'body[data-design-system="v2"][data-page="shadow-test"]' in CSS
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


def test_shadow_lab_table_and_mobile_card_contracts() -> None:
    assert "min-width: 1120px" in CSS
    assert "overflow: auto" in CSS
    assert "@media (max-width: 700px)" in CSS
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in CSS
    assert "content: attr(data-label)" in CSS
    assert ".shadow-wallet-table thead" in CSS
    assert ".shadow-policy-grid" in CSS


def test_shadow_lab_asset_loads_after_foundation() -> None:
    foundation = BASE.index("filename='design-system.css'")
    canonical = BASE.index("filename='shadow-lab-v2.css'", foundation)

    assert canonical > foundation
    assert "-canonical-v1" in BASE[canonical : canonical + 190]
