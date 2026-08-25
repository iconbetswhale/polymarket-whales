from __future__ import annotations

import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from novig_feed_worker import websocket_smoke_test
from novig_provider import NoVIGAuthClient, NoVIGRestClient


def _authorized(header_value: str) -> bool:
    supplied = str(header_value or "").strip()
    if supplied.lower().startswith("bearer "):
        supplied = supplied[7:].strip()
    configured = [
        str(value).strip()
        for value in (os.getenv("TRACKER_JOB_SECRET"), os.getenv("CRON_SECRET"))
        if str(value or "").strip()
    ]
    return bool(supplied) and any(
        hmac.compare_digest(supplied, secret) for secret in configured
    )


def _smoke_payload() -> tuple[dict, int]:
    client_id = str(os.getenv("NOVIG_CLIENT_ID") or "").strip()
    client_secret = str(os.getenv("NOVIG_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        return (
            {
                "provider": "novig",
                "success": False,
                "error_code": "NOVIG_CREDENTIALS_NOT_CONFIGURED",
                "credentials_exposed": False,
                "token_exposed": False,
            },
            503,
        )
    auth = NoVIGAuthClient(client_id, client_secret, timeout=4)
    rest = NoVIGRestClient(auth, timeout=4)
    result = websocket_smoke_test(auth, rest, timeout_seconds=5)
    return {"provider": "novig", **result}, 200 if result.get("success") else 503


class handler(BaseHTTPRequestHandler):
    """Small Vercel function that avoids importing the full Flask application."""

    def do_POST(self) -> None:
        if not _authorized(self.headers.get("Authorization", "")):
            self._write_json({"status": "UNAUTHORIZED"}, 401)
            return
        payload, status = _smoke_payload()
        self._write_json(payload, status)

    def do_GET(self) -> None:
        self._write_json({"status": "METHOD_NOT_ALLOWED"}, 405)

    def _write_json(self, payload: dict, status: int) -> None:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
