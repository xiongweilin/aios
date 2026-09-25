from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import Field
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import AuthorityClass, EffectRecord, UtcModel, utcnow
from .persistence import Base, SqlStore

if TYPE_CHECKING:
    from .authority import AuthorityRepository
    from .domain import AdministrativeCase
    from .policy import OffboardingPolicy, PolicyEvaluation
    from .transfer import AdministrativeTransferRequirement


class ObligationError(RuntimeError):
    pass


class ObligationFulfillmentKind(StrEnum):
    """How one required obligation can be proven complete.

    External reality is proven by a Kernel-owned effect plus independent
    verification; Administrative domain state is proven inside the
    Administrative model. The two are never simulated as each other.
    """

    EXTERNAL_EFFECT_VERIFIED = "external_effect_verified"
    DOMAIN_STATE_VERIFIED = "domain_state_verified"


class AdministrativeObligation(UtcModel):
    obligation_id: UUID
    case_id: UUID
    authority_epoch: int
    governance_basis_id: UUID
    kind: str
    subject_ref: str
    target_system: str
    required_operation: str
    expected_postcondition: dict[str, Any] = Field(default_factory=dict)
    authority_class: AuthorityClass
    required: bool = True
    fulfillment_kind: ObligationFulfillmentKind = ObligationFulfillmentKind.EXTERNAL_EFFECT_VERIFIED


class AdministrativeObligationSet(UtcModel):
    requirement_id: UUID
    case_id: UUID
    authority_epoch: int
    governance_basis_id: UUID
    obligations: tuple[AdministrativeObligation, ...]


# Compatibility alias kept for M5/M6 callers and stored API shapes.
OnboardingObligationSet = AdministrativeObligationSet


class EffectObligationLink(UtcModel):
    effect_id: UUID
    obligation_id: UUID
    governance_basis_id: UUID


class ObligationDomainStateFulfillment(UtcModel):
    """Verified Administrative domain state that fulfils one obligation.

    Used only for DOMAIN_STATE_VERIFIED obligations. It is deliberately not
    an EffectRecord/ConfirmedOutcome pair: internal Administrative state
    changes must not be dressed up as remote provider effects.
    """

    fulfillment_id: UUID
    obligation_id: UUID
    case_id: UUID
    authority_epoch: int
    governance_basis_id: UUID
    fulfillment_kind: ObligationFulfillmentKind = (
        ObligationFulfillmentKind.DOMAIN_STATE_VERIFIED
    )
    verified_by: str
    reason: str
    observed_state_digest: str
    evidence_ref: str | None = None
    observed_at: datetime = Field(default_factory=utcnow)


class ObligationSetRow(Base):
    __tablename__ = "administrative_obligation_set"
    __table_args__ = (
        UniqueConstraint(
            "case_id",
            "authority_epoch",
            name="uq_admin_obligation_set_case_epoch",
        ),
    )

    requirement_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    governance_basis_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)


class ObligationRow(Base):
    __tablename__ = "administrative_obligation"
    __table_args__ = (
        UniqueConstraint(
            "requirement_id",
            "sequence",
            name="uq_admin_obligation_requirement_sequence",
        ),
    )

    obligation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    requirement_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_obligation_set.requirement_id"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    governance_basis_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    kind: Mapped[str] = mapped_column(String(128), nullable=False)
    subject_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    target_system: Mapped[str] = mapped_column(String(255), nullable=False)
    required_operation: Mapped[str] = mapped_column(String(255), nullable=False)
    expected_postcondition_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    authority_class: Mapped[str] = mapped_column(String(64), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fulfillment_kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ObligationFulfillmentKind.EXTERNAL_EFFECT_VERIFIED.value,
        server_default=ObligationFulfillmentKind.EXTERNAL_EFFECT_VERIFIED.value,
    )


class EffectObligationLinkRow(Base):
    __tablename__ = "administrative_effect_obligation_link"

    effect_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_effect.effect_id"), primary_key=True
    )
    obligation_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_obligation.obligation_id"), nullable=False, unique=True
    )
    governance_basis_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)


