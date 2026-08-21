from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STYLE_PATH = ROOT / "static" / "style.css"
DESIGN_SYSTEM_PATH = ROOT / "static" / "design-system.css"
TRADES_STYLE_PATH = ROOT / "static" / "stage2-trades.css"
SCRIPT_PATH = ROOT / "static" / "app.js"
TEMPLATE_PATH = ROOT / "templates" / "base.html"
TRADES_TEMPLATE_PATH = ROOT / "templates" / "trades.html"


def _function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    next_function = source.find("\nfunction ", start + 1)
    return source[start:] if next_function == -1 else source[start:next_function]


def _rule_bodies(css: str, selector_fragment: str) -> list[str]:
    return [
        body
        for selector, body in re.findall(r"(?s)([^{}]+)\{([^{}]*)\}", css)
        if selector_fragment in selector
    ]


def test_product_foundation_defines_semantic_visual_tokens():
    css = DESIGN_SYSTEM_PATH.read_text(encoding="utf-8")

    for token in (
        "--il-bg-app",
        "--il-bg-sidebar",
        "--il-surface-1",
        "--il-surface-2",
        "--il-surface-elevated",
        "--il-surface-hover",
        "--il-surface-selected",
        "--il-border-subtle",
        "--il-border-standard",
        "--il-border-interactive",
        "--il-text-primary",
        "--il-text-secondary",
        "--il-text-muted",
        "--il-brand",
        "--il-brand-hover",
        "--il-positive",
        "--il-negative",
        "--il-warning",
    ):
        assert token in css

    assert '--il-font-ui: "DM Sans", Inter, sans-serif' in css
    assert '--il-font-data: "DM Sans", Inter, sans-serif' in css
    assert "font-variant-numeric: tabular-nums lining-nums" in css
    for role in (
        "--il-type-page-title",
        "--il-type-section-title",
        "--il-type-card-title",
        "--il-type-primary-metric",
        "--il-type-body",
        "--il-type-metadata",
        "--il-type-micro-label",
        "--il-type-table-header",
        "--il-type-numeric-data",
        "--il-type-sidebar-nav",
        "--il-type-control",
    ):
        assert role in css


def test_canonical_pages_opt_into_the_v2_foundation_last():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert 'data-design-system="{% if page in [\'trades\', \'positive-ev\', \'sharp-money\', \'odds-screen\', \'dfs\', \'tracker\'] %}v2' in template
    assert "filename='trades-hierarchy.css'" not in template
    assert "page == 'tracker' %}<link rel=\"stylesheet\" href=\"{{ url_for('static', filename='premium-compact.css'" in template

    late_foundation = template.rindex("foundation-v6")
    late_trades = template.index("filename='stage2-trades.css'", late_foundation)
    late_positive_ev = template.index("filename='positive-ev.css'", late_foundation)
    late_sharp_money = template.index("filename='sharp-money-v2.css'", late_foundation)
    late_odds_screen = template.index("filename='odds-screen-v2.css'", late_foundation)
    late_dfs = template.index("filename='dfs-v2.css'", late_foundation)
    late_tracker = template.index("filename='tracker-v2.css'", late_foundation)
    assert late_foundation > template.index("filename='app-premium.css'")
    assert late_foundation > template.index("filename='sidebar-shell.css'")
    assert late_trades > late_foundation
    assert late_positive_ev > late_foundation
    assert late_sharp_money > late_foundation
    assert late_odds_screen > late_foundation
    assert late_dfs > late_foundation
    assert late_tracker > late_foundation


def test_canonical_pages_do_not_reload_legacy_override_layers():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    design_css = DESIGN_SYSTEM_PATH.read_text(encoding="utf-8")
    trades_css = TRADES_STYLE_PATH.read_text(encoding="utf-8")

    for stylesheet in (
        "legacy-design-system.css",
        "stage2-art-direction.css",
        "shared-shell.css",
        "mobile-product.css",
        "app-premium.css",
        "sidebar-shell.css",
    ):
        excluded_for_canonical_pages = (
            f"page not in ['trades', 'positive-ev', 'sharp-money', 'odds-screen', 'dfs', 'tracker'] %}}<link rel=\"stylesheet\" href=\"{{{{ url_for('static', filename='{stylesheet}'"
            in template
        )
        excluded_for_home_and_canonical_pages = (
            f"page not in ['home', 'trades', 'positive-ev', 'sharp-money', 'odds-screen', 'dfs', 'tracker'] %}}<link rel=\"stylesheet\" href=\"{{{{ url_for('static', filename='{stylesheet}'"
            in template
        )
        assert excluded_for_canonical_pages or (
            stylesheet in {"app-premium.css", "sidebar-shell.css"}
            and excluded_for_home_and_canonical_pages
        )

    assert design_css.count("!important") <= 4
    assert trades_css.count("!important") <= 3


