from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "templates" / "wallet_unlock.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "wallet-lock-v2.css").read_text(encoding="utf-8")


def configure_wallet_lock(app_client) -> None:
    app_client.application.config["WALLET_PAGE_PASSCODE"] = "1357"
    app_client.application.config["WALLET_PAGE_LOCK_SECRET"] = "wallet-lock-test-only"


def test_wallet_lock_opts_into_v2_without_global_legacy_layers(app_client) -> None:
    configure_wallet_lock(app_client)
    response = app_client.get("/wallets/unlock?next=/wallets")

    assert response.status_code == 200
    assert b'data-page="wallet-lock" data-design-system="v2"' in response.data
    assert b"design-system.css" in response.data
    assert b"wallet-lock-v2.css" in response.data
    for stylesheet in (
        b"legacy-design-system.css",
        b"stage2-art-direction.css",
        b"shared-shell.css",
        b"mobile-product.css",
        b"app-premium.css",
        b"sidebar-shell.css",
    ):
        assert stylesheet not in response.data


def test_wallet_lock_preserves_four_digit_security_contract(app_client) -> None:
    configure_wallet_lock(app_client)

    for hook in (
        "wallet-lock-shell",
        "il-dashboard-page",
        "wallet-lock-card",
        "il-panel",
        'type="password"',
        'pattern="[0-9]{4}"',
        'minlength="4"',
        'maxlength="4"',
        'autocomplete="one-time-code"',
        'role="alert" aria-live="polite"',
    ):
        assert hook in TEMPLATE

    wrong = app_client.post(
        "/wallets/unlock?next=/wallets",
        data={"passcode": "0000", "next": "/wallets"},
    )
    assert wrong.status_code == 401
    assert b"Incorrect passcode. Try again." in wrong.data

    correct = app_client.post(
        "/wallets/unlock?next=/wallets",
        data={"passcode": "1357", "next": "/wallets"},
    )
    assert correct.status_code == 302
    assert correct.headers["Location"].endswith("/wallets")
    assert "iconbets_wallet_unlocked=" in correct.headers["Set-Cookie"]


def test_wallet_lock_v2_is_flat_and_token_driven() -> None:
    assert 'body[data-design-system="v2"][data-page="wallet-lock"]' in CSS
    assert "gradient(" not in CSS
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", CSS)
    assert not re.search(r"\brgba?\(", CSS)
    assert "!important" not in CSS

    for token in (
        "var(--il-bg-app)",
        "var(--il-surface-1)",
        "var(--il-surface-2)",
        "var(--il-border-subtle)",
        "var(--il-text-primary)",
        "var(--il-brand-hover)",
    ):
        assert token in CSS


def test_wallet_lock_marks_sharp_wallets_navigation_current() -> None:
    assert "page in ['wallets', 'wallet-lock']" in BASE


def test_wallet_lock_asset_loads_after_foundation() -> None:
    foundation = BASE.index("filename='design-system.css'")
    canonical = BASE.index("filename='wallet-lock-v2.css'", foundation)

    assert canonical > foundation
    assert "-canonical-v1" in BASE[canonical : canonical + 200]
