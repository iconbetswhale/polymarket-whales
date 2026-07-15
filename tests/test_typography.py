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
    assert '--font-data: "DM Sans", sans-serif' in css
    assert "font-variant-numeric: tabular-nums lining-nums" in css
    assert "family=DM+Sans" in template
    assert "family=Fraunces" in template
    assert '"DM Sans"' in script
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
