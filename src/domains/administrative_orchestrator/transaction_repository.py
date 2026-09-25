from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Uuid, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from .financial import (
    AdministrativeCaseEvidenceLink,
    TransactionQualificationAssessment,
)
from .persistence import Base, SqlStore


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


def _link_from_row(row: AdministrativeCaseEvidenceLinkRow) -> AdministrativeCaseEvidenceLink:
    return AdministrativeCaseEvidenceLink(
        link_id=row.link_id,
        case_id=row.case_id,
        authority_epoch=row.authority_epoch,
        artifact_ref=row.artifact_ref,
        representation_ref=row.representation_ref,
        declared_role=row.declared_role,
        source=row.source,
        linked_at=row.linked_at,
        linked_by=row.linked_by,
    )


def _assessment_from_row(
    row: TransactionQualificationAssessmentRow,
) -> TransactionQualificationAssessment:
    return TransactionQualificationAssessment(
        assessment_id=row.assessment_id,
        case_id=row.case_id,
        authority_epoch=row.authority_epoch,
        assessment_kind=row.assessment_kind,
        supersedes_assessment_id=row.supersedes_assessment_id,
        input_refs=tuple(row.input_refs_json),
        rule_ref=row.rule_ref,
        result=row.result,
        blocking_reasons=tuple(row.blocking_reasons_json),
        created_at=row.created_at,
    )


def _link_semantics(link: AdministrativeCaseEvidenceLink) -> dict[str, Any]:
    return link.model_dump(mode="json", exclude={"link_id"})


def _assessment_semantics(assessment: TransactionQualificationAssessment) -> dict[str, Any]:
    return assessment.model_dump(mode="json", exclude={"assessment_id"})


