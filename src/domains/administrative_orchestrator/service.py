from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .authority import ApprovalSatisfaction
from .domain import (
    AdministrativeCase,
    AdministrativeRequest,
    AuthorityClass,
    CaseStatus,
    Decision,
    DecisionDisposition,
    EffectRecord,
    EffectReversibility,
    EvidenceRef,
    ExecutionAuthorization,
    FactAuthority,
    FactSnapshot,
    ReopenReason,
)
from .policy import PolicyDisposition, PolicyEvaluation


class TransitionError(ValueError):
    """Raised when a requested domain transition would violate an invariant."""


def utcnow() -> datetime:
    return datetime.now(UTC)


def create_case(
    request: AdministrativeRequest,
    *,
    case_kind: str,
    subject_ref: str,
    fact_snapshot: FactSnapshot | None = None,
) -> AdministrativeCase:
    return AdministrativeCase(
        case_kind=case_kind,
        requester_principal_id=request.requester_principal_id,
        subject_ref=subject_ref,
        fact_snapshot=fact_snapshot,
        status=CaseStatus.RECEIVED,
    )


def replace_fact_snapshot(
    case: AdministrativeCase,
    fact_snapshot: FactSnapshot,
) -> AdministrativeCase:
    if case.status in {CaseStatus.COMPLETED, CaseStatus.CANCELLED}:
        raise TransitionError("terminal case cannot replace current facts")
    return case.model_copy(
        update={
            "fact_snapshot": fact_snapshot,
            "version": case.version + 1,
            "authority_epoch": case.authority_epoch + 1,
            "updated_at": utcnow(),
        }
    )


def add_evidence(case: AdministrativeCase, evidence: EvidenceRef) -> AdministrativeCase:
    if case.status in {CaseStatus.COMPLETED, CaseStatus.CANCELLED}:
        raise TransitionError("terminal case cannot accept new ordinary evidence")
    return case.model_copy(
        update={
            "evidence": [*case.evidence, evidence],
            "version": case.version + 1,
            "authority_epoch": case.authority_epoch + 1,
            "updated_at": utcnow(),
        }
    )


def start_policy_evaluation(case: AdministrativeCase) -> AdministrativeCase:
    if case.status not in {
        CaseStatus.RECEIVED,
        CaseStatus.GATHERING_FACTS,
        CaseStatus.READY_FOR_POLICY,
    }:
        raise TransitionError(f"cannot evaluate policy from status {case.status}")
    return case.model_copy(
        update={
            "status": CaseStatus.READY_FOR_POLICY,
            "version": case.version + 1,
            "updated_at": utcnow(),
        }
    )


def apply_policy_evaluation(
    case: AdministrativeCase,
    evaluation: PolicyEvaluation,
) -> AdministrativeCase:
    if case.status != CaseStatus.READY_FOR_POLICY:
        raise TransitionError("policy evaluation requires ready_for_policy state")

    common = {
        "policy_ref": evaluation.policy_ref,
        "version": case.version + 1,
        "authority_epoch": case.authority_epoch + 1,
        "updated_at": utcnow(),
    }

    if evaluation.disposition == PolicyDisposition.NEED_MORE_FACTS:
        return case.model_copy(update={**common, "status": CaseStatus.GATHERING_FACTS})
    if evaluation.disposition == PolicyDisposition.HUMAN_DECISION_REQUIRED:
        return case.model_copy(update={**common, "status": CaseStatus.AWAITING_DECISION})
    if evaluation.disposition == PolicyDisposition.AUTO_CLOSABLE:
        return case.model_copy(update={**common, "status": CaseStatus.COMPLETED})
    if evaluation.disposition == PolicyDisposition.DENIED:
        return case.model_copy(update={**common, "status": CaseStatus.CANCELLED})
    if evaluation.disposition == PolicyDisposition.REOPEN_REQUIRED:
        return case.model_copy(
            update={
                **common,
                "status": CaseStatus.REOPEN_REQUIRED,
                "reopen_reason": evaluation.reopen_reason,
            }
        )
    raise TransitionError(f"unsupported policy disposition {evaluation.disposition}")