def test_prediction_feed_uses_separated_cards_and_a_five_track_scan_path():
    css = TRADES_STYLE_PATH.read_text(encoding="utf-8")
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    template = TRADES_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert (
        "--trade-row-grid: 76px minmax(270px, 1fr) minmax(150px, 190px) "
        "132px 68px"
    ) in css
    assert "grid-template-columns: var(--trade-row-grid)" in css

    list_rules = "\n".join(_rule_bodies(css, ".trade-list"))
    card_rules = "\n".join(_rule_bodies(css, ".trade-card"))
    assert "gap: 8px" in list_rules
    assert "min-height: 112px" in card_rules
    assert "border: 1px solid var(--il-border-subtle)" in card_rules
    assert "border-radius: 9px" in card_rules
    assert "background: var(--il-surface-1)" in card_rules
    assert ".trade-card.is-selected" in css

    assert '<h2>Top Opportunities</h2>' in template
    assert "trade-view-action" not in script
    assert "data-trade-view" in script
    assert "max-width: 1160px" not in css
    assert "trades-hierarchy" not in css


def test_prediction_cards_keep_signals_human_and_quotes_logo_first():
    css = TRADES_STYLE_PATH.read_text(encoding="utf-8")
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    card_function = _function(script, "tradeCard")
    quote_function = _function(script, "executableQuoteChip")

    assert "trade-confidence-indicator" not in card_function
    assert ".trade-confidence-indicator" not in css
    assert "trade-signal-summary" in card_function
    for phrase in ("sharp", "size", "hit"):
        assert phrase in card_function.lower()
    assert "metricIconMarkup" not in script
    stake_function = _function(script, "recommendedBetMarkup")
    assert "trade-bet-size" in stake_function
    assert "<small>Bet Size</small>" in stake_function
    assert '.trade-bet-size::before' not in css
    assert "trade-view-action" not in card_function
    assert "trade-event-action" in card_function

    assert "executable-quote-chip" in quote_function
    assert "providerLogoMarkup" in quote_function
    assert "displayOdds" in quote_function
    assert "providerName" in quote_function
    assert "aria-label" in quote_function
    assert "<small>" not in quote_function

    design_css = DESIGN_SYSTEM_PATH.read_text(encoding="utf-8")
    quote_rules = "\n".join(_rule_bodies(design_css, ".il-executable-quote"))
    assert "min-height: 48px" in quote_rules
    assert "border: 1px solid var(--il-positive)" in quote_rules
    assert "border-radius: var(--il-radius-control)" in quote_rules
    assert "background: var(--il-surface-positive-subtle)" in quote_rules

    provider_rules = _rule_bodies(design_css + css, ".il-provider-logo")
    assert provider_rules
    assert all(
        re.search(r"(?<!-)filter\s*:", body) is None for body in provider_rules
    )


def test_prediction_summary_and_filters_match_the_four_metric_contract():
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    template = TRADES_TEMPLATE_PATH.read_text(encoding="utf-8")

    summary_ids = (
        "trade-summary-qualified",
        "trade-summary-edge",
        "trade-summary-hit-rate",
        "trade-summary-exposure",
    )
    for summary_id in summary_ids:
        assert template.count(f'id="{summary_id}"') == 1
        assert summary_id in script
    for superseded_id in (
        "trade-summary-scanned",
        "trade-summary-providers",
        "trade-summary-warnings",
    ):
        assert superseded_id not in template

    for filter_id in ("trade-sport", "trade-market", "trade-confidence", "trade-sort"):
        assert template.count(f'id="{filter_id}"') == 1


def test_prediction_evidence_and_signal_activity_use_progressive_disclosure():
    css = TRADES_STYLE_PATH.read_text(encoding="utf-8")
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    template = TRADES_TEMPLATE_PATH.read_text(encoding="utf-8")
    evidence_function = _function(script, "detailStripMetric")

    assert "TRADE_METRIC_TOOLTIPS" in script
    assert "bindIconLabsTooltipSystem" in script
    assert "chart-point-tooltip" in script
    assert "trade-confidence-meter" not in css + script
    assert "<strong>${escapeHtml(value)}</strong>" in evidence_function
    assert "<small>${escapeHtml(label)}</small>" in evidence_function

    assert '<details class="low-inventory-state"' in template
    signal_opening_tag = template.split('<details class="low-inventory-state"', 1)[1].split(">", 1)[0]
    assert " open" not in signal_opening_tag
    assert "signal-activity-preview" in template
    assert "signal-activity-expanded" in template
    assert "play-activity-chart" in template
    assert "min-height: 228px" not in css


