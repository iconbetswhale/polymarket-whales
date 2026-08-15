from io import BytesIO

from PIL import Image


def test_new_brand_assets_are_transparent_and_served(app_client):
    for path in (
        "/static/iconlabs-mark-v2.png",
        "/static/iconlabs-horizontal-v2.webp",
        "/static/assets/iconlabs-wordmark-only-4k-transparent.webp",
    ):
        response = app_client.get(path)
        assert response.status_code == 200, path
        image = Image.open(BytesIO(response.data)).convert("RGBA")
        assert image.getchannel("A").getextrema() == (0, 255), path
        assert image.getpixel((0, 0))[3] == 0, path


def test_shared_shell_uses_expanded_wordmark_and_collapsed_mark(app_client):
    page = app_client.get("/lab-tracker").get_data(as_text=True)
    assert "assets/iconlabs-wordmark-only-4k-transparent.webp" in page
    assert "iconlabs-mark-v2.png" in page
    assert "brand-lockup" in page
    assert "brand-icon" in page


def test_home_uses_new_logo_mark(app_client):
    page = app_client.get("/").get_data(as_text=True)
    assert "iconlabs-mark-v2.png" in page
