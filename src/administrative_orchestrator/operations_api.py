from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .access_policy import AccessDenied, AdministrativePermission
from .admission import IntakeAssessmentService, IntakePromotionService
from .operations import projection as _projection
from .operations.administration import (
    _apply_authoritative_refresh as _apply_authoritative_refresh_impl,
)
from .operations.administration import build_administration_router
from .operations.cases import build_case_router
from .operations.commitments import build_commitment_router
from .operations.intake import _admission_bridge as _admission_bridge_impl
from .operations.intake import build_intake_router
from .operations.investigations import build_investigation_router
from .operations.models import (
    BindIdentityBody,
    CommitmentCancellationBody,
    CommitmentCandidateQueueItem,
    CommitmentConfirmationBody,
    CommitmentDueRevisionBody,
    CommitmentFulfillmentBody,
    CommitmentSpeakerResolutionBody,
    ExpireAuthorityBody,
    FinancialDocumentRevisionBody,
    IntakeAssessmentBody,
    IntakeCandidateDetail,
    IntakePromotionBody,
    IntakePromotionResponse,
    IntakeQueueItem,
    InvestigationEvidenceBody,
    InvestigationEvidenceRequestBody,
    InvestigationProposalBody,
    InvestigationRequestBody,
    OutboxReplayResponse,
    QualificationAssessmentBody,
    QueueItem,
    RefreshFactsResponse,
    ReopenAssessmentBody,
    ReopenCaseBody,
)
from .operations.runtime import OperationsRuntime, build_operations_runtime
from .operations.transactions import build_transaction_router
from .production_readiness import (
    ProductionReadinessError,
    validate_world_runtime_compatibility,
)
from .responsibility_discharge import AdministrativeResponsibilityDischargeService

app = FastAPI(title="Administrative Operations API", version="0.3.0")
_runtime: OperationsRuntime = build_operations_runtime()

# Compatibility aliases for existing tests, operational probes, and local
# tooling. Ownership and construction live in operations.runtime; these names
# remain mutable because the pre-refactor module was an established test seam.
_settings = _runtime.settings
_store = _runtime.store
_authority = _runtime.authority
_access = _runtime.access
_authenticator = _runtime.authenticator
_lifecycle = _runtime.lifecycle
_execution = _runtime.execution
_governance = _runtime.governance
_obligations = _runtime.obligations
_policies = _runtime.policies
_transactions = _runtime.transactions
_uow = _runtime.uow
_intake = _runtime.intake
_intake_assessments = _runtime.intake_assessments
_intake_promotions = _runtime.intake_promotions
_commitments = _runtime.commitments
_commitment_service = _runtime.commitment_service
_investigations = _runtime.investigations
_investigation_service = _runtime.investigation_service


class _CompatibilityRuntime:
    """Resolve router collaborators through the legacy mutable module seam."""

    @property
    def settings(self):
        return _settings

    @property
    def store(self):
        return _store

    @property
    def authority(self):
        return _authority

    @property
    def access(self):
        return _access

    @property
    def authenticator(self):
        return _authenticator

    @property
    def lifecycle(self):
        return _lifecycle

    @property
    def execution(self):
        return _execution

    @property
    def governance(self):
        return _governance

    @property
    def obligations(self):
        return _obligations

    @property
    def policies(self):
        return _policies

    @property
    def transactions(self):
        return _transactions

    @property
    def uow(self):
        return _uow

    @property
    def intake(self):
        return _intake

    @property
    def intake_assessments(self):
        return _intake_assessments

    @property
    def intake_promotions(self):
        return _intake_promotions

    @property
    def commitments(self):
        return _commitments

    @property
    def commitment_service(self):
        return _commitment_service

    @property
    def investigations(self):
        return _investigations

    @property
    def investigation_service(self):
        return _investigation_service

    def actor(self, request):
        return _actor(request)

    def require(self, actor, permission, *, case=None) -> None:
        _require(actor, permission, case=case)

    def require_intake_review(self, actor) -> None:
        _require_intake_review(actor)


_http_runtime = _CompatibilityRuntime()


def _actor(request):
    return _authenticator.authenticate(request)


def _require(actor, permission, *, case=None) -> None:
    try:
        _access.require(
            actor.principal_id,
            permission,
            case=case,
            organization_scope="*" if case is None else None,
        )
    except AccessDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _require_intake_review(actor) -> None:
    _require(actor, AdministrativePermission.INTAKE_REVIEW)


