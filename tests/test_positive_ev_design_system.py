from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "templates" / "positive_ev.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "static" / "positive-ev.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "positive-ev.css").read_text(encoding="utf-8")
DESIGN_SYSTEM = (ROOT / "static" / "design-system.css").read_text(encoding="utf-8")


def _function(name: str) -> str:
    start = SCRIPT.index(f"function {name}(")
    end = SCRIPT.find("\n  function ", start + 1)
    return SCRIPT[start:] if end == -1 else SCRIPT[start:end]


def test_positive_ev_opts_into_v2_without_legacy_layers() -> None:
    canonical_pages = "['trades', 'positive-ev', 'arbitrage', 'calculators', 'middles', 'low-hold', 'sharp-money', 'odds-screen', 'dfs', 'tracker', 'lab-tracker', 'shadow-test', 'live-positions', 'wallets', 'wallet-lock', 'position-history', 'edge-map', 'intelligence']"
    assert f"page in {canonical_pages} %}}" in BASE
    assert f'data-design-system="{{% if page in {canonical_pages} %}}v2' in BASE
    assert BASE.index("filename='design-system.css'") < BASE.index("filename='positive-ev.css'")

    for stylesheet in (
        "legacy-design-system.css",
        "stage2-art-direction.css",
        "shared-shell.css",
        "mobile-product.css",
    ):
        assert (
            f"page not in {canonical_pages} %}}<link rel=\"stylesheet\" "
            f"href=\"{{{{ url_for('static', filename='{stylesheet}'"
        ) in BASE

    for stylesheet in ("app-premium.css", "sidebar-shell.css"):
        assert (
            f"page not in ['home', 'trades', 'positive-ev', 'arbitrage', 'calculators', 'middles', 'low-hold', 'sharp-money', 'odds-screen', 'dfs', 'tracker', 'lab-tracker', 'shadow-test', 'live-positions', 'wallets', 'wallet-lock', 'position-history', 'edge-map', 'intelligence'] %}}<link rel=\"stylesheet\" "
            f"href=\"{{{{ url_for('static', filename='{stylesheet}'"
        ) in BASE


def test_positive_ev_reuses_canonical_components() -> None:
    for hook in (
        "il-page-header",
        "workspace-tabs",
        "search-control",
        "icon-button",
    ):
        assert hook in TEMPLATE

    for hook in (
        "il-confidence-display",
        "il-executable-quote",
        "il-provider-logo",
        "il-detail-section",
        "il-metric-group",
        "il-chart-container",
        "il-state",
    ):
        assert hook in SCRIPT + TEMPLATE

    assert "data-il-tooltip" in TEMPLATE
    assert "aria-label=\"Search Positive EV opportunities\"" in TEMPLATE


def test_positive_ev_reuses_prediction_traders_finance_toolbar_pattern() -> None:
    for hook in (
        "ev-finance-actions il-finance-controls",
        'id="ev-bankroll-popover-button"',
        'id="ev-bankroll-popover"',
        'id="ev-unit-toolbar-value"',
        'id="ev-filter-open"',
        'id="ev-active-filter-count"',
        'id="ev-more-menu-toggle"',
        'id="ev-more-menu"',
    ):
        assert hook in TEMPLATE

    assert 'requestJson("/api/user-settings")' in SCRIPT
    assert 'method:"PUT"' in SCRIPT
    assert "bankroll:bankrollConfig.amount" in SCRIPT
    assert ".ev-finance-actions" in CSS
    assert ".ev-bankroll-popover" in CSS
    assert ".ev-more-menu" in CSS
    assert ".ev-active-filter-count" in CSS


