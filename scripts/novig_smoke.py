from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_settings
from novig_feed_worker import websocket_smoke_test
from novig_provider import NoVIGAuthClient, NoVIGRestClient


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sanitized read-only NoVIG credential and market-data smoke test."
    )
    parser.add_argument(
        "--websocket-seconds",
        type=float,
        default=8.0,
        help="How long to wait for a market book snapshot and tape update.",
    )
    args = parser.parse_args()
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
    rest_result = rest.credential_smoke_test(sample_size=3)
    book_result = _initial_book_smoke(rest, rest_result)
    websocket_result = (
        websocket_smoke_test(
            auth,
            rest,
            websocket_url=settings.novig_websocket_url,
            timeout_seconds=max(1.0, min(args.websocket_seconds, 30.0)),
        )
        if rest_result.get("success")
        else {
            "success": False,
            "error_code": "NOVIG_REST_SMOKE_FAILED",
            "credentials_exposed": False,
            "token_exposed": False,
        }
    )
    result = {
        "provider": "novig",
        "read_only": True,
        "rest": rest_result,
        "initial_order_book": book_result,
        "websocket": websocket_result,
        "credentials_exposed": False,
        "token_exposed": False,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return (
        0
        if rest_result.get("success")
        and book_result.get("success")
        and websocket_result.get("success")
        else 1
    )


def _initial_book_smoke(rest: NoVIGRestClient, rest_result: dict) -> dict:
    result = {
        "success": False,
        "http_status": None,
        "market_id": None,
        "outcome_ladder_count": 0,
        "resting_order_count": 0,
        "quantity_mcu_sample": [],
        "documented_quantity_mcu_per_contract": 100,
        "error_code": None,
        "credentials_exposed": False,
        "token_exposed": False,
    }
    samples = rest_result.get("market_sample") or []
    market_id = str((samples[0] if samples else {}).get("market_id") or "").strip()
    if not market_id:
        result["error_code"] = "NOVIG_NO_MARKET_FOR_BOOK_SMOKE"
        return result
    try:
        book = rest.get_book(market_id)
    except Exception as exc:
        result["http_status"] = getattr(exc, "status_code", None) or rest.last_http_status
        result["error_code"] = getattr(exc, "code", "NOVIG_BOOK_SMOKE_FAILED")
        return result
    ladders = [row for row in book.get("outcomeLadders") or [] if isinstance(row, dict)]
    orders = [
        order
        for ladder in ladders
        for order in ladder.get("bids") or []
        if isinstance(order, dict)
    ]
    result.update(
        {
            "success": True,
            "http_status": rest.last_http_status,
            "market_id": market_id,
            "outcome_ladder_count": len(ladders),
            "resting_order_count": len(orders),
            "quantity_mcu_sample": [
                {
                    "price": order.get("price"),
                    "qty": order.get("qty"),
                    "originalQty": order.get("originalQty"),
                    "currency": order.get("currency"),
                }
                for order in orders[:3]
            ],
        }
    )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
