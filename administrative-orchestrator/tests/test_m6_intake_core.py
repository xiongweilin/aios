from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from administrative_orchestrator.domain import AdministrativeRequest
from administrative_orchestrator.intake.models import (
    AssessmentAuthority,
    CandidateAdministrativeRequest,
    CandidateAuthority,
    CandidateCaseUpdate,
    CandidateFactAssertion,
    CandidateStatus,
    EvidenceSpan,
    IntakeAssessment,
    IntakeDisposition,
    IntakeReceipt,
    IntakeVerificationStatus,
    InterpretationRecord,
    PromotionRecord,
    SourceArtifact,
)
from administrative_orchestrator.intake.repository import (
    CandidateAdministrativeRequestRow,
    CandidateConflict,
    IntakeReceiptConflict,
    IntakeRepository,
    PromotionConflict,
    SourceArtifactConflict,
)
from administrative_orchestrator.onboarding_admission import (
    CandidateOnboardingAdmissionService,
    OnboardingAdmissionError,
)
from administrative_orchestrator.persistence import SqlStore


def _artifact() -> SourceArtifact:
    return SourceArtifact(
        source_kind="message",
        source_system="test-provider",
        tenant_ref="tenant:test",
        canonical_source_ref="thread:1/message:1",
        source_event_ref="event:1",
        content_digest="a" * 64,
        storage_ref="filesystem://sha256/" + "a" * 64,
        mime_type="text/plain",
        size=12,
        authenticity_class="provider_verified",
        retention_class="business_record",
    )


def _interpretation(artifact_ref, *, model_version: str) -> InterpretationRecord:
    return InterpretationRecord(
        artifact_refs=(artifact_ref,),
        interpretation_profile_ref="onboarding-request-v1",
        model_provider="test-model-gateway",
        model_identity="test-model",
        model_version=model_version,
        schema_ref="candidate-request-v1",
        structured_output={"intent": "onboard"},
        response_digest=f"digest-{model_version}",
    )


def test_candidate_authority_cannot_construct_authoritative_value() -> None:
    with pytest.raises(ValidationError):
        CandidateFactAssertion(
            fact_key="employee_ref",
            value="employee:1",
            authority="authoritative",
            source_refs=(uuid4(),),
            evidence_span_refs=(uuid4(),),
        )


def test_candidate_fact_requires_evidence_or_explicit_gap_reason() -> None:
    with pytest.raises(ValidationError):
        CandidateFactAssertion(
            fact_key="start_date",
            value="2026-09-15",
            authority=CandidateAuthority.CLAIM,
            source_refs=(uuid4(),),
        )

    fact = CandidateFactAssertion(
        fact_key="start_date",
        value="2026-09-15",
        authority=CandidateAuthority.CLAIM,
        source_refs=(uuid4(),),
        no_evidence_reason="The source is available but the parser has no stable locator yet.",
    )
    assert fact.evidence_span_refs == ()


def test_model_suggestion_cannot_be_final_assessment() -> None:
    with pytest.raises(ValidationError):
        IntakeAssessment(
            candidate_ref=uuid4(),
            disposition=IntakeDisposition.ADMIT,
            authority=AssessmentAuthority.MODEL_SUGGESTION,
            is_final=True,
            basis={"confidence": 0.99},
        )


def test_receipt_artifact_and_interpretations_are_idempotent_or_append_only() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    repository = IntakeRepository(store)

    receipt = IntakeReceipt(
        source_system="test-provider",
        tenant_ref="tenant:test",
        source_event_id="event:1",
        verification_status=IntakeVerificationStatus.VERIFIED,
        delivery_digest="delivery-digest",
    )
    first_receipt = repository.persist_intake_receipt(receipt)
    duplicate_receipt = repository.persist_intake_receipt(receipt.model_copy(update={"receipt_id": uuid4()}))
    assert duplicate_receipt.receipt_id == first_receipt.receipt_id

    with pytest.raises(IntakeReceiptConflict):
        repository.persist_intake_receipt(
            receipt.model_copy(update={"receipt_id": uuid4(), "delivery_digest": "different"})
        )

    artifact = _artifact()
    first_artifact = repository.append_source_artifact(artifact)
    duplicate_artifact = repository.append_source_artifact(artifact.model_copy(update={"artifact_id": uuid4()}))
    assert duplicate_artifact.artifact_id == first_artifact.artifact_id

    with pytest.raises(SourceArtifactConflict):
        repository.append_source_artifact(
            artifact.model_copy(update={"artifact_id": uuid4(), "content_digest": "b" * 64})
        )

    interpretation_v1 = repository.append_interpretation(
        _interpretation(artifact.artifact_id, model_version="v1")
    )
    interpretation_v2 = repository.append_interpretation(
        _interpretation(artifact.artifact_id, model_version="v2")
    )
    assert interpretation_v1.interpretation_id != interpretation_v2.interpretation_id
    assert {item.model_version for item in repository.list_interpretations(artifact.artifact_id)} == {
        "v1",
        "v2",
    }


