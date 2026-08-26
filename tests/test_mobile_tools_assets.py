from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_core_tool_pages_load_the_mobile_workspace_assets():
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")

    assert "mobile-tools.css" in base
    assert "mobile-tools.js" in base
    for page in (
        "trades",
        "positive-ev",
        "arbitrage",
        "middles",
        "low-hold",
        "sharp-money",
        "odds-screen",
        "dfs",
        "calculators",
    ):
        assert page in base


def test_mobile_workspace_covers_every_expandable_feed():
    script = (ROOT / "static" / "mobile-tools.js").read_text(encoding="utf-8")

    for feed, detail in (
        ("#trade-list", "#trade-detail"),
        ("#ev-feed", "#ev-detail"),
        ("#arb-feed", "#arb-detail"),
        ("#mid-feed", "#mid-detail"),
        ("#lh-feed", "#lh-detail"),
        ("#sharp-signal-list", "#sharp-detail-panel"),
    ):
        assert feed in script
        assert detail in script

    assert "setupDfsCards" in script
    assert "All book comparisons" in script
    assert 'matchMedia("(max-width: 760px)")' in script


def test_mobile_styles_keep_tool_controls_and_detail_views_reachable():
    styles = (ROOT / "static" / "mobile-tools.css").read_text(encoding="utf-8")

    assert "@media (max-width: 760px)" in styles
    assert ".mobile-inline-detail" in styles
    assert ".dfs-mobile-player" in styles
    assert ".mobile-odds-sheet" in styles
    assert "min-height: 46px" in styles
    assert "env(safe-area-inset-bottom)" in styles
    assert "overflow-x: hidden" in styles


def test_phone_navigation_replaces_the_side_drawer_with_primary_actions_and_more_sheet():
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    styles = (ROOT / "static" / "sidebar-v2.css").read_text(encoding="utf-8")
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert 'class="mobile-bottom-nav"' in base
    assert 'id="mobile-more-toggle"' in base
    assert 'id="mobile-more-sheet"' in base
    for label in ("Money", "Traders", "Arbs", "+EV", "Track", "More"):
        assert f">{label}<" in base
    for destination in ("Fantasy Optimizer", "Middles", "Low Hold", "Sportsbook Screen", "Calculators", "LabTracker", "Shadow Lab", "Live Positions", "Sharp Wallets", "Bet History", "Edge Map", "Intelligence"):
        assert destination in base

    assert "@media (max-width:760px)" in styles
    assert "grid-template-columns:repeat(6,minmax(0,1fr))" in styles
    assert "transform:translateY(102%)" in styles
    assert "mobile-more-open" in script
    assert "openMobileMore" in script
    assert "moreFocusable" in script


def test_prediction_traders_mobile_search_keeps_icon_out_of_input_text():
    styles = (ROOT / "static" / "mobile-tools.css").read_text(encoding="utf-8")

    assert '.compact-search > i' in styles
    assert "position: static !important" in styles
    assert '.compact-search input[type="search"]' in styles
    assert "appearance: none" in styles


def test_trade_refresh_error_state_tolerates_inline_mobile_detail():
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert 'const tradeDetail = document.getElementById("trade-detail")' in script
    assert "if (tradeDetail)" in script
