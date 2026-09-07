from pathlib import Path


BASE = Path("templates/base.html").read_text(encoding="utf-8")
PARTIAL = Path("templates/_value_lab_empty.html").read_text(encoding="utf-8")
CSS = Path("static/value-lab-empty.css").read_text(encoding="utf-8")
ASSET = Path("static/assets/value-lab-empty-state.png")

TOOLS = {
    "arbitrage": (
        Path("templates/arbitrage.html").read_text(encoding="utf-8"),
        Path("static/arbitrage.js").read_text(encoding="utf-8"),
    ),
    "middles": (
        Path("templates/middles.html").read_text(encoding="utf-8"),
        Path("static/middles.js").read_text(encoding="utf-8"),
    ),
    "low-hold": (
        Path("templates/low_hold.html").read_text(encoding="utf-8"),
        Path("static/low-hold.js").read_text(encoding="utf-8"),
    ),
}


def test_value_lab_is_shared_by_all_three_live_scanners() -> None:
    assert "page in ['arbitrage', 'middles', 'low-hold']" in BASE
    assert "value-lab-empty.css" in BASE
    for template, _script in TOOLS.values():
        assert "{% include '_value_lab_empty.html' %}" in template
        assert template.index("{% include '_value_lab_empty.html' %}") < template.index("-detail\"")


def test_value_lab_copy_and_generated_art_are_production_ready() -> None:
    for copy in (
        "Model live",
        "Value is still cooking",
        "We’re testing every line against your settings.",
        "Nothing has qualified yet—but the scan never stops.",
        "Odds synced",
        "Markets compared",
        "Waiting for an edge",
        "Scanning continuously",
    ):
        assert copy in PARTIAL
    assert "value-lab-empty-state.png" in PARTIAL
    assert ASSET.exists()
    assert ASSET.stat().st_size > 100_000
    assert "<svg" not in PARTIAL


def test_value_lab_only_replaces_the_workspace_after_a_successful_empty_live_scan() -> None:
    for _template, script in TOOLS.values():
        assert "hasCompletedScan: false" in script
        assert 'state.view === "live"' in script
        assert "&& state.hasCompletedScan" in script
        assert "&& !state.loading" in script
        assert "&& !state.error" in script
        assert "&& !state.paused" in script
        assert "&& state.rows.length === 0" in script
        assert 'classList.toggle("value-lab-empty-active", showValueLab)' in script
        assert "valueLabEmpty.hidden = !showValueLab" in script
        assert "state.hasCompletedScan = true" in script
        assert "Live scan active · waiting for a qualified play" in script
        assert "scanner is paused" in script


def test_value_lab_has_responsive_and_reduced_motion_treatments() -> None:
    assert ".value-lab-empty[hidden]" in CSS
    assert "grid-column: 1 / -1" in CSS
    assert "object-fit: contain" in CSS
    assert "@media (max-width: 1080px)" in CSS
    assert "@media (max-width: 760px)" in CSS
    assert "@media (prefers-reduced-motion: reduce)" in CSS
    assert ".arb-workspace.value-lab-empty-active > .arb-detail" in CSS
    assert ".mid-workspace.value-lab-empty-active > .mid-feed-panel" in CSS
