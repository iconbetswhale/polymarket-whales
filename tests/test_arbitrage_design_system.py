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
    assert TEMPLATE.index('id="arb-detail"') < TEMPLATE.index('id="arb-feed"')
    assert 'class="arb-board-footer"' in TEMPLATE


def test_existing_summary_metric_bar_is_preserved() -> None:
    assert 'class="arb-kpi-strip il-kpi-strip"' in TEMPLATE
    assert '.arb-kpi-strip { display: none; }' not in CSS
    for label in ("Opportunities", "Best return", "Top profit", "Books compared"):
        assert label in TEMPLATE
    for description in (
        "Awaiting scan",
        "Modeled if every leg fills",
        "On a $1,000 stake",
        "Selected execution venues",
    ):
        assert description in TEMPLATE


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


def test_proof_first_workspace_and_ranked_queue_adapt_to_their_content() -> None:
    assert "repeat(4, var(--il-control-height, 44px))" in CSS
    assert "grid-template-columns: minmax(620px, 1.7fr) minmax(340px, .76fr)" in CSS
    assert ".arb-detail { grid-column: 1; grid-row: 1; }" in CSS
    assert "grid-template-rows: auto minmax(0, 1fr) auto" in CSS
    assert "grid-template-columns: 28px 74px minmax(130px, 1fr) 76px" in CSS
    assert ".arb-guaranteed-layout" in CSS
    assert ".arb-comparison-grid" in CSS
    assert "queueDateParts" in SCRIPT
    assert "rows.map(opportunityCard)" in SCRIPT


def test_market_context_is_not_rendered_in_card_or_detail_metadata() -> None:
    assert "const context = row.marketContext" not in SCRIPT
    assert '<small>${esc(context' not in SCRIPT
    assert '${esc(row.marketLabel)}${row.marketContext ?' not in SCRIPT


def test_requested_detail_labels_and_calculation_dropdown_are_rendered() -> None:
    assert "Stake Plan" in SCRIPT
    assert "Mathematical Payout" in SCRIPT
    assert "only if every listed leg is accepted" in SCRIPT
    assert "Guaranteed" not in TEMPLATE
    assert "guaranteed" not in TEMPLATE
    assert "Odds Comparison" in SCRIPT
    assert '<details class="arb-detail-section arb-calculation">' in SCRIPT
    assert "sportLabel(row)" in SCRIPT
    assert '=== "EPL" ? "Soccer"' in SCRIPT
    assert ".arb-comparison-group h4" in CSS and "font-size: 16px" in CSS
    assert ".arb-quote-row span" in CSS and "font-size: 15px" in CSS
    assert "<span>Stake</span><span>Payout</span>" in SCRIPT
    assert "projectedStake" in SCRIPT and "projectedPayout" in SCRIPT
    assert ".arb-math-note p" in CSS and "font-size: 12px" in CSS
    assert ".arb-math-note code" in CSS and 'font: 600 12px/1.4 "DM Sans"' in CSS
    assert "row.calculationVersion" not in SCRIPT


