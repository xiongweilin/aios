from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..persistence import Base

class SourceArtifactRow(Base):
    __tablename__ = "administrative_source_artifact"
    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "tenant_ref",
            "canonical_source_ref",
            "source_revision",
            name="uq_source_artifact_revision",
        ),
    )

    artifact_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    source_system: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    canonical_source_ref: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_revision: Mapped[str] = mapped_column(String(256), nullable=False)
    source_event_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    actor_external_identity_ref: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    content_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_ref: Mapped[str] = mapped_column(String(2000), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    authenticity_class: Mapped[str] = mapped_column(String(128), nullable=False)
    retention_class: Mapped[str] = mapped_column(String(128), nullable=False)

class IntakeReceiptRow(Base):
    __tablename__ = "administrative_intake_receipt"
    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "tenant_ref",
            "source_event_id",
            name="uq_intake_receipt_delivery",
        ),
    )

    receipt_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_system: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(512), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False)
    artifact_ref: Mapped[UUID | None] = mapped_column(
        ForeignKey("administrative_source_artifact.artifact_id"), nullable=True
    )
    delivery_digest: Mapped[str] = mapped_column(String(128), nullable=False)

class EvidenceSpanRow(Base):
    __tablename__ = "administrative_evidence_span"
    __table_args__ = (
        UniqueConstraint(
            "artifact_ref",
            "representation_digest",
            "locator_digest",
            "extractor_ref",
            name="uq_evidence_span_identity",
        ),
    )

    evidence_span_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    artifact_ref: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_source_artifact.artifact_id"), nullable=False
    )
    representation_ref: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    representation_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    locator_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    locator_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    locator_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    extractor_ref: Mapped[str] = mapped_column(String(512), nullable=False)

class InterpretationRecordRow(Base):
    __tablename__ = "administrative_interpretation_record"

    interpretation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    artifact_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    interpretation_profile_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(128), nullable=False)
    model_identity: Mapped[str] = mapped_column(String(512), nullable=False)
    model_version: Mapped[str] = mapped_column(String(256), nullable=False)
    schema_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    interpreted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    structured_output_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence_span_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    response_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)

class CandidateFactAssertionRow(Base):
    __tablename__ = "administrative_candidate_fact_assertion"
    __table_args__ = (
        CheckConstraint(
            "authority IN ('claim', 'attested_candidate')",
            name="ck_candidate_fact_authority",
        ),
    )

    candidate_fact_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    fact_key: Mapped[str] = mapped_column(String(512), nullable=False)
    value_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    authority: Mapped[str] = mapped_column(String(32), nullable=False)
    interpretation_ref: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    source_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence_span_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    no_evidence_reason: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    extractor_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class CandidateAdministrativeRequestRow(Base):
    __tablename__ = "administrative_candidate_request"

    candidate_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    conversation_ref: Mapped[str] = mapped_column(String(1000), nullable=False)
    interpretation_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    candidate_requester: Mapped[str] = mapped_column(String(1000), nullable=False)
    candidate_intent: Mapped[str] = mapped_column(String(2000), nullable=False)
    candidate_fact_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    supersedes_candidate_ref: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)

class CandidateCaseUpdateRow(Base):
    __tablename__ = "administrative_candidate_case_update"

    candidate_update_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    conversation_ref: Mapped[str] = mapped_column(String(1000), nullable=False)
    interpretation_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    candidate_fact_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)

class IntakeAssessmentRow(Base):
    __tablename__ = "administrative_intake_assessment"
    __table_args__ = (
        CheckConstraint(
            "NOT (is_final AND authority = 'model_suggestion')",
            name="ck_final_assessment_not_model",
        ),
        Index(
            "uq_intake_final_assessment_candidate",
            "candidate_ref",
            unique=True,
            sqlite_where=text("is_final = 1"),
            postgresql_where=text("is_final"),
        ),
    )

    assessment_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    candidate_ref: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    disposition: Mapped[str] = mapped_column(String(64), nullable=False)
    basis_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    authority: Mapped[str] = mapped_column(String(64), nullable=False)
    is_final: Mapped[bool] = mapped_column(nullable=False, default=False)
    reviewer_principal_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class PromotionRecordRow(Base):
    __tablename__ = "administrative_promotion_record"
    __table_args__ = (
        UniqueConstraint("candidate_ref", name="uq_promotion_candidate"),
        UniqueConstraint("request_id", name="uq_promotion_request"),
    )

    promotion_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    candidate_ref: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    assessment_ref: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    request_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_request.request_id"), nullable=False
    )
    ingress_receipt_ref: Mapped[str] = mapped_column(String(1000), nullable=False)
    promoted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    promotion_policy_ref: Mapped[str] = mapped_column(String(512), nullable=False)

class DocumentRepresentationRow(Base):
    __tablename__ = "administrative_document_representation"

    representation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_artifact_ref: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_source_artifact.artifact_id"), nullable=False
    )
    representation_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    extractor_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(256), nullable=False)
    content_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_ref: Mapped[str] = mapped_column(String(2000), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False)
