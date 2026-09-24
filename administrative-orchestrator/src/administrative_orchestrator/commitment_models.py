from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from .domain import UtcModel, utcnow


class CandidateCommitmentClassification(StrEnum):
    EXPLICIT_SELF_COMMITMENT = "explicit_self_commitment"
    AMBIGUOUS_COMMITMENT = "ambiguous_commitment"
    ASPIRATION = "aspiration"
    SUGGESTION = "suggestion"
    INFORMATION = "information"
    ASSIGNMENT_TO_OTHER = "assignment_to_other"


class CandidateCommitmentStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ADMITTED = "admitted"
    REJECTED = "rejected"
    REQUIRES_HUMAN_REVIEW = "requires_human_review"


class CommitmentState(StrEnum):
    ACTIVE = "active"
    OVERDUE = "overdue"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"
    REOPEN_REQUIRED = "reopen_required"


class CommitmentFulfillmentKind(StrEnum):
    EVIDENCE_VERIFIED = "evidence_verified"
    AUTHORIZED_ATTESTATION = "authorized_attestation"


class CommunicationDeliveryState(StrEnum):
    PREPARED = "prepared"
    TRANSPORT_ACCEPTED = "transport_accepted"
    DELIVERY_CONFIRMED = "delivery_confirmed"
    RETRYING = "retrying"
    PERMANENT_FAILED = "permanent_failed"
    OUTCOME_UNKNOWN = "outcome_unknown"


class CommunicationReadState(StrEnum):
    UNKNOWN = "unknown"


class CandidateCommitment(UtcModel):
    candidate_commitment_id: UUID = Field(default_factory=uuid4)
    source_artifact_ref: UUID
    interpretation_ref: UUID
    evidence_span_refs: tuple[UUID, ...] = Field(min_length=1)
    candidate_committer_identity: str = Field(min_length=1, max_length=512)
    candidate_action: str = Field(min_length=1, max_length=2000)
    candidate_due_text: str | None = Field(default=None, max_length=512)
    candidate_due_at: datetime | None = None
    candidate_scope_ref: str | None = Field(default=None, max_length=1000)
    candidate_beneficiary: str | None = Field(default=None, max_length=1000)
    classification: CandidateCommitmentClassification
    status: CandidateCommitmentStatus = CandidateCommitmentStatus.ACTIVE
    created_at: datetime = Field(default_factory=utcnow)
    superseded_by: UUID | None = None

    @model_validator(mode="after")
    def validate_candidate(self) -> CandidateCommitment:
        if self.candidate_due_at is not None and self.candidate_due_at.tzinfo is None:
            raise ValueError("candidate_due_at must be offset-aware")
        if self.status is CandidateCommitmentStatus.SUPERSEDED and self.superseded_by is None:
            raise ValueError("superseded candidate requires superseded_by")
        return self


class SpeakerPrincipalResolution(UtcModel):
    resolution_id: UUID = Field(default_factory=uuid4)
    candidate_ref: UUID
    source_speaker_identity: str = Field(min_length=1, max_length=512)
    resolved_principal_id: str = Field(min_length=1, max_length=255)
    provider: str = Field(default="feishu", min_length=1, max_length=128)
    external_subject: str = Field(min_length=1, max_length=1000)
    basis: dict[str, Any] = Field(min_length=1)
    resolver_type: str = Field(min_length=1, max_length=128)
    resolved_at: datetime = Field(default_factory=utcnow)


class CommitmentRecord(UtcModel):
    commitment_id: UUID = Field(default_factory=uuid4)
    candidate_ref: UUID
    case_id: UUID
    authority_epoch: int = Field(ge=1)
    committer_principal_id: str = Field(min_length=1, max_length=255)
    committer_external_subject: str = Field(min_length=1, max_length=1000)
    commitment_action: str = Field(min_length=1, max_length=2000)
    due_at: datetime
    due_time_basis: str = Field(min_length=1, max_length=512)
    scope_ref: str | None = Field(default=None, max_length=1000)
    beneficiary_principal_id: str | None = Field(default=None, max_length=255)
    fulfillment_kind: CommitmentFulfillmentKind = CommitmentFulfillmentKind.AUTHORIZED_ATTESTATION
    state: CommitmentState = CommitmentState.ACTIVE
    version: int = Field(default=1, ge=1)
    responsibility_ref: str | None = None
    responsibility_version: int | None = Field(default=None, ge=1)
    responsibility_admission_ref: str | None = None
    responsibility_assessment_ref: str | None = None
    responsibility_proposal_ref: str | None = None
    responsibility_discharge_assessment_ref: str | None = None
    responsibility_discharge_decision_ref: str | None = None
    responsibility_transition_ref: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    was_overdue: bool = False

    @model_validator(mode="after")
    def validate_due_at(self) -> CommitmentRecord:
        if self.due_at.tzinfo is None:
            raise ValueError("qualified due_at must be offset-aware")
        return self


class CommitmentFulfillmentAttestation(UtcModel):
    attestation_id: UUID = Field(default_factory=uuid4)
    case_id: UUID
    authority_epoch: int = Field(ge=1)
    commitment_version: int = Field(ge=1)
    principal_id: str = Field(min_length=1, max_length=255)
    disposition: str = Field(default="fulfilled", min_length=1, max_length=64)
    basis: dict[str, Any] = Field(min_length=1)
    attested_at: datetime = Field(default_factory=utcnow)


class CommunicationDraftRecord(UtcModel):
    draft_id: UUID = Field(default_factory=uuid4)
    case_id: UUID
    authority_epoch: int = Field(ge=1)
    channel: str = Field(min_length=1, max_length=64)
    recipient_principal_id: str = Field(min_length=1, max_length=255)
    recipient_external_subject: str = Field(min_length=1, max_length=1000)
    content_storage_ref: str = Field(min_length=1, max_length=2000)
    content_digest: str = Field(min_length=64, max_length=64)
    content_size: int = Field(ge=1)
    draft_kind: str = Field(min_length=1, max_length=128)
    generator_ref: str = Field(min_length=1, max_length=512)
    created_at: datetime = Field(default_factory=utcnow)
    superseded_by: UUID | None = None


class CommunicationEffectRecord(UtcModel):
    communication_event_id: UUID = Field(default_factory=uuid4)
    case_id: UUID
    authority_epoch: int = Field(ge=1)
    draft_id: UUID
    effect_id: UUID
    delivery_state: CommunicationDeliveryState = CommunicationDeliveryState.PREPARED
    read_state: CommunicationReadState = CommunicationReadState.UNKNOWN
    provider_message_ref: str | None = Field(default=None, max_length=1000)
    attempts: int = Field(default=0, ge=0)
    last_error_code: str | None = Field(default=None, max_length=256)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


__all__ = [
    "CandidateCommitment",
    "CandidateCommitmentClassification",
    "CandidateCommitmentStatus",
    "CommitmentFulfillmentKind",
    "CommitmentFulfillmentAttestation",
    "CommitmentRecord",
    "CommitmentState",
    "CommunicationDeliveryState",
    "CommunicationDraftRecord",
    "CommunicationEffectRecord",
    "CommunicationReadState",
    "SpeakerPrincipalResolution",
]
