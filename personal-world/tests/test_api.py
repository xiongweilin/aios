from __future__ import annotations

import json
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from personal_world.api.app import create_app
from personal_world.api.auth import workload_signature
from personal_world.model.contracts import (
    ClaimCreate,
    DataAccessProfile,
    ObservationCreate,
    PersonalFactCreate,
    RecordKind,
    SensitivityClass,
    SourceClass,
    SourceDescriptorCreate,
)
from semantic_language import SemanticRef


def test_service_auth_and_purpose_gate(service, monkeypatch) -> None:
    monkeypatch.setenv(
        "PERSONAL_WORLD_SERVICE_TOKENS_JSON",
        json.dumps({"administrative-orchestrator": "secret", "travel": "travel-secret"}),
    )
    client = TestClient(create_app(service))

    unauthenticated = client.get(
        "/v1/contracts",
        headers={"X-Service-Identity": "administrative-orchestrator", "X-Purpose": "audit"},
    )
    assert unauthenticated.status_code == 401

    authenticated = client.get(
        "/v1/contracts",
        headers={
            "X-Service-Identity": "administrative-orchestrator",
            "X-Purpose": "audit",
            "Authorization": "Bearer secret",
        },
    )
    assert authenticated.status_code == 200

    denied = client.get(
        f"/v1/subjects/{uuid4()}/current",
        headers={
            "X-Service-Identity": "travel",
            "X-Purpose": "finance",
            "Authorization": "Bearer travel-secret",
        },
    )
    assert denied.status_code == 403


def test_admin_can_manage_access_profiles(service, monkeypatch) -> None:
    monkeypatch.setenv(
        "PERSONAL_WORLD_SERVICE_TOKENS_JSON",
        json.dumps({"administrative-orchestrator": "secret"}),
    )
    client = TestClient(create_app(service))
    response = client.put(
        "/v1/access-profiles",
        json=DataAccessProfile(
            service_identity="new-service",
            allowed_purposes=("test",),
            allowed_kinds=(RecordKind.FACT,),
            max_sensitivity=SensitivityClass.PERSONAL,
        ).model_dump(mode="json"),
        headers={
            "X-Service-Identity": "administrative-orchestrator",
            "X-Purpose": "admin",
            "Authorization": "Bearer secret",
        },
    )
    assert response.status_code == 200


def test_signed_workload_identity_and_expiry(service, monkeypatch) -> None:
    secret = "workload-secret"
    monkeypatch.setenv("PERSONAL_WORLD_AUTH_MODE", "signed-hmac")
    monkeypatch.setenv(
        "PERSONAL_WORLD_WORKLOAD_HMAC_SECRETS_JSON",
        json.dumps({"administrative-orchestrator": secret}),
    )
    monkeypatch.setenv("PERSONAL_WORLD_WORKLOAD_ASSERTION_TTL_SECONDS", "60")
    client = TestClient(create_app(service))

    timestamp = str(int(time.time()))
    signature = workload_signature(
        secret,
        service_identity="administrative-orchestrator",
        purpose="audit",
        timestamp=timestamp,
    )
    accepted = client.get(
        "/v1/contracts",
        headers={
            "X-Service-Identity": "administrative-orchestrator",
            "X-Purpose": "audit",
            "X-Workload-Timestamp": timestamp,
            "X-Workload-Signature": signature,
        },
    )
    assert accepted.status_code == 200

    expired_timestamp = str(int(time.time()) - 120)
    expired_signature = workload_signature(
        secret,
        service_identity="administrative-orchestrator",
        purpose="audit",
        timestamp=expired_timestamp,
    )
    expired = client.get(
        "/v1/contracts",
        headers={
            "X-Service-Identity": "administrative-orchestrator",
            "X-Purpose": "audit",
            "X-Workload-Timestamp": expired_timestamp,
            "X-Workload-Signature": expired_signature,
        },
    )
    assert expired.status_code == 401


