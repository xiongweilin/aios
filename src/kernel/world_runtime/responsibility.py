from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .decisions import assert_decision_applies
from .ledger import SemanticLedger

if TYPE_CHECKING:
    from .responsibility_graph import ResponsibilityGraphService


@dataclass(frozen=True, slots=True)
class Responsibility:
    """Single durable owner model for responsibility state."""

    id: str
    principal: str
    subject: str
    domain: str
    scope: dict[str, Any] = field(default_factory=dict)
    goal_refs: tuple[str, ...] = ()
    constraint_refs: tuple[str, ...] = ()
    acceptance_refs: tuple[str, ...] = ()
    authority_refs: tuple[str, ...] = ()
    status: str = "active"


class ResponsibilityService:
    _ASSESSMENT_TRANSITIONS = {
        "active": {"active", "blocked", "satisfied", "failed"},
        "blocked": {"active", "blocked", "satisfied", "failed"},
        "satisfied": {"satisfied"},
        "failed": {"failed"},
        "discharged": set(),
    }

    def __init__(self, ledger: SemanticLedger) -> None:
        self.ledger = ledger
        self._graph: ResponsibilityGraphService | None = None

    def bind_graph(self, graph: ResponsibilityGraphService) -> None:
        self._graph = graph

    def create(self, responsibility: Responsibility) -> Responsibility:
        if responsibility.status != "active":
            raise ValueError("new responsibility must start active")
        incoming = self._value(responsibility)
        existing = self.ledger.project_get("responsibility.current", responsibility.id)
        if existing is not None:
            if self._identity_value(existing[0]) != self._identity_value(incoming):
                raise ValueError("responsibility identity rebound")
            return self.get(responsibility.id)

        with self.ledger.transaction():
            self.ledger.project_put(
                "responsibility.current",
                responsibility.id,
                incoming,
                expected_version=0,
            )
            self.ledger.append(
                stream=f"responsibility:{responsibility.id}",
                kind="responsibility.created",
                payload=incoming,
            )
        return responsibility

    def assign(self, responsibility_id: str, *, controller: str) -> str:
        current = self.get(responsibility_id)
        if current.status != "active":
            raise ValueError("domain assignment requires active responsibility")
        assignment_id = f"domain-assignment:{responsibility_id}:{controller}"
        value = {
            "id": assignment_id,
            "responsibility_id": responsibility_id,
            "domain": current.domain,
            "controller": controller,
            "status": "offered",
        }
        existing = self.ledger.project_get("responsibility.assignment", assignment_id)
        if existing is not None:
            if existing[0] != value:
                raise ValueError("responsibility assignment identity rebound")
            return assignment_id
        with self.ledger.transaction():
            self.ledger.project_put(
                "responsibility.assignment",
                assignment_id,
                value,
                expected_version=0,
            )
            self.ledger.append(
                stream=f"responsibility:{responsibility_id}",
                kind="responsibility.assignment.offered",
                payload=value,
            )
        return assignment_id

    def assess(
        self,
        responsibility_id: str,
        *,
        status: str,
        basis_refs: tuple[str, ...],
    ) -> str:
        if status not in {"active", "blocked", "satisfied", "failed"}:
            raise ValueError(status)
        if status in {"satisfied", "failed"} and not basis_refs:
            raise ValueError("terminal responsibility assessment requires basis")
        current = self.ledger.project_get("responsibility.current", responsibility_id)
        if current is None:
            raise KeyError(responsibility_id)
        value, version = current
        current_status = str(value.get("status", "active"))
        allowed = self._ASSESSMENT_TRANSITIONS.get(current_status)
        if allowed is None:
            raise ValueError(f"unknown responsibility status: {current_status}")
        if status not in allowed:
            raise ValueError(
                f"responsibility status {current_status} does not admit assessment to {status}"
            )
        if status == "satisfied" and self._graph is not None:
            self._graph.assert_requirements_resolved(responsibility_id)
        value["status"] = status
        value["assessment_basis_refs"] = list(basis_refs)
        with self.ledger.transaction():
            self.ledger.project_put(
                "responsibility.current",
                responsibility_id,
                value,
                expected_version=version,
            )
            event = self.ledger.append(
                stream=f"responsibility:{responsibility_id}",
                kind="responsibility.assessed",
                payload={
                    "responsibility_id": responsibility_id,
                    "status": status,
                    "basis_refs": list(basis_refs),
                },
            )
        return event.id

    def discharge(self, responsibility_id: str, *, decision_id: str) -> str:
        current = self.ledger.project_get("responsibility.current", responsibility_id)
        if current is None:
            raise KeyError(responsibility_id)
        value, version = current
        if value["status"] != "satisfied":
            raise ValueError("responsibility must be assessed satisfied before discharge")
        if self._graph is not None:
            self._graph.assert_requirements_resolved(responsibility_id)
        assert_decision_applies(
            self.ledger,
            decision_id,
            target_ref=responsibility_id,
            operation="discharge-responsibility",
            expected={"to_status": "discharged"},
        )
        value["status"] = "discharged"
        value["discharge_decision_id"] = decision_id
        with self.ledger.transaction():
            self.ledger.project_put(
                "responsibility.current",
                responsibility_id,
                value,
                expected_version=version,
            )
            event = self.ledger.append(
                stream=f"responsibility:{responsibility_id}",
                kind="responsibility.discharged",
                payload={
                    "responsibility_id": responsibility_id,
                    "decision_id": decision_id,
                },
            )
        return event.id

    def get(self, responsibility_id: str) -> Responsibility:
        row = self.ledger.project_get("responsibility.current", responsibility_id)
        if row is None:
            raise KeyError(responsibility_id)
        v = row[0]
        return Responsibility(
            id=str(v["id"]),
            principal=str(v["principal"]),
            subject=str(v["subject"]),
            domain=str(v["domain"]),
            scope=dict(v.get("scope", {})),
            goal_refs=tuple(str(item) for item in v.get("goal_refs", [])),
            constraint_refs=tuple(str(item) for item in v.get("constraint_refs", [])),
            acceptance_refs=tuple(str(item) for item in v.get("acceptance_refs", [])),
            authority_refs=tuple(str(item) for item in v.get("authority_refs", [])),
            status=str(v.get("status", "active")),
        )

    @staticmethod
    def _identity_value(value: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value.get(key)
            for key in (
                "id",
                "principal",
                "subject",
                "domain",
                "scope",
                "goal_refs",
                "constraint_refs",
                "acceptance_refs",
                "authority_refs",
            )
        }

    @staticmethod
    def _value(item: Responsibility) -> dict[str, Any]:
        return {
            "id": item.id,
            "principal": item.principal,
            "subject": item.subject,
            "domain": item.domain,
            "scope": dict(item.scope),
            "goal_refs": list(item.goal_refs),
            "constraint_refs": list(item.constraint_refs),
            "acceptance_refs": list(item.acceptance_refs),
            "authority_refs": list(item.authority_refs),
            "status": item.status,
        }


__all__ = ["Responsibility", "ResponsibilityService"]
