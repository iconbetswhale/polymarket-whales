from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_odds_screen_opts_into_v2_without_legacy_layers(app_client):
    response = app_client.get("/odds-screen?preview=1")

    assert response.status_code == 200
    assert b'data-page="odds-screen" data-design-system="v2"' in response.data
    assert b"design-system.css" in response.data
    assert b"odds-screen-v2.css" in response.data
    assert b"stage2-odds.css" not in response.data
    assert b"legacy-design-system.css" not in response.data
    assert b"stage2-art-direction.css" not in response.data
    assert b"shared-shell.css" not in response.data
    assert b"mobile-product.css" not in response.data
    assert b"app-premium.css" not in response.data
    assert b"sidebar-shell.css" not in response.data
    assert b'id="odds-preview-data"' not in response.data


def test_odds_screen_live_page_does_not_embed_preview_data(app_client):
    response = app_client.get("/odds-screen")

    assert response.status_code == 200
    assert b'id="odds-preview-data"' not in response.data


def test_odds_screen_demo_parameter_cannot_embed_fixture_rows(app_client):
    response = app_client.get("/odds-screen?demo=1")
    live = app_client.get("/odds-screen")

    assert response.status_code == 200
    assert response.data == live.data
    assert b'id="odds-preview-data"' not in response.data
    assert b"temporary preview matchups" not in response.data


def test_odds_screen_preview_parameter_cannot_enable_fixture_rows(app_client):
    response = app_client.get("/api/odds-screen?preview=1")
    live = app_client.get("/api/odds-screen")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload == live.get_json()
    assert payload["paused"] is True
    assert payload["data"] == []
    assert "previewOnly" not in payload


def test_odds_screen_template_uses_approved_terminal_structure():
    template = (ROOT / "templates" / "odds_screen.html").read_text(
        encoding="utf-8"
    )

    for hook in (
        "odds-screen-header",
        "odds-navigation-shell",
        "odds-navigation-top",
        "odds-view-tabs",
        "odds-sport-tabs",
        "odds-compact-market-tabs",
        "odds-matrix",
        "odds-grid-head",
        "mobile-odds-board",
    ):
        assert hook in template
    assert 'id="odds-market-trigger"' not in template
    assert 'id="odds-auto-refresh"' not in template
    assert "Auto-refresh</span>" not in template
    assert "odds-history-head" not in template
    assert "odds-history-cell" not in template
    assert "Main Markets" not in template
    assert "odds-footer" not in template
    assert "All times shown in ET" not in template
    for label in (
        "Games",
        "Props",
        "PRO",
        "NFL PRE",
        "WNBA",
        "MLB",
        "NCAAF",
        "NFL",
        "NBA",
        "NHL",
        "NCAAB",
        "Moneyline",
        "Spread",
        "Total",
    ):
        assert label in template
    for league_asset in ("nfl.png", "wnba.png", "mlb.png", "ncaa.png", "nba.png", "nhl.png"):
        assert league_asset in template
    assert 'id="odds-league-trigger"' not in template
    assert 'id="odds-feed-toggle"' not in template
    assert 'id="odds-props-trigger"' not in template
    assert "data-odds-favorite" not in template
    assert "Alt Spreads" not in template
    assert "Alt Totals" not in template


