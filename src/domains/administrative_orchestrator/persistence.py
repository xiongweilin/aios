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
    Decision,
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
        # 在 metadata 创建前导入 optional domain row module，使
        # 直接 in-memory/test store 获得与
        # application entrypoint 相同的 table topology。
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


# 在 shared metadata 中注册 Intake Plane table，同时不移动
# 本 module 中已经稳定的 M0-M5 persistence definition。Import
# 发生在 Base 和 SqlStore 完全初始化之后，因此 intake/repository.py
# 可以安全复用现有 database/session boundary。
from . import transaction_repository as _transaction_repository  # noqa: E402, F401
from .intake import document_repository as _document_repository  # noqa: E402, F401
from .intake import repository as _intake_repository  # noqa: E402, F401