class ObligationDomainStateFulfillmentRow(Base):
    __tablename__ = "administrative_obligation_fulfillment"

    fulfillment_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    obligation_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_obligation.obligation_id"),
        nullable=False,
        unique=True,
    )
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    governance_basis_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    fulfillment_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    verified_by: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(String(2000), nullable=False)
    observed_state_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_ref: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ObligationRepository:
    def __init__(self, store: SqlStore) -> None:
        self.store = store

    def put(self, obligation_set: OnboardingObligationSet) -> OnboardingObligationSet:
        with self.store.sessions.begin() as db:
            return self.put_in_session(db, obligation_set)

    def put_in_session(
        self,
        db: Session,
        obligation_set: OnboardingObligationSet,
    ) -> OnboardingObligationSet:
        existing_sets = (
            db.execute(
                select(ObligationSetRow).where(
                    ObligationSetRow.case_id == obligation_set.case_id,
                    ObligationSetRow.authority_epoch == obligation_set.authority_epoch,
                )
            )
            .scalars()
            .all()
        )
        if len(existing_sets) > 1:
            raise ObligationError(
                "multiple obligation sets exist for one case and authority epoch"
            )
        if existing_sets:
            restored = self._load_in_session(db, existing_sets[0].requirement_id)
            if restored != obligation_set:
                raise ObligationError(
                    "obligation set already exists with different semantics"
                )
            return restored
        db.add(
            ObligationSetRow(
                requirement_id=obligation_set.requirement_id,
                case_id=obligation_set.case_id,
                authority_epoch=obligation_set.authority_epoch,
                governance_basis_id=obligation_set.governance_basis_id,
            )
        )
        # There are deliberately no ORM relationships between the immutable
        # obligation records. Flush the parent explicitly so PostgreSQL FK
        # ordering does not depend on SQLAlchemy unit-of-work relationship
        # discovery.
        db.flush()
        for sequence, item in enumerate(obligation_set.obligations):
            db.add(
                ObligationRow(
                    obligation_id=item.obligation_id,
                    requirement_id=obligation_set.requirement_id,
                    sequence=sequence,
                    case_id=item.case_id,
                    authority_epoch=item.authority_epoch,
                    governance_basis_id=item.governance_basis_id,
                    kind=item.kind,
                    subject_ref=item.subject_ref,
                    target_system=item.target_system,
                    required_operation=item.required_operation,
                    expected_postcondition_json=dict(item.expected_postcondition),
                    authority_class=item.authority_class.value,
                    required=item.required,
                    fulfillment_kind=item.fulfillment_kind.value,
                )
            )
        try:
            db.flush()
        except IntegrityError as exc:
            raise ObligationError(
                "obligation set concurrently exists for this case and authority epoch"
            ) from exc
        return obligation_set

    def link_effect(
        self,
        effect: EffectRecord,
        obligation: AdministrativeObligation,
    ) -> EffectObligationLink:
        if effect.case_id != obligation.case_id:
            raise ObligationError("effect and obligation belong to different cases")
        if effect.authority_epoch != obligation.authority_epoch:
            raise ObligationError("effect and obligation belong to different authority epochs")
        if (
            effect.target_system != obligation.target_system
            or effect.operation != obligation.required_operation
            or effect.subject_ref != obligation.subject_ref
            or effect.authority_class != obligation.authority_class
        ):
            raise ObligationError("effect does not implement the declared obligation")
        link = EffectObligationLink(
            effect_id=effect.effect_id,
            obligation_id=obligation.obligation_id,
            governance_basis_id=obligation.governance_basis_id,
        )
        with self.store.sessions.begin() as db:
            row = db.get(EffectObligationLinkRow, effect.effect_id)
            if row is not None:
                restored = self._link_from_row(row)
                if restored != link:
                    raise ObligationError("effect already links to a different obligation")
                return restored
            existing_for_obligation = (
                db.execute(
                    select(EffectObligationLinkRow).where(
                        EffectObligationLinkRow.obligation_id == obligation.obligation_id
                    )
                )
                .scalars()
                .first()
            )
            if existing_for_obligation is not None:
                raise ObligationError("obligation already has a different effect")
            db.add(
                EffectObligationLinkRow(
                    effect_id=effect.effect_id,
                    obligation_id=obligation.obligation_id,
                    governance_basis_id=obligation.governance_basis_id,
                )
            )
        return link

    def get_current(self, case_id: UUID, authority_epoch: int) -> OnboardingObligationSet | None:
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(ObligationSetRow)
                    .where(
                        ObligationSetRow.case_id == case_id,
                        ObligationSetRow.authority_epoch == authority_epoch,
                    )
                )
                .scalars()
                .all()
            )
            if len(rows) > 1:
                raise ObligationError(
                    "multiple obligation sets exist for one case and authority epoch"
                )
            return None if not rows else self._load_in_session(db, rows[0].requirement_id)

    def list_links(self, case_id: UUID, authority_epoch: int) -> list[EffectObligationLink]:
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(EffectObligationLinkRow)
                    .join(
                        ObligationRow,
                        ObligationRow.obligation_id == EffectObligationLinkRow.obligation_id,
                    )
                    .where(
                        ObligationRow.case_id == case_id,
                        ObligationRow.authority_epoch == authority_epoch,
                    )
                    .order_by(EffectObligationLinkRow.effect_id)
                )
                .scalars()
                .all()
            )
            return [self._link_from_row(row) for row in rows]

    @staticmethod
    def _load_in_session(db: Session, requirement_id: UUID) -> OnboardingObligationSet:
        row = db.get(ObligationSetRow, requirement_id)
        if row is None:
            raise KeyError(f"obligation set {requirement_id} not found")
        obligation_rows = (
            db.execute(
                select(ObligationRow)
                .where(ObligationRow.requirement_id == requirement_id)
                .order_by(ObligationRow.sequence)
            )
            .scalars()
            .all()
        )
        sequences = [item.sequence for item in obligation_rows]
        if sequences != list(range(len(obligation_rows))):
            raise ObligationError(
                "persisted obligation sequence must be contiguous from zero"
            )
        return OnboardingObligationSet(
            requirement_id=row.requirement_id,
            case_id=row.case_id,
            authority_epoch=row.authority_epoch,
            governance_basis_id=row.governance_basis_id,
            obligations=tuple(
                AdministrativeObligation(
                    obligation_id=item.obligation_id,
                    case_id=item.case_id,
                    authority_epoch=item.authority_epoch,
                    governance_basis_id=item.governance_basis_id,
                    kind=item.kind,
                    subject_ref=item.subject_ref,
                    target_system=item.target_system,
                    required_operation=item.required_operation,
                    expected_postcondition=dict(item.expected_postcondition_json),
                    authority_class=AuthorityClass(item.authority_class),
                    required=item.required,
                    fulfillment_kind=ObligationFulfillmentKind(
                        item.fulfillment_kind
                        or ObligationFulfillmentKind.EXTERNAL_EFFECT_VERIFIED.value
                    ),
                )
                for item in obligation_rows
            ),
        )

    def record_domain_state_fulfillment(
        self, fulfillment: ObligationDomainStateFulfillment
    ) -> ObligationDomainStateFulfillment:
        with self.store.sessions.begin() as db:
            obligation_row = db.get(ObligationRow, fulfillment.obligation_id)
            if obligation_row is None:
                raise ObligationError("domain-state fulfillment requires a persisted obligation")
            if obligation_row.case_id != fulfillment.case_id:
                raise ObligationError("fulfillment and obligation belong to different cases")
            if obligation_row.authority_epoch != fulfillment.authority_epoch:
                raise ObligationError(
                    "fulfillment and obligation belong to different authority epochs"
                )
            if (
                obligation_row.fulfillment_kind
                != ObligationFulfillmentKind.DOMAIN_STATE_VERIFIED.value
            ):
                raise ObligationError(
                    "only domain-state obligations accept a domain-state fulfillment"
                )
            existing = db.get(
                ObligationDomainStateFulfillmentRow, fulfillment.fulfillment_id
            )
            if existing is not None:
                restored = self._fulfillment_from_row(existing)
                if _fulfillment_semantics(restored) != _fulfillment_semantics(fulfillment):
                    raise ObligationError(
                        "fulfillment identity was reused with different semantics"
                    )
                return restored
            existing_for_obligation = (
                db.execute(
                    select(ObligationDomainStateFulfillmentRow).where(
                        ObligationDomainStateFulfillmentRow.obligation_id
                        == fulfillment.obligation_id
                    )
                )
                .scalars()
                .first()
            )
            if existing_for_obligation is not None:
                raise ObligationError(
                    "obligation already has a different domain-state fulfillment"
                )
            db.add(
                ObligationDomainStateFulfillmentRow(
                    fulfillment_id=fulfillment.fulfillment_id,
                    obligation_id=fulfillment.obligation_id,
                    case_id=fulfillment.case_id,
                    authority_epoch=fulfillment.authority_epoch,
                    governance_basis_id=fulfillment.governance_basis_id,
                    fulfillment_kind=fulfillment.fulfillment_kind.value,
                    verified_by=fulfillment.verified_by,
                    reason=fulfillment.reason,
                    observed_state_digest=fulfillment.observed_state_digest,
                    evidence_ref=fulfillment.evidence_ref,
                    observed_at=fulfillment.observed_at,
                )
            )
            db.flush()
        return fulfillment

    def get_domain_state_fulfillment(
        self, obligation_id: UUID
    ) -> ObligationDomainStateFulfillment | None:
        with self.store.sessions() as db:
            row = (
                db.execute(
                    select(ObligationDomainStateFulfillmentRow).where(
                        ObligationDomainStateFulfillmentRow.obligation_id == obligation_id
                    )
                )
                .scalars()
                .first()
            )
            return None if row is None else self._fulfillment_from_row(row)

    def list_domain_state_fulfillments(
        self, case_id: UUID, authority_epoch: int
    ) -> list[ObligationDomainStateFulfillment]:
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(ObligationDomainStateFulfillmentRow)
                    .where(
                        ObligationDomainStateFulfillmentRow.case_id == case_id,
                        ObligationDomainStateFulfillmentRow.authority_epoch
                        == authority_epoch,
                    )
                    .order_by(ObligationDomainStateFulfillmentRow.obligation_id)
                )
                .scalars()
                .all()
            )
            return [self._fulfillment_from_row(row) for row in rows]

    @staticmethod
    def _fulfillment_from_row(
        row: ObligationDomainStateFulfillmentRow,
    ) -> ObligationDomainStateFulfillment:
        return ObligationDomainStateFulfillment(
            fulfillment_id=row.fulfillment_id,
            obligation_id=row.obligation_id,
            case_id=row.case_id,
            authority_epoch=row.authority_epoch,
            governance_basis_id=row.governance_basis_id,
            fulfillment_kind=ObligationFulfillmentKind(row.fulfillment_kind),
            verified_by=row.verified_by,
            reason=row.reason,
            observed_state_digest=row.observed_state_digest,
            evidence_ref=row.evidence_ref,
            observed_at=row.observed_at,
        )

    @staticmethod
    def _link_from_row(row: EffectObligationLinkRow) -> EffectObligationLink:
        return EffectObligationLink(
            effect_id=row.effect_id,
            obligation_id=row.obligation_id,
            governance_basis_id=row.governance_basis_id,
        )