# Preserve helper names previously defined by operations_api.py without
# keeping their implementation in the HTTP composition root.
_case_completion_assessment = _projection.case_completion_assessment
_dedupe_json_records = _projection.dedupe_json_records
_termination_snapshot = _projection.termination_snapshot


def _authority_snapshot(case):
    return _projection.authority_snapshot(_http_runtime, case)


def _responsibility_snapshot(case, obligation_set, completion, projections=None):
    del projections
    return _projection.responsibility_snapshot(
        _http_runtime,
        case,
        obligation_set,
        completion,
        discharge_service_factory=AdministrativeResponsibilityDischargeService,
    )


def _apply_authoritative_refresh(case, record):
    return _apply_authoritative_refresh_impl(_http_runtime, case, record)


def _admission_bridge(case_kind):
    return _admission_bridge_impl(_http_runtime, case_kind)


def readyz() -> dict[str, str]:
    if (
        _settings.runtime_profile in {"staging", "production"}
        and _settings.world_runtime_mode != "disabled"
    ):
        try:
            validate_world_runtime_compatibility(_settings)
        except ProductionReadinessError as exc:
            raise HTTPException(
                status_code=503,
                detail="World Runtime compatibility/readiness check failed",
            ) from exc
    return {
        "status": "ready",
        "auth_mode": _settings.auth_mode,
        "runtime_profile": _settings.runtime_profile,
        "hris_source": _settings.hris_source_kind,
        "iam_source": _settings.iam_source_kind,
        "authority_mutation_shortcuts": "forbidden",
        "world_runtime": (
            _settings.world_runtime_mode
            if _settings.runtime_profile in {"staging", "production"}
            else "not-required"
        ),
    }


_case_router = build_case_router(_http_runtime)
_investigation_router = build_investigation_router(_http_runtime)
_transaction_router = build_transaction_router(_http_runtime)
_intake_router = build_intake_router(_http_runtime)
_commitment_router = build_commitment_router(_http_runtime)
_administration_router = build_administration_router(_http_runtime)

app.include_router(_case_router)
app.include_router(_investigation_router)
app.include_router(_transaction_router)
app.include_router(_intake_router)
app.include_router(_commitment_router)
app.include_router(_administration_router)


def _endpoint(router, path: str, method: str):
    method = method.upper()
    for route in router.routes:
        methods = getattr(route, "methods", None) or set()
        if getattr(route, "path", None) == path and method in methods:
            endpoint = getattr(route, "endpoint", None)
            if endpoint is not None:
                return endpoint
    raise RuntimeError(f"operations route {method} {path!r} is unavailable")


