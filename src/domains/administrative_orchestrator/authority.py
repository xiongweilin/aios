from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import BaseModel, Field
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Uuid, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import (
    Decision,
    Delegation,
    PolicyRef,
    Principal,
    PrincipalKind,
    RoleAssignment,
    UtcModel,
    normalize_datetime,
    utcnow,
)
from .persistence import Base, SqlStore
from .policy import PolicyEvaluation


class AuthorityError(ValueError):
    pass


class IdentityBinding(UtcModel):
    binding_id: UUID = Field(default_factory=uuid4)
    provider: str
    external_subject: str
    principal_id: str
    valid_from: datetime = Field(default_factory=utcnow)
    valid_until: datetime | None = None

    def is_current_at(self, at: datetime) -> bool:
        at = normalize_datetime(at)
        return self.valid_from <= at and (self.valid_until is None or at < self.valid_until)


class DecisionAuthorityBinding(UtcModel):
    decision_id: UUID
    decision_role: str
    organization_scope: str
    authenticated_principal_id: str
    bound_at: datetime = Field(default_factory=utcnow)


class ApprovalSatisfaction(UtcModel):
    satisfaction_id: UUID
    case_id: UUID
    authority_epoch: int
    policy_ref: PolicyRef
    decision_ids: tuple[UUID, ...]
    satisfied_roles: tuple[str, ...]
    assessed_at: datetime = Field(default_factory=utcnow)


class ApprovalAssessment(BaseModel):
    satisfied: bool
    required_roles: tuple[str, ...]
    missing_roles: tuple[str, ...] = ()
    distinct_principals_required: bool = False
    selected_decision_ids: tuple[UUID, ...] = ()
    selected_principal_ids: tuple[str, ...] = ()
    satisfaction: ApprovalSatisfaction | None = None


