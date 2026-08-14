"""Back up and reset the live and shadow model-tracker experiments."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row


MODEL_USER_IDS = (
    "iconbets-model-tracker-global",
    "iconbets-model-tracker-three-sharp-qk-conviction-2x-v3",
    "iconbets-model-tracker-weighted-mlb-tennis-v1",
    "iconbets-shadow-broad-consensus-2",
)


def load_env_file(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        key = key.strip()
        if not os.environ.get(key):
            os.environ[key] = value


def json_value(value: Any) -> Any:
    if isinstance(value, (datetime,)):
        return value.isoformat()
    return str(value)


def table_exists(conn: psycopg.Connection, table: str) -> bool:
    row = conn.execute("SELECT to_regclass(%s) AS name", (f"public.{table}",)).fetchone()
    return bool(row and row["name"])


def fetch_rows(
    conn: psycopg.Connection,
    table: str,
    where_sql: str,
    params: tuple[Any, ...],
) -> list[dict[str, Any]]:
    if not table_exists(conn, table):
        return []
    return [
        dict(row)
        for row in conn.execute(
            f"SELECT * FROM {table} WHERE {where_sql}", params
        ).fetchall()
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--backup-dir", type=Path, default=Path("outputs/model-reset-backups"))
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if args.env_file:
        load_env_file(args.env_file)
    database_url = (
        os.getenv("DURABLE_DATABASE_URL")
        or os.getenv("POSTGRES_URL")
        or os.getenv("DATABASE_URL")
    )
    if not database_url:
        raise SystemExit("No production database URL was found.")

    reset_at = datetime.now(timezone.utc).isoformat()
    placeholders = ", ".join(["%s"] * len(MODEL_USER_IDS))
    user_params = tuple(MODEL_USER_IDS)

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        tracker_rows = fetch_rows(
            conn, "bet_tracker", f"user_id IN ({placeholders})", user_params
        )
        tracker_keys = tuple(
            sorted({str(row["dedupe_key"]) for row in tracker_rows})
        )
        key_placeholders = ", ".join(["%s"] * len(tracker_keys))

        backup: dict[str, Any] = {
            "reset_at": reset_at,
            "user_ids": MODEL_USER_IDS,
            "tables": {
                "bet_tracker": tracker_rows,
                "tracking_rejections": fetch_rows(
                    conn,
                    "tracking_rejections",
                    f"user_id IN ({placeholders})",
                    user_params,
                ),
                "discord_trade_notifications": fetch_rows(
                    conn,
                    "discord_trade_notifications",
                    f"user_id IN ({placeholders})",
                    user_params,
                ),
                "closing_line_snapshots": fetch_rows(
                    conn,
                    "closing_line_snapshots",
                    f"user_id IN ({placeholders})",
                    user_params,
                ),
                "dual_clv_measurements": fetch_rows(
                    conn,
                    "dual_clv_measurements",
                    f"user_id IN ({placeholders})",
                    user_params,
                ),
                "portfolio_risk_snapshots": fetch_rows(
                    conn,
                    "portfolio_risk_snapshots",
                    f"user_id IN ({placeholders})",
                    user_params,
                ),
                "risk_account_state": fetch_rows(
                    conn,
                    "risk_account_state",
                    f"user_id IN ({placeholders})",
                    user_params,
                ),
                "clv_quote_snapshots": (
                    fetch_rows(
                        conn,
                        "clv_quote_snapshots",
                        f"tracker_type = 'model' AND tracker_record_id IN ({key_placeholders})",
                        tracker_keys,
                    )
                    if tracker_keys
                    else []
                ),
            },
        }
        backup["counts"] = {
            table: len(rows) for table, rows in backup["tables"].items()
        }

        args.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = reset_at.replace(":", "").replace("-", "").replace("+00:00", "Z")
        backup_path = args.backup_dir / f"model-tracking-reset-{stamp}.json"
        backup_path.write_text(
            json.dumps(backup, indent=2, default=json_value),
            encoding="utf-8",
        )

        if not args.execute:
            conn.rollback()
            print(
                json.dumps(
                    {
                        "mode": "dry-run",
                        "backup": str(backup_path.resolve()),
                        "counts": backup["counts"],
                    }
                )
            )
            return 0

        deleted: dict[str, int] = {}
        if tracker_keys and table_exists(conn, "clv_quote_snapshots"):
            cursor = conn.execute(
                f"""DELETE FROM clv_quote_snapshots
                    WHERE tracker_type = 'model'
                      AND tracker_record_id IN ({key_placeholders})""",
                tracker_keys,
            )
            deleted["clv_quote_snapshots"] = cursor.rowcount

        for table in (
            "dual_clv_measurements",
            "closing_line_snapshots",
            "portfolio_risk_snapshots",
            "discord_trade_notifications",
            "tracking_rejections",
            "bet_tracker",
        ):
            if not table_exists(conn, table):
                deleted[table] = 0
                continue
            cursor = conn.execute(
                f"DELETE FROM {table} WHERE user_id IN ({placeholders})",
                user_params,
            )
            deleted[table] = cursor.rowcount

        if table_exists(conn, "risk_account_state"):
            cursor = conn.execute(
                f"DELETE FROM risk_account_state WHERE user_id IN ({placeholders})",
                user_params,
            )
            deleted["risk_account_state"] = cursor.rowcount

        remaining = conn.execute(
            f"""SELECT user_id, COUNT(*) AS count
                FROM bet_tracker
                WHERE user_id IN ({placeholders})
                GROUP BY user_id""",
            user_params,
        ).fetchall()
        if remaining:
            raise RuntimeError(f"Tracker reset verification failed: {remaining}")

        conn.commit()
        print(
            json.dumps(
                {
                    "mode": "executed",
                    "reset_at": reset_at,
                    "backup": str(backup_path.resolve()),
                    "backed_up": backup["counts"],
                    "deleted": deleted,
                    "remaining_tracker_records": 0,
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
