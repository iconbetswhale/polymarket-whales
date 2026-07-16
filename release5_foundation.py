from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from completion_system import APPLIED_POLICY_VERSION, COMPLETION_SYSTEM_VERSION, EXPLAINABILITY_VERSION

RELEASE5_MIGRATION_VERSION = "005_release5_completion"
def migration_sql(dialect: str) -> str:
    suffix = "postgres" if dialect == "postgres" else "sqlite"
    return (Path(__file__).resolve().parent / "migrations" / f"{RELEASE5_MIGRATION_VERSION}.{suffix}.sql").read_text(encoding="utf-8")
def model_version_rows():
    now = datetime.now(timezone.utc).isoformat()
    versions = {"completion_system": COMPLETION_SYSTEM_VERSION, "applied_segment_policy": APPLIED_POLICY_VERSION, "explainability_trace": EXPLAINABILITY_VERSION}
    return [{"version_key": f"{k}:{v}", "component": k, "version": v, "status": "ACTIVE", "description": "Final completion release.", "registered_at": now} for k,v in versions.items()]
