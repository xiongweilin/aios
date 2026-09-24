from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

import administrative_orchestrator.api as api
from administrative_orchestrator.access_policy import AdministrativeAccessPolicy
from administrative_orchestrator.authority import AuthorityRepository
from administrative_orchestrator.bootstrap_foundation import bootstrap_foundation
from administrative_orchestrator.domain import (
    AdministrativeRequest,
    FactSnapshot,
    Principal,
    RoleAssignment,
)
from administrative_orchestrator.execution_repository import ExecutionRepository
from administrative_orchestrator.obligations import ObligationRepository
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.policy import OnboardingFacts, OnboardingPolicy
from administrative_orchestrator.policy_plane import default_onboarding_policy_version
from administrative_orchestrator.service import (
    apply_policy_evaluation,
    create_case,
    start_policy_evaluation,
)
from administrative_orchestrator.unit_of_work import AdministrativeUnitOfWork

SECRET = "agency-console-secret"


def _signed(method: str, path: str, body: bytes = b"") -> dict[str, str]:
    timestamp = str(int(time.time()))
    digest = hashlib.sha256(body).hexdigest()
    canonical = f"{timestamp}\n{method}\n{path}\n{digest}".encode()
    return {
        "X-Agency-Console-Timestamp": timestamp,
        "X-Agency-Console-Signature": hmac.new(
            SECRET.encode(), canonical, hashlib.sha256
        ).hexdigest(),
    }


