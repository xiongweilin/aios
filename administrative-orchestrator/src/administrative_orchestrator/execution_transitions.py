from __future__ import annotations

from .domain import AdministrativeCase, CaseStatus
from .service import TransitionError, utcnow


def begin_reconciliation(case: AdministrativeCase) -> AdministrativeCase:
    if case.status not in {CaseStatus.EXECUTING, CaseStatus.VERIFYING}:
        raise TransitionError("reconciliation requires executing or verifying state")
    return case.model_copy(
        update={
            "status": CaseStatus.RECONCILING,
            "version": case.version + 1,
            "updated_at": utcnow(),
        }
    )


def resume_verification(case: AdministrativeCase) -> AdministrativeCase:
    if case.status != CaseStatus.RECONCILING:
        raise TransitionError("verification resume requires reconciling state")
    return case.model_copy(
        update={
            "status": CaseStatus.VERIFYING,
            "version": case.version + 1,
            "updated_at": utcnow(),
        }
    )


def complete_verified_case(
    case: AdministrativeCase,
    *,
    expected_effect_count: int,
    verified_outcome_count: int,
) -> AdministrativeCase:
    if case.status != CaseStatus.VERIFYING:
        raise TransitionError("completion requires verifying state")
    if expected_effect_count < 1:
        raise TransitionError("completion requires at least one planned effect")
    if verified_outcome_count != expected_effect_count:
        raise TransitionError("completion requires a verified outcome for every planned effect")
    return case.model_copy(
        update={
            "status": CaseStatus.COMPLETED,
            "version": case.version + 1,
            "updated_at": utcnow(),
        }
    )


def fail_execution(case: AdministrativeCase) -> AdministrativeCase:
    if case.status not in {
        CaseStatus.AUTHORIZED,
        CaseStatus.EXECUTING,
        CaseStatus.VERIFYING,
        CaseStatus.RECONCILING,
    }:
        raise TransitionError("execution failure requires an active execution state")
    return case.model_copy(
        update={
            "status": CaseStatus.FAILED,
            "version": case.version + 1,
            "updated_at": utcnow(),
        }
    )