def _fulfillment_semantics(
    fulfillment: ObligationDomainStateFulfillment,
) -> dict[str, Any]:
    """Immutable fulfillment fields used for replay idempotency."""
    return fulfillment.model_dump(mode="json", exclude={"created_at"})


# Compatibility facade: historical callers may continue importing derivation
# functions from this module, while all interpretation lives with domain owners.
def derive_onboarding_obligations(
    case: AdministrativeCase,
    evaluation: PolicyEvaluation,
    *,
    governance_basis_id: UUID,
) -> OnboardingObligationSet:
    from .onboarding_obligations import derive_onboarding_obligations as derive

    return derive(case, evaluation, governance_basis_id=governance_basis_id)


def derive_offboarding_obligations(
    case: AdministrativeCase,
    evaluation: PolicyEvaluation,
    policy: OffboardingPolicy,
    authority_repository: AuthorityRepository,
    *,
    governance_basis_id: UUID,
    transfer_requirements: tuple[AdministrativeTransferRequirement, ...] | None = None,
) -> AdministrativeObligationSet:
    from .offboarding_obligations import derive_offboarding_obligations as derive

    return derive(
        case,
        evaluation,
        policy,
        authority_repository,
        governance_basis_id=governance_basis_id,
        transfer_requirements=transfer_requirements,
    )


