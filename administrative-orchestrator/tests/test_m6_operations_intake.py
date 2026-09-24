from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from administrative_orchestrator.access_policy import (
    AdministrativeAccessPolicy,
    AdministrativePermission,
)
from administrative_orchestrator.authority import AuthorityRepository
from administrative_orchestrator.domain import Principal, RoleAssignment
from administrative_orchestrator.intake.models import (
    CandidateAdministrativeRequest,
    IntakeReceipt,
    IntakeVerificationStatus,
)
from administrative_orchestrator.intake.repository import IntakeRepository
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.policy_plane import (
    PolicyRepository,
    default_onboarding_policy_version,
)
from administrative_orchestrator.unit_of_work import AdministrativeUnitOfWork


def _store_and_candidate() -> tuple[SqlStore, IntakeRepository, CandidateAdministrativeRequest]:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    PolicyRepository(store).put_version(default_onboarding_policy_version())
    repository = IntakeRepository(store)
    candidate = repository.append_candidate_request(
        CandidateAdministrativeRequest(
            conversation_ref="test-provider/tenant:test/thread:1",
            interpretation_refs=(uuid4(),),
            candidate_requester="external:alice",
            candidate_intent="onboard employee:1",
            source_refs=(uuid4(),),
        )
    )
    repository.persist_intake_receipt(
        IntakeReceipt(
            source_system="test-provider",
            tenant_ref="tenant:test",
            source_event_id="event:review",
            verification_status=IntakeVerificationStatus.VERIFIED,
            delivery_digest="delivery:review",
        )
    )
    return store, repository, candidate


@pytest.fixture
def intake_console(monkeypatch: pytest.MonkeyPatch):
    from administrative_orchestrator import operations_api
    from administrative_orchestrator.auth import AuthenticatedPrincipal

    store, repository, candidate = _store_and_candidate()
    actor = AuthenticatedPrincipal(
        principal=Principal(principal_id="person:reviewer", display_name="Reviewer"),
        auth_mode="test",
        external_subject="external:reviewer",
    )
    monkeypatch.setattr(operations_api, "_store", store)
    monkeypatch.setattr(operations_api, "_policies", PolicyRepository(store))
    monkeypatch.setattr(operations_api, "_uow", AdministrativeUnitOfWork(store))
    monkeypatch.setattr(operations_api, "_intake", repository)
    monkeypatch.setattr(
        operations_api,
        "_intake_assessments",
        operations_api.IntakeAssessmentService(repository),
    )
    monkeypatch.setattr(
        operations_api,
        "_intake_promotions",
        operations_api.IntakePromotionService(store, repository),
    )
    monkeypatch.setattr(operations_api, "_actor", lambda request: actor)
    monkeypatch.setattr(operations_api, "_require", lambda *args, **kwargs: None)
    return TestClient(operations_api.app), candidate


def test_intake_console_supports_review_and_human_confirmed_promotion(intake_console) -> None:
    client, candidate = intake_console

    queue = client.get("/v1/operations/intake/candidates")
    assert queue.status_code == 200
    assert queue.json()[0]["candidate_id"] == str(candidate.candidate_id)
    assert queue.json()[0]["latest_assessment"] is None

    detail = client.get(f"/v1/operations/intake/candidates/{candidate.candidate_id}")
    assert detail.status_code == 200
    assert detail.json()["assessments"] == []

    assessment_response = client.post(
        f"/v1/operations/intake/candidates/{candidate.candidate_id}/assessments",
        json={"disposition": "admit", "basis": {"reviewed": True}},
    )
    assert assessment_response.status_code == 200
    assessment = assessment_response.json()
    assert assessment["authority"] == "human_review"
    assert assessment["reviewer_principal_id"] == "person:reviewer"

    promotion_response = client.post(
        f"/v1/operations/intake/candidates/{candidate.candidate_id}/promote",
        json={
            "assessment_id": assessment["assessment_id"],
            "source_system": "test-provider",
            "tenant_ref": "tenant:test",
            "source_event_id": "event:review",
            "requester_principal_id": "person:requester",
            "case_kind": "employee-onboarding",
            "subject_ref": "employee:1",
            "bridge_to_m5": True,
        },
    )
    assert promotion_response.status_code == 200
    promotion = promotion_response.json()
    assert promotion["created"] is True

    redelivery = client.post(
        f"/v1/operations/intake/candidates/{candidate.candidate_id}/promote",
        json={
            "assessment_id": assessment["assessment_id"],
            "source_system": "test-provider",
            "tenant_ref": "tenant:test",
            "source_event_id": "event:review",
            "requester_principal_id": "person:requester",
        },
    )
    assert redelivery.status_code == 200
    assert redelivery.json()["created"] is False

    admitted_queue = client.get(
        "/v1/operations/intake/candidates", params={"status": "admitted"}
    )
    assert admitted_queue.status_code == 200
    assert admitted_queue.json()[0]["status"] == "admitted"

    admitted_detail = client.get(
        f"/v1/operations/intake/candidates/{candidate.candidate_id}"
    )
    assert admitted_detail.status_code == 200
    assert (
        admitted_detail.json()["promotion"]["promotion_id"]
        == promotion["promotion"]["promotion_id"]
    )


