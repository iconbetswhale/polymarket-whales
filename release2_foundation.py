from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from decision_engine import (
    INDEPENDENCE_VERSION,
    KELLY_VERSION,
    LIQUIDITY_VERSION,
    OPPOSITION_VERSION,
    TRADE_QUALITY_VERSION,
)
from fair_price_engine import FAIR_PRICE_VERSION


RELEASE2_MIGRATION_VERSION = "002_release2_decision_engine"


def migration_sql(dialect: str) -> str:
    suffix = "postgres" if dialect == "postgres" else "sqlite"
    path = Path(__file__).resolve().parent / "migrations" / f"{RELEASE2_MIGRATION_VERSION}.{suffix}.sql"
    return path.read_text(encoding="utf-8")


def model_version_rows() -> list[dict[str, str]]:
    now = datetime.now(timezone.utc).isoformat()
    versions = {
        "trade_scoring": TRADE_QUALITY_VERSION,
        "fair_price": FAIR_PRICE_VERSION,
        "kelly": KELLY_VERSION,
        "sharp_independence": INDEPENDENCE_VERSION,
        "weighted_opposition": OPPOSITION_VERSION,
        "liquidity_quality": LIQUIDITY_VERSION,
    }
    return [
        {
            "version_key": f"{component}:{version}",
            "component": component,
            "version": version,
            "status": "ACTIVE",
            "description": "Release 2 decision engine.",
            "registered_at": now,
        }
        for component, version in versions.items()
    ]

