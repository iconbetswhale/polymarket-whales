from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["DATABASE_PATH"] = str(PROJECT_ROOT / ".sharp-money-local.db")
os.environ["DURABLE_DATABASE_URL"] = ""
os.environ["POSTGRES_URL"] = ""
os.environ["DATABASE_URL"] = ""

from app import create_app  # noqa: E402


if __name__ == "__main__":
    port = int(os.getenv("SHARP_MONEY_LOCAL_PORT", "5003"))
    app = create_app(start_background=False)
    app.run(
        host="127.0.0.1",
        port=port,
        debug=False,
        threaded=True,
        use_reloader=False,
    )
