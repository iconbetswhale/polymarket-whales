from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "templates" / "wallets.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "sharp-wallets-v2.css").read_text(encoding="utf-8")


def test_sharp_wallets_opts_into_v2_without_global_legacy_layers(app_client) -> None:
    response = app_client.get("/wallets")

    assert response.status_code == 200
    assert b'data-page="wallets" data-design-system="v2"' in response.data
    assert b"design-system.css" in response.data
    assert b"sharp-wallets-v2.css" in response.data
    for stylesheet in (
        b"legacy-design-system.css",
        b"stage2-art-direction.css",
        b"shared-shell.css",
        b"mobile-product.css",
        b"app-premium.css",
        b"sidebar-shell.css",
    ):
        assert stylesheet not in response.data


def test_sharp_wallets_uses_v2_primitives_and_preserves_roster_workflow() -> None:
    for hook in (
        "wallet-roster-page",
        "il-data-grid-page",
        "il-page-header",
        "il-page-title",
        "il-segmented",
        "il-toolbar",
        "il-panel",
        "wallet-roster-grid",
        "wallet-clv-note",
    ):
        assert hook in TEMPLATE

    for hook in (
        "loadWallets",
        "bindWallets",
        "walletCard",
        "walletRosterMetric",
        "data-copy-address",
        "wallet-hidden-toolbar",
    ):
        assert hook in SCRIPT + TEMPLATE


def test_sharp_wallets_v2_is_flat_and_token_driven() -> None:
    assert 'body[data-design-system="v2"][data-page="wallets"]' in CSS
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
        "var(--il-warning)",
    ):
        assert token in CSS


def test_sharp_wallets_responsive_card_and_filter_contracts() -> None:
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in CSS
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in CSS
    assert "@media (max-width: 700px)" in CSS
    assert ".wallet-hidden-toolbar[hidden]" in CSS
    assert ".wallet-roster-card" in CSS
    assert ".wallet-roster-metrics" in CSS
    assert ".wallet-clv-band" in CSS
    assert ".empty-state" in CSS


def test_sharp_wallets_tabs_expose_selected_state() -> None:
    assert 'role="tablist"' in TEMPLATE
    assert TEMPLATE.count('role="tab"') == 2
    assert 'aria-selected="true"' in TEMPLATE
    assert 'aria-selected="false"' in TEMPLATE
    assert 'tab.setAttribute("aria-selected", String(selected))' in SCRIPT


def test_sharp_wallets_asset_loads_after_foundation() -> None:
    foundation = BASE.index("filename='design-system.css'")
    canonical = BASE.index("filename='sharp-wallets-v2.css'", foundation)

    assert canonical > foundation
    assert "-canonical-v1" in BASE[canonical : canonical + 200]