def record_decision(
    case: AdministrativeCase,
    decision: Decision,
    *,
    approval_complete: bool = True,
) -> AdministrativeCase:
    if case.status != CaseStatus.AWAITING_DECISION:
        raise TransitionError("decision requires awaiting_decision state")
    if decision.case_id != case.case_id:
        raise TransitionError("decision belongs to a different case")
    if decision.authority_epoch != case.authority_epoch:
        raise TransitionError("decision is not bound to the current authority epoch")
    if decision.case_version != case.version:
        raise TransitionError("decision is not bound to the current case version")
    if case.policy_ref is None or decision.policy_ref != case.policy_ref:
        raise TransitionError("decision is not bound to the current policy version")

    if decision.disposition == DecisionDisposition.APPROVE:
        status = CaseStatus.AUTHORIZED if approval_complete else CaseStatus.AWAITING_DECISION
    elif decision.disposition == DecisionDisposition.REJECT:
        status = CaseStatus.CANCELLED
    elif decision.disposition == DecisionDisposition.REQUEST_CHANGES:
        status = CaseStatus.GATHERING_FACTS
    else:
        status = CaseStatus.REOPEN_REQUIRED

    updates: dict[str, object] = {
        "status": status,
        "version": case.version + 1,
        "updated_at": utcnow(),
    }
    if status == CaseStatus.REOPEN_REQUIRED:
        updates["reopen_reason"] = ReopenReason.AUTHORITY_UNRESOLVED
        updates["authority_epoch"] = case.authority_epoch + 1
    return case.model_copy(update=updates)


def mint_execution_authorization(
    case: AdministrativeCase,
    decision: Decision,
    *,
    issuer_principal_id: str,
    target_system: str,
    allowed_operations: tuple[str, ...],
    authority_class: AuthorityClass,
    expires_at: datetime | None = None,
) -> ExecutionAuthorization:
    if case.status != CaseStatus.AUTHORIZED:
        raise TransitionError("execution authorization requires an authorized case")
    if decision.disposition != DecisionDisposition.APPROVE:
        raise TransitionError("only an approving decision may support execution authorization")
    if decision.case_id != case.case_id:
        raise TransitionError("decision belongs to a different case")
    if decision.authority_epoch != case.authority_epoch:
        raise TransitionError("decision is stale for the current authority epoch")
    if decision.case_version >= case.version:
        raise TransitionError("decision must precede the current case state")
    if case.policy_ref is None or decision.policy_ref != case.policy_ref:
        raise TransitionError("decision policy is not current")

    return ExecutionAuthorization(
        case_id=case.case_id,
        case_version=case.version,
        authority_epoch=case.authority_epoch,
        decision_id=decision.decision_id,
        issuer_principal_id=issuer_principal_id,
        target_system=target_system,
        subject_ref=case.subject_ref,
        allowed_operations=allowed_operations,
        authority_class=authority_class,
        policy_ref=case.policy_ref,
        expires_at=expires_at,
    )


def mint_execution_authorization_from_approval(
    case: AdministrativeCase,
    approval: ApprovalSatisfaction,
    *,
    issuer_principal_id: str,
    target_system: str,
    allowed_operations: tuple[str, ...],
    authority_class: AuthorityClass,
    expires_at: datetime | None = None,
) -> ExecutionAuthorization:
    if case.status != CaseStatus.AUTHORIZED:
        raise TransitionError("execution authorization requires an authorized case")
    if approval.case_id != case.case_id:
        raise TransitionError("approval satisfaction belongs to a different case")
    if approval.authority_epoch != case.authority_epoch:
        raise TransitionError("approval satisfaction is stale for the current authority epoch")
    if case.policy_ref is None or approval.policy_ref != case.policy_ref:
        raise TransitionError("approval satisfaction policy is not current")
    if not approval.decision_ids or not approval.satisfied_roles:
        raise TransitionError("approval satisfaction has no supporting decisions")

    return ExecutionAuthorization(
        case_id=case.case_id,
        case_version=case.version,
        authority_epoch=case.authority_epoch,
        approval_satisfaction_id=approval.satisfaction_id,
        issuer_principal_id=issuer_principal_id,
        target_system=target_system,
        subject_ref=case.subject_ref,
        allowed_operations=allowed_operations,
        authority_class=authority_class,
        policy_ref=case.policy_ref,
        expires_at=expires_at,
    )


def validate_execution_authorization(
    case: AdministrativeCase,
    authorization: ExecutionAuthorization,
    *,
    operation: str,
) -> None:
    if authorization.case_id != case.case_id:
        raise TransitionError("authorization belongs to a different case")
    if authorization.authority_epoch != case.authority_epoch:
        raise TransitionError("authorization is stale for the current authority epoch")
    if case.status not in {CaseStatus.AUTHORIZED, CaseStatus.EXECUTING}:
        raise TransitionError("authorization may be used only while authorized or executing")
    if authorization.subject_ref != case.subject_ref:
        raise TransitionError("authorization subject does not match current case subject")
    if not authorization.is_current_at(utcnow()):
        raise TransitionError("authorization is expired or revoked")
    if operation not in authorization.allowed_operations:
        raise TransitionError("operation is outside the authorization scope")


