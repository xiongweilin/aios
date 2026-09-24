from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from autonomous_development.adapters.personal_world import (
    PersonalWorldBoundaryError,
    PersonalWorldProjectionClient,
)
from autonomous_development.domain.models import DevelopmentTarget, MutationPolicy


def _target() -> DevelopmentTarget:
    return DevelopmentTarget(
        id="personal-world",
        repository="github:xiongweilin/personal-world",
        default_branch="main",
        target_contract_revision="contracts-v1",
        active_objective_revision_id="objective:pw:1",
        mutation_policy=MutationPolicy(allowed_paths=("src/**", "tests/**")),
        current_release_id="release:pw:0.9",
    )


def test_development_target_maps_to_resource_link() -> None:
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
                    "kind": "resource-link",
                    "status": "candidate",
                    "resource_ref": "github:xiongweilin/personal-world",
                    "domain": "development",
                    "relation": "development-target",
                }
            ],
        )

    client = PersonalWorldProjectionClient(
        "http://personal-world.test",
        transport=httpx.MockTransport(handler),
    )
    result = client.project_target(
        uuid4(),
        _target(),
        observed_at=datetime(2026, 9, 22, tzinfo=UTC),
    )

    assert result[0]["kind"] == "resource-link"
    path, payload = calls[0]
    assert path == "/v1/domain-projections"
    assert payload["source_domain"] == "autonomous-development"
    claim = payload["claims"][0]
    assert claim["record_kind"] == "resource-link"
    assert claim["resource_ref"] == "github:xiongweilin/personal-world"
    assert claim["domain"] == "development"
    assert claim["relation"] == "development-target"
    client.close()


def test_personal_world_contract_drift_fails_closed() -> None:
    client = PersonalWorldProjectionClient(
        "http://personal-world.test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "manifest": "personal-world-contracts-v1",
                    "conformance": "personal-world-conformance-v2",
                    "package": "1.0.0",
                    "semantic_language": "0.2.0",
                },
            )
        ),
    )
    with pytest.raises(PersonalWorldBoundaryError, match="contract mismatch"):
        client.ensure_contracts()
    client.close()


@pytest.mark.integration
def test_real_personal_world_development_ingress() -> None:
    base_url = os.getenv("AUTODEV_PERSONAL_WORLD_TEST_URL")
    if not base_url:
        pytest.skip("real Personal World integration is not configured")

    client = PersonalWorldProjectionClient(base_url)
    result = client.project_target(uuid4(), _target())
    assert len(result) == 1
    assert result[0]["kind"] == "resource-link"
    assert result[0]["status"] == "candidate"
    assert result[0]["resource_ref"] == "github:xiongweilin/personal-world"
    assert result[0]["domain"] == "development"
    assert result[0]["relation"] == "development-target"
    client.close()


def test_personal_world_signed_workload_identity_is_purpose_bound() -> None:
    secret = "pw-workload-secret"
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        purpose = request.headers.get("X-Purpose", "")
        timestamp = request.headers.get("X-Workload-Timestamp", "")
        signature = request.headers.get("X-Workload-Signature", "")
        assert request.headers["X-Service-Identity"] == "autonomous-development"
        assert purpose in {"contract-discovery", "domain-projection"}
        assert timestamp
        expected = hmac.new(
            secret.encode(),
            f"autonomous-development\n{purpose}\n{timestamp}".encode(),
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
                    "kind": "resource-link",
                    "status": "candidate",
                    "resource_ref": "github:xiongweilin/personal-world",
                    "domain": "development",
                    "relation": "development-target",
                }
            ],
        )

    client = PersonalWorldProjectionClient(
        "http://personal-world.test",
        workload_secret=secret,
        transport=httpx.MockTransport(handler),
    )
    client.project_target(uuid4(), _target())
    assert seen == ["contract-discovery", "domain-projection"]
    client.close()

def test_personal_world_model_context_separates_current_from_revalidation() -> None:
    subject_id = uuid4()

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
        assert request.url.path == "/v1/model-context"
        payload = json.loads(request.content)
        assert payload["purpose"] == "development-requirement-analysis"
        assert payload["query"] == "Keep changes local"
        return httpx.Response(
            200,
            json={
                "purpose": "development-requirement-analysis",
                "query": "Keep changes local",
                "projection_ref": str(uuid4()),
                "included_items": [
                    {
                        "id": str(uuid4()),
                        "revision": 3,
                        "kind": "preference",
                        "semantic": {
                            "kind": "predicate",
                            "id": "change-style",
                            "namespace": "development",
                            "version": "0.1",
                        },
                        "value": {"preference": "small-diff"},
                        "status": "current",
                    }
                ],
                "unresolved_conflicts": [
                    {
                        "id": str(uuid4()),
                        "revision": 2,
                        "kind": "fact",
                        "semantic": {
                            "kind": "predicate",
                            "id": "repository",
                            "namespace": "development",
                            "version": "0.1",
                        },
                        "value": "conflicted",
                        "status": "contested",
                    }
                ],
                "stale_items": [],
                "unknowns": [],
                "excluded_count": 1,
                "source_refs": [],
            },
        )

    client = PersonalWorldProjectionClient(
        "http://personal-world.test",
        transport=httpx.MockTransport(handler),
    )
    context = client.model_context(
        subject_id,
        purpose="development-requirement-analysis",
        query="Keep changes local",
    )

    assert len(context.included_items) == 1
    assert len(context.blocked_items) == 1
    assert context.basis_refs[0].endswith("@3")
    assert context.revalidation_refs[0].endswith("@2")
    client.close()


def test_personal_world_revalidates_exact_record_revisions() -> None:
    subject_id = uuid4()
    record_id = uuid4()
    revision = {"value": 3}

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
        assert request.url.path == f"/v1/subjects/{subject_id}/current"
        assert request.headers["X-Purpose"] == "development-requirement-analysis"
        return httpx.Response(
            200,
            json=[
                {
                    "id": str(record_id),
                    "revision": revision["value"],
                    "status": "current",
                }
            ],
        )

    client = PersonalWorldProjectionClient(
        "http://personal-world.test",
        transport=httpx.MockTransport(handler),
    )
    basis = (f"personal-world:{record_id}@3",)
    client.revalidate(
        subject_id,
        purpose="development-requirement-analysis",
        basis_refs=basis,
    )

    revision["value"] = 4
    with pytest.raises(PersonalWorldBoundaryError, match="requires revalidation"):
        client.revalidate(
            subject_id,
            purpose="development-requirement-analysis",
            basis_refs=basis,
        )
    client.close()
