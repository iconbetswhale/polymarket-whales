from pathlib import Path


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "deploy-production.yml"
).read_text(encoding="utf-8")


def test_optimizer_smoke_does_not_fail_a_successful_deploy_on_provider_timeout() -> None:
    assert "with urllib.request.urlopen(request, timeout=30)" in WORKFLOW
    assert "except urllib.error.HTTPError:" in WORKFLOW
    assert "except (TimeoutError, socket.timeout, urllib.error.URLError):" in WORKFLOW
    assert "::warning title=Optimizer API timed out::" in WORKFLOW
    assert "The production deploy succeeded; check provider health separately." in WORKFLOW


def test_optimizer_smoke_still_rejects_broken_api_contracts() -> None:
    assert 'if status != 200:' in WORKFLOW
    assert 'raise SystemExit(f"{path} returned HTTP {status}")' in WORKFLOW
    assert 'if data.get("degraded") and not data.get("message"):' in WORKFLOW
    assert 'raise SystemExit(f"{path} omitted its degraded-state message")' in WORKFLOW