def test_devig_method_filter_is_single_choice_and_drives_api_query() -> None:
    assert 'class="ev-devig-methods" role="radiogroup"' in TEMPLATE
    assert TEMPLATE.count('name="devig-method"') == 4
    assert 'name="devig-method" value="power" checked' in TEMPLATE
    for method in ("power", "additive", "multiplicative", "shin"):
        assert f'value="{method}"' in TEMPLATE

    assert 'devigMethod: "power"' in SCRIPT
    assert 'input[name="devig-method"]:checked' in SCRIPT
    assert "devig_method:settings.devigMethod" in SCRIPT
    assert ".ev-devig-methods input:checked + span" in CSS
    assert ".ev-devig-methods input:focus-visible + span" in CSS


def test_threshold_filter_has_four_controls_and_required_book_multiselect() -> None:
    threshold_panel = TEMPLATE[
        TEMPLATE.index('data-filter-panel="thresholds"'):
        TEMPLATE.index('data-filter-panel="warnings"')
    ]
    for label in ("Min EV", "Kelly Multiplier", "Min # of Books", "Required Books"):
        assert label in threshold_panel
    for removed_id in (
        "ev-bankroll",
        "ev-max-quote-age",
        "ev-max-dispersion",
        "ev-max-stake-pct",
        "ev-max-event-pct",
    ):
        assert removed_id not in threshold_panel

    assert 'id="ev-required-books-control"' in threshold_panel
    assert 'id="ev-required-books-list"' in threshold_panel
    assert "requiredBooks: []" in SCRIPT
    assert "data-required-book" in SCRIPT
    assert "required_books:settings.requiredBooks.join" in SCRIPT
    assert "updateRequiredBooksSummary" in SCRIPT
    assert ".ev-required-books-dropdown" in CSS
    assert "z-index: var(--il-z-popover)" in CSS


def test_threshold_and_warning_panels_use_the_requested_type_and_spacing() -> None:
    assert "<h3>Bet Warnings</h3>" in TEMPLATE
    assert '.ev-filter-panel[data-filter-panel="thresholds"] > h3' in CSS
    assert '.ev-filter-panel[data-filter-panel="warnings"] > h3' in CSS
    assert "margin-bottom: var(--il-space-4)" in CSS
    assert ".ev-toggle-row strong { color: var(--il-text-primary); font-size: 14px; }" in CSS
    assert ".ev-toggle-row small { margin-top: 3px; color: var(--il-text-muted); font-size: 12px; }" in CSS


def test_positive_ev_keeps_the_locked_page_and_row_order() -> None:
    assert TEMPLATE.index('class="ev-credit-banner"') < TEMPLATE.index('class="ev-content"')
    assert TEMPLATE.index('id="ev-title"') < TEMPLATE.index('id="ev-search"')

    feed = _function("renderFeed")
    assert feed.index('class="ev-score') < feed.index('class="ev-event')
    assert feed.index('class="ev-event') < feed.index('class="ev-pick')
    assert feed.index('class="ev-pick') < feed.index('class="ev-execution')
    assert feed.index('class="ev-selection"') < feed.index('class="ev-bet-metrics"')
    assert feed.index('class="ev-bet-metrics"') < feed.index('class="ev-best-button')
    assert '<div class="ev-selection">' in feed
    assert '<input class="ev-selection"' not in feed
    assert "leagueWatermark(row)" in feed
    assert "matchup(row)" in feed
    assert 'class="ev-league-watermark"' in SCRIPT
    assert 'alt="" aria-hidden="true"' in SCRIPT

    select = _function("select")
    assert select.index("marketOddsVisual(row)") < select.index("ev-market-trend")
    assert select.index("ev-market-trend") < select.index("marketTrendVisual(row)")


def test_market_odds_remains_two_sided_with_provider_between_prices() -> None:
    market_odds = _function("marketOddsVisual")
    row = market_odds[market_odds.index('return `<div class="ev-market-compare-row">') :]
    assert row.index("priceCell(left, 0)") < row.index("ev-market-book-center")
    assert row.index("ev-market-book-center") < row.index("priceCell(right, 1)")
    assert "ev-market-compare-head" in market_odds
    assert "ev-market-compare-rows" in market_odds


