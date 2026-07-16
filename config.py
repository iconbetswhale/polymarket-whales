from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent
MAX_UNFAVORABLE_SLIPPAGE_PCT = 5.0


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
    discord_bot_token: str | None = field(default=None, repr=False)
    discord_guild_id: str | None = None
    discord_trade_channel_id: str | None = None
    discord_notifications_enabled: bool = False
    discord_notification_batch_size: int = 10
    durable_database_url: str | None = None
    tracker_job_secret: str | None = None
    tracker_job_interval_seconds: int = 300
    novig_api_key: str | None = None
    novig_api_base_url: str = "https://api.sportsgameodds.com/v2"
    novig_cache_ttl_seconds: int = 45
    prophetx_access_key: str | None = field(default=None, repr=False)
    prophetx_secret_key: str | None = field(default=None, repr=False)
    prophetx_api_base_url: str = "https://api-ss-sandbox.betprophet.co/partner"
    prophetx_trade_url: str | None = None
    prophetx_cache_ttl_seconds: int = 30
    execution_quote_max_age_seconds: int = 60
    execution_wide_spread_fraction: float = 0.03
    minimum_edge_discovery: float = 0.01
    minimum_edge_b: float = 0.015
    minimum_edge_a: float = 0.02
    minimum_edge_a_plus: float = 0.025
    max_single_position_fraction: float = 0.02
    max_game_exposure_fraction: float = 0.025
    max_team_day_exposure_fraction: float = 0.04
    max_daily_exposure_fraction: float = 0.06
    max_correlated_cluster_fraction: float = 0.04
    max_provider_exposure_fraction: float = 0.10


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
        execution_quote_max_age_seconds=_get_int("EXECUTION_QUOTE_MAX_AGE_SECONDS", 60),
        execution_wide_spread_fraction=_get_float("EXECUTION_WIDE_SPREAD_FRACTION", 0.03),
        minimum_edge_discovery=_get_float("MINIMUM_EDGE_DISCOVERY", 0.01),
        minimum_edge_b=_get_float("MINIMUM_EDGE_B", 0.015),
        minimum_edge_a=_get_float("MINIMUM_EDGE_A", 0.02),
        minimum_edge_a_plus=_get_float("MINIMUM_EDGE_A_PLUS", 0.025),
        max_single_position_fraction=_get_float("MAX_SINGLE_POSITION_FRACTION", 0.02),
        max_game_exposure_fraction=_get_float("MAX_GAME_EXPOSURE_FRACTION", 0.025),
        max_team_day_exposure_fraction=_get_float("MAX_TEAM_DAY_EXPOSURE_FRACTION", 0.04),
        max_daily_exposure_fraction=_get_float("MAX_DAILY_EXPOSURE_FRACTION", 0.06),
        max_correlated_cluster_fraction=_get_float("MAX_CORRELATED_CLUSTER_FRACTION", 0.04),
        max_provider_exposure_fraction=_get_float("MAX_PROVIDER_EXPOSURE_FRACTION", 0.10),
        discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL") or None,
        discord_alert_types=_get_csv(
            "DISCORD_ALERT_TYPES", ("new_entry", "size_increase", "full_exit")
        ),
        discord_min_position_usd=_get_float("DISCORD_MIN_POSITION_USD", 0.0),
        discord_notify_on_initial_scan=_get_bool(
            "DISCORD_NOTIFY_ON_INITIAL_SCAN", False
        ),
        discord_bot_token=os.getenv("DISCORD_BOT_TOKEN") or None,
        discord_guild_id=os.getenv("DISCORD_GUILD_ID") or None,
        discord_trade_channel_id=os.getenv("DISCORD_TRADE_CHANNEL_ID") or None,
        discord_notifications_enabled=_get_bool(
            "DISCORD_NOTIFICATIONS_ENABLED", False
        ),
        discord_notification_batch_size=_get_int(
            "DISCORD_NOTIFICATION_BATCH_SIZE", 10
        ),
        durable_database_url=(
            os.getenv("DURABLE_DATABASE_URL")
            or os.getenv("POSTGRES_URL")
            or os.getenv("DATABASE_URL")
            or None
        ),
        tracker_job_secret=os.getenv("TRACKER_JOB_SECRET") or None,
        tracker_job_interval_seconds=_get_int("TRACKER_JOB_INTERVAL_SECONDS", 300),
        novig_api_key=(
            os.getenv("NOVIG_ODDS_API_KEY")
            or os.getenv("SPORTSGAMEODDS_API_KEY")
            or None
        ),
        novig_api_base_url=os.getenv(
            "NOVIG_ODDS_API_BASE_URL", "https://api.sportsgameodds.com/v2"
        ),
        novig_cache_ttl_seconds=_get_int("NOVIG_ODDS_CACHE_TTL_SECONDS", 45),
        prophetx_access_key=os.getenv("PROPHETX_ACCESS_KEY") or None,
        prophetx_secret_key=os.getenv("PROPHETX_SECRET_KEY") or None,
        prophetx_api_base_url=os.getenv(
            "PROPHETX_API_BASE_URL",
            "https://api-ss-sandbox.betprophet.co/partner",
        ),
        prophetx_trade_url=os.getenv("PROPHETX_TRADE_URL") or None,
        prophetx_cache_ttl_seconds=_get_int("PROPHETX_CACHE_TTL_SECONDS", 30),
    )
