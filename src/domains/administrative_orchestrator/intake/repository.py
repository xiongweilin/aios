from __future__ import annotations

from dataclasses import dataclass
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
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from ..persistence import Base, SqlStore
from ..persistence_mapping import model_from_row, model_values
from .models import (
    CandidateAdministrativeRequest,
    CandidateCaseUpdate,
    CandidateFactAssertion,
    CandidateStatus,
    EvidenceSpan,
    IntakeAssessment,
    IntakeReceipt,
    InterpretationRecord,
    PromotionRecord,
    SourceArtifact,
)


class IntakeReceiptConflict(RuntimeError):
    """The same provider delivery key was observed with different content."""


class SourceArtifactConflict(RuntimeError):
    """The same canonical source revision was observed with different content."""


class PromotionConflict(RuntimeError):
    """A candidate or request was already promoted with different lineage."""


class AssessmentConflict(RuntimeError):
    """A candidate already has a different final intake assessment."""


class InterpretationConflict(RuntimeError):
    """An interpretation identity was reused with different semantics."""


class CandidateConflict(RuntimeError):
    """A candidate identity was reused with different semantics."""


@dataclass(frozen=True, slots=True)
class IntakeDeliveryAcceptance:
    """The durable receipt and async handoff created for one provider event."""

    receipt: IntakeReceipt
    outbox_event_id: UUID
    created: bool


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


def _uuid_tuple(values: list[str] | None) -> tuple[UUID, ...]:
    return tuple(UUID(value) for value in (values or []))


def _receipt_from_row(row: IntakeReceiptRow) -> IntakeReceipt:
    return model_from_row(IntakeReceipt, row)


def _artifact_from_row(row: SourceArtifactRow) -> SourceArtifact:
    return model_from_row(SourceArtifact, row)


def _span_from_row(row: EvidenceSpanRow) -> EvidenceSpan:
    return model_from_row(EvidenceSpan, row, rename={"locator_json": "locator"})


def _interpretation_from_row(row: InterpretationRecordRow) -> InterpretationRecord:
    return model_from_row(
        InterpretationRecord,
        row,
        rename={
            "artifact_refs_json": "artifact_refs",
            "structured_output_json": "structured_output",
            "evidence_span_refs_json": "evidence_span_refs",
        },
    )


def _fact_from_row(row: CandidateFactAssertionRow) -> CandidateFactAssertion:
    return model_from_row(
        CandidateFactAssertion,
        row,
        rename={
            "value_json": "value",
            "source_refs_json": "source_refs",
            "evidence_span_refs_json": "evidence_span_refs",
        },
    )


def _candidate_fact_semantics(fact: CandidateFactAssertion) -> dict[str, Any]:
    return fact.model_dump(mode="json", exclude={"created_at"})


def _candidate_semantics(candidate: CandidateAdministrativeRequest) -> dict[str, Any]:
    return candidate.model_dump(mode="json", exclude={"status"})


def _candidate_from_row(row: CandidateAdministrativeRequestRow) -> CandidateAdministrativeRequest:
    return model_from_row(
        CandidateAdministrativeRequest,
        row,
        rename={
            "interpretation_refs_json": "interpretation_refs",
            "candidate_fact_refs_json": "candidate_fact_refs",
            "source_refs_json": "source_refs",
        },
    )


def _case_update_from_row(row: CandidateCaseUpdateRow) -> CandidateCaseUpdate:
    return model_from_row(
        CandidateCaseUpdate,
        row,
        rename={
            "interpretation_refs_json": "interpretation_refs",
            "candidate_fact_refs_json": "candidate_fact_refs",
            "source_refs_json": "source_refs",
        },
    )


def _assessment_from_row(row: IntakeAssessmentRow) -> IntakeAssessment:
    return model_from_row(IntakeAssessment, row, rename={"basis_json": "basis"})


def _promotion_from_row(row: PromotionRecordRow) -> PromotionRecord:
    return model_from_row(PromotionRecord, row)


