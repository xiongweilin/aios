"""Read-only, online-introspection protected resource for isolated P3 qualification.

Never accepts JWT signature alone as authorization. Never logs a bearer token or
client secret. No real employee or production tenant is addressed by this app.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


REALM = os.environ.get("P3_KEYCLOAK_REALM", "baa-real-e2e")
KEYCLOAK_BASE = os.environ.get("P3_KEYCLOAK_BASE", "http://keycloak:8080").rstrip("/")
CLIENT_ID = os.environ["P3_INTROSPECTION_CLIENT_ID"]
CLIENT_SECRET = os.environ["P3_INTROSPECTION_CLIENT_SECRET"]
AUTHORIZED_CLIENT = os.environ.get("P3_ALLOWED_BEARER_CLIENT_ID", "baa-session-client")


def inspect(token: str) -> tuple[str, dict[str, object]]:
    """One live Keycloak decision. Auth-server outage is UNKNOWN, not DENY."""
    body = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "token": token,
    }).encode("utf-8")
    url = (
        f"{KEYCLOAK_BASE}/realms/{urllib.parse.quote(REALM)}/"
        "protocol/openid-connect/token/introspect"
    )
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            payload = json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return "UNKNOWN", {"reason": "identity-provider-unavailable"}
    except (ValueError, TypeError):
        return "UNKNOWN", {"reason": "introspection-invalid-response"}

    if not isinstance(payload, dict) or type(payload.get("active")) is not bool:
        return "UNKNOWN", {"reason": "introspection-missing-active"}
    if payload["active"] is False:
        return "DENY", {"reason": "inactive-token"}

    bearer_client = payload.get("client_id")
    subject = payload.get("sub")
    if bearer_client != AUTHORIZED_CLIENT or not isinstance(subject, str) or not subject:
        return "DENY", {"reason": "client-or-subject-out-of-scope"}

    # Do not expose the token or full introspection metadata.
    return "ALLOW", {
        "subject": subject,
        "client_id": bearer_client,
    }


class ProtectedResource(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        # Default BaseHTTPRequestHandler logs URL and client data. Log nothing
        # from this deliberately credential-bearing acceptance endpoint.
        return

    def _reply(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._reply(200, {"status": "ready"})
            return
        if self.path != "/protected":
            self._reply(404, {"status": "not-found"})
            return

        authorization = self.headers.get("Authorization", "")
        if not authorization.startswith("Bearer ") or len(authorization) < 12:
            self._reply(401, {"access": "DENY", "reason": "missing-bearer"})
            return
        token = authorization[7:]
        if any(ch.isspace() for ch in token):
            self._reply(401, {"access": "DENY", "reason": "malformed-bearer"})
            return

        decision, fields = inspect(token)
        http_status = {"ALLOW": 200, "DENY": 403, "UNKNOWN": 503}[decision]
        self._reply(http_status, {"access": decision, **fields})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8095), ProtectedResource).serve_forever()
