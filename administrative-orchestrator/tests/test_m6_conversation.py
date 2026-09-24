from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from administrative_orchestrator.admission import (
    IntakeAssessmentService,
    IntakePromotionService,
)
from administrative_orchestrator.authority import AuthorityRepository, IdentityBinding
from administrative_orchestrator.conversation import (
    CandidateSupersessionConflict,
    ConversationMessage,
    ConversationRef,
    ConversationService,
    IdentityResolutionError,
    OutOfOrderDelivery,
    ParticipantChanged,
    SenderSpoof,
    TenantMismatch,
)
from administrative_orchestrator.domain import Principal, utcnow
from administrative_orchestrator.intake.models import (
    CandidateAdministrativeRequest,
    CandidateStatus,
    IntakeDisposition,
    IntakeReceipt,
    IntakeVerificationStatus,
)
from administrative_orchestrator.intake.repository import IntakeRepository
from administrative_orchestrator.persistence import SqlStore


def _setup() -> tuple[SqlStore, ConversationService, ConversationRef]:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    authority = AuthorityRepository(store)
    authority.put_principal(Principal(principal_id="person:alice", display_name="Alice"))
    authority.put_principal(Principal(principal_id="person:bob", display_name="Bob"))
    binding_at = utcnow()
    authority.put_identity_binding(
        IdentityBinding(
            provider="test-provider",
            external_subject="external:alice",
            principal_id="person:alice",
            valid_from=binding_at,
        )
    )
    authority.put_identity_binding(
        IdentityBinding(
            provider="test-provider",
            external_subject="external:bob",
            principal_id="person:bob",
            valid_from=binding_at,
        )
    )
    ref = ConversationRef(
        provider="test-provider",
        tenant_ref="tenant:test",
        thread_ref="thread:1",
    )
    return store, ConversationService(store, authority=authority), ref


def _message(
    ref: ConversationRef,
    *,
    sequence: int,
    provider_message_id: str,
    sender: str = "external:alice",
    participants: tuple[str, ...] = ("external:alice",),
    source_refs: tuple[UUID, ...] = (),
    interpretation_refs: tuple[UUID, ...] = (),
    displayed_sender: str | None = None,
    claimed_sender_external_subject: str | None = None,
) -> ConversationMessage:
    return ConversationMessage(
        conversation_ref=ref,
        provider_message_id=provider_message_id,
        source_event_id=f"event:{provider_message_id}",
        sender_external_subject=sender,
        participant_external_subjects=participants,
        sequence=sequence,
        content_digest=f"digest:{provider_message_id}",
        source_refs=source_refs,
        interpretation_refs=interpretation_refs,
        displayed_sender=displayed_sender,
        claimed_sender_external_subject=claimed_sender_external_subject,
    )


def _candidate(
    ref: ConversationRef,
    *,
    candidate_id: UUID | None = None,
    supersedes: UUID | None = None,
) -> CandidateAdministrativeRequest:
    return CandidateAdministrativeRequest(
        candidate_id=candidate_id or uuid4(),
        conversation_ref=ref.canonical_ref,
        interpretation_refs=(uuid4(),),
        candidate_requester="external:alice",
        candidate_intent="onboard employee:1",
        source_refs=(uuid4(),),
        supersedes_candidate_ref=supersedes,
    )


def test_provider_identity_uses_binding_not_display_text() -> None:
    _, service, ref = _setup()

    resolved = service.resolve_provider_identity(
        ref,
        external_subject="external:alice",
        displayed_sender="person:bob",
    )
    assert resolved.principal_id == "person:alice"

    with pytest.raises(SenderSpoof):
        service.resolve_provider_identity(
            ref,
            external_subject="external:alice",
            claimed_sender_external_subject="external:bob",
        )
    with pytest.raises(IdentityResolutionError):
        service.resolve_provider_identity(ref, external_subject="external:unbound")


def test_tenant_mismatch_is_rejected_before_message_persistence() -> None:
    _, service, ref = _setup()

    with pytest.raises(TenantMismatch):
        service.accept_message(
            _message(ref, sequence=1, provider_message_id="message:1"),
            tenant_ref="tenant:other",
        )
    with pytest.raises(TenantMismatch):
        service.accept_message(
            _message(ref, sequence=1, provider_message_id="message:2").model_copy(
                update={"provider_tenant_ref": "tenant:other"}
            )
        )
    assert service.get_conversation(ref) is None


