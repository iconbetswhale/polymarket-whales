from __future__ import annotations

import re
from pathlib import Path


STYLE_PATH = Path(__file__).resolve().parents[1] / "static" / "style.css"
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "static" / "app.js"
TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "base.html"


def _rule(css: str, selector: str) -> str:
    matches = re.findall(
        rf"(?ms)^{re.escape(selector)}\s*\{{(.*?)^\}}",
        css,
    )
    assert matches, f"Missing CSS rule for {selector}"
    return matches[-1]


def test_display_headings_use_loaded_font_weights_and_safe_line_height():
    css = STYLE_PATH.read_text(encoding="utf-8")

    assert "font-weight: 750" not in css
    assert "line-height: 0.98" not in css
    assert "line-height: 1.05" not in css
    assert "text-rendering: optimizeLegibility" not in css
    assert "font-weight: 800" in _rule(css, "h2")
    assert "line-height: 1.12" in _rule(css, "h2")


def test_typography_uses_warm_display_and_readable_tabular_data_fonts():
    css = STYLE_PATH.read_text(encoding="utf-8")
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert '--font-display: "Fraunces", Georgia, serif' in css
    assert '--font-body: "DM Sans", sans-serif' in css
    assert '--font-data: "Roboto Condensed", sans-serif' in css
    assert "font-variant-numeric: tabular-nums lining-nums" in css
    assert "family=DM+Sans" in template
    assert "family=Fraunces" in template
    assert "family=Roboto+Condensed" in template
    assert '"Roboto Condensed"' in script
    assert "Chivo Mono" not in template + css + script
    assert "Sometype Mono" not in template + css + script
    assert "IBM Plex Sans" not in template + css + script
    assert "JetBrains Mono" not in template + css + script
    assert "League Spartan" not in template + css + script


def test_empty_state_heading_keeps_full_glyph_box_visible():
    css = STYLE_PATH.read_text(encoding="utf-8")
    empty_heading_rule = _rule(css, ".empty-state h2,\n.empty-detail h2")

    assert "max-width: 100%" in empty_heading_rule
    assert "overflow: visible" in empty_heading_rule
    assert "font-weight: 700" in empty_heading_rule
    assert "line-height: 1.2" in empty_heading_rule
    assert "text-rendering: geometricPrecision" in empty_heading_rule


def test_trades_workspace_is_centered_and_capped_on_ultrawide_screens():
    css = STYLE_PATH.read_text(encoding="utf-8")
    trades_page_rule = _rule(css, ".trades-page")

    assert "width: min(100%, 1520px)" in trades_page_rule
    assert "margin-inline: auto" in trades_page_rule


def test_readability_refinement_enlarges_dense_trade_microcopy():
    css = STYLE_PATH.read_text(encoding="utf-8")

    trade_context_rule = _rule(css, ".trade-kicker,\n.trade-market")
    provider_label_rule = _rule(css, ".trade-selection small,\n.execution-option > span small")
    orderbook_rule = _rule(
        css,
        ".live-price small,\n.live-price em,\n.detail-selection-size small,\n.detail-strip-metric small,\n.price-range-controls button,\n.price-legend,\n.orderbook-side > small,\n.orderbook-row,\n.orderbook-row > strong,\n.orderbook-summary,\n.orderbook-empty small,\n.detail-accordion > summary > small,\n.calculation-grid strong,\n.calculation-note,\n.supporter-row small",
    )

    assert "/* Readability and depth refinements */" in css
    assert "font-size: 11px" in trade_context_rule
    assert "font-size: 9.5px" in provider_label_rule
    assert "font-size: 10px" in orderbook_rule


def test_depth_refinement_uses_neutral_dimension_and_restrained_green():
    css = STYLE_PATH.read_text(encoding="utf-8")
    root_rule = _rule(css, ":root")
    trades_rule = _rule(css, 'body[data-page="trades"]')

    assert "--muted: #96a8b0" in root_rule
    assert "rgba(215, 174, 102, 0.16)" in root_rule
    assert "--trade-score: #ddb86e" in trades_rule
    assert "repeating-linear-gradient" in trades_rule
    assert "background-attachment: fixed" in trades_rule
