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


def test_locked_first_leg_is_the_recommended_sizing_workflow() -> None:
    assert '<option value="first-leg">Bet 1 stake</option>' in TEMPLATE
    assert '<strong>Lock Bet 1</strong>' in TEMPLATE
    assert "Recommended · calculate the exact hedge" in TEMPLATE
    assert 'stakeMode: "first-leg"' in SCRIPT
    assert "stake: 100" in SCRIPT


def test_low_hold_polish_keeps_primary_plan_visible_and_details_collapsed() -> None:
    assert 'id="lh-kpi-opportunities"' in TEMPLATE
    assert TEMPLATE.count("arb-kpi-strip") == 1
    assert "lh-leg-copy" in SCRIPT
    assert "lh-leg-numbers" in SCRIPT
    assert '<details class="lh-detail-disclosure">' in SCRIPT
    assert "Odds comparison" in SCRIPT
    assert "Calculation details" in SCRIPT
    assert "lh-result-section" in SCRIPT
    assert "Lower is more efficient" not in TEMPLATE
    assert "Chance to win both legs" not in TEMPLATE


def test_low_hold_rows_render_real_team_matchups_without_changing_the_payload() -> None:
    assert "teamLogoCodes" in SCRIPT
    assert "function matchupLogoMarkup" in SCRIPT
    assert 'class="lh-team-matchup"' in SCRIPT
    assert 'class="lh-matchup-vs">VS<' in SCRIPT
    assert "/static/assets/teams/${league}/" in SCRIPT
    assert ".lh-team-logo-frame" in CSS