def test_intake_review_permission_is_separate_from_operations_read() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    authority = AuthorityRepository(store)
    authority.put_principal(Principal(principal_id="person:operator", display_name="Operator"))
    authority.put_principal(Principal(principal_id="person:auditor", display_name="Auditor"))
    authority.put_role_assignment(
        RoleAssignment(
            principal_id="person:operator",
            role="administrative_operator",
            organization_scope="*",
        )
    )
    authority.put_role_assignment(
        RoleAssignment(
            principal_id="person:auditor",
            role="administrative_auditor",
            organization_scope="*",
        )
    )
    policy = AdministrativeAccessPolicy(authority)

    assert policy.allows("person:operator", AdministrativePermission.INTAKE_REVIEW)
    assert not policy.allows("person:auditor", AdministrativePermission.INTAKE_REVIEW)
    assert policy.allows("person:auditor", AdministrativePermission.OPERATIONS_READ)


def test_intake_console_rejects_missing_and_conflicting_review_inputs(intake_console) -> None:
    client, candidate = intake_console
    unknown = uuid4()

    assert client.get(f"/v1/operations/intake/candidates/{unknown}").status_code == 404
    assert (
        client.post(
            f"/v1/operations/intake/candidates/{unknown}/assessments",
            json={"disposition": "admit", "basis": {"reviewed": True}},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/v1/operations/intake/candidates/{unknown}/promote",
            json={
                "assessment_id": str(uuid4()),
                "source_system": "test-provider",
                "tenant_ref": "tenant:test",
                "source_event_id": "event:missing",
                "requester_principal_id": "person:requester",
            },
        ).status_code
        == 404
    )

    first = client.post(
        f"/v1/operations/intake/candidates/{candidate.candidate_id}/assessments",
        json={"disposition": "admit", "basis": {"reviewed": True}},
    )
    assert first.status_code == 200
    second = client.post(
        f"/v1/operations/intake/candidates/{candidate.candidate_id}/assessments",
        json={"disposition": "duplicate", "basis": {"reviewed": True}},
    )
    assert second.status_code == 409

    assert (
        client.post(
            f"/v1/operations/intake/candidates/{candidate.candidate_id}/promote",
            json={
                "assessment_id": str(uuid4()),
                "source_system": "test-provider",
                "tenant_ref": "tenant:test",
                "source_event_id": "event:missing-assessment",
                "requester_principal_id": "person:requester",
            },
        ).status_code
        == 404
    )
    failed_promotion = client.post(
        f"/v1/operations/intake/candidates/{candidate.candidate_id}/promote",
        json={
            "assessment_id": first.json()["assessment_id"],
            "source_system": "test-provider",
            "tenant_ref": "tenant:test",
            "source_event_id": "event:not-persisted",
            "requester_principal_id": "person:requester",
        },
    )
    assert failed_promotion.status_code == 409
