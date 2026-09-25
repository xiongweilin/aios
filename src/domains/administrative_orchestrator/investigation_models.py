from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import ConfigDict, Field, model_validator

from .domain import UtcModel, utcnow


class StrictUtcModel(UtcModel):
    """Strict persisted investigation models.

    Investigation output crosses a model/client boundary.  Unknown fields must
    not silently become new authority-bearing semantics.
    """

    model_config = ConfigDict(extra="forbid")


class InvestigationTriggerType(StrEnum):
    AMBIGUOUS_EVIDENCE = "ambiguous_evidence"
    CONFLICTING_FACTS = "conflicting_facts"
    MISSING_QUALIFICATION = "missing_qualification"
    MISSING_AUTHORITY = "missing_authority"
    POLICY_UNDERSPECIFIED = "policy_underspecified"
    UNEXPECTED_REALITY_STATE = "unexpected_reality_state"
    OUTCOME_UNKNOWN = "outcome_unknown"
    VERIFICATION_CONTRADICTION = "verification_contradiction"
    OBLIGATION_STALLED = "obligation_stalled"
    COMMITMENT_CONFLICT = "commitment_conflict"
    LATE_EVIDENCE = "late_evidence"
    HUMAN_REQUESTED_REVIEW = "human_requested_review"


class InvestigationStatus(StrEnum):
    REQUESTED = "requested"
    RUNNING = "running"
    PROPOSAL_RECORDED = "proposal_recorded"
    AWAITING_EVIDENCE = "awaiting_evidence"
    REQUIRES_HUMAN_REVIEW = "requires_human_review"
    CLOSURE_PRESERVED = "closure_preserved"
    REOPENED = "reopened"
    FAILED = "failed"
    EXPIRED = "expired"


class EvidenceRequestStatus(StrEnum):
    OPEN = "open"
    FULFILLED = "fulfilled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ReopenAssessmentDisposition(StrEnum):
    PRESERVE_CLOSURE = "preserve_closure"
    REOPEN_REQUIRED = "reopen_required"
    REQUIRES_HUMAN_REVIEW = "requires_human_review"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    SUPERSEDED = "superseded"


class ReopenAssessmentKind(StrEnum):
    DETERMINISTIC = "deterministic"
    HUMAN = "human"


class ReframingStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class InvestigationConstraints(StrictUtcModel):
    max_rounds: int = Field(default=4, ge=1, le=32)
    max_model_calls: int = Field(default=4, ge=0, le=64)
    max_evidence_requests: int = Field(default=4, ge=0, le=64)
    allowed_source_kinds: tuple[str, ...] = ("administrative",)
    deadline: datetime | None = None
    human_review_threshold: float = Field(default=0.75, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_sources(self) -> InvestigationConstraints:
        if not self.allowed_source_kinds:
            raise ValueError("investigation requires at least one allowed source kind")
        if any(not item.strip() for item in self.allowed_source_kinds):
            raise ValueError("allowed source kinds cannot be blank")
        return self


class InvestigationTrigger(StrictUtcModel):
    trigger_id: UUID = Field(default_factory=uuid4)
    case_id: UUID
    authority_epoch: int = Field(ge=1)
    trigger_type: InvestigationTriggerType
    reason: str = Field(min_length=1, max_length=2000)
    evidence_refs: tuple[str, ...] = ()
    source_type: str = Field(default="administrative", min_length=1, max_length=128)
    reconciliation_ref: str | None = Field(default=None, max_length=512)
    created_by: str = Field(min_length=1, max_length=255)
    created_at: datetime = Field(default_factory=utcnow)
    idempotency_key: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_trigger(self) -> InvestigationTrigger:
        if self.trigger_type is InvestigationTriggerType.OUTCOME_UNKNOWN and not (
            self.reconciliation_ref or ""
        ).strip():
            raise ValueError(
                "outcome_unknown investigation requires a completed World Runtime reconciliation reference"
            )
        return self


class InvestigationRequest(StrictUtcModel):
    investigation_id: UUID = Field(default_factory=uuid4)
    tenant_id: str = Field(default="*", min_length=1, max_length=512)
    case_id: UUID
    authority_epoch: int = Field(ge=1)
    trigger: InvestigationTrigger
    requested_question: str = Field(min_length=1, max_length=4000)
    allowed_evidence_refs: tuple[str, ...] = ()
    current_fact_snapshot_ref: str | None = Field(default=None, max_length=512)
    current_governance_basis_ref: str | None = Field(default=None, max_length=512)
    current_obligation_refs: tuple[str, ...] = ()
    current_commitment_refs: tuple[str, ...] = ()
    constraints: InvestigationConstraints = Field(default_factory=InvestigationConstraints)
    created_at: datetime = Field(default_factory=utcnow)
    created_by: str = Field(min_length=1, max_length=255)
    status: InvestigationStatus = InvestigationStatus.REQUESTED
    idempotency_key: str = Field(min_length=1, max_length=512)
    rounds_used: int = Field(default=0, ge=0)
    model_calls_used: int = Field(default=0, ge=0)
    evidence_requests_used: int = Field(default=0, ge=0)
    last_error_code: str | None = Field(default=None, max_length=256)
    updated_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def validate_lineage(self) -> InvestigationRequest:
        if self.trigger.case_id != self.case_id:
            raise ValueError("investigation trigger belongs to another case")
        if self.trigger.authority_epoch != self.authority_epoch:
            raise ValueError("investigation trigger is stale for the request epoch")
        if self.rounds_used > self.constraints.max_rounds:
            raise ValueError("investigation rounds exceed the configured budget")
        if self.model_calls_used > self.constraints.max_model_calls:
            raise ValueError("investigation model calls exceed the configured budget")
        if self.evidence_requests_used > self.constraints.max_evidence_requests:
            raise ValueError("investigation evidence requests exceed the configured budget")
        return self


class InvestigationHypothesis(StrictUtcModel):
    hypothesis_ref: str = Field(min_length=1, max_length=512)
    statement: str = Field(min_length=1, max_length=4000)
    basis_refs: tuple[str, ...] = ()
    uncertainty: float = Field(default=1.0, ge=0.0, le=1.0)


class InvestigationQueryRecommendation(StrictUtcModel):
    query_ref: str = Field(min_length=1, max_length=512)
    question: str = Field(min_length=1, max_length=4000)
    source_kind: str = Field(min_length=1, max_length=128)
    effect_class: Literal["read-only"] = "read-only"
    expected_discrimination: float = Field(default=0.0, ge=0.0, le=1.0)
    basis_refs: tuple[str, ...] = ()


class InvestigationModelProvenance(StrictUtcModel):
    provider: str = Field(min_length=1, max_length=128)
    model_identity: str = Field(min_length=1, max_length=512)
    model_version: str = Field(min_length=1, max_length=256)
    prompt_ref: str = Field(min_length=1, max_length=512)
    schema_ref: str = Field(min_length=1, max_length=512)
    response_digest: str = Field(min_length=1, max_length=128)


class ReframingProposal(StrictUtcModel):
    reframing_id: UUID = Field(default_factory=uuid4)
    investigation_id: UUID
    case_id: UUID
    current_frame: str = Field(min_length=1, max_length=2000)
    proposed_frame: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=4000)
    evidence_refs: tuple[str, ...] = ()
    status: ReframingStatus = ReframingStatus.PROPOSED
    created_at: datetime = Field(default_factory=utcnow)


class InvestigationProposal(StrictUtcModel):
    proposal_id: UUID = Field(default_factory=uuid4)
    investigation_id: UUID
    case_id: UUID
    authority_epoch: int = Field(ge=1)
    representation_version: str = Field(min_length=1, max_length=256)
    hypotheses: tuple[InvestigationHypothesis, ...] = ()
    ambiguities: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    recommended_queries: tuple[InvestigationQueryRecommendation, ...] = ()
    recommended_human_questions: tuple[str, ...] = ()
    possible_reframings: tuple[ReframingProposal, ...] = ()
    possible_reopen_targets: tuple[str, ...] = ()
    uncertainty: dict[str, Any] = Field(default_factory=dict)
    model_provenance: InvestigationModelProvenance
    created_at: datetime = Field(default_factory=utcnow)
    idempotency_key: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_lineage(self) -> InvestigationProposal:
        for item in self.possible_reframings:
            if item.investigation_id != self.investigation_id or item.case_id != self.case_id:
                raise ValueError("reframing proposal does not belong to the investigation")
            if item.status is not ReframingStatus.PROPOSED:
                raise ValueError("advisory output cannot accept or reject its own reframing")
        return self


