from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Uuid, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from .domain import (
    AdministrativeCase,
    AdministrativeRequest,
    ConfirmedOutcome,
    Decision,
    EffectRealizationAssessment,
    EffectRecord,
    ExecutionAuthorization,
)
from .policy import PolicyEvaluation


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class RequestRow(Base):
    __tablename__ = "administrative_request"

    request_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    requester_principal_id: Mapped[str] = mapped_column(String(255), nullable=False)
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    intent: Mapped[str] = mapped_column(String(1000), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class CaseRow(Base):
    __tablename__ = "administrative_case"

    case_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    request_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_request.request_id"), nullable=False
    )
    case_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    requester_principal_id: Mapped[str] = mapped_column(String(255), nullable=False)
    subject_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    fact_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    policy_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    reopen_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PolicyEvaluationRow(Base):
    __tablename__ = "administrative_policy_evaluation"

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("administrative_case.case_id"), nullable=False)
    case_version: Mapped[int] = mapped_column(Integer, nullable=False)
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evaluation_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class DecisionRow(Base):
    __tablename__ = "administrative_decision"

    decision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("administrative_case.case_id"), nullable=False)
    case_version: Mapped[int] = mapped_column(Integer, nullable=False)
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    principal_id: Mapped[str] = mapped_column(String(255), nullable=False)
    decision_role: Mapped[str | None] = mapped_column(String(128), nullable=True)
    disposition: Mapped[str] = mapped_column(String(64), nullable=False)
    rationale: Mapped[str] = mapped_column(String(2000), nullable=False)
    policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuthorizationRow(Base):
    __tablename__ = "administrative_execution_authorization"

    authorization_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("administrative_case.case_id"), nullable=False)
    case_version: Mapped[int] = mapped_column(Integer, nullable=False)
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    decision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("administrative_decision.decision_id"), nullable=True
    )
    approval_satisfaction_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    issuer_principal_id: Mapped[str] = mapped_column(String(255), nullable=False)
    target_system: Mapped[str] = mapped_column(String(255), nullable=False)
    subject_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    allowed_operations: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    authority_class: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EffectRow(Base):
    __tablename__ = "administrative_effect"

    effect_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("administrative_case.case_id"), nullable=False)
    case_version: Mapped[int] = mapped_column(Integer, nullable=False)
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    authorization_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_execution_authorization.authorization_id"), nullable=False
    )
    target_system: Mapped[str] = mapped_column(String(255), nullable=False)
    operation: Mapped[str] = mapped_column(String(255), nullable=False)
    subject_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    reversibility: Mapped[str] = mapped_column(String(64), nullable=False)
    authority_class: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RealizationRow(Base):
    __tablename__ = "administrative_effect_realization"

    assessment_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    effect_id: Mapped[UUID] = mapped_column(ForeignKey("administrative_effect.effect_id"))
    disposition: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OutcomeRow(Base):
    __tablename__ = "administrative_confirmed_outcome"

    outcome_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("administrative_case.case_id"), nullable=False)
    case_version: Mapped[int] = mapped_column(Integer, nullable=False)
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    effect_id: Mapped[UUID] = mapped_column(ForeignKey("administrative_effect.effect_id"))
    realization_assessment_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_effect_realization.assessment_id"), nullable=False
    )
    outcome_kind: Mapped[str] = mapped_column(String(255), nullable=False)
    evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditEventRow(Base):
    __tablename__ = "administrative_audit_event"

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("administrative_case.case_id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class ConcurrencyConflict(RuntimeError):
    pass


class SqlStore:
    def __init__(self, database_url: str) -> None:
        if database_url.startswith("sqlite") and ":memory:" in database_url:
            self.engine = create_engine(
                database_url,
                future=True,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        elif database_url.startswith("sqlite"):
            path_text = database_url.split("///", 1)[-1]
            if path_text and path_text != ":memory:":
                Path(path_text).parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(
                database_url,
                future=True,
                connect_args={"check_same_thread": False},
            )
        else:
            self.engine = create_engine(database_url, future=True, pool_pre_ping=True)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    def init_schema(self) -> None:
        # Import optional domain row modules before metadata creation so a
        # direct in-memory/test store gets the same table topology as the
        # application entrypoints.
        from . import investigation_repository as _investigation_repository  # noqa: F401

        Base.metadata.create_all(self.engine)

    def create_case(self, request: AdministrativeRequest, case: AdministrativeCase) -> None:
        with self.sessions.begin() as db:
            db.add(
                RequestRow(
                    request_id=request.request_id,
                    requester_principal_id=request.requester_principal_id,
                    channel=request.channel,
                    intent=request.intent,
                    received_at=request.received_at,
                    source_ref=request.source_ref,
                )
            )
            db.add(self._case_row(case, request.request_id))
            self._append_audit(
                db,
                case.case_id,
                "case.created",
                {
                    "request_id": str(request.request_id),
                    "case_kind": case.case_kind,
                    "case_version": case.version,
                    "authority_epoch": case.authority_epoch,
                    "fact_snapshot_id": (
                        str(case.fact_snapshot.snapshot_id) if case.fact_snapshot else None
                    ),
                },
            )

    def get_case(self, case_id: UUID) -> AdministrativeCase | None:
        with self.sessions() as db:
            row = db.get(CaseRow, case_id)
            return None if row is None else self._case_from_row(row)

    def update_case(
        self,
        case: AdministrativeCase,
        *,
        expected_previous_version: int,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self.sessions.begin() as db:
            row = db.get(CaseRow, case.case_id)
            if row is None:
                raise KeyError(f"case {case.case_id} not found")
            if row.version != expected_previous_version:
                raise ConcurrencyConflict(
                    f"case {case.case_id} version changed: expected "
                    f"{expected_previous_version}, found {row.version}"
                )
            self._copy_case_into_row(row, case)
            self._append_audit(
                db,
                case.case_id,
                event_type,
                {
                    "case_version": case.version,
                    "authority_epoch": case.authority_epoch,
                    "status": case.status.value,
                    **(payload or {}),
                },
            )

    def append_policy_evaluation(
        self,
        case_id: UUID,
        case_version: int,
        authority_epoch: int,
        evaluation: PolicyEvaluation,
    ) -> None:
        with self.sessions.begin() as db:
            db.add(
                PolicyEvaluationRow(
                    case_id=case_id,
                    case_version=case_version,
                    authority_epoch=authority_epoch,
                    policy_json=evaluation.policy_ref.model_dump(mode="json"),
                    evaluation_json=evaluation.model_dump(mode="json"),
                    created_at=utcnow(),
                )
            )
            self._append_audit(
                db,
                case_id,
                "policy.evaluated",
                {
                    "case_version": case_version,
                    "authority_epoch": authority_epoch,
                    "policy_id": evaluation.policy_ref.policy_id,
                    "policy_version": evaluation.policy_ref.version,
                    "disposition": evaluation.disposition.value,
                },
            )

    def get_latest_policy_evaluation(self, case_id: UUID) -> PolicyEvaluation | None:
        with self.sessions() as db:
            row = (
                db.execute(
                    select(PolicyEvaluationRow)
                    .where(PolicyEvaluationRow.case_id == case_id)
                    .order_by(PolicyEvaluationRow.sequence.desc())
                    .limit(1)
                )
                .scalars()
                .first()
            )
            return None if row is None else PolicyEvaluation.model_validate(row.evaluation_json)

    def append_decision(self, decision: Decision) -> None:
        with self.sessions.begin() as db:
            db.add(
                DecisionRow(
                    decision_id=decision.decision_id,
                    case_id=decision.case_id,
                    case_version=decision.case_version,
                    authority_epoch=decision.authority_epoch,
                    principal_id=decision.principal_id,
                    decision_role=decision.decision_role,
                    disposition=decision.disposition.value,
                    rationale=decision.rationale,
                    policy_json=decision.policy_ref.model_dump(mode="json"),
                    decided_at=decision.decided_at,
                )
            )
            self._append_audit(
                db,
                decision.case_id,
                "decision.recorded",
                {
                    "decision_id": str(decision.decision_id),
                    "case_version": decision.case_version,
                    "authority_epoch": decision.authority_epoch,
                    "principal_id": decision.principal_id,
                    "decision_role": decision.decision_role,
                    "disposition": decision.disposition.value,
                    "policy_id": decision.policy_ref.policy_id,
                    "policy_version": decision.policy_ref.version,
                },
            )

    def get_decision(self, decision_id: UUID) -> Decision | None:
        with self.sessions() as db:
            row = db.get(DecisionRow, decision_id)
            if row is None:
                return None
            return Decision.model_validate(
                {
                    "decision_id": row.decision_id,
                    "case_id": row.case_id,
                    "case_version": row.case_version,
                    "authority_epoch": row.authority_epoch,
                    "principal_id": row.principal_id,
                    "decision_role": row.decision_role,
                    "disposition": row.disposition,
                    "rationale": row.rationale,
                    "policy_ref": row.policy_json,
                    "decided_at": row.decided_at,
                }
            )

    def append_authorization(self, authorization: ExecutionAuthorization) -> None:
        with self.sessions.begin() as db:
            db.add(
                AuthorizationRow(
                    authorization_id=authorization.authorization_id,
                    case_id=authorization.case_id,
                    case_version=authorization.case_version,
                    authority_epoch=authorization.authority_epoch,
                    decision_id=authorization.decision_id,
                    approval_satisfaction_id=authorization.approval_satisfaction_id,
                    issuer_principal_id=authorization.issuer_principal_id,
                    target_system=authorization.target_system,
                    subject_ref=authorization.subject_ref,
                    allowed_operations=list(authorization.allowed_operations),
                    authority_class=authorization.authority_class.value,
                    policy_json=authorization.policy_ref.model_dump(mode="json"),
                    issued_at=authorization.issued_at,
                    expires_at=authorization.expires_at,
                    revoked_at=authorization.revoked_at,
                )
            )
            self._append_audit(
                db,
                authorization.case_id,
                "authorization.issued",
                {
                    "authorization_id": str(authorization.authorization_id),
                    "decision_id": (
                        str(authorization.decision_id) if authorization.decision_id else None
                    ),
                    "approval_satisfaction_id": (
                        str(authorization.approval_satisfaction_id)
                        if authorization.approval_satisfaction_id
                        else None
                    ),
                    "case_version": authorization.case_version,
                    "authority_epoch": authorization.authority_epoch,
                    "target_system": authorization.target_system,
                    "allowed_operations": list(authorization.allowed_operations),
                    "authority_class": authorization.authority_class.value,
                },
            )

    def append_effect(self, effect: EffectRecord) -> None:
        with self.sessions.begin() as db:
            db.add(
                EffectRow(
                    effect_id=effect.effect_id,
                    case_id=effect.case_id,
                    case_version=effect.case_version,
                    authority_epoch=effect.authority_epoch,
                    authorization_id=effect.authorization_id,
                    target_system=effect.target_system,
                    operation=effect.operation,
                    subject_ref=effect.subject_ref,
                    reversibility=effect.reversibility.value,
                    authority_class=effect.authority_class.value,
                    status=effect.status.value,
                    provider_ref=effect.provider_ref,
                    created_at=effect.created_at,
                    updated_at=effect.updated_at,
                )
            )
            self._append_audit(
                db,
                effect.case_id,
                "effect.planned",
                {
                    "effect_id": str(effect.effect_id),
                    "authorization_id": str(effect.authorization_id),
                    "case_version": effect.case_version,
                    "authority_epoch": effect.authority_epoch,
                    "target_system": effect.target_system,
                    "operation": effect.operation,
                    "reversibility": effect.reversibility.value,
                    "authority_class": effect.authority_class.value,
                },
            )

    def append_realization(self, assessment: EffectRealizationAssessment, case_id: UUID) -> None:
        with self.sessions.begin() as db:
            db.add(
                RealizationRow(
                    assessment_id=assessment.assessment_id,
                    effect_id=assessment.effect_id,
                    disposition=assessment.disposition.value,
                    evidence_json=[item.model_dump(mode="json") for item in assessment.evidence],
                    assessed_at=assessment.assessed_at,
                )
            )
            self._append_audit(
                db,
                case_id,
                "effect.realization_assessed",
                {
                    "assessment_id": str(assessment.assessment_id),
                    "effect_id": str(assessment.effect_id),
                    "disposition": assessment.disposition.value,
                },
            )

    def append_outcome(self, outcome: ConfirmedOutcome) -> None:
        with self.sessions.begin() as db:
            db.add(
                OutcomeRow(
                    outcome_id=outcome.outcome_id,
                    case_id=outcome.case_id,
                    case_version=outcome.case_version,
                    authority_epoch=outcome.authority_epoch,
                    effect_id=outcome.effect_id,
                    realization_assessment_id=outcome.realization_assessment_id,
                    outcome_kind=outcome.outcome_kind,
                    evidence_json=[item.model_dump(mode="json") for item in outcome.evidence],
                    confirmed_at=outcome.confirmed_at,
                )
            )
            self._append_audit(
                db,
                outcome.case_id,
                "outcome.confirmed",
                {
                    "outcome_id": str(outcome.outcome_id),
                    "effect_id": str(outcome.effect_id),
                    "outcome_kind": outcome.outcome_kind,
                    "case_version": outcome.case_version,
                    "authority_epoch": outcome.authority_epoch,
                },
            )

    def list_audit_events(self, case_id: UUID) -> list[dict[str, Any]]:
        with self.sessions() as db:
            rows = (
                db.execute(
                    select(AuditEventRow)
                    .where(AuditEventRow.case_id == case_id)
                    .order_by(AuditEventRow.sequence)
                )
                .scalars()
                .all()
            )
            return [
                {
                    "sequence": row.sequence,
                    "event_id": str(row.event_id),
                    "event_type": row.event_type,
                    "payload": row.payload_json,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]

    @staticmethod
    def _case_row(case: AdministrativeCase, request_id: UUID) -> CaseRow:
        return CaseRow(
            case_id=case.case_id,
            request_id=request_id,
            case_kind=case.case_kind,
            requester_principal_id=case.requester_principal_id,
            subject_ref=case.subject_ref,
            status=case.status.value,
            version=case.version,
            authority_epoch=case.authority_epoch,
            fact_snapshot_json=(
                case.fact_snapshot.model_dump(mode="json") if case.fact_snapshot else None
            ),
            policy_json=case.policy_ref.model_dump(mode="json") if case.policy_ref else None,
            evidence_json=[item.model_dump(mode="json") for item in case.evidence],
            reopen_reason=case.reopen_reason.value if case.reopen_reason else None,
            created_at=case.created_at,
            updated_at=case.updated_at,
        )

    @staticmethod
    def _copy_case_into_row(row: CaseRow, case: AdministrativeCase) -> None:
        row.case_kind = case.case_kind
        row.requester_principal_id = case.requester_principal_id
        row.subject_ref = case.subject_ref
        row.status = case.status.value
        row.version = case.version
        row.authority_epoch = case.authority_epoch
        row.fact_snapshot_json = (
            case.fact_snapshot.model_dump(mode="json") if case.fact_snapshot else None
        )
        row.policy_json = case.policy_ref.model_dump(mode="json") if case.policy_ref else None
        row.evidence_json = [item.model_dump(mode="json") for item in case.evidence]
        row.reopen_reason = case.reopen_reason.value if case.reopen_reason else None
        row.updated_at = case.updated_at

    @staticmethod
    def _case_from_row(row: CaseRow) -> AdministrativeCase:
        return AdministrativeCase.model_validate(
            {
                "case_id": row.case_id,
                "case_kind": row.case_kind,
                "requester_principal_id": row.requester_principal_id,
                "subject_ref": row.subject_ref,
                "status": row.status,
                "version": row.version,
                "authority_epoch": row.authority_epoch,
                "fact_snapshot": row.fact_snapshot_json,
                "policy_ref": row.policy_json,
                "evidence": row.evidence_json,
                "reopen_reason": row.reopen_reason,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )

    @staticmethod
    def _append_audit(
        db: Session,
        case_id: UUID,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        db.add(
            AuditEventRow(
                event_id=uuid4(),
                case_id=case_id,
                event_type=event_type,
                payload_json=payload,
                created_at=utcnow(),
            )
        )


# Register Intake Plane tables in the shared metadata without moving the
# already-stable M0-M5 persistence definitions out of this module. The import
# occurs after Base and SqlStore are fully initialized, so intake/repository.py
# can safely reuse the existing database/session boundary.
from . import transaction_repository as _transaction_repository  # noqa: E402, F401
from .intake import document_repository as _document_repository  # noqa: E402, F401
from .intake import repository as _intake_repository  # noqa: E402, F401
