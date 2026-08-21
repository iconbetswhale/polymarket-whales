from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "templates" / "intelligence.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "intelligence-v2.css").read_text(encoding="utf-8")


def test_intelligence_opts_into_v2_without_global_legacy_layers(app_client) -> None:
    response = app_client.get("/intelligence")

    assert response.status_code == 200
    assert b'data-page="intelligence" data-design-system="v2"' in response.data
    assert b"design-system.css" in response.data
    assert b"intelligence-v2.css" in response.data
    for stylesheet in (
        b"legacy-design-system.css",
        b"stage2-art-direction.css",
        b"shared-shell.css",
        b"mobile-product.css",
        b"app-premium.css",
        b"sidebar-shell.css",
    ):
        assert stylesheet not in response.data


def test_intelligence_uses_v2_primitives_and_preserves_security_gate() -> None:
    for hook in (
        "intel-page",
        "il-dashboard-page",
        "il-page-header",
        "il-page-title",
        "il-stat-grid",
        "il-toolbar",
        "il-panel",
        "intel-trace-dialog",
    ):
        assert hook in TEMPLATE

    assert 'id="intel-login-form"' in TEMPLATE
    assert 'id="intel-password"' in TEMPLATE
    assert 'type="password"' in TEMPLATE
    assert 'autocomplete="current-password"' in TEMPLATE
    assert 'id="intel-workspace" hidden' in TEMPLATE
    assert 'id="intel-login-error" role="alert" aria-live="polite"' in TEMPLATE


def test_intelligence_v2_is_flat_and_token_driven() -> None:
    assert 'body[data-design-system="v2"][data-page="intelligence"]' in CSS
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
        "var(--il-backdrop)",
    ):
        assert token in CSS


def test_intelligence_preserves_all_workspace_tabs_and_controls() -> None:
    for tab in ("candidates", "proposals", "violations", "diagnostics"):
        assert f'data-intel-tab="{tab}"' in TEMPLATE
        assert f'data-intel-panel="{tab}"' in TEMPLATE

    for decision in (
        "APPROVED_STANDARD",
        "APPROVED_DISCOVERY",
        "PASSED",
        "RESEARCH_ONLY",
        "INVALID",
    ):
        assert decision in TEMPLATE

    assert 'role="tab"' in TEMPLATE
    assert 'aria-selected="true"' in TEMPLATE
    assert 'item.setAttribute("aria-selected",String(active))' in SCRIPT


def test_intelligence_retains_auth_data_trace_and_apply_workflows() -> None:
    for hook in (
        "loadIntelligence",
        "renderIntelligence",
        "bindIntelligence",
        "/api/admin/login",
        "/api/admin/candidate-ledger",
        "openIntelTrace",
        "data-intel-apply",
        "showModal()",
    ):
        assert hook in SCRIPT


def test_intelligence_asset_loads_after_foundation() -> None:
    foundation = BASE.index("filename='design-system.css'")
    canonical = BASE.index("filename='intelligence-v2.css'", foundation)

    assert canonical > foundation
    assert "-canonical-v1" in BASE[canonical : canonical + 200]
