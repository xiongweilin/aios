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

# Import row modules for their declarative metadata registration.  M9 tables
# refer to M6 intake artifacts and the generic effect ledger.
from .persistence import Base, SqlStore


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
            for key, value in self._commitment_values(updated).items():
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
            for key, value in self._communication_values(communication).items():
                setattr(row, key, value)
            db.flush()
            return self._communication_from_row(row)

    @staticmethod
    def _candidate_row(item: CandidateCommitment) -> CandidateCommitmentRow:
        return CandidateCommitmentRow(
            candidate_commitment_id=item.candidate_commitment_id,
            source_artifact_ref=item.source_artifact_ref,
            interpretation_ref=item.interpretation_ref,
            evidence_span_refs_json=[str(value) for value in item.evidence_span_refs],
            candidate_committer_identity=item.candidate_committer_identity,
            candidate_action=item.candidate_action,
            candidate_due_text=item.candidate_due_text,
            candidate_due_at=item.candidate_due_at,
            candidate_scope_ref=item.candidate_scope_ref,
            candidate_beneficiary=item.candidate_beneficiary,
            classification=item.classification.value,
            status=item.status.value,
            created_at=item.created_at,
            superseded_by=item.superseded_by,
        )

    @staticmethod
    def _candidate_from_row(row: CandidateCommitmentRow) -> CandidateCommitment:
        return CandidateCommitment(
            candidate_commitment_id=row.candidate_commitment_id,
            source_artifact_ref=row.source_artifact_ref,
            interpretation_ref=row.interpretation_ref,
            evidence_span_refs=tuple(UUID(value) for value in row.evidence_span_refs_json),
            candidate_committer_identity=row.candidate_committer_identity,
            candidate_action=row.candidate_action,
            candidate_due_text=row.candidate_due_text,
            candidate_due_at=row.candidate_due_at,
            candidate_scope_ref=row.candidate_scope_ref,
            candidate_beneficiary=row.candidate_beneficiary,
            classification=row.classification,
            status=row.status,
            created_at=row.created_at,
            superseded_by=row.superseded_by,
        )

    @staticmethod
    def _resolution_row(item: SpeakerPrincipalResolution) -> SpeakerPrincipalResolutionRow:
        return SpeakerPrincipalResolutionRow(
            resolution_id=item.resolution_id,
            candidate_ref=item.candidate_ref,
            source_speaker_identity=item.source_speaker_identity,
            resolved_principal_id=item.resolved_principal_id,
            provider=item.provider,
            external_subject=item.external_subject,
            basis_json=dict(item.basis),
            resolver_type=item.resolver_type,
            resolved_at=item.resolved_at,
        )

    @staticmethod
    def _resolution_from_row(row: SpeakerPrincipalResolutionRow) -> SpeakerPrincipalResolution:
        return SpeakerPrincipalResolution(
            resolution_id=row.resolution_id,
            candidate_ref=row.candidate_ref,
            source_speaker_identity=row.source_speaker_identity,
            resolved_principal_id=row.resolved_principal_id,
            provider=row.provider,
            external_subject=row.external_subject,
            basis=dict(row.basis_json),
            resolver_type=row.resolver_type,
            resolved_at=row.resolved_at,
        )

    @staticmethod
    def _commitment_values(item: CommitmentRecord) -> dict[str, Any]:
        return {
            "authority_epoch": item.authority_epoch,
            "committer_principal_id": item.committer_principal_id,
            "committer_external_subject": item.committer_external_subject,
            "commitment_action": item.commitment_action,
            "due_at": item.due_at,
            "due_time_basis": item.due_time_basis,
            "scope_ref": item.scope_ref,
            "beneficiary_principal_id": item.beneficiary_principal_id,
            "fulfillment_kind": item.fulfillment_kind.value,
            "state": item.state.value,
            "version": item.version,
            "responsibility_ref": item.responsibility_ref,
            "responsibility_version": item.responsibility_version,
            "responsibility_admission_ref": item.responsibility_admission_ref,
            "responsibility_assessment_ref": item.responsibility_assessment_ref,
            "responsibility_proposal_ref": item.responsibility_proposal_ref,
            "responsibility_discharge_assessment_ref": item.responsibility_discharge_assessment_ref,
            "responsibility_discharge_decision_ref": item.responsibility_discharge_decision_ref,
            "responsibility_transition_ref": item.responsibility_transition_ref,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "was_overdue": item.was_overdue,
        }

    @classmethod
    def _commitment_row(cls, item: CommitmentRecord) -> CommitmentRow:
        return CommitmentRow(
            commitment_id=item.commitment_id,
            candidate_ref=item.candidate_ref,
            case_id=item.case_id,
            **cls._commitment_values(item),
        )

    @staticmethod
    def _commitment_from_row(row: CommitmentRow) -> CommitmentRecord:
        return CommitmentRecord(
            commitment_id=row.commitment_id,
            candidate_ref=row.candidate_ref,
            case_id=row.case_id,
            authority_epoch=row.authority_epoch,
            committer_principal_id=row.committer_principal_id,
            committer_external_subject=row.committer_external_subject,
            commitment_action=row.commitment_action,
            due_at=row.due_at,
            due_time_basis=row.due_time_basis,
            scope_ref=row.scope_ref,
            beneficiary_principal_id=row.beneficiary_principal_id,
            fulfillment_kind=row.fulfillment_kind,
            state=row.state,
            version=row.version,
            responsibility_ref=row.responsibility_ref,
            responsibility_version=row.responsibility_version,
            responsibility_admission_ref=row.responsibility_admission_ref,
            responsibility_assessment_ref=row.responsibility_assessment_ref,
            responsibility_proposal_ref=row.responsibility_proposal_ref,
            responsibility_discharge_assessment_ref=row.responsibility_discharge_assessment_ref,
            responsibility_discharge_decision_ref=row.responsibility_discharge_decision_ref,
            responsibility_transition_ref=row.responsibility_transition_ref,
            created_at=row.created_at,
            updated_at=row.updated_at,
            was_overdue=row.was_overdue,
        )

    @staticmethod
    def _attestation_row(item: CommitmentFulfillmentAttestation) -> CommitmentFulfillmentAttestationRow:
        return CommitmentFulfillmentAttestationRow(
            attestation_id=item.attestation_id,
            case_id=item.case_id,
            authority_epoch=item.authority_epoch,
            commitment_version=item.commitment_version,
            principal_id=item.principal_id,
            disposition=item.disposition,
            basis_json=dict(item.basis),
            attested_at=item.attested_at,
        )

    @staticmethod
    def _attestation_from_row(row: CommitmentFulfillmentAttestationRow) -> CommitmentFulfillmentAttestation:
        return CommitmentFulfillmentAttestation(
            attestation_id=row.attestation_id,
            case_id=row.case_id,
            authority_epoch=row.authority_epoch,
            commitment_version=row.commitment_version,
            principal_id=row.principal_id,
            disposition=row.disposition,
            basis=dict(row.basis_json),
            attested_at=row.attested_at,
        )

    @staticmethod
    def _draft_row(item: CommunicationDraftRecord) -> CommunicationDraftRow:
        return CommunicationDraftRow(
            draft_id=item.draft_id,
            case_id=item.case_id,
            authority_epoch=item.authority_epoch,
            channel=item.channel,
            recipient_principal_id=item.recipient_principal_id,
            recipient_external_subject=item.recipient_external_subject,
            content_storage_ref=item.content_storage_ref,
            content_digest=item.content_digest,
            content_size=item.content_size,
            draft_kind=item.draft_kind,
            generator_ref=item.generator_ref,
            created_at=item.created_at,
            superseded_by=item.superseded_by,
        )

    @staticmethod
    def _draft_from_row(row: CommunicationDraftRow) -> CommunicationDraftRecord:
        return CommunicationDraftRecord(
            draft_id=row.draft_id,
            case_id=row.case_id,
            authority_epoch=row.authority_epoch,
            channel=row.channel,
            recipient_principal_id=row.recipient_principal_id,
            recipient_external_subject=row.recipient_external_subject,
            content_storage_ref=row.content_storage_ref,
            content_digest=row.content_digest,
            content_size=row.content_size,
            draft_kind=row.draft_kind,
            generator_ref=row.generator_ref,
            created_at=row.created_at,
            superseded_by=row.superseded_by,
        )

    @staticmethod
    def _communication_values(item: CommunicationEffectRecord) -> dict[str, Any]:
        return {
            "case_id": item.case_id,
            "authority_epoch": item.authority_epoch,
            "draft_id": item.draft_id,
            "effect_id": item.effect_id,
            "delivery_state": item.delivery_state.value,
            "read_state": item.read_state.value,
            "provider_message_ref": item.provider_message_ref,
            "attempts": item.attempts,
            "last_error_code": item.last_error_code,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }

    @classmethod
    def _communication_row(cls, item: CommunicationEffectRecord) -> CommunicationEffectRow:
        return CommunicationEffectRow(
            communication_event_id=item.communication_event_id,
            **cls._communication_values(item),
        )

    @staticmethod
    def _communication_from_row(row: CommunicationEffectRow) -> CommunicationEffectRecord:
        return CommunicationEffectRecord(
            communication_event_id=row.communication_event_id,
            case_id=row.case_id,
            authority_epoch=row.authority_epoch,
            draft_id=row.draft_id,
            effect_id=row.effect_id,
            delivery_state=row.delivery_state,
            read_state=row.read_state,
            provider_message_ref=row.provider_message_ref,
            attempts=row.attempts,
            last_error_code=row.last_error_code,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


__all__ = ["CommitmentConflict", "CommitmentRepository"]