def test_root_subject_boundary_fails_closed(service, monkeypatch) -> None:
    root = uuid4()
    other = uuid4()
    monkeypatch.setenv("PERSONAL_WORLD_ROOT_SUBJECT_ID", str(root))
    monkeypatch.setenv(
        "PERSONAL_WORLD_SERVICE_TOKENS_JSON",
        json.dumps({"administrative-orchestrator": "secret"}),
    )
    client = TestClient(create_app(service))
    headers = {
        "X-Service-Identity": "administrative-orchestrator",
        "X-Purpose": "audit",
        "Authorization": "Bearer secret",
    }

    accepted = client.get(f"/v1/subjects/{root}/current", headers=headers)
    assert accepted.status_code == 200

    denied = client.get(f"/v1/subjects/{other}/current", headers=headers)
    assert denied.status_code == 403


def test_production_requires_root_subject_and_signed_workload_identity(service, monkeypatch) -> None:
    monkeypatch.setenv("PERSONAL_WORLD_DEPLOYMENT_PROFILE", "production")
    monkeypatch.delenv("PERSONAL_WORLD_ROOT_SUBJECT_ID", raising=False)
    with pytest.raises(RuntimeError, match="ROOT_SUBJECT_ID"):
        create_app(service)

    monkeypatch.setenv("PERSONAL_WORLD_ROOT_SUBJECT_ID", str(uuid4()))
    monkeypatch.setenv("PERSONAL_WORLD_AUTH_MODE", "bearer")
    client = TestClient(create_app(service))
    with pytest.raises(RuntimeError, match="signed-hmac"):
        client.get(
            "/v1/contracts",
            headers={
                "X-Service-Identity": "administrative-orchestrator",
                "X-Purpose": "audit",
                "Authorization": "Bearer secret",
            },
        )


def test_root_subject_boundary_covers_all_subject_bearing_surfaces(service, monkeypatch) -> None:
    root = uuid4()
    other = uuid4()
    semantic = SemanticRef(kind="predicate", id="boundary-test", namespace="personal")
    source = service.create_source(
        SourceDescriptorCreate(
            source_class=SourceClass.HUMAN_EXPLICIT,
            actor_ref="human:other",
            description="root-subject boundary seed",
        )
    )
    observation = service.create_observation(
        ObservationCreate(
            subject_id=other,
            source_id=source.id,
            semantic=semantic,
            value="observed",
        )
    )
    claim = service.create_claim(
        ClaimCreate(
            subject_id=other,
            source_id=source.id,
            semantic=semantic,
            value="claimed",
            observation_refs=(observation.id,),
        )
    )
    record = service.create_fact(
        PersonalFactCreate(
            subject_id=other,
            semantic=semantic,
            value="fact",
            source_refs=(source.id,),
            claim_refs=(claim.id,),
        )
    )
    other_bundle = service.export_bundle()

    monkeypatch.setenv("PERSONAL_WORLD_ROOT_SUBJECT_ID", str(root))
    monkeypatch.setenv(
        "PERSONAL_WORLD_SERVICE_TOKENS_JSON",
        json.dumps({"administrative-orchestrator": "secret"}),
    )
    client = TestClient(create_app(service))
    headers = {
        "X-Service-Identity": "administrative-orchestrator",
        "X-Purpose": "audit",
        "Authorization": "Bearer secret",
    }

    denied_gets = [
        f"/v1/observations/{observation.id}",
        f"/v1/claims/{claim.id}",
        f"/v1/subjects/{other}/current",
        f"/v1/subjects/{other}/history",
        f"/v1/disclosure-audit?subject_id={other}",
        "/v1/bundle",
    ]
    for endpoint in denied_gets:
        assert client.get(endpoint, headers=headers).status_code == 403

    source_ref = str(source.id)
    semantic_json = {
        "kind": semantic.kind,
        "id": semantic.id,
        "namespace": semantic.namespace,
        "version": semantic.version,
    }
    denied_posts = [
        (
            "/v1/observations",
            {
                "subject_id": str(other),
                "source_id": source_ref,
                "semantic": semantic_json,
                "value": "x",
            },
        ),
        (
            "/v1/claims",
            {
                "subject_id": str(other),
                "source_id": source_ref,
                "semantic": semantic_json,
                "value": "x",
            },
        ),
        (
            "/v1/facts",
            {
                "subject_id": str(other),
                "semantic": semantic_json,
                "value": "x",
                "source_refs": [source_ref],
            },
        ),
        (
            "/v1/preferences",
            {
                "subject_id": str(other),
                "semantic": semantic_json,
                "value": "window",
                "source_refs": [source_ref],
                "origin": "explicit",
            },
        ),
        (
            "/v1/relationships",
            {
                "subject_id": str(other),
                "semantic": semantic_json,
                "value": "employee",
                "source_refs": [source_ref],
                "target_ref": "organization:acme",
                "relation_namespace": "employment",
            },
        ),
        (
            "/v1/resource-links",
            {
                "subject_id": str(other),
                "semantic": semantic_json,
                "value": "repo",
                "source_refs": [source_ref],
                "resource_ref": "github:x/repo",
                "domain": "development",
                "relation": "target",
            },
        ),
        (
            "/v1/context-projections",
            {"subject_id": str(other), "purpose": "audit"},
        ),
        (
            "/v1/model-context",
            {"subject_id": str(other), "purpose": "audit"},
        ),
        (
            "/v1/search",
            {"subject_id": str(other), "purpose": "audit", "query": "fact"},
        ),
        (
            "/v1/domain-projections",
            {
                "subject_id": str(other),
                "source_domain": "administrative-orchestrator",
                "source_object_ref": "object:1",
                "claims": [
                    {
                        "record_kind": "fact",
                        "semantic": semantic_json,
                        "value": "x",
                    }
                ],
            },
        ),
        (
            "/v1/redactions",
            {"object_type": "record", "object_id": str(record.id), "reason": "test"},
        ),
        (
            "/v1/erasures",
            {"subject_id": str(other), "reason": "test"},
        ),
        (
            "/v1/bundle/import",
            other_bundle.model_dump(mode="json"),
        ),
    ]
    for endpoint, payload in denied_posts:
        response = client.post(endpoint, json=payload, headers=headers)
        assert response.status_code == 403, (endpoint, response.text)

    assert (
        client.post(
            f"/v1/records/{record.id}/revise",
            json={
                "expected_revision": 1,
                "value": "new",
                "source_refs": [source_ref],
            },
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/v1/records/{record.id}/revalidate",
            json={
                "expected_revision": 1,
                "status": "current",
                "reason": "test",
            },
            headers=headers,
        ).status_code
        == 403
    )