def test_positive_ev_css_is_token_driven_and_page_owned() -> None:
    assert "!important" not in CSS
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", CSS)
    assert not re.search(r"\brgba?\(", CSS)
    assert not re.search(r"--il-[\w-]+\s*:", CSS)

    for token in (
        "var(--il-bg-app)",
        "var(--il-surface-1)",
        "var(--il-text-primary)",
        "var(--il-border-subtle)",
        "var(--il-brand)",
        "var(--il-positive)",
        "var(--il-focus)",
    ):
        assert token in CSS

    assert "grid-template-columns: minmax(0, 1fr) 550px" in CSS
    assert "grid-template-columns: 202px minmax(200px, .9fr) minmax(140px, .65fr) minmax(447px, 1.8fr)" in CSS
    assert "grid-template-columns: minmax(0, 1fr) 30px minmax(0, 1fr)" in CSS
    assert ".ev-selection" in CSS
    assert "box-shadow: inset 4px 0 0 var(--il-brand), 0 0 10px var(--il-brand-glow)" in CSS
    assert ".ev-opportunity:hover { border-color: var(--il-border-standard); background: var(--il-surface-play-card-purple-hover); transform: none; }" in CSS
    assert '.ev-opportunity.active {\n  border-width: 1px;' in CSS
    assert 'body[data-design-system="v2"][data-page="positive-ev"] .ev-score.il-confidence-display > strong' in CSS
    assert ".ev-bet-metrics { display: grid; grid-template-columns: auto auto; align-items: stretch; gap: var(--il-space-1); }" in CSS
    assert "border: 1px solid var(--il-border-subtle); border-radius: var(--il-radius-control); background: var(--il-surface-play-card-purple)" in CSS
    assert "flex-direction: column; align-items: center; justify-content: center" in CSS
    assert "text-align: center; font-variant-numeric" in CSS
    assert ".ev-execution" in CSS and "background: transparent" in CSS


def test_positive_ev_restores_the_locked_desktop_type_scale() -> None:
    for rule in (
        "font: 700 29px/1 var(--il-font-data)",
        "font: 700 12px/1 var(--il-font-ui)",
        "font-size: 16px",
        "font: var(--il-type-metadata)",
        "font: 700 22px/1.25 var(--il-font-ui)",
        "font: 650 14px/1.2 var(--il-font-ui)",
        "font: 700 20px/1.25 var(--il-font-ui)",
        "font: 700 18px/1.14 var(--il-font-ui)",
        "font: 650 10px/1.2 var(--il-font-ui)",
        "font: 700 16px/1 var(--il-font-data)",
        "font: 700 24px/1 var(--il-font-data)",
        "font: 700 20px/1.2 var(--il-font-ui)",
        "font: 700 14px/1.25 var(--il-font-ui)",
        "font: 600 11px/1.1 var(--il-font-data)",
        "font: 700 18px/1 var(--il-font-data)",
    ):
        assert rule in CSS

    assert ".ev-opportunity > .ev-score { padding: 11px 0 11px 9px; }" in CSS
    assert "width: 72px" in CSS
    assert "min-width: 98px" in CSS
    assert "border: 2px solid var(--il-brand-hover)" in CSS
    assert "box-shadow: 0 0 0 1px var(--il-border-interactive), var(--il-focus-shadow), 0 0 14px var(--il-brand-glow)" in CSS


def test_positive_ev_uses_real_league_logo_watermarks() -> None:
    for league in ("mlb", "wnba", "atp", "wta", "nba", "nfl", "nhl", "ncaa", "mls", "epl", "uefa", "fifa"):
        assert f'/static/assets/leagues/{league}.png' in SCRIPT
        assert (ROOT / "static" / "assets" / "leagues" / f"{league}.png").is_file()

    assert 'const leagueLogo = row =>' in SCRIPT
    assert 'return source ? `<img class="ev-league-watermark"' in SCRIPT
    assert ".ev-pick { position: relative; isolation: isolate; overflow: hidden; }" in CSS
    assert "opacity: .16" in CSS
    assert "pointer-events: none" in CSS


