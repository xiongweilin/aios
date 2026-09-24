from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import Field
from sqlalchemy import JSON, DateTime, String, Uuid, select
from sqlalchemy.orm import Mapped, mapped_column

from .authority import (
    AuthorityError,
    DelegationRow,
    IdentityBinding,
    IdentityBindingRow,
    PrincipalRow,
    RoleAssignmentRow,
)
from .domain import UtcModel, normalize_datetime, utcnow
from .persistence import Base, SqlStore


class AuthorityLifecycleEvent(UtcModel):
    event_id: UUID = Field(default_factory=uuid4)
    event_type: str
    actor_principal_id: str
    target_ref: str
    reason: str
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=utcnow)


class AuthorityLifecycleEventRow(Base):
    __tablename__ = "administrative_authority_lifecycle_event"

    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_principal_id: Mapped[str] = mapped_column(String(255), nullable=False)
    target_ref: Mapped[str] = mapped_column(String(1000), nullable=False)
    reason: Mapped[str] = mapped_column(String(2000), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuthorityLifecycleRepository:
    def __init__(self, store: SqlStore) -> None:
        self.store = store

    def deactivate_principal(
        self,
        principal_id: str,
        *,
        actor_principal_id: str,
        reason: str,
        at: datetime | None = None,
    ) -> AuthorityLifecycleEvent:
        if not reason.strip():
            raise AuthorityError("principal deactivation requires a reason")
        occurred_at = normalize_datetime(at or utcnow())
        with self.store.sessions.begin() as db:
            row = db.get(PrincipalRow, principal_id)
            if row is None:
                raise AuthorityError("principal does not exist")
            if row.active:
                row.active = False
            event = AuthorityLifecycleEvent(
                event_id=uuid5(
                    NAMESPACE_URL,
                    "administrative:authority-lifecycle:principal.deactivated:"
                    f"{principal_id}:{occurred_at.isoformat()}",
                ),
                event_type="principal.deactivated",
                actor_principal_id=actor_principal_id,
                target_ref=f"principal:{principal_id}",
                reason=reason,
                payload={"principal_id": principal_id},
                occurred_at=occurred_at,
            )
            return self._record(db, event)

    def expire_identity_binding(
        self,
        binding_id: UUID,
        *,
        actor_principal_id: str,
        reason: str,
        at: datetime | None = None,
    ) -> AuthorityLifecycleEvent:
        return self._expire_validity(
            IdentityBindingRow,
            binding_id,
            event_type="identity_binding.revoked",
            target_prefix="identity-binding",
            label="identity revocation",
            actor_principal_id=actor_principal_id,
            reason=reason,
            at=at,
            payload_fields=(
                "binding_id",
                "provider",
                "external_subject",
                "principal_id",
            ),
        )

    def expire_role_assignment(
        self,
        assignment_id: UUID,
        *,
        actor_principal_id: str,
        reason: str,
        at: datetime | None = None,
    ) -> AuthorityLifecycleEvent:
        """End a role assignment at the qualified effective time."""
        return self._expire_validity(
            RoleAssignmentRow,
            assignment_id,
            event_type="role_assignment.expired",
            target_prefix="role-assignment",
            label="role assignment expiry",
            actor_principal_id=actor_principal_id,
            reason=reason,
            at=at,
            payload_fields=(
                "assignment_id",
                "principal_id",
                "role",
                "organization_scope",
            ),
        )

    def expire_delegation(
        self,
        delegation_id: UUID,
        *,
        actor_principal_id: str,
        reason: str,
        at: datetime | None = None,
    ) -> AuthorityLifecycleEvent:
        """End a delegation at the qualified effective time."""
        return self._expire_validity(
            DelegationRow,
            delegation_id,
            event_type="delegation.expired",
            target_prefix="delegation",
            label="delegation expiry",
            actor_principal_id=actor_principal_id,
            reason=reason,
            at=at,
            payload_fields=(
                "delegation_id",
                "from_principal_id",
                "to_principal_id",
                "role",
                "organization_scope",
            ),
        )

    def bind_identity(
        self,
        binding: IdentityBinding,
        *,
        actor_principal_id: str,
        reason: str,
    ) -> AuthorityLifecycleEvent:
        if not reason.strip():
            raise AuthorityError("identity binding requires a reason")
        with self.store.sessions.begin() as db:
            principal = db.get(PrincipalRow, binding.principal_id)
            if principal is None or not principal.active:
                raise AuthorityError("identity may bind only to an active principal")
            rows = (
                db.execute(
                    select(IdentityBindingRow).where(
                        IdentityBindingRow.provider == binding.provider,
                        IdentityBindingRow.external_subject == binding.external_subject,
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                existing = IdentityBinding(
                    binding_id=row.binding_id,
                    provider=row.provider,
                    external_subject=row.external_subject,
                    principal_id=row.principal_id,
                    valid_from=row.valid_from,
                    valid_until=row.valid_until,
                )
                if _windows_overlap(existing, binding):
                    raise AuthorityError("identity binding validity overlaps existing binding")
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
            event = AuthorityLifecycleEvent(
                event_type="identity_binding.created",
                actor_principal_id=actor_principal_id,
                target_ref=f"identity-binding:{binding.binding_id}",
                reason=reason,
                payload=binding.model_dump(mode="json"),
                occurred_at=binding.valid_from,
            )
            return self._record(db, event)

    def list_events(self, *, limit: int = 200) -> list[AuthorityLifecycleEvent]:
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(AuthorityLifecycleEventRow)
                    .order_by(AuthorityLifecycleEventRow.occurred_at.desc())
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [
                AuthorityLifecycleEvent(
                    event_id=row.event_id,
                    event_type=row.event_type,
                    actor_principal_id=row.actor_principal_id,
                    target_ref=row.target_ref,
                    reason=row.reason,
                    payload=dict(row.payload_json),
                    occurred_at=row.occurred_at,
                )
                for row in rows
            ]

    def _expire_validity(
        self,
        row_type: type,
        row_id: UUID,
        *,
        event_type: str,
        target_prefix: str,
        label: str,
        actor_principal_id: str,
        reason: str,
        at: datetime | None,
        payload_fields: tuple[str, ...],
    ) -> AuthorityLifecycleEvent:
        """Monotonically end one validity window and append an audit event."""
        if not reason.strip():
            raise AuthorityError(f"{label} requires a reason")
        effective_at = normalize_datetime(at or utcnow())
        with self.store.sessions.begin() as db:
            row = db.get(row_type, row_id)
            if row is None:
                raise AuthorityError(f"{label} target does not exist")
            valid_from = normalize_datetime(row.valid_from)
            if effective_at < valid_from:
                raise AuthorityError(f"{label} cannot precede its validity start")
            previous = row.valid_until
            if previous is None or effective_at < normalize_datetime(previous):
                row.valid_until = effective_at
            target_ref = f"{target_prefix}:{row_id}"
            payload: dict[str, Any] = {}
            for field in payload_fields:
                value = getattr(row, field)
                payload[field] = str(value) if isinstance(value, UUID) else value
            payload["valid_from"] = valid_from.isoformat()
            # The event records the resulting window, which the monotonic guard
            # may have kept earlier than the requested time.
            payload["valid_until"] = normalize_datetime(row.valid_until).isoformat()
            event = AuthorityLifecycleEvent(
                event_id=uuid5(
                    NAMESPACE_URL,
                    f"administrative:authority-lifecycle:{event_type}:"
                    f"{target_ref}:{effective_at.isoformat()}",
                ),
                event_type=event_type,
                actor_principal_id=actor_principal_id,
                target_ref=target_ref,
                reason=reason,
                payload=payload,
                occurred_at=effective_at,
            )
            return self._record(db, event)

    @staticmethod
    def _record(
        db, event: AuthorityLifecycleEvent
    ) -> AuthorityLifecycleEvent:
        existing = db.get(AuthorityLifecycleEventRow, event.event_id)
        if existing is not None:
            stored = AuthorityLifecycleEvent(
                event_id=existing.event_id,
                event_type=existing.event_type,
                actor_principal_id=existing.actor_principal_id,
                target_ref=existing.target_ref,
                reason=existing.reason,
                payload=dict(existing.payload_json),
                occurred_at=existing.occurred_at,
            )
            if stored != event:
                raise AuthorityError(
                    "authority lifecycle event id already exists with different semantics"
                )
            return stored
        db.add(
            AuthorityLifecycleEventRow(
                event_id=event.event_id,
                event_type=event.event_type,
                actor_principal_id=event.actor_principal_id,
                target_ref=event.target_ref,
                reason=event.reason,
                payload_json=dict(event.payload),
                occurred_at=event.occurred_at,
            )
        )
        return event


def _windows_overlap(left: IdentityBinding, right: IdentityBinding) -> bool:
    left_end = left.valid_until
    right_end = right.valid_until
    if left_end is not None and normalize_datetime(left_end) <= normalize_datetime(right.valid_from):
        return False
    return not (
        right_end is not None
        and normalize_datetime(right_end) <= normalize_datetime(left.valid_from)
    )


__all__ = [
    "AuthorityLifecycleEvent",
    "AuthorityLifecycleEventRow",
    "AuthorityLifecycleRepository",
]