def test_all_candidate_core_records_persist_without_authority_promotion() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    repository = IntakeRepository(store)
    artifact = repository.append_source_artifact(_artifact())
    span = repository.append_evidence_span(
        EvidenceSpan(
            artifact_ref=artifact.artifact_id,
            representation_digest=artifact.content_digest,
            locator_kind="message_body",
            locator={"char_start": 0, "char_end": 12},
            extractor_ref="test-extractor-v1",
        )
    )
    interpretation = repository.append_interpretation(
        _interpretation(artifact.artifact_id, model_version="v1")
    )
    fact = repository.append_candidate_fact(
        CandidateFactAssertion(
            fact_key="employee_ref",
            value="employee:1",
            authority=CandidateAuthority.CLAIM,
            interpretation_ref=interpretation.interpretation_id,
            source_refs=(artifact.artifact_id,),
            evidence_span_refs=(span.evidence_span_id,),
        )
    )
    candidate = repository.append_candidate_request(
        CandidateAdministrativeRequest(
            conversation_ref="test-provider/tenant:test/thread:1",
            interpretation_refs=(interpretation.interpretation_id,),
            candidate_requester="external:person:1",
            candidate_intent="onboard employee:1",
            candidate_fact_refs=(fact.candidate_fact_id,),
            source_refs=(artifact.artifact_id,),
        )
    )

    from administrative_orchestrator.domain import AdministrativeCase

    case_id = uuid4()
    request = AdministrativeRequest(
        requester_principal_id="person:reviewer",
        channel="intake",
        intent="onboard employee:1",
    )
    store.create_case(
        request,
        AdministrativeCase(
            case_id=case_id,
            case_kind="employee-onboarding",
            requester_principal_id=request.requester_principal_id,
            subject_ref="employee:1",
        ),
    )
    update = repository.append_case_update(
        CandidateCaseUpdate(
            case_id=case_id,
            conversation_ref="test-provider/tenant:test/thread:1",
            interpretation_refs=(interpretation.interpretation_id,),
            candidate_fact_refs=(fact.candidate_fact_id,),
            source_refs=(artifact.artifact_id,),
        )
    )
    assessment = repository.append_assessment(
        IntakeAssessment(
            candidate_ref=candidate.candidate_id,
            disposition=IntakeDisposition.REQUIRES_HUMAN_REVIEW,
            authority=AssessmentAuthority.MODEL_SUGGESTION,
            basis={"suggested": True},
        )
    )

    from administrative_orchestrator.intake.repository import (
        CandidateAdministrativeRequestRow,
        CandidateCaseUpdateRow,
        CandidateFactAssertionRow,
        EvidenceSpanRow,
        IntakeAssessmentRow,
        InterpretationRecordRow,
        SourceArtifactRow,
    )

    with store.sessions() as db:
        assert db.get(SourceArtifactRow, artifact.artifact_id) is not None
        assert db.get(EvidenceSpanRow, span.evidence_span_id) is not None
        assert db.get(InterpretationRecordRow, interpretation.interpretation_id) is not None
        assert db.get(CandidateFactAssertionRow, fact.candidate_fact_id) is not None
        assert db.get(CandidateAdministrativeRequestRow, candidate.candidate_id) is not None
        assert db.get(CandidateCaseUpdateRow, update.candidate_update_id) is not None
        assert db.get(IntakeAssessmentRow, assessment.assessment_id) is not None


def test_candidate_fact_replay_ignores_only_creation_timestamp() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    repository = IntakeRepository(store)
    artifact = repository.append_source_artifact(_artifact())
    span = repository.append_evidence_span(
        EvidenceSpan(
            artifact_ref=artifact.artifact_id,
            representation_digest=artifact.content_digest,
            locator_kind="message_body",
            locator={"char_start": 0, "char_end": 12},
            extractor_ref="test-extractor-v1",
        )
    )
    fact = CandidateFactAssertion(
        fact_key="employee_ref",
        value="employee:1",
        authority=CandidateAuthority.CLAIM,
        source_refs=(artifact.artifact_id,),
        evidence_span_refs=(span.evidence_span_id,),
    )
    first = repository.append_candidate_fact(fact)
    replay = repository.append_candidate_fact(
        fact.model_copy(update={"created_at": fact.created_at + timedelta(seconds=1)})
    )

    assert replay == first
    assert repository.get_candidate_fact(first.candidate_fact_id) == first


