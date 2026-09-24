from __future__ import annotations

import hashlib
import hmac
import os
import time
from importlib.metadata import version as package_version
from typing import Any, Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from .access_policy import (
    AccessDenied,
    AdministrativeAccessPolicy,
    AdministrativePermission,
)
from .auth import AuthenticatedPrincipal, Authenticator
from .authority import (
    ApprovalAssessment,
    AuthorityError,
    AuthorityRepository,
    assess_approval_satisfaction,
    resolve_decision_role,
)
from .completion import (
    CompletionAssessment,
    assess_administrative_completion,
    assess_onboarding_completion,
)
from .config import get_settings
from .domain import (
    AdministrativeCase,
    AdministrativeRequest,
    ConfirmedOutcome,
    Decision,
    DecisionDisposition,
    EffectRealizationAssessment,
    EffectRecord,
    ExecutionAuthorization,
    FactAuthority,
    FactSnapshot,
)
from .execution_repository import ExecutionRepository
from .fact_history import list_fact_snapshots
from .fact_transitions import replace_facts_for_reevaluation
from .governance import GovernanceBasis, GovernanceRepository
from .ingress import DuplicateIngressEvent, get_ingress_receipt
from .inspection import list_authorizations, list_decisions, list_realizations
from .intake.repository import IntakeReceiptConflict
from .messaging import FailedOutboxEvent, list_failed_outbox
from .obligations import ObligationRepository, OnboardingObligationSet
from .persistence import ConcurrencyConflict, SqlStore
from .policy import OnboardingFacts, PolicyEvaluation
from .policy_plane import (
    PolicyPlaneError,
    PolicyRepository,
    PolicyVersionRecord,
    compile_onboarding_policy,
)
from .production_readiness import (
    ProductionReadinessError,
    validate_world_runtime_compatibility,
)
from .providers.feishu import (
    FeishuAcceptance,
    FeishuChallenge,
    FeishuVerificationError,
    FeishuWebhookBoundary,
)
from .providers.feishu_runtime import build_feishu_webhook_boundary
from .service import (
    TransitionError,
    apply_policy_evaluation,
    create_case,
    explicit_reopen,
    record_decision,
    start_policy_evaluation,
)
from .unit_of_work import AdministrativeUnitOfWork

app = FastAPI(
    title="Administrative Orchestrator",
    version=package_version("administrative-orchestrator"),
)

_settings = get_settings()
_store = SqlStore(_settings.database_url)
_uow = AdministrativeUnitOfWork(_store)
_execution = ExecutionRepository(_store)
_authority = AuthorityRepository(_store)
_access = AdministrativeAccessPolicy(_authority)
_policies = PolicyRepository(_store)
_governance = GovernanceRepository(_store)
_obligations = ObligationRepository(_store)
_authenticator = Authenticator(_store, _settings)
_feishu_intake_boundary: FeishuWebhookBoundary | None = None
if _settings.auto_create_schema:
    # UoW and repositories above intentionally import/register all domain row
    # models before metadata creation.
    _store.init_schema()


def configure_feishu_intake(boundary: FeishuWebhookBoundary | None) -> None:
    """Inject the provider verifier without making secrets part of app import."""
    global _feishu_intake_boundary
    _feishu_intake_boundary = boundary


configure_feishu_intake(build_feishu_webhook_boundary(_store, _settings))


class CreateOnboardingCase(BaseModel):
    employee_ref: str
    department_ref: str | None = None
    manager_principal_id: str | None = None
    start_date: str | None = None
    employment_type: str | None = None
    requested_systems: tuple[str, ...] = ()
    requires_privileged_access: bool = False
    channel: str = "api"
    source_event_id: str | None = Field(default=None, min_length=1, max_length=512)