def test_positive_ev_matchups_use_high_resolution_team_assets() -> None:
    expected_counts = {"mlb": 30, "wnba": 13}
    for league, expected_count in expected_counts.items():
        assets = sorted((ROOT / "static" / "assets" / "teams" / league).glob("*.png"))
        assert len(assets) == expected_count
        for asset in assets:
            assert f'/static/assets/teams/{league}/{asset.name}' in SCRIPT

    assert 'class="ev-matchup-inline"' in SCRIPT
    assert SCRIPT.count('class="ev-team-logo"') == 2
    assert 'alt="" aria-hidden="true"' in SCRIPT
    assert ".ev-team-logo { width: 38px; height: 38px" in CSS
    assert "grid-template-rows: auto minmax(0, 1fr)" in CSS
    assert "text-align: center" in CSS
    assert ".ev-matchup-inline .ev-team-name { font-size: 17px" in CSS
    assert ".ev-team-logo { width: 28px; height: 28px; flex-basis: 28px; }" in CSS
    assert '.ev-league-watermark[src$="/mlb.png"]' in CSS
    assert "top: -33%" in CSS
    assert "height: 155%" in CSS
    assert "column-gap: .3em" in CSS
    assert "width: fit-content" in CSS
    assert "justify-self: center" in CSS
    assert '.ev-league-watermark[src$="/atp.png"]' in CSS


def test_positive_ev_responsive_and_accessibility_contracts() -> None:
    for breakpoint in (1600, 1320, 980, 640, 420):
        assert f"@media (max-width: {breakpoint}px)" in CSS

    assert "grid-template-columns: 144px minmax(195px, 1fr) minmax(67px, .6fr) minmax(298px, 1.45fr)" in CSS

    assert "overflow-x: hidden" in CSS
    assert "transform: translateY(102%)" in CSS
    assert ".ev-detail.open { transform: translateY(0); }" in CSS
    assert 'matchMedia("(max-width:980px)")' in SCRIPT
    assert 'detail.setAttribute("aria-modal", "true")' in SCRIPT
    assert 'if(event.key==="Escape")' in SCRIPT
    assert 'event.key!=="Tab"' in SCRIPT
    assert "lastFilterTrigger" in SCRIPT
    assert 'tab.setAttribute("aria-selected", String(active))' in SCRIPT
    assert '["ArrowLeft", "ArrowRight"]' in SCRIPT


def test_positive_ev_detail_heading_uses_compact_ev_percentage() -> None:
    assert 'class="ev-detail-head"><strong>${evPercent(row.evPercent)}</strong>' in SCRIPT
    assert 'class="ev-detail-head"><strong>${evPercent(row.evPercent)} EV</strong>' not in SCRIPT
    assert ".ev-detail-head > strong { color: var(--il-positive); font: 700 27px/1 var(--il-font-data);" in CSS


def test_market_trend_matches_market_odds_and_keeps_four_centered_metrics() -> None:
    assert ".ev-market-odds > header h3 { margin: 0; color: var(--il-text-primary); font: 700 20px/1.2 var(--il-font-ui);" in CSS
    assert ".ev-market-trend > header h3 { font: 700 20px/1.2 var(--il-font-ui); }" in CSS
    assert 'body[data-design-system="v2"][data-page="positive-ev"] .ev-trend-metrics.il-metric-group' in CSS
    assert "grid-template-columns: repeat(4, minmax(0, 1fr))" in CSS
    assert "justify-items: center; text-align: center;" in CSS
    assert 'body[data-design-system="v2"][data-page="positive-ev"] .ev-trend-metrics .il-metric b' in CSS
    assert "font: 700 16px/1 var(--il-font-data)" in CSS
    assert 'body[data-design-system="v2"][data-page="positive-ev"] .ev-trend-metrics .il-metric small { font-size: 12px' in CSS
    assert ".ev-chart-tabs button { min-height: 30px;" in CSS
    assert "font: 650 12px/1 var(--il-font-ui)" in CSS
    assert "font: 700 16px/1.2 var(--il-font-ui)" in CSS
    assert "font: 500 14px/1.2 var(--il-font-ui)" in CSS
    assert ".ev-trend-limit-label { fill: var(--il-text-muted); font: 500 12px var(--il-font-data); }" in CSS
    assert ".ev-trend-legend-toggle { min-height: 30px;" in CSS


