from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from world_runtime.common import new_id, utcnow
from world_runtime.ledger import SemanticLedger


@dataclass(frozen=True, slots=True)
class MetaPolicyEvent:
    id: str
    event_type: str
    controller_ref: str
    kernel_state_version: int
    policy_version: str
    payload: dict[str, object]
    basis_refs: tuple[str, ...]
    created_at: datetime


class MetaPolicyJournal:
    """Cognition event view backed by the canonical World Ledger."""

    def __init__(self, ledger: SemanticLedger) -> None:
        self.ledger = ledger

    def record(
        self,
        *,
        event_type: str,
        controller_ref: str,
        kernel_state_version: int,
        policy_version: str,
        payload: dict[str, object] | None = None,
        basis_refs: tuple[str, ...] = (),
    ) -> MetaPolicyEvent:
        if not event_type.strip() or not controller_ref.strip() or not policy_version.strip():
            raise ValueError("event_type, controller_ref and policy_version must be non-empty")
        if kernel_state_version < 0:
            raise ValueError("kernel_state_version cannot be negative")
        item = MetaPolicyEvent(
            id=new_id("cognition-event"),
            event_type=event_type,
            controller_ref=controller_ref,
            kernel_state_version=kernel_state_version,
            policy_version=policy_version,
            payload=dict(payload or {}),
            basis_refs=tuple(basis_refs),
            created_at=utcnow(),
        )
        self.ledger.append(
            stream=f"cognition:{controller_ref}",
            kind="cognition.policy.event",
            event_id=item.id,
            payload={
                "event_type": event_type,
                "controller_ref": controller_ref,
                "kernel_state_version": kernel_state_version,
                "policy_version": policy_version,
                "payload": dict(item.payload),
                "basis_refs": list(basis_refs),
                "created_at": item.created_at.isoformat(),
            },
        )
        return item

    def list_events(
        self,
        *,
        controller_ref: str | None = None,
        event_type: str | None = None,
    ) -> tuple[MetaPolicyEvent, ...]:
        rows = self.ledger.events(stream=f"cognition:{controller_ref}") if controller_ref else self.ledger.events(kind="cognition.policy.event")
        result = []
        for row in rows:
            if row.kind != "cognition.policy.event":
                continue
            p = row.payload
            if event_type is not None and p.get("event_type") != event_type:
                continue
            result.append(
                MetaPolicyEvent(
                    id=row.id,
                    event_type=str(p["event_type"]),
                    controller_ref=str(p["controller_ref"]),
                    kernel_state_version=int(p["kernel_state_version"]),
                    policy_version=str(p["policy_version"]),
                    payload=dict(p.get("payload", {})),
                    basis_refs=tuple(str(x) for x in p.get("basis_refs", [])),
                    created_at=datetime.fromisoformat(str(p["created_at"])),
                )
            )
        return tuple(result)
