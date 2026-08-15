from pathlib import Path
import struct

from ev_preview import temporary_ev_preview_rows
from sharp_money_preview import temporary_sharp_money_preview_payload


ROOT = Path(__file__).resolve().parents[1]
BETONLINE_LOGO = "/static/assets/sportsbooks/betonline.png"
BETONLINE_LOGO_PATH = ROOT / "static" / "assets" / "sportsbooks" / "betonline.png"
DFS_BETONLINE_LOGO_PATH = ROOT / "static" / "assets" / "dfs-books" / "betonline.png"


def test_betonline_uses_the_canonical_local_logo_across_product_surfaces() -> None:
    ev_quotes = temporary_ev_preview_rows()[0]["quotes"]
    ev_betonline = next(quote for quote in ev_quotes if quote["bookKey"] == "betonlineag")
    assert ev_betonline["logoUrl"] == BETONLINE_LOGO

    sharp_comparisons = temporary_sharp_money_preview_payload()["signals"][0][
        "comparisonLines"
    ]
    sharp_betonline = next(
        quote for quote in sharp_comparisons if quote["providerKey"] == "betonlineag"
    )
    assert sharp_betonline["logoUrl"] == BETONLINE_LOGO


def test_shared_frontend_overrides_legacy_betonline_urls() -> None:
    app_script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    home_template = (ROOT / "templates" / "home.html").read_text(encoding="utf-8")

    assert 'providerKey === "betonline"' in app_script
    assert app_script.count(BETONLINE_LOGO) >= 3
    assert "assets/sportsbooks/betonline.png" in home_template
    assert "domain=betonline.ag" not in home_template


def test_betonline_assets_use_the_supplied_square_b_mark() -> None:
    canonical_logo = BETONLINE_LOGO_PATH.read_bytes()
    dfs_logo = DFS_BETONLINE_LOGO_PATH.read_bytes()

    assert canonical_logo.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", canonical_logo[16:24]) == (447, 447)
    assert dfs_logo == canonical_logo


def test_sharp_money_does_not_stretch_betonline_into_a_wordmark() -> None:
    stylesheet = (ROOT / "static" / "sharp-money-v2.css").read_text(encoding="utf-8")

    assert ".sharp-market-book--betonline img" not in stylesheet
    assert ".sharp-market-book--betonlineag img" not in stylesheet
