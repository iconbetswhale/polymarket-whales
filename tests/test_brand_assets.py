from io import BytesIO
from pathlib import Path

from PIL import Image


def test_new_brand_assets_are_transparent_and_served(app_client):
    for path in (
        "/static/iconlabs-mark-v2.png",
        "/static/iconlabs-horizontal-v2.webp",
        "/static/assets/iconlabs-horizontal-logo-white.webp",
        "/static/assets/iconlabs-mark-white.webp",
    ):
        response = app_client.get(path)
        assert response.status_code == 200, path
        image = Image.open(BytesIO(response.data)).convert("RGBA")
        assert image.getchannel("A").getextrema() == (0, 255), path
        assert image.getpixel((0, 0))[3] == 0, path


def test_shared_shell_uses_the_reference_iconlabs_lockup(app_client):
    page = app_client.get("/lab-tracker").get_data(as_text=True)
    assert "assets/iconlabs-horizontal-logo-white.webp" in page
    assert "assets/iconlabs-mark-white.webp" in page
    assert "brand-lockup" in page
    assert "brand-icon" in page


def test_home_uses_reference_logo_lockup(app_client):
    page = app_client.get("/").get_data(as_text=True)
    assert "assets/iconlabs-horizontal-logo-white.webp" in page


def test_home_hero_v3_uses_mockup_assets_and_preserves_following_sections(app_client):
    response = app_client.get("/")
    assert response.status_code == 200
    page = response.get_data(as_text=True)

    assert "hero-v3-grid-background.png" in page
    assert "hero-v3-odds-board.png" in page
    assert "1000+ Verified Winners" in page
    assert "100+" in page
    assert "50+" in page
    assert "Real-Time" in page
    assert page.index('class="marketing-hero hero-v3"') < page.index('class="home-testimonials"')


def test_shared_shell_keeps_brand_and_navigation_responsive():
    root = Path(__file__).parents[1]
    css = (root / "static" / "sidebar-v2.css").read_text(encoding="utf-8")
    legacy = (root / "static" / "sidebar-shell.css").read_text(encoding="utf-8")
    assert "--il-sidebar-width:256px" in css
    assert "--il-sidebar-collapsed-width:72px" in css
    assert "width:min(256px,88vw)" in css
    assert "overflow-x: clip !important" in legacy