class ReplaceOnboardingFacts(BaseModel):
    employee_ref: str
    department_ref: str | None = None
    manager_principal_id: str | None = None
    start_date: str | None = None
    employment_type: str | None = None
    requested_systems: tuple[str, ...] = ()
    requires_privileged_access: bool = False
    attestation_ref: str | None = Field(default=None, max_length=1000)
    # Compatibility only. Caller-supplied source labels are never trusted as
    # authoritative provenance.
    source: str | None = None


class OnboardingCaseResponse(BaseModel):
    case: AdministrativeCase
    policy_evaluation: PolicyEvaluation


class RecordDecisionBody(BaseModel):
    role: str | None = None
    disposition: DecisionDisposition
    rationale: str = Field(min_length=1)


class DecisionResponse(BaseModel):
    decision: Decision
    case: AdministrativeCase
    approval: ApprovalAssessment | None = None


class AgencyConsoleDispositionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    gesture_id: UUID = Field(alias="gestureId")
    principal_ref: str = Field(alias="principalRef", min_length=1)
    proposal_ref: str = Field(alias="proposalRef", min_length=1)
    proposal_version: str = Field(alias="proposalVersion", min_length=1)
    expected_state_version: str = Field(alias="expectedStateVersion", min_length=1)
    disposition: Literal["approved", "rejected"]
    occurred_at: str = Field(alias="occurredAt", min_length=1)


def _authenticate(request: Request) -> AuthenticatedPrincipal:
    return _authenticator.authenticate(request)


def _authorize(
    actor: AuthenticatedPrincipal,
    permission: AdministrativePermission,
    *,
    case: AdministrativeCase | None = None,
    organization_scope: str | None = None,
) -> None:
    try:
        _access.require(
            actor.principal_id,
            permission,
            case=case,
            organization_scope=organization_scope,
        )
    except AccessDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _case_scope(case: AdministrativeCase) -> str:
    facts = case.fact_snapshot.facts if case.fact_snapshot else {}
    department = facts.get("department_ref")
    return str(department) if department else "*"


def _agency_console_secret() -> str:
    secret = os.getenv("ADMIN_AGENCY_CONSOLE_SHARED_SECRET", "").strip()
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Agency Console integration authentication is not configured",
        )
    return secret


def _verify_agency_console_request(request: Request, body: bytes = b"") -> None:
    timestamp = request.headers.get("X-Agency-Console-Timestamp", "").strip()
    signature = request.headers.get("X-Agency-Console-Signature", "").strip().lower()
    if not timestamp or not signature:
        raise HTTPException(status_code=401, detail="Agency Console signature is required")
    try:
        asserted_at = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid Agency Console timestamp") from exc
    ttl = max(1, int(os.getenv("ADMIN_AGENCY_CONSOLE_ASSERTION_TTL_SECONDS", "60")))
    if abs(int(time.time()) - asserted_at) > ttl:
        raise HTTPException(status_code=401, detail="Agency Console assertion is expired")
    body_digest = hashlib.sha256(body).hexdigest()
    canonical = f"{timestamp}\n{request.method.upper()}\n{request.url.path}\n{body_digest}".encode()
    expected = hmac.new(_agency_console_secret().encode(), canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature.removeprefix("sha256=")):
        raise HTTPException(status_code=401, detail="invalid Agency Console signature")


def _agency_console_binding(case: AdministrativeCase) -> dict[str, object] | None:
    if case.status.value != "awaiting_decision":
        return None
    version = str(case.version)
    proposal_ref = f"administrative:case:{case.case_id}:decision"
    return {
        "bindingId": f"administrative:case:{case.case_id}:decision:{version}",
        "sourceSystem": "administrative-orchestrator",
        "commandName": "case.disposition",
        "targetRef": str(case.case_id),
        "expectedTargetVersion": version,
        "proposalRef": proposal_ref,
        "proposalVersion": version,
        "allowedDispositions": ["approved", "rejected"],
        "readBackRef": f"administrative:case:{case.case_id}",
    }


