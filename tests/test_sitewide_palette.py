from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_reference_slate_palette_is_defined_in_the_shared_foundation():
    css = read("static/style.css")

    assert "--site-bg-canvas: #111827;" in css
    assert "--site-bg-sidebar: #0d1421;" in css
    assert "--site-surface-deep: #030712;" in css
    assert "--site-surface-primary: #090e1a;" in css
    assert "--site-surface-secondary: #0a101c;" in css
    assert "--site-surface-elevated: #0d1421;" in css


def test_canonical_iconlabs_tokens_match_the_sitewide_canvas():
    css = read("static/design-system.css")

    assert "--il-bg-app: #111827;" in css
    assert "--il-bg-sidebar: #0d1421;" in css
    assert "--il-bg-workspace: #111827;" in css
    assert "--il-surface-1: #090e1a;" in css
    assert "--il-surface-2: #0a101c;" in css


def test_reference_sidebar_palette_and_geometry_are_preserved():
    sidebar = read("static/sidebar-v2.css")

    assert "--il-sidebar-width:256px" in sidebar
    assert "--il-sidebar-bg:#070a13" in sidebar
    assert "--il-sidebar-surface:#0a101a" in sidebar
    assert "--il-sidebar-active:#1b1033" in sidebar
    assert "--il-sidebar-tool-hover:rgba(139,92,246,.32)" in sidebar
    assert "height:36px!important" in sidebar
    assert "background-image:none" in sidebar
    assert "sidebar-neon-purple-flow" not in sidebar


def test_real_model_positive_ev_keeps_layout_and_uses_the_slate_canvas():
    css = read("static/positive-ev.css")

    assert "height: 100dvh;" in css
    assert "padding: var(--il-gutter-desktop);" in css
    assert "background: var(--il-bg-app);" in css
    assert "grid-template-columns: minmax(0, 1fr)" in css


def test_page_owned_themes_keep_layout_but_inherit_the_slate_canvas():
    expected = {
        "static/odds-screen-v2.css": "--odds-panel: var(--il-surface-1);",
        "static/stage2-tracker.css": "--tracker-root: var(--site-bg-canvas);",
        "static/sharp-money-v2.css": "background: var(--site-bg-canvas) !important;",
        "static/lab-tracker.css": "--lab-bg: var(--site-bg-canvas);",
        "static/home.css": 'body[data-page="home"] .home-page',
    }

    for relative_path, contract in expected.items():
        assert contract in read(relative_path)


def test_legacy_layers_consume_the_shared_palette():
    assert "--bg-root: var(--site-bg-canvas);" in read("static/legacy-design-system.css")
    assert "--bg-root: var(--site-bg-canvas);" in read("static/stage2-art-direction.css")
    assert "--app-bg: var(--site-bg-canvas);" in read("static/app-premium.css")


def test_browser_chrome_uses_the_same_slate_theme_color():
    assert '<meta name="theme-color" content="#111827">' in read("templates/base.html")