class PrincipalRow(Base):
    __tablename__ = "administrative_principal"

    principal_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class IdentityBindingRow(Base):
    __tablename__ = "administrative_identity_binding"

    binding_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    provider: Mapped[str] = mapped_column(String(255), nullable=False)
    external_subject: Mapped[str] = mapped_column(String(512), nullable=False)
    principal_id: Mapped[str] = mapped_column(
        ForeignKey("administrative_principal.principal_id"), nullable=False
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RoleAssignmentRow(Base):
    __tablename__ = "administrative_role_assignment"

    assignment_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    principal_id: Mapped[str] = mapped_column(
        ForeignKey("administrative_principal.principal_id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(128), nullable=False)
    organization_scope: Mapped[str] = mapped_column(String(512), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DelegationRow(Base):
    __tablename__ = "administrative_delegation"

    delegation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    from_principal_id: Mapped[str] = mapped_column(
        ForeignKey("administrative_principal.principal_id"), nullable=False
    )
    to_principal_id: Mapped[str] = mapped_column(
        ForeignKey("administrative_principal.principal_id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(128), nullable=False)
    organization_scope: Mapped[str] = mapped_column(String(512), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DecisionAuthorityBindingRow(Base):
    __tablename__ = "administrative_decision_authority_binding"

    decision_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_decision.decision_id"), primary_key=True
    )
    decision_role: Mapped[str] = mapped_column(String(128), nullable=False)
    organization_scope: Mapped[str] = mapped_column(String(512), nullable=False)
    authenticated_principal_id: Mapped[str] = mapped_column(
        ForeignKey("administrative_principal.principal_id"), nullable=False
    )
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ApprovalSatisfactionRow(Base):
    __tablename__ = "administrative_approval_satisfaction"

    satisfaction_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    decision_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    satisfied_roles_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuthorityRepository:
    def __init__(self, store: SqlStore) -> None:
        self.store = store

    def put_principal(self, principal: Principal, *, active: bool = True) -> Principal:
        with self.store.sessions.begin() as db:
            row = db.get(PrincipalRow, principal.principal_id)
            if row is None:
                db.add(
                    PrincipalRow(
                        principal_id=principal.principal_id,
                        kind=principal.kind.value,
                        display_name=principal.display_name,
                        active=active,
                    )
                )
            else:
                row.kind = principal.kind.value
                row.display_name = principal.display_name
                row.active = active
        return principal

    def get_principal(self, principal_id: str) -> Principal | None:
        with self.store.sessions() as db:
            row = db.get(PrincipalRow, principal_id)
            if row is None or not row.active:
                return None
            return Principal(
                principal_id=row.principal_id,
                kind=PrincipalKind(row.kind),
                display_name=row.display_name,
            )

    def put_identity_binding(self, binding: IdentityBinding) -> IdentityBinding:
        with self.store.sessions.begin() as db:
            duplicates = (
                db.execute(
                    select(IdentityBindingRow).where(
                        IdentityBindingRow.provider == binding.provider,
                        IdentityBindingRow.external_subject == binding.external_subject,
                    )
                )
                .scalars()
                .all()
            )
            for row in duplicates:
                restored = self._binding_from_row(row)
                if (
                    restored.principal_id != binding.principal_id
                    or restored.valid_from != binding.valid_from
                    or restored.valid_until != binding.valid_until
                ):
                    raise AuthorityError(
                        "external identity is already bound with different semantics"
                    )
                return restored
            db.add(
                IdentityBindingRow(
                    binding_id=binding.binding_id,
                    provider=binding.provider,
                    external_subject=binding.external_subject,
                    principal_id=binding.principal_id,
                    valid_from=binding.valid_from,
                    valid_until=binding.valid_until,
                )
            )
        return binding

    def resolve_identity(
        self,
        *,
        provider: str,
        external_subject: str,
        at: datetime | None = None,
    ) -> Principal | None:
        at = normalize_datetime(at or utcnow())
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(IdentityBindingRow).where(
                        IdentityBindingRow.provider == provider,
                        IdentityBindingRow.external_subject == external_subject,
                    )
                )
                .scalars()
                .all()
            )
            current = [self._binding_from_row(row) for row in rows]
            current = [binding for binding in current if binding.is_current_at(at)]
            if len(current) != 1:
                return None
            principal_row = db.get(PrincipalRow, current[0].principal_id)
            if principal_row is None or not principal_row.active:
                return None
            return Principal(
                principal_id=principal_row.principal_id,
                kind=PrincipalKind(principal_row.kind),
                display_name=principal_row.display_name,
            )

    def put_role_assignment(self, assignment: RoleAssignment) -> RoleAssignment:
        with self.store.sessions.begin() as db:
            row = db.get(RoleAssignmentRow, assignment.assignment_id)
            if row is not None:
                restored = self._assignment_from_row(row)
                if restored != assignment:
                    raise AuthorityError("role assignment id already exists with different semantics")
                return restored
            db.add(
                RoleAssignmentRow(
                    assignment_id=assignment.assignment_id,
                    principal_id=assignment.principal_id,
                    role=assignment.role,
                    organization_scope=assignment.organization_scope,
                    valid_from=assignment.valid_from,
                    valid_until=assignment.valid_until,
                )
            )
        return assignment

    def put_delegation(self, delegation: Delegation) -> Delegation:
        with self.store.sessions.begin() as db:
            row = db.get(DelegationRow, delegation.delegation_id)
            if row is not None:
                restored = self._delegation_from_row(row)
                if restored != delegation:
                    raise AuthorityError("delegation id already exists with different semantics")
                return restored
            db.add(
                DelegationRow(
                    delegation_id=delegation.delegation_id,
                    from_principal_id=delegation.from_principal_id,
                    to_principal_id=delegation.to_principal_id,
                    role=delegation.role,
                    organization_scope=delegation.organization_scope,
                    valid_from=delegation.valid_from,
                    valid_until=delegation.valid_until,
                )
            )
        return delegation

    def list_current_identity_bindings(
        self,
        principal_id: str,
        *,
        at: datetime | None = None,
    ) -> tuple[IdentityBinding, ...]:
        at = normalize_datetime(at or utcnow())
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(IdentityBindingRow).where(
                        IdentityBindingRow.principal_id == principal_id
                    )
                )
                .scalars()
                .all()
            )
            return tuple(
                binding
                for binding in (self._binding_from_row(row) for row in rows)
                if binding.is_current_at(at)
            )

    def list_current_role_assignments(
        self,
        principal_id: str,
        *,
        at: datetime | None = None,
    ) -> tuple[RoleAssignment, ...]:
        at = normalize_datetime(at or utcnow())
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(RoleAssignmentRow).where(
                        RoleAssignmentRow.principal_id == principal_id
                    )
                )
                .scalars()
                .all()
            )
            return tuple(
                assignment
                for assignment in (self._assignment_from_row(row) for row in rows)
                if assignment.is_current_at(at)
            )

    def list_current_delegations_involving(
        self,
        principal_id: str,
        *,
        at: datetime | None = None,
    ) -> tuple[Delegation, ...]:
        at = normalize_datetime(at or utcnow())
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(DelegationRow).where(
                        (DelegationRow.from_principal_id == principal_id)
                        | (DelegationRow.to_principal_id == principal_id)
                    )
                )
                .scalars()
                .all()
            )
            return tuple(
                delegation
                for delegation in (self._delegation_from_row(row) for row in rows)
                if delegation.valid_from <= at < delegation.valid_until
            )

    def roles_for(
        self,
        principal_id: str,
        *,
        organization_scope: str,
        at: datetime | None = None,
    ) -> set[str]:
        at = normalize_datetime(at or utcnow())
        with self.store.sessions() as db:
            direct_rows = (
                db.execute(
                    select(RoleAssignmentRow).where(RoleAssignmentRow.principal_id == principal_id)
                )
                .scalars()
                .all()
            )
            direct = [self._assignment_from_row(row) for row in direct_rows]
            roles = {
                assignment.role
                for assignment in direct
                if assignment.is_current_at(at)
                and _scope_matches(assignment.organization_scope, organization_scope)
            }

            delegation_rows = (
                db.execute(
                    select(DelegationRow).where(DelegationRow.to_principal_id == principal_id)
                )
                .scalars()
                .all()
            )
            for row in delegation_rows:
                delegation = self._delegation_from_row(row)
                if not (
                    delegation.valid_from <= at < delegation.valid_until
                    and _scope_matches(delegation.organization_scope, organization_scope)
                ):
                    continue
                source_rows = (
                    db.execute(
                        select(RoleAssignmentRow).where(
                            RoleAssignmentRow.principal_id == delegation.from_principal_id,
                            RoleAssignmentRow.role == delegation.role,
                        )
                    )
                    .scalars()
                    .all()
                )
                source_assignments = [self._assignment_from_row(item) for item in source_rows]
                if any(
                    assignment.is_current_at(at)
                    and _scope_matches(assignment.organization_scope, organization_scope)
                    for assignment in source_assignments
                ):
                    roles.add(delegation.role)
            return roles

    def put_decision_binding(
        self,
        decision: Decision,
        *,
        organization_scope: str,
        db: Session | None = None,
    ) -> DecisionAuthorityBinding:
        if decision.decision_role is None:
            raise AuthorityError("accepted governed decision must record decision_role")
        binding = DecisionAuthorityBinding(
            decision_id=decision.decision_id,
            decision_role=decision.decision_role,
            organization_scope=organization_scope,
            authenticated_principal_id=decision.principal_id,
            bound_at=decision.decided_at,
        )
        if db is not None:
            return self._put_decision_binding_in_session(db, binding)
        with self.store.sessions.begin() as session:
            return self._put_decision_binding_in_session(session, binding)

    def get_decision_binding(self, decision_id: UUID) -> DecisionAuthorityBinding | None:
        with self.store.sessions() as db:
            row = db.get(DecisionAuthorityBindingRow, decision_id)
            return None if row is None else self._decision_binding_from_row(row)

    def put_approval_satisfaction(
        self,
        satisfaction: ApprovalSatisfaction,
        *,
        db: Session | None = None,
    ) -> ApprovalSatisfaction:
        if db is not None:
            return self._put_satisfaction_in_session(db, satisfaction)
        with self.store.sessions.begin() as session:
            return self._put_satisfaction_in_session(session, satisfaction)

    def get_approval_satisfaction(
        self,
        case_id: UUID,
        authority_epoch: int,
    ) -> ApprovalSatisfaction | None:
        with self.store.sessions() as db:
            row = (
                db.execute(
                    select(ApprovalSatisfactionRow)
                    .where(
                        ApprovalSatisfactionRow.case_id == case_id,
                        ApprovalSatisfactionRow.authority_epoch == authority_epoch,
                    )
                    .order_by(ApprovalSatisfactionRow.assessed_at.desc())
                    .limit(1)
                )
                .scalars()
                .first()
            )
            return None if row is None else self._satisfaction_from_row(row)

    def _put_decision_binding_in_session(
        self,
        db: Session,
        binding: DecisionAuthorityBinding,
    ) -> DecisionAuthorityBinding:
        row = db.get(DecisionAuthorityBindingRow, binding.decision_id)
        if row is not None:
            restored = self._decision_binding_from_row(row)
            if restored != binding:
                raise AuthorityError(
                    "decision authority binding already exists with different semantics"
                )
            return restored
        db.add(
            DecisionAuthorityBindingRow(
                decision_id=binding.decision_id,
                decision_role=binding.decision_role,
                organization_scope=binding.organization_scope,
                authenticated_principal_id=binding.authenticated_principal_id,
                bound_at=binding.bound_at,
            )
        )
        return binding

    def _put_satisfaction_in_session(
        self,
        db: Session,
        satisfaction: ApprovalSatisfaction,
    ) -> ApprovalSatisfaction:
        row = db.get(ApprovalSatisfactionRow, satisfaction.satisfaction_id)
        if row is not None:
            restored = self._satisfaction_from_row(row)
            if restored != satisfaction:
                raise AuthorityError(
                    "approval satisfaction id already exists with different semantics"
                )
            return restored
        db.add(
            ApprovalSatisfactionRow(
                satisfaction_id=satisfaction.satisfaction_id,
                case_id=satisfaction.case_id,
                authority_epoch=satisfaction.authority_epoch,
                policy_json=satisfaction.policy_ref.model_dump(mode="json"),
                decision_ids_json=[str(item) for item in satisfaction.decision_ids],
                satisfied_roles_json=list(satisfaction.satisfied_roles),
                assessed_at=satisfaction.assessed_at,
            )
        )
        return satisfaction

    @staticmethod
    def _binding_from_row(row: IdentityBindingRow) -> IdentityBinding:
        return IdentityBinding(
            binding_id=row.binding_id,
            provider=row.provider,
            external_subject=row.external_subject,
            principal_id=row.principal_id,
            valid_from=row.valid_from,
            valid_until=row.valid_until,
        )

    @staticmethod
    def _assignment_from_row(row: RoleAssignmentRow) -> RoleAssignment:
        return RoleAssignment(
            assignment_id=row.assignment_id,
            principal_id=row.principal_id,
            role=row.role,
            organization_scope=row.organization_scope,
            valid_from=row.valid_from,
            valid_until=row.valid_until,
        )

    @staticmethod
    def _delegation_from_row(row: DelegationRow) -> Delegation:
        return Delegation(
            delegation_id=row.delegation_id,
            from_principal_id=row.from_principal_id,
            to_principal_id=row.to_principal_id,
            role=row.role,
            organization_scope=row.organization_scope,
            valid_from=row.valid_from,
            valid_until=row.valid_until,
        )

    @staticmethod
    def _decision_binding_from_row(row: DecisionAuthorityBindingRow) -> DecisionAuthorityBinding:
        return DecisionAuthorityBinding(
            decision_id=row.decision_id,
            decision_role=row.decision_role,
            organization_scope=row.organization_scope,
            authenticated_principal_id=row.authenticated_principal_id,
            bound_at=row.bound_at,
        )

    @staticmethod
    def _satisfaction_from_row(row: ApprovalSatisfactionRow) -> ApprovalSatisfaction:
        return ApprovalSatisfaction(
            satisfaction_id=row.satisfaction_id,
            case_id=row.case_id,
            authority_epoch=row.authority_epoch,
            policy_ref=PolicyRef.model_validate(row.policy_json),
            decision_ids=tuple(UUID(item) for item in row.decision_ids_json),
            satisfied_roles=tuple(row.satisfied_roles_json),
            assessed_at=row.assessed_at,
        )


