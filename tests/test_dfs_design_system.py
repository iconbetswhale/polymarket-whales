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
    demo = app_client.get("/dfs?demo=1")
    regular = app_client.get("/dfs")

    assert b'data-dfs-preview="true"' in preview.data
    assert b"30 temporary optimizer props" in preview.data
    assert b'data-dfs-preview="true"' in demo.data
    assert b"30 temporary optimizer props" in demo.data
    assert b"Visual fixtures only" in preview.data
    assert b'data-dfs-preview="false"' in regular.data
    assert b"30 temporary optimizer props" not in regular.data
    assert "fetch(" not in SCRIPT
    assert SCRIPT.count("{player:") == 30
    assert "supplementalPreviewRows" in SCRIPT


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
    assert "near-threshold" in SCRIPT
    assert "negative-edge" in SCRIPT
    assert ".hit-rate.positive-edge" in CSS
    assert ".hit-rate.near-threshold" in CSS
    assert ".hit-rate.negative-edge" in CSS


def test_dfs_v2_keeps_responsive_and_interactive_contracts() -> None:
    assert "@media (max-width: 700px)" in CSS
    assert ".dfs-table-shell" in CSS
    assert "overflow: auto" in CSS
    assert "#dfs-devig-open" in SCRIPT
    assert "#dfs-discrepancies" not in SCRIPT
    assert "#dfs-search" in SCRIPT
    assert "Preview refreshed just now" in SCRIPT
    assert "devigDialog.showModal()" in SCRIPT


def test_dfs_assets_load_after_the_v2_foundation() -> None:
    foundation = BASE.index("filename='design-system.css'")
    canonical = BASE.index("filename='dfs-v2.css'", foundation)
    script = BASE.index("filename='dfs.js'")

    assert canonical > foundation
    assert "-filters-v2" in BASE[canonical : canonical + 160]
    assert "-filters-v2" in BASE[script : script + 140]


def test_dfs_rows_use_the_same_alternating_purple_treatment_as_odds_screen() -> None:
    assert ".dfs-table tbody tr:nth-child(even) td" in CSS
    assert "background: rgba(141, 68, 246, .08)" in CSS
    assert ".dfs-table tbody tr:hover td" in CSS
    assert "background: rgba(141, 68, 246, .15)" in CSS


def test_prizepicks_and_iconlabs_columns_inherit_the_row_backgrounds() -> None:
    assert '.selected-line {\n  background: var(--il-surface-1) !important;' in CSS
    assert ".dfs-table tbody tr td.algo-odds-cell" in CSS
    assert ".dfs-table tbody tr:nth-child(even) td.selected-line" in CSS
    assert ".dfs-table tbody tr:nth-child(even) td.algo-odds-cell" in CSS
    assert ".dfs-table tbody tr:hover td.selected-line" in CSS
    assert ".dfs-table tbody tr:hover td.algo-odds-cell" in CSS


def test_iconlabs_fair_odds_uses_the_current_white_mark() -> None:
    assert "assets/iconlabs-mark-white-transparent.png" in TEMPLATE


def test_dfs_removes_summary_row_and_prizepicks_line_odds() -> None:
    assert "dfs-summary-row" not in TEMPLATE
    assert "Line discrepancies only" not in TEMPLATE
    assert "PrizePicks lines ranked by model edge" not in TEMPLATE
    assert "activeBook === 'PrizePicks' ? ''" in SCRIPT


def test_dfs_filter_controls_share_equal_columns_and_alignment() -> None:
    assert "grid-template-columns: repeat(6, minmax(0, 1fr));" in CSS
    assert "align-items: end;" in CSS
    assert "justify-content: center;" in CSS
    assert "min-height: var(--il-control-height-compact);" in CSS

