from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from administrative_orchestrator import api
from administrative_orchestrator.intake.repository import IntakeRepository
from administrative_orchestrator.messaging import OutboxEventRow
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.providers.feishu import (
    FeishuEventVerifier,
    FeishuWebhookBoundary,
)

EVENT_TIME = 1_893_456_000_000


def _body(*, token: str = "verification-token") -> bytes:
    return json.dumps(
        {
            "schema": "2.0",
            "header": {
                "event_id": "event-http-1",
                "event_type": "im.message.receive_v1",
                "tenant_key": "tenant-http",
                "token": token,
                "create_time": str(EVENT_TIME),
            },
            "event": {
                "sender": {"sender_id": {"open_id": "ou-http"}},
                "message": {
                    "message_id": "om-http-1",
                    "root_id": "om-http-1",
                    "create_time": str(EVENT_TIME),
                    "message_type": "text",
                },
            },
        },
        separators=(",", ":"),
    ).encode()


def _boundary() -> tuple[SqlStore, FeishuWebhookBoundary]:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    repository = IntakeRepository(store)
    verifier = FeishuEventVerifier(
        "verification-token",
        gateway_shared_secret="gateway-secret",
        clock=lambda: datetime.fromtimestamp(EVENT_TIME / 1000, tz=UTC).timestamp(),
    )
    return store, FeishuWebhookBoundary(repository, verifier)


def test_feishu_http_boundary_only_enqueues_verified_metadata(
    monkeypatch,
) -> None:
    store, boundary = _boundary()
    monkeypatch.setattr(api, "_feishu_intake_boundary", None)
    api.configure_feishu_intake(boundary)
    client = TestClient(api.app)

    response = client.post("/v1/intake/feishu/events", content=_body())

    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["created"] is True
    with store.sessions() as db:
        event = db.query(OutboxEventRow).one()
        assert event.event_type == "intake.feishu.received"
        assert "body" not in event.payload_json
        assert "content" not in event.payload_json


def test_feishu_http_boundary_maps_verification_and_challenge(monkeypatch) -> None:
    _, boundary = _boundary()
    monkeypatch.setattr(api, "_feishu_intake_boundary", boundary)
    client = TestClient(api.app)

    invalid = client.post(
        "/v1/intake/feishu/events",
        content=_body(token="wrong"),
    )
    assert invalid.status_code == 401

    challenge = client.post(
        "/v1/intake/feishu/events",
        content=json.dumps(
            {
                "type": "url_verification",
                "token": "verification-token",
                "challenge": "challenge-http",
            }
        ).encode(),
    )
    assert challenge.status_code == 200
    assert challenge.json() == {"challenge": "challenge-http"}


def test_feishu_http_boundary_reports_unconfigured(monkeypatch) -> None:
    monkeypatch.setattr(api, "_feishu_intake_boundary", None)
    response = TestClient(api.app).post(
        "/v1/intake/feishu/events",
        content=_body(),
    )
    assert response.status_code == 503


def test_feishu_http_boundary_accepts_long_connection_handoff_with_gateway_auth(monkeypatch) -> None:
    _, boundary = _boundary()
    monkeypatch.setattr(api, "_feishu_intake_boundary", boundary)
    decoded = json.loads(_body())
    decoded["header"].pop("token")
    client = TestClient(api.app)

    response = client.post(
        "/v1/intake/feishu/events",
        content=json.dumps(decoded).encode(),
        headers={"X-Administrative-Ingress-Token": "gateway-secret"},
    )

    assert response.status_code == 202