def test_odds_screen_canonical_layer_uses_v2_tokens_and_mobile_board():
    stylesheet = (ROOT / "static" / "odds-screen-v2.css").read_text(
        encoding="utf-8"
    )

    assert 'body[data-design-system="v2"][data-page="odds-screen"]' in stylesheet
    for token in (
        "var(--il-bg-app)",
        "var(--il-surface-1)",
        "var(--il-border-subtle)",
        "var(--il-brand)",
        "var(--il-positive)",
        "var(--il-focus)",
    ):
        assert token in stylesheet
    assert "@media (max-width: 700px)" in stylesheet
    assert ".mobile-odds-board" in stylesheet
    assert ".mobile-odds-sheet" in stylesheet
    assert "overflow-x: hidden" in stylesheet
    assert "border-collapse: collapse" in stylesheet
    assert ".odds-price-stack .odds-price + .odds-price" in stylesheet
    assert ".odds-best-stack .provider-logo-mark" in stylesheet
    assert ".odds-best-stack strong" in stylesheet
    assert "grid-template-columns: 20px 38px" in stylesheet
    assert "min-width: 20px" in stylesheet
    assert "max-width: 20px" in stylesheet
    assert "font-variant-numeric: tabular-nums" in stylesheet
    assert ".odds-market-row:nth-child(even) { background: rgba(141, 68, 246, .08); }" in stylesheet
    assert ".odds-market-row:hover { background: rgba(139, 92, 246, .32); }" in stylesheet
    assert "zoom: 1.25" in stylesheet
    assert "height: 80vh" in stylesheet
    assert ".mobile-odds-game:nth-child(even) { background: rgba(141, 68, 246, .08); }" in stylesheet
    assert "font-size: 13px" in stylesheet
    assert ".odds-time-cell strong" in stylesheet
    assert "font-size: 12px" in stylesheet
    assert ".odds-price small" in stylesheet
    assert "font-size: 9px" in stylesheet
    assert "text-align: center" in stylesheet
    assert ".odds-navigation-shell" in stylesheet
    assert ".odds-view-tabs" in stylesheet
    assert ".odds-sport-tabs" in stylesheet
    assert ".odds-pro-badge" in stylesheet
    assert ".odds-compact-market-tabs" in stylesheet


def test_odds_screen_client_starts_only_the_live_feed():
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert "iconbets_odds_favorites" not in script
    assert "favoritesOnly" not in script

    assert "oddsState.preview" not in script
    assert 'params.set("preview", "1")' not in script
    assert 'document.getElementById("odds-preview-data")' not in script
    assert "previewPayload" not in script
    assert "oddsState.timer = window.setInterval(loadOddsScreen, 15000)" in script
    assert 'params.set("active", "1")' in script
    assert 'params.set("sport", oddsState.sport)' not in script
    assert 'params.set("league", oddsState.league)' not in script
    assert 'params.set("market", oddsState.kind)' not in script
    assert "persistOddsProviderOrder()" in script
    assert 'oddsState.providerOrder = [...previewKeys, "best"]' not in script
    assert "ODDS_DEFAULT_PROVIDER_KEYS" in script
    assert "ODDS_LIQUIDITY_PROVIDER_KEYS" in script
    assert 'return `${formattedAmount} Limit`' in script
    assert "if (ODDS_LIQUIDITY_PROVIDER_KEYS.has(providerKey)) return formattedAmount" in script
    assert "primary.canonical_league_id || primary.league || primary.category" not in script
    assert "Liq $" not in script
    assert "odds-column-highlight" not in script
    assert "bindOddsColumnHighlight" not in script
    assert "oddsState.autoRefresh" not in script
    assert "setOddsFeedActive(true)" in script
    assert 'oddsState.sport = ""' in script
    assert 'oddsState.league = ""' in script
    assert 'document.querySelectorAll("[data-odds-view]")' in script
    assert 'document.querySelectorAll("[data-odds-sport-filter]")' in script
    assert 'oddsPlayerPropMarkets()[0]?.kind || "player_hits"' in script
    assert "iconbets_odds_provider_selection_v2" in script
    assert "availableProviderKeys.has(key)" in script
    assert "isNew && savedOddsProviderSelection" not in script
    assert "oddsState.providers.filter(key => availableProviderKeys.has(key))" in script
    assert "input.checked = oddsState.providers.includes(input.value)" in script
    assert 'pagePayloadCacheKey("odds-screen", params.toString())' in script
    assert "oddsTeamLogoUrl(label)" in script
    assert "/static/assets/teams/mlb/nyy.png" in script
    assert "/static/assets/teams/wnba/ny.png" in script

