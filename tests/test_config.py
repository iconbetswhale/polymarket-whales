from pathlib import Path
import tempfile

from config import PROJECT_ROOT, get_settings


def test_blank_database_path_uses_local_default(monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", "   ")
    monkeypatch.delenv("VERCEL", raising=False)

    assert get_settings().database_path == PROJECT_ROOT / "polymarket_tracker.db"


def test_blank_database_path_uses_writable_vercel_default(monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", "")
    monkeypatch.setenv("VERCEL", "1")

    assert get_settings().database_path == Path(tempfile.gettempdir()) / "polymarket_tracker.db"


def test_explicit_database_path_wins_on_vercel(monkeypatch, tmp_path):
    configured = tmp_path / "tracker.db"
    monkeypatch.setenv("DATABASE_PATH", str(configured))
    monkeypatch.setenv("VERCEL", "1")

    assert get_settings().database_path == configured

