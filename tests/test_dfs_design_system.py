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


def test_dfs_preview_is_explicit_and_read_only(app_client) -> None:
    preview = app_client.get("/dfs?preview=1")
    regular = app_client.get("/dfs")

    assert b'data-dfs-preview="true"' in preview.data
    assert b"Eight temporary optimizer props" in preview.data
    assert b"Visual fixtures only" in preview.data
    assert b'data-dfs-preview="false"' in regular.data
    assert b"Eight temporary optimizer props" not in regular.data
    assert "fetch(" not in SCRIPT
    assert SCRIPT.count("{player:") == 8


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
    assert "IconLabs fair odds" in TEMPLATE
    assert "fairAmericanOdds" in SCRIPT
    assert "americanOddsToProbability" in SCRIPT
    assert "positive-edge" in SCRIPT
    assert ".hit-rate.positive-edge" in CSS


def test_dfs_v2_keeps_responsive_and_interactive_contracts() -> None:
    assert "@media (max-width: 700px)" in CSS
    assert ".dfs-table-shell" in CSS
    assert "overflow: auto" in CSS
    assert "#dfs-devig-open" in SCRIPT
    assert "#dfs-discrepancies" in SCRIPT
    assert "#dfs-search" in SCRIPT
    assert "Preview refreshed just now" in SCRIPT
    assert "devigDialog.showModal()" in SCRIPT


def test_dfs_assets_load_after_the_v2_foundation() -> None:
    foundation = BASE.index("filename='design-system.css'")
    canonical = BASE.index("filename='dfs-v2.css'", foundation)
    script = BASE.index("filename='dfs.js'")

    assert canonical > foundation
    assert "-canonical-v1" in BASE[canonical : canonical + 160]
    assert "-canonical-v1" in BASE[script : script + 140]
