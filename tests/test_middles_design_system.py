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
