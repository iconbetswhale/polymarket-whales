from pathlib import Path


TEMPLATE = Path("templates/arbitrage.html").read_text(encoding="utf-8")
BASE = Path("templates/base.html").read_text(encoding="utf-8")
CSS = Path("static/arbitrage.css").read_text(encoding="utf-8")
SCRIPT = Path("static/arbitrage.js").read_text(encoding="utf-8")


def test_arbitrage_is_a_canonical_v2_route_in_the_shared_shell() -> None:
    assert "page == 'arbitrage'" in BASE
    assert "url_for('arbitrage_page'" in BASE
    assert "ph-intersect-three" in BASE
    assert "arbitrage.css" in BASE
    assert "arbitrage.js" in BASE
    assert "'positive-ev'" in BASE
    assert "'arbitrage'" in BASE
    assert "'sharp-money'" in BASE


def test_arbitrage_page_exposes_the_complete_master_detail_workflow() -> None:
    for required in (
        'id="arb-search"',
        'id="arb-stake"',
        'id="arb-filter-dialog"',
        'id="arb-feed"',
        'id="arb-detail"',
        'id="arb-book-grid"',
        'id="arb-min-profit"',
        'id="arb-commission"',
        'id="arb-distinct-books"',
        'id="arb-learn-dialog"',
    ):
        assert required in TEMPLATE


def test_arbitrage_visuals_use_iconlabs_tokens_and_phosphor_icons() -> None:
    assert "var(--il-bg-app" in CSS
    assert "var(--il-brand" in CSS
    assert "var(--il-positive" in CSS
    assert "--arb-card: var(--arb-bg)" in CSS
    assert "--arb-panel: var(--il-surface-1" in CSS
    assert "--arb-panel-2: var(--il-surface-2" in CSS
    assert 'body[data-page="arbitrage"] :where(' not in CSS
    assert "ph ph-" in TEMPLATE
    assert "<svg" not in TEMPLATE
    assert "linear-gradient" not in CSS
    assert "radial-gradient" not in CSS


def test_arbitrage_cards_and_toolbar_adapt_to_their_content() -> None:
    assert "repeat(4, var(--il-control-height, 44px))" in CSS
    assert "grid-template-columns: 112px" in CSS
    assert "flex: 0 0 auto" in CSS
    assert ".arb-opportunity:has(.arb-leg-summary:nth-child(3))" in CSS
    assert ".arb-leg-summary > span:first-child" in CSS
    assert "grid-template-rows: auto 45px auto" in CSS


def test_market_context_is_not_rendered_in_card_or_detail_metadata() -> None:
    assert "const context = row.marketContext" not in SCRIPT
    assert '<small>${esc(context' not in SCRIPT
    assert '${esc(row.marketLabel)}${row.marketContext ?' not in SCRIPT


def test_requested_detail_labels_and_calculation_dropdown_are_rendered() -> None:
    assert "Stake Plan" in SCRIPT
    assert "Guaranteed Outcome" in SCRIPT
    assert "Odds Comparison" in SCRIPT
    assert '<details class="arb-detail-section arb-calculation">' in SCRIPT
    assert "sportLabel(row)" in SCRIPT
    assert '=== "EPL" ? "Soccer"' in SCRIPT
    assert ".arb-comparison-group h4" in CSS and "font-size: 15px" in CSS
    assert ".arb-quote-row span" in CSS and "font-size: 14px" in CSS
    assert ".arb-math-note p" in CSS and "font-size: 11px" in CSS
    assert ".arb-math-note code" in CSS and 'font: 600 10px/1.4 "DM Sans"' in CSS


def test_total_stake_input_formats_thousands_without_letter_spacing() -> None:
    assert 'id="arb-stake" type="text" value="1,000"' in TEMPLATE
    assert "function stakeInputValue" in SCRIPT
    assert "function stakeInputNumber" in SCRIPT
    assert "letter-spacing: 0" in CSS


def test_primary_interactions_and_visible_states_are_implemented() -> None:
    for required in (
        "function loadBoard",
        "function renderFeed",
        "function renderDetail",
        "function togglePause",
        "function renderBookGrid",
        "function copyPlan",
        "data-arb-start",
        "data-arb-retry",
        "data-arb-copy-plan",
        "showModal()",
    ):
        assert required in SCRIPT
