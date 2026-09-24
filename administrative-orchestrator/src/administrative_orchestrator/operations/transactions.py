from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from ..access_policy import AdministrativePermission
from ..domain import AdministrativeCase, CaseStatus, FactAuthority, FactSnapshot
from ..fact_transitions import replace_facts_for_reevaluation
from ..financial import (
    AdministrativeCaseEvidenceLink,
    ExpenseFacts,
    InvoiceFacts,
    ProcurementFacts,
    TransactionQualificationAssessment,
    has_material_financial_revision,
)
from ..persistence import ConcurrencyConflict
from ..policy_plane import (
    PolicyPlaneError,
    compile_expense_policy,
    compile_invoice_ap_policy,
    compile_procurement_policy,
)
from ..service import TransitionError, apply_policy_evaluation
from .models import FinancialDocumentRevisionBody, QualificationAssessmentBody
from .runtime import OperationsRuntime

_TRANSACTION_CASE_KINDS = {
    "procurement-request",
    "invoice-ap-preparation",
    "expense-reimbursement",
}


def build_transaction_router(runtime: OperationsRuntime) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/v1/operations/cases/{case_id}/qualification-assessments",
        response_model=TransactionQualificationAssessment,
    )
    def append_qualification_assessment(
        case_id: UUID,
        payload: QualificationAssessmentBody,
        request: Request,
    ) -> TransactionQualificationAssessment:
        actor = runtime.actor(request)
        case = runtime.store.get_case(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="case not found")
        if case.case_kind not in _TRANSACTION_CASE_KINDS:
            raise HTTPException(status_code=409, detail="case kind is not a transaction case")
        runtime.require(actor, AdministrativePermission.FACTS_ATTEST, case=case)
        assessment = TransactionQualificationAssessment(
            case_id=case.case_id,
            authority_epoch=case.authority_epoch,
            assessment_kind=payload.assessment_kind,
            input_refs=payload.input_refs,
            rule_ref=payload.rule_ref,
            result=payload.result,
            blocking_reasons=payload.blocking_reasons,
        )
        return runtime.transactions.append_assessment(assessment)

    @router.post(
        "/v1/operations/cases/{case_id}/document-revision",
        response_model=AdministrativeCase,
    )
    def apply_financial_document_revision(
        case_id: UUID,
        payload: FinancialDocumentRevisionBody,
        request: Request,
    ) -> AdministrativeCase:
        actor = runtime.actor(request)
        case = runtime.store.get_case(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="case not found")
        if case.case_kind not in _TRANSACTION_CASE_KINDS:
            raise HTTPException(status_code=409, detail="case kind is not a transaction case")
        runtime.require(actor, AdministrativePermission.FACTS_ATTEST, case=case)
        if case.fact_snapshot is None:
            raise HTTPException(status_code=409, detail="case has no current document facts")
        if case.status in {CaseStatus.COMPLETED, CaseStatus.CANCELLED}:
            raise HTTPException(
                status_code=409, detail="terminal case cannot accept a document revision"
            )

        typed_facts: Any
        if case.case_kind == "procurement-request":
            typed_facts = ProcurementFacts.model_validate(payload.facts)
        elif case.case_kind == "invoice-ap-preparation":
            typed_facts = InvoiceFacts.model_validate(payload.facts)
        else:
            typed_facts = ExpenseFacts.model_validate(payload.facts)
        facts = typed_facts.model_dump(mode="json")
        try:
            material = has_material_financial_revision(
                case.case_kind,
                case.fact_snapshot.facts,
                facts,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not material:
            raise HTTPException(
                status_code=409, detail="document revision has no material financial change"
            )

        snapshot = FactSnapshot(
            source=f"document-revision:{actor.principal_id}",
            owner=actor.principal_id,
            authority=FactAuthority.CLAIM,
            source_ref=payload.source_ref,
            source_version=payload.source_version,
            facts=facts,
        )
        changed = replace_facts_for_reevaluation(case, snapshot)
        try:
            policy_record = runtime.policies.resolve_current(
                {
                    "procurement-request": "procurement-request",
                    "invoice-ap-preparation": "invoice-ap-preparation",
                    "expense-reimbursement": "expense-reimbursement",
                }[case.case_kind]
            )
            if case.case_kind == "procurement-request":
                evaluation = compile_procurement_policy(policy_record).evaluate(typed_facts)
            elif case.case_kind == "invoice-ap-preparation":
                evaluation = compile_invoice_ap_policy(policy_record).evaluate(typed_facts)
            else:
                evaluation = compile_expense_policy(policy_record).evaluate(typed_facts)
            updated = apply_policy_evaluation(changed, evaluation)
            runtime.uow.replace_facts_and_apply_policy(case, updated, evaluation)
        except (ConcurrencyConflict, TransitionError, PolicyPlaneError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        if payload.artifact_ref is not None:
            runtime.transactions.append_evidence_link(
                AdministrativeCaseEvidenceLink(
                    case_id=updated.case_id,
                    authority_epoch=updated.authority_epoch,
                    artifact_ref=payload.artifact_ref,
                    representation_ref=payload.representation_ref,
                    declared_role=payload.declared_role,
                    source=payload.source_ref,
                    linked_by=actor.principal_id,
                )
            )
        return updated

    return router


__all__ = ["build_transaction_router"]