def resolve_decision_role(
    repository: AuthorityRepository,
    *,
    principal_id: str,
    evaluation: PolicyEvaluation,
    organization_scope: str,
    requested_role: str | None,
    at: datetime | None = None,
) -> str:
    required = tuple(evaluation.required_decision_roles)
    if not required:
        raise AuthorityError("current policy does not admit human decisions")
    eligible = repository.roles_for(
        principal_id,
        organization_scope=organization_scope,
        at=at,
    ).intersection(required)
    if requested_role is not None:
        if requested_role not in required:
            raise AuthorityError("requested decision role is not required by current policy")
        if requested_role not in eligible:
            raise AuthorityError("authenticated principal is not eligible for requested decision role")
        return requested_role
    if len(eligible) != 1:
        raise AuthorityError(
            "decision role is ambiguous or authenticated principal has no eligible required role"
        )
    return next(iter(eligible))


def assess_approval_satisfaction(
    repository: AuthorityRepository,
    *,
    case_id: UUID,
    authority_epoch: int,
    policy_ref: PolicyRef,
    evaluation: PolicyEvaluation,
    decisions: Iterable[Decision],
    organization_scope: str,
) -> ApprovalAssessment:
    required_roles = tuple(evaluation.required_decision_roles)
    candidates: dict[str, list[Decision]] = {role: [] for role in required_roles}
    for decision in decisions:
        if (
            decision.case_id != case_id
            or decision.authority_epoch != authority_epoch
            or decision.policy_ref != policy_ref
            or decision.disposition.value != "approve"
            or decision.decision_role not in candidates
        ):
            continue
        roles = repository.roles_for(
            decision.principal_id,
            organization_scope=organization_scope,
            at=decision.decided_at,
        )
        if decision.decision_role in roles:
            candidates[decision.decision_role].append(decision)

    missing = tuple(role for role in required_roles if not candidates[role])
    distinct = bool(evaluation.require_distinct_decision_principals)
    if missing:
        return ApprovalAssessment(
            satisfied=False,
            required_roles=required_roles,
            missing_roles=missing,
            distinct_principals_required=distinct,
        )

    selected = _select_role_decisions(required_roles, candidates, distinct=distinct)
    if selected is None:
        return ApprovalAssessment(
            satisfied=False,
            required_roles=required_roles,
            missing_roles=(),
            distinct_principals_required=distinct,
        )

    decision_ids = tuple(item.decision_id for item in selected)
    satisfaction_id = uuid5(
        NAMESPACE_URL,
        "administrative:approval-satisfaction:"
        f"{case_id}:{authority_epoch}:"
        + ":".join(sorted(str(item) for item in decision_ids)),
    )
    satisfaction = ApprovalSatisfaction(
        satisfaction_id=satisfaction_id,
        case_id=case_id,
        authority_epoch=authority_epoch,
        policy_ref=policy_ref,
        decision_ids=decision_ids,
        satisfied_roles=required_roles,
    )
    return ApprovalAssessment(
        satisfied=True,
        required_roles=required_roles,
        distinct_principals_required=distinct,
        selected_decision_ids=decision_ids,
        selected_principal_ids=tuple(item.principal_id for item in selected),
        satisfaction=satisfaction,
    )