def test_prediction_traders_responsive_rules_prevent_horizontal_overflow():
    css = TRADES_STYLE_PATH.read_text(encoding="utf-8")

    for breakpoint in (1920, 1480, 1320, 980, 640):
        assert f"@media (max-width: {breakpoint}px)" in css
    assert "overflow-x: hidden" in css
    assert re.search(r"overflow-x:\s*(?:auto|scroll)", css) is None
    assert re.search(r"min-width:\s*[1-9][0-9]{3,}px", css) is None
    assert "grid-template-columns: minmax(0, 1fr) clamp(450px, 24vw, 480px)" in css
    assert "grid-template-columns: minmax(0, 1fr) 420px" in css
    assert "grid-template-columns: minmax(0, 1fr);" in css
    assert "width: min(500px, 92vw)" in css
    assert '"score event event event"' in css
    assert '"execution execution execution stake"' in css
    assert '"selection selection selection"' in css
    assert '"execution execution stake"' in css
    assert "width: 100%" in css
    assert "transform: translateY(102%)" in css
    assert ".mobile-trade-detail-open .trade-detail { transform: translateY(0); }" in css


def test_prediction_price_chart_is_compact_data_aware_and_accessible():
    css = TRADES_STYLE_PATH.read_text(encoding="utf-8")
    script = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "const seriesMin = Math.min(...values)" in script
    assert "const seriesMax = Math.max(...values)" in script
    assert "const PREDICTION_TRADERS_PRICE_DOMAIN" in script
    assert "minimumPadding: 0.005" in script
    assert "minimumSpan: 0.01" in script
    assert "* 0.12, minimumPadding" in script
    assert "domain: PREDICTION_TRADERS_PRICE_DOMAIN" in script
    assert "domainValues" not in script
    assert 'chartTokenValue(container, "--il-brand-hover", "#8b5cf6")' in script
    assert 'chartTokenValue(container, "--il-warning", "#f5a524")' in script
    assert 'chartTokenValue(container, "--il-positive", "#39d66f")' in script
    assert '{ value: number(slippage?.whalePrice), tone: "trader", label: "Trader" }' in script
    assert '{ value: number(currentPrice), tone: "current", label: "Current" }' in script
    assert "reference.value) >= min && Number(reference.value) <= max" in script
    assert "color: tradePriceHistoryColor(container)" in script
    assert "Current executable" in script
    assert "priceDeltaLabel" in script
    assert 'canvas.setAttribute("role", "img")' in script
    assert 'canvas.addEventListener("pointermove"' in script
    assert 'canvas.addEventListener("focus"' in script
    assert 'canvas.addEventListener("keydown"' in script
    assert '"ArrowLeft", "ArrowRight"' in script
    design_css = DESIGN_SYSTEM_PATH.read_text(encoding="utf-8")
    chart_rule = re.search(r"\.il-chart-container\s*\{(?P<body>[^}]*)\}", design_css)
    assert chart_rule
    assert "min-height: 150px" in chart_rule.group("body")
    assert "min-height: 220px" not in chart_rule.group("body")


def test_prediction_traders_uses_shared_component_contracts_without_preview_artifacts():
    design_css = DESIGN_SYSTEM_PATH.read_text(encoding="utf-8")
    trades_css = TRADES_STYLE_PATH.read_text(encoding="utf-8")
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    template = TRADES_TEMPLATE_PATH.read_text(encoding="utf-8")

    for component in (
        ".il-page-header",
        ".il-kpi-strip",
        ".il-filter-bar",
        ".il-confidence-display",
        ".il-executable-quote",
        ".il-provider-row",
        ".il-metric-group",
        ".il-detail-section",
        ".il-chart-container",
        ".il-state",
    ):
        assert component in design_css

    for hook in (
        "il-page-header",
        "il-kpi-strip",
        "il-filter-bar",
        "il-confidence-display",
        "il-executable-quote",
        "il-provider-row",
        "il-metric-group",
        "il-detail-section",
        "il-chart-container",
    ):
        assert hook in template + script

    assert "--il-bg-app:" not in trades_css
    assert "visual-preview" not in script + trades_css
    assert "Design preview" not in script + template


def test_prediction_controls_expose_selected_and_focus_states():
    design_css = DESIGN_SYSTEM_PATH.read_text(encoding="utf-8")
    script = SCRIPT_PATH.read_text(encoding="utf-8")

    assert ":focus-visible" in design_css
    assert "outline: 2px solid var(--il-focus)" in design_css
    assert 'role="group" aria-label="Price history range"' in script
    assert 'item.setAttribute("aria-pressed", String(active))' in script


def test_existing_brand_fonts_and_wordmark_assets_remain_available():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    style = STYLE_PATH.read_text(encoding="utf-8")

    assert "family=DM+Sans" in template
    assert "family=Fraunces" in template
    assert "family=Roboto+Condensed" in template
    assert "iconlabs-wordmark-only-4k-transparent.webp" in template
    assert '--font-display: "Fraunces", Georgia, serif' in style
