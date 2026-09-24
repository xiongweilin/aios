from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, model_validator
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Uuid, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .authority import (
    ApprovalSatisfaction,
    DelegationRow,
    PrincipalRow,
    RoleAssignmentRow,
)
from .domain import AdministrativeCase, PolicyRef, UtcModel, normalize_datetime, utcnow
from .persistence import Base, DecisionRow, SqlStore
from .policy_plane import PolicyRepository, PolicyVersionRow
from .transaction_repository import (
    TransactionRecordConflict,
    current_assessments_in_session,
)


class GovernanceError(RuntimeError):
    pass


class GovernanceQualification(UtcModel):
    decision_id: UUID
    principal_id: str
    role: str
    qualification_refs: tuple[str, ...]


class TransactionQualificationBasis(UtcModel):
    assessment_id: UUID
    assessment_kind: str
    assessment_digest: str


class GovernanceBasis(UtcModel):
    basis_id: UUID
    case_id: UUID
    case_version_at_basis: int
    authority_epoch: int
    fact_snapshot_id: UUID
    fact_digest: str
    policy_ref: PolicyRef
    policy_definition_digest: str
    organization_scope: str
    approval_satisfaction_id: UUID
    qualifications: tuple[GovernanceQualification, ...]
    authority_digest: str
    basis_digest: str
    created_at: datetime = Field(default_factory=utcnow)
    fact_dependency_keys: tuple[str, ...] | None = None
    fact_dependency_values: dict[str, Any] = Field(default_factory=dict)
    expected_change_keys: tuple[str, ...] = ()
    transaction_qualifications: tuple[TransactionQualificationBasis, ...] = ()

    @model_validator(mode="after")
    def dependency_scope_is_unambiguous(self) -> GovernanceBasis:
        if self.fact_dependency_keys is not None:
            overlap = set(self.fact_dependency_keys).intersection(
                self.expected_change_keys
            )
            if overlap:
                raise ValueError(
                    "expected self-induced changes cannot be governance "
                    "dependencies: " + ", ".join(sorted(overlap))
                )
        return self


class GovernanceValidation(UtcModel):
    valid: bool
    reasons: tuple[str, ...] = ()
    checked_at: datetime = Field(default_factory=utcnow)


class GovernanceBasisRow(Base):
    __tablename__ = "administrative_governance_basis"

    basis_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    case_version_at_basis: Mapped[int] = mapped_column(Integer, nullable=False)
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    fact_snapshot_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    fact_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    policy_definition_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    organization_scope: Mapped[str] = mapped_column(String(512), nullable=False)
    approval_satisfaction_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, unique=True)
    qualifications_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    transaction_qualifications_json: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True
    )
    authority_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    basis_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fact_dependency_keys_json: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True
    )
    fact_dependency_values_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    expected_change_keys_json: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )


class GovernanceRepository:
    def __init__(self, store: SqlStore) -> None:
        self.store = store

    def create_for_approval(
        self,
        case: AdministrativeCase,
        satisfaction: ApprovalSatisfaction,
        *,
        organization_scope: str,
        fact_dependency_keys: tuple[str, ...] | None = None,
        expected_change_keys: tuple[str, ...] = (),
        db: Session | None = None,
    ) -> GovernanceBasis:
        if case.fact_snapshot is None or case.policy_ref is None:
            raise GovernanceError("governance basis requires current facts and policy")
        if satisfaction.case_id != case.case_id:
            raise GovernanceError("approval satisfaction belongs to another case")
        if satisfaction.authority_epoch != case.authority_epoch:
            raise GovernanceError("approval satisfaction is stale")
        if satisfaction.policy_ref != case.policy_ref:
            raise GovernanceError("approval satisfaction policy is stale")

        if db is not None:
            basis = self._build_basis(
                db,
                case,
                satisfaction,
                organization_scope=organization_scope,
                fact_dependency_keys=fact_dependency_keys,
                expected_change_keys=expected_change_keys,
            )
            return self._put_in_session(db, basis)
        with self.store.sessions.begin() as session:
            basis = self._build_basis(
                session,
                case,
                satisfaction,
                organization_scope=organization_scope,
                fact_dependency_keys=fact_dependency_keys,
                expected_change_keys=expected_change_keys,
            )
            return self._put_in_session(session, basis)

    def get_for_approval(self, approval_satisfaction_id: UUID) -> GovernanceBasis | None:
        with self.store.sessions() as db:
            row = (
                db.execute(
                    select(GovernanceBasisRow).where(
                        GovernanceBasisRow.approval_satisfaction_id == approval_satisfaction_id
                    )
                )
                .scalars()
                .first()
            )
            return None if row is None else self._from_row(row)

    def get_current_for_case(self, case_id: UUID, authority_epoch: int) -> GovernanceBasis | None:
        with self.store.sessions() as db:
            row = (
                db.execute(
                    select(GovernanceBasisRow)
                    .where(
                        GovernanceBasisRow.case_id == case_id,
                        GovernanceBasisRow.authority_epoch == authority_epoch,
                    )
                    .order_by(GovernanceBasisRow.created_at.desc())
                    .limit(1)
                )
                .scalars()
                .first()
            )
            return None if row is None else self._from_row(row)

    def revalidate(
        self,
        basis: GovernanceBasis,
        case: AdministrativeCase,
    ) -> GovernanceValidation:
        reasons: list[str] = []
        if case.case_id != basis.case_id or case.authority_epoch != basis.authority_epoch:
            reasons.append("case authority epoch no longer matches governance basis")
        if case.fact_snapshot is None:
            reasons.append("case no longer has a current fact snapshot")
        else:
            if basis.fact_dependency_keys is None:
                if case.fact_snapshot.snapshot_id != basis.fact_snapshot_id:
                    reasons.append("current fact snapshot differs from governance basis")
                if _digest(case.fact_snapshot.facts) != basis.fact_digest:
                    reasons.append("current fact content differs from governance basis")
            else:
                for key in basis.fact_dependency_keys:
                    if (
                        case.fact_snapshot.facts.get(key)
                        != basis.fact_dependency_values.get(key)
                    ):
                        reasons.append(
                            f"authoritative dependency changed for {key}"
                        )
        if case.policy_ref is None:
            reasons.append("case no longer has a current policy")
        elif case.policy_ref != basis.policy_ref:
            reasons.append("case policy reference differs from governance basis")

        try:
            current_policy = PolicyRepository(self.store).resolve_current(basis.policy_ref.policy_id)
        except Exception as exc:  # fail closed on any policy-plane ambiguity
            reasons.append(f"current policy cannot be resolved: {exc}")
        else:
            if current_policy.policy_ref != basis.policy_ref:
                reasons.append("current effective policy version differs from governance basis")
            if _digest(current_policy.definition) != basis.policy_definition_digest:
                reasons.append("current policy definition differs from governance basis")

        now = utcnow()
        with self.store.sessions() as db:
            try:
                current_transaction_qualifications = self._transaction_qualification_basis(
                    db, case
                )
            except TransactionRecordConflict as exc:
                reasons.append(f"current transaction qualifications are ambiguous: {exc}")
                current_transaction_qualifications = ()
            if (
                basis.transaction_qualifications
                and current_transaction_qualifications != basis.transaction_qualifications
            ):
                reasons.append("transaction qualification basis changed")
            for qualification in basis.qualifications:
                refs = _select_qualification_basis(
                    db,
                    principal_id=qualification.principal_id,
                    role=qualification.role,
                    organization_scope=basis.organization_scope,
                    at=now,
                )
                if refs is None:
                    reasons.append(
                        f"principal {qualification.principal_id} no longer qualifies as "
                        f"{qualification.role}"
                    )
                elif refs != qualification.qualification_refs:
                    reasons.append(
                        f"qualification basis changed for {qualification.principal_id}:"
                        f"{qualification.role}"
                    )

        return GovernanceValidation(valid=not reasons, reasons=tuple(reasons), checked_at=now)

    def bind_current_transaction_qualifications(
        self,
        basis: GovernanceBasis,
        case: AdministrativeCase,
    ) -> GovernanceBasis:
        """Bind qualification evidence immediately before financial effect planning."""

        if basis.case_id != case.case_id or basis.authority_epoch != case.authority_epoch:
            raise GovernanceError("transaction qualification binding is stale")
        with self.store.sessions.begin() as db:
            row = db.get(GovernanceBasisRow, basis.basis_id)
            if row is None:
                raise GovernanceError("governance basis is not persisted")
            restored = self._from_row(row)
            try:
                current = self._transaction_qualification_basis(db, case)
            except TransactionRecordConflict as exc:
                raise GovernanceError(str(exc)) from exc
            if not current:
                return restored
            if restored.transaction_qualifications:
                if restored.transaction_qualifications != current:
                    raise GovernanceError("transaction qualification basis is stale")
                return restored

            updated = restored.model_copy(update={"transaction_qualifications": current})
            basis_payload = {
                "case_id": str(updated.case_id),
                "authority_epoch": updated.authority_epoch,
                "fact_snapshot_id": str(updated.fact_snapshot_id),
                "fact_digest": updated.fact_digest,
                "policy": updated.policy_ref.model_dump(mode="json"),
                "policy_definition_digest": updated.policy_definition_digest,
                "organization_scope": updated.organization_scope,
                "approval_satisfaction_id": str(updated.approval_satisfaction_id),
                "authority_digest": updated.authority_digest,
                "transaction_qualifications": [
                    item.model_dump(mode="json") for item in updated.transaction_qualifications
                ],
            }
            if updated.fact_dependency_keys is not None:
                basis_payload["fact_dependency_keys"] = list(updated.fact_dependency_keys)
                basis_payload["expected_change_keys"] = list(updated.expected_change_keys)
            updated = updated.model_copy(update={"basis_digest": _digest(basis_payload)})
            row.transaction_qualifications_json = [
                item.model_dump(mode="json") for item in updated.transaction_qualifications
            ]
            row.basis_digest = updated.basis_digest
            db.flush()
            return updated

    def _build_basis(
        self,
        db: Session,
        case: AdministrativeCase,
        satisfaction: ApprovalSatisfaction,
        *,
        organization_scope: str,
        fact_dependency_keys: tuple[str, ...] | None = None,
        expected_change_keys: tuple[str, ...] = (),
    ) -> GovernanceBasis:
        assert case.fact_snapshot is not None
        assert case.policy_ref is not None
        policy_row = db.get(
            PolicyVersionRow,
            (case.policy_ref.policy_id, case.policy_ref.version),
        )
        if policy_row is None:
            raise GovernanceError("current policy version is not persisted")

        qualifications: list[GovernanceQualification] = []
        at = satisfaction.assessed_at
        for decision_id in satisfaction.decision_ids:
            decision = db.get(DecisionRow, decision_id)
            if decision is None:
                raise GovernanceError(f"approval decision {decision_id} is not persisted")
            if not decision.decision_role:
                raise GovernanceError("governed approval decision lacks decision_role")
            refs = _select_qualification_basis(
                db,
                principal_id=decision.principal_id,
                role=decision.decision_role,
                organization_scope=organization_scope,
                at=at,
            )
            if refs is None:
                raise GovernanceError(
                    f"principal {decision.principal_id} is not currently qualified as "
                    f"{decision.decision_role}"
                )
            qualifications.append(
                GovernanceQualification(
                    decision_id=decision.decision_id,
                    principal_id=decision.principal_id,
                    role=decision.decision_role,
                    qualification_refs=refs,
                )
            )

        qualifications.sort(key=lambda item: (item.role, item.principal_id, str(item.decision_id)))
        authority_payload = [item.model_dump(mode="json") for item in qualifications]
        authority_digest = _digest(authority_payload)
        fact_digest = _digest(case.fact_snapshot.facts)
        dependency_values = (
            {}
            if fact_dependency_keys is None
            else {
                key: case.fact_snapshot.facts.get(key)
                for key in fact_dependency_keys
            }
        )
        policy_definition_digest = _digest(policy_row.definition_json)
        transaction_qualifications = self._transaction_qualification_basis(db, case)
        basis_payload = {
            "case_id": str(case.case_id),
            "authority_epoch": case.authority_epoch,
            "fact_snapshot_id": str(case.fact_snapshot.snapshot_id),
            "fact_digest": fact_digest,
            "policy": case.policy_ref.model_dump(mode="json"),
            "policy_definition_digest": policy_definition_digest,
            "organization_scope": organization_scope,
            "approval_satisfaction_id": str(satisfaction.satisfaction_id),
            "authority_digest": authority_digest,
            "transaction_qualifications": [
                item.model_dump(mode="json") for item in transaction_qualifications
            ],
        }
        if fact_dependency_keys is not None:
            basis_payload["fact_dependency_keys"] = list(fact_dependency_keys)
            basis_payload["expected_change_keys"] = list(expected_change_keys)
        basis_digest = _digest(basis_payload)
        basis_id = uuid5(
            NAMESPACE_URL,
            f"administrative:governance-basis:{case.case_id}:{case.authority_epoch}:"
            f"{satisfaction.satisfaction_id}",
        )
        return GovernanceBasis(
            basis_id=basis_id,
            case_id=case.case_id,
            case_version_at_basis=case.version,
            authority_epoch=case.authority_epoch,
            fact_snapshot_id=case.fact_snapshot.snapshot_id,
            fact_digest=fact_digest,
            policy_ref=case.policy_ref,
            policy_definition_digest=policy_definition_digest,
            organization_scope=organization_scope,
            approval_satisfaction_id=satisfaction.satisfaction_id,
            qualifications=tuple(qualifications),
            authority_digest=authority_digest,
            basis_digest=basis_digest,
            created_at=at,
            fact_dependency_keys=fact_dependency_keys,
            fact_dependency_values=dependency_values,
            expected_change_keys=expected_change_keys,
            transaction_qualifications=transaction_qualifications,
        )

    @staticmethod
    def _put_in_session(db: Session, basis: GovernanceBasis) -> GovernanceBasis:
        row = db.get(GovernanceBasisRow, basis.basis_id)
        if row is not None:
            restored = GovernanceRepository._from_row(row)
            if restored != basis:
                raise GovernanceError("governance basis id already exists with different semantics")
            return restored
        db.add(
            GovernanceBasisRow(
                basis_id=basis.basis_id,
                case_id=basis.case_id,
                case_version_at_basis=basis.case_version_at_basis,
                authority_epoch=basis.authority_epoch,
                fact_snapshot_id=basis.fact_snapshot_id,
                fact_digest=basis.fact_digest,
                policy_json=basis.policy_ref.model_dump(mode="json"),
                policy_definition_digest=basis.policy_definition_digest,
                organization_scope=basis.organization_scope,
                approval_satisfaction_id=basis.approval_satisfaction_id,
                qualifications_json=[item.model_dump(mode="json") for item in basis.qualifications],
                transaction_qualifications_json=[
                    item.model_dump(mode="json") for item in basis.transaction_qualifications
                ],
                authority_digest=basis.authority_digest,
                basis_digest=basis.basis_digest,
                created_at=basis.created_at,
                fact_dependency_keys_json=(
                    None
                    if basis.fact_dependency_keys is None
                    else list(basis.fact_dependency_keys)
                ),
                fact_dependency_values_json=dict(basis.fact_dependency_values),
                expected_change_keys_json=list(basis.expected_change_keys),
            )
        )
        return basis

    @staticmethod
    def _from_row(row: GovernanceBasisRow) -> GovernanceBasis:
        return GovernanceBasis(
            basis_id=row.basis_id,
            case_id=row.case_id,
            case_version_at_basis=row.case_version_at_basis,
            authority_epoch=row.authority_epoch,
            fact_snapshot_id=row.fact_snapshot_id,
            fact_digest=row.fact_digest,
            policy_ref=PolicyRef.model_validate(row.policy_json),
            policy_definition_digest=row.policy_definition_digest,
            organization_scope=row.organization_scope,
            approval_satisfaction_id=row.approval_satisfaction_id,
            qualifications=tuple(
                GovernanceQualification.model_validate(item) for item in row.qualifications_json
            ),
            authority_digest=row.authority_digest,
            basis_digest=row.basis_digest,
            created_at=row.created_at,
            fact_dependency_keys=(
                None
                if row.fact_dependency_keys_json is None
                else tuple(row.fact_dependency_keys_json)
            ),
            fact_dependency_values=dict(row.fact_dependency_values_json or {}),
            expected_change_keys=tuple(row.expected_change_keys_json or ()),
            transaction_qualifications=tuple(
                TransactionQualificationBasis.model_validate(item)
                for item in (row.transaction_qualifications_json or ())
            ),
        )

    @staticmethod
    def _transaction_qualification_basis(
        db: Session,
        case: AdministrativeCase,
    ) -> tuple[TransactionQualificationBasis, ...]:
        assessments = current_assessments_in_session(db, case.case_id, case.authority_epoch)
        return tuple(
            TransactionQualificationBasis(
                assessment_id=assessment.assessment_id,
                assessment_kind=assessment.assessment_kind,
                assessment_digest=_digest(
                    assessment.model_dump(mode="json", exclude={"assessment_id"})
                ),
            )
            for assessment in sorted(
                assessments,
                key=lambda item: (item.assessment_kind, str(item.assessment_id)),
            )
        )


