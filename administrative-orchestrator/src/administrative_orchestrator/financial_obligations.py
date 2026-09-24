from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from .domain import AdministrativeCase
from .obligation_derivation_common import domain_or_external_obligation
from .obligations import (
    AdministrativeObligation,
    AdministrativeObligationSet,
    ObligationError,
    ObligationFulfillmentKind,
)
from .policy import PolicyEvaluation


def derive_financial_obligations(
    case: AdministrativeCase,
    evaluation: PolicyEvaluation,
    *,
    governance_basis_id: UUID,
) -> AdministrativeObligationSet:
    """Freeze the bounded ERP preparation effects for an M8 transaction case."""
    allowed_case_kinds = {
        "procurement-request",
        "invoice-ap-preparation",
        "expense-reimbursement",
    }
    if case.case_kind not in allowed_case_kinds:
        raise ObligationError("financial obligations require a supported transaction case")
    if case.fact_snapshot is None:
        raise ObligationError("financial obligations require current facts")
    if evaluation.policy_ref != case.policy_ref:
        raise ObligationError("financial obligations require current policy evaluation")

    expected_operations = {
        "procurement-request": {
            "purchase_order.create_draft",
            "purchase_order.confirm",
        },
        "invoice-ap-preparation": {"vendor_bill.create_draft"},
        "expense-reimbursement": {"expense_report.create"},
    }[case.case_kind]
    if not evaluation.allowed_effects:
        raise ObligationError("current financial policy produces no required obligations")

    obligations: list[AdministrativeObligation] = []
    facts = case.fact_snapshot.facts
    operation_order = {
        "purchase_order.create_draft": 0,
        "purchase_order.confirm": 1,
        "vendor_bill.create_draft": 0,
        "expense_report.create": 0,
    }
    for template in sorted(
        evaluation.allowed_effects,
        key=lambda item: (
            item.target_system,
            operation_order.get(item.operation, 99),
            item.operation,
        ),
    ):
        if template.target_system != "erp":
            raise ObligationError("financial effects must target the ERP boundary")
        if template.operation not in expected_operations:
            raise ObligationError(
                f"financial effect is outside the case contract: {template.operation!r}"
            )
        expected_postcondition = {
            "target_system": "erp",
            "operation": template.operation,
            "subject_ref": case.subject_ref,
            "transaction_case_ref": str(case.case_id),
            "authority_epoch": case.authority_epoch,
            "payload": dict(facts),
            "preconditions": ["qualification_assessments_current"],
            "settlement": "forbidden",
        }
        if case.case_kind in {"procurement-request", "invoice-ap-preparation"}:
            expected_postcondition["vendor_qualification"] = "required"
        if case.case_kind == "invoice-ap-preparation":
            expected_postcondition["three_way_match"] = "required"
        if template.operation == "purchase_order.confirm":
            expected_postcondition["requires_draft_reference"] = True
        obligations.append(
            domain_or_external_obligation(
                case,
                governance_basis_id,
                discriminator=f"external:erp:{template.operation}",
                kind=f"erp.{template.operation}",
                target_system="erp",
                operation=template.operation,
                expected_postcondition=expected_postcondition,
                authority_class=template.authority_class,
                fulfillment_kind=ObligationFulfillmentKind.EXTERNAL_EFFECT_VERIFIED,
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


__all__ = ["derive_financial_obligations"]
