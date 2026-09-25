from __future__ import annotations

from uuid import uuid4

import pytest

from administrative_orchestrator.admission import IntakeAssessmentService
from administrative_orchestrator.domain import CaseStatus, FactAuthority
from administrative_orchestrator.intake.models import (
    CandidateAdministrativeRequest,
    CandidateAuthority,
    CandidateFactAssertion,
    IntakeAssessment,
    IntakeDisposition,
    IntakeReceipt,
    IntakeVerificationStatus,
)
from administrative_orchestrator.intake.repository import (
    CandidateAdministrativeRequestRow,
    IntakeRepository,
)
from administrative_orchestrator.offboarding_admission import (
    CandidateOffboardingAdmissionService,
    OffboardingAdmissionError,
)
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.policy import PolicyDisposition
from administrative_orchestrator.policy_plane import (
    PolicyRepository,
    default_offboarding_policy_version,
)


def _setup() -> tuple[SqlStore, IntakeRepository, CandidateAdministrativeRequest]:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    repository = IntakeRepository(store)
    PolicyRepository(store).put_version(default_offboarding_policy_version())
    candidate = repository.append_candidate_request(
        CandidateAdministrativeRequest(
            conversation_ref="provider/tenant/thread:1",
            interpretation_refs=(uuid4(),),
            candidate_requester="external:actor:1",
            candidate_intent="offboard employee:1",
            source_refs=(uuid4(),),
        )
    )
    repository.persist_intake_receipt(
        IntakeReceipt(
            source_system="test-provider",
            tenant_ref="tenant:test",
            source_event_id="event:1",
            verification_status=IntakeVerificationStatus.VERIFIED,
            artifact_ref=candidate.source_refs[0],
            delivery_digest="delivery:1",
        )
    )
    return store, repository, candidate


def _attach_candidate_facts(store, repository, candidate, facts):
    refs = []
    for fact_key, value in facts:
        fact = repository.append_candidate_fact(
            CandidateFactAssertion(
                fact_key=fact_key,
                value=value,
                authority=CandidateAuthority.CLAIM,
                source_refs=candidate.source_refs,
                no_evidence_reason="test source has no span for this contract fixture",
            )
        )
        refs.append(fact.candidate_fact_id)
    updated = candidate.model_copy(update={"candidate_fact_refs": tuple(refs)})
    with store.sessions.begin() as db:
        row = db.get(CandidateAdministrativeRequestRow, candidate.candidate_id)
        assert row is not None
        row.candidate_fact_refs_json = [str(ref) for ref in refs]
    return updated


def _final_admit(repository, candidate) -> IntakeAssessment:
    return IntakeAssessmentService(repository).finalize_human(
        candidate.candidate_id,
        IntakeDisposition.ADMIT,
        reviewer_principal_id="principal:reviewer",
        basis={"reviewed": True},
    )


def _promote(store, repository, candidate, assessment, subject_ref='employee:1'):
    return CandidateOffboardingAdmissionService(store, repository).promote_and_evaluate(
        candidate,
        assessment,
        source_system="test-provider",
        tenant_ref="tenant:test",
        source_event_id="event:1",
        requester_principal_id="principal:reviewer",
        subject_ref=subject_ref,
    )


def test_offboarding_bridge_keeps_claims_and_waits_for_authoritative_termination() -> None:
    store, repository, candidate = _setup()
    candidate = _attach_candidate_facts(
        store,
        repository,
        candidate,
        [
            ("employee_ref", "employee:1"),
            ("requested_termination_date", "2026-10-01"),
            ("requested_systems", ["synthetic-iam", "synthetic-hris"]),
        ],
    )
    assessment = _final_admit(repository, candidate)
    result = _promote(store, repository, candidate, assessment)

    assert result.case.case_kind == "employee-offboarding"
    assert result.case.subject_ref == "employee:1"
    assert result.case.status is CaseStatus.GATHERING_FACTS
    assert result.policy_evaluation.disposition is PolicyDisposition.NEED_MORE_FACTS
    assert set(result.policy_evaluation.missing_facts) == {
        "termination_status",
        "termination_effective_at",
    }
    snapshot = result.case.fact_snapshot
    assert snapshot is not None
    assert snapshot.authority is FactAuthority.CLAIM
    assert snapshot.facts["employee_ref"] == "employee:1"
    assert snapshot.facts["requested_termination_date"] == "2026-10-01"
    assert snapshot.facts["requested_systems"] == ["synthetic-iam", "synthetic-hris"]
    assert snapshot.facts["termination_status"] is None
    assert all(
        assertion.authority is FactAuthority.CLAIM
        for assertion in snapshot.assertions.values()
    )

    replay = _promote(store, repository, candidate, assessment)
    assert replay.created is False
    assert replay.case.case_id == result.case.case_id


def test_offboarding_bridge_rejects_authority_shaped_candidate_facts() -> None:
    store, repository, candidate = _setup()
    candidate = _attach_candidate_facts(
        store,
        repository,
        candidate,
        [
            ("employee_ref", "employee:1"),
            ("termination_status", "terminated"),
        ],
    )
    with pytest.raises(OffboardingAdmissionError, match='not allowed for offboarding'):
        CandidateOffboardingAdmissionService(store, repository)._candidate_facts(
            candidate, subject_ref="employee:1"
        )


def test_offboarding_bridge_requires_matching_selected_subject() -> None:
    store, repository, candidate = _setup()
    candidate = _attach_candidate_facts(
        store, repository, candidate, [('employee_ref', 'employee:1')]
    )
    with pytest.raises(OffboardingAdmissionError, match='does not match'):
        CandidateOffboardingAdmissionService(store, repository)._candidate_facts(
            candidate, subject_ref="employee:2"
        )


def test_offboarding_bridge_rejects_unknown_candidate_fact_keys() -> None:
    store, repository, candidate = _setup()
    candidate = _attach_candidate_facts(
        store, repository, candidate, [('department_ref', 'department:1')]
    )
    with pytest.raises(OffboardingAdmissionError, match='not allowed for offboarding'):
        CandidateOffboardingAdmissionService(store, repository)._candidate_facts(
            candidate, subject_ref="employee:1"
        )

