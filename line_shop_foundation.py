from __future__ import annotations

from pathlib import Path


LINE_SHOP_MIGRATION_VERSION = "006_line_shop_execution"


def migration_sql(dialect: str) -> str:
    suffix = "postgres" if dialect == "postgres" else "sqlite"
    path = Path(__file__).resolve().parent / "migrations" / f"{LINE_SHOP_MIGRATION_VERSION}.{suffix}.sql"
    return path.read_text(encoding="utf-8")
