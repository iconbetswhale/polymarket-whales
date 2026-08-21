from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "sidebar-v2.css").read_text(encoding="utf-8")

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

    assert "-canonical-v3" in BASE[sidebar : sidebar + 180]
    for stylesheet in V2_PAGE_STYLES:
        assert BASE.index(f"filename='{stylesheet}'") < sidebar


def test_shared_sidebar_contract_is_route_agnostic_and_complete():
    assert "[data-page=" not in CSS
    assert '@media (min-width: 981px)' in CSS
    assert '.sidebar-expanded .desktop-nav-toggle' in CSS
    assert '.sidebar-expanded .brand' in CSS
    assert '.sidebar-expanded .nav-links > a' in CSS
    assert '.sidebar-expanded .sidebar-account-button' in CSS
    assert 'grid-template-columns: 30px minmax(0, 1fr) 16px' in CSS
    assert 'background: var(--il-surface-selected-quiet)' in CSS
    assert 'box-shadow: inset 2px 0 0 var(--il-brand)' in CSS


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
