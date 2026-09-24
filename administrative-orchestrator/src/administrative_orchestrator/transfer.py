from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, model_validator
from sqlalchemy import DateTime, ForeignKey, Integer, String, Uuid, select
from sqlalchemy.orm import Mapped, mapped_column

from .authority import AuthorityRepository
from .domain import AdministrativeCase, UtcModel, normalize_datetime, utcnow
from .persistence import Base, SqlStore
from .policy import OffboardingPolicy


class TransferError(RuntimeError):
    pass


class TransferMode(StrEnum):
    REVOKE_ONLY = "revoke_only"
    TRANSFER_REQUIRED = "transfer_required"


class TransferRequirementStatus(StrEnum):
    READY_TO_REVOKE = "ready_to_revoke"
    SUCCESSOR_MISSING = "successor_missing"
    SUCCESSOR_UNQUALIFIED = "successor_unqualified"
    SUCCESSOR_QUALIFIED = "successor_qualified"
    FULFILLED = "fulfilled"


class AdministrativeTransferRequirement(UtcModel):
    requirement_id: UUID
    case_id: UUID
    authority_epoch: int
    governance_basis_id: UUID
    departing_principal_id: str
    relationship_kind: str
    relationship_ref: UUID
    role: str
    organization_scope: str
    transfer_mode: TransferMode
    successor_principal_id: str | None = None
    effective_at: datetime
    status: TransferRequirementStatus
    qualification_reason: str
    created_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def validate_status(self) -> AdministrativeTransferRequirement:
        successor_statuses = {
            TransferRequirementStatus.SUCCESSOR_UNQUALIFIED,
            TransferRequirementStatus.SUCCESSOR_QUALIFIED,
            TransferRequirementStatus.FULFILLED,
        }
        if self.status in successor_statuses and self.successor_principal_id is None:
            raise ValueError("successor status requires successor_principal_id")
        if (
            self.transfer_mode is TransferMode.REVOKE_ONLY
            and self.status is not TransferRequirementStatus.READY_TO_REVOKE
        ):
            raise ValueError("revoke-only requirement must be ready_to_revoke")
        return self


class AdministrativeTransferRequirementRow(Base):
    __tablename__ = "administrative_transfer_requirement"

    requirement_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    governance_basis_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    departing_principal_id: Mapped[str] = mapped_column(String(255), nullable=False)
    relationship_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    relationship_ref: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    role: Mapped[str] = mapped_column(String(128), nullable=False)
    organization_scope: Mapped[str] = mapped_column(String(255), nullable=False)
    transfer_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    successor_principal_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    qualification_reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TransferRequirementRepository:
    def __init__(self, store: SqlStore) -> None:
        self.store = store

    def put_all(
        self, requirements: tuple[AdministrativeTransferRequirement, ...]
    ) -> tuple[AdministrativeTransferRequirement, ...]:
        with self.store.sessions.begin() as db:
            for requirement in requirements:
                row = db.get(
                    AdministrativeTransferRequirementRow, requirement.requirement_id
                )
                if row is not None:
                    restored = self._from_row(row)
                    if self._semantics(restored) != self._semantics(requirement):
                        raise TransferError(
                            "transfer requirement id already exists with different semantics"
                        )
                    continue
                db.add(
                    AdministrativeTransferRequirementRow(
                        requirement_id=requirement.requirement_id,
                        case_id=requirement.case_id,
                        authority_epoch=requirement.authority_epoch,
                        governance_basis_id=requirement.governance_basis_id,
                        departing_principal_id=requirement.departing_principal_id,
                        relationship_kind=requirement.relationship_kind,
                        relationship_ref=requirement.relationship_ref,
                        role=requirement.role,
                        organization_scope=requirement.organization_scope,
                        transfer_mode=requirement.transfer_mode.value,
                        successor_principal_id=requirement.successor_principal_id,
                        effective_at=requirement.effective_at,
                        status=requirement.status.value,
                        qualification_reason=requirement.qualification_reason,
                        created_at=requirement.created_at,
                    )
                )
        return requirements

    def list_for_case(
        self, case_id: UUID, authority_epoch: int
    ) -> tuple[AdministrativeTransferRequirement, ...]:
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(AdministrativeTransferRequirementRow)
                    .where(
                        AdministrativeTransferRequirementRow.case_id == case_id,
                        AdministrativeTransferRequirementRow.authority_epoch
                        == authority_epoch,
                    )
                    .order_by(
                        AdministrativeTransferRequirementRow.relationship_kind,
                        AdministrativeTransferRequirementRow.role,
                        AdministrativeTransferRequirementRow.relationship_ref,
                    )
                )
                .scalars()
                .all()
            )
            return tuple(self._from_row(row) for row in rows)

    def mark_fulfilled(
        self,
        requirement_id: UUID,
        *,
        successor_principal_id: str,
    ) -> AdministrativeTransferRequirement:
        with self.store.sessions.begin() as db:
            row = db.get(AdministrativeTransferRequirementRow, requirement_id)
            if row is None:
                raise TransferError("transfer requirement does not exist")
            current = self._from_row(row)
            if current.transfer_mode is not TransferMode.TRANSFER_REQUIRED:
                raise TransferError("revoke-only requirement cannot be marked transferred")
            if current.successor_principal_id != successor_principal_id:
                raise TransferError("transfer fulfillment successor does not match qualification")
            if current.status is TransferRequirementStatus.FULFILLED:
                return current
            if current.status is not TransferRequirementStatus.SUCCESSOR_QUALIFIED:
                raise TransferError("transfer requirement lacks a qualified successor")
            row.status = TransferRequirementStatus.FULFILLED.value
            row.qualification_reason = (
                "qualified successor role is current in the required organization scope"
            )
            db.flush()
            return self._from_row(row)

    @staticmethod
    def _semantics(requirement: AdministrativeTransferRequirement) -> dict[str, object]:
        return requirement.model_dump(mode="json", exclude={"created_at"})

    @staticmethod
    def _from_row(
        row: AdministrativeTransferRequirementRow,
    ) -> AdministrativeTransferRequirement:
        return AdministrativeTransferRequirement(
            requirement_id=row.requirement_id,
            case_id=row.case_id,
            authority_epoch=row.authority_epoch,
            governance_basis_id=row.governance_basis_id,
            departing_principal_id=row.departing_principal_id,
            relationship_kind=row.relationship_kind,
            relationship_ref=row.relationship_ref,
            role=row.role,
            organization_scope=row.organization_scope,
            transfer_mode=TransferMode(row.transfer_mode),
            successor_principal_id=row.successor_principal_id,
            effective_at=row.effective_at,
            status=TransferRequirementStatus(row.status),
            qualification_reason=row.qualification_reason,
            created_at=row.created_at,
        )


