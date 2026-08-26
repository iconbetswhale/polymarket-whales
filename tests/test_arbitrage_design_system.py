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
    assert "'positive-ev', 'arbitrage', 'sharp-money'" in BASE


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
        "function copyPlan",
        "data-arb-start",
        "data-arb-retry",
        "data-arb-copy-plan",
        "showModal()",
    ):
        assert required in SCRIPT