def test_expanded_ev_explanation_and_sharp_odds_use_readable_type() -> None:
    assert ".ev-value-copy p { margin: 0; color: var(--il-text-secondary); font: 500 12px/1.55 var(--il-font-ui); }" in CSS
    assert ".ev-value-formula span { color: var(--il-text-muted); font: 650 12px/1.2 var(--il-font-ui); }" in CSS
    assert ".ev-value-formula code { min-width: 0; color: var(--il-text-secondary); font: 500 12px/1.3 var(--il-font-data);" in CSS
    assert ".ev-value-formula strong { color: var(--il-positive); font: 700 14px/1 var(--il-font-data); }" in CSS
    assert ".ev-sharp-book strong { color: var(--il-text-primary); font-size: 12px; }" in CSS
    assert ".ev-sharp-novig small { color: var(--il-text-muted); font-size: 10px; }" in CSS
    assert ".ev-sharp-novig b { color: var(--il-text-secondary); font: 700 12px/1.2 var(--il-font-data); }" in CSS
    assert ".ev-sharp-odds { color: var(--il-text-primary); font: 700 16px/1 var(--il-font-data);" in CSS
    assert ".ev-value-explanation summary span," in CSS
    assert ".ev-sharp-prices summary span { font-size: 12px; }" in CSS


def test_expanded_detail_uses_neon_flow_with_pure_black_content_boxes() -> None:
    assert "background-color: var(--il-bg-pure-black)" in CSS
    assert 'background-image: url("/static/assets/expanded-details-neon-flow-v1.webp")' in CSS
    assert "background-repeat: no-repeat" in CSS
    assert "background-position: center" in CSS
    assert "background-size: 100% 100%" in CSS
    assert (ROOT / "static" / "assets" / "expanded-details-neon-flow-v1.webp").is_file()
    assert ".ev-detail-pick" in CSS and "background: var(--il-bg-pure-black)" in CSS
    assert '.ev-market-odds.il-detail-section { background: var(--il-bg-pure-black); }' in CSS
    assert '.ev-market-trend.il-detail-section { background: var(--il-bg-pure-black); }' in CSS
    assert ".ev-trend-chart" in CSS and "background: var(--il-bg-pure-black)" in CSS
    assert '.ev-detail-accordion.il-detail-section { background: var(--il-bg-pure-black); }' in CSS
    assert ".ev-value-formula" in CSS and "background: var(--il-bg-pure-black)" in CSS


def test_header_divider_and_expanded_detail_reuse_the_sidebar_depth_palette() -> None:
    for token in (
        "--il-depth-edge: #b23cff",
        "--il-depth-highlight: #dd9cff",
        "--il-depth-mid: #68189b",
        "--il-depth-deep: #2c063f",
        "--il-depth-inset: rgba(228, 190, 255, .72)",
        "--il-depth-shadow: rgba(0, 0, 0, .72)",
    ):
        assert token in DESIGN_SYSTEM

    assert "border-bottom: 2px solid var(--il-depth-edge)" in CSS
    assert "inset 0 -1px 0 var(--il-depth-inset)" in CSS
    assert "0 1px 0 var(--il-depth-highlight)" in CSS
    assert "0 3px 0 var(--il-depth-mid)" in CSS
    assert "0 5px 0 var(--il-depth-deep)" in CSS
    assert "border-top: 2px solid var(--il-depth-edge)" not in CSS
    assert "border: 2px solid var(--il-depth-edge)" in CSS
    assert "inset 0 0 0 1px var(--il-depth-inset)" in CSS
    assert "0 0 0 1px var(--il-depth-highlight)" in CSS
    assert "0 0 0 3px var(--il-depth-mid)" in CSS
    assert "0 0 0 5px var(--il-depth-deep)" in CSS


