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
    assert b"sharp-money-ledger-preview.css" in response.data
    assert b"sharp-preview-active" in response.data
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
    assert template.count("icon-button") >= 6
    assert "il-detail-panel" in template
    assert "sharp-list-status" in template
    assert "sharp-more-menu" in template
    assert "sharp-profile-button" in template
    assert '<span class="sharp-profile-initial" aria-hidden="true">R</span>' in template
    assert "sharp-finance-actions" in template
    assert 'id="sharp-filter-dialog"' in template
    assert "Refresh opportunities" in template
    assert "Automatic refresh" in template
    assert "Visible bets" in template
    assert "Hidden bets" in template
    assert 'id="sharp-sport-filter"' in template
    assert "data-sharp-sport" not in template
    assert '<option value="alternate">Alternate lines</option>' in template
    assert '<option value="player_prop">Player props</option>' in template


def test_sharp_money_profile_avatar_uses_the_signed_in_first_name():
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert "function accountProfileInitial(profile = {})" in script
    assert "profile.firstName || fallbackIdentity" in script
    assert 'document.querySelectorAll(".sharp-profile-initial")' in script
    assert "syncAccountProfileInitials(profile);" in script


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
    assert "state.previewExpandedId === card.dataset.sharpSignal" in script


def test_sharp_money_production_ledger_tracks_personal_bets(app_client):
    app_client.set_cookie("iconbets_user", "sharp-money-ledger-user")
    response = app_client.post(
        "/api/sharp-money/personal-bets",
        json={
            "source_id": "sharp-money-dodgers-under",
            "event_title": "Los Angeles Dodgers vs San Francisco Giants",
            "market_title": "Game Total",
            "selection": "Under 8.5 Runs",
            "event_start_time": "2026-09-28T02:20:00+00:00",
            "league": "MLB",
            "market_key": "game_total",
            "market_line": 8.5,
            "american_odds": 110,
            "stake": 105,
            "fees": 0,
            "sportsbook": "BetOnline",
            "tags": ["Sharp Money"],
        },
    )

    assert response.status_code == 201
    assert response.get_json()["source"] == "sharp_money"
    tracker = app_client.get("/api/personal-tracker").get_json()
    assert tracker["pagination"]["total"] == 1
    assert tracker["data"][0]["selection"] == "Under 8.5 Runs"


def test_sharp_money_ledger_uses_live_tracking_and_visibility_controls():
    script = (ROOT / "static" / "sharp-money.js").read_text(encoding="utf-8")

    assert 'fetch("/api/sharp-money/personal-bets"' in script
    assert 'document.body.classList.add("sharp-preview-active")' in script
    assert 'previewViewTabsHost.hidden = false' in script
    assert 'if (!listView) return;' in script
    assert 'payload.destinations?.betTracker || "/tracker?view=personal&section=bets"' in script


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
