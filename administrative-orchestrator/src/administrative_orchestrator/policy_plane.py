from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import JSON, DateTime, String, Uuid, select
from sqlalchemy.orm import Mapped, mapped_column

from .domain import PolicyRef, UtcModel, normalize_datetime, utcnow
from .persistence import Base, SqlStore
from .policy import OnboardingPolicy


class PolicyPlaneError(ValueError):
    pass


class PolicyVersionStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    SHADOW = "shadow"
    INACTIVE = "inactive"
    RETIRED = "retired"


class PolicyVersionRecord(UtcModel):
    policy_id: str
    version: str
    owner: str
    status: PolicyVersionStatus = PolicyVersionStatus.DRAFT
    effective_from: datetime
    effective_until: datetime | None = None
    definition: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def policy_ref(self) -> PolicyRef:
        return PolicyRef(
            policy_id=self.policy_id,
            version=self.version,
            owner=self.owner,
            effective_from=self.effective_from,
            effective_until=self.effective_until,
        )

    @property
    def definition_digest(self) -> str:
        payload = json.dumps(
            self.definition,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
        return hashlib.sha256(payload).hexdigest()

    def is_effective_at(self, at: datetime) -> bool:
        at = normalize_datetime(at)
        return self.status == PolicyVersionStatus.ACTIVE and self.policy_ref.is_current_at(at)


class PolicyLifecycleEvent(UtcModel):
    event_id: UUID = Field(default_factory=uuid4)
    policy_id: str
    version: str
    action: str
    actor_principal_id: str
    reason: str
    occurred_at: datetime = Field(default_factory=utcnow)


class PolicyVersionRow(Base):
    __tablename__ = "administrative_policy_version"

    policy_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    version: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PolicyLifecycleEventRow(Base):
    __tablename__ = "administrative_policy_lifecycle_event"

    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    policy_id: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_principal_id: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PolicyRepository:
    def __init__(self, store: SqlStore) -> None:
        self.store = store

    def put_version(self, record: PolicyVersionRecord) -> PolicyVersionRecord:
        """Persist an immutable policy version.

        A version may change lifecycle status later, but its owner, effective
        window and definition can never be overwritten in place.
        """
        with self.store.sessions.begin() as db:
            row = db.get(PolicyVersionRow, (record.policy_id, record.version))
            if row is not None:
                restored = self._from_row(row)
                same_definition = (
                    restored.policy_id == record.policy_id
                    and restored.version == record.version
                    and restored.owner == record.owner
                    and restored.effective_from == record.effective_from
                    and restored.effective_until == record.effective_until
                    and restored.definition == record.definition
                    and restored.created_at == record.created_at
                )
                if not same_definition:
                    raise PolicyPlaneError("policy version is immutable once created")
                return restored
            if record.status == PolicyVersionStatus.ACTIVE:
                self._assert_no_active_overlap(db, record)
            db.add(
                PolicyVersionRow(
                    policy_id=record.policy_id,
                    version=record.version,
                    owner=record.owner,
                    status=record.status.value,
                    effective_from=record.effective_from,
                    effective_until=record.effective_until,
                    definition_json=dict(record.definition),
                    created_at=record.created_at,
                )
            )
        return record

    def create_draft(self, record: PolicyVersionRecord) -> PolicyVersionRecord:
        if record.status != PolicyVersionStatus.DRAFT:
            raise PolicyPlaneError("create_draft requires draft status")
        return self.put_version(record)

    def activate(
        self,
        policy_id: str,
        version: str,
        *,
        actor_principal_id: str,
        reason: str,
    ) -> PolicyVersionRecord:
        if not reason.strip():
            raise PolicyPlaneError("policy activation requires a reason")
        with self.store.sessions.begin() as db:
            row = db.get(PolicyVersionRow, (policy_id, version))
            if row is None:
                raise KeyError(f"policy version {policy_id}:{version} not found")
            record = self._from_row(row).model_copy(update={"status": PolicyVersionStatus.ACTIVE})
            self._assert_no_active_overlap(db, record, excluding_version=version)
            row.status = PolicyVersionStatus.ACTIVE.value
            event = PolicyLifecycleEvent(
                policy_id=policy_id,
                version=version,
                action="activate",
                actor_principal_id=actor_principal_id,
                reason=reason,
            )
            db.add(self._event_row(event))
            db.flush()
            return self._from_row(row)

    def retire(
        self,
        policy_id: str,
        version: str,
        *,
        actor_principal_id: str,
        reason: str,
    ) -> PolicyVersionRecord:
        if not reason.strip():
            raise PolicyPlaneError("policy retirement requires a reason")
        with self.store.sessions.begin() as db:
            row = db.get(PolicyVersionRow, (policy_id, version))
            if row is None:
                raise KeyError(f"policy version {policy_id}:{version} not found")
            row.status = PolicyVersionStatus.RETIRED.value
            event = PolicyLifecycleEvent(
                policy_id=policy_id,
                version=version,
                action="retire",
                actor_principal_id=actor_principal_id,
                reason=reason,
            )
            db.add(self._event_row(event))
            db.flush()
            return self._from_row(row)

    def set_status(
        self,
        policy_id: str,
        version: str,
        status: PolicyVersionStatus,
    ) -> PolicyVersionRecord:
        """Compatibility surface for tests and historical callers.

        Production policy management should use activate()/retire(), which
        record actor and reason.  ACTIVE still enforces non-overlap here.
        """
        with self.store.sessions.begin() as db:
            row = db.get(PolicyVersionRow, (policy_id, version))
            if row is None:
                raise KeyError(f"policy version {policy_id}:{version} not found")
            if status == PolicyVersionStatus.ACTIVE:
                candidate = self._from_row(row).model_copy(update={"status": status})
                self._assert_no_active_overlap(db, candidate, excluding_version=version)
            row.status = status.value
            db.flush()
            return self._from_row(row)

    def get_version(self, policy_id: str, version: str) -> PolicyVersionRecord | None:
        with self.store.sessions() as db:
            row = db.get(PolicyVersionRow, (policy_id, version))
            return None if row is None else self._from_row(row)

    def list_versions(self, policy_id: str) -> list[PolicyVersionRecord]:
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(PolicyVersionRow)
                    .where(PolicyVersionRow.policy_id == policy_id)
                    .order_by(PolicyVersionRow.effective_from, PolicyVersionRow.version)
                )
                .scalars()
                .all()
            )
            return [self._from_row(row) for row in rows]

    def list_lifecycle_events(self, policy_id: str) -> list[PolicyLifecycleEvent]:
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(PolicyLifecycleEventRow)
                    .where(PolicyLifecycleEventRow.policy_id == policy_id)
                    .order_by(PolicyLifecycleEventRow.occurred_at, PolicyLifecycleEventRow.event_id)
                )
                .scalars()
                .all()
            )
            return [
                PolicyLifecycleEvent(
                    event_id=row.event_id,
                    policy_id=row.policy_id,
                    version=row.version,
                    action=row.action,
                    actor_principal_id=row.actor_principal_id,
                    reason=row.reason,
                    occurred_at=row.occurred_at,
                )
                for row in rows
            ]

    def resolve_current(
        self,
        policy_id: str,
        *,
        at: datetime | None = None,
    ) -> PolicyVersionRecord:
        at = normalize_datetime(at or utcnow())
        candidates = [
            record for record in self.list_versions(policy_id) if record.is_effective_at(at)
        ]
        if not candidates:
            raise PolicyPlaneError(f"no active current policy version for {policy_id}")
        if len(candidates) != 1:
            raise PolicyPlaneError(f"multiple active current policy versions for {policy_id}")
        return candidates[0]

    @staticmethod
    def _event_row(event: PolicyLifecycleEvent) -> PolicyLifecycleEventRow:
        return PolicyLifecycleEventRow(
            event_id=event.event_id,
            policy_id=event.policy_id,
            version=event.version,
            action=event.action,
            actor_principal_id=event.actor_principal_id,
            reason=event.reason,
            occurred_at=event.occurred_at,
        )

    @staticmethod
    def _from_row(row: PolicyVersionRow) -> PolicyVersionRecord:
        return PolicyVersionRecord(
            policy_id=row.policy_id,
            version=row.version,
            owner=row.owner,
            status=PolicyVersionStatus(row.status),
            effective_from=row.effective_from,
            effective_until=row.effective_until,
            definition=dict(row.definition_json),
            created_at=row.created_at,
        )

    @staticmethod
    def _assert_no_active_overlap(
        db,
        candidate: PolicyVersionRecord,
        *,
        excluding_version: str | None = None,
    ) -> None:
        rows = (
            db.execute(
                select(PolicyVersionRow).where(
                    PolicyVersionRow.policy_id == candidate.policy_id,
                    PolicyVersionRow.status == PolicyVersionStatus.ACTIVE.value,
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            if excluding_version is not None and row.version == excluding_version:
                continue
            existing = PolicyRepository._from_row(row)
            if _windows_overlap(
                candidate.effective_from,
                candidate.effective_until,
                existing.effective_from,
                existing.effective_until,
            ):
                raise PolicyPlaneError(
                    f"active policy windows overlap: {candidate.policy_id}:"
                    f"{candidate.version} and {existing.version}"
                )


def _windows_overlap(
    left_start: datetime,
    left_end: datetime | None,
    right_start: datetime,
    right_end: datetime | None,
) -> bool:
    left_start = normalize_datetime(left_start)
    right_start = normalize_datetime(right_start)
    left_end = normalize_datetime(left_end) if left_end is not None else None
    right_end = normalize_datetime(right_end) if right_end is not None else None
    return (right_end is None or left_start < right_end) and (
        left_end is None or right_start < left_end
    )


def default_onboarding_policy_version() -> PolicyVersionRecord:
    baseline = datetime(2026, 1, 1, tzinfo=UTC)
    return PolicyVersionRecord(
        policy_id="employee-onboarding",
        version="v1",
        owner="administrative-orchestrator",
        status=PolicyVersionStatus.ACTIVE,
        effective_from=baseline,
        definition=OnboardingPolicy.default_definition(),
        created_at=baseline,
    )


def default_offboarding_policy_version() -> PolicyVersionRecord:
    from .policy import OffboardingPolicy

    baseline = datetime(2026, 1, 1, tzinfo=UTC)
    return PolicyVersionRecord(
        policy_id="employee-offboarding",
        version="v1",
        owner="administrative-orchestrator",
        status=PolicyVersionStatus.ACTIVE,
        effective_from=baseline,
        definition=OffboardingPolicy.default_definition(),
        created_at=baseline,
    )


def default_procurement_policy_version() -> PolicyVersionRecord:
    from .financial import ProcurementPolicy

    baseline = datetime(2026, 1, 1, tzinfo=UTC)
    return PolicyVersionRecord(
        policy_id="procurement-request",
        version="v1",
        owner="administrative-orchestrator",
        status=PolicyVersionStatus.ACTIVE,
        effective_from=baseline,
        definition=ProcurementPolicy.default_definition(),
        created_at=baseline,
    )


def default_invoice_ap_policy_version() -> PolicyVersionRecord:
    from .financial import InvoiceAPPolicy

    baseline = datetime(2026, 1, 1, tzinfo=UTC)
    return PolicyVersionRecord(
        policy_id="invoice-ap-preparation",
        version="v1",
        owner="administrative-orchestrator",
        status=PolicyVersionStatus.ACTIVE,
        effective_from=baseline,
        definition=InvoiceAPPolicy.default_definition(),
        created_at=baseline,
    )


def default_expense_policy_version() -> PolicyVersionRecord:
    from .financial import ExpensePolicy

    baseline = datetime(2026, 1, 1, tzinfo=UTC)
    return PolicyVersionRecord(
        policy_id="expense-reimbursement",
        version="v1",
        owner="administrative-orchestrator",
        status=PolicyVersionStatus.ACTIVE,
        effective_from=baseline,
        definition=ExpensePolicy.default_definition(),
        created_at=baseline,
    )


def default_commitment_policy_version() -> PolicyVersionRecord:
    """The closed M9 policy for admitting one meeting commitment.

    Meeting interpretation is candidate-only.  This policy is evaluated only
    after an authorized human has qualified the committer and due time.
    """

    baseline = datetime(2026, 1, 1, tzinfo=UTC)
    return PolicyVersionRecord(
        policy_id="meeting-commitment",
        version="m9-v1",
        owner="administrative-orchestrator",
        status=PolicyVersionStatus.ACTIVE,
        effective_from=baseline,
        definition={
            "required_decision_roles": ["administrative_operator"],
            "require_distinct_decision_principals": False,
            "allowed_effects": [
                {
                    "target_system": "communication",
                    "operation": "message.send",
                    "authority_class": "normal",
                }
            ],
            "confirmation": "internal_feishu_one_to_one_fixed_template",
            "reminder": "one_bounded_internal_feishu_one_to_one",
            "fulfillment": ["authorized_attestation", "evidence_verified"],
        },
        created_at=baseline,
    )


def compile_offboarding_policy(record: PolicyVersionRecord):
    from .policy import OffboardingPolicy

    if record.policy_id != "employee-offboarding":
        raise PolicyPlaneError("record is not an employee-offboarding policy")
    return OffboardingPolicy(record.policy_ref, definition=record.definition)


def compile_onboarding_policy(record: PolicyVersionRecord) -> OnboardingPolicy:
    if record.policy_id != "employee-onboarding":
        raise PolicyPlaneError("record is not an employee-onboarding policy")
    return OnboardingPolicy(record.policy_ref, definition=record.definition)


def compile_procurement_policy(record: PolicyVersionRecord):
    from .financial import ProcurementPolicy

    if record.policy_id != "procurement-request":
        raise PolicyPlaneError("record is not a procurement-request policy")
    return ProcurementPolicy(record.policy_ref, definition=record.definition)


def compile_invoice_ap_policy(record: PolicyVersionRecord):
    from .financial import InvoiceAPPolicy

    if record.policy_id != "invoice-ap-preparation":
        raise PolicyPlaneError("record is not an invoice-ap-preparation policy")
    return InvoiceAPPolicy(record.policy_ref, definition=record.definition)


def compile_expense_policy(record: PolicyVersionRecord):
    from .financial import ExpensePolicy

    if record.policy_id != "expense-reimbursement":
        raise PolicyPlaneError("record is not an expense-reimbursement policy")
    return ExpensePolicy(record.policy_ref, definition=record.definition)


__all__ = [
    "PolicyLifecycleEvent",
    "PolicyLifecycleEventRow",
    "PolicyPlaneError",
    "PolicyRepository",
    "PolicyVersionRecord",
    "PolicyVersionRow",
    "PolicyVersionStatus",
    "compile_onboarding_policy",
    "compile_offboarding_policy",
    "compile_procurement_policy",
    "compile_invoice_ap_policy",
    "compile_expense_policy",
    "default_onboarding_policy_version",
    "default_offboarding_policy_version",
    "default_procurement_policy_version",
    "default_invoice_ap_policy_version",
    "default_expense_policy_version",
]
