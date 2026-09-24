from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from administrative_orchestrator.domain import RoleAssignment
from administrative_orchestrator.integrations.personal_world import (
    PersonalWorldBoundaryError,
    PersonalWorldProjectionClient,
)


def _assignment() -> RoleAssignment:
    return RoleAssignment(
        principal_id="person:employee-42",
        role="employee",
        organization_scope="organization:acme",
        valid_from=datetime(2026, 9, 1, tzinfo=UTC),
    )


def test_role_assignment_maps_to_relationship_without_domain_ontology() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/contracts":
            return httpx.Response(
                200,
                json={
                    "manifest": "personal-world-contracts-v1",
                    "conformance": "personal-world-conformance-v1",
                    "package": "1.0.0",
                    "semantic_language": "0.2.0",
                },
            )
        payload = json.loads(request.content)
        calls.append((request.url.path, payload))
        return httpx.Response(
            200,
            json=[
                {
                    "kind": "relationship",
                    "status": "candidate",
                    "target_ref": "organization:acme",
                    "relation_namespace": "administrative.employment",
                }
            ],
        )

    client = PersonalWorldProjectionClient(
        "http://personal-world.test",
        transport=httpx.MockTransport(handler),
    )
    result = client.project_role_assignment(
        uuid4(),
        _assignment(),
        observed_at=datetime(2026, 9, 22, tzinfo=UTC),
    )

    assert result[0]["kind"] == "relationship"
    path, payload = calls[0]
    assert path == "/v1/domain-projections"
    assert payload["source_domain"] == "administrative-orchestrator"
    claim = payload["claims"][0]
    assert claim["record_kind"] == "relationship"
    assert claim["target_ref"] == "organization:acme"
    assert claim["relation_namespace"] == "administrative.employment"
    client.close()


def test_contract_drift_fails_closed() -> None:
    client = PersonalWorldProjectionClient(
        "http://personal-world.test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "manifest": "personal-world-contracts-v2",
                    "conformance": "personal-world-conformance-v1",
                    "package": "1.0.0",
                    "semantic_language": "0.2.0",
                },
            )
        ),
    )
    with pytest.raises(PersonalWorldBoundaryError, match="contract mismatch"):
        client.ensure_contracts()
    client.close()


def test_real_personal_world_administrative_ingress() -> None:
    base_url = os.getenv("ADMIN_PERSONAL_WORLD_TEST_URL")
    if not base_url:
        pytest.skip("real Personal World integration is not configured")

    client = PersonalWorldProjectionClient(base_url)
    result = client.project_role_assignment(uuid4(), _assignment())
    assert len(result) == 1
    assert result[0]["kind"] == "relationship"
    assert result[0]["status"] == "candidate"
    assert result[0]["target_ref"] == "organization:acme"
    assert result[0]["relation_namespace"] == "administrative.employment"
    client.close()


def test_personal_world_signed_workload_identity_is_purpose_bound() -> None:
    secret = "pw-workload-secret"
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        purpose = request.headers.get("X-Purpose", "")
        timestamp = request.headers.get("X-Workload-Timestamp", "")
        signature = request.headers.get("X-Workload-Signature", "")
        assert request.headers["X-Service-Identity"] == "administrative-orchestrator"
        assert purpose in {"contract-discovery", "domain-projection"}
        assert timestamp
        expected = hmac.new(
            secret.encode(),
            f"administrative-orchestrator\n{purpose}\n{timestamp}".encode(),
            hashlib.sha256,
        ).hexdigest()
        assert hmac.compare_digest(signature, expected)
        seen.append(purpose)
        if request.url.path == "/v1/contracts":
            return httpx.Response(
                200,
                json={
                    "manifest": "personal-world-contracts-v1",
                    "conformance": "personal-world-conformance-v1",
                    "package": "1.0.0",
                    "semantic_language": "0.2.0",
                },
            )
        return httpx.Response(
            200,
            json=[
                {
                    "kind": "relationship",
                    "status": "candidate",
                    "target_ref": "organization:acme",
                    "relation_namespace": "administrative.employment",
                }
            ],
        )

    client = PersonalWorldProjectionClient(
        "http://personal-world.test",
        workload_secret=secret,
        transport=httpx.MockTransport(handler),
    )
    client.project_role_assignment(uuid4(), _assignment())
    assert seen == ["contract-discovery", "domain-projection"]
    client.close()