def _select_role_decisions(
    roles: tuple[str, ...],
    candidates: dict[str, list[Decision]],
    *,
    distinct: bool,
) -> tuple[Decision, ...] | None:
    selected: list[Decision] = []
    used_principals: set[str] = set()

    def visit(index: int) -> bool:
        if index == len(roles):
            return True
        role = roles[index]
        for decision in candidates[role]:
            if distinct and decision.principal_id in used_principals:
                continue
            selected.append(decision)
            used_principals.add(decision.principal_id)
            if visit(index + 1):
                return True
            selected.pop()
            if all(item.principal_id != decision.principal_id for item in selected):
                used_principals.discard(decision.principal_id)
        return False

    return tuple(selected) if visit(0) else None


def _scope_matches(assignment_scope: str, requested_scope: str) -> bool:
    return assignment_scope == "*" or assignment_scope == requested_scope


__all__ = [
    "ApprovalAssessment",
    "ApprovalSatisfaction",
    "ApprovalSatisfactionRow",
    "AuthorityError",
    "AuthorityRepository",
    "DecisionAuthorityBinding",
    "DecisionAuthorityBindingRow",
    "DelegationRow",
    "IdentityBinding",
    "IdentityBindingRow",
    "PrincipalRow",
    "RoleAssignmentRow",
    "assess_approval_satisfaction",
    "resolve_decision_role",
]
