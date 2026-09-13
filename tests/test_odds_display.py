from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("route", [
    "/trades", "/sharp-money", "/positive-ev", "/odds-screen", "/dfs",
    "/arbitrage", "/middles", "/low-hold", "/futures", "/tracker",
    "/lab-tracker", "/shadow-test", "/live-positions", "/calculators",
    "/wallets", "/position-history", "/edge-map", "/intelligence",
])
def test_every_tool_and_tracker_loads_shared_odds_before_its_renderer(app_client, route):
    response = app_client.get(route)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert html.index("/static/odds-format.js?") < html.index("/static/app.js?")


def test_renderer_has_no_direct_native_odds_fallbacks_or_dual_price_headline():
    script = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert "const headline = window.IconLabsOdds.quote(option);" in script
    assert "const contractAndAmerican =" not in script
    assert "snapshot.provider_display_odds ||" not in script
    assert "return String(option?.displayOdds" not in script
    assert "return option.displayOdds ||" not in script
    assert "window.IconLabsOdds.setFormat(profile.oddsFormat)" in script


def test_quote_preferences_never_rewrite_native_stored_prices_or_math():
    script = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert 'entry_price: Number(document.getElementById("personal-entry-price").value) / 100' in script
    assert 'sell_price: Number(document.getElementById("personal-sell-price").value) / 100' in script
    assert 'entry_price: Number(document.getElementById("personal-manual-entry").value) / 100' in script
    for filename in ("arbitrage.js", "middles.js", "low-hold.js"):
        tool = (ROOT / "static" / filename).read_text(encoding="utf-8")
        assert "function decimalOdds(value)" in tool
        assert "return window.IconLabsOdds.fromAmerican(value);" in tool


def test_account_choices_and_default_are_supported_without_building_a_new_account_page():
    base = (ROOT / "templates/base.html").read_text(encoding="utf-8")
    assert 'id="profile-odds-format"><option>American</option><option>Cents</option><option>Decimal</option>' in base
    module = (ROOT / "static/odds-format.js").read_text(encoding="utf-8")
    assert 'let preference = "american"' in module
    assert 'const STORAGE_KEY = "iconlabs-odds-format"' in module
