from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sharp_money_opts_into_v2_without_legacy_layers(app_client):
    response = app_client.get("/sharp-money?preview=1")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert b'data-page="sharp-money" data-design-system="v2"' in response.data
    assert b"design-system.css" in response.data
    assert b"sharp-money-v2.css" in response.data
    assert b"sharp-money-redesign.css" in response.data
    assert b"legacy-design-system.css" not in response.data
    assert b"stage2-art-direction.css" not in response.data
    assert b"shared-shell.css" not in response.data
    assert b"mobile-product.css" not in response.data
    assert b"app-premium.css" not in response.data
    assert b"sidebar-shell.css" not in response.data
    assert html.index("app.js") < html.index("sharp-money.js")


def test_sharp_money_template_uses_canonical_v2_primitives():
    template = (ROOT / "templates" / "sharp_money.html").read_text(encoding="utf-8")

    assert "sharp-preview-banner" in template
    assert "il-page-header" in template
    assert "il-page-title" in template
    assert "search-control" in template
    assert template.count("icon-button") >= 7
    assert "il-detail-panel" in template
    assert "sharp-list-status" in template
    assert "sharp-more-menu" in template
    assert 'id="sharp-sport-filter"' in template
    assert "data-sharp-sport" not in template
    assert '<option value="alternate">Alternate lines</option>' in template
    assert '<option value="player_prop">Player props</option>' in template


def test_sharp_money_canonical_layer_unifies_cards_and_centers_bet_size():
    stylesheet = (ROOT / "static" / "sharp-money-v2.css").read_text(
        encoding="utf-8"
    )

    marker = "Canonical IconLabs v2 contract"
    canonical = stylesheet[stylesheet.index(marker) :]
    assert 'body[data-design-system="v2"][data-page="sharp-money"]' in canonical
    assert "background: var(--il-surface-1) !important;" in canonical
    assert "background: transparent !important;" in canonical
    assert ".sharp-card-market-row.primary > span:not(.sharp-sportsbook-action)" in canonical
    assert "align-items: center;" in canonical
    assert "justify-content: center;" in canonical
    assert "font: 700 24px/1 var(--il-font-data)" in canonical


def test_sharp_money_cards_support_keyboard_selection():
    script = (ROOT / "static" / "sharp-money.js").read_text(encoding="utf-8")

    assert 'addEventListener("keydown"' in script
    assert 'event.key !== "Enter" && event.key !== " "' in script
    assert "card.click();" in script


def test_sharp_money_surfaces_provider_entitlement_errors_instead_of_waiting():
    script = (ROOT / "static" / "sharp-money.js").read_text(encoding="utf-8")

    assert 'payload.signalMode === "quote_consensus"' in script
    assert "Live price movement" in script
    assert "exact two-sided REST prices and sharp-consensus movement" in script
    assert "Live price-consensus mode" in script
    assert 'return "Net Sharp Liquidity"' in script
    assert "Selected-side liquidity minus opposing-side liquidity" in script
    assert "Price Pressure" not in script
    assert "advancedPlanRequired" in script
    assert "OddsEngine Advanced access required" in script
    assert "Upgrade OddsEngine to Advanced" in script
    assert "Order-book access blocked" in script
    assert "Price feed temporarily unavailable" in script


def test_sharp_money_reference_redesign_has_list_detail_contract():
    stylesheet = (ROOT / "static" / "sharp-money-redesign.css").read_text(
        encoding="utf-8"
    )
    script = (ROOT / "static" / "sharp-money.js").read_text(encoding="utf-8")

    assert ".sharp-signal-card.selected" in stylesheet
    assert ".sharp-detail-overview" in stylesheet
    assert ".sharp-liquidity-panel" in stylesheet
    assert ".sharp-market-comparison" in stylesheet
    assert 'class="sharp-card-bet"' in script
    assert 'class="sharp-flow-book"' in script
    assert 'class="sharp-card-teams"' in script
    assert 'class="sharp-card-rec-selection"' in script
    assert "function displaySelection(signal)" in script
    assert 'unit = "Runs"' in script
    assert "desktop-overlay-open" in script
    assert 'class="sharp-card-best-price"' not in script
    assert "Best sharp price" not in script
    assert "depthSummary(signal)" in script
    assert "Sharp Money" in script
    assert "exchangeAction(key, row)" in script
    assert 'class="sharp-depth-bet' in script
    assert "https://www.prophetx.co/lobby/" in script
    assert "oppositeDeepLink || row.deepLink" in script
    assert ".sharp-depth-bet" in stylesheet


def test_sharp_money_reference_redesign_keeps_card_hover_state_inside_the_feed():
    stylesheet = (ROOT / "static" / "sharp-money-redesign.css").read_text(
        encoding="utf-8"
    )

    assert ".sharp-signal-list .sharp-signal-card:hover" in stylesheet
    assert "transform: none !important;" in stylesheet


def test_sharp_money_accepts_verified_direct_depth_and_filters_crossed_price_edge():
    template = (ROOT / "templates" / "sharp_money.html").read_text(encoding="utf-8")
    script = (ROOT / "static" / "sharp-money.js").read_text(encoding="utf-8")

    assert 'if (!quote) return "";' in script
    assert "const hasDirectDepth = signal.depthAvailable === true" in script
    assert "&& Boolean(retailQuote || hasDirectDepth)" in script
    assert "function crossedPriceGapPercent(signal)" in script
    assert 'minimumCrossedEdgePercent: 0' in script
    assert 'max="3" step="0.5"' in template
    assert "Awaiting line" not in script
    assert "row || {providerKey:key}" in script
    assert "Live source active · ${payload.lastError}" in script
    assert "Live cards retained · refresh temporarily unavailable" in script
    assert '"Live feed unavailable"' in script
    assert "MAX_ACTIONABLE_ABS_AMERICAN_ODDS = 10000" in script
    assert "rows.filter(isUsableQuote)" in script
    assert "(!rawDirectDepth || hasDirectDepth)" in script
    assert "signal.history || []).filter(row => isUsableAmericanOdds" in script


def test_sharp_money_line_shop_uses_shared_draggable_account_order():
    script = (ROOT / "static" / "sharp-money.js").read_text(encoding="utf-8")

    assert "data-line-shop-book" in script
    assert 'draggable="true"' in script
    assert "window.IconLabsLineShopOrder?.save(order)" in script
