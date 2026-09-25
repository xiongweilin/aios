from __future__ import annotations

from uuid import UUID

from .authority import AuthorityRepository
from .domain import AdministrativeCase
from .financial_obligations import derive_financial_obligations
from .obligations import AdministrativeObligationSet, ObligationError
from .offboarding_obligations import derive_offboarding_obligations
from .onboarding_obligations import derive_onboarding_obligations
from .policy import OffboardingPolicy, PolicyEvaluation


def derive_administrative_obligations(
    case: AdministrativeCase,
    evaluation: PolicyEvaluation,
    *,
    governance_basis_id: UUID,
    offboarding_policy: OffboardingPolicy | None = None,
    authority_repository: AuthorityRepository | None = None,
) -> AdministrativeObligationSet:
    """Dispatch obligation derivation by case kind without owning domain semantics."""
    if case.case_kind == "employee-onboarding":
        return derive_onboarding_obligations(
            case, evaluation, governance_basis_id=governance_basis_id
        )
    if case.case_kind == "employee-offboarding":
        if offboarding_policy is None or authority_repository is None:
            raise ObligationError(
                "offboarding derivation requires policy and authority repository"
            )
        return derive_offboarding_obligations(
            case,
            evaluation,
            offboarding_policy,
            authority_repository,
            governance_basis_id=governance_basis_id,
        )
    if case.case_kind in {
        "procurement-request",
        "invoice-ap-preparation",
        "expense-reimbursement",
    }:
        return derive_financial_obligations(
            case, evaluation, governance_basis_id=governance_basis_id
        )
    raise ObligationError(
        f"no obligation derivation is registered for case kind {case.case_kind!r}"
    )


__all__ = ["derive_administrative_obligations"]