def derive_transfer_requirements(
    case: AdministrativeCase,
    policy: OffboardingPolicy,
    authority: AuthorityRepository,
    *,
    governance_basis_id: UUID,
) -> tuple[AdministrativeTransferRequirement, ...]:
    if case.case_kind != "employee-offboarding":
        raise TransferError("transfer requirements require employee-offboarding case")
    if case.fact_snapshot is None:
        raise TransferError("transfer requirements require current facts")
    facts = case.fact_snapshot.facts
    departing = str(facts.get("departing_principal_id") or "").strip()
    if not departing:
        raise TransferError("departing_principal_id is required")
    try:
        effective_at = normalize_datetime(
            datetime.fromisoformat(
                str(facts[policy.definition.effective_time_fact]).replace("Z", "+00:00")
            )
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise TransferError("qualified termination effective time is required") from exc

    successor = str(facts.get("successor_principal_id") or "").strip() or None
    transfer_roles = set(policy.definition.transfer_required_roles)
    revoke_roles = set(policy.definition.revoke_only_roles)
    requirements: list[AdministrativeTransferRequirement] = []
    for assignment in authority.list_current_role_assignments(
        departing, at=effective_at
    ):
        if assignment.role in transfer_roles:
            mode = TransferMode.TRANSFER_REQUIRED
            status, reason = _qualify_successor(
                authority,
                departing_principal_id=departing,
                successor_principal_id=successor,
                organization_scope=assignment.organization_scope,
                at=effective_at,
            )
        elif assignment.role in revoke_roles:
            mode = TransferMode.REVOKE_ONLY
            status = TransferRequirementStatus.READY_TO_REVOKE
            reason = "policy classifies the role as revoke-only"
        else:
            raise TransferError(
                f"offboarding policy does not classify current role {assignment.role!r}"
            )
        requirement_id = uuid5(
            NAMESPACE_URL,
            f"administrative:transfer:{case.case_id}:{case.authority_epoch}:"
            f"{governance_basis_id}:role_assignment:{assignment.assignment_id}",
        )
        requirements.append(
            AdministrativeTransferRequirement(
                requirement_id=requirement_id,
                case_id=case.case_id,
                authority_epoch=case.authority_epoch,
                governance_basis_id=governance_basis_id,
                departing_principal_id=departing,
                relationship_kind="role_assignment",
                relationship_ref=assignment.assignment_id,
                role=assignment.role,
                organization_scope=assignment.organization_scope,
                transfer_mode=mode,
                successor_principal_id=successor if mode is TransferMode.TRANSFER_REQUIRED else None,
                effective_at=effective_at,
                status=status,
                qualification_reason=reason,
            )
        )
    return tuple(requirements)


def _qualify_successor(
    authority: AuthorityRepository,
    *,
    departing_principal_id: str,
    successor_principal_id: str | None,
    organization_scope: str,
    at: datetime,
) -> tuple[TransferRequirementStatus, str]:
    if successor_principal_id is None:
        return (
            TransferRequirementStatus.SUCCESSOR_MISSING,
            "policy requires a successor but no successor principal was supplied",
        )
    if successor_principal_id == departing_principal_id:
        return (
            TransferRequirementStatus.SUCCESSOR_UNQUALIFIED,
            "successor cannot be the departing principal",
        )
    if authority.get_principal(successor_principal_id) is None:
        return (
            TransferRequirementStatus.SUCCESSOR_UNQUALIFIED,
            "successor principal does not exist or is inactive",
        )
    if not authority.roles_for(
        successor_principal_id, organization_scope=organization_scope, at=at
    ):
        return (
            TransferRequirementStatus.SUCCESSOR_UNQUALIFIED,
            "successor has no current authority in the required organization scope",
        )
    return (
        TransferRequirementStatus.SUCCESSOR_QUALIFIED,
        "successor is active, distinct, and current in the required organization scope",
    )


__all__ = [
    "AdministrativeTransferRequirement",
    "AdministrativeTransferRequirementRow",
    "TransferError",
    "TransferMode",
    "TransferRequirementRepository",
    "TransferRequirementStatus",
    "derive_transfer_requirements",
]
