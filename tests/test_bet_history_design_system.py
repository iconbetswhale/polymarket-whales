from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "templates" / "position_history.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "bet-history-v2.css").read_text(encoding="utf-8")


def test_bet_history_opts_into_v2_without_global_legacy_layers(app_client) -> None:
    response = app_client.get("/position-history")

    assert response.status_code == 200
    assert b'data-page="position-history" data-design-system="v2"' in response.data
    assert b"design-system.css" in response.data
    assert b"bet-history-v2.css" in response.data
    for stylesheet in (
        b"legacy-design-system.css",
        b"stage2-art-direction.css",
        b"shared-shell.css",
        b"mobile-product.css",
        b"app-premium.css",
        b"sidebar-shell.css",
    ):
        assert stylesheet not in response.data


def test_bet_history_uses_v2_primitives_and_preserves_filters() -> None:
    for hook in (
        "history-page",
        "il-data-grid-page",
        "il-page-header",
        "il-page-title",
        "il-toolbar",
        "il-panel",
        "history-table",
        "history-pagination",
    ):
        assert hook in TEMPLATE

    for control_id in (
        "history-search",
        "history-wallet",
        "history-sport",
        "history-league",
        "history-event-type",
        "history-start",
        "history-end",
        "history-sort",
    ):
        assert f'id="{control_id}"' in TEMPLATE


def test_bet_history_v2_is_flat_and_token_driven() -> None:
    assert 'body[data-design-system="v2"][data-page="position-history"]' in CSS
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


def test_bet_history_table_becomes_labeled_mobile_cards() -> None:
    assert "min-width: 960px" in CSS
    assert "table-layout: fixed" in CSS
    assert "overflow-x: auto" in CSS
    assert "@media (max-width: 700px)" in CSS
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in CSS
    assert "content: attr(data-label)" in CSS
    assert ".history-table thead" in CSS

    for label in (
        "Detected",
        "Change",
        "Wallet",
        "Event / Market",
        "Selection",
        "League",
        "Position Value",
    ):
        assert f'data-label="{label}"' in SCRIPT


def test_bet_history_retains_query_and_pagination_workflow() -> None:
    for hook in (
        "loadHistory",
        "bindHistory",
        "historyRow",
        "/api/history",
        "paginationMarkup(payload)",
        "appState.pageNumber",
    ):
        assert hook in SCRIPT


def test_bet_history_asset_loads_after_foundation() -> None:
    foundation = BASE.index("filename='design-system.css'")
    canonical = BASE.index("filename='bet-history-v2.css'", foundation)

    assert canonical > foundation
    assert "-canonical-v1" in BASE[canonical : canonical + 200]
