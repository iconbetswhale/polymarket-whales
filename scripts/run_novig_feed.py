from __future__ import annotations

import logging
import signal
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_settings
from novig_feed_worker import NoVIGFeedWorker
from novig_provider import NoVIGAuthClient, NoVIGRestClient, NoVIGStateStore


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = get_settings()
    auth = NoVIGAuthClient(
        settings.novig_client_id,
        settings.novig_client_secret,
        auth_url=settings.novig_auth_url,
        timeout=min(settings.request_timeout, 5),
    )
    rest = NoVIGRestClient(
        auth,
        base_url=settings.novig_rest_base_url,
        timeout=min(settings.request_timeout, 5),
    )
    worker = NoVIGFeedWorker(
        auth,
        rest,
        NoVIGStateStore(settings.novig_state_database_url),
        websocket_url=settings.novig_websocket_url,
        stale_after_seconds=settings.novig_stale_after_seconds,
        flush_interval_seconds=settings.novig_worker_flush_seconds,
        market_subscription_limit=settings.novig_ws_market_subscription_limit,
    )

    def stop_worker(_signum, _frame) -> None:
        worker.stop()

    signal.signal(signal.SIGINT, stop_worker)
    signal.signal(signal.SIGTERM, stop_worker)
    try:
        worker.run_forever()
    except Exception as exc:
        logging.getLogger(__name__).error(
            "NoVIG feed worker stopped: %s", getattr(exc, "code", "WORKER_FAILED")
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
