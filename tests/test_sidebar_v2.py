from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "sidebar-v2.css").read_text(encoding="utf-8")
APP_JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

V2_PAGE_STYLES = (
    "stage2-trades.css",
    "positive-ev.css",
    "sharp-money-v2.css",
    "odds-screen-v2.css",
    "dfs-v2.css",
    "tracker-v2.css",
    "lab-tracker-v2.css",
    "shadow-lab-v2.css",
    "live-positions-v2.css",
    "sharp-wallets-v2.css",
    "wallet-lock-v2.css",
    "bet-history-v2.css",
    "edge-map-v2.css",
    "intelligence-v2.css",
)


def test_shared_sidebar_styles_load_after_every_v2_page_stylesheet():
    sidebar = BASE.index("filename='sidebar-v2.css'")

    assert "-canonical-v13-connected-neon-flow" in BASE[sidebar : sidebar + 200]
    for stylesheet in V2_PAGE_STYLES:
        assert BASE.index(f"filename='{stylesheet}'") < sidebar


def test_shared_sidebar_contract_is_route_agnostic_and_complete():
    assert "[data-page=" not in CSS
    assert '@media (min-width: 981px)' in CSS
    assert '.sidebar-expanded .desktop-nav-toggle' in CSS
    assert '.sidebar-expanded .brand' in CSS
    assert '.sidebar-expanded .nav-links > a' in CSS
    assert 'width: calc(100% - 24px)' in CSS
    assert '.sidebar-expanded .sidebar-account-button' in CSS
    assert 'grid-template-columns: 30px minmax(0, 1fr) 16px' in CSS
    assert 'background-color: #000' in CSS
    assert 'background-image: url("/static/assets/sidebar-neon-purple-flow-connected-v5.webp")' in CSS
    assert (ROOT / "static" / "assets" / "sidebar-neon-purple-flow-connected-v5.webp").is_file()
    assert "background-repeat: no-repeat" in CSS
    assert "background-size: 100% 100%" in CSS
    assert "var(--il-sidebar-texture-image)" not in CSS
    assert "mix-blend-mode: screen" not in CSS
    assert '.sidebar-expanded .app-nav > *' in CSS
    assert 'font: 750 15.5px/1.15 var(--il-font-ui)' in CSS
    assert '0 3px 0 #68189b' in CSS
    assert 'border-color: #b23cff' in CSS
    assert 'inset 0 0 0 1px rgba(228, 190, 255, 0.72)' in CSS
    assert "border-right: 2px solid #b23cff" in CSS
    assert "inset -1px 0 0 rgba(228, 190, 255, 0.72)" in CSS
    assert "1px 0 0 #dd9cff" in CSS
    assert "3px 0 0 #68189b" in CSS
    assert "5px 0 0 #2c063f" in CSS


def test_tactile_sidebar_uses_requested_phosphor_icon_mapping():
    for icon in (
        "ph-coins",
        "ph-grid-nine",
        "ph-sliders-horizontal",
        "ph-activity",
    ):
        assert f'class="ph {icon}"' in BASE

    assert "sharp-money-nav-icon" not in BASE
    assert "sportsbook-nav-icon" not in BASE
    assert "live-position-nav-icon" not in BASE


def test_every_v2_route_renders_the_shared_sidebar_stylesheet(app_client):
    routes = (
        "/trades",
        "/positive-ev",
        "/sharp-money",
        "/odds-screen",
        "/dfs",
        "/tracker",
        "/lab-tracker",
        "/shadow-test",
        "/live-positions",
        "/wallets",
        "/wallets/unlock",
        "/position-history",
        "/edge-map",
        "/intelligence",
    )

    for route in routes:
        response = app_client.get(route, follow_redirects=True)
        assert response.status_code == 200, route
        assert b"sidebar-v2.css" in response.data, route


def test_preview_navigation_keeps_every_sidebar_destination_in_preview_mode(app_client):
    response = app_client.get("/dfs?preview=1")

    assert response.status_code == 200
    for route in (
        "/trades",
        "/sharp-money",
        "/positive-ev",
        "/odds-screen",
        "/dfs",
        "/tracker",
        "/lab-tracker",
        "/shadow-test",
        "/live-positions",
        "/wallets",
        "/position-history",
        "/edge-map",
        "/intelligence",
    ):
        assert f'href="{route}?preview=1"'.encode() in response.data, route


def test_regular_navigation_does_not_force_preview_mode(app_client):
    response = app_client.get("/dfs")

    assert response.status_code == 200
    assert b'href="/positive-ev"' in response.data
    assert b'href="/positive-ev?preview=1"' not in response.data


def test_prediction_traders_url_updates_do_not_drop_preview_mode():
    assert 'const previewMode = new URLSearchParams(window.location.search).get("preview")' in APP_JS
    assert '["1", "true", "yes", "on", "trade"].includes(previewMode)' in APP_JS


def test_wallet_lock_redirect_keeps_preview_navigation_active(app_client):
    app_client.application.config["WALLET_PAGE_PASSCODE"] = "1357"
    app_client.application.config["WALLET_PAGE_LOCK_SECRET"] = "sidebar-preview-test"

    locked = app_client.get("/wallets?preview=1")
    assert locked.status_code == 302
    assert "preview=1" in locked.headers["Location"]

    unlock_page = app_client.get(locked.headers["Location"])
    assert unlock_page.status_code == 200
    assert b'href="/positive-ev?preview=1"' in unlock_page.data
