from typing import Any, Mapping

from semantic_language import Decision, Revision, SemanticKind, SemanticRef

from .identity import AuthenticatedRequestContext
from .ledger import SemanticLedger
from .lineage import RevisionLineageService


def _assert_decision_qualified_current(
    ledger: SemanticLedger,
    decision_id: str,
) -> None:
    RevisionLineageService(ledger).assert_current(
        SemanticRef(SemanticKind.DECISION, decision_id)
    )
    qualification = ledger.project_get("decision.qualification", decision_id)
    if qualification is None:
        # Decisions recorded before institutional continuity are historical active
        # decisions unless supersession lineage says otherwise.
        return
    status = str(qualification[0].get("status", "active"))
    if status != "active":
        raise ValueError(f"decision is not current: {status}")


def assert_decision_applies(
    ledger: SemanticLedger,
    decision_id: str,
    *,
    target_ref: str,
    operation: str,
    expected: Mapping[str, object] | None = None,
) -> Mapping[str, Any]:
    _assert_decision_qualified_current(ledger, decision_id)
    row = ledger.project_get("decision.current", decision_id)
    if row is None:
        raise ValueError("required decision is not recorded")
    value = row[0]
    selected = dict(value.get("selected", {}))
    if selected.get("target_ref") != target_ref:
        raise ValueError("decision does not apply to target")
    if selected.get("operation") != operation:
        raise ValueError("decision does not authorize requested transition")
    for key, expected_value in dict(expected or {}).items():
        if selected.get(key) != expected_value:
            raise ValueError(f"decision does not qualify requested {key}")
    return value


