from __future__ import annotations

from typing import Any

from .candidate_admission import CandidateAdministrativeAdmissionService
from .financial import (
    ExpenseFacts,
    ExpensePolicy,
    InvoiceAPPolicy,
    InvoiceFacts,
    ProcurementFacts,
    ProcurementPolicy,
)
from .intake.models import CandidateAdministrativeRequest
from .policy_plane import (
    PolicyVersionRecord,
    compile_expense_policy,
    compile_invoice_ap_policy,
    compile_procurement_policy,
)


class FinancialAdmissionError(ValueError):
    """Candidate data cannot safely enter a financial transaction case."""


def _candidate_values(
    service: str,
    candidate: CandidateAdministrativeRequest,
    repository,
    allowed: frozenset[str],
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for assertion in repository.list_candidate_facts(candidate.candidate_id):
        if assertion.fact_key not in allowed:
            raise FinancialAdmissionError(
                f"candidate fact {assertion.fact_key!r} is not allowed for {service}"
            )
        if assertion.fact_key in values:
            raise FinancialAdmissionError(
                f"candidate contains duplicate {service} fact {assertion.fact_key!r}"
            )
        values[assertion.fact_key] = assertion.value
    return values


class CandidateProcurementAdmissionService(CandidateAdministrativeAdmissionService):
    case_kind = "procurement-request"
    policy_id = "procurement-request"
    description = "procurement"
    error_type = FinancialAdmissionError
    snapshot_source_version = "m8-human-confirmed-v1"
    _FACT_KEYS = frozenset(ProcurementFacts.model_fields)

    def _candidate_facts(
        self, candidate: CandidateAdministrativeRequest, *, subject_ref: str
    ) -> ProcurementFacts:
        values = _candidate_values("procurement", candidate, self.repository, self._FACT_KEYS)
        values.setdefault("quote_ref", next(iter(map(str, candidate.source_refs)), None))
        return ProcurementFacts.model_validate(values)

    def _compile_policy(self, record: PolicyVersionRecord) -> ProcurementPolicy:
        return compile_procurement_policy(record)


class CandidateInvoiceAPAdmissionService(CandidateAdministrativeAdmissionService):
    case_kind = "invoice-ap-preparation"
    policy_id = "invoice-ap-preparation"
    description = "invoice/AP preparation"
    error_type = FinancialAdmissionError
    snapshot_source_version = "m8-human-confirmed-v1"
    _FACT_KEYS = frozenset(InvoiceFacts.model_fields)

    def _candidate_facts(
        self, candidate: CandidateAdministrativeRequest, *, subject_ref: str
    ) -> InvoiceFacts:
        values = _candidate_values("invoice", candidate, self.repository, self._FACT_KEYS)
        return InvoiceFacts.model_validate(values)

    def _compile_policy(self, record: PolicyVersionRecord) -> InvoiceAPPolicy:
        return compile_invoice_ap_policy(record)


class CandidateExpenseAdmissionService(CandidateAdministrativeAdmissionService):
    case_kind = "expense-reimbursement"
    policy_id = "expense-reimbursement"
    description = "expense reimbursement preparation"
    error_type = FinancialAdmissionError
    snapshot_source_version = "m8-human-confirmed-v1"
    _FACT_KEYS = frozenset(ExpenseFacts.model_fields)

    def _candidate_facts(
        self, candidate: CandidateAdministrativeRequest, *, subject_ref: str
    ) -> ExpenseFacts:
        values = _candidate_values("expense", candidate, self.repository, self._FACT_KEYS)
        supplied_employee = values.get("employee_ref")
        if supplied_employee is not None and str(supplied_employee).strip() != subject_ref:
            raise FinancialAdmissionError(
                "candidate employee_ref does not match the human-selected subject_ref"
            )
        values["employee_ref"] = subject_ref
        return ExpenseFacts.model_validate(values)

    def _compile_policy(self, record: PolicyVersionRecord) -> ExpensePolicy:
        return compile_expense_policy(record)


__all__ = [
    "CandidateExpenseAdmissionService",
    "CandidateInvoiceAPAdmissionService",
    "CandidateProcurementAdmissionService",
    "FinancialAdmissionError",
]
