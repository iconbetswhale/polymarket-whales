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


def test_odds_screen_preview_is_read_only_and_populated(app_client):
    response = app_client.get("/api/odds-screen?preview=1")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    payload = response.get_json()
    assert payload["previewOnly"] is True
    assert payload["providerRequestsEnabled"] is False
    assert payload["trackerWritesEnabled"] is False
    assert len(payload["data"]) == 18
    assert len({row["event_id"] for row in payload["data"]}) == 3
    assert all(row["executionOptions"] for row in payload["data"])


def test_odds_screen_template_uses_approved_terminal_structure():
    template = (ROOT / "templates" / "odds_screen.html").read_text(
        encoding="utf-8"
    )

    for hook in (
        "odds-preview-banner",
        "odds-screen-header",
        "odds-toolbar",
        "odds-market-tabs",
        "odds-matrix",
        "odds-grid-head",
        "mobile-odds-board",
    ):
        assert hook in template
    assert 'id="odds-market-trigger"' not in template
    assert "Main Markets" not in template
    for label in (
        "Moneyline",
        "Run Line / Spread",
        "Alt Spreads",
        "Game Totals",
        "Alt Totals",
        "Player Props",
    ):
        assert label in template


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


def test_odds_screen_preview_client_does_not_start_polling():
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert 'preview: new URLSearchParams(window.location.search).get("preview") === "1"' in script
    assert 'if (oddsState.preview) params.set("preview", "1")' in script
    assert "if (!oddsState.preview && oddsState.autoRefresh) oddsState.timer = window.setInterval" in script
    assert "setOddsFeedActive(oddsState.preview)" in script