class DecisionLedger:
    def __init__(
        self,
        ledger: SemanticLedger,
        lineage: RevisionLineageService | None = None,
    ) -> None:
        self.ledger = ledger
        self.lineage = lineage or RevisionLineageService(ledger)

    def record_attested(
        self,
        decision: Decision,
        *,
        context: AuthenticatedRequestContext,
    ) -> None:
        if decision.decided_by != context.effective_principal:
            raise PermissionError(
                "Decision.decided_by must equal the authenticated effective principal"
            )
        self._record(decision, attestation=context.attestation())

    def record(self, decision: Decision) -> None:
        self._record(decision, attestation=None)

    def _record(
        self,
        decision: Decision,
        *,
        attestation: Mapping[str, Any] | None,
    ) -> None:
        if not decision.decided_by or not decision.basis_refs:
            raise ValueError("decision requires decided_by and explicit basis")
        value: dict[str, Any] = {
            "id": decision.id,
            "subject": decision.subject,
            "decided_by": decision.decided_by,
            "selected": dict(decision.selected),
            "proposal_refs": [r.id for r in decision.proposal_refs],
            "alternative_refs": [r.id for r in decision.alternative_refs],
            "basis_refs": [r.id for r in decision.basis_refs],
            "authority_refs": [r.id for r in decision.authority_refs],
            "review_triggers": [dict(x) for x in decision.review_triggers],
        }
        existing = self.ledger.project_get("decision.current", decision.id)
        if existing is not None:
            existing_value = dict(existing[0])
            existing_attestation = existing_value.pop("attestation", None)
            if existing_value != value:
                raise ValueError("decision identity rebound")
            if attestation is not None:
                if not isinstance(existing_attestation, Mapping):
                    raise PermissionError(
                        "unattested historical Decision cannot be adopted by replay"
                    )
                if existing_attestation.get("effective_principal") != attestation.get(
                    "effective_principal"
                ):
                    raise PermissionError(
                        "Decision replay principal differs from original attestation"
                    )
            return
        if attestation is not None:
            value["attestation"] = dict(attestation)
        with self.ledger.transaction():
            self.ledger.project_put(
                "decision.current",
                decision.id,
                value,
                expected_version=0,
            )
            self.ledger.project_put(
                "decision.qualification",
                decision.id,
                {
                    "decision_id": decision.id,
                    "status": "active",
                },
                expected_version=0,
            )
            self.ledger.append(
                stream=f"decision:{decision.id}",
                kind="decision.recorded",
                payload=value,
            )

    def supersede(
        self,
        previous_id: str,
        successor: Decision,
        revision: Revision,
        *,
        context: AuthenticatedRequestContext | None = None,
    ) -> None:
        previous_ref = SemanticRef(SemanticKind.DECISION, previous_id)
        if revision.supersedes_ref != previous_ref:
            raise ValueError("Decision Revision must supersede the selected Decision")
        if revision.target_ref != successor.ref:
            raise ValueError("Decision Revision target must be the successor Decision")
        self.get(previous_id)
        _assert_decision_qualified_current(self.ledger, previous_id)
        previous_qualification = self.ledger.project_get(
            "decision.qualification",
            previous_id,
        )

        with self.ledger.transaction():
            if context is None:
                self.record(successor)
            else:
                self.record_attested(successor, context=context)
            self.lineage.record(revision)
            superseded = {
                "decision_id": previous_id,
                "status": "superseded",
                "successor_id": successor.id,
                "revision_id": revision.id,
                "reason": revision.reason,
                "basis_refs": [ref.id for ref in revision.basis_refs],
            }
            if previous_qualification is None:
                self.ledger.project_put(
                    "decision.qualification",
                    previous_id,
                    superseded,
                    expected_version=0,
                )
            else:
                self.ledger.project_put(
                    "decision.qualification",
                    previous_id,
                    superseded,
                    expected_version=previous_qualification[1],
                )
            self.ledger.append(
                stream=f"decision:{previous_id}",
                kind="decision.superseded",
                payload=superseded,
            )

    def revoke(
        self,
        decision_id: str,
        *,
        reason: str,
        basis_refs: tuple[str, ...],
    ) -> None:
        if not reason.strip():
            raise ValueError("decision revocation requires reason")
        if not basis_refs:
            raise ValueError("decision revocation requires basis refs")
        self.get(decision_id)
        _assert_decision_qualified_current(self.ledger, decision_id)
        current = self.ledger.project_get("decision.qualification", decision_id)
        value = {
            "decision_id": decision_id,
            "status": "revoked",
            "reason": reason,
            "basis_refs": list(basis_refs),
        }
        with self.ledger.transaction():
            if current is None:
                self.ledger.project_put(
                    "decision.qualification",
                    decision_id,
                    value,
                    expected_version=0,
                )
            else:
                self.ledger.project_put(
                    "decision.qualification",
                    decision_id,
                    value,
                    expected_version=current[1],
                )
            self.ledger.append(
                stream=f"decision:{decision_id}",
                kind="decision.revoked",
                payload=value,
            )

    def get_current(self, decision_id: str) -> Mapping[str, Any]:
        current = self.lineage.resolve_current(
            SemanticRef(SemanticKind.DECISION, decision_id)
        )
        _assert_decision_qualified_current(self.ledger, current.id)
        return self.get(current.id)

    def assert_current(self, decision_id: str) -> None:
        _assert_decision_qualified_current(self.ledger, decision_id)

    def assert_attested(
        self,
        decision_id: str,
        *,
        context: AuthenticatedRequestContext,
    ) -> Mapping[str, Any]:
        value = self.get(decision_id)
        attestation = value.get("attestation")
        if not isinstance(attestation, Mapping):
            raise PermissionError("Decision is not authenticated under Runtime Protocol 2.0")
        if attestation.get("effective_principal") != context.effective_principal:
            raise PermissionError("Decision attestation does not match authenticated principal")
        return value

    def get(self, decision_id: str) -> Mapping[str, Any]:
        row = self.ledger.project_get("decision.current", decision_id)
        if row is None:
            raise KeyError(decision_id)
        return row[0]


__all__ = ["DecisionLedger", "assert_decision_applies"]