def _current_onboarding_policy():
    try:
        record = _policies.resolve_current("employee-onboarding")
    except PolicyPlaneError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return compile_onboarding_policy(record)


def _existing_onboarding_response(
    source_event_id: str,
    *,
    requester_principal_id: str,
) -> OnboardingCaseResponse | None:
    receipt = get_ingress_receipt(_store, source_event_id)
    if receipt is None:
        return None
    case = _store.get_case(receipt.case_id)
    if case is None:
        raise HTTPException(status_code=500, detail="ingress receipt points to missing case")
    if case.requester_principal_id != requester_principal_id:
        raise HTTPException(
            status_code=409,
            detail="source event id is already owned by a different requester",
        )
    evaluation = _store.get_latest_policy_evaluation(case.case_id)
    if evaluation is None:
        raise HTTPException(
            status_code=409,
            detail="source event already created a case that has not completed policy evaluation",
        )
    return OnboardingCaseResponse(case=case, policy_evaluation=evaluation)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/v1/agency-console/contracts")
def agency_console_contracts() -> dict[str, object]:
    return {
        "manifest": "agency-console-controller-contracts-v2",
        "system": "administrative-orchestrator",
        "contract": "administrative-agency-console-v2",
        "package": "1.0.0",
        "runtime_protocol": "4.0",
        "reads": {
            "health": "/healthz",
            "ready": "/readyz",
            "case": "/v1/cases/{case_id}",
            "facts": "/v1/cases/{case_id}/facts",
            "decisions": "/v1/cases/{case_id}/decisions",
            "authorizations": "/v1/cases/{case_id}/authorizations",
            "effects": "/v1/cases/{case_id}/effects",
            "outcomes": "/v1/cases/{case_id}/outcomes",
            "completion": "/v1/cases/{case_id}/completion",
            "console_proposal": "/v1/agency-console/cases/{case_id}/proposal",
            "console_projection": "/v1/agency-console/cases/{case_id}/projection",
        },
        "commands": {
            "disposition": "/v1/agency-console/cases/{case_id}/dispositions",
            "reopen": "/v1/cases/{case_id}/reopen",
        },
        "command_version_semantics": "administrative-case-version",
    }


@app.get("/v1/agency-console/cases/{case_id}/proposal")
def agency_console_case_proposal(case_id: UUID, request: Request) -> dict[str, object]:
    _verify_agency_console_request(request)
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    binding = _agency_console_binding(case)
    proposal = None
    if binding is not None:
        proposal = {
            "proposalRef": binding["proposalRef"],
            "proposalVersion": str(case.version),
            "expectedStateVersion": str(case.version),
            "title": f"Administrative decision for {case.subject_ref}",
            "rationale": f"Case {case.case_kind} is awaiting an authorized human decision.",
            "scope": [f"administrative:{case.case_kind}"],
            "resources": [case.subject_ref],
            "irreversibleConsequences": [],
            "evidenceRefs": [],
            "unknowns": [],
            "commandBinding": binding,
        }
    return {
        "caseRef": str(case.case_id),
        "caseVersion": str(case.version),
        "caseStatus": case.status.value,
        "proposal": proposal,
    }


@app.get("/v1/agency-console/cases/{case_id}/projection")
def agency_console_case_projection(case_id: UUID, request: Request) -> dict[str, object]:
    _verify_agency_console_request(request)
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    effects = _execution.list_effects(case.case_id, case.authority_epoch)
    outcomes = _execution.list_outcomes(case.case_id, case.authority_epoch)
    realizations = _execution.list_realizations(case.case_id, case.authority_epoch)
    obligation_set = _obligations.get_current(case.case_id, case.authority_epoch)
    if obligation_set is None:
        completion = assess_onboarding_completion(effects, outcomes, realizations=realizations)
    else:
        completion = assess_administrative_completion(
            obligation_set,
            effects,
            outcomes,
            realizations=realizations,
            links=_obligations.list_links(case.case_id, case.authority_epoch),
            fulfillments=_obligations.list_domain_state_fulfillments(
                case.case_id, case.authority_epoch
            ),
        )
    return {
        "case": case.model_dump(mode="json"),
        "decisions": [item.model_dump(mode="json") for item in list_decisions(_store, case.case_id)],
        "authorizations": [
            item.model_dump(mode="json") for item in list_authorizations(_store, case.case_id)
        ],
        "effects": [item.model_dump(mode="json") for item in effects],
        "realizations": [item.model_dump(mode="json") for item in realizations],
        "outcomes": [item.model_dump(mode="json") for item in outcomes],
        "completion": completion.model_dump(mode="json"),
        "commandBinding": _agency_console_binding(case),
    }


