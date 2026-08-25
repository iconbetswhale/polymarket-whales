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
    assert b'id="odds-preview-data"' in response.data


def test_odds_screen_live_page_does_not_embed_preview_data(app_client):
    response = app_client.get("/odds-screen")

    assert response.status_code == 200
    assert b'id="odds-preview-data"' not in response.data


def test_odds_screen_demo_page_embeds_thirty_game_preview(app_client):
    response = app_client.get("/odds-screen?demo=1")

    assert response.status_code == 200
    assert b'id="odds-preview-data"' in response.data
    assert b"30 temporary preview matchups" in response.data


def test_odds_screen_preview_is_read_only_and_populated(app_client):
    response = app_client.get("/api/odds-screen?preview=1")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    payload = response.get_json()
    assert payload["previewOnly"] is True
    assert payload["providerRequestsEnabled"] is False
    assert payload["trackerWritesEnabled"] is False
    assert len(payload["data"]) == 140
    assert len({row["event_id"] for row in payload["data"]}) == 30
    assert all(row["executionOptions"] for row in payload["data"])
    market_titles = {row["sports_market_type"] for row in payload["data"]}
    assert market_titles == {
        "Moneyline",
        "Run Line / Spread",
        "Alternate Spread",
        "Game Total",
        "Alternate Total",
        "Player Hits",
    }
    event_counts = {
        title: len(
            {
                row["event_id"]
                for row in payload["data"]
                if row["sports_market_type"] == title
            }
        )
        for title in market_titles
    }
    assert event_counts == {
        "Moneyline": 30,
        "Run Line / Spread": 8,
        "Alternate Spread": 8,
        "Game Total": 8,
        "Alternate Total": 8,
        "Player Hits": 8,
    }


def test_odds_screen_template_uses_approved_terminal_structure():
    template = (ROOT / "templates" / "odds_screen.html").read_text(
        encoding="utf-8"
    )

    for hook in (
        "odds-preview-banner",
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


def test_odds_screen_preview_client_does_not_start_polling():
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert 'preview: new URLSearchParams(window.location.search).get("preview") === "1"' in script
    assert 'document.querySelector(".odds-screen-page")?.dataset.oddsPreview === "true"' in script
    assert 'if (oddsState.preview) params.set("preview", "1")' in script
    assert "if (!oddsState.preview) oddsState.timer = window.setInterval(loadOddsScreen, 60000)" in script
    assert 'document.getElementById("odds-preview-data")' in script
    assert "previewPayload || await fetchJson" in script
    assert 'oddsState.providerOrder = [...previewKeys, "best"]' in script
    assert "if (!oddsState.preview) persistOddsProviderOrder()" in script
    assert "ODDS_LIQUIDITY_PROVIDER_KEYS" in script
    assert 'return `${formattedAmount} Limit`' in script
    assert "if (ODDS_LIQUIDITY_PROVIDER_KEYS.has(providerKey)) return formattedAmount" in script
    assert "primary.canonical_league_id || primary.league || primary.category" not in script
    assert "Liq $" not in script
    assert "odds-column-highlight" not in script
    assert "bindOddsColumnHighlight" not in script
    assert "oddsState.autoRefresh" not in script
    assert "setOddsFeedActive(oddsState.preview)" in script
    assert 'oddsState.sport = "Baseball"' in script
    assert 'oddsState.league = "MLB"' in script
    assert 'document.querySelectorAll("[data-odds-view]")' in script
    assert 'document.querySelectorAll("[data-odds-sport-filter]")' in script
    assert 'oddsPlayerPropMarkets()[0]?.kind || "player_hits"' in script

