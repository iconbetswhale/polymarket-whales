from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402


if __name__ == "__main__":
    create_app(start_background=False).run(
        host="127.0.0.1", port=5099, debug=False
    )