class TransactionRepository:
    """Persistence boundary for M8 transaction evidence and qualification."""

    def __init__(self, store: SqlStore) -> None:
        self.store = store

    def append_evidence_link(
        self, link: AdministrativeCaseEvidenceLink
    ) -> AdministrativeCaseEvidenceLink:
        with self.store.sessions.begin() as db:
            existing = db.get(AdministrativeCaseEvidenceLinkRow, link.link_id)
            if existing is not None:
                restored = _link_from_row(existing)
                if _link_semantics(restored) != _link_semantics(link):
                    raise TransactionRecordConflict(
                        "evidence link identity was reused with different semantics"
                    )
                return restored
            existing_semantic = (
                db.execute(
                    select(AdministrativeCaseEvidenceLinkRow).where(
                        AdministrativeCaseEvidenceLinkRow.case_id == link.case_id,
                        AdministrativeCaseEvidenceLinkRow.authority_epoch
                        == link.authority_epoch,
                        AdministrativeCaseEvidenceLinkRow.artifact_ref == link.artifact_ref,
                        AdministrativeCaseEvidenceLinkRow.representation_ref
                        == link.representation_ref,
                        AdministrativeCaseEvidenceLinkRow.declared_role == link.declared_role,
                    )
                )
                .scalars()
                .first()
            )
            if existing_semantic is not None:
                restored = _link_from_row(existing_semantic)
                if _link_semantics(restored) != _link_semantics(link):
                    raise TransactionRecordConflict(
                        "evidence link semantics already exist with different identity"
                    )
                return restored
            db.add(
                AdministrativeCaseEvidenceLinkRow(
                    link_id=link.link_id,
                    case_id=link.case_id,
                    authority_epoch=link.authority_epoch,
                    artifact_ref=link.artifact_ref,
                    representation_ref=link.representation_ref,
                    declared_role=link.declared_role,
                    source=link.source,
                    linked_at=link.linked_at,
                    linked_by=link.linked_by,
                )
            )
            try:
                db.flush()
            except IntegrityError as exc:
                raise TransactionRecordConflict(
                    "evidence link was concurrently inserted"
                ) from exc
            self.store._append_audit(
                db,
                link.case_id,
                "transaction.evidence_link.appended",
                {
                    "link_id": str(link.link_id),
                    "authority_epoch": link.authority_epoch,
                    "artifact_ref": str(link.artifact_ref),
                    "representation_ref": (
                        str(link.representation_ref) if link.representation_ref else None
                    ),
                    "declared_role": link.declared_role,
                },
            )
            return link

    def list_evidence_links(
        self, case_id: UUID, authority_epoch: int
    ) -> list[AdministrativeCaseEvidenceLink]:
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(AdministrativeCaseEvidenceLinkRow)
                    .where(
                        AdministrativeCaseEvidenceLinkRow.case_id == case_id,
                        AdministrativeCaseEvidenceLinkRow.authority_epoch == authority_epoch,
                    )
                    .order_by(
                        AdministrativeCaseEvidenceLinkRow.linked_at,
                        AdministrativeCaseEvidenceLinkRow.link_id,
                    )
                )
                .scalars()
                .all()
            )
            return [_link_from_row(row) for row in rows]

    def append_assessment(
        self, assessment: TransactionQualificationAssessment
    ) -> TransactionQualificationAssessment:
        # Import lazily because persistence registers this repository while
        # messaging is importing its persistence dependency.
        from .messaging import emit_outbox

        with self.store.sessions.begin() as db:
            existing = db.get(
                TransactionQualificationAssessmentRow, assessment.assessment_id
            )
            if existing is not None:
                restored = _assessment_from_row(existing)
                if _assessment_semantics(restored) != _assessment_semantics(assessment):
                    raise TransactionRecordConflict(
                        "qualification assessment identity was reused with different semantics"
                    )
                return restored
            superseded = None
            if assessment.supersedes_assessment_id is not None:
                superseded = db.get(
                    TransactionQualificationAssessmentRow,
                    assessment.supersedes_assessment_id,
                )
                if superseded is None:
                    raise TransactionRecordConflict(
                        "qualification assessment supersession target does not exist"
                    )
                if (
                    superseded.case_id != assessment.case_id
                    or superseded.authority_epoch != assessment.authority_epoch
                    or superseded.assessment_kind != assessment.assessment_kind
                ):
                    raise TransactionRecordConflict(
                        "qualification assessment supersession target has incompatible identity"
                    )
                successor_exists = db.execute(
                    select(TransactionQualificationAssessmentRow.assessment_id).where(
                        TransactionQualificationAssessmentRow.supersedes_assessment_id
                        == assessment.supersedes_assessment_id
                    )
                ).first()
                if successor_exists is not None:
                    raise TransactionRecordConflict(
                        "qualification assessment supersession target is already superseded"
                    )
            else:
                same_kind_rows = db.execute(
                    select(TransactionQualificationAssessmentRow).where(
                        TransactionQualificationAssessmentRow.case_id == assessment.case_id,
                        TransactionQualificationAssessmentRow.authority_epoch
                        == assessment.authority_epoch,
                        TransactionQualificationAssessmentRow.assessment_kind
                        == assessment.assessment_kind,
                    )
                ).scalars().all()
                superseded_ids = {
                    row.supersedes_assessment_id
                    for row in same_kind_rows
                    if row.supersedes_assessment_id is not None
                }
                current_same_kind = next(
                    (row for row in same_kind_rows if row.assessment_id not in superseded_ids),
                    None,
                )
                if current_same_kind is not None:
                    raise TransactionRecordConflict(
                        "new qualification assessment must supersede the current assessment"
                    )
            db.add(
                TransactionQualificationAssessmentRow(
                    assessment_id=assessment.assessment_id,
                    case_id=assessment.case_id,
                    authority_epoch=assessment.authority_epoch,
                    assessment_kind=assessment.assessment_kind,
                    supersedes_assessment_id=assessment.supersedes_assessment_id,
                    input_refs_json=list(assessment.input_refs),
                    rule_ref=assessment.rule_ref,
                    result=assessment.result.value,
                    blocking_reasons_json=list(assessment.blocking_reasons),
                    created_at=assessment.created_at,
                )
            )
            try:
                db.flush()
            except IntegrityError as exc:
                raise TransactionRecordConflict(
                    "qualification assessment was concurrently inserted"
                ) from exc
            self.store._append_audit(
                db,
                assessment.case_id,
                "transaction.qualification_assessment.appended",
                {
                    "assessment_id": str(assessment.assessment_id),
                    "authority_epoch": assessment.authority_epoch,
                    "assessment_kind": assessment.assessment_kind,
                    "result": assessment.result.value,
                    "rule_ref": assessment.rule_ref,
                },
            )
            emit_outbox(
                db,
                event_type="workflow.case_changed",
                aggregate_id=str(assessment.case_id),
                payload={
                    "case_id": str(assessment.case_id),
                    "authority_epoch": assessment.authority_epoch,
                    "cause": "qualification_assessment",
                    "assessment_id": str(assessment.assessment_id),
                    "assessment_kind": assessment.assessment_kind,
                },
            )
            return assessment

    def get_assessment(self, assessment_id: UUID) -> TransactionQualificationAssessment | None:
        with self.store.sessions() as db:
            row = db.get(TransactionQualificationAssessmentRow, assessment_id)
            return None if row is None else _assessment_from_row(row)

    def list_assessments(
        self, case_id: UUID, authority_epoch: int
    ) -> list[TransactionQualificationAssessment]:
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(TransactionQualificationAssessmentRow)
                    .where(
                        TransactionQualificationAssessmentRow.case_id == case_id,
                        TransactionQualificationAssessmentRow.authority_epoch == authority_epoch,
                    )
                    .order_by(
                        TransactionQualificationAssessmentRow.created_at,
                        TransactionQualificationAssessmentRow.assessment_id,
                    )
                )
                .scalars()
                .all()
            )
            return [_assessment_from_row(row) for row in rows]

    def list_current_assessments(
        self, case_id: UUID, authority_epoch: int
    ) -> list[TransactionQualificationAssessment]:
        with self.store.sessions() as db:
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
    "TransactionRepository",
    "current_assessments_in_session",
]