def plan_effect(
    case: AdministrativeCase,
    authorization: ExecutionAuthorization,
    *,
    operation: str,
    reversibility: EffectReversibility,
) -> EffectRecord:
    if case.status != CaseStatus.AUTHORIZED:
        raise TransitionError("effect planning requires an authorized case")
    validate_execution_authorization(case, authorization, operation=operation)

    return EffectRecord(
        case_id=case.case_id,
        case_version=case.version,
        authority_epoch=case.authority_epoch,
        authorization_id=authorization.authorization_id,
        target_system=authorization.target_system,
        operation=operation,
        subject_ref=case.subject_ref,
        reversibility=reversibility,
        authority_class=authorization.authority_class,
    )


def begin_execution(case: AdministrativeCase) -> AdministrativeCase:
    if case.status != CaseStatus.AUTHORIZED:
        raise TransitionError("execution may begin only from authorized state")
    return case.model_copy(
        update={
            "status": CaseStatus.EXECUTING,
            "version": case.version + 1,
            "updated_at": utcnow(),
        }
    )


def begin_verification(case: AdministrativeCase) -> AdministrativeCase:
    if case.status != CaseStatus.EXECUTING:
        raise TransitionError("verification may begin only from executing state")
    return case.model_copy(
        update={
            "status": CaseStatus.VERIFYING,
            "version": case.version + 1,
            "updated_at": utcnow(),
        }
    )


def require_reopen(case: AdministrativeCase, reason: ReopenReason) -> AdministrativeCase:
    if case.status in {CaseStatus.COMPLETED, CaseStatus.CANCELLED}:
        raise TransitionError("terminal case cannot be reopened by ordinary transition")
    return case.model_copy(
        update={
            "status": CaseStatus.REOPEN_REQUIRED,
            "reopen_reason": reason,
            "version": case.version + 1,
            "authority_epoch": case.authority_epoch + 1,
            "updated_at": utcnow(),
        }
    )


def explicit_reopen(case: AdministrativeCase) -> AdministrativeCase:
    if case.status != CaseStatus.REOPEN_REQUIRED:
        raise TransitionError("explicit reopen requires reopen_required state")
    return case.model_copy(
        update={
            "status": CaseStatus.GATHERING_FACTS,
            "reopen_reason": None,
            "version": case.version + 1,
            "updated_at": utcnow(),
        }
    )


def _parse_effective_at(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def authoritative_effective_time(case: AdministrativeCase) -> datetime | None:
    """Return the authoritative termination effective time, if one exists."""
    snapshot = case.fact_snapshot
    if snapshot is None:
        return None
    assertion = snapshot.assertions.get("termination_effective_at")
    if assertion is None or assertion.authority is not FactAuthority.AUTHORITATIVE:
        return None
    return _parse_effective_at(assertion.value)


def begin_waiting_for_effective_time(
    case: AdministrativeCase,
    *,
    now: datetime | None = None,
) -> AdministrativeCase:
    """Persist the qualified wait for an offboarding effective time.

    DBOS owns waking the workflow; this transition only records that the case is
    """
    if case.case_kind != "employee-offboarding":
        raise TransitionError(
            "only employee-offboarding cases wait for an effective time"
        )
    if case.status != CaseStatus.AUTHORIZED:
        raise TransitionError(
            f"cannot wait for an effective time from status {case.status}"
        )
    effective_at = authoritative_effective_time(case)
    if effective_at is None:
        raise TransitionError(
            "effective-time waiting requires an authoritative "
            "termination_effective_at"
        )
    current = now or utcnow()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    if effective_at <= current.astimezone(UTC):
        raise TransitionError(
            "effective time has already passed; revalidate instead of waiting"
        )
    return case.model_copy(
        update={
            "status": CaseStatus.WAITING,
            "version": case.version + 1,
            "updated_at": utcnow(),
        }
    )


def resume_from_waiting(
    case: AdministrativeCase,
    *,
    now: datetime | None = None,
) -> AdministrativeCase:
    """Leave WAITING only after the effective time has been reached."""
    if case.status != CaseStatus.WAITING:
        raise TransitionError(f"cannot resume from status {case.status}")
    effective_at = authoritative_effective_time(case)
    if effective_at is None:
        raise TransitionError("waiting case lost its authoritative termination time")
    current = now or utcnow()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    if effective_at > current.astimezone(UTC):
        raise TransitionError("effective time has not been reached")
    return case.model_copy(
        update={
            "status": CaseStatus.AUTHORIZED,
            "version": case.version + 1,
            "updated_at": utcnow(),
        }
    )
