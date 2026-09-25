from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from .domain import AdministrativeCase
from .obligations import (
    AdministrativeObligation,
    ObligationError,
    OnboardingObligationSet,
)
from .policy import PolicyEvaluation


def derive_onboarding_obligations(
    case: AdministrativeCase,
    evaluation: PolicyEvaluation,
    *,
    governance_basis_id: UUID,
) -> OnboardingObligationSet:
    if case.fact_snapshot is None:
        raise ObligationError("onboarding obligations require current facts")
    if evaluation.policy_ref != case.policy_ref:
        raise ObligationError("onboarding obligations require current policy evaluation")

    facts = case.fact_snapshot.facts
    templates = {
        (item.target_system, item.operation, item.authority_class): item
        for item in evaluation.allowed_effects
    }
    obligations: list[AdministrativeObligation] = []
    for key in sorted(templates, key=lambda value: (value[0], value[1], value[2].value)):
        template = templates[key]
        obligation_id = uuid5(
            NAMESPACE_URL,
            f"administrative:obligation:{case.case_id}:{case.authority_epoch}:"
            f"{template.target_system}:{template.operation}",
        )
        expected_payload = {
            field: facts.get(field)
            for field in (
                "employee_ref",
                "department_ref",
                "manager_principal_id",
                "start_date",
                "employment_type",
            )
            if facts.get(field) is not None
        }
        expected_postcondition: dict[str, Any] = {
            "target_system": template.target_system,
            "operation": template.operation,
            "subject_ref": case.subject_ref,
            "active": True,
            "payload": expected_payload,
        }
        if template.operation == "account.provision":
            expected_postcondition["requested_system"] = template.target_system
        obligations.append(
            AdministrativeObligation(
                obligation_id=obligation_id,
                case_id=case.case_id,
                authority_epoch=case.authority_epoch,
                governance_basis_id=governance_basis_id,
                kind=f"{template.target_system}.{template.operation}",
                subject_ref=case.subject_ref,
                target_system=template.target_system,
                required_operation=template.operation,
                expected_postcondition=expected_postcondition,
                authority_class=template.authority_class,
                required=True,
            )
        )

    if not obligations:
        raise ObligationError("current onboarding policy produces no required obligations")
    requirement_id = uuid5(
        NAMESPACE_URL,
        f"administrative:obligation-set:{case.case_id}:{case.authority_epoch}:{governance_basis_id}",
    )
    return OnboardingObligationSet(
        requirement_id=requirement_id,
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        governance_basis_id=governance_basis_id,
        obligations=tuple(obligations),
    )


__all__ = ["derive_onboarding_obligations"]
