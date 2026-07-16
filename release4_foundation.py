from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from learning_system import EDGE_MAP_VERSION, HOLDOUT_VERSION, LEARNING_SYSTEM_VERSION, RULE_VIOLATION_VERSION

RELEASE4_MIGRATION_VERSION = "004_release4_learning_system"

def migration_sql(dialect: str) -> str:
    suffix = "postgres" if dialect == "postgres" else "sqlite"
    return (Path(__file__).resolve().parent / "migrations" / f"{RELEASE4_MIGRATION_VERSION}.{suffix}.sql").read_text(encoding="utf-8")

def model_version_rows() -> list[dict[str, str]]:
    now = datetime.now(timezone.utc).isoformat()
    versions = {"learning_system": LEARNING_SYSTEM_VERSION, "edge_map": EDGE_MAP_VERSION, "holdout": HOLDOUT_VERSION, "rule_violations": RULE_VIOLATION_VERSION}
    return [{"version_key": f"{component}:{version}", "component": component, "version": version, "status": "OBSERVATIONAL", "description": "Release 4 learning system; cannot automatically change production weights.", "registered_at": now} for component, version in versions.items()]
