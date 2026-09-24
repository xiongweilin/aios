from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request

from ..access_policy import AdministrativePermission
from ..authority import AuthorityError, IdentityBinding
from ..authority_lifecycle import AuthorityLifecycleEvent
from ..domain import AdministrativeCase, utcnow
from ..fact_acquisition import (
    FactAcquisitionError,
    build_hris_source,
    merge_authoritative_offboarding_facts,
    merge_authoritative_onboarding_facts,
)
from ..fact_transitions import replace_facts_for_reevaluation
from ..messaging import OutboxEventNotFailed, OutboxEventNotFound, replay_failed_outbox
from ..persistence import ConcurrencyConflict
from ..policy import OffboardingFacts, OnboardingFacts
from ..policy_plane import (
    PolicyPlaneError,
    compile_offboarding_policy,
    compile_onboarding_policy,
)
from ..service import TransitionError, apply_policy_evaluation, start_policy_evaluation
from .models import (
    BindIdentityBody,
    ExpireAuthorityBody,
    OutboxReplayResponse,
    ReasonBody,
    RefreshFactsResponse,
)
from .runtime import OperationsRuntime


def _apply_authoritative_refresh(
    runtime: OperationsRuntime,
    case: AdministrativeCase,
    record: object,
) -> AdministrativeCase:
    if case.case_kind == "employee-onboarding":
        snapshot = merge_authoritative_onboarding_facts(case, record)  # type: ignore[arg-type]
        policy_id = "employee-onboarding"
        facts_model = OnboardingFacts
        compile_policy = compile_onboarding_policy
    elif case.case_kind == "employee-offboarding":
        snapshot = merge_authoritative_offboarding_facts(case, record)  # type: ignore[arg-type]
        policy_id = "employee-offboarding"
        facts_model = OffboardingFacts
        compile_policy = compile_offboarding_policy
    else:
        raise FactAcquisitionError(
            f"authoritative refresh does not support case kind {case.case_kind!r}"
        )
    changed = replace_facts_for_reevaluation(case, snapshot)
    ready = start_policy_evaluation(changed)
    policy_record = runtime.policies.resolve_current(policy_id)
    facts = facts_model.model_validate(snapshot.facts)
    evaluation = compile_policy(policy_record).evaluate(facts)
    updated = apply_policy_evaluation(ready, evaluation)
    runtime.uow.replace_facts_and_apply_policy(case, updated, evaluation)
    return updated


