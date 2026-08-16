from pathlib import Path


def test_healthy_empty_trade_state_is_not_presented_as_loading():
    app_js = (Path(__file__).parents[1] / "static" / "app.js").read_text(
        encoding="utf-8"
    )

    assert 'feedHealthy ? "No live picks" : "Scanning markets"' in app_js
    assert "<dt>Positions monitored</dt>" in app_js
    assert 'evaluated ? `${exactProviders.size} connected` : "Not required"' in app_js