def _select_qualification_basis(
    db: Session,
    *,
    principal_id: str,
    role: str,
    organization_scope: str,
    at: datetime,
) -> tuple[str, ...] | None:
    at = normalize_datetime(at)
    principal = db.get(PrincipalRow, principal_id)
    if principal is None or not principal.active:
        return None

    direct_rows = (
        db.execute(
            select(RoleAssignmentRow).where(
                RoleAssignmentRow.principal_id == principal_id,
                RoleAssignmentRow.role == role,
            )
        )
        .scalars()
        .all()
    )
    direct = [
        row
        for row in direct_rows
        if _window_current(row.valid_from, row.valid_until, at)
        and _scope_matches(row.organization_scope, organization_scope)
    ]
    if direct:
        chosen = min(direct, key=lambda row: str(row.assignment_id))
        return (f"role:{chosen.assignment_id}",)

    delegation_rows = (
        db.execute(
            select(DelegationRow).where(
                DelegationRow.to_principal_id == principal_id,
                DelegationRow.role == role,
            )
        )
        .scalars()
        .all()
    )
    candidates: list[tuple[str, str]] = []
    for delegation in delegation_rows:
        if not (
            _window_current(delegation.valid_from, delegation.valid_until, at)
            and _scope_matches(delegation.organization_scope, organization_scope)
        ):
            continue
        source_rows = (
            db.execute(
                select(RoleAssignmentRow).where(
                    RoleAssignmentRow.principal_id == delegation.from_principal_id,
                    RoleAssignmentRow.role == role,
                )
            )
            .scalars()
            .all()
        )
        for source in source_rows:
            if _window_current(source.valid_from, source.valid_until, at) and _scope_matches(
                source.organization_scope,
                organization_scope,
            ):
                candidates.append(
                    (f"delegation:{delegation.delegation_id}", f"role:{source.assignment_id}")
                )
    if not candidates:
        return None
    return min(candidates)


def _window_current(
    valid_from: datetime,
    valid_until: datetime | None,
    at: datetime,
) -> bool:
    valid_from = normalize_datetime(valid_from)
    valid_until = normalize_datetime(valid_until) if valid_until is not None else None
    at = normalize_datetime(at)
    return valid_from <= at and (valid_until is None or at < valid_until)


def _scope_matches(assignment_scope: str, requested_scope: str) -> bool:
    return assignment_scope == "*" or assignment_scope == requested_scope


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "GovernanceBasis",
    "GovernanceBasisRow",
    "GovernanceError",
    "GovernanceQualification",
    "GovernanceRepository",
    "GovernanceValidation",
    "TransactionQualificationBasis",
]
