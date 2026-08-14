from __future__ import annotations

from pathlib import Path


MARKET_QUOTE_MIGRATION_VERSION = "007_normalized_market_quotes"


def migration_sql(dialect: str) -> str:
    suffix = "postgres" if dialect == "postgres" else "sqlite"
    path = Path(__file__).resolve().parent / "migrations" / f"{MARKET_QUOTE_MIGRATION_VERSION}.{suffix}.sql"
    return path.read_text(encoding="utf-8")
