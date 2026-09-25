from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from .persistence import Base


class InvestigationRow(Base):
    __tablename__ = "administrative_investigation"
    __table_args__ = (
        UniqueConstraint(
            "case_id",
            "idempotency_key",
            name="uq_admin_investigation_case_idempotency",
        ),
    )

    investigation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(512), nullable=False)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(128), nullable=False)
    trigger_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    requested_question: Mapped[str] = mapped_column(String(4000), nullable=False)
    allowed_evidence_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    current_fact_snapshot_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    current_governance_basis_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    current_obligation_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    current_commitment_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    constraints_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(512), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    rounds_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_calls_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evidence_requests_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(256), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InvestigationProposalRow(Base):
    __tablename__ = "administrative_investigation_proposal"
    __table_args__ = (
        UniqueConstraint(
            "investigation_id",
            "idempotency_key",
            name="uq_admin_investigation_proposal_idempotency",
        ),
    )

    proposal_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    investigation_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_investigation.investigation_id"), nullable=False
    )
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    representation_version: Mapped[str] = mapped_column(String(256), nullable=False)
    hypotheses_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    ambiguities_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    missing_evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    recommended_queries_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    recommended_human_questions_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    possible_reframings_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    possible_reopen_targets_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    uncertainty_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    model_provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(512), nullable=False)
    proposal_digest: Mapped[str] = mapped_column(String(64), nullable=False)


class ReframingProposalRow(Base):
    __tablename__ = "administrative_reframing_proposal"

    reframing_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    investigation_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_investigation.investigation_id"), nullable=False
    )
    proposal_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_investigation_proposal.proposal_id"), nullable=False
    )
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    current_frame: Mapped[str] = mapped_column(String(2000), nullable=False)
    proposed_frame: Mapped[str] = mapped_column(String(2000), nullable=False)
    reason: Mapped[str] = mapped_column(String(4000), nullable=False)
    evidence_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InvestigationEvidenceRequestRow(Base):
    __tablename__ = "administrative_investigation_evidence_request"
    __table_args__ = (
        UniqueConstraint(
            "investigation_id",
            "idempotency_key",
            name="uq_admin_investigation_evidence_request_idempotency",
        ),
    )

    evidence_request_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    investigation_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_investigation.investigation_id"), nullable=False
    )
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_question: Mapped[str] = mapped_column(String(4000), nullable=False)
    allowed_evidence_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(512), nullable=False)


class InvestigationEvidenceRow(Base):
    __tablename__ = "administrative_investigation_evidence"
    __table_args__ = (
        UniqueConstraint(
            "investigation_id",
            "idempotency_key",
            name="uq_admin_investigation_evidence_idempotency",
        ),
    )

    evidence_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    investigation_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_investigation.investigation_id"), nullable=False
    )
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_request_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("administrative_investigation_evidence_request.evidence_request_id"),
        nullable=True,
    )
    evidence_ref: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(512), nullable=False)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_version: Mapped[str | None] = mapped_column(String(256), nullable=True)
    digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    added_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(512), nullable=False)


class ReopenAssessmentRow(Base):
    __tablename__ = "administrative_reopen_assessment"
    __table_args__ = (
        UniqueConstraint(
            "investigation_id",
            "idempotency_key",
            name="uq_admin_reopen_assessment_idempotency",
        ),
    )

    assessment_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    investigation_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_investigation.investigation_id"), nullable=False
    )
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    disposition: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(4000), nullable=False)
    evidence_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    proposal_ref: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    assessment_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    assessed_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(512), nullable=False)
    assessment_digest: Mapped[str] = mapped_column(String(64), nullable=False)


class ReopenRecordRow(Base):
    __tablename__ = "administrative_reopen_record"
    __table_args__ = (
        UniqueConstraint(
            "case_id",
            "idempotency_key",
            name="uq_admin_reopen_record_idempotency",
        ),
        UniqueConstraint(
            "assessment_ref",
            name="uq_admin_reopen_record_assessment",
        ),
    )

    reopen_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    investigation_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_investigation.investigation_id"), nullable=False
    )
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    assessment_ref: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_reopen_assessment.assessment_id"), nullable=False
    )
    previous_authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    new_authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    reopen_reason: Mapped[str] = mapped_column(String(4000), nullable=False)
    evidence_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    authorized_by: Mapped[str] = mapped_column(String(255), nullable=False)
    invalidated_decision_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    invalidated_governance_basis_refs_json: Mapped[list[str]] = mapped_column(
        JSON, nullable=False
    )
    affected_obligation_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    affected_execution_authorization_refs_json: Mapped[list[str]] = mapped_column(
        JSON, nullable=False
    )
    affected_commitment_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(512), nullable=False)


__all__ = [
    "InvestigationEvidenceRequestRow",
    "InvestigationEvidenceRow",
    "InvestigationProposalRow",
    "InvestigationRow",
    "ReframingProposalRow",
    "ReopenAssessmentRow",
    "ReopenRecordRow",
]