# The old module exposed its route functions directly. Bind those names from
# the source APIRouters before FastAPI copies their route registrations.
healthz = _endpoint(_case_router, "/healthz", "GET")
case_queue = _endpoint(_case_router, "/v1/operations/cases", "GET")
case_detail = _endpoint(_case_router, "/v1/operations/cases/{case_id}", "GET")
request_case_investigation = _endpoint(
    _investigation_router, "/v1/operations/cases/{case_id}/investigations", "POST"
)
list_case_investigations = _endpoint(
    _investigation_router, "/v1/operations/cases/{case_id}/investigations", "GET"
)
investigation_detail = _endpoint(
    _investigation_router, "/v1/operations/investigations/{investigation_id}", "GET"
)
run_investigation = _endpoint(
    _investigation_router, "/v1/operations/investigations/{investigation_id}/run", "POST"
)
record_investigation_proposal = _endpoint(
    _investigation_router,
    "/v1/operations/investigations/{investigation_id}/proposals",
    "POST",
)
request_investigation_evidence = _endpoint(
    _investigation_router,
    "/v1/operations/investigations/{investigation_id}/evidence-requests",
    "POST",
)
add_investigation_evidence = _endpoint(
    _investigation_router,
    "/v1/operations/investigations/{investigation_id}/evidence",
    "POST",
)
assess_investigation_reopen = _endpoint(
    _investigation_router,
    "/v1/operations/investigations/{investigation_id}/human-assessment",
    "POST",
)
assess_case_reopen = _endpoint(
    _investigation_router, "/v1/operations/cases/{case_id}/reopen-assessments", "POST"
)
authorize_case_reopen = _endpoint(
    _investigation_router, "/v1/operations/cases/{case_id}/reopen", "POST"
)
case_reopen_history = _endpoint(
    _investigation_router, "/v1/operations/cases/{case_id}/reopen-history", "GET"
)
append_qualification_assessment = _endpoint(
    _transaction_router,
    "/v1/operations/cases/{case_id}/qualification-assessments",
    "POST",
)
apply_financial_document_revision = _endpoint(
    _transaction_router, "/v1/operations/cases/{case_id}/document-revision", "POST"
)
intake_candidate_queue = _endpoint(_intake_router, "/v1/operations/intake/candidates", "GET")
intake_candidate_detail = _endpoint(
    _intake_router, "/v1/operations/intake/candidates/{candidate_id}", "GET"
)
finalize_intake_assessment = _endpoint(
    _intake_router,
    "/v1/operations/intake/candidates/{candidate_id}/assessments",
    "POST",
)
promote_intake_candidate = _endpoint(
    _intake_router, "/v1/operations/intake/candidates/{candidate_id}/promote", "POST"
)
commitment_candidate_queue = _endpoint(
    _commitment_router, "/v1/operations/commitments/candidates", "GET"
)
commitment_candidate_detail = _endpoint(
    _commitment_router,
    "/v1/operations/commitments/candidates/{candidate_id}",
    "GET",
)
resolve_commitment_speaker = _endpoint(
    _commitment_router,
    "/v1/operations/commitments/candidates/{candidate_id}/resolve-speaker",
    "POST",
)
confirm_commitment_candidate = _endpoint(
    _commitment_router,
    "/v1/operations/commitments/candidates/{candidate_id}/confirm",
    "POST",
)
commitment_detail = _endpoint(
    _commitment_router, "/v1/operations/commitments/{case_id}", "GET"
)
attest_commitment_fulfillment = _endpoint(
    _commitment_router, "/v1/operations/commitments/{case_id}/fulfillment", "POST"
)
revise_commitment_due = _endpoint(
    _commitment_router, "/v1/operations/commitments/{case_id}/due-revision", "POST"
)
cancel_commitment = _endpoint(
    _commitment_router, "/v1/operations/commitments/{case_id}/cancel", "POST"
)
refresh_authoritative_facts = _endpoint(
    _administration_router,
    "/v1/operations/cases/{case_id}/authoritative-facts/refresh",
    "POST",
)
replay_dead_letter = _endpoint(
    _administration_router, "/v1/operations/outbox/dead-letter/{event_id}/replay", "POST"
)
bind_identity = _endpoint(_administration_router, "/v1/operations/identities/bind", "POST")
revoke_identity = _endpoint(
    _administration_router, "/v1/operations/identities/{binding_id}/revoke", "POST"
)
deactivate_principal = _endpoint(
    _administration_router, "/v1/operations/principals/{principal_id}/deactivate", "POST"
)
expire_role_assignment = _endpoint(
    _administration_router,
    "/v1/operations/role-assignments/{assignment_id}/expire",
    "POST",
)
expire_delegation = _endpoint(
    _administration_router, "/v1/operations/delegations/{delegation_id}/expire", "POST"
)
authority_events = _endpoint(_administration_router, "/v1/operations/authority-events", "GET")


__all__ = [
    "app",
    "AdministrativeResponsibilityDischargeService",
    "BindIdentityBody",
    "CommitmentCancellationBody",
    "CommitmentCandidateQueueItem",
    "CommitmentConfirmationBody",
    "CommitmentDueRevisionBody",
    "CommitmentFulfillmentBody",
    "CommitmentSpeakerResolutionBody",
    "ExpireAuthorityBody",
    "FinancialDocumentRevisionBody",
    "IntakeAssessmentBody",
    "IntakeAssessmentService",
    "IntakeCandidateDetail",
    "IntakePromotionBody",
    "IntakePromotionResponse",
    "IntakePromotionService",
    "IntakeQueueItem",
    "InvestigationEvidenceBody",
    "InvestigationEvidenceRequestBody",
    "InvestigationProposalBody",
    "InvestigationRequestBody",
    "OutboxReplayResponse",
    "QualificationAssessmentBody",
    "QueueItem",
    "RefreshFactsResponse",
    "ReopenAssessmentBody",
    "ReopenCaseBody",
    "validate_world_runtime_compatibility",
]
