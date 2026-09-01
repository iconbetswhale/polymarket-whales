from pathlib import Path


TEMPLATE = Path("templates/low_hold.html").read_text(encoding="utf-8")
BASE = Path("templates/base.html").read_text(encoding="utf-8")
CSS = Path("static/low-hold.css").read_text(encoding="utf-8")
SCRIPT = Path("static/low-hold.js").read_text(encoding="utf-8")


def test_low_hold_is_a_canonical_v2_route_in_the_shared_shell() -> None:
    assert "page == 'low-hold'" in BASE
    assert "url_for('low_hold_page'" in BASE
    assert "ph-percent" in BASE
    assert "low-hold.css" in BASE
    assert "low-hold.js" in BASE
    assert "'arbitrage'" in BASE
    assert "'low-hold'" in BASE
    assert "'sharp-money'" in BASE


def test_low_hold_page_exposes_the_complete_master_detail_workflow() -> None:
    for required in (
        'id="lh-search"',
        'id="lh-stake"',
        'id="lh-stake-mode"',
        'id="lh-dialog-stake-label"',
        'id="lh-filter-dialog"',
        'id="lh-feed"',
        'id="lh-detail"',
        'id="lh-book-grid"',
        'id="lh-max-hold"',
        'id="lh-min-odds"',
        'id="lh-max-odds"',
        'id="lh-min-distance"',
        'id="lh-learn-dialog"',
        'id="lh-save-filter"',
    ):
        assert required in TEMPLATE


def test_low_hold_visuals_use_iconlabs_tokens_and_phosphor_icons() -> None:
    assert "var(--il-bg-app" in CSS
    assert "var(--il-brand" in CSS
    assert "var(--il-positive" in CSS
    assert "var(--il-surface-1" in CSS
    assert "ph ph-" in TEMPLATE
    assert "<svg" not in TEMPLATE
    assert "linear-gradient" not in CSS
    assert "radial-gradient" not in CSS


def test_primary_interactions_and_visible_states_are_implemented() -> None:
    for required in (
        "function loadBoard",
        "function renderFeed",
        "function renderDetail",
        "function togglePause",
        "function renderBookGrid",
        "function renderSavedFilters",
        "function saveFilter",
        "function copyPlan",
        "function syncStakeModeUI",
        "data-lh-start",
        "data-lh-retry",
        "data-lh-copy-plan",
        "data-lh-lock-leg",
        'params.set("stake_mode"',
        "showModal()",
    ):
        assert required in SCRIPT


def test_low_hold_comparison_uses_shared_draggable_book_order() -> None:
    assert 'draggable="true" data-line-shop-book' in SCRIPT
    assert "IconLabsLineShopOrder?.sortRows" in SCRIPT
    assert "IconLabsLineShopOrder?.bindDrag" in SCRIPT
    assert "quotes.slice(0, 8)" not in SCRIPT


def test_locked_first_leg_is_the_recommended_sizing_workflow() -> None:
    assert '<option value="first-leg">Bet 1 stake</option>' in TEMPLATE
    assert '<strong>Lock Bet 1</strong>' in TEMPLATE
    assert "Recommended · calculate the exact hedge" in TEMPLATE
    assert 'stakeMode: "first-leg"' in SCRIPT
    assert "stake: 100" in SCRIPT


def test_low_hold_polish_matches_the_live_arbitrage_queue_and_detail_format() -> None:
    assert 'id="lh-kpi-opportunities"' in TEMPLATE
    assert 'id="lh-kpi-books"' in TEMPLATE
    assert TEMPLATE.count("arb-kpi-strip") == 1
    assert 'class="arb-queue-rank"' in SCRIPT
    assert 'class="arb-queue-date"' in SCRIPT
    assert 'class="arb-detail-main"' in SCRIPT
    assert 'class="arb-detail-facts"' in SCRIPT
    assert 'class="arb-plan-head"' in SCRIPT
    assert 'class="arb-guaranteed-layout"' in SCRIPT
    assert 'class="arb-quote-head"' in SCRIPT
    assert '<details class="arb-detail-section arb-calculation">' in SCRIPT
    assert "Odds Comparison" in SCRIPT
    assert "Calculation Details" in SCRIPT
    assert "Balanced Outcome" in SCRIPT
    assert 'executable ? "Copy bet plan" : "Copy verification checklist"' in SCRIPT
    assert "THEORETICAL — VERIFY PRICES, LIMITS, SETTLEMENT, AND ELIGIBILITY BEFORE BETTING" in SCRIPT
    assert 'executable ? "Bet plan copied." : "Verification checklist copied."' in SCRIPT
    assert "Lower is more efficient" not in TEMPLATE
    assert "Chance to win both legs" not in TEMPLATE


def test_low_hold_inherits_arbitrage_sizing_and_formatting() -> None:
    assert "MARKET INEFFICIENCIES" in TEMPLATE
    assert TEMPLATE.count("arb-kpi-icon") == 4
    assert "--arb-card: var(--arb-bg)" in CSS
    assert "grid-template-columns: repeat(4, minmax(0, 1fr))" in CSS
    assert "padding: 14px 18px 16px" in CSS
    assert ".lh-page .arb-toolbar" not in CSS
    assert ".lh-page .arb-opportunity" not in CSS
    assert ".lh-page .arb-workspace" not in CSS
    assert ".lh-page .arb-detail-hero" not in CSS
    assert TEMPLATE.index('id="lh-detail"') < TEMPLATE.index('id="lh-feed"')
    assert TEMPLATE.count('class="arb-board-actions"') == 1
    assert TEMPLATE.count('class="arb-board-footer"') == 1


def test_low_hold_rows_use_the_live_arbitrage_compact_queue_contract() -> None:
    assert "function queueDateParts" in SCRIPT
    assert "function sportIcon" in SCRIPT
    assert 'grid-template-columns: repeat(4, minmax(0, 1fr))' in CSS
    assert 'class="arb-event-cell"' in SCRIPT
    assert 'class="arb-return-cell lh-hold-cell' in SCRIPT
    assert "arb-leg-summary" not in SCRIPT
    assert "arb-market-cell" not in SCRIPT
    assert "arb-legs-cell" not in SCRIPT