def derive_financial_obligations(
    case: AdministrativeCase,
    evaluation: PolicyEvaluation,
    *,
    governance_basis_id: UUID,
) -> AdministrativeObligationSet:
    from .financial_obligations import derive_financial_obligations as derive

    return derive(case, evaluation, governance_basis_id=governance_basis_id)


def derive_administrative_obligations(
    case: AdministrativeCase,
    evaluation: PolicyEvaluation,
    *,
    governance_basis_id: UUID,
    offboarding_policy: OffboardingPolicy | None = None,
    authority_repository: AuthorityRepository | None = None,
) -> AdministrativeObligationSet:
    from .obligation_derivation import derive_administrative_obligations as derive

    return derive(
        case,
        evaluation,
        governance_basis_id=governance_basis_id,
        offboarding_policy=offboarding_policy,
        authority_repository=authority_repository,
    )


__all__ = [
    "AdministrativeObligation",
    "AdministrativeObligationSet",
    "EffectObligationLink",
    "EffectObligationLinkRow",
    "ObligationError",
    "ObligationDomainStateFulfillment",
    "ObligationDomainStateFulfillmentRow",
    "ObligationFulfillmentKind",
    "ObligationRepository",
    "ObligationRow",
    "ObligationSetRow",
    "OnboardingObligationSet",
    "derive_administrative_obligations",
    "derive_financial_obligations",
    "derive_offboarding_obligations",
    "derive_onboarding_obligations",
]
