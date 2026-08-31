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
    desktop_hide = styles[: styles.index("@media (max-width: 760px)")]
    assert ".dfs-mobile-list" in desktop_hide
    assert "display: none" in desktop_hide
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
    assert "bottom:0" in styles
    assert "border-radius:17px 17px 0 0" in styles
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
    assert "window.innerWidth <= 760" in script
    assert 'list.querySelector(":scope > #trade-detail.mobile-inline-detail")' in script


def test_mobile_dfs_picker_keeps_one_active_app_and_an_other_apps_control():
    template = (ROOT / "templates" / "dfs.html").read_text(encoding="utf-8")
    styles = (ROOT / "static" / "mobile-tools.css").read_text(encoding="utf-8")
    script = (ROOT / "static" / "mobile-tools.js").read_text(encoding="utf-8")

    assert 'id="dfs-mobile-book-select"' in template
    assert "Other apps" in template
    assert ".dfs-book.active" in styles
    assert "setupDfsAppPicker" in script
    assert 'nextBook?.click()' in script


def test_mobile_dfs_filters_collapse_behind_a_compact_icon_control():
    template = (ROOT / "templates" / "dfs.html").read_text(encoding="utf-8")
    styles = (ROOT / "static" / "mobile-tools.css").read_text(encoding="utf-8")
    script = (ROOT / "static" / "mobile-tools.js").read_text(encoding="utf-8")

    assert 'id="dfs-mobile-filter-toggle"' in template
    assert 'aria-controls="dfs-filter-bar"' in template
    assert 'id="dfs-mobile-filter-summary"' in template
    assert ".dfs-mobile-filter-command" in styles
    assert ".dfs-filter-bar.mobile-open" in styles
    assert "setupDfsFilters" in script
    assert 'deck.classList.toggle("mobile-filters-open"' in script


def test_mobile_dfs_detail_uses_logos_and_horizontal_over_under_prices():
    dfs_script = (ROOT / "static" / "dfs.js").read_text(encoding="utf-8")
    mobile_script = (ROOT / "static" / "mobile-tools.js").read_text(encoding="utf-8")
    styles = (ROOT / "static" / "mobile-tools.css").read_text(encoding="utf-8")

    assert "mobileDetailPayload" in dfs_script
    assert 'data-mobile-detail="${esc(mobileDetail)}"' in dfs_script
    assert "over:sidePayload(pair.over)" in dfs_script
    assert "under:sidePayload(pair.under)" in dfs_script
    assert "appendDfsLogoValue" in mobile_script
    assert 'appendDfsComparisonSide(prices, "O"' in mobile_script
    assert 'appendDfsComparisonSide(prices, "U"' in mobile_script
    assert 'image.title = book.name || ""' in mobile_script
    assert ".dfs-mobile-comparison-prices" in styles
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in styles


def test_mobile_dfs_starts_directly_below_the_brand_bar_and_recovers_failed_feeds():
    template = (ROOT / "templates" / "dfs.html").read_text(encoding="utf-8")
    dfs_script = (ROOT / "static" / "dfs.js").read_text(encoding="utf-8")
    styles = (ROOT / "static" / "mobile-tools.css").read_text(encoding="utf-8")

    assert 'body[data-design-system="v2"][data-page="dfs"] .app-shell' in styles
    assert "min-height: calc(100dvh - 62px) !important" in styles
    assert "padding: 0 !important" in styles
    assert "Find the strongest projection edge" not in template
    assert "padding: 4px 10px" in styles
    assert 'id="dfs-feed-notice"' in template
    assert 'id="dfs-error-retry"' in template
    assert "persistentSnapshotMaxAgeMs = 15*60*1000" in dfs_script
    assert "readPersistentSnapshot()" in dfs_script
    assert "writePersistentSnapshot(payload)" in dfs_script
    assert "timedOut = true" in dfs_script
    assert "},12000)" in dfs_script


def test_mobile_dvig_uses_compact_two_column_book_controls():
    styles = (ROOT / "static" / "mobile-tools.css").read_text(encoding="utf-8")

    assert "DVIG becomes a dense, two-column control sheet on phones" in styles
    assert 'body[data-design-system="v2"][data-page="dfs"] .dfs-devig-list' in styles
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in styles
    assert "grid-template-columns: 24px minmax(0, 1fr) 48px !important" in styles
    assert "grid-column: 1 / -1 !important" in styles


def test_mobile_ev_market_prices_are_optically_centered():
    styles = (ROOT / "static" / "mobile-tools.css").read_text(encoding="utf-8")

    assert ".ev-market-comparison .ev-compare-price" in styles
    assert "justify-content: center" in styles
    assert ".ev-market-comparison .ev-compare-price strong" in styles
    assert "text-align: center" in styles


def test_prediction_traders_mobile_is_scan_first_with_labeled_samples():
    template = (ROOT / "templates" / "trades.html").read_text(encoding="utf-8")
    styles = (ROOT / "static" / "mobile-tools.css").read_text(encoding="utf-8")
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert 'id="mobile-trade-samples"' in template
    assert "Sample layout · not live recommendations" in template
    assert "More plays are coming" in template
    assert ".trades-command-bar" in styles
    assert ".trade-summary-strip" in styles
    assert "mobileTradeSamples.hidden = appState.trades.length > 0" in script