def build_administration_router(runtime: OperationsRuntime) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/v1/operations/cases/{case_id}/authoritative-facts/refresh",
        response_model=RefreshFactsResponse,
    )
    def refresh_authoritative_facts(
        case_id: UUID, request: Request
    ) -> RefreshFactsResponse:
        actor = runtime.actor(request)
        case = runtime.store.get_case(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="case not found")
        runtime.require(
            actor,
            AdministrativePermission.FACTS_REFRESH_AUTHORITATIVE,
            case=case,
        )
        if case.case_kind not in {"employee-onboarding", "employee-offboarding"}:
            raise HTTPException(
                status_code=409,
                detail="authoritative refresh does not support this case kind",
            )
        source = build_hris_source(runtime.settings)
        if source is None:
            raise HTTPException(
                status_code=503,
                detail="authoritative HRIS source is not configured",
            )
        try:
            record = source.read_employee(case.subject_ref)
            if not record.is_fresh_at(
                utcnow(),
                max_age_seconds=runtime.settings.authoritative_fact_max_age_seconds,
            ):
                raise FactAcquisitionError("authoritative HRIS observation is stale")
            updated = _apply_authoritative_refresh(runtime, case, record)
        except (
            FactAcquisitionError,
            PolicyPlaneError,
            TransitionError,
            ConcurrencyConflict,
            ValueError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return RefreshFactsResponse(
            case=updated,
            source=record.source,
            source_ref=record.source_ref,
            source_version=record.source_version,
            source_digest=record.digest,
        )

    @router.post(
        "/v1/operations/outbox/dead-letter/{event_id}/replay",
        response_model=OutboxReplayResponse,
    )
    def replay_dead_letter(
        event_id: UUID,
        payload: ReasonBody,
        request: Request,
    ) -> OutboxReplayResponse:
        actor = runtime.actor(request)
        runtime.require(actor, AdministrativePermission.DEAD_LETTER_REPLAY)
        try:
            replayed = replay_failed_outbox(
                runtime.store,
                event_id,
                reason=payload.reason,
                actor_principal_id=actor.principal_id,
            )
        except OutboxEventNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except OutboxEventNotFailed as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return OutboxReplayResponse(
            event_id=replayed.event_id,
            status=replayed.status,
            attempts=replayed.attempts,
            audit_id=replayed.audit_id,
        )

    @router.post("/v1/operations/identities/bind", response_model=AuthorityLifecycleEvent)
    def bind_identity(
        payload: BindIdentityBody, request: Request
    ) -> AuthorityLifecycleEvent:
        actor = runtime.actor(request)
        runtime.require(actor, AdministrativePermission.IDENTITY_MANAGE)
        valid_from = payload.valid_from or utcnow()
        try:
            binding = IdentityBinding(
                provider=payload.provider.rstrip("/"),
                external_subject=payload.external_subject,
                principal_id=payload.principal_id,
                valid_from=valid_from,
                valid_until=payload.valid_until,
            )
            return runtime.lifecycle.bind_identity(
                binding,
                actor_principal_id=actor.principal_id,
                reason=payload.reason,
            )
        except (AuthorityError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post(
        "/v1/operations/identities/{binding_id}/revoke",
        response_model=AuthorityLifecycleEvent,
    )
    def revoke_identity(
        binding_id: UUID,
        payload: ReasonBody,
        request: Request,
    ) -> AuthorityLifecycleEvent:
        actor = runtime.actor(request)
        runtime.require(actor, AdministrativePermission.IDENTITY_MANAGE)
        try:
            return runtime.lifecycle.expire_identity_binding(
                binding_id,
                actor_principal_id=actor.principal_id,
                reason=payload.reason,
            )
        except AuthorityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post(
        "/v1/operations/principals/{principal_id}/deactivate",
        response_model=AuthorityLifecycleEvent,
    )
    def deactivate_principal(
        principal_id: str,
        payload: ReasonBody,
        request: Request,
    ) -> AuthorityLifecycleEvent:
        actor = runtime.actor(request)
        runtime.require(actor, AdministrativePermission.IDENTITY_MANAGE)
        try:
            return runtime.lifecycle.deactivate_principal(
                principal_id,
                actor_principal_id=actor.principal_id,
                reason=payload.reason,
            )
        except AuthorityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post(
        "/v1/operations/role-assignments/{assignment_id}/expire",
        response_model=AuthorityLifecycleEvent,
    )
    def expire_role_assignment(
        assignment_id: UUID,
        payload: ExpireAuthorityBody,
        request: Request,
    ) -> AuthorityLifecycleEvent:
        actor = runtime.actor(request)
        runtime.require(actor, AdministrativePermission.IDENTITY_MANAGE)
        try:
            return runtime.lifecycle.expire_role_assignment(
                assignment_id,
                actor_principal_id=actor.principal_id,
                reason=payload.reason,
                at=payload.at,
            )
        except (AuthorityError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post(
        "/v1/operations/delegations/{delegation_id}/expire",
        response_model=AuthorityLifecycleEvent,
    )
    def expire_delegation(
        delegation_id: UUID,
        payload: ExpireAuthorityBody,
        request: Request,
    ) -> AuthorityLifecycleEvent:
        actor = runtime.actor(request)
        runtime.require(actor, AdministrativePermission.IDENTITY_MANAGE)
        try:
            return runtime.lifecycle.expire_delegation(
                delegation_id,
                actor_principal_id=actor.principal_id,
                reason=payload.reason,
                at=payload.at,
            )
        except (AuthorityError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get(
        "/v1/operations/authority-events",
        response_model=list[AuthorityLifecycleEvent],
    )
    def authority_events(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    ) -> list[AuthorityLifecycleEvent]:
        actor = runtime.actor(request)
        runtime.require(actor, AdministrativePermission.OPERATIONS_READ)
        return runtime.lifecycle.list_events(limit=limit)

    return router


__all__ = ["build_administration_router"]
