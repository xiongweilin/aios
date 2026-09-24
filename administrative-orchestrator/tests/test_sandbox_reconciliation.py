from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from administrative_orchestrator import sandbox


@pytest.fixture
def sandbox_client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    test_store = sandbox.SandboxStore(f"sqlite+pysqlite:///{tmp_path / 'sandbox.db'}")
    test_store.init_schema()
    monkeypatch.setattr(sandbox, "store", test_store)
    with TestClient(sandbox.app) as client:
        yield client
    test_store.engine.dispose()


def _effect_body(*, request_ref: str | None) -> dict[str, object]:
    return {
        "target_system": "hris",
        "operation": "employee.create",
        "subject_ref": "employee:test-reconciliation",
        "payload": {
            "employee_ref": "employee:test-reconciliation",
            "department_ref": "department:engineering",
        },
        "request_ref": request_ref,
    }


def test_request_binding_survives_readback_without_reapplying_effect(
    sandbox_client: TestClient,
) -> None:
    effect_id = uuid4()
    request_ref = "request_domain_effect_test_reconciliation"
    applied = sandbox_client.put(
        f"/v1/effects/{effect_id}",
        json=_effect_body(request_ref=request_ref),
    )
    assert applied.status_code == 200

    observed = sandbox_client.get(f"/v1/effects/{effect_id}")
    reconciled = sandbox_client.get(f"/v1/reconciliation/effects/{request_ref}")
    assert observed.status_code == 200
    assert reconciled.status_code == 200
    assert observed.json()["request_ref"] == request_ref
    assert reconciled.json()["request_ref"] == request_ref
    assert reconciled.json()["provider_ref"] == f"sandbox:{effect_id}"
    assert reconciled.json()["apply_attempts"] == 1
    assert reconciled.json()["state"] == observed.json()["state"]

    reconciled_again = sandbox_client.get(f"/v1/reconciliation/effects/{request_ref}")
    assert reconciled_again.status_code == 200
    assert reconciled_again.json()["apply_attempts"] == 1


def test_idempotent_apply_keeps_same_request_binding_and_counts_physical_attempts(
    sandbox_client: TestClient,
) -> None:
    effect_id = uuid4()
    request_ref = "request_domain_effect_replayed"
    body = _effect_body(request_ref=request_ref)
    assert sandbox_client.put(f"/v1/effects/{effect_id}", json=body).status_code == 200
    assert sandbox_client.put(f"/v1/effects/{effect_id}", json=body).status_code == 200

    observation = sandbox_client.get(f"/v1/reconciliation/effects/{request_ref}")
    assert observation.status_code == 200
    assert observation.json()["request_ref"] == request_ref
    assert observation.json()["apply_attempts"] == 2


def test_request_ref_cannot_rebind_to_another_realized_effect(
    sandbox_client: TestClient,
) -> None:
    request_ref = "request_domain_effect_fixed"
    first = uuid4()
    second = uuid4()
    assert sandbox_client.put(
        f"/v1/effects/{first}",
        json=_effect_body(request_ref=request_ref),
    ).status_code == 200

    rebound = sandbox_client.put(
        f"/v1/effects/{second}",
        json=_effect_body(request_ref=request_ref),
    )
    assert rebound.status_code == 409
    assert rebound.json()["detail"] == "request ref already bound to a different realized effect"
    assert sandbox_client.get(f"/v1/effects/{second}").status_code == 404


def test_realized_effect_cannot_rebind_to_another_request_ref(
    sandbox_client: TestClient,
) -> None:
    effect_id = uuid4()
    assert sandbox_client.put(
        f"/v1/effects/{effect_id}",
        json=_effect_body(request_ref="request:first"),
    ).status_code == 200

    rebound = sandbox_client.put(
        f"/v1/effects/{effect_id}",
        json=_effect_body(request_ref="request:second"),
    )
    assert rebound.status_code == 409
    assert rebound.json()["detail"] == "realized effect already bound to a different request ref"

    observation = sandbox_client.get(f"/v1/effects/{effect_id}")
    assert observation.status_code == 200
    assert observation.json()["request_ref"] == "request:first"
    assert observation.json()["apply_attempts"] == 1


def test_missing_blank_and_optional_request_refs_are_fail_closed_or_compatible(
    sandbox_client: TestClient,
) -> None:
    missing = sandbox_client.get("/v1/reconciliation/effects/request:missing")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "request ref not found"

    blank_effect = uuid4()
    blank = sandbox_client.put(
        f"/v1/effects/{blank_effect}",
        json=_effect_body(request_ref="   "),
    )
    assert blank.status_code == 422
    assert blank.json()["detail"] == "request_ref must not be blank"

    legacy_effect = uuid4()
    legacy_body = _effect_body(request_ref=None)
    applied = sandbox_client.put(f"/v1/effects/{legacy_effect}", json=legacy_body)
    assert applied.status_code == 200
    observed = sandbox_client.get(f"/v1/effects/{legacy_effect}")
    assert observed.status_code == 200
    assert observed.json()["request_ref"] is None
    assert observed.json()["apply_attempts"] == 1
