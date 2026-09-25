from __future__ import annotations

from uuid import UUID

from .domain import AdministrativeCase
from .onboarding_execution import OnboardingExecutionEngine
from .service import TransitionError

FINANCIAL_CASE_KINDS = frozenset(
    {
        "procurement-request",
        "invoice-ap-preparation",
        "expense-reimbursement",
    }
)


class FinancialExecutionEngine(OnboardingExecutionEngine):
    """Reuse the governed effect lifecycle for bounded ERP preparations."""

    def run(self, case_id: UUID) -> AdministrativeCase:
        case = self._require_case(case_id)
        if case.case_kind not in FINANCIAL_CASE_KINDS:
            raise TransitionError(
                f"financial execution engine requires a financial case, got {case.case_kind!r}"
            )
        return super().run(case_id)


__all__ = ["FINANCIAL_CASE_KINDS", "FinancialExecutionEngine"]
