from __future__ import annotations

from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from .authority import AuthorityRepository
from .domain import AdministrativeCase, AuthorityClass, normalize_datetime
from .obligation_derivation_common import domain_or_external_obligation
from .obligations import (
    AdministrativeObligation,
    AdministrativeObligationSet,
    ObligationError,
    ObligationFulfillmentKind,
)
from .policy import OffboardingPolicy, PolicyEvaluation
from .transfer import (
    AdministrativeTransferRequirement,
    TransferMode,
    derive_transfer_requirements,
)


def derive_offboarding_obligations(
    case: AdministrativeCase,
    evaluation: PolicyEvaluation,
    policy: OffboardingPolicy,
    authority_repository: AuthorityRepository,
    *,
    governance_basis_id: UUID,
    transfer_requirements: tuple[AdministrativeTransferRequirement, ...] | None = None,
) -> AdministrativeObligationSet:
    if case.case_kind != "employee-offboarding":
        raise ObligationError("offboarding obligations require employee-offboarding case")
    if case.fact_snapshot is None:
        raise ObligationError("offboarding obligations require current facts")
    if evaluation.policy_ref != case.policy_ref or policy.policy_ref != case.policy_ref:
        raise ObligationError("offboarding obligations require current policy evaluation")

    facts = case.fact_snapshot.facts
    departing = str(facts.get("departing_principal_id") or "").strip()
    if not departing:
        raise ObligationError("offboarding obligations require departing_principal_id")
    try:
        effective_at = normalize_datetime(
            datetime.fromisoformat(
                str(facts[policy.definition.effective_time_fact]).replace("Z", "+00:00")
            )
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ObligationError("qualified termination effective time is required") from exc
    transfers = transfer_requirements
    if transfers is None:
        transfers = derive_transfer_requirements(
            case,
            policy,
            authority_repository,
            governance_basis_id=governance_basis_id,
        )

    obligations: list[AdministrativeObligation] = []
    effect_order = {
        ("iam", "identity.disable"): 0,
        ("iam", "sessions.revoke"): 1,
        ("hris", "employee.deactivate"): 2,
    }
    for template in sorted(
        evaluation.allowed_effects,
        key=lambda item: (
            effect_order.get((item.target_system, item.operation), 99),
            item.target_system,
            item.operation,
        ),
    ):
        effect_state = {
            "employee.deactivate": {"active": False},
            "identity.disable": {"enabled": False},
            "sessions.revoke": {"active_sessions": 0},
        }.get(template.operation)
        if effect_state is None:
            raise ObligationError(
                f"offboarding effect has no postcondition contract: {template.operation!r}"
            )
        expected_postcondition = {
            "target_system": template.target_system,
            "operation": template.operation,
            "subject_ref": case.subject_ref,
            **effect_state,
            "payload": {
                key: facts[key]
                for key in (
                    "employee_ref",
                    "employment_episode_ref",
                    "termination_status",
                    "termination_effective_at",
                )
                if facts.get(key) is not None
            },
        }
        obligations.append(
            domain_or_external_obligation(
                case,
                governance_basis_id,
                discriminator=f"external:{template.target_system}:{template.operation}",
                kind=f"{template.target_system}.{template.operation}",
                target_system=template.target_system,
                operation=template.operation,
                expected_postcondition=expected_postcondition,
                authority_class=template.authority_class,
                fulfillment_kind=ObligationFulfillmentKind.EXTERNAL_EFFECT_VERIFIED,
            )
        )

    for binding in authority_repository.list_current_identity_bindings(
        departing, at=effective_at
    ):
        obligations.append(
            domain_or_external_obligation(
                case,
                governance_basis_id,
                discriminator=f"identity-binding:{binding.binding_id}",
                kind="administrative.identity_binding.expire",
                target_system="administrative",
                operation="identity_binding.expire",
                expected_postcondition={
                    "binding_id": str(binding.binding_id),
                    "principal_id": departing,
                    "current": False,
                },
                authority_class=AuthorityClass.PRIVILEGED_ACCESS,
                fulfillment_kind=ObligationFulfillmentKind.DOMAIN_STATE_VERIFIED,
            )
        )

    for requirement in transfers:
        obligations.append(
            domain_or_external_obligation(
                case,
                governance_basis_id,
                discriminator=f"role-expire:{requirement.relationship_ref}",
                kind="administrative.role_assignment.expire",
                target_system="administrative",
                operation="role_assignment.expire",
                expected_postcondition={
                    "assignment_id": str(requirement.relationship_ref),
                    "principal_id": departing,
                    "current": False,
                },
                authority_class=AuthorityClass.EMPLOYMENT,
                fulfillment_kind=ObligationFulfillmentKind.DOMAIN_STATE_VERIFIED,
            )
        )
        if requirement.transfer_mode is TransferMode.TRANSFER_REQUIRED:
            obligations.append(
                domain_or_external_obligation(
                    case,
                    governance_basis_id,
                    discriminator=f"role-transfer:{requirement.requirement_id}",
                    kind="administrative.role_assignment.transfer",
                    target_system="administrative",
                    operation="role_assignment.transfer",
                    expected_postcondition={
                        "transfer_requirement_id": str(requirement.requirement_id),
                        "successor_principal_id": requirement.successor_principal_id,
                        "role": requirement.role,
                        "organization_scope": requirement.organization_scope,
                        "current": True,
                    },
                    authority_class=AuthorityClass.EMPLOYMENT,
                    fulfillment_kind=ObligationFulfillmentKind.DOMAIN_STATE_VERIFIED,
                )
            )

    for delegation in authority_repository.list_current_delegations_involving(
        departing, at=effective_at
    ):
        obligations.append(
            domain_or_external_obligation(
                case,
                governance_basis_id,
                discriminator=f"delegation-expire:{delegation.delegation_id}",
                kind="administrative.delegation.expire",
                target_system="administrative",
                operation="delegation.expire",
                expected_postcondition={
                    "delegation_id": str(delegation.delegation_id),
                    "current": False,
                },
                authority_class=AuthorityClass.EMPLOYMENT,
                fulfillment_kind=ObligationFulfillmentKind.DOMAIN_STATE_VERIFIED,
            )
        )

    obligations.append(
        domain_or_external_obligation(
            case,
            governance_basis_id,
            discriminator=f"principal-deactivate:{departing}",
            kind="administrative.principal.deactivate",
            target_system="administrative",
            operation="principal.deactivate",
            expected_postcondition={"principal_id": departing, "active": False},
            authority_class=AuthorityClass.EMPLOYMENT,
            fulfillment_kind=ObligationFulfillmentKind.DOMAIN_STATE_VERIFIED,
        )
    )
    requirement_id = uuid5(
        NAMESPACE_URL,
        f"administrative:obligation-set:{case.case_id}:{case.authority_epoch}:"
        f"{governance_basis_id}",
    )
    return AdministrativeObligationSet(
        requirement_id=requirement_id,
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        governance_basis_id=governance_basis_id,
        obligations=tuple(obligations),
    )


__all__ = ["derive_offboarding_obligations"]
