from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sharp_money_opts_into_v2_without_legacy_layers(app_client):
    response = app_client.get("/sharp-money?preview=1")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert b'data-page="sharp-money" data-design-system="v2"' in response.data
    assert b"design-system.css" in response.data
    assert b"sharp-money-v2.css" in response.data
    assert b"legacy-design-system.css" not in response.data
    assert b"stage2-art-direction.css" not in response.data
    assert b"shared-shell.css" not in response.data
    assert b"mobile-product.css" not in response.data
    assert b"app-premium.css" not in response.data
    assert b"sidebar-shell.css" not in response.data
    assert html.index("sharp-money.js") < html.index("app.js")


def test_sharp_money_template_uses_canonical_v2_primitives():
    template = (ROOT / "templates" / "sharp_money.html").read_text(encoding="utf-8")

    assert "sharp-preview-banner" in template
    assert "il-page-header" in template
    assert "il-page-title" in template
    assert "search-control" in template
    assert template.count("icon-button") >= 7
    assert "il-detail-panel" in template


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
