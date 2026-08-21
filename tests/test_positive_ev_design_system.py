from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "templates" / "positive_ev.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "static" / "positive-ev.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "positive-ev.css").read_text(encoding="utf-8")


def _function(name: str) -> str:
    start = SCRIPT.index(f"function {name}(")
    end = SCRIPT.find("\n  function ", start + 1)
    return SCRIPT[start:] if end == -1 else SCRIPT[start:end]


def test_positive_ev_opts_into_v2_without_legacy_layers() -> None:
    canonical_pages = "['trades', 'positive-ev', 'sharp-money', 'odds-screen', 'dfs', 'tracker', 'lab-tracker', 'shadow-test', 'live-positions', 'wallets', 'wallet-lock', 'position-history', 'edge-map', 'intelligence']"
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
            f"page not in ['home', 'trades', 'positive-ev', 'sharp-money', 'odds-screen', 'dfs', 'tracker', 'lab-tracker', 'shadow-test', 'live-positions', 'wallets', 'wallet-lock', 'position-history', 'edge-map', 'intelligence'] %}}<link rel=\"stylesheet\" "
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
    assert "Live market scan" not in TEMPLATE
    assert 'id="ev-feed-label"' not in TEMPLATE
    assert '<small><i class="ph ${sportIcon(row)}"' not in feed

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
    assert ".ev-opportunity:hover { border-color: var(--il-border-standard); background: var(--il-surface-hover); transform: none; }" in CSS
    assert '.ev-opportunity.active {\n  border-width: 1px;' in CSS
    assert 'body[data-design-system="v2"][data-page="positive-ev"] .ev-score.il-confidence-display > strong' in CSS
    assert ".ev-bet-metrics { display: grid; grid-template-columns: auto auto; align-items: stretch; gap: var(--il-space-1); }" in CSS
    assert "border: 1px solid var(--il-border-subtle); border-radius: var(--il-radius-control); background: var(--il-surface-elevated)" in CSS
    assert "flex-direction: column; align-items: center; justify-content: center" in CSS
    assert "text-align: center; font-variant-numeric" in CSS
    assert ".ev-execution" in CSS and "background: transparent" in CSS


def test_positive_ev_restores_the_locked_desktop_type_scale() -> None:
    for rule in (
        "font: 700 27px/1 var(--il-font-data)",
        "font: 700 12px/1 var(--il-font-ui)",
        "font-size: 16px",
        "font: var(--il-type-metadata)",
        "font: 700 18px/1.25 var(--il-font-ui)",
        "font: 700 20px/1.25 var(--il-font-ui)",
        "font: 700 12px/1.14 var(--il-font-ui)",
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
    assert "grid-template-columns: minmax(152px, 1fr) auto auto" in CSS
    assert "white-space: nowrap" in CSS


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
    assert ".ev-team-logo { width: 34px; height: 34px" in CSS
    assert "grid-template-rows: auto minmax(0, 1fr)" in CSS
    assert "text-align: center" in CSS
    assert ".ev-matchup-inline .ev-team-name { font-size: 13px" in CSS
    assert ".ev-team-logo { width: 24px; height: 24px; flex-basis: 24px; }" in CSS
    assert '.ev-league-watermark[src$="/mlb.png"]' in CSS
    assert "height: 118%" in CSS
    assert '.ev-league-watermark[src$="/atp.png"]' in CSS
    assert 'class="ev-matchup-players"' in SCRIPT
    assert 'class="ev-player-name"' in SCRIPT
    assert ".ev-matchup-players" in CSS
    assert "column-gap: 7px" in CSS


def test_positive_ev_responsive_and_accessibility_contracts() -> None:
    for breakpoint in (1800, 1600, 1320, 980, 640, 420):
        assert f"@media (max-width: {breakpoint}px)" in CSS

    assert "grid-template-columns: 158px minmax(140px, 1fr) minmax(72px, .6fr) minmax(320px, 1.45fr)" in CSS

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