@app.post("/v1/agency-console/cases/{case_id}/dispositions")
async def agency_console_case_disposition(case_id: UUID, request: Request) -> dict[str, object]:
    raw = await request.body()
    _verify_agency_console_request(request, raw)
    try:
        payload = AgencyConsoleDispositionBody.model_validate_json(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid Agency Console disposition") from exc

    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    expected_proposal_ref = f"administrative:case:{case.case_id}:decision"
    if payload.proposal_ref != expected_proposal_ref:
        raise HTTPException(status_code=409, detail="proposal reference is stale")

    existing = _store.get_decision(payload.gesture_id)
    if existing is not None:
        expected_disposition = (
            DecisionDisposition.APPROVE
            if payload.disposition == "approved"
            else DecisionDisposition.REJECT
        )
        if (
            existing.case_id != case.case_id
            or existing.principal_id != payload.principal_ref
            or existing.disposition != expected_disposition
            or str(existing.case_version) != payload.proposal_version
            or str(existing.case_version) != payload.expected_state_version
        ):
            raise HTTPException(status_code=409, detail="gesture id is already bound differently")
        current = _store.get_case(case_id)
        if current is None:
            raise HTTPException(status_code=404, detail="case not found")
        return {
            "commandId": f"administrative:{payload.gesture_id}",
            "accepted": True,
            "authoritativeRef": str(existing.decision_id),
            "stateVersion": str(current.version),
            "status": "accepted",
            "message": "Human disposition was already admitted; returning authoritative replay.",
            "replayed": True,
        }

    if payload.proposal_version != str(case.version) or payload.expected_state_version != str(
        case.version
    ):
        raise HTTPException(status_code=409, detail="administrative case version is stale")

    principal = _authority.get_principal(payload.principal_ref)
    if principal is None:
        raise HTTPException(status_code=403, detail="represented principal is not active")
    try:
        _access.require(
            payload.principal_ref,
            AdministrativePermission.DECISION_SUBMIT,
            case=case,
        )
    except AccessDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if case.policy_ref is None:
        raise HTTPException(status_code=409, detail="case has no current policy")
    evaluation = _store.get_latest_policy_evaluation(case.case_id)
    if evaluation is None or evaluation.policy_ref != case.policy_ref:
        raise HTTPException(status_code=409, detail="case has no current policy evaluation")

    scope = _case_scope(case)
    try:
        role = resolve_decision_role(
            _authority,
            principal_id=payload.principal_ref,
            evaluation=evaluation,
            organization_scope=scope,
            requested_role=None,
        )
    except AuthorityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    disposition = (
        DecisionDisposition.APPROVE
        if payload.disposition == "approved"
        else DecisionDisposition.REJECT
    )
    decision = Decision(
        decision_id=payload.gesture_id,
        case_id=case.case_id,
        case_version=case.version,
        authority_epoch=case.authority_epoch,
        principal_id=payload.principal_ref,
        decision_role=role,
        disposition=disposition,
        rationale=f"Agency Console human disposition {payload.gesture_id}",
        policy_ref=case.policy_ref,
    )
    approval: ApprovalAssessment | None = None
    approval_complete = False
    satisfaction = None
    if disposition == DecisionDisposition.APPROVE:
        prior_decisions = list_decisions(_store, case.case_id)
        approval = assess_approval_satisfaction(
            _authority,
            case_id=case.case_id,
            authority_epoch=case.authority_epoch,
            policy_ref=case.policy_ref,
            evaluation=evaluation,
            decisions=[*prior_decisions, decision],
            organization_scope=scope,
        )
        approval_complete = approval.satisfied
        satisfaction = approval.satisfaction

    try:
        updated = record_decision(case, decision, approval_complete=approval_complete)
        _uow.apply_decision_transition(
            case,
            updated,
            decision,
            organization_scope=scope,
            approval_satisfaction=satisfaction,
        )
    except (TransitionError, ConcurrencyConflict, ValueError, AuthorityError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {
        "commandId": f"administrative:{payload.gesture_id}",
        "accepted": True,
        "authoritativeRef": str(decision.decision_id),
        "stateVersion": str(updated.version),
        "status": "accepted",
        "message": "Human disposition admitted by Administrative authority and state transition.",
        "replayed": False,
    }


@app.post("/v1/intake/feishu/events", status_code=202)
async def receive_feishu_event(request: Request) -> JSONResponse:
    """Accept only the authenticated Feishu envelope and enqueue metadata.

    Canonical message fetch, artifact persistence, identity resolution, and
    interpretation happen in the worker after this transaction commits.
    """
    boundary = _feishu_intake_boundary
    if boundary is None:
        raise HTTPException(status_code=503, detail="Feishu intake is not configured")
    body = await request.body()
    try:
        accepted = boundary.accept(body, request.headers)
    except FeishuVerificationError as exc:
        raise HTTPException(status_code=401, detail="invalid Feishu callback") from exc
    except IntakeReceiptConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if isinstance(accepted, FeishuChallenge):
        return JSONResponse(status_code=200, content={"challenge": accepted.challenge})
    assert isinstance(accepted, FeishuAcceptance)
    return JSONResponse(
        status_code=202,
        content={
            "accepted": True,
            "created": accepted.created,
            "receipt_id": str(accepted.receipt.receipt_id),
            "outbox_event_id": str(accepted.outbox_event_id),
        },
    )


@app.get("/readyz")
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
        "storage": "sql-m3",
        "schema": "auto-create" if _settings.auto_create_schema else "managed-migration",
        "external_effects": "enabled" if _settings.external_effects_enabled else "disabled",
        "auth_mode": _settings.auth_mode,
        "authority_enforcement": (
            "enabled" if _settings.authority_enforcement_enabled else "disabled"
        ),
        "resource_authorization": "enabled",
        "world_runtime": (
            _settings.world_runtime_mode
            if _settings.runtime_profile in {"staging", "production"}
            else "not-required"
        ),
    }


@app.post("/v1/onboarding", response_model=OnboardingCaseResponse)
def create_onboarding(payload: CreateOnboardingCase, request: Request) -> OnboardingCaseResponse:
    actor = _authenticate(request)
    if payload.source_event_id is not None:
        existing = _existing_onboarding_response(
            payload.source_event_id,
            requester_principal_id=actor.principal_id,
        )
        if existing is not None:
            return existing

    policy = _current_onboarding_policy()
    administrative_request = AdministrativeRequest(
        requester_principal_id=actor.principal_id,
        channel=payload.channel,
        intent=f"onboard {payload.employee_ref}",
        source_ref=payload.source_event_id,
    )
    facts = OnboardingFacts(
        employee_ref=payload.employee_ref,
        department_ref=payload.department_ref,
        manager_principal_id=payload.manager_principal_id,
        start_date=payload.start_date,
        employment_type=payload.employment_type,
        requested_systems=payload.requested_systems,
        requires_privileged_access=payload.requires_privileged_access,
    )
    fact_snapshot = FactSnapshot(
        source=f"ingress:{payload.channel}",
        owner=actor.principal_id,
        authority=FactAuthority.CLAIM,
        source_ref=payload.source_event_id,
        facts=facts.model_dump(mode="json"),
    )
    original = create_case(
        administrative_request,
        case_kind="employee-onboarding",
        subject_ref=payload.employee_ref,
        fact_snapshot=fact_snapshot,
    )
    try:
        _uow.create_case(
            administrative_request,
            original,
            source_event_id=payload.source_event_id,
        )
    except DuplicateIngressEvent as exc:
        existing = _existing_onboarding_response(
            exc.receipt.source_event_id,
            requester_principal_id=actor.principal_id,
        )
        if existing is not None:
            return existing
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        if payload.source_event_id is not None:
            existing = _existing_onboarding_response(
                payload.source_event_id,
                requester_principal_id=actor.principal_id,
            )
            if existing is not None:
                return existing
        raise HTTPException(status_code=409, detail="duplicate ingress event") from exc

    ready = start_policy_evaluation(original)
    evaluation = policy.evaluate(facts)
    case = apply_policy_evaluation(ready, evaluation)
    try:
        _uow.apply_policy_transition(original, case, evaluation)
    except (ConcurrencyConflict, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return OnboardingCaseResponse(case=case, policy_evaluation=evaluation)


@app.get("/v1/cases/{case_id}", response_model=AdministrativeCase)
def get_case(case_id: UUID, request: Request) -> AdministrativeCase:
    actor = _authenticate(request)
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    _authorize(actor, AdministrativePermission.CASE_READ, case=case)
    return case


@app.get("/v1/cases/{case_id}/policy", response_model=PolicyEvaluation)
def get_policy_evaluation(case_id: UUID, request: Request) -> PolicyEvaluation:
    actor = _authenticate(request)
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    _authorize(actor, AdministrativePermission.CASE_READ, case=case)
    evaluation = _store.get_latest_policy_evaluation(case_id)
    if evaluation is None:
        raise HTTPException(status_code=404, detail="policy evaluation not found")
    return evaluation


@app.get("/v1/policies/{policy_id}", response_model=list[PolicyVersionRecord])
def get_policy_versions(policy_id: str, request: Request) -> list[PolicyVersionRecord]:
    actor = _authenticate(request)
    _authorize(actor, AdministrativePermission.POLICY_READ, organization_scope="*")
    return _policies.list_versions(policy_id)


@app.get("/v1/policies/{policy_id}/current", response_model=PolicyVersionRecord)
def get_current_policy(policy_id: str, request: Request) -> PolicyVersionRecord:
    actor = _authenticate(request)
    _authorize(actor, AdministrativePermission.POLICY_READ, organization_scope="*")
    try:
        return _policies.resolve_current(policy_id)
    except PolicyPlaneError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/v1/cases/{case_id}/facts", response_model=list[FactSnapshot])
def get_case_fact_history(case_id: UUID, request: Request) -> list[FactSnapshot]:
    actor = _authenticate(request)
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    _authorize(actor, AdministrativePermission.FACTS_READ, case=case)
    return list_fact_snapshots(_store, case_id)


@app.post("/v1/cases/{case_id}/facts", response_model=OnboardingCaseResponse)
def replace_onboarding_facts(
    case_id: UUID,
    payload: ReplaceOnboardingFacts,
    request: Request,
) -> OnboardingCaseResponse:
    actor = _authenticate(request)
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    _authorize(actor, AdministrativePermission.FACTS_ATTEST, case=case)
    if case.case_kind != "employee-onboarding":
        raise HTTPException(status_code=409, detail="facts endpoint supports onboarding cases only")
    if payload.employee_ref != case.subject_ref:
        raise HTTPException(status_code=409, detail="employee_ref cannot change case subject")

    policy = _current_onboarding_policy()
    facts = OnboardingFacts(
        employee_ref=payload.employee_ref,
        department_ref=payload.department_ref,
        manager_principal_id=payload.manager_principal_id,
        start_date=payload.start_date,
        employment_type=payload.employment_type,
        requested_systems=payload.requested_systems,
        requires_privileged_access=payload.requires_privileged_access,
    )
    snapshot = FactSnapshot(
        source=f"attestation:{actor.principal_id}",
        owner=actor.principal_id,
        authority=FactAuthority.ATTESTED,
        source_ref=payload.attestation_ref,
        facts=facts.model_dump(mode="json"),
    )
    changed = replace_facts_for_reevaluation(case, snapshot)
    ready = start_policy_evaluation(changed)
    evaluation = policy.evaluate(facts)
    updated = apply_policy_evaluation(ready, evaluation)
    try:
        _uow.replace_facts_and_apply_policy(case, updated, evaluation)
    except (TransitionError, ConcurrencyConflict, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return OnboardingCaseResponse(case=updated, policy_evaluation=evaluation)


@app.get("/v1/cases/{case_id}/decisions", response_model=list[Decision])
def get_case_decisions(case_id: UUID, request: Request) -> list[Decision]:
    actor = _authenticate(request)
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    _authorize(actor, AdministrativePermission.CASE_READ, case=case)
    return list_decisions(_store, case_id)


@app.get(
    "/v1/cases/{case_id}/authorizations",
    response_model=list[ExecutionAuthorization],
)
def get_case_authorizations(case_id: UUID, request: Request) -> list[ExecutionAuthorization]:
    actor = _authenticate(request)
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    _authorize(actor, AdministrativePermission.CASE_READ, case=case)
    return list_authorizations(_store, case_id)


@app.get("/v1/cases/{case_id}/effects", response_model=list[EffectRecord])
def get_case_effects(case_id: UUID, request: Request) -> list[EffectRecord]:
    actor = _authenticate(request)
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    _authorize(actor, AdministrativePermission.CASE_READ, case=case)
    return _execution.list_effects(case_id, case.authority_epoch)


@app.get(
    "/v1/cases/{case_id}/realizations",
    response_model=list[EffectRealizationAssessment],
)
def get_case_realizations(
    case_id: UUID,
    request: Request,
) -> list[EffectRealizationAssessment]:
    actor = _authenticate(request)
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    _authorize(actor, AdministrativePermission.CASE_READ, case=case)
    return list_realizations(_store, case_id)


@app.get("/v1/cases/{case_id}/outcomes", response_model=list[ConfirmedOutcome])
def get_case_outcomes(case_id: UUID, request: Request) -> list[ConfirmedOutcome]:
    actor = _authenticate(request)
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    _authorize(actor, AdministrativePermission.CASE_READ, case=case)
    return _execution.list_outcomes(case_id)


@app.get("/v1/cases/{case_id}/governance", response_model=GovernanceBasis | None)
def get_case_governance(case_id: UUID, request: Request) -> GovernanceBasis | None:
    actor = _authenticate(request)
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    _authorize(actor, AdministrativePermission.CASE_READ, case=case)
    return _governance.get_current_for_case(case.case_id, case.authority_epoch)


@app.get("/v1/cases/{case_id}/obligations", response_model=OnboardingObligationSet | None)
def get_case_obligations(case_id: UUID, request: Request) -> OnboardingObligationSet | None:
    actor = _authenticate(request)
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    _authorize(actor, AdministrativePermission.CASE_READ, case=case)
    return _obligations.get_current(case.case_id, case.authority_epoch)


@app.get("/v1/cases/{case_id}/completion", response_model=CompletionAssessment)
def get_case_completion(case_id: UUID, request: Request) -> CompletionAssessment:
    actor = _authenticate(request)
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    _authorize(actor, AdministrativePermission.CASE_READ, case=case)
    effects = _execution.list_effects(case.case_id, case.authority_epoch)
    outcomes = _execution.list_outcomes(case.case_id, case.authority_epoch)
    realizations = _execution.list_realizations(case.case_id, case.authority_epoch)
    obligation_set = _obligations.get_current(case.case_id, case.authority_epoch)
    if obligation_set is None:
        return assess_onboarding_completion(
            effects,
            outcomes,
            realizations=realizations,
        )
    return assess_administrative_completion(
        obligation_set,
        effects,
        outcomes,
        realizations=realizations,
        links=_obligations.list_links(case.case_id, case.authority_epoch),
        fulfillments=_obligations.list_domain_state_fulfillments(
            case.case_id, case.authority_epoch
        ),
    )


@app.get("/v1/cases/{case_id}/audit")
def get_case_audit(case_id: UUID, request: Request) -> list[dict[str, Any]]:
    actor = _authenticate(request)
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    _authorize(actor, AdministrativePermission.AUDIT_READ, case=case)
    return _store.list_audit_events(case_id)


@app.get("/v1/outbox/dead-letter", response_model=list[FailedOutboxEvent])
def get_dead_letter_outbox(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[FailedOutboxEvent]:
    actor = _authenticate(request)
    _authorize(actor, AdministrativePermission.DEAD_LETTER_READ, organization_scope="*")
    return list_failed_outbox(_store, limit=limit)


@app.post("/v1/cases/{case_id}/decisions", response_model=DecisionResponse)
def submit_decision(
    case_id: UUID,
    payload: RecordDecisionBody,
    request: Request,
) -> DecisionResponse:
    actor = _authenticate(request)
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    _authorize(actor, AdministrativePermission.DECISION_SUBMIT, case=case)
    if case.policy_ref is None:
        raise HTTPException(status_code=409, detail="case has no current policy")
    evaluation = _store.get_latest_policy_evaluation(case.case_id)
    if evaluation is None or evaluation.policy_ref != case.policy_ref:
        raise HTTPException(status_code=409, detail="case has no current policy evaluation")

    scope = _case_scope(case)
    try:
        role = resolve_decision_role(
            _authority,
            principal_id=actor.principal_id,
            evaluation=evaluation,
            organization_scope=scope,
            requested_role=payload.role,
        )
    except AuthorityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    decision = Decision(
        case_id=case.case_id,
        case_version=case.version,
        authority_epoch=case.authority_epoch,
        principal_id=actor.principal_id,
        decision_role=role,
        disposition=payload.disposition,
        rationale=payload.rationale,
        policy_ref=case.policy_ref,
    )

    approval: ApprovalAssessment | None = None
    approval_complete = False
    satisfaction = None
    if decision.disposition == DecisionDisposition.APPROVE:
        prior_decisions = list_decisions(_store, case.case_id)
        approval = assess_approval_satisfaction(
            _authority,
            case_id=case.case_id,
            authority_epoch=case.authority_epoch,
            policy_ref=case.policy_ref,
            evaluation=evaluation,
            decisions=[*prior_decisions, decision],
            organization_scope=scope,
        )
        approval_complete = approval.satisfied
        satisfaction = approval.satisfaction

    try:
        updated = record_decision(
            case,
            decision,
            approval_complete=approval_complete,
        )
        _uow.apply_decision_transition(
            case,
            updated,
            decision,
            organization_scope=scope,
            approval_satisfaction=satisfaction,
        )
    except (TransitionError, ConcurrencyConflict, ValueError, AuthorityError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return DecisionResponse(decision=decision, case=updated, approval=approval)


@app.post("/v1/cases/{case_id}/reopen", response_model=AdministrativeCase)
def reopen_case(case_id: UUID, request: Request) -> AdministrativeCase:
    actor = _authenticate(request)
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    _authorize(actor, AdministrativePermission.CASE_REASSESS, case=case)
    try:
        updated = explicit_reopen(case)
        _store.update_case(
            updated,
            expected_previous_version=case.version,
            event_type="case.reassessed",
        )
    except (TransitionError, ConcurrencyConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return updated