def test_conversation_sender_participants_and_delivery_order_are_stable() -> None:
    _, service, ref = _setup()
    first = _message(
        ref,
        sequence=1,
        provider_message_id="message:1",
        participants=("external:alice", "external:bob"),
    )
    assert service.accept_message(first).created is True
    assert service.accept_message(first).created is False

    with pytest.raises(ParticipantChanged):
        service.accept_message(
            _message(
                ref,
                sequence=2,
                provider_message_id="message:2",
                participants=("external:alice", "external:bob", "external:new"),
            )
        )
    with pytest.raises(ParticipantChanged):
        service.accept_message(
            _message(
                ref,
                sequence=2,
                provider_message_id="message:3",
                sender="external:bob",
                participants=("external:alice", "external:bob"),
            )
        )
    with pytest.raises(OutOfOrderDelivery):
        service.accept_message(
            _message(
                ref,
                sequence=1,
                provider_message_id="message:4",
                participants=("external:alice", "external:bob"),
            )
        )

    state = service.get_conversation(ref)
    assert state is not None
    assert state.last_sequence == 1
    assert len(service.list_messages(ref)) == 1


def test_provider_sequence_accepts_feishu_large_integer() -> None:
    _, service, ref = _setup()
    sequence = 1_789_020_305_342

    result = service.accept_message(
        _message(ref, sequence=sequence, provider_message_id="message:large-sequence")
    )

    assert result.created is True
    state = service.get_conversation(ref)
    assert state is not None
    assert state.last_sequence == sequence
    assert service.list_messages(ref)[0].sequence == sequence


def test_candidate_supersession_is_explicit_and_same_conversation_only() -> None:
    store, service, ref = _setup()
    repository = IntakeRepository(store)
    previous = _candidate(ref)
    repository.append_candidate_request(previous)
    replacement = _candidate(ref, supersedes=previous.candidate_id)

    assert service.supersede_candidate(previous.candidate_id, replacement) == replacement
    assert repository.get_candidate(previous.candidate_id).status is CandidateStatus.SUPERSEDED
    assert repository.get_candidate(replacement.candidate_id).status is CandidateStatus.ACTIVE

    other_ref = ConversationRef(
        provider="test-provider", tenant_ref="tenant:test", thread_ref="thread:other"
    )
    with pytest.raises(CandidateSupersessionConflict):
        service.supersede_candidate(previous.candidate_id, _candidate(other_ref, supersedes=previous.candidate_id))


def test_message_before_admission_then_after_admission_becomes_case_update() -> None:
    store, service, ref = _setup()
    repository = IntakeRepository(store)
    candidate = _candidate(ref)
    repository.append_candidate_request(candidate)
    source_ref = candidate.source_refs[0]
    interpretation_ref = candidate.interpretation_refs[0]

    before = service.accept_message(
        _message(
            ref,
            sequence=1,
            provider_message_id="message:before-admission",
            source_refs=(source_ref,),
            interpretation_refs=(interpretation_ref,),
        ),
        candidate=candidate,
    )
    assert before.candidate_ref == candidate.candidate_id
    assert before.case_update is None

    repository.persist_intake_receipt(
        IntakeReceipt(
            source_system="test-provider",
            tenant_ref="tenant:test",
            source_event_id="admission:event",
            verification_status=IntakeVerificationStatus.VERIFIED,
            delivery_digest="delivery:admission",
        )
    )
    assessment = IntakeAssessmentService(repository).finalize_human(
        candidate.candidate_id,
        IntakeDisposition.ADMIT,
        reviewer_principal_id="person:alice",
        basis={"reviewed": True},
    )
    promotion = IntakePromotionService(store, repository).promote(
        candidate,
        assessment,
        source_system="test-provider",
        tenant_ref="tenant:test",
        source_event_id="admission:event",
        requester_principal_id="person:alice",
    )

    after = service.accept_message(
        _message(
            ref,
            sequence=2,
            provider_message_id="message:after-admission",
            source_refs=(source_ref,),
            interpretation_refs=(interpretation_ref,),
        )
    )
    assert after.candidate_ref == candidate.candidate_id
    assert after.case_update is not None
    assert after.case_update.case_id == promotion.case.case_id
    assert after.case_update.status.value == "requires_human_review"
    state = service.get_conversation(ref)
    assert state is not None and state.bound_case_id == promotion.case.case_id
