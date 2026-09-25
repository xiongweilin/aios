from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from ..domain import UtcModel, utcnow


class IntakeVerificationStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class InterpretationStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INVALID = "invalid"


class CandidateAuthority(StrEnum):
    """The complete authority surface available to candidate facts.

    AUTHORITATIVE intentionally does not exist in this enum. Authoritative
    facts remain owned by approved systems of record and the existing M5
    FactAuthority path.
    """

    CLAIM = "claim"
    ATTESTED_CANDIDATE = "attested_candidate"


class CandidateStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ADMITTED = "admitted"
    REJECTED = "rejected"


class CandidateCaseUpdateStatus(StrEnum):
    REQUIRES_HUMAN_REVIEW = "requires_human_review"


class IntakeDisposition(StrEnum):
    ADMIT = "admit"
    NEEDS_CLARIFICATION = "needs_clarification"
    INFORMATION_ONLY = "information_only"
    UNSUPPORTED = "unsupported"
    DUPLICATE = "duplicate"
    AMBIGUOUS = "ambiguous"
    REQUIRES_HUMAN_REVIEW = "requires_human_review"


class AssessmentAuthority(StrEnum):
    MODEL_SUGGESTION = "model_suggestion"
    DETERMINISTIC_RULE = "deterministic_rule"
    HUMAN_REVIEW = "human_review"


