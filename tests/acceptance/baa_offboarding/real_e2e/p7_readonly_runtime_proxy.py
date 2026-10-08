"""Loopback-only, GET-only credential boundary for the isolated P7 Runtime source."""
from __future__ import annotations

import contextlib
import hmac
import http.server
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any

MAX_RESPONSE_BYTES = 1_048_577
ALLOWED_PATHS = frozenset({"/healthz", "/v1/capabilities"})


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def _parse_expiry(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError("invalid_p7_proxy_expiry") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise RuntimeError("invalid_p7_proxy_expiry")
    return result.astimezone(UTC)


def request_is_allowed(
    method: str,
    path: str,
    authorization: str | None,
    delegation_id: str | None,
    expected_token: str,
    expected_delegation: str,
    *,
    now: datetime | None = None,
    expires_at: datetime | None = None,
) -> bool:
    if method != "GET" or path not in ALLOWED_PATHS:
        return False
    if path == "/healthz":
        return True
    if expires_at is not None and (now or datetime.now(UTC)) >= expires_at:
        return False
    expected_authorization = "Bearer " + expected_token
    return (
        isinstance(authorization, str)
        and hmac.compare_digest(authorization, expected_authorization)
        and delegation_id == expected_delegation
    )


class ReadOnlyRuntimeHandler(http.server.BaseHTTPRequestHandler):
    server_version = "P7ReadOnlyRelay"
    sys_version = ""

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _respond(self, status: int, body: bytes = b"", content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _close_without_response(self) -> None:
        self.close_connection = True
        with contextlib.suppress(OSError):
            self.connection.shutdown(socket.SHUT_RDWR)
        with contextlib.suppress(OSError):
            self.connection.close()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.query or parsed.fragment:
            self._respond(400)
            return

        token = os.environ["BAA_P7_RUNTIME_TOKEN"]
        delegation = os.environ["BAA_P7_RUNTIME_DELEGATION_ID"]
        expires_at = _parse_expiry(os.environ["BAA_P7_RUNTIME_EXPIRES_AT"])
        if not request_is_allowed(
            "GET",
            parsed.path,
            self.headers.get("Authorization"),
            self.headers.get("X-World-Runtime-Delegation"),
            token,
            delegation,
            expires_at=expires_at,
        ):
            self._respond(403)
            return

        upstream = os.environ["BAA_P7_RUNTIME_UPSTREAM"].rstrip("/") + parsed.path
        headers = {"Accept": "application/json"}
        if parsed.path == "/v1/capabilities":
            headers["Authorization"] = "Bearer " + os.environ["BAA_REAL_RUNTIME_TOKEN"]
            headers["X-World-Runtime-Delegation"] = os.environ[
                "BAA_REAL_RUNTIME_DELEGATION_ID"
            ]
        request = urllib.request.Request(upstream, headers=headers, method="GET")
        opener = urllib.request.build_opener(NoRedirectHandler()).open
        try:
            response = opener(request, timeout=3.0)
            try:
                body = response.read(MAX_RESPONSE_BYTES)
                content_type = response.headers.get("Content-Type", "application/json")
                self._respond(int(response.status), body, content_type)
            finally:
                response.close()
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            exc.close()
            self._respond(status)
        except (urllib.error.URLError, OSError, TimeoutError, ConnectionError):
            self._close_without_response()

    def do_POST(self) -> None:
        self._respond(405)

    def do_PUT(self) -> None:
        self._respond(405)

    def do_PATCH(self) -> None:
        self._respond(405)

    def do_DELETE(self) -> None:
        self._respond(405)

    def do_OPTIONS(self) -> None:
        self._respond(405)

    def do_HEAD(self) -> None:
        self._respond(405)


def main() -> None:
    required = (
        "BAA_P7_RUNTIME_TOKEN",
        "BAA_P7_RUNTIME_DELEGATION_ID",
        "BAA_P7_RUNTIME_EXPIRES_AT",
        "BAA_P7_RUNTIME_UPSTREAM",
        "BAA_REAL_RUNTIME_TOKEN",
        "BAA_REAL_RUNTIME_DELEGATION_ID",
    )
    if any(not os.environ.get(name) for name in required):
        raise SystemExit("p7_readonly_proxy_configuration_missing")
    if _parse_expiry(os.environ["BAA_P7_RUNTIME_EXPIRES_AT"]) <= datetime.now(UTC):
        raise SystemExit("p7_readonly_proxy_credential_expired")
    server = http.server.ThreadingHTTPServer(
        ("0.0.0.0", int(os.environ.get("BAA_P7_RUNTIME_PROXY_PORT", "8087"))),
        ReadOnlyRuntimeHandler,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