def test_requested_arbitrage_typography_and_alignment_are_explicit() -> None:
    for rule in (
        ".arb-queue-rank { color: var(--arb-secondary); font-size: 14px",
        ".arb-return-cell strong { color: var(--arb-green); font-size: 20px",
        ".arb-return-cell span { margin-top: 5px; color: var(--arb-green); font-size: 12px",
        ".arb-event-cell h3 { display: flex; align-items: flex-start; gap: 6px; margin: 0; color: var(--arb-text); font-size: 15px",
        ".arb-event-cell p { margin: 5px 0 0 22px; overflow: hidden; color: var(--arb-muted); font-size: 12px",
        ".arb-queue-date { display: flex; min-width: 0; flex-direction: column; align-items: flex-end; justify-content: center; color: var(--arb-secondary); font-size: 12px",
        ".arb-queue-date small { margin-top: 4px; color: var(--arb-muted); font-size: 12px",
        ".arb-detail-return strong { color: var(--arb-green); font-size: 30px",
        ".arb-detail-return span { color: var(--arb-green); font-size: 12px",
        ".arb-detail-hero h2 { margin: 8px 0 0; color: var(--arb-text); font-size: 18px",
        ".arb-detail-hero p { margin: 4px 0 0; color: var(--arb-muted); font-size: 14px",
        ".arb-detail-facts dt { color: var(--arb-muted); font-size: 12px",
        ".arb-detail-facts dd { margin: 7px 0 0; overflow: hidden; color: var(--arb-text); font-size: 15px",
        ".arb-detail-actions button { height: 38px; font-size: 13px",
        ".arb-detail-section h3 { margin: 0; color: var(--arb-text); font-size: 16px",
        ".arb-plan-head { padding: 0 10px 5px; color: var(--arb-muted); font-size: 12px",
        ".arb-plan-outcome strong { font-size: 15px",
        ".arb-plan-outcome small { display: block; margin-top: 4px; color: var(--arb-muted); font-size: 12px",
        ".arb-plan-book strong { font-size: 14px",
        ".arb-plan-odds { font-size: 15px",
        ".arb-plan-payout { font-size: 14px",
        ".arb-plan-stake b { color: var(--arb-text); font-size: 14px",
        ".arb-bet-link { display: inline-flex; align-items: center; justify-content: center; gap: 4px; min-width: 54px; height: 29px; border: 1px solid rgba(80, 217, 119, .55); border-radius: 6px; color: var(--arb-green); font-size: 14px",
        ".arb-payout-row span { overflow: hidden; color: var(--arb-secondary); font-size: 12px",
        ".arb-payout-row b { color: var(--arb-green); font-size: 13px",
        ".arb-quote-head { display: grid; grid-template-columns: 20px minmax(0, 1fr) 28px 40px 64px 64px; gap: 4px; padding: 4px 6px; border-bottom: 1px solid rgba(71, 85, 105, .4); color: var(--arb-muted); font-size: 11px",
        ".arb-quote-row small { color: var(--arb-muted); font-size: 10px",
        ".arb-quote-row b { color: var(--arb-text); font-size: 14px",
        ".arb-quote-row strong { color: var(--arb-secondary); font-size: 12px",
        ".arb-detail-warning { display: flex; gap: 7px; margin-top: 8px; color: var(--arb-yellow); font-size: 12px",
    ):
        assert rule in CSS

    assert ".arb-plan-head span:nth-child(4)," in CSS
    assert ".arb-plan-head span:nth-child(5) { text-align: center; }" in CSS
    assert ".arb-plan-outcome { text-align: center; }" not in CSS
    assert ".arb-plan-book { display: flex; align-items: center; gap: 8px; }" in CSS
    assert "background: transparent" in CSS
    assert "border: 0" in CSS


def test_selection_rows_and_best_price_emphasis_match_the_reference() -> None:
    assert '"Capacity unverified"' not in SCRIPT
    assert ".arb-quote-row.best { position: relative; z-index: 1; border-radius: 5px" in CSS
    assert "box-shadow: inset 0 0 0 1px rgba(80, 217, 119, .78), 0 0 12px rgba(80, 217, 119, .32)" in CSS
    assert ".arb-quote-row strong:last-child { color: var(--arb-green); }" in CSS


def test_total_stake_input_formats_thousands_without_letter_spacing() -> None:
    assert 'id="arb-stake" type="text" value="1,000"' in TEMPLATE
    assert "function stakeInputValue" in SCRIPT
    assert "function stakeInputNumber" in SCRIPT
    assert "letter-spacing: 0" in CSS
    assert ".arb-money-input:focus-within" in CSS
    assert ".arb-money-input input:focus-visible { outline: 0; }" in CSS


def test_play_card_selection_and_sport_treatments_are_explicit() -> None:
    assert ".arb-opportunity.active { border-width: 2px" in CSS
    assert ".arb-event-cell h3 span" in CSS
    assert ".arb-queue-date" in CSS
    assert "arb-queue-rank" in SCRIPT
    assert "function sportIcon" in SCRIPT
    for icon in ("ph-baseball", "ph-basketball", "ph-soccer-ball", "ph-football"):
        assert icon in SCRIPT
    assert "best-price" not in TEMPLATE
    assert "fee-aware" not in TEMPLATE


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


def test_arbitrage_comparison_uses_shared_draggable_book_order() -> None:
    assert 'draggable="true" data-line-shop-book' in SCRIPT
    assert "IconLabsLineShopOrder?.sortRows" in SCRIPT
    assert "IconLabsLineShopOrder?.bindDrag" in SCRIPT
    assert "quotes.slice(0, 8)" not in SCRIPT
