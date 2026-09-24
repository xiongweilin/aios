from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from ..commitment_models import (
    CandidateCommitment,
    CommitmentRecord,
    SpeakerPrincipalResolution,
)
from ..domain import AdministrativeCase, AdministrativeRequest, CaseStatus
from ..financial import TransactionQualificationResult
from ..intake.models import (
    CandidateAdministrativeRequest,
    CandidateStatus,
    IntakeAssessment,
    IntakeDisposition,
    PromotionRecord,
)
from ..investigation_models import (
    InvestigationConstraints,
    InvestigationProposal,
    InvestigationTriggerType,
    ReopenAssessmentDisposition,
)
from ..policy import PolicyEvaluation


class QueueItem(BaseModel):
    case_id: UUID
    case_kind: str
    status: CaseStatus
    subject_ref: str
    requester_principal_id: str
    version: int
    authority_epoch: int
    updated_at: datetime


class RefreshFactsResponse(BaseModel):
    case: AdministrativeCase
    source: str
    source_ref: str
    source_version: str
    source_digest: str


class BindIdentityBody(BaseModel):
    provider: str = Field(min_length=1, max_length=255)
    external_subject: str = Field(min_length=1, max_length=512)
    principal_id: str = Field(min_length=1, max_length=255)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    reason: str = Field(min_length=1, max_length=2000)


class ReasonBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class QualificationAssessmentBody(BaseModel):
    assessment_kind: str = Field(min_length=1, max_length=128)
    input_refs: tuple[str, ...] = Field(min_length=1)
    rule_ref: str = Field(min_length=1, max_length=512)
    result: TransactionQualificationResult
    blocking_reasons: tuple[str, ...] = ()


class FinancialDocumentRevisionBody(BaseModel):
    facts: dict[str, Any]
    source_ref: str = Field(min_length=1, max_length=1000)
    source_version: str = Field(min_length=1, max_length=256)
    artifact_ref: UUID | None = None
    representation_ref: UUID | None = None
    declared_role: str = Field(default="material-revision", min_length=1, max_length=128)


class OutboxReplayResponse(BaseModel):
    event_id: UUID
    status: str
    attempts: int
    audit_id: UUID


class ExpireAuthorityBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    at: datetime | None = None


class IntakeQueueItem(BaseModel):
    candidate_id: UUID
    conversation_ref: str
    candidate_requester: str
    candidate_intent: str
    status: CandidateStatus
    created_at: datetime
    latest_assessment: IntakeAssessment | None = None


class IntakeCandidateDetail(BaseModel):
    candidate: CandidateAdministrativeRequest
    assessments: list[IntakeAssessment]
    promotion: PromotionRecord | None = None


class IntakeAssessmentBody(BaseModel):
    disposition: IntakeDisposition
    basis: dict[str, Any] = Field(default_factory=dict)


class IntakePromotionBody(BaseModel):
    assessment_id: UUID
    source_system: str = Field(min_length=1, max_length=128)
    tenant_ref: str = Field(min_length=1, max_length=512)
    source_event_id: str = Field(min_length=1, max_length=512)
    requester_principal_id: str = Field(min_length=1, max_length=255)
    channel: str = Field(default="intake", min_length=1, max_length=64)
    case_kind: str = Field(default="intake", min_length=1, max_length=128)
    subject_ref: str | None = Field(default=None, max_length=512)
    bridge_to_m5: bool = False
    bridge_to_m8: bool = False
    promotion_policy_ref: str = Field(
        default="m6-human-confirmed-v1", min_length=1, max_length=512
    )


class IntakePromotionResponse(BaseModel):
    promotion: PromotionRecord
    request: AdministrativeRequest
    case: AdministrativeCase
    created: bool
    policy_evaluation: PolicyEvaluation | None = None


class CommitmentSpeakerResolutionBody(BaseModel):
    external_subject: str = Field(min_length=1, max_length=1000)
    provider: str = Field(default="feishu", min_length=1, max_length=128)
    basis: dict[str, Any] = Field(min_length=1)


class CommitmentConfirmationBody(BaseModel):
    qualified_due_at: datetime
    due_time_basis: str = Field(min_length=1, max_length=512)


class CommitmentFulfillmentBody(BaseModel):
    basis: dict[str, Any] = Field(min_length=1)


class CommitmentDueRevisionBody(BaseModel):
    due_at: datetime
    basis: str = Field(min_length=1, max_length=512)


class CommitmentCancellationBody(BaseModel):
    basis: str = Field(min_length=1, max_length=2000)


class CommitmentCandidateQueueItem(BaseModel):
    candidate: CandidateCommitment
    resolution: SpeakerPrincipalResolution | None = None
    commitment: CommitmentRecord | None = None


class InvestigationRequestBody(BaseModel):
    trigger: InvestigationTriggerType
    reason: str = Field(min_length=1, max_length=2000)
    requested_question: str = Field(min_length=1, max_length=4000)
    evidence_refs: tuple[str, ...] = ()
    allowed_evidence_refs: tuple[str, ...] = ()
    constraints: InvestigationConstraints = Field(default_factory=InvestigationConstraints)
    source_type: str = Field(default="administrative", min_length=1, max_length=128)
    reconciliation_ref: str | None = Field(default=None, max_length=512)
    idempotency_key: str = Field(min_length=1, max_length=512)


class InvestigationEvidenceRequestBody(BaseModel):
    source_kind: str = Field(min_length=1, max_length=128)
    requested_question: str = Field(min_length=1, max_length=4000)
    allowed_evidence_refs: tuple[str, ...] = ()
    idempotency_key: str = Field(min_length=1, max_length=512)


class InvestigationEvidenceBody(BaseModel):
    evidence_request_id: UUID | None = None
    evidence_ref: str = Field(min_length=1, max_length=1000)
    source_kind: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=512)
    owner: str = Field(min_length=1, max_length=255)
    source_ref: str | None = Field(default=None, max_length=1000)
    source_version: str | None = Field(default=None, max_length=256)
    digest: str | None = Field(default=None, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=512)


class InvestigationProposalBody(BaseModel):
    proposal: InvestigationProposal


class ReopenAssessmentBody(BaseModel):
    investigation_id: UUID
    disposition: ReopenAssessmentDisposition
    reason: str = Field(min_length=1, max_length=4000)
    evidence_refs: tuple[str, ...] = ()
    proposal_ref: UUID | None = None
    idempotency_key: str = Field(min_length=1, max_length=512)


class ReopenCaseBody(BaseModel):
    assessment_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=512)


__all__ = [
    "BindIdentityBody",
    "CommitmentCancellationBody",
    "CommitmentCandidateQueueItem",
    "CommitmentConfirmationBody",
    "CommitmentDueRevisionBody",
    "CommitmentFulfillmentBody",
    "CommitmentSpeakerResolutionBody",
    "ExpireAuthorityBody",
    "FinancialDocumentRevisionBody",
    "IntakeAssessmentBody",
    "IntakeCandidateDetail",
    "IntakePromotionBody",
    "IntakePromotionResponse",
    "IntakeQueueItem",
    "InvestigationEvidenceBody",
    "InvestigationEvidenceRequestBody",
    "InvestigationProposalBody",
    "InvestigationRequestBody",
    "OutboxReplayResponse",
    "QualificationAssessmentBody",
    "QueueItem",
    "RefreshFactsResponse",
    "ReopenAssessmentBody",
    "ReopenCaseBody",
]