def test_workspace_uses_the_sitewide_slate_canvas_without_changing_page_geometry() -> None:
    assert 'body[data-design-system="v2"][data-page="positive-ev"] .app-shell {' in CSS
    assert "height: 100dvh" in CSS
    assert "padding: var(--il-gutter-desktop)" in CSS
    assert "background: var(--il-bg-app)" in CSS
    assert "background-image: var(--il-sidebar-texture-image)" not in CSS
    assert ".ev-page {" in CSS and "background: transparent" in CSS


def test_play_cards_metrics_and_detail_odds_share_the_purple_surface() -> None:
    assert "background: var(--il-surface-play-card-purple)" in CSS
    assert ".ev-opportunity:hover { border-color: var(--il-border-standard); background: var(--il-surface-play-card-purple-hover); transform: none; }" in CSS
    assert "background: var(--il-surface-play-card-purple-active)" in CSS
    assert ".ev-bet-metric" in CSS and "background: var(--il-surface-play-card-purple)" in CSS
    assert ".ev-compare-price" in CSS and "background: var(--il-surface-play-card-purple)" in CSS
    assert ".ev-compare-price.best { border-color: var(--il-positive); background: var(--il-surface-play-card-purple); }" in CSS


def test_toolbar_icons_share_play_card_surfaces_and_search_content_does_not_overlap() -> None:
    assert '.ev-icon-button.icon-button { position: relative; background: var(--il-surface-play-card-purple); }' in CSS
    assert '.ev-icon-button.icon-button:hover { background: var(--il-surface-play-card-purple-hover); }' in CSS
    assert '.ev-icon-button[aria-pressed="true"] { border-color: var(--il-border-interactive); background: var(--il-surface-play-card-purple-active);' in CSS
    assert '.ev-search.search-control { background: var(--il-surface-play-card-purple); }' in CSS
    assert ".ev-search > i { position: static; flex: 0 0 auto;" in CSS
    assert "transform: none" in CSS
    assert ".ev-search input { width: auto; min-width: 0; flex: 1 1 auto;" in CSS


def test_toolbar_groups_hidden_bets_and_refresh_controls_in_more_menu() -> None:
    assert 'id="ev-more-menu-toggle"' in TEMPLATE
    assert 'id="ev-more-menu"' in TEMPLATE
    assert 'class="ph ph-eye-slash"' in TEMPLATE
    assert 'data-feed-view="active"' in TEMPLATE
    assert 'data-feed-view="hidden"' in TEMPLATE
    assert 'id="ev-refresh"' in TEMPLATE
    assert 'id="ev-pause"' in TEMPLATE
    assert 'ph-funnel-simple' not in TEMPLATE
    assert 'ph-bell' not in TEMPLATE
    assert 'ph-dots-three-vertical' in TEMPLATE
    assert 'ph-sidebar-simple' not in TEMPLATE
    assert 'id="ev-detail-toggle"' not in TEMPLATE
    assert 'grid-template-columns: minmax(0, 1fr) repeat(2, var(--il-control-height))' in CSS


def test_hidden_bets_view_reuses_manually_hidden_opportunities_and_supports_restore() -> None:
    assert 'feedView = "active"' in SCRIPT
    assert 'feedView === "hidden" ? isHidden : !isHidden' in SCRIPT
    assert 'data-restore="${esc(row.id)}"' in SCRIPT
    assert 'restoreOpportunity(button.dataset.restore)' in SCRIPT
    assert 'No hidden bets yet. Use Track and Hide on a bet to save it here.' in SCRIPT
    assert 'showDetailPlaceholder()' in SCRIPT
    assert 'No hidden bet selected' in SCRIPT
