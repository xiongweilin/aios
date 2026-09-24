from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from semantic_language import SemanticKind, SemanticRef

from .ledger import SemanticLedger


@dataclass(frozen=True, slots=True)
class DomainAssignment:
    id: str
    responsibility_ref: str
    domain: str
    controller: str
    mandate_refs: tuple[str, ...] = ()
    goal_refs: tuple[str, ...] = ()
    constraint_refs: tuple[str, ...] = ()
    authority_refs: tuple[str, ...] = ()
    acceptance_refs: tuple[str, ...] = ()
    evidence_requirements: tuple[Mapping[str, Any], ...] = ()
    resource_budget: Mapping[str, Any] = field(default_factory=dict)
    review_conditions: tuple[Mapping[str, Any], ...] = ()
    status: str = field(default="offered", init=False)


@dataclass(frozen=True, slots=True)
class DomainReport:
    id: str
    assignment_id: str
    kind: str
    basis_refs: tuple[SemanticRef, ...] = ()
    evidence_refs: tuple[SemanticRef, ...] = ()
    outcome_refs: tuple[SemanticRef, ...] = ()
    detail: Mapping[str, Any] = field(default_factory=dict)


class DomainProtocolService:
    """Durable Runtime side of the Domain Controller protocol.

    The Runtime owns assignment identity, bounded delegation, and report lineage.
    Domain Controllers retain ownership of domain-specific lifecycle, verification,
    Outcome qualification, Acceptance, and completion semantics.
    """

    _REPORT_KINDS = frozenset(
        {
            "accepted",
            "rejected",
            "progress",
            "evidence-submission",
            "outcome-candidate",
            "escalation",
            "completion-proposal",
        }
    )

    def __init__(self, ledger: SemanticLedger) -> None:
        self.ledger = ledger

    def offer(self, assignment: DomainAssignment) -> DomainAssignment:
        if not assignment.id.strip():
            raise ValueError("domain assignment requires id")
        if assignment.status != "offered":
            raise ValueError("new domain assignment must start in offered state")
        if not assignment.controller.strip():
            raise ValueError("domain assignment requires controller")
        responsibility = self.ledger.project_get(
            "responsibility.current", assignment.responsibility_ref
        )
        if responsibility is None:
            raise ValueError("domain assignment requires standing responsibility")
        if responsibility[0].get("status") != "active":
            raise ValueError("domain assignment requires active responsibility")
        if str(responsibility[0].get("domain", "")) != assignment.domain:
            raise ValueError("domain assignment must match responsibility domain")

        existing = self.ledger.project_get("domain.assignment", assignment.id)
        value = self._assignment_value(assignment)
        if existing is not None:
            existing_identity = dict(existing[0])
            incoming_identity = dict(value)
            existing_identity.pop("status", None)
            incoming_identity.pop("status", None)
            if existing_identity != incoming_identity:
                raise ValueError("domain assignment identity rebound")
            return self._assignment_from_value(existing[0])

        with self.ledger.transaction():
            self.ledger.project_put("domain.assignment", assignment.id, value)
            self.ledger.append(
                stream=f"domain-assignment:{assignment.id}",
                kind="domain.assignment.offered",
                payload=value,
            )
        return assignment

    def get(self, assignment_id: str) -> DomainAssignment:
        row = self.ledger.project_get("domain.assignment", assignment_id)
        if row is None:
            raise KeyError(assignment_id)
        return self._assignment_from_value(row[0])

    def report(
        self,
        assignment_id: str,
        *,
        kind: str,
        report_id: str,
        basis_refs: tuple[SemanticRef, ...] = (),
        evidence_refs: tuple[SemanticRef, ...] = (),
        outcome_refs: tuple[SemanticRef, ...] = (),
        detail: Mapping[str, Any] | None = None,
    ) -> DomainReport:
        if kind not in self._REPORT_KINDS:
            raise ValueError(f"unsupported domain report kind: {kind}")
        if not report_id.strip():
            raise ValueError("domain report requires caller-owned id")
        if any(ref.kind != SemanticKind.EVIDENCE for ref in evidence_refs):
            raise ValueError("evidence_refs must contain only Evidence refs")
        if any(ref.kind != SemanticKind.OUTCOME for ref in outcome_refs):
            raise ValueError("outcome_refs must contain only Outcome refs")
        if any(ref.namespace == "universal" for ref in outcome_refs):
            raise ValueError("domain outcome refs require an explicit domain namespace")
        if kind in {"evidence-submission", "outcome-candidate", "completion-proposal"}:
            if not evidence_refs:
                raise ValueError(f"{kind} requires evidence refs")
        if kind == "outcome-candidate" and not outcome_refs:
            raise ValueError("outcome-candidate requires domain-owned outcome refs")

        current = self.ledger.project_get("domain.assignment", assignment_id)
        if current is None:
            raise KeyError(assignment_id)
        assignment_value, version = current

        report = DomainReport(
            id=report_id,
            assignment_id=assignment_id,
            kind=kind,
            basis_refs=tuple(basis_refs),
            evidence_refs=tuple(evidence_refs),
            outcome_refs=tuple(outcome_refs),
            detail=dict(detail or {}),
        )
        existing_report = self.ledger.project_get("domain.report", report_id)
        report_value = self._report_value(report)
        if existing_report is not None:
            if existing_report[0] != report_value:
                raise ValueError("domain report identity rebound")
            return self._report_from_value(existing_report[0])

        status = str(assignment_value.get("status", "offered"))
        allowed_by_state = {
            "offered": {"accepted", "rejected"},
            "active": {
                "progress",
                "evidence-submission",
                "outcome-candidate",
                "escalation",
                "completion-proposal",
            },
            "escalated": set(),
            "completion-proposed": set(),
            "rejected": set(),
        }
        allowed = allowed_by_state.get(status)
        if allowed is None:
            raise ValueError(f"unknown domain assignment state: {status}")
        if kind not in allowed:
            raise ValueError(
                f"domain assignment state {status} does not admit report kind {kind}"
            )

        next_status = status
        if kind == "accepted":
            next_status = "active"
        elif kind == "rejected":
            next_status = "rejected"
        elif kind == "escalation":
            next_status = "escalated"
        elif kind == "completion-proposal":
            next_status = "completion-proposed"

        assignment_value["status"] = next_status
        with self.ledger.transaction():
            self.ledger.project_put(
                "domain.assignment",
                assignment_id,
                assignment_value,
                expected_version=version,
            )
            self.ledger.project_put("domain.report", report_id, report_value)
            self.ledger.append(
                stream=f"domain-assignment:{assignment_id}",
                kind=f"domain.report.{kind}",
                payload=report_value,
            )
        return report

    def reports(self, assignment_id: str) -> tuple[DomainReport, ...]:
        values = [
            self._report_from_value(event.payload)
            for event in self.ledger.events(stream=f"domain-assignment:{assignment_id}")
            if event.kind.startswith("domain.report.")
        ]
        return tuple(values)

    @staticmethod
    def _assignment_value(item: DomainAssignment) -> dict[str, Any]:
        return {
            "id": item.id,
            "responsibility_ref": item.responsibility_ref,
            "domain": item.domain,
            "controller": item.controller,
            "mandate_refs": list(item.mandate_refs),
            "goal_refs": list(item.goal_refs),
            "constraint_refs": list(item.constraint_refs),
            "authority_refs": list(item.authority_refs),
            "acceptance_refs": list(item.acceptance_refs),
            "evidence_requirements": [dict(value) for value in item.evidence_requirements],
            "resource_budget": dict(item.resource_budget),
            "review_conditions": [dict(value) for value in item.review_conditions],
            "status": item.status,
        }

    @staticmethod
    def _assignment_from_value(value: Mapping[str, Any]) -> DomainAssignment:
        item = DomainAssignment(
            id=str(value["id"]),
            responsibility_ref=str(value["responsibility_ref"]),
            domain=str(value["domain"]),
            controller=str(value["controller"]),
            mandate_refs=tuple(str(v) for v in value.get("mandate_refs", [])),
            goal_refs=tuple(str(v) for v in value.get("goal_refs", [])),
            constraint_refs=tuple(str(v) for v in value.get("constraint_refs", [])),
            authority_refs=tuple(str(v) for v in value.get("authority_refs", [])),
            acceptance_refs=tuple(str(v) for v in value.get("acceptance_refs", [])),
            evidence_requirements=tuple(
                dict(v) for v in value.get("evidence_requirements", [])
            ),
            resource_budget=dict(value.get("resource_budget", {})),
            review_conditions=tuple(
                dict(v) for v in value.get("review_conditions", [])
            ),
        )
        object.__setattr__(item, "status", str(value.get("status", "offered")))
        return item

    @staticmethod
    def _ref_value(ref: SemanticRef) -> dict[str, str]:
        kind = ref.kind.value if isinstance(ref.kind, SemanticKind) else str(ref.kind)
        return {
            "kind": kind,
            "id": ref.id,
            "namespace": ref.namespace,
            "version": ref.version,
        }

    @staticmethod
    def _ref_from_value(value: Mapping[str, Any]) -> SemanticRef:
        raw_kind = str(value["kind"])
        try:
            kind: SemanticKind | str = SemanticKind(raw_kind)
        except ValueError:
            kind = raw_kind
        return SemanticRef(
            kind=kind,
            id=str(value["id"]),
            namespace=str(value.get("namespace", "universal")),
            version=str(value.get("version", "0.1")),
        )

    @classmethod
    def _report_value(cls, item: DomainReport) -> dict[str, Any]:
        return {
            "id": item.id,
            "assignment_id": item.assignment_id,
            "kind": item.kind,
            "basis_refs": [cls._ref_value(ref) for ref in item.basis_refs],
            "evidence_refs": [cls._ref_value(ref) for ref in item.evidence_refs],
            "outcome_refs": [cls._ref_value(ref) for ref in item.outcome_refs],
            "detail": dict(item.detail),
        }

    @classmethod
    def _report_from_value(cls, value: Mapping[str, Any]) -> DomainReport:
        return DomainReport(
            id=str(value["id"]),
            assignment_id=str(value["assignment_id"]),
            kind=str(value["kind"]),
            basis_refs=tuple(
                cls._ref_from_value(v) for v in value.get("basis_refs", [])
            ),
            evidence_refs=tuple(
                cls._ref_from_value(v) for v in value.get("evidence_refs", [])
            ),
            outcome_refs=tuple(
                cls._ref_from_value(v) for v in value.get("outcome_refs", [])
            ),
            detail=dict(value.get("detail", {})),
        )


__all__ = ["DomainAssignment", "DomainProtocolService", "DomainReport"]
