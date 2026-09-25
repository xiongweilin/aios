from __future__ import annotations

from .authority import ApprovalSatisfaction, AuthorityRepository
from .domain import AdministrativeCase, AdministrativeRequest, Decision
from .fact_history import persist_fact_snapshot
from .governance import GovernanceRepository
from .ingress import persist_ingress_receipt
from .messaging import emit_outbox
from .obligations import ObligationRepository
from .persistence import (
    CaseRow,
    ConcurrencyConflict,
    DecisionRow,
    PolicyEvaluationRow,
    RequestRow,
    SqlStore,
    utcnow,
)
from .policy import PolicyEvaluation

_EXPECTED_GOVERNANCE_CHANGE_KEYS: dict[str, tuple[str, ...]] = {
    "employee-offboarding": ("active",),
}


def _expected_governance_change_keys(case: AdministrativeCase) -> tuple[str, ...]:
    """Describe authoritative fields changed by the approved lifecycle effects."""
    return _EXPECTED_GOVERNANCE_CHANGE_KEYS.get(case.case_kind, ())


class AdministrativeUnitOfWork:
    """Atomic persistence boundary for case creation and authority transitions.

    A policy/decision record, the current Case state, immutable fact lineage and
    the durable workflow wake-up event commit together. A crash after this
    transaction may delay orchestration, but cannot silently lose the fact that
    orchestration is due.
    """

    def __init__(self, store: SqlStore) -> None:
        self.store = store
        self.authority = AuthorityRepository(store)
        self.governance = GovernanceRepository(store)
        # Keep obligation row models registered wherever the UoW is imported,
        # including direct Base.metadata.create_all integration-test paths.
        self.obligations = ObligationRepository(store)

    def create_case(
        self,
        request: AdministrativeRequest,
        case: AdministrativeCase,
        *,
        source_event_id: str | None = None,
    ) -> None:
        """Create Request -> Case -> fact lineage -> receipt -> Audit in FK order."""
        if request.requester_principal_id != case.requester_principal_id:
            raise ValueError("request and case requester must match")
        with self.store.sessions.begin() as db:
            db.add(
                RequestRow(
                    request_id=request.request_id,
                    requester_principal_id=request.requester_principal_id,
                    channel=request.channel,
                    intent=request.intent,
                    received_at=request.received_at,
                    source_ref=request.source_ref,
                )
            )
            db.flush()
            db.add(self.store._case_row(case, request.request_id))
            db.flush()
            persist_fact_snapshot(db, case)
            if source_event_id is not None:
                persist_ingress_receipt(
                    db,
                    source_event_id=source_event_id,
                    request_id=request.request_id,
                    case_id=case.case_id,
                )
            self.store._append_audit(
                db,
                case.case_id,
                "case.created",
                {
                    "request_id": str(request.request_id),
                    "source_event_id": source_event_id,
                    "case_kind": case.case_kind,
                    "case_version": case.version,
                    "authority_epoch": case.authority_epoch,
                    "fact_snapshot_id": (
                        str(case.fact_snapshot.snapshot_id) if case.fact_snapshot else None
                    ),
                    "fact_authority": (
                        case.fact_snapshot.authority.value if case.fact_snapshot else None
                    ),
                },
            )

    def apply_policy_transition(
        self,
        before: AdministrativeCase,
        after: AdministrativeCase,
        evaluation: PolicyEvaluation,
    ) -> None:
        if before.case_id != after.case_id:
            raise ValueError("policy transition cannot change case identity")
        if after.version <= before.version:
            raise ValueError("policy transition must advance case version")
        if after.authority_epoch != before.authority_epoch + 1:
            raise ValueError("policy transition must advance authority epoch exactly once")
        if after.policy_ref != evaluation.policy_ref:
            raise ValueError("case policy must match persisted policy evaluation")

        with self.store.sessions.begin() as db:
            row = db.get(CaseRow, before.case_id)
            self._require_version(row, before)
            self._append_policy_evaluation(db, after, evaluation)
            self.store._copy_case_into_row(row, after)
            self.store._append_audit(
                db,
                after.case_id,
                "case.policy_applied",
                {
                    "case_version": after.version,
                    "authority_epoch": after.authority_epoch,
                    "status": after.status.value,
                    "policy_disposition": evaluation.disposition.value,
                },
            )
            emit_outbox(
                db,
                event_type="workflow.case_changed",
                aggregate_id=str(after.case_id),
                payload={
                    "case_id": str(after.case_id),
                    "case_kind": after.case_kind,
                    "case_version": after.version,
                    "authority_epoch": after.authority_epoch,
                    "status": after.status.value,
                    "cause": "policy_evaluated",
                },
            )

    def replace_facts_and_apply_policy(
        self,
        before: AdministrativeCase,
        after: AdministrativeCase,
        evaluation: PolicyEvaluation,
    ) -> None:
        """Atomically persist a new immutable fact snapshot and its new policy world."""
        if before.case_id != after.case_id:
            raise ValueError("fact transition cannot change case identity")
        if after.fact_snapshot is None:
            raise ValueError("fact transition requires a current fact snapshot")
        if before.fact_snapshot is not None and (
            after.fact_snapshot.snapshot_id == before.fact_snapshot.snapshot_id
        ):
            raise ValueError("fact transition requires a new snapshot identity")
        if after.version <= before.version:
            raise ValueError("fact transition must advance case version")
        if after.authority_epoch <= before.authority_epoch:
            raise ValueError("fact transition must invalidate the previous authority epoch")
        if after.policy_ref != evaluation.policy_ref:
            raise ValueError("re-evaluated case policy must match persisted evaluation")

        with self.store.sessions.begin() as db:
            row = db.get(CaseRow, before.case_id)
            self._require_version(row, before)
            persist_fact_snapshot(db, after)
            self._append_policy_evaluation(db, after, evaluation)
            self.store._copy_case_into_row(row, after)
            self.store._append_audit(
                db,
                after.case_id,
                "facts.replaced",
                {
                    "case_version": after.version,
                    "authority_epoch": after.authority_epoch,
                    "fact_snapshot_id": str(after.fact_snapshot.snapshot_id),
                    "previous_fact_snapshot_id": (
                        str(before.fact_snapshot.snapshot_id) if before.fact_snapshot else None
                    ),
                    "fact_authority": after.fact_snapshot.authority.value,
                    "source": after.fact_snapshot.source,
                    "source_ref": after.fact_snapshot.source_ref,
                    "source_version": after.fact_snapshot.source_version,
                },
            )
            self.store._append_audit(
                db,
                after.case_id,
                "case.policy_applied",
                {
                    "case_version": after.version,
                    "authority_epoch": after.authority_epoch,
                    "status": after.status.value,
                    "policy_disposition": evaluation.disposition.value,
                    "cause": "facts_replaced",
                },
            )
            emit_outbox(
                db,
                event_type="workflow.case_changed",
                aggregate_id=str(after.case_id),
                payload={
                    "case_id": str(after.case_id),
                    "case_kind": after.case_kind,
                    "case_version": after.version,
                    "authority_epoch": after.authority_epoch,
                    "status": after.status.value,
                    "cause": "facts_replaced",
                },
            )

    def apply_decision_transition(
        self,
        before: AdministrativeCase,
        after: AdministrativeCase,
        decision: Decision,
        *,
        organization_scope: str | None = None,
        approval_satisfaction: ApprovalSatisfaction | None = None,
    ) -> None:
        if before.case_id != after.case_id or decision.case_id != before.case_id:
            raise ValueError("decision transition cannot change case identity")
        if decision.case_version != before.version:
            raise ValueError("decision must be bound to the pre-transition case version")
        if decision.authority_epoch != before.authority_epoch:
            raise ValueError("decision must be bound to the pre-transition authority epoch")
        if after.version != before.version + 1:
            raise ValueError("decision transition must advance case version exactly once")
        if before.policy_ref is None or decision.policy_ref != before.policy_ref:
            raise ValueError("decision must be bound to the current policy")
        if decision.decision_role is not None and organization_scope is None:
            raise ValueError("governed decision role requires an organization scope")
        if approval_satisfaction is not None:
            if approval_satisfaction.case_id != after.case_id:
                raise ValueError("approval satisfaction belongs to a different case")
            if approval_satisfaction.authority_epoch != after.authority_epoch:
                raise ValueError("approval satisfaction is stale for the case authority epoch")
            if approval_satisfaction.policy_ref != after.policy_ref:
                raise ValueError("approval satisfaction policy is not current")
            if decision.decision_id not in approval_satisfaction.decision_ids:
                raise ValueError("final decision must be part of approval satisfaction")

        with self.store.sessions.begin() as db:
            row = db.get(CaseRow, before.case_id)
            self._require_version(row, before)
            db.add(
                DecisionRow(
                    decision_id=decision.decision_id,
                    case_id=decision.case_id,
                    case_version=decision.case_version,
                    authority_epoch=decision.authority_epoch,
                    principal_id=decision.principal_id,
                    decision_role=decision.decision_role,
                    disposition=decision.disposition.value,
                    rationale=decision.rationale,
                    policy_json=decision.policy_ref.model_dump(mode="json"),
                    decided_at=decision.decided_at,
                )
            )
            db.flush()
            if decision.decision_role is not None:
                self.authority.put_decision_binding(
                    decision,
                    organization_scope=organization_scope or "*",
                    db=db,
                )
            governance_basis = None
            if approval_satisfaction is not None:
                self.authority.put_approval_satisfaction(approval_satisfaction, db=db)
                governance_basis = self.governance.create_for_approval(
                    after,
                    approval_satisfaction,
                    organization_scope=organization_scope or "*",
                    expected_change_keys=_expected_governance_change_keys(after),
                    db=db,
                )
                self.store._append_audit(
                    db,
                    after.case_id,
                    "approval.satisfied",
                    {
                        "satisfaction_id": str(approval_satisfaction.satisfaction_id),
                        "decision_ids": [
                            str(item) for item in approval_satisfaction.decision_ids
                        ],
                        "satisfied_roles": list(approval_satisfaction.satisfied_roles),
                        "authority_epoch": approval_satisfaction.authority_epoch,
                        "governance_basis_id": str(governance_basis.basis_id),
                        "governance_basis_digest": governance_basis.basis_digest,
                    },
                )
            self.store._copy_case_into_row(row, after)
            self.store._append_audit(
                db,
                decision.case_id,
                "decision.recorded",
                {
                    "decision_id": str(decision.decision_id),
                    "case_version": decision.case_version,
                    "authority_epoch": decision.authority_epoch,
                    "principal_id": decision.principal_id,
                    "decision_role": decision.decision_role,
                    "disposition": decision.disposition.value,
                    "policy_id": decision.policy_ref.policy_id,
                    "policy_version": decision.policy_ref.version,
                },
            )
            self.store._append_audit(
                db,
                after.case_id,
                "case.decision_applied",
                {
                    "case_version": after.version,
                    "authority_epoch": after.authority_epoch,
                    "status": after.status.value,
                    "decision_id": str(decision.decision_id),
                    "approval_satisfaction_id": (
                        str(approval_satisfaction.satisfaction_id)
                        if approval_satisfaction is not None
                        else None
                    ),
                    "governance_basis_id": (
                        str(governance_basis.basis_id) if governance_basis is not None else None
                    ),
                },
            )
            emit_outbox(
                db,
                event_type="workflow.case_changed",
                aggregate_id=str(after.case_id),
                payload={
                    "case_id": str(after.case_id),
                    "case_kind": after.case_kind,
                    "case_version": after.version,
                    "authority_epoch": after.authority_epoch,
                    "status": after.status.value,
                    "cause": "decision_recorded",
                    "decision_id": str(decision.decision_id),
                    "approval_satisfaction_id": (
                        str(approval_satisfaction.satisfaction_id)
                        if approval_satisfaction is not None
                        else None
                    ),
                    "governance_basis_id": (
                        str(governance_basis.basis_id) if governance_basis is not None else None
                    ),
                },
            )

    def _append_policy_evaluation(
        self,
        db,
        case: AdministrativeCase,
        evaluation: PolicyEvaluation,
    ) -> None:
        db.add(
            PolicyEvaluationRow(
                case_id=case.case_id,
                case_version=case.version,
                authority_epoch=case.authority_epoch,
                policy_json=evaluation.policy_ref.model_dump(mode="json"),
                evaluation_json=evaluation.model_dump(mode="json"),
                created_at=utcnow(),
            )
        )
        self.store._append_audit(
            db,
            case.case_id,
            "policy.evaluated",
            {
                "case_version": case.version,
                "authority_epoch": case.authority_epoch,
                "policy_id": evaluation.policy_ref.policy_id,
                "policy_version": evaluation.policy_ref.version,
                "disposition": evaluation.disposition.value,
            },
        )

    @staticmethod
    def _require_version(row: CaseRow | None, expected: AdministrativeCase) -> None:
        if row is None:
            raise KeyError(f"case {expected.case_id} not found")
        if row.version != expected.version:
            raise ConcurrencyConflict(
                f"case {expected.case_id} version changed: expected "
                f"{expected.version}, found {row.version}"
            )
        if row.authority_epoch != expected.authority_epoch:
            raise ConcurrencyConflict(
                f"case {expected.case_id} authority epoch changed: expected "
                f"{expected.authority_epoch}, found {row.authority_epoch}"
            )


__all__ = ["AdministrativeUnitOfWork"]
