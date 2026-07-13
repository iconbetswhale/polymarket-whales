from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent


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


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return float(value)


def _get_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _get_path(name: str, default: str) -> Path:
    value = Path(os.getenv(name, default))
    return value if value.is_absolute() else PROJECT_ROOT / value


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
    default_bankroll: float = 10000.0
    unit_percentage: float = 0.01
    discord_webhook_url: str | None = None
    discord_alert_types: tuple[str, ...] = ("new_entry", "size_increase", "full_exit")
    discord_min_position_usd: float = 0.0
    discord_notify_on_initial_scan: bool = False


def get_settings() -> Settings:
    dashboard_port = _get_int("PORT", _get_int("DASHBOARD_PORT", 5000))
    return Settings(
        dashboard_refresh=_get_int("DASHBOARD_REFRESH", 120),
        dashboard_port=dashboard_port,
        wallets_file=_get_path("WALLETS_FILE", "wallets.json"),
        database_path=_get_path("DATABASE_PATH", "polymarket_tracker.db"),
        sports_only=_get_bool("SPORTS_ONLY", True),
        resolve_hours=_get_int("RESOLVE_HOURS", 168),
        min_american_odds=_get_optional_int("MIN_AMERICAN_ODDS"),
        max_american_odds=_get_optional_int("MAX_AMERICAN_ODDS"),
        request_timeout=_get_int("REQUEST_TIMEOUT", 15),
        max_retries=_get_int("MAX_RETRIES", 3),
        admin_password=os.getenv("ADMIN_PASSWORD") or None,
        default_bankroll=_get_float("DEFAULT_BANKROLL", 10000.0),
        unit_percentage=_get_float("UNIT_PERCENTAGE", 0.01),
        discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL") or None,
        discord_alert_types=_get_csv(
            "DISCORD_ALERT_TYPES", ("new_entry", "size_increase", "full_exit")
        ),
        discord_min_position_usd=_get_float("DISCORD_MIN_POSITION_USD", 0.0),
        discord_notify_on_initial_scan=_get_bool(
            "DISCORD_NOTIFY_ON_INITIAL_SCAN", False
        ),
    )
