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
        "data-lh-start",
        "data-lh-retry",
        "data-lh-copy-plan",
        "showModal()",
    ):
        assert required in SCRIPT