def _require_text(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


def _locator_digest(locator: dict[str, Any]) -> str:
    encoded = json.dumps(locator, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class IntakeReceipt(UtcModel):
    receipt_id: UUID = Field(default_factory=uuid4)
    source_system: str = Field(min_length=1, max_length=128)
    tenant_ref: str = Field(min_length=1, max_length=512)
    source_event_id: str = Field(min_length=1, max_length=512)
    received_at: datetime = Field(default_factory=utcnow)
    verification_status: IntakeVerificationStatus = IntakeVerificationStatus.PENDING
    artifact_ref: UUID | None = None
    delivery_digest: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_delivery_identity(self) -> IntakeReceipt:
        _require_text(self.source_system, "source_system")
        _require_text(self.tenant_ref, "tenant_ref")
        _require_text(self.source_event_id, "source_event_id")
        _require_text(self.delivery_digest, "delivery_digest")
        return self


class SourceArtifact(UtcModel):
    artifact_id: UUID = Field(default_factory=uuid4)
    source_kind: str = Field(min_length=1, max_length=128)
    source_system: str = Field(min_length=1, max_length=128)
    tenant_ref: str = Field(min_length=1, max_length=512)
    canonical_source_ref: str = Field(min_length=1, max_length=1000)
    source_revision: str = Field(default="initial", min_length=1, max_length=256)
    source_event_ref: str = Field(min_length=1, max_length=512)
    actor_external_identity_ref: str | None = Field(default=None, max_length=1000)
    captured_at: datetime = Field(default_factory=utcnow)
    source_timestamp: datetime | None = None
    content_digest: str = Field(min_length=1, max_length=128)
    storage_ref: str = Field(min_length=1, max_length=2000)
    mime_type: str | None = Field(default=None, max_length=255)
    size: int = Field(ge=0)
    authenticity_class: str = Field(min_length=1, max_length=128)
    retention_class: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_source_identity(self) -> SourceArtifact:
        for name in (
            "source_kind",
            "source_system",
            "tenant_ref",
            "canonical_source_ref",
            "source_revision",
            "source_event_ref",
            "content_digest",
            "storage_ref",
            "authenticity_class",
            "retention_class",
        ):
            _require_text(getattr(self, name), name)
        return self


class EvidenceSpan(UtcModel):
    evidence_span_id: UUID = Field(default_factory=uuid4)
    artifact_ref: UUID
    representation_ref: UUID | None = None
    representation_digest: str = Field(min_length=1, max_length=128)
    locator_kind: str = Field(min_length=1, max_length=128)
    locator: dict[str, Any] = Field(min_length=1)
    extractor_ref: str = Field(min_length=1, max_length=512)
    locator_digest: str | None = Field(default=None, min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_locator_digest(self) -> EvidenceSpan:
        expected = _locator_digest(self.locator)
        if self.locator_digest is None:
            self.locator_digest = expected
        elif self.locator_digest != expected:
            raise ValueError("locator_digest does not match canonical locator")
        _require_text(self.representation_digest, "representation_digest")
        _require_text(self.locator_kind, "locator_kind")
        _require_text(self.extractor_ref, "extractor_ref")
        return self


class DocumentRepresentation(UtcModel):
    """Immutable, content-addressed parser/OCR output for one raw artifact."""

    representation_id: UUID = Field(default_factory=uuid4)
    source_artifact_ref: UUID
    representation_kind: str = Field(min_length=1, max_length=128)
    extractor_ref: str = Field(min_length=1, max_length=512)
    extractor_version: str = Field(min_length=1, max_length=256)
    content_digest: str = Field(min_length=1, max_length=128)
    storage_ref: str = Field(min_length=1, max_length=2000)
    size: int = Field(ge=0)
    created_at: datetime = Field(default_factory=utcnow)
    page_count: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_identity(self) -> DocumentRepresentation:
        for name in (
            "representation_kind",
            "extractor_ref",
            "extractor_version",
            "content_digest",
            "storage_ref",
        ):
            _require_text(getattr(self, name), name)
        return self


class InterpretationRecord(UtcModel):
    interpretation_id: UUID = Field(default_factory=uuid4)
    artifact_refs: tuple[UUID, ...] = Field(min_length=1)
    interpretation_profile_ref: str = Field(min_length=1, max_length=512)
    model_provider: str = Field(min_length=1, max_length=128)
    model_identity: str = Field(min_length=1, max_length=512)
    model_version: str = Field(min_length=1, max_length=256)
    schema_ref: str = Field(min_length=1, max_length=512)
    interpreted_at: datetime = Field(default_factory=utcnow)
    structured_output: dict[str, Any] = Field(default_factory=dict)
    evidence_span_refs: tuple[UUID, ...] = ()
    response_digest: str = Field(min_length=1, max_length=128)
    status: InterpretationStatus = InterpretationStatus.SUCCEEDED

    @model_validator(mode="after")
    def validate_provenance(self) -> InterpretationRecord:
        for name in (
            "interpretation_profile_ref",
            "model_provider",
            "model_identity",
            "model_version",
            "schema_ref",
            "response_digest",
        ):
            _require_text(getattr(self, name), name)
        return self


class CandidateFactAssertion(UtcModel):
    candidate_fact_id: UUID = Field(default_factory=uuid4)
    fact_key: str = Field(min_length=1, max_length=512)
    value: Any
    authority: CandidateAuthority
    interpretation_ref: UUID | None = None
    source_refs: tuple[UUID, ...] = Field(min_length=1)
    evidence_span_refs: tuple[UUID, ...] = ()
    no_evidence_reason: str | None = Field(default=None, max_length=2000)
    extractor_ref: str | None = Field(default=None, max_length=512)
    created_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def validate_candidate_provenance(self) -> CandidateFactAssertion:
        _require_text(self.fact_key, "fact_key")
        if not self.evidence_span_refs and not (self.no_evidence_reason or "").strip():
            raise ValueError(
                "candidate fact requires evidence_span_refs or no_evidence_reason"
            )
        return self


class CandidateAdministrativeRequest(UtcModel):
    candidate_id: UUID = Field(default_factory=uuid4)
    conversation_ref: str = Field(min_length=1, max_length=1000)
    interpretation_refs: tuple[UUID, ...] = Field(min_length=1)
    candidate_requester: str = Field(min_length=1, max_length=1000)
    candidate_intent: str = Field(min_length=1, max_length=2000)
    candidate_fact_refs: tuple[UUID, ...] = ()
    source_refs: tuple[UUID, ...] = Field(min_length=1)
    created_at: datetime = Field(default_factory=utcnow)
    supersedes_candidate_ref: UUID | None = None
    status: CandidateStatus = CandidateStatus.ACTIVE

    @model_validator(mode="after")
    def validate_candidate_request(self) -> CandidateAdministrativeRequest:
        for name in ("conversation_ref", "candidate_requester", "candidate_intent"):
            _require_text(getattr(self, name), name)
        return self


class CandidateCaseUpdate(UtcModel):
    candidate_update_id: UUID = Field(default_factory=uuid4)
    case_id: UUID
    conversation_ref: str = Field(min_length=1, max_length=1000)
    interpretation_refs: tuple[UUID, ...] = Field(min_length=1)
    candidate_fact_refs: tuple[UUID, ...] = ()
    source_refs: tuple[UUID, ...] = Field(min_length=1)
    created_at: datetime = Field(default_factory=utcnow)
    status: CandidateCaseUpdateStatus = CandidateCaseUpdateStatus.REQUIRES_HUMAN_REVIEW

    @model_validator(mode="after")
    def validate_case_update(self) -> CandidateCaseUpdate:
        _require_text(self.conversation_ref, "conversation_ref")
        if self.status != CandidateCaseUpdateStatus.REQUIRES_HUMAN_REVIEW:
            raise ValueError("candidate case updates remain pending human review in M6")
        return self


class IntakeAssessment(UtcModel):
    assessment_id: UUID = Field(default_factory=uuid4)
    candidate_ref: UUID
    disposition: IntakeDisposition
    basis: dict[str, Any] = Field(default_factory=dict)
    authority: AssessmentAuthority
    is_final: bool = False
    reviewer_principal_id: str | None = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def validate_assessment_authority(self) -> IntakeAssessment:
        if self.is_final:
            if self.authority == AssessmentAuthority.MODEL_SUGGESTION:
                raise ValueError("model suggestion cannot be a final intake assessment")
            if not self.basis:
                raise ValueError("final intake assessment requires a non-empty basis")
            if (
                self.authority == AssessmentAuthority.HUMAN_REVIEW
                and not (self.reviewer_principal_id or "").strip()
            ):
                raise ValueError("human final assessment requires reviewer_principal_id")
        return self


class PromotionRecord(UtcModel):
    promotion_id: UUID = Field(default_factory=uuid4)
    candidate_ref: UUID
    assessment_ref: UUID
    request_id: UUID
    ingress_receipt_ref: str = Field(min_length=1, max_length=1000)
    promoted_at: datetime = Field(default_factory=utcnow)
    promotion_policy_ref: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_promotion_lineage(self) -> PromotionRecord:
        _require_text(self.ingress_receipt_ref, "ingress_receipt_ref")
        _require_text(self.promotion_policy_ref, "promotion_policy_ref")
        return self


__all__ = [
    "AssessmentAuthority",
    "CandidateAdministrativeRequest",
    "CandidateAuthority",
    "CandidateCaseUpdate",
    "CandidateCaseUpdateStatus",
    "CandidateFactAssertion",
    "CandidateStatus",
    "DocumentRepresentation",
    "EvidenceSpan",
    "IntakeAssessment",
    "IntakeDisposition",
    "IntakeReceipt",
    "IntakeVerificationStatus",
    "InterpretationRecord",
    "InterpretationStatus",
    "PromotionRecord",
    "SourceArtifact",
]
