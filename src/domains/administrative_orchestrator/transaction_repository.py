from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Uuid, select
from sqlalchemy.orm import Mapped, mapped_column

from .financial import (
    TransactionQualificationAssessment,
)
from .persistence import Base
from .persistence_mapping import model_from_row


class TransactionRecordConflict(RuntimeError):
    """An immutable transaction evidence record was reused inconsistently."""


class AdministrativeCaseEvidenceLinkRow(Base):
    __tablename__ = "administrative_case_evidence_link"

    link_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_ref: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_source_artifact.artifact_id"), nullable=False
    )
    representation_ref: Mapped[UUID | None] = mapped_column(
        ForeignKey("administrative_document_representation.representation_id"),
        nullable=True,
    )
    declared_role: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(512), nullable=False)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    linked_by: Mapped[str] = mapped_column(String(255), nullable=False)


class TransactionQualificationAssessmentRow(Base):
    __tablename__ = "administrative_transaction_qualification_assessment"

    assessment_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    assessment_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    supersedes_assessment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("administrative_transaction_qualification_assessment.assessment_id"),
        nullable=True,
    )
    input_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    rule_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    result: Mapped[str] = mapped_column(String(64), nullable=False)
    blocking_reasons_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _assessment_from_row(
    row: TransactionQualificationAssessmentRow,
) -> TransactionQualificationAssessment:
    return model_from_row(
        TransactionQualificationAssessment,
        row,
        input_refs=row.input_refs_json,
        blocking_reasons=row.blocking_reasons_json,
    )


def _current_assessments_from_rows(
    rows: list[TransactionQualificationAssessmentRow],
) -> list[TransactionQualificationAssessment]:
    assessments = [_assessment_from_row(row) for row in rows]
    superseded_ids = {
        item.supersedes_assessment_id
        for item in assessments
        if item.supersedes_assessment_id is not None
    }
    current = [item for item in assessments if item.assessment_id not in superseded_ids]
    by_kind: dict[str, list[TransactionQualificationAssessment]] = {}
    for item in current:
        by_kind.setdefault(item.assessment_kind, []).append(item)
    ambiguous = sorted(kind for kind, items in by_kind.items() if len(items) > 1)
    if ambiguous:
        raise TransactionRecordConflict(
            "multiple current qualification assessments exist for: "
            + ", ".join(ambiguous)
        )
    return current


def current_assessments_in_session(
    db, case_id: UUID, authority_epoch: int
) -> list[TransactionQualificationAssessment]:
    rows = (
        db.execute(
            select(TransactionQualificationAssessmentRow).where(
                TransactionQualificationAssessmentRow.case_id == case_id,
                TransactionQualificationAssessmentRow.authority_epoch == authority_epoch,
            )
        )
        .scalars()
        .all()
    )
    return _current_assessments_from_rows(rows)


__all__ = [
    "AdministrativeCaseEvidenceLinkRow",
    "TransactionQualificationAssessmentRow",
    "TransactionRecordConflict",
    "current_assessments_in_session",
]
