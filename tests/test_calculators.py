from pathlib import Path


TEMPLATE = Path("templates/calculators.html").read_text(encoding="utf-8")
BASE = Path("templates/base.html").read_text(encoding="utf-8")
CSS = Path("static/calculators.css").read_text(encoding="utf-8")
SCRIPT = Path("static/calculators.js").read_text(encoding="utf-8")
MATH = Path("static/calculator-math.js").read_text(encoding="utf-8")


CALCULATOR_IDS = (
    "arbitrage",
    "expected-value",
    "bonus-bet",
    "half-point",
    "hold",
    "implied-probability",
    "kelly",
    "no-vig",
    "odds-converter",
    "parlay",
    "prediction-market",
    "point-spread",
    "poisson",
    "round-robin",
    "vig",
)


def test_calculators_are_a_canonical_v2_page_in_the_shared_shell() -> None:
    assert "url_for('calculators_page')" in BASE
    assert "page == 'calculators'" in BASE
    assert "calculators.css" in BASE
    assert "calculator-math.js" in BASE
    assert "calculators.js" in BASE
    assert "'calculators'" in BASE
    calculators_link = BASE.index("url_for('calculators_page')")
    fantasy_link = BASE.index("url_for('dfs_page'")
    labs_label = BASE.index(">Labs</span>")
    assert fantasy_link < calculators_link < labs_label


def test_all_fifteen_calculator_tabs_are_present() -> None:
    assert TEMPLATE.count("data-calculator=") == 15
    for calculator_id in CALCULATOR_IDS:
        assert f'data-calculator="{calculator_id}"' in TEMPLATE


def test_calculators_use_iconlabs_tokens_and_phosphor_icons() -> None:
    assert "var(--il-bg-app" in CSS
    assert "var(--il-brand" in CSS
    assert "var(--il-positive" in CSS
    assert "ph ph-" in TEMPLATE
    assert "<svg" not in TEMPLATE
    assert "linear-gradient" not in CSS
    assert "radial-gradient" not in CSS


def test_primary_interactions_and_math_engines_are_implemented() -> None:
    for required in (
        "function renderActive",
        "function calculateActive",
        "function filterTabs",
        "function selectCalculator",
        "data-add-leg",
        "data-remove-leg",
        "navigator.clipboard",
    ):
        assert required in SCRIPT

    for required in (
        "function arbitrage",
        "function expectedValue",
        "function bonusBet",
        "function halfPoint",
        "function hold",
        "function kelly",
        "function noVig",
        "function parlay",
        "function predictionMarket",
        "function pointSpread",
        "function poisson",
        "function roundRobin",
        "function vig",
    ):
        assert required in MATH
