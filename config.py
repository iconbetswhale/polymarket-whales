from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value)


def _get_optional_int(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    return int(value)


@dataclass(frozen=True)
class Settings:
    dashboard_refresh: int
    dashboard_port: int
    wallets_file: Path
    database_path: Path
    sports_only: bool
    resolve_hours: int
    min_american_odds: int | None
    max_american_odds: int | None
    request_timeout: int
    max_retries: int
    admin_password: str | None


def get_settings() -> Settings:
    dashboard_port = _get_int("PORT", _get_int("DASHBOARD_PORT", 5000))
    return Settings(
        dashboard_refresh=_get_int("DASHBOARD_REFRESH", 120),
        dashboard_port=dashboard_port,
        wallets_file=Path(os.getenv("WALLETS_FILE", "wallets.json")),
        database_path=Path(os.getenv("DATABASE_PATH", "polymarket_tracker.db")),
        sports_only=_get_bool("SPORTS_ONLY", True),
        resolve_hours=_get_int("RESOLVE_HOURS", 168),
        min_american_odds=_get_optional_int("MIN_AMERICAN_ODDS"),
        max_american_odds=_get_optional_int("MAX_AMERICAN_ODDS"),
        request_timeout=_get_int("REQUEST_TIMEOUT", 15),
        max_retries=_get_int("MAX_RETRIES", 3),
        admin_password=os.getenv("ADMIN_PASSWORD") or None,
    )
