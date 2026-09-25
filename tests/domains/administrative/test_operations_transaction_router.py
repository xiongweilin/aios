from __future__ import annotations

from types import SimpleNamespace

from starlette.requests import Request

from administrative_orchestrator.access_policy import AdministrativePermission
from administrative_orchestrator.financial import TransactionQualificationResult
from administrative_orchestrator.operations.models import QualificationAssessmentBody
from administrative_orchestrator.operations.transactions import build_transaction_router

from .test_m8_transactions import _financial_case


def test_transaction_router_records_qualification_against_current_authority_epoch() -> None:
    _, case, _ = _financial_case()
    recorded = []
    required = []

    class Store:
        @staticmethod
        def get_case(case_id):
            assert case_id == case.case_id
            return case

    class Transactions:
        @staticmethod
        def append_assessment(assessment):
            recorded.append(assessment)
            return assessment

    def require(actor, permission, *, case):
        required.append((actor.principal_id, permission, case.case_id))

    runtime = SimpleNamespace(
        actor=lambda request: SimpleNamespace(principal_id="reviewer:transaction"),
        store=Store(),
        transactions=Transactions(),
        require=require,
    )
    router = build_transaction_router(runtime)
    endpoint = next(
        route.endpoint
        for route in router.routes
        if route.path == "/v1/operations/cases/{case_id}/qualification-assessments"
        and "POST" in route.methods
    )
    payload = QualificationAssessmentBody(
        assessment_kind="vendor-qualification",
        input_refs=("artifact:quote:1", "vendor:master:42"),
        rule_ref="m8-vendor-qualification-v1",
        result=TransactionQualificationResult.QUALIFIED,
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/v1/operations/cases/{case.case_id}/qualification-assessments",
            "headers": [],
        }
    )

    assessment = endpoint(case.case_id, payload, request)

    assert assessment is recorded[0]
    assert assessment.case_id == case.case_id
    assert assessment.authority_epoch == case.authority_epoch
    assert assessment.assessment_kind == "vendor-qualification"
    assert assessment.result is TransactionQualificationResult.QUALIFIED
    assert required == [
        (
            "reviewer:transaction",
            AdministrativePermission.FACTS_ATTEST,
            case.case_id,
        )
    ]
