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
    canonical_pages = "['trades', 'positive-ev', 'sharp-money', 'odds-screen']"
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
            f"page not in ['home', 'trades', 'positive-ev', 'sharp-money', 'odds-screen'] %}}<link rel=\"stylesheet\" "
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

    assert "grid-template-columns: minmax(0, 1fr) clamp(420px, 25vw, 480px)" in CSS
    assert "grid-template-columns: 202px minmax(210px, 1fr)" in CSS
    assert "grid-template-columns: minmax(0, 1fr) 30px minmax(0, 1fr)" in CSS
    assert ".ev-selection" in CSS
    assert "box-shadow: inset 3px 0 0 var(--il-brand)" in CSS
    assert 'body[data-design-system="v2"][data-page="positive-ev"] .ev-score.il-confidence-display > strong' in CSS
    assert ".ev-bet-metrics { display: grid; grid-template-columns: auto auto; align-items: stretch; gap: var(--il-space-1); }" in CSS
    assert "border: 1px solid var(--il-border-subtle); border-radius: var(--il-radius-control); background: var(--il-surface-elevated)" in CSS
    assert "flex-direction: column; align-items: center; justify-content: center" in CSS
    assert "text-align: center; font-variant-numeric" in CSS
    assert ".ev-execution" in CSS and "background: transparent" in CSS


def test_positive_ev_responsive_and_accessibility_contracts() -> None:
    for breakpoint in (1600, 1320, 980, 640, 420):
        assert f"@media (max-width: {breakpoint}px)" in CSS

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