def test_candidate_replay_ignores_mutated_admission_status() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    repository = IntakeRepository(store)
    candidate = CandidateAdministrativeRequest(
        conversation_ref="test-provider/tenant:test/thread:1",
        interpretation_refs=(uuid4(),),
        candidate_requester="external:person:1",
        candidate_intent="onboard employee:1",
        source_refs=(uuid4(),),
    )
    first = repository.append_candidate_request(candidate)
    with store.sessions.begin() as db:
        row = db.get(CandidateAdministrativeRequestRow, first.candidate_id)
        assert row is not None
        row.status = CandidateStatus.ADMITTED.value

    replay = repository.append_candidate_request(candidate)
    assert replay.status is CandidateStatus.ADMITTED
    assert replay == first.model_copy(update={"status": CandidateStatus.ADMITTED})

    with pytest.raises(CandidateConflict):
        repository.append_candidate_request(
            candidate.model_copy(update={"candidate_intent": "different intent"})
        )


def test_onboarding_bridge_rejects_invalid_facts_before_creating_state() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    repository = IntakeRepository(store)
    artifact = repository.append_source_artifact(_artifact())
    fact = repository.append_candidate_fact(
        CandidateFactAssertion(
            fact_key="employee_id",
            value="employee:1",
            authority=CandidateAuthority.CLAIM,
            source_refs=(artifact.artifact_id,),
            no_evidence_reason="staging regression fixture",
        )
    )
    candidate = repository.append_candidate_request(
        CandidateAdministrativeRequest(
            conversation_ref="test-provider/tenant:test/thread:1",
            interpretation_refs=(uuid4(),),
            candidate_requester="external:person:1",
            candidate_intent="onboard employee:1",
            candidate_fact_refs=(fact.candidate_fact_id,),
            source_refs=(artifact.artifact_id,),
        )
    )
    assessment = IntakeAssessment(
        candidate_ref=candidate.candidate_id,
        disposition=IntakeDisposition.ADMIT,
        authority=AssessmentAuthority.HUMAN_REVIEW,
        is_final=True,
        reviewer_principal_id="person:reviewer",
        basis={"reviewed": True},
    )
    service = CandidateOnboardingAdmissionService(store, repository)
    with pytest.raises(OnboardingAdmissionError):
        service.promote_and_evaluate(
            candidate,
            assessment,
            source_system="test-provider",
            tenant_ref="tenant:test",
            source_event_id="event:1",
            requester_principal_id="person:reviewer",
            subject_ref="employee:1",
        )
    assert repository.get_promotion(candidate.candidate_id) is None
    with store.sessions() as db:
        assert db.execute(text("select count(*) from administrative_case")).scalar_one() == 0
        assert db.execute(text("select count(*) from administrative_request")).scalar_one() == 0


def test_promotion_is_idempotent_per_candidate_and_request() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    repository = IntakeRepository(store)

    request = AdministrativeRequest(
        requester_principal_id="person:reviewer",
        channel="intake",
        intent="onboard employee:1",
    )
    case_id = uuid4()
    # The existing M5 schema requires the request row before a promotion FK
    # can be persisted; use the store's normal request/case writer below.
    from administrative_orchestrator.domain import AdministrativeCase

    store.create_case(
        request,
        AdministrativeCase(
            case_kind="employee-onboarding",
            requester_principal_id=request.requester_principal_id,
            subject_ref="employee:1",
            case_id=case_id,
        ),
    )
    candidate = CandidateAdministrativeRequest(
        conversation_ref="test-provider/tenant:test/thread:1",
        interpretation_refs=(uuid4(),),
        candidate_requester="external:person:1",
        candidate_intent="onboard employee:1",
        source_refs=(uuid4(),),
    )
    assessment = IntakeAssessment(
        candidate_ref=candidate.candidate_id,
        disposition=IntakeDisposition.ADMIT,
        authority=AssessmentAuthority.HUMAN_REVIEW,
        is_final=True,
        reviewer_principal_id="person:reviewer",
        basis={"reviewed": True},
    )
    promotion = PromotionRecord(
        candidate_ref=candidate.candidate_id,
        assessment_ref=assessment.assessment_id,
        request_id=request.request_id,
        ingress_receipt_ref="test-provider/event:1",
        promotion_policy_ref="m6-human-confirmed-v1",
    )
    first = repository.persist_promotion(promotion)
    duplicate = repository.persist_promotion(promotion.model_copy(update={"promotion_id": uuid4()}))
    assert duplicate.promotion_id == first.promotion_id

    with pytest.raises(PromotionConflict):
        repository.persist_promotion(
            promotion.model_copy(update={"promotion_id": uuid4(), "assessment_ref": uuid4()})
        )
