from __future__ import annotations

from pathlib import Path


ODDS_TOOL_MIGRATION_VERSION = "008_odds_tool_state"


def migration_sql(dialect: str) -> str:
    suffix = "postgres" if dialect == "postgres" else "sqlite"
    path = (
        Path(__file__).resolve().parent
        / "migrations"
        / f"{ODDS_TOOL_MIGRATION_VERSION}.{suffix}.sql"
    )
    return path.read_text(encoding="utf-8")
