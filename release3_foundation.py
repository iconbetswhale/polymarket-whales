from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from execution_engine import EXECUTION_ENGINE_VERSION
from risk_engine import BANKROLL_BUCKET_VERSION, DRAWDOWN_VERSION, RISK_ENGINE_VERSION


RELEASE3_MIGRATION_VERSION = "003_release3_execution_and_risk"


def migration_sql(dialect: str) -> str:
    suffix = "postgres" if dialect == "postgres" else "sqlite"
    path = Path(__file__).resolve().parent / "migrations" / f"{RELEASE3_MIGRATION_VERSION}.{suffix}.sql"
    return path.read_text(encoding="utf-8")


def model_version_rows() -> list[dict[str, str]]:
    now = datetime.now(timezone.utc).isoformat()
    versions = {
        "execution_plan": EXECUTION_ENGINE_VERSION,
        "portfolio_risk": RISK_ENGINE_VERSION,
        "bankroll_buckets": BANKROLL_BUCKET_VERSION,
        "drawdown_protocol": DRAWDOWN_VERSION,
    }
    return [
        {
            "version_key": f"{component}:{version}",
            "component": component,
            "version": version,
            "status": "ACTIVE",
            "description": "Release 3 execution and risk engine.",
            "registered_at": now,
        }
        for component, version in versions.items()
    ]

