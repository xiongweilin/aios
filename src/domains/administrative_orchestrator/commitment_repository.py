from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Uuid, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from .commitment_models import (
    CandidateCommitment,
    CandidateCommitmentStatus,
    CommitmentFulfillmentAttestation,
    CommitmentRecord,
    CommunicationDraftRecord,
    CommunicationEffectRecord,
    SpeakerPrincipalResolution,
)

# 导入 row module 以完成 declarative metadata 注册。M9 table
# 会引用 M6 intake artifact 和通用 effect ledger。
from .persistence import Base, SqlStore
from .persistence_mapping import model_from_row, model_values


class CommitmentConflict(RuntimeError):
    """A durable M9 identity was reused with different semantics."""


class CandidateCommitmentRow(Base):
    __tablename__ = "administrative_candidate_commitment"

    candidate_commitment_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_artifact_ref: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_source_artifact.artifact_id"), nullable=False
    )
    interpretation_ref: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_interpretation_record.interpretation_id"), nullable=False
    )
    evidence_span_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    candidate_committer_identity: Mapped[str] = mapped_column(String(512), nullable=False)
    candidate_action: Mapped[str] = mapped_column(String(2000), nullable=False)
    candidate_due_text: Mapped[str | None] = mapped_column(String(512), nullable=True)
    candidate_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    candidate_scope_ref: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    candidate_beneficiary: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    classification: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    superseded_by: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)


