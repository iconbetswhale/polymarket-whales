from pathlib import Path


TEMPLATE = Path("templates/middles.html").read_text(encoding="utf-8")
BASE = Path("templates/base.html").read_text(encoding="utf-8")
CSS = Path("static/middles.css").read_text(encoding="utf-8")
SCRIPT = Path("static/middles.js").read_text(encoding="utf-8")


def test_middles_is_a_canonical_v2_route_in_the_shared_shell() -> None:
    assert "page == 'middles'" in BASE
    assert "url_for('middles_page'" in BASE
    assert "ph-arrows-in-line-horizontal" in BASE
    assert "middles.css" in BASE
    assert "middles.js" in BASE
    assert "'middles'" in BASE


def test_middles_exposes_the_complete_scan_plan_and_filter_workflow() -> None:
    for required in (
        'id="mid-search"',
        'id="mid-stake"',
        'id="mid-filter-dialog"',
        'id="mid-feed"',
        'id="mid-detail"',
        'id="mid-book-grid"',
        'id="mid-min-width"',
        'id="mid-max-cost"',
        'id="mid-commission"',
        'id="mid-distinct-books"',
        'id="mid-learn-dialog"',
    ):
        assert required in TEMPLATE


def test_middles_visuals_use_iconlabs_tokens_and_real_icon_assets() -> None:
    assert "var(--il-bg-workspace" in CSS
    assert "var(--il-brand" in CSS
    assert "var(--il-positive" in CSS
    assert "var(--il-surface-play-card-purple" in CSS
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
        "function toggleTracked",
        "showModal()",
        'data-mid-id',
    ):
        assert required in SCRIPT


def test_middles_comparison_uses_shared_draggable_book_order() -> None:
    assert 'draggable="true" data-line-shop-book' in SCRIPT
    assert "IconLabsLineShopOrder?.sortRows" in SCRIPT
    assert "IconLabsLineShopOrder?.bindDrag" in SCRIPT


def test_middles_polish_keeps_the_requested_information_hierarchy() -> None:
    assert "mid-summary-metrics" in TEMPLATE
    assert "mid-scan-status" in TEMPLATE
    assert TEMPLATE.count("mid-summary-count") == 1
    assert "mid-card-outcome" in SCRIPT
    assert "Guaranteed outcome" in SCRIPT
    assert "Equalized stakes" in SCRIPT
    assert '<h3>Payout scenarios</h3>' in SCRIPT
    assert "qualified windows" not in TEMPLATE
    assert "RANKED BY LOWEST BREAK-EVEN" not in TEMPLATE
    assert "BOTH WIN" not in SCRIPT


def test_sportsbook_logos_are_normalized_and_fail_safely() -> None:
    assert 'decoding="async"' in SCRIPT
    assert "mid-book-logo-fallback" in SCRIPT
    assert "onerror=" in SCRIPT
    assert "object-fit: contain" in CSS
    assert "object-position: center" in CSS
    assert ".mid-book-logo {" in CSS
    assert "background: transparent" in CSS
    assert "border: 0" in CSS
    assert "padding: 0" in CSS
    assert ".mid-book-logo-fallback" in CSS
    assert "background: var(--il-surface-selected-badge)" in CSS
