from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

from .commitment_common import M9_NAMESPACE, CommitmentIntakeError
from .commitment_models import CommitmentRecord, CommitmentState
from .domain import Decision, DecisionDisposition, utcnow
from .fact_transitions import replace_facts_for_reevaluation
from .service import apply_policy_evaluation, record_decision, start_policy_evaluation


class CommitmentRevisionCoordinator:
    """Own due-time revision and authority requalification."""

    def __init__(self, service: Any) -> None:
        self.service = service

    def revise_due_at(
        self,
        case_id: UUID,
        *,
        reviewer_principal_id: str,
        due_at: datetime,
        basis: str,
    ) -> CommitmentRecord:
        svc = self.service
        svc._require_reviewer(reviewer_principal_id)
        if due_at.tzinfo is None or not basis.strip():
            raise CommitmentIntakeError("due revision requires an offset-aware time and basis")
        commitment = svc.repository.get_commitment(case_id)
        case = svc.store.get_case(case_id)
        if commitment is None or case is None or commitment.state in {
            CommitmentState.FULFILLED,
            CommitmentState.CANCELLED,
        }:
            raise CommitmentIntakeError("commitment cannot be revised in its current state")
        if commitment.authority_epoch != case.authority_epoch:
            raise CommitmentIntakeError(
                "commitment revision requires revalidation after an authority epoch change"
            )
        if case.fact_snapshot is None:
            raise CommitmentIntakeError("due revision requires a current fact snapshot")
        now = utcnow()
        facts = dict(case.fact_snapshot.facts)
        facts["due_at"] = due_at.astimezone(UTC).isoformat()
        facts["due_time_basis"] = basis
        snapshot = case.fact_snapshot.model_copy(
            update={
                "snapshot_id": uuid5(
                    M9_NAMESPACE,
                    f"facts:{case_id}:{commitment.version + 1}",
                ),
                "facts": facts,
                "observed_at": now,
            }
        )
        changed = replace_facts_for_reevaluation(case, snapshot)
        policy = svc._current_policy()
        evaluation = svc._commitment_policy_evaluation(policy)
        ready = start_policy_evaluation(changed)
        awaiting = apply_policy_evaluation(ready, evaluation)
        svc.uow.replace_facts_and_apply_policy(case, awaiting, evaluation)
        decision = Decision(
            decision_id=uuid5(
                M9_NAMESPACE,
                f"revision-decision:{case_id}:{commitment.version + 1}",
            ),
            case_id=awaiting.case_id,
            case_version=awaiting.version,
            authority_epoch=awaiting.authority_epoch,
            principal_id=reviewer_principal_id,
            decision_role="administrative_operator",
            disposition=DecisionDisposition.APPROVE,
            rationale="Human-qualified commitment due-time revision",
            policy_ref=awaiting.policy_ref,  # type: ignore[arg-type]
        )
        assessment = svc._assess_approval(awaiting, evaluation, decision)
        if not assessment.satisfied or assessment.satisfaction is None:
            raise CommitmentIntakeError("reviewer does not satisfy the revised commitment policy")
        authorized = record_decision(awaiting, decision, approval_complete=True)
        svc.uow.apply_decision_transition(
            awaiting,
            authorized,
            decision,
            organization_scope="*",
            approval_satisfaction=assessment.satisfaction,
        )
        revised = commitment.model_copy(
            update={
                "authority_epoch": authorized.authority_epoch,
                "due_at": due_at.astimezone(UTC),
                "due_time_basis": basis,
                "version": commitment.version,
                "updated_at": now,
                "state": CommitmentState.ACTIVE,
            }
        )
        revised = svc.repository.update_commitment(revised)
        svc.ensure_communication(revised, draft_kind="confirmation")
        return revised


__all__ = ["CommitmentRevisionCoordinator"]