def test_workload_authentication_fail_closed_paths(service, monkeypatch) -> None:
    headers = {
        "X-Service-Identity": "administrative-orchestrator",
        "X-Purpose": "audit",
    }

    monkeypatch.setenv("PERSONAL_WORLD_AUTH_MODE", "unsupported")
    with pytest.raises(RuntimeError, match="AUTH_MODE"):
        TestClient(create_app(service)).get("/v1/contracts", headers=headers)

    monkeypatch.setenv("PERSONAL_WORLD_AUTH_MODE", "insecure-local")
    monkeypatch.delenv("PERSONAL_WORLD_ALLOW_INSECURE_LOCAL", raising=False)
    with pytest.raises(RuntimeError, match="ALLOW_INSECURE_LOCAL"):
        TestClient(create_app(service)).get("/v1/contracts", headers=headers)

    monkeypatch.setenv("PERSONAL_WORLD_AUTH_MODE", "signed-hmac")
    monkeypatch.setenv(
        "PERSONAL_WORLD_WORKLOAD_HMAC_SECRETS_JSON",
        json.dumps({"administrative-orchestrator": "secret"}),
    )
    client = TestClient(create_app(service))

    missing = client.get("/v1/contracts", headers=headers)
    assert missing.status_code == 401

    invalid_time = client.get(
        "/v1/contracts",
        headers={
            **headers,
            "X-Workload-Timestamp": "not-a-number",
            "X-Workload-Signature": "bad",
        },
    )
    assert invalid_time.status_code == 401

    timestamp = str(int(time.time()))
    invalid_signature = client.get(
        "/v1/contracts",
        headers={
            **headers,
            "X-Workload-Timestamp": timestamp,
            "X-Workload-Signature": "bad",
        },
    )
    assert invalid_signature.status_code == 401

    unknown = client.get(
        "/v1/contracts",
        headers={
            "X-Service-Identity": "unknown-service",
            "X-Purpose": "audit",
            "X-Workload-Timestamp": timestamp,
            "X-Workload-Signature": "bad",
        },
    )
    assert unknown.status_code == 401