class InvestigationEvidenceRequest(StrictUtcModel):
    evidence_request_id: UUID = Field(default_factory=uuid4)
    investigation_id: UUID
    case_id: UUID
    authority_epoch: int = Field(ge=1)
    source_kind: str = Field(min_length=1, max_length=128)
    requested_question: str = Field(min_length=1, max_length=4000)
    allowed_evidence_refs: tuple[str, ...] = ()
    status: EvidenceRequestStatus = EvidenceRequestStatus.OPEN
    evidence_refs: tuple[str, ...] = ()
    requested_by: str = Field(min_length=1, max_length=255)
    created_at: datetime = Field(default_factory=utcnow)
    fulfilled_at: datetime | None = None
    idempotency_key: str = Field(min_length=1, max_length=512)


class InvestigationEvidence(StrictUtcModel):
    evidence_id: UUID = Field(default_factory=uuid4)
    investigation_id: UUID
    case_id: UUID
    authority_epoch: int = Field(ge=1)
    evidence_request_id: UUID | None = None
    evidence_ref: str = Field(min_length=1, max_length=1000)
    source_kind: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=512)
    owner: str = Field(min_length=1, max_length=255)
    source_ref: str | None = Field(default=None, max_length=1000)
    source_version: str | None = Field(default=None, max_length=256)
    digest: str | None = Field(default=None, max_length=128)
    added_by: str = Field(min_length=1, max_length=255)
    created_at: datetime = Field(default_factory=utcnow)
    idempotency_key: str = Field(min_length=1, max_length=512)


class ReopenAssessment(StrictUtcModel):
    assessment_id: UUID = Field(default_factory=uuid4)
    investigation_id: UUID
    case_id: UUID
    authority_epoch: int = Field(ge=1)
    disposition: ReopenAssessmentDisposition
    reason: str = Field(min_length=1, max_length=4000)
    evidence_refs: tuple[str, ...] = ()
    proposal_ref: UUID | None = None
    assessment_kind: ReopenAssessmentKind
    assessed_by: str = Field(min_length=1, max_length=255)
    created_at: datetime = Field(default_factory=utcnow)
    idempotency_key: str = Field(min_length=1, max_length=512)


class ReopenRecord(StrictUtcModel):
    reopen_id: UUID = Field(default_factory=uuid4)
    investigation_id: UUID
    case_id: UUID
    assessment_ref: UUID
    previous_authority_epoch: int = Field(ge=1)
    new_authority_epoch: int = Field(ge=1)
    reopen_reason: str = Field(min_length=1, max_length=4000)
    evidence_refs: tuple[str, ...] = ()
    authorized_by: str = Field(min_length=1, max_length=255)
    invalidated_decision_refs: tuple[str, ...] = ()
    invalidated_governance_basis_refs: tuple[str, ...] = ()
    affected_obligation_refs: tuple[str, ...] = ()
    affected_execution_authorization_refs: tuple[str, ...] = ()
    affected_commitment_refs: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=utcnow)
    idempotency_key: str = Field(min_length=1, max_length=512)


__all__ = [
    "EvidenceRequestStatus",
    "InvestigationConstraints",
    "InvestigationEvidence",
    "InvestigationEvidenceRequest",
    "InvestigationHypothesis",
    "InvestigationModelProvenance",
    "InvestigationProposal",
    "InvestigationQueryRecommendation",
    "InvestigationRequest",
    "InvestigationStatus",
    "InvestigationTrigger",
    "InvestigationTriggerType",
    "ReframingProposal",
    "ReframingStatus",
    "ReopenAssessment",
    "ReopenAssessmentDisposition",
    "ReopenAssessmentKind",
    "ReopenRecord",
]
