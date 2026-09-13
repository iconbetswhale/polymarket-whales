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
        "positions-view-tabs",
        "my-bets-panel",
        "sharp-positions-panel",
        "live-positions-table",
        "personal-positions-table",
        "positions-cards",
    ):
        assert hook in TEMPLATE

    for control_id in (
        "personal-position-search",
        "personal-position-sportsbook",
        "personal-position-source",
        "personal-position-sort",
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
    assert "-positions-workspace-v23-text-sort-menu" in BASE[canonical : canonical + 240]


def test_positions_workspace_defaults_to_my_bets_and_keeps_sharp_positions() -> None:
    assert '<h1 id="positions-title">Positions</h1>' in TEMPLATE
    assert 'data-position-view="my-bets"' in TEMPLATE
    assert 'data-position-view="sharp-positions"' in TEMPLATE
    assert 'data-personal-position-status="upcoming"' in TEMPLATE
    assert 'data-personal-position-status="live"' in TEMPLATE
    assert 'data-personal-position-status="all"' in TEMPLATE
    assert 'fetchJson("/api/personal-positions?state=open")' in SCRIPT
    assert 'fetchJson(`/api/positions?${params.toString()}`)' in SCRIPT
    assert 'data-label="Source">${trackerSourceCompact({tracking_source: position.trackingSource})}' in SCRIPT
    assert ".personal-positions-table .tracker-sharp-compact" in CSS


def test_my_bets_uses_rich_filters_and_scan_friendly_rows() -> None:
    assert 'data-personal-filter-menu="sportsbook"' in TEMPLATE
    assert 'id="personal-position-sportsbook-options"' in TEMPLATE
    assert 'data-personal-filter-menu="source"' in TEMPLATE
    assert 'id="personal-position-source-options"' in TEMPLATE
    assert "function renderPersonalPositionFilter" in SCRIPT
    assert "personalPositionFilterIcon(kind, value)" in SCRIPT
    assert 'data-personal-filter-value="${escapeHtml(value)}"' in SCRIPT

    workspace_row = SCRIPT.split("function personalWorkspacePositionRow", 1)[1].split(
        "function personalWorkspacePositionCard", 1
    )[0]
    assert "position.buyFees" not in workspace_row

    assert ".live-positions-table.personal-positions-table tbody tr:nth-child(even) td" in CSS
    assert ".live-positions-table.personal-positions-table td:nth-child(3) > strong" in CSS
    assert "justify-content: center;" in CSS


def test_my_bets_row_branding_and_clean_values() -> None:
    workspace_row = SCRIPT.split("function personalWorkspacePositionRow", 1)[1].split(
        "function personalWorkspacePositionCard", 1
    )[0]
    assert "implied" not in workspace_row
    assert " shares" not in workspace_row
    assert "personalPositionEventMarkup(position)" in workspace_row
    assert "personalPositionSportsbookMarkup(position)" in workspace_row
    assert "personalPositionLeagueMarkup(position)" in workspace_row
    assert "oddsTeamLogoUrl(label)" in SCRIPT
    assert 'trackerCalendarSportIcon({sport_key: position.sportKey, league: position.league})' in SCRIPT
    market_rule = CSS.split("td .personal-position-market {", 1)[1].split("}", 1)[0]
    assert "font-size: 13px;" in market_rule
    even_row_rule = CSS.split("tbody tr:nth-child(even) td {", 1)[1].split("}", 1)[0]
    assert "background: var(--il-bg-workspace);" in even_row_rule


def test_my_bets_values_and_metadata_are_centered_under_headers() -> None:
    for selector in (
        ".live-positions-table.personal-positions-table th",
        ".live-positions-table.personal-positions-table td",
    ):
        rule = CSS.split(f"{selector} {{", 1)[1].split("}", 1)[0]
        assert "text-align: center;" in rule
    metadata_rule = CSS.split(".live-positions-table.personal-positions-table td small {", 1)[1].split("}", 1)[0]
    assert "margin-inline: auto;" in metadata_rule
    assert "td .personal-position-league {\n  justify-content: center;" in CSS
    source_note_rule = CSS.split(".personal-positions-table .personal-position-source-note {", 1)[1].split("}", 1)[0]
    assert "padding-left: 0;" in source_note_rule


def test_my_bets_has_clv_drawer_and_local_only_sample_bets() -> None:
    my_bets = TEMPLATE.split('id="my-bets-panel"', 1)[1].split('id="sharp-positions-panel"', 1)[0]
    assert ">CLV</th>" in my_bets
    assert ">P&amp;L</th>" not in my_bets
    assert 'id="personal-clv-dialog"' in TEMPLATE
    assert 'aria-labelledby="personal-clv-title"' in TEMPLATE
    assert 'data-personal-clv="${escapeHtml(position.positionId)}"' in SCRIPT
    assert 'aria-haspopup="dialog"' in SCRIPT
    assert "function renderPersonalClvDetails" in SCRIPT
    assert "Provisional · Not Final CLV" in SCRIPT
    assert "personalPositionClv(position)" in SCRIPT
    assert "if (!PERSONAL_CLV_LOCAL_PREVIEW) return [];" in SCRIPT
    assert 'isPreview: true' in SCRIPT
    assert 'Not A Real Wager Or Live Quote' in SCRIPT
    assert 'new Date(Date.now() + hours * 3600000)' in SCRIPT
    assert '.personal-clv-drawer::backdrop' in CSS
    assert 'width: min(540px, 100%);' in CSS
    assert ':has(.personal-clv-drawer[open])' in CSS
    preview_gate = SCRIPT.split('const PERSONAL_CLV_LOCAL_PREVIEW', 1)[1].split(';', 1)[0]
    assert 'page === "live-positions"' in preview_gate
    assert '["127.0.0.1", "localhost"].includes(window.location.hostname)' in preview_gate
    assert 'get("preview") === "1"' in preview_gate
    assert 'const weightedEntry = number(position.averageBuyEntry);' in SCRIPT


def test_clv_drawer_locks_comparison_to_placed_sportsbook() -> None:
    drawer = SCRIPT.split("function renderPersonalClvDetails", 1)[1].split(
        "function openPersonalClvDetails", 1
    )[0]
    assert "<select" not in drawer
    assert 'id="personal-clv-book"' in drawer
    assert 'personalPositionFilterIcon("sportsbook", position.provider || "Sportsbook")' in drawer
    assert 'personalPositionFilterIcon("source", position.trackingSource' in drawer
    assert "personal-clv-tracked-source" in drawer
    assert "Potential Payout" in drawer
    assert "Tracked From" in drawer
    assert "Price Improvement Vs Current" in drawer
    comparison = SCRIPT.split("function personalPositionLineComparison", 1)[1].split(
        "function personalPositionLinePercent", 1
    )[0]
    assert "sources[0]" not in comparison
    assert "personalPositionFilterKey(position.provider)" in comparison
    assert "sourceKey" not in comparison


def test_clv_drawer_requested_typography_and_selection_surface() -> None:
    sizes = {
        ".personal-clv-header h2": 25,
        ".personal-clv-header p": 14,
        ".personal-clv-sample-label": 12,
        ".personal-clv-event h3": 20,
        ".personal-clv-event p": 15,
        ".personal-clv-event .personal-position-league": 15,
        ".personal-clv-selection strong": 24,
        ".personal-clv-selection small": 16,
        ".personal-clv-comparison h3": 22,
        ".personal-clv-metric span": 14,
        ".personal-clv-metric small": 12,
        ".personal-clv-odds dt": 14,
        ".personal-clv-odds dd": 18,
        ".personal-clv-timestamp": 12,
        ".personal-clv-explanation": 12,
        ".personal-clv-bet-summary dt": 16,
        ".personal-clv-bet-summary dd": 18,
    }
    for selector, size in sizes.items():
        rule = CSS.split(f"{selector} {{", 1)[1].split("}", 1)[0]
        assert f"font-size: {size}px;" in rule
    assert "font: 700 42px/1.1 var(--il-font-data);" in CSS
    assert "font: 600 18px var(--il-font-ui);" in CSS
    selection = CSS.split(".personal-clv-selection {", 1)[1].split("}", 1)[0]
    assert "border: 2px solid var(--il-brand-hover);" in selection
    assert "background: var(--il-surface-play-card-purple);" in selection
    assert "text-transform: capitalize;" in selection


def test_clv_summary_has_one_row_and_larger_placed_book_branding() -> None:
    summary = CSS.split(".personal-clv-bet-summary {", 1)[1].split("}", 1)[0]
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in summary
    logo = CSS.split(".personal-clv-source-logo {", 1)[1].split("}", 1)[0]
    assert "width: 40px;" in logo
    assert "height: 40px;" in logo
    assert "flex: 0 0 40px;" in logo
    name = CSS.split(".personal-clv-source > strong {", 1)[1].split("}", 1)[0]
    assert "font: 600 18px var(--il-font-ui);" in name
    mobile = CSS.split("@media (max-width: 440px)", 1)[1]
    assert ".personal-clv-bet-summary dt {\n    min-height: 2.9em;" in mobile


def test_clv_current_odds_and_percentage_increase_and_prop_preview_notice() -> None:
    current = CSS.split(".personal-clv-odds dd.personal-clv-current-odds {", 1)[1].split("}", 1)[0]
    assert "font-size: 20px;" in current
    mobile = CSS.split("@media (max-width: 440px)", 1)[1]
    assert ".personal-clv-metric strong {\n    font-size: 32px;" in mobile
    assert ".personal-clv-odds dd.personal-clv-current-odds {\n    font-size: 18px;" in mobile
    assert 'class="${isCurrent ? "personal-clv-current-odds" : ""}"' in SCRIPT
    assert "Five sample prematch bets" in TEMPLATE
    assert "Includes three player props" in TEMPLATE


def test_my_bets_compact_table_keeps_names_unwrapped_and_all_columns() -> None:
    table = CSS.split(".personal-positions-table {", 1)[1].split("}", 1)[0]
    assert "min-width: 0;" in table
    assert "table-layout: auto;" in table
    assert "min-width: 1540px" not in CSS
    clv = CSS.split(".personal-position-clv {", 1)[1].split("}", 1)[0]
    assert "min-width: max-content;" in clv
    header = CSS.split(".live-positions-table.personal-positions-table th {", 1)[1].split("}", 1)[0]
    cell = CSS.split(".live-positions-table.personal-positions-table td {", 1)[1].split("}", 1)[0]
    assert "padding-inline: var(--il-space-1);" in header
    assert "padding: 9px var(--il-space-1);" in cell
    assert "font: 600 14px/1.3" in cell
    shared_cell = CSS.split(".live-positions-table td {", 1)[1].split("}", 1)[0]
    assert "white-space: nowrap;" in shared_cell
    start_time = CSS.split(".personal-position-start-time span {", 1)[1].split("}", 1)[0]
    assert "display: block;" in start_time
    assert "white-space: nowrap;" in start_time
    my_bets = TEMPLATE.split('id="my-bets-panel"', 1)[1].split('id="sharp-positions-panel"', 1)[0]
    assert "<th>Payout</th><th>Current</th>" in my_bets
    assert "<th>Potential Payout</th>" not in my_bets
    assert len(re.findall(r"<th(?:\s|>)", my_bets)) == 10
    row = SCRIPT.split("function personalWorkspacePositionRow", 1)[1].split("function personalWorkspacePositionCard", 1)[0]
    assert "personalPositionStartTimeMarkup(position.eventStartTime)" in row


def test_my_bets_current_odds_are_14px_without_subtext_and_clv_stays_16px() -> None:
    enlarged = CSS.split(".live-positions-table.personal-positions-table td .personal-position-clv strong {", 1)[1].split("}", 1)[0]
    assert "font-size: 16px;" in enlarged
    assert ".live-positions-table.personal-positions-table td:nth-child(9) > strong," not in CSS
    entry = CSS.split(".live-positions-table.personal-positions-table .position-market-link strong {", 1)[1].split("}", 1)[0]
    assert "font-size: 14px;" in entry
    assert "font-weight: 700;" in entry
    row = SCRIPT.split("function personalWorkspacePositionRow", 1)[1].split("function personalWorkspacePositionCard", 1)[0]
    assert "personalPositionCurrent(position, false)" in row
    card = SCRIPT.split("function personalWorkspacePositionCard", 1)[1].split("function renderPersonal", 1)[0]
    assert "personalPositionCurrent(position)" in card


def test_my_bets_sort_uses_same_rich_filter_as_all_sources() -> None:
    assert 'class="personal-rich-filter" id="personal-position-sort" data-personal-filter-menu="sort"' in TEMPLATE
    assert 'id="personal-position-sort-options" role="listbox" aria-label="Sort options"' in TEMPLATE
    assert 'id="personal-position-sort-icon"' not in TEMPLATE
    assert 'id="personal-position-sort-label">Start Time' in TEMPLATE
    assert '<select id="personal-position-sort"' not in TEMPLATE
    assert 'personalPositionSort: "start-asc"' in SCRIPT
    assert 'const sort = appState.personalPositionSort || "start-asc";' in SCRIPT
    assert 'renderPersonalPositionFilter("sort");' in SCRIPT
    assert 'getElementById("personal-position-sort").addEventListener("change"' not in SCRIPT
    for label in ("Start Time", "Highest Stake", "Recently Tracked"):
        assert f'label: "{label}"' in SCRIPT
    sort_popover = CSS.split("#personal-position-sort-options {", 1)[1].split("}", 1)[0]
    assert "right: 0;" in sort_popover
    sort_summary = CSS.split("#personal-position-sort > summary {", 1)[1].split("}", 1)[0]
    assert "grid-template-columns: minmax(0, 1fr) 14px;" in sort_summary
    sort_option = CSS.split("#personal-position-sort-options button {", 1)[1].split("}", 1)[0]
    assert "grid-template-columns: minmax(0, 1fr);" in sort_option
    assert 'if (menu.dataset.personalFilterMenu !== "sort") return;' in SCRIPT
    assert '["ArrowDown", "ArrowUp"].includes(event.key)' in SCRIPT