class IntakeRepository:
    """Durable append/read primitives for M6 intake objects.

    This repository deliberately has no provider, model, assessment, or
    promotion decision logic. It only preserves immutable lineage and
    deterministic delivery/admission identity for later service slices.
    """

    def __init__(self, store: SqlStore) -> None:
        self.store = store

    def persist_intake_receipt(self, receipt: IntakeReceipt) -> IntakeReceipt:
        with self.store.sessions.begin() as db:
            existing = db.execute(
                select(IntakeReceiptRow).where(
                    IntakeReceiptRow.source_system == receipt.source_system,
                    IntakeReceiptRow.tenant_ref == receipt.tenant_ref,
                    IntakeReceiptRow.source_event_id == receipt.source_event_id,
                )
            ).scalar_one_or_none()
            if existing is not None:
                if existing.delivery_digest != receipt.delivery_digest:
                    raise IntakeReceiptConflict(
                        "delivery identity was redelivered with a different digest"
                    )
                return _receipt_from_row(existing)
            db.add(
                IntakeReceiptRow(**model_values(receipt))
            )
            try:
                db.flush()
            except IntegrityError as exc:
                raise IntakeReceiptConflict("delivery identity was concurrently inserted") from exc
            return receipt


    def attach_artifact_to_receipt(self, receipt_id: UUID, artifact_id: UUID) -> IntakeReceipt:
        """Attach the immutable canonical artifact exactly once to a receipt."""
        with self.store.sessions.begin() as db:
            row = db.get(IntakeReceiptRow, receipt_id)
            if row is None:
                raise IntakeReceiptConflict("intake receipt does not exist")
            if row.artifact_ref is not None and row.artifact_ref != artifact_id:
                raise IntakeReceiptConflict("intake receipt is already linked to another artifact")
            row.artifact_ref = artifact_id
            db.flush()
            return _receipt_from_row(row)

    def get_intake_receipt(
        self, *, source_system: str, tenant_ref: str, source_event_id: str
    ) -> IntakeReceipt | None:
        with self.store.sessions() as db:
            row = db.execute(
                select(IntakeReceiptRow).where(
                    IntakeReceiptRow.source_system == source_system,
                    IntakeReceiptRow.tenant_ref == tenant_ref,
                    IntakeReceiptRow.source_event_id == source_event_id,
                )
            ).scalar_one_or_none()
            return None if row is None else _receipt_from_row(row)

    def append_source_artifact(self, artifact: SourceArtifact) -> SourceArtifact:
        with self.store.sessions.begin() as db:
            existing = db.execute(
                select(SourceArtifactRow).where(
                    SourceArtifactRow.source_system == artifact.source_system,
                    SourceArtifactRow.tenant_ref == artifact.tenant_ref,
                    SourceArtifactRow.canonical_source_ref == artifact.canonical_source_ref,
                    SourceArtifactRow.source_revision == artifact.source_revision,
                )
            ).scalar_one_or_none()
            if existing is not None:
                if existing.content_digest != artifact.content_digest:
                    raise SourceArtifactConflict(
                        "canonical source revision was redelivered with a different digest"
                    )
                return _artifact_from_row(existing)
            db.add(
                SourceArtifactRow(**model_values(artifact))
            )
            try:
                db.flush()
            except IntegrityError as exc:
                raise SourceArtifactConflict(
                    "canonical source revision was concurrently inserted"
                ) from exc
            return artifact

    def append_evidence_span(self, span: EvidenceSpan) -> EvidenceSpan:
        with self.store.sessions.begin() as db:
            existing = db.execute(
                select(EvidenceSpanRow).where(
                    EvidenceSpanRow.artifact_ref == span.artifact_ref,
                    EvidenceSpanRow.representation_digest == span.representation_digest,
                    EvidenceSpanRow.locator_digest == span.locator_digest,
                    EvidenceSpanRow.extractor_ref == span.extractor_ref,
                )
            ).scalar_one_or_none()
            if existing is not None:
                return _span_from_row(existing)
            db.add(
                EvidenceSpanRow(
                    **model_values(
                        span, rename={"locator": "locator_json"}, json_fields={"locator"}
                    )
                )
            )
            db.flush()
            return span

    def append_interpretation(self, interpretation: InterpretationRecord) -> InterpretationRecord:
        with self.store.sessions.begin() as db:
            existing = db.get(InterpretationRecordRow, interpretation.interpretation_id)
            if existing is not None:
                restored = _interpretation_from_row(existing)
                if restored != interpretation:
                    raise InterpretationConflict(
                        "interpretation identity was reused with different semantics"
                    )
                return restored
            db.add(
                InterpretationRecordRow(
                    **model_values(
                        interpretation,
                        rename={
                            "artifact_refs": "artifact_refs_json",
                            "structured_output": "structured_output_json",
                            "evidence_span_refs": "evidence_span_refs_json",
                        },
                        json_fields={"artifact_refs", "structured_output", "evidence_span_refs"},
                    )
                )
            )
            db.flush()
            return interpretation

    def list_interpretations(self, artifact_ref: UUID) -> list[InterpretationRecord]:
        with self.store.sessions() as db:
            rows = db.execute(select(InterpretationRecordRow)).scalars().all()
            return [
                _interpretation_from_row(row)
                for row in rows
                if artifact_ref in _uuid_tuple(row.artifact_refs_json)
            ]

    def append_candidate_fact(self, fact: CandidateFactAssertion) -> CandidateFactAssertion:
        with self.store.sessions.begin() as db:
            existing = db.get(CandidateFactAssertionRow, fact.candidate_fact_id)
            if existing is not None:
                restored = _fact_from_row(existing)
                if _candidate_fact_semantics(restored) != _candidate_fact_semantics(fact):
                    raise CandidateConflict("candidate fact identity was reused with different semantics")
                return restored
            db.add(
                CandidateFactAssertionRow(
                    **model_values(
                        fact,
                        rename={
                            "value": "value_json",
                            "source_refs": "source_refs_json",
                            "evidence_span_refs": "evidence_span_refs_json",
                        },
                        json_fields={"value", "source_refs", "evidence_span_refs"},
                    )
                )
            )
            db.flush()
            return fact

    def get_candidate_fact(self, fact_ref: UUID) -> CandidateFactAssertion | None:
        with self.store.sessions() as db:
            row = db.get(CandidateFactAssertionRow, fact_ref)
            return None if row is None else _fact_from_row(row)

    def list_candidate_facts(
        self, candidate_ref: UUID
    ) -> list[CandidateFactAssertion]:
        """Load the immutable fact assertions referenced by one candidate."""
        candidate = self.get_candidate(candidate_ref)
        if candidate is None:
            return []
        with self.store.sessions() as db:
            rows = [
                db.get(CandidateFactAssertionRow, fact_ref)
                for fact_ref in candidate.candidate_fact_refs
            ]
            return [_fact_from_row(row) for row in rows if row is not None]

    def append_candidate_request(
        self, candidate: CandidateAdministrativeRequest
    ) -> CandidateAdministrativeRequest:
        with self.store.sessions.begin() as db:
            existing = db.get(CandidateAdministrativeRequestRow, candidate.candidate_id)
            if existing is not None:
                restored = _candidate_from_row(existing)
                if _candidate_semantics(restored) != _candidate_semantics(candidate):
                    raise CandidateConflict("candidate identity was reused with different semantics")
                return restored
            db.add(
                CandidateAdministrativeRequestRow(
                    **model_values(
                        candidate,
                        rename={
                            "interpretation_refs": "interpretation_refs_json",
                            "candidate_fact_refs": "candidate_fact_refs_json",
                            "source_refs": "source_refs_json",
                        },
                        json_fields={"interpretation_refs", "candidate_fact_refs", "source_refs"},
                    )
                )
            )
            db.flush()
            return candidate

    def get_candidate(self, candidate_ref: UUID) -> CandidateAdministrativeRequest | None:
        with self.store.sessions() as db:
            row = db.get(CandidateAdministrativeRequestRow, candidate_ref)
            return None if row is None else _candidate_from_row(row)

    def list_candidates(
        self,
        *,
        status: CandidateStatus | None = None,
        limit: int = 200,
    ) -> list[CandidateAdministrativeRequest]:
        with self.store.sessions() as db:
            statement = select(CandidateAdministrativeRequestRow).order_by(
                CandidateAdministrativeRequestRow.created_at.desc()
            )
            if status is not None:
                statement = statement.where(
                    CandidateAdministrativeRequestRow.status == status.value
                )
            rows = db.execute(statement.limit(limit)).scalars().all()
            return [_candidate_from_row(row) for row in rows]

    def append_case_update(self, update: CandidateCaseUpdate) -> CandidateCaseUpdate:
        with self.store.sessions.begin() as db:
            db.add(
                CandidateCaseUpdateRow(
                    **model_values(
                        update,
                        rename={
                            "interpretation_refs": "interpretation_refs_json",
                            "candidate_fact_refs": "candidate_fact_refs_json",
                            "source_refs": "source_refs_json",
                        },
                        json_fields={"interpretation_refs", "candidate_fact_refs", "source_refs"},
                    )
                )
            )
            db.flush()
            return update

    def append_assessment(self, assessment: IntakeAssessment) -> IntakeAssessment:
        with self.store.sessions.begin() as db:
            db.add(
                IntakeAssessmentRow(
                    **model_values(
                        assessment, rename={"basis": "basis_json"}, json_fields={"basis"}
                    )
                )
            )
            try:
                db.flush()
            except IntegrityError as exc:
                raise AssessmentConflict(
                    "candidate already has a different final intake assessment"
                ) from exc
            return assessment

    def get_assessment(self, assessment_ref: UUID) -> IntakeAssessment | None:
        with self.store.sessions() as db:
            row = db.get(IntakeAssessmentRow, assessment_ref)
            return None if row is None else _assessment_from_row(row)

    def list_assessments(self, candidate_ref: UUID) -> list[IntakeAssessment]:
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(IntakeAssessmentRow)
                    .where(IntakeAssessmentRow.candidate_ref == candidate_ref)
                    .order_by(IntakeAssessmentRow.created_at)
                )
                .scalars()
                .all()
            )
            return [_assessment_from_row(row) for row in rows]

    def persist_promotion(self, promotion: PromotionRecord) -> PromotionRecord:
        with self.store.sessions.begin() as db:
            existing = db.execute(
                select(PromotionRecordRow).where(
                    PromotionRecordRow.candidate_ref == promotion.candidate_ref
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing_promotion = _promotion_from_row(existing)
                if (
                    existing_promotion.assessment_ref != promotion.assessment_ref
                    or existing_promotion.request_id != promotion.request_id
                    or existing_promotion.ingress_receipt_ref != promotion.ingress_receipt_ref
                    or existing_promotion.promotion_policy_ref != promotion.promotion_policy_ref
                ):
                    raise PromotionConflict("candidate was already promoted with different lineage")
                return existing_promotion
            request_existing = db.execute(
                select(PromotionRecordRow).where(
                    PromotionRecordRow.request_id == promotion.request_id
                )
            ).scalar_one_or_none()
            if request_existing is not None:
                raise PromotionConflict("request was already linked to another promotion")
            db.add(
                PromotionRecordRow(**model_values(promotion))
            )
            try:
                db.flush()
            except IntegrityError as exc:
                raise PromotionConflict("candidate or request was concurrently promoted") from exc
            return promotion

    def get_promotion(self, candidate_ref: UUID) -> PromotionRecord | None:
        with self.store.sessions() as db:
            row = db.execute(
                select(PromotionRecordRow).where(
                    PromotionRecordRow.candidate_ref == candidate_ref
                )
            ).scalar_one_or_none()
            return None if row is None else _promotion_from_row(row)


__all__ = [
    "CandidateAdministrativeRequestRow",
    "CandidateConflict",
    "CandidateCaseUpdateRow",
    "CandidateFactAssertionRow",
    "EvidenceSpanRow",
    "AssessmentConflict",
    "IntakeDeliveryAcceptance",
    "IntakeAssessmentRow",
    "IntakeReceiptConflict",
    "IntakeReceiptRow",
    "IntakeRepository",
    "InterpretationConflict",
    "InterpretationRecordRow",
    "PromotionConflict",
    "PromotionRecordRow",
    "SourceArtifactConflict",
    "SourceArtifactRow",
]