def _client(monkeypatch) -> tuple[TestClient, object]:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    bootstrap_foundation(store)
    authority = AuthorityRepository(store)
    authority.put_principal(Principal(principal_id="person:hr", display_name="HR"))
    authority.put_role_assignment(
        RoleAssignment(
            principal_id="person:hr",
            role="hr_approver",
            organization_scope="department:engineering",
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )

    facts = OnboardingFacts(
        employee_ref="employee:new",
        department_ref="department:engineering",
        manager_principal_id="person:manager",
        start_date="2026-09-15",
        employment_type="full-time",
    )
    request = AdministrativeRequest(
        requester_principal_id="person:requester",
        channel="test",
        intent="onboard employee:new",
    )
    case = create_case(
        request,
        case_kind="employee-onboarding",
        subject_ref="employee:new",
        fact_snapshot=FactSnapshot(
            source="ingress:test",
            owner="administrative-orchestrator",
            observed_at=datetime(2026, 9, 22, tzinfo=UTC),
            facts=facts.model_dump(mode="json"),
        ),
    )
    store.create_case(request, case)
    ready = start_policy_evaluation(case)
    policy = default_onboarding_policy_version()
    evaluation = OnboardingPolicy(policy.policy_ref).evaluate(facts)
    awaiting = apply_policy_evaluation(ready, evaluation)
    AdministrativeUnitOfWork(store).apply_policy_transition(case, awaiting, evaluation)

    monkeypatch.setenv("ADMIN_AGENCY_CONSOLE_SHARED_SECRET", SECRET)
    monkeypatch.setattr(api, "_store", store)
    monkeypatch.setattr(api, "_uow", AdministrativeUnitOfWork(store))
    monkeypatch.setattr(api, "_execution", ExecutionRepository(store))
    monkeypatch.setattr(api, "_authority", authority)
    monkeypatch.setattr(api, "_access", AdministrativeAccessPolicy(authority))
    monkeypatch.setattr(api, "_obligations", ObligationRepository(store))
    return TestClient(api.app), awaiting


def test_agency_console_v2_disposition_uses_case_version_and_replays(monkeypatch) -> None:
    client, awaiting = _client(monkeypatch)
    case_id = awaiting.case_id
    proposal_path = f"/v1/agency-console/cases/{case_id}/proposal"
    proposal = client.get(proposal_path, headers=_signed("GET", proposal_path))
    assert proposal.status_code == 200
    payload = proposal.json()["proposal"]
    assert payload["expectedStateVersion"] == str(awaiting.version)
    assert payload["commandBinding"]["commandName"] == "case.disposition"

    gesture_id = uuid4()
    disposition_path = f"/v1/agency-console/cases/{case_id}/dispositions"
    body = json.dumps(
        {
            "gestureId": str(gesture_id),
            "principalRef": "person:hr",
            "proposalRef": payload["proposalRef"],
            "proposalVersion": payload["proposalVersion"],
            "expectedStateVersion": payload["expectedStateVersion"],
            "disposition": "approved",
            "occurredAt": "2026-09-22T00:00:00Z",
        },
        separators=(",", ":"),
    ).encode()
    accepted = client.post(
        disposition_path,
        content=body,
        headers={**_signed("POST", disposition_path, body), "content-type": "application/json"},
    )
    assert accepted.status_code == 200
    receipt = accepted.json()
    assert receipt["accepted"] is True
    assert receipt["authoritativeRef"] == str(gesture_id)

    projection_path = f"/v1/agency-console/cases/{case_id}/projection"
    projection = client.get(projection_path, headers=_signed("GET", projection_path))
    assert projection.status_code == 200
    assert any(
        item["decision_id"] == str(gesture_id) for item in projection.json()["decisions"]
    )

    replay = client.post(
        disposition_path,
        content=body,
        headers={**_signed("POST", disposition_path, body), "content-type": "application/json"},
    )
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True


def test_agency_console_v2_rejects_stale_case_version(monkeypatch) -> None:
    client, awaiting = _client(monkeypatch)
    case_id = awaiting.case_id
    path = f"/v1/agency-console/cases/{case_id}/dispositions"
    body = json.dumps(
        {
            "gestureId": str(uuid4()),
            "principalRef": "person:hr",
            "proposalRef": f"administrative:case:{case_id}:decision",
            "proposalVersion": str(awaiting.version - 1),
            "expectedStateVersion": str(awaiting.version - 1),
            "disposition": "approved",
            "occurredAt": "2026-09-22T00:00:00Z",
        },
        separators=(",", ":"),
    ).encode()
    response = client.post(
        path,
        content=body,
        headers={**_signed("POST", path, body), "content-type": "application/json"},
    )
    assert response.status_code == 409


def test_agency_console_transport_auth_fails_closed(monkeypatch) -> None:
    client, awaiting = _client(monkeypatch)
    path = f"/v1/agency-console/cases/{awaiting.case_id}/proposal"

    missing = client.get(path)
    assert missing.status_code == 401

    invalid_time = client.get(
        path,
        headers={
            "X-Agency-Console-Timestamp": "not-a-number",
            "X-Agency-Console-Signature": "bad",
        },
    )
    assert invalid_time.status_code == 401

    expired_time = str(int(time.time()) - 600)
    expired = client.get(
        path,
        headers={
            "X-Agency-Console-Timestamp": expired_time,
            "X-Agency-Console-Signature": "bad",
        },
    )
    assert expired.status_code == 401

    now = str(int(time.time()))
    bad_signature = client.get(
        path,
        headers={
            "X-Agency-Console-Timestamp": now,
            "X-Agency-Console-Signature": "bad",
        },
    )
    assert bad_signature.status_code == 401

    monkeypatch.delenv("ADMIN_AGENCY_CONSOLE_SHARED_SECRET", raising=False)
    unconfigured = client.get(
        path,
        headers={
            "X-Agency-Console-Timestamp": now,
            "X-Agency-Console-Signature": "bad",
        },
    )
    assert unconfigured.status_code == 503


def test_agency_console_reject_path_is_domain_admitted(monkeypatch) -> None:
    client, awaiting = _client(monkeypatch)
    case_id = awaiting.case_id
    proposal_path = f"/v1/agency-console/cases/{case_id}/proposal"
    proposal = client.get(proposal_path, headers=_signed("GET", proposal_path)).json()["proposal"]

    disposition_path = f"/v1/agency-console/cases/{case_id}/dispositions"
    body = json.dumps(
        {
            "gestureId": str(uuid4()),
            "principalRef": "person:hr",
            "proposalRef": proposal["proposalRef"],
            "proposalVersion": proposal["proposalVersion"],
            "expectedStateVersion": proposal["expectedStateVersion"],
            "disposition": "rejected",
            "occurredAt": "2026-09-22T00:00:00Z",
        },
        separators=(",", ":"),
    ).encode()
    response = client.post(
        disposition_path,
        content=body,
        headers={**_signed("POST", disposition_path, body), "content-type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["accepted"] is True


def test_agency_console_gesture_reuse_with_different_meaning_is_rejected(monkeypatch) -> None:
    client, awaiting = _client(monkeypatch)
    case_id = awaiting.case_id
    proposal_path = f"/v1/agency-console/cases/{case_id}/proposal"
    proposal = client.get(proposal_path, headers=_signed("GET", proposal_path)).json()["proposal"]
    disposition_path = f"/v1/agency-console/cases/{case_id}/dispositions"
    gesture_id = str(uuid4())

    original = {
        "gestureId": gesture_id,
        "principalRef": "person:hr",
        "proposalRef": proposal["proposalRef"],
        "proposalVersion": proposal["proposalVersion"],
        "expectedStateVersion": proposal["expectedStateVersion"],
        "disposition": "approved",
        "occurredAt": "2026-09-22T00:00:00Z",
    }
    raw = json.dumps(original, separators=(",", ":")).encode()
    first = client.post(
        disposition_path,
        content=raw,
        headers={**_signed("POST", disposition_path, raw), "content-type": "application/json"},
    )
    assert first.status_code == 200

    conflicting = {**original, "disposition": "rejected"}
    conflicting_raw = json.dumps(conflicting, separators=(",", ":")).encode()
    replay = client.post(
        disposition_path,
        content=conflicting_raw,
        headers={
            **_signed("POST", disposition_path, conflicting_raw),
            "content-type": "application/json",
        },
    )
    assert replay.status_code == 409


def test_agency_console_unknown_case_and_principal_fail_closed(monkeypatch) -> None:
    client, awaiting = _client(monkeypatch)
    missing_case = uuid4()
    missing_path = f"/v1/agency-console/cases/{missing_case}/proposal"
    assert client.get(missing_path, headers=_signed("GET", missing_path)).status_code == 404

    case_id = awaiting.case_id
    path = f"/v1/agency-console/cases/{case_id}/dispositions"
    body = json.dumps(
        {
            "gestureId": str(uuid4()),
            "principalRef": "person:missing",
            "proposalRef": f"administrative:case:{case_id}:decision",
            "proposalVersion": str(awaiting.version),
            "expectedStateVersion": str(awaiting.version),
            "disposition": "approved",
            "occurredAt": "2026-09-22T00:00:00Z",
        },
        separators=(",", ":"),
    ).encode()
    response = client.post(
        path,
        content=body,
        headers={**_signed("POST", path, body), "content-type": "application/json"},
    )
    assert response.status_code == 403