class SpeakerPrincipalResolutionRow(Base):
    __tablename__ = "administrative_speaker_principal_resolution"

    resolution_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    candidate_ref: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_candidate_commitment.candidate_commitment_id"),
        nullable=False,
    )
    source_speaker_identity: Mapped[str] = mapped_column(String(512), nullable=False)
    resolved_principal_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    external_subject: Mapped[str] = mapped_column(String(1000), nullable=False)
    basis_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    resolver_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CommitmentRow(Base):
    __tablename__ = "administrative_commitment"

    commitment_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    candidate_ref: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_candidate_commitment.candidate_commitment_id"),
        nullable=False,
        unique=True,
    )
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False, unique=True
    )
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    committer_principal_id: Mapped[str] = mapped_column(String(255), nullable=False)
    committer_external_subject: Mapped[str] = mapped_column(String(1000), nullable=False)
    commitment_action: Mapped[str] = mapped_column(String(2000), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_time_basis: Mapped[str] = mapped_column(String(512), nullable=False)
    scope_ref: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    beneficiary_principal_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fulfillment_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    responsibility_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    responsibility_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    responsibility_admission_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    responsibility_assessment_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    responsibility_proposal_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    responsibility_discharge_assessment_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    responsibility_discharge_decision_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    responsibility_transition_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    was_overdue: Mapped[bool] = mapped_column(nullable=False, default=False)


class CommitmentFulfillmentAttestationRow(Base):
    __tablename__ = "administrative_commitment_fulfillment_attestation"

    attestation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    commitment_version: Mapped[int] = mapped_column(Integer, nullable=False)
    principal_id: Mapped[str] = mapped_column(String(255), nullable=False)
    disposition: Mapped[str] = mapped_column(String(64), nullable=False)
    basis_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    attested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CommunicationDraftRow(Base):
    __tablename__ = "administrative_communication_draft"

    draft_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    recipient_principal_id: Mapped[str] = mapped_column(String(255), nullable=False)
    recipient_external_subject: Mapped[str] = mapped_column(String(1000), nullable=False)
    content_storage_ref: Mapped[str] = mapped_column(String(2000), nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    content_size: Mapped[int] = mapped_column(Integer, nullable=False)
    draft_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    generator_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    superseded_by: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)


class CommunicationEffectRow(Base):
    __tablename__ = "administrative_communication_effect"

    communication_event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    draft_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_communication_draft.draft_id"), nullable=False
    )
    effect_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_effect.effect_id"), nullable=False, unique=True
    )
    delivery_state: Mapped[str] = mapped_column(String(64), nullable=False)
    read_state: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_message_ref: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CommitmentRepository:
    def __init__(self, store: SqlStore) -> None:
        self.store = store

    def put_candidate(self, candidate: CandidateCommitment) -> CandidateCommitment:
        with self.store.sessions.begin() as db:
            row = db.get(CandidateCommitmentRow, candidate.candidate_commitment_id)
            if row is not None:
                restored = self._candidate_from_row(row)
                if restored != candidate:
                    raise CommitmentConflict("candidate commitment identity was reused")
                return restored
            db.add(self._candidate_row(candidate))
            try:
                db.flush()
            except IntegrityError as exc:
                raise CommitmentConflict("candidate commitment persistence conflicted") from exc
        return candidate

    def get_candidate(self, candidate_id: UUID) -> CandidateCommitment | None:
        with self.store.sessions() as db:
            row = db.get(CandidateCommitmentRow, candidate_id)
            return None if row is None else self._candidate_from_row(row)

    def list_candidates(
        self,
        *,
        status: CandidateCommitmentStatus | None = None,
        limit: int = 200,
    ) -> list[CandidateCommitment]:
        with self.store.sessions() as db:
            statement = select(CandidateCommitmentRow).order_by(
                CandidateCommitmentRow.created_at.desc()
            ).limit(limit)
            if status is not None:
                statement = statement.where(CandidateCommitmentRow.status == status.value)
            return [self._candidate_from_row(row) for row in db.execute(statement).scalars()]

    def update_candidate_status(
        self,
        candidate_id: UUID,
        *,
        status: CandidateCommitmentStatus,
        superseded_by: UUID | None = None,
    ) -> CandidateCommitment:
        with self.store.sessions.begin() as db:
            row = db.get(CandidateCommitmentRow, candidate_id)
            if row is None:
                raise KeyError(f"candidate commitment {candidate_id} not found")
            row.status = status.value
            row.superseded_by = superseded_by
            return self._candidate_from_row(row)

    def put_resolution(self, resolution: SpeakerPrincipalResolution) -> SpeakerPrincipalResolution:
        with self.store.sessions.begin() as db:
            row = db.get(SpeakerPrincipalResolutionRow, resolution.resolution_id)
            if row is not None:
                restored = self._resolution_from_row(row)
                if restored != resolution:
                    raise CommitmentConflict("speaker resolution identity was reused")
                return restored
            existing = (
                db.execute(
                    select(SpeakerPrincipalResolutionRow).where(
                        SpeakerPrincipalResolutionRow.candidate_ref == resolution.candidate_ref
                    )
                )
                .scalars()
                .first()
            )
            if existing is not None:
                restored = self._resolution_from_row(existing)
                if restored != resolution:
                    raise CommitmentConflict("candidate already has a different speaker resolution")
                return restored
            db.add(self._resolution_row(resolution))
        return resolution

    def get_resolution(self, candidate_id: UUID) -> SpeakerPrincipalResolution | None:
        with self.store.sessions() as db:
            row = (
                db.execute(
                    select(SpeakerPrincipalResolutionRow).where(
                        SpeakerPrincipalResolutionRow.candidate_ref == candidate_id
                    )
                )
                .scalars()
                .first()
            )
            return None if row is None else self._resolution_from_row(row)

    def put_commitment(self, commitment: CommitmentRecord) -> CommitmentRecord:
        with self.store.sessions.begin() as db:
            row = db.get(CommitmentRow, commitment.commitment_id)
            if row is not None:
                restored = self._commitment_from_row(row)
                if restored != commitment:
                    raise CommitmentConflict("commitment identity was reused")
                return restored
            existing = (
                db.execute(
                    select(CommitmentRow).where(CommitmentRow.candidate_ref == commitment.candidate_ref)
                )
                .scalars()
                .first()
            )
            if existing is not None:
                restored = self._commitment_from_row(existing)
                if restored != commitment:
                    raise CommitmentConflict("candidate already has a different commitment")
                return restored
            db.add(self._commitment_row(commitment))
        return commitment

    def get_commitment(self, case_id: UUID) -> CommitmentRecord | None:
        with self.store.sessions() as db:
            row = (
                db.execute(select(CommitmentRow).where(CommitmentRow.case_id == case_id))
                .scalars()
                .first()
            )
            return None if row is None else self._commitment_from_row(row)

    def get_commitment_for_candidate(self, candidate_id: UUID) -> CommitmentRecord | None:
        with self.store.sessions() as db:
            row = (
                db.execute(
                    select(CommitmentRow).where(CommitmentRow.candidate_ref == candidate_id)
                )
                .scalars()
                .first()
            )
            return None if row is None else self._commitment_from_row(row)

    def update_commitment(self, commitment: CommitmentRecord) -> CommitmentRecord:
        with self.store.sessions.begin() as db:
            row = db.get(CommitmentRow, commitment.commitment_id)
            if row is None:
                raise KeyError(f"commitment {commitment.commitment_id} not found")
            if row.version != commitment.version:
                raise CommitmentConflict("commitment version changed")
            updated = commitment.model_copy(update={"version": commitment.version + 1})
            for key, value in model_values(updated, exclude={"commitment_id", "candidate_ref", "case_id"}).items():
                setattr(row, key, value)
            db.flush()
            return self._commitment_from_row(row)

    def put_attestation(self, attestation: CommitmentFulfillmentAttestation) -> CommitmentFulfillmentAttestation:
        with self.store.sessions.begin() as db:
            row = db.get(CommitmentFulfillmentAttestationRow, attestation.attestation_id)
            if row is not None:
                restored = self._attestation_from_row(row)
                if restored != attestation:
                    raise CommitmentConflict("attestation identity was reused")
                return restored
            existing = (
                db.execute(
                    select(CommitmentFulfillmentAttestationRow).where(
                        CommitmentFulfillmentAttestationRow.case_id == attestation.case_id,
                        CommitmentFulfillmentAttestationRow.commitment_version
                        == attestation.commitment_version,
                    )
                )
                .scalars()
                .first()
            )
            if existing is not None:
                restored = self._attestation_from_row(existing)
                if restored != attestation:
                    raise CommitmentConflict("commitment already has a different attestation")
                return restored
            db.add(self._attestation_row(attestation))
        return attestation

    def get_attestation(self, case_id: UUID, commitment_version: int) -> CommitmentFulfillmentAttestation | None:
        with self.store.sessions() as db:
            row = (
                db.execute(
                    select(CommitmentFulfillmentAttestationRow).where(
                        CommitmentFulfillmentAttestationRow.case_id == case_id,
                        CommitmentFulfillmentAttestationRow.commitment_version == commitment_version,
                    )
                )
                .scalars()
                .first()
            )
            return None if row is None else self._attestation_from_row(row)

    def put_draft(self, draft: CommunicationDraftRecord) -> CommunicationDraftRecord:
        with self.store.sessions.begin() as db:
            row = db.get(CommunicationDraftRow, draft.draft_id)
            if row is not None:
                restored = self._draft_from_row(row)
                if restored != draft:
                    raise CommitmentConflict("communication draft identity was reused")
                return restored
            db.add(self._draft_row(draft))
        return draft

    def get_draft(self, draft_id: UUID) -> CommunicationDraftRecord | None:
        with self.store.sessions() as db:
            row = db.get(CommunicationDraftRow, draft_id)
            return None if row is None else self._draft_from_row(row)

    def put_communication(self, communication: CommunicationEffectRecord) -> CommunicationEffectRecord:
        with self.store.sessions.begin() as db:
            row = db.get(CommunicationEffectRow, communication.communication_event_id)
            if row is not None:
                restored = self._communication_from_row(row)
                if restored != communication:
                    raise CommitmentConflict("communication event identity was reused")
                return restored
            existing = (
                db.execute(
                    select(CommunicationEffectRow).where(
                        CommunicationEffectRow.effect_id == communication.effect_id
                    )
                )
                .scalars()
                .first()
            )
            if existing is not None:
                restored = self._communication_from_row(existing)
                if restored != communication:
                    raise CommitmentConflict("effect already has a different communication event")
                return restored
            db.add(self._communication_row(communication))
        return communication

    def get_communication(self, effect_id: UUID) -> CommunicationEffectRecord | None:
        with self.store.sessions() as db:
            row = (
                db.execute(
                    select(CommunicationEffectRow).where(
                        CommunicationEffectRow.effect_id == effect_id
                    )
                )
                .scalars()
                .first()
            )
            return None if row is None else self._communication_from_row(row)

    def get_communication_event(self, communication_event_id: UUID) -> CommunicationEffectRecord | None:
        with self.store.sessions() as db:
            row = db.get(CommunicationEffectRow, communication_event_id)
            return None if row is None else self._communication_from_row(row)

    def list_communications(
        self,
        case_id: UUID,
        *,
        authority_epoch: int | None = None,
    ) -> list[CommunicationEffectRecord]:
        with self.store.sessions() as db:
            statement = (
                select(CommunicationEffectRow)
                .where(CommunicationEffectRow.case_id == case_id)
                .order_by(CommunicationEffectRow.created_at, CommunicationEffectRow.communication_event_id)
            )
            if authority_epoch is not None:
                statement = statement.where(
                    CommunicationEffectRow.authority_epoch == authority_epoch
                )
            return [
                self._communication_from_row(row)
                for row in db.execute(statement).scalars().all()
            ]

    def update_communication(self, communication: CommunicationEffectRecord) -> CommunicationEffectRecord:
        with self.store.sessions.begin() as db:
            row = db.get(CommunicationEffectRow, communication.communication_event_id)
            if row is None:
                raise KeyError(f"communication event {communication.communication_event_id} not found")
            for key, value in model_values(communication, exclude={"communication_event_id"}).items():
                setattr(row, key, value)
            db.flush()
            return self._communication_from_row(row)

    @staticmethod
    def _candidate_row(item: CandidateCommitment) -> CandidateCommitmentRow:
        return CandidateCommitmentRow(
            **model_values(
                item,
                rename={"evidence_span_refs": "evidence_span_refs_json"},
                json_fields={"evidence_span_refs"},
            )
        )

    @staticmethod
    def _candidate_from_row(row: CandidateCommitmentRow) -> CandidateCommitment:
        return model_from_row(
            CandidateCommitment,
            row,
            evidence_span_refs=row.evidence_span_refs_json,
        )

    @staticmethod
    def _resolution_row(item: SpeakerPrincipalResolution) -> SpeakerPrincipalResolutionRow:
        return SpeakerPrincipalResolutionRow(
            **model_values(item, rename={"basis": "basis_json"}, json_fields={"basis"})
        )

    @staticmethod
    def _resolution_from_row(row: SpeakerPrincipalResolutionRow) -> SpeakerPrincipalResolution:
        return model_from_row(SpeakerPrincipalResolution, row, basis=row.basis_json)

    @staticmethod
    def _commitment_row(item: CommitmentRecord) -> CommitmentRow:
        return CommitmentRow(**model_values(item))

    @staticmethod
    def _commitment_from_row(row: CommitmentRow) -> CommitmentRecord:
        return model_from_row(CommitmentRecord, row)

    @staticmethod
    def _attestation_row(
        item: CommitmentFulfillmentAttestation,
    ) -> CommitmentFulfillmentAttestationRow:
        return CommitmentFulfillmentAttestationRow(
            **model_values(item, rename={"basis": "basis_json"}, json_fields={"basis"})
        )

    @staticmethod
    def _attestation_from_row(
        row: CommitmentFulfillmentAttestationRow,
    ) -> CommitmentFulfillmentAttestation:
        return model_from_row(CommitmentFulfillmentAttestation, row, basis=row.basis_json)

    @staticmethod
    def _draft_row(item: CommunicationDraftRecord) -> CommunicationDraftRow:
        return CommunicationDraftRow(**model_values(item))

    @staticmethod
    def _draft_from_row(row: CommunicationDraftRow) -> CommunicationDraftRecord:
        return model_from_row(CommunicationDraftRecord, row)

    @staticmethod
    def _communication_row(item: CommunicationEffectRecord) -> CommunicationEffectRow:
        return CommunicationEffectRow(**model_values(item))

    @staticmethod
    def _communication_from_row(row: CommunicationEffectRow) -> CommunicationEffectRecord:
        return model_from_row(CommunicationEffectRecord, row)


__all__ = ["CommitmentConflict", "CommitmentRepository"]
