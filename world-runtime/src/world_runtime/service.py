from __future__ import annotations

import importlib
import os
from datetime import datetime
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from semantic_language import Decision, Mandate, Responsibility, SemanticKind, SemanticRef

from .agency_protocol import register_agency_protocol_routes
from .conformance import conformance_vectors
from .contracts import contract_catalog
from .domain_protocol import register_domain_protocol_routes
from .execution import CapabilityRequest, CapabilityResult, EffectIdentityReboundError
from .identity import AuthenticatedRequestContext, DelegationGrant
from .runtime import WorldRuntime


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResponsibilityCommand(_ClosedModel):
    id: str
    principal: str
    subject: str
    domain: str
    scope: dict[str, Any] = Field(default_factory=dict)


class ResponsibilityAssessmentCommand(_ClosedModel):
    status: str
    basis_refs: list[str] = Field(default_factory=list)


class ResponsibilityDischargeCommand(_ClosedModel):
    decision_id: str


class ResponsibilityRelationCommand(_ClosedModel):
    id: str | None = None
    target_responsibility_id: str
    relation: Literal["requires", "contributes-to"]
    decision_id: str
    basis_refs: list[str] = Field(default_factory=list)


class ResponsibilityRelationRetireCommand(_ClosedModel):
    decision_id: str
    basis_refs: list[str] = Field(default_factory=list)


class WorkCommand(_ClosedModel):
    id: str | None = None
    responsibility_id: str
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)


class RunCommand(_ClosedModel):
    work_id: str
    workflow_id: str


class RunLeaseCommand(_ClosedModel):
    owner: str
    ttl_seconds: float = 30.0


class RunLeaseIdentityCommand(_ClosedModel):
    owner: str
    lease_generation: int
    ttl_seconds: float = 30.0


class DomainEffectPrepareCommand(_ClosedModel):
    request: CapabilityRequest
    provider_id: str
    provider_version: str


class DomainEffectResultCommand(_ClosedModel):
    dispatch_generation: int
    result: CapabilityResult


class DecisionCommand(_ClosedModel):
    id: str
    subject: str
    decided_by: str
    selected: dict[str, Any] = Field(default_factory=dict)
    basis_refs: list[str] = Field(default_factory=list)
    authority_refs: list[str] = Field(default_factory=list)


class MandateCommand(_ClosedModel):
    id: str
    principal: str
    scope: dict[str, Any] = Field(default_factory=dict)
    authority_ceiling: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None


class DelegationCommand(_ClosedModel):
    id: str
    grantor: str
    grantee: str
    scope: dict[str, Any] = Field(default_factory=dict)
    authority_ceiling: dict[str, Any] = Field(default_factory=dict)
    parent_id: str | None = None
    expires_at: datetime | None = None


class DelegationRevocationCommand(_ClosedModel):
    reason: str


class AuthorizationCommand(_ClosedModel):
    id: str | None = None
    principal: str
    action: str
    resource: str
    mandate_id: str
    decision_id: str
    conditions: dict[str, Any] = Field(default_factory=dict)
    annotations: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None


def _refs(values: list[str], kind: SemanticKind) -> tuple[SemanticRef, ...]:
    return tuple(SemanticRef(kind=kind, id=value) for value in values)


def _assert_root_context(
    runtime: WorldRuntime,
    context: AuthenticatedRequestContext,
) -> None:
    if runtime.root_principal is None:
        raise PermissionError(
            "whole-agency state access is disabled until root_principal is configured"
        )
    if (
        context.authenticated_principal != runtime.root_principal
        or context.effective_principal != runtime.root_principal
        or context.delegation_chain
    ):
        raise PermissionError("direct configured root principal authentication is required")


def _request_context(runtime: WorldRuntime, request: Request) -> AuthenticatedRequestContext:
    try:
        return runtime.identity.authenticate_bearer(
            request.headers.get("authorization"),
            delegation_id=request.headers.get("x-world-runtime-delegation"),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _assert_transition_authority(
    runtime: WorldRuntime,
    context: AuthenticatedRequestContext,
    *,
    operation: str,
    resource: str | None = None,
) -> None:
    runtime.identity.assert_transition_authority(
        context,
        operation=operation,
        resource=resource,
    )


def _assert_effect_authority(
    runtime: WorldRuntime,
    context: AuthenticatedRequestContext,
    *,
    action: str,
    resource: str,
) -> None:
    runtime.identity.assert_delegated_authority(
        context,
        scope={},
        authority_ceiling={"action": action, "resource": resource},
    )


def _assert_provider_attempt_reader(
    runtime: WorldRuntime,
    context: AuthenticatedRequestContext,
    attempt: dict[str, Any],
) -> None:
    identity = attempt.get("effect_identity")
    if not isinstance(identity, dict):
        _assert_root_context(runtime, context)
        return
    principal = str(identity.get("principal") or "")
    actor = str(identity.get("actor_ref") or "")
    if not principal:
        _assert_root_context(runtime, context)
        return
    if context.effective_principal != principal:
        raise PermissionError("provider attempt belongs to another principal")
    if context.delegation_chain and actor and context.authenticated_principal != actor:
        raise PermissionError("provider attempt belongs to another authenticated actor")


def _assert_provider_result_reader(
    runtime: WorldRuntime,
    context: AuthenticatedRequestContext,
    request_id: str,
) -> None:
    access = runtime.ledger.project_get("execution.provider-result-access", request_id)
    if access is None:
        _assert_root_context(runtime, context)
        return
    value = access[0]
    principal = str(value.get("principal") or "")
    actor = str(value.get("authenticated_actor") or "")
    if not principal:
        _assert_root_context(runtime, context)
        return
    if context.effective_principal != principal:
        raise PermissionError("provider result belongs to another principal")
    if context.delegation_chain and actor and context.authenticated_principal != actor:
        raise PermissionError("provider result belongs to another authenticated actor")


def create_app(runtime: WorldRuntime) -> FastAPI:
    app = FastAPI(title="World Runtime", version="1.1.0", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    async def healthz() -> dict[str, object]:
        return await runtime.health()

    @app.get("/v1/contracts")
    async def contracts() -> dict[str, Any]:
        return contract_catalog()

    @app.get("/v1/contracts/vectors")
    async def contract_vectors() -> dict[str, Any]:
        return conformance_vectors()

    @app.get("/v1/state/export")
    async def export_state(http_request: Request) -> dict[str, Any]:
        context = _request_context(runtime, http_request)
        try:
            _assert_root_context(runtime, context)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return runtime.state_bundle.export()

    @app.post("/v1/state/import")
    async def import_state(bundle: dict[str, Any], http_request: Request) -> dict[str, object]:
        context = _request_context(runtime, http_request)
        try:
            _assert_root_context(runtime, context)
            runtime.state_bundle.import_bundle(bundle)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "status": "imported",
            "events": len(bundle.get("events", [])),
            "projections": len(bundle.get("projections", [])),
        }

    @app.get("/v1/capabilities")
    async def capabilities(http_request: Request) -> dict[str, object]:
        _request_context(runtime, http_request)
        return {
            "runtime_id": runtime.runtime_id,
            "providers": [item.model_dump(mode="json") for item in runtime.registry.list()],
            "effect_rules": [
                {
                    "capability": rule.capability,
                    "impact_class": rule.impact_class,
                    "authorization_required": rule.authorization_required,
                    "resource_required": rule.resource_required,
                    "version_required": rule.version_required,
                }
                for rule in runtime.contract_registry.list_effect_rules()
            ],
        }

    @app.post("/v1/responsibilities")
    async def create_responsibility(
        command: ResponsibilityCommand,
        http_request: Request,
    ) -> dict[str, object]:
        context = _request_context(runtime, http_request)
        try:
            runtime.identity.assert_claimed_principal(context, command.principal)
            _assert_transition_authority(
                runtime,
                context,
                operation="create-responsibility",
            )
            current = runtime.responsibility.create(
                Responsibility(
                    id=command.id,
                    principal=command.principal,
                    subject=command.subject,
                    scope=command.scope,
                ),
                domain=command.domain,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"id": current.id, "status": current.status}

    @app.get("/v1/responsibilities/{responsibility_id}")
    async def get_responsibility(
        responsibility_id: str,
        http_request: Request,
    ) -> dict[str, object]:
        context = _request_context(runtime, http_request)
        try:
            item = runtime.responsibility.get(responsibility_id)
            runtime.identity.assert_claimed_principal(context, item.principal)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="responsibility not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {
            "id": item.id,
            "principal": item.principal,
            "subject": item.subject,
            "domain": item.domain,
            "scope": item.scope,
            "status": item.status,
        }

    @app.post("/v1/responsibilities/{responsibility_id}/assess")
    async def assess_responsibility(
        responsibility_id: str,
        command: ResponsibilityAssessmentCommand,
        http_request: Request,
    ) -> dict[str, object]:
        context = _request_context(runtime, http_request)
        try:
            runtime.identity.assert_claimed_principal(
                context,
                runtime.responsibility.get(responsibility_id).principal,
            )
            _assert_transition_authority(
                runtime,
                context,
                operation="assess-responsibility",
                resource=responsibility_id,
            )
            assessment_ref = runtime.responsibility.assess(
                responsibility_id,
                status=command.status,
                basis_refs=tuple(command.basis_refs),
            )
            item = runtime.responsibility.get(responsibility_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": item.id, "status": item.status, "assessment_ref": assessment_ref}

    @app.post("/v1/responsibilities/{responsibility_id}/discharge")
    async def discharge_responsibility(
        responsibility_id: str,
        command: ResponsibilityDischargeCommand,
        http_request: Request,
    ) -> dict[str, object]:
        context = _request_context(runtime, http_request)
        try:
            runtime.identity.assert_claimed_principal(
                context,
                runtime.responsibility.get(responsibility_id).principal,
            )
            _assert_transition_authority(
                runtime,
                context,
                operation="discharge-responsibility",
                resource=responsibility_id,
            )
            runtime.decisions.assert_attested(command.decision_id, context=context)
            transition_ref = runtime.responsibility.discharge(
                responsibility_id,
                decision_id=command.decision_id,
            )
            item = runtime.responsibility.get(responsibility_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": item.id, "status": item.status, "transition_ref": transition_ref}

    @app.post("/v1/responsibilities/{responsibility_id}/relations")
    async def create_responsibility_relation(
        responsibility_id: str,
        command: ResponsibilityRelationCommand,
        http_request: Request,
    ) -> dict[str, object]:
        context = _request_context(runtime, http_request)
        try:
            source = runtime.responsibility.get(responsibility_id)
            runtime.identity.assert_claimed_principal(context, source.principal)
            _assert_transition_authority(
                runtime,
                context,
                operation="relate-responsibility",
                resource=responsibility_id,
            )
            runtime.decisions.assert_attested(command.decision_id, context=context)
            relation = runtime.responsibility_graph.create(
                responsibility_id,
                command.target_responsibility_id,
                relation=command.relation,
                decision_id=command.decision_id,
                basis_refs=tuple(command.basis_refs),
                relation_id=command.id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="responsibility not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "id": relation.id,
            "source_responsibility_id": relation.source_responsibility_id,
            "target_responsibility_id": relation.target_responsibility_id,
            "relation": relation.relation,
            "status": relation.status,
        }

    @app.get("/v1/responsibilities/{responsibility_id}/relations")
    async def list_responsibility_relations(
        responsibility_id: str,
        http_request: Request,
    ) -> dict[str, object]:
        context = _request_context(runtime, http_request)
        try:
            source = runtime.responsibility.get(responsibility_id)
            runtime.identity.assert_claimed_principal(context, source.principal)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="responsibility not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {
            "relations": [
                {
                    "id": relation.id,
                    "source_responsibility_id": relation.source_responsibility_id,
                    "target_responsibility_id": relation.target_responsibility_id,
                    "relation": relation.relation,
                    "status": relation.status,
                }
                for relation in runtime.responsibility_graph.list_from(
                    responsibility_id,
                    active_only=False,
                )
            ]
        }

    @app.post("/v1/responsibility-relations/{relation_id}/retire")
    async def retire_responsibility_relation(
        relation_id: str,
        command: ResponsibilityRelationRetireCommand,
        http_request: Request,
    ) -> dict[str, object]:
        context = _request_context(runtime, http_request)
        try:
            current = runtime.responsibility_graph.get(relation_id)
            source = runtime.responsibility.get(current.source_responsibility_id)
            runtime.identity.assert_claimed_principal(context, source.principal)
            _assert_transition_authority(
                runtime,
                context,
                operation="retire-responsibility-relation",
                resource=current.source_responsibility_id,
            )
            runtime.decisions.assert_attested(command.decision_id, context=context)
            relation = runtime.responsibility_graph.retire(
                relation_id,
                decision_id=command.decision_id,
                basis_refs=tuple(command.basis_refs),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="responsibility relation not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"id": relation.id, "status": relation.status}

    @app.post("/v1/work")
    async def create_work(command: WorkCommand, http_request: Request) -> dict[str, object]:
        context = _request_context(runtime, http_request)
        try:
            runtime.identity.assert_claimed_principal(
                context,
                runtime.responsibility.get(command.responsibility_id).principal,
            )
            _assert_transition_authority(
                runtime,
                context,
                operation="admit-work",
                resource=command.responsibility_id,
            )
        except (KeyError, PermissionError) as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        work = runtime.get_work(command.id) if command.id else None
        if work is None and command.id is None:
            work = next(
                (
                    item
                    for item in runtime.list_work()
                    if item.responsibility_id == command.responsibility_id
                    and item.kind == command.kind
                    and dict(item.payload) == command.payload
                ),
                None,
            )
        if work is None:
            try:
                work = runtime.execution.admit_work(
                    responsibility_id=command.responsibility_id,
                    kind=command.kind,
                    payload=command.payload,
                    work_id=command.id,
                )
            except (KeyError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        elif command.id is not None and (
            work.responsibility_id != command.responsibility_id
            or work.kind != command.kind
            or dict(work.payload) != command.payload
        ):
            raise HTTPException(status_code=409, detail="work identity rebound")
        return {"id": work.id, "status": work.status}

    @app.post("/v1/runs")
    async def create_run(command: RunCommand, http_request: Request) -> dict[str, object]:
        context = _request_context(runtime, http_request)
        work_item = runtime.get_work(command.work_id)
        if work_item is None:
            raise HTTPException(status_code=404, detail="work not found")
        try:
            runtime.identity.assert_claimed_principal(
                context,
                runtime.responsibility.get(work_item.responsibility_id).principal,
            )
            _assert_transition_authority(
                runtime,
                context,
                operation="start-run",
                resource=command.work_id,
            )
        except (KeyError, PermissionError) as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        runs = runtime.list_runs(command.work_id)
        run = next((item for item in runs if item.workflow_id == command.workflow_id), None)
        if run is None:
            try:
                run = runtime.start_run(command.work_id, workflow_id=command.workflow_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="work not found") from exc
            except PermissionError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"id": run.id, "status": run.status}

    @app.post("/v1/runs/{run_id}/lease")
    async def acquire_run_lease(
        run_id: str,
        command: RunLeaseCommand,
        http_request: Request,
    ) -> dict[str, object]:
        context = _request_context(runtime, http_request)
        if command.owner != context.effective_principal:
            raise HTTPException(status_code=403, detail="lease owner must be authenticated principal")
        try:
            _assert_transition_authority(
                runtime,
                context,
                operation="acquire-run-lease",
                resource=run_id,
            )
            run = runtime.execution.acquire_run_lease(
                run_id,
                owner=command.owner,
                ttl_seconds=command.ttl_seconds,
            )
        except (KeyError, PermissionError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "run_id": run.id,
            "lease_owner": run.lease_owner,
            "lease_generation": run.lease_generation,
            "lease_expires_at": (
                run.lease_expires_at.isoformat() if run.lease_expires_at else None
            ),
        }

    @app.post("/v1/runs/{run_id}/lease/heartbeat")
    async def heartbeat_run_lease(
        run_id: str,
        command: RunLeaseIdentityCommand,
        http_request: Request,
    ) -> dict[str, object]:
        context = _request_context(runtime, http_request)
        if command.owner != context.effective_principal:
            raise HTTPException(status_code=403, detail="lease owner must be authenticated principal")
        try:
            _assert_transition_authority(
                runtime,
                context,
                operation="heartbeat-run-lease",
                resource=run_id,
            )
            run = runtime.execution.heartbeat_run_lease(
                run_id,
                owner=command.owner,
                lease_generation=command.lease_generation,
                ttl_seconds=command.ttl_seconds,
            )
        except (KeyError, PermissionError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "run_id": run.id,
            "lease_owner": run.lease_owner,
            "lease_generation": run.lease_generation,
            "lease_expires_at": (
                run.lease_expires_at.isoformat() if run.lease_expires_at else None
            ),
        }

    @app.post("/v1/runs/{run_id}/lease/release")
    async def release_run_lease(
        run_id: str,
        command: RunLeaseIdentityCommand,
        http_request: Request,
    ) -> dict[str, object]:
        context = _request_context(runtime, http_request)
        if command.owner != context.effective_principal:
            raise HTTPException(status_code=403, detail="lease owner must be authenticated principal")
        try:
            _assert_transition_authority(
                runtime,
                context,
                operation="release-run-lease",
                resource=run_id,
            )
            run = runtime.execution.release_run_lease(
                run_id,
                owner=command.owner,
                lease_generation=command.lease_generation,
            )
        except (KeyError, PermissionError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "run_id": run.id,
            "lease_owner": run.lease_owner,
            "lease_generation": run.lease_generation,
        }

    @app.post("/v1/decisions")
    async def record_decision(
        command: DecisionCommand,
        http_request: Request,
    ) -> dict[str, object]:
        context = _request_context(runtime, http_request)
        if not command.basis_refs:
            raise HTTPException(status_code=400, detail="decision requires basis refs")
        try:
            transition_operation = str(command.selected.get("operation") or "record-decision")
            transition_resource = str(command.selected.get("target_ref") or command.subject)
            _assert_transition_authority(
                runtime,
                context,
                operation=transition_operation,
                resource=transition_resource,
            )
            runtime.decisions.record_attested(
                Decision(
                    id=command.id,
                    subject=command.subject,
                    decided_by=command.decided_by,
                    selected=command.selected,
                    basis_refs=_refs(command.basis_refs, SemanticKind.EVIDENCE),
                    authority_refs=_refs(command.authority_refs, SemanticKind.AUTHORIZATION),
                ),
                context=context,
            )
            current = runtime.decisions.get(command.id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return dict(current)

    @app.post("/v1/mandates")
    async def register_mandate(
        command: MandateCommand,
        http_request: Request,
    ) -> dict[str, object]:
        context = _request_context(runtime, http_request)
        try:
            _assert_transition_authority(
                runtime,
                context,
                operation="register-mandate",
            )
            runtime.identity.assert_delegated_authority(
                context,
                scope=command.scope,
                authority_ceiling=command.authority_ceiling,
            )
            runtime.governance.register_mandate_attested(
                Mandate(
                    id=command.id,
                    principal=command.principal,
                    scope=command.scope,
                    authority_ceiling=command.authority_ceiling,
                    expires_at=command.expires_at,
                ),
                context=context,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        current = runtime.ledger.project_get("governance.mandate", command.id)
        assert current is not None
        return {"id": command.id, "status": str(current[0]["status"])}

    @app.post("/v1/delegations")
    async def grant_delegation(command: DelegationCommand, request: Request) -> dict[str, object]:
        context = _request_context(runtime, request)
        try:
            runtime.identity.grant_delegation(
                DelegationGrant(
                    id=command.id,
                    grantor=command.grantor,
                    grantee=command.grantee,
                    scope=command.scope,
                    authority_ceiling=command.authority_ceiling,
                    parent_id=command.parent_id,
                    expires_at=command.expires_at,
                ),
                context=context,
            )
        except (KeyError, PermissionError, ValueError) as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {"id": command.id, "status": "active"}

    @app.post("/v1/delegations/{delegation_id}/revoke")
    async def revoke_delegation(
        delegation_id: str,
        command: DelegationRevocationCommand,
        request: Request,
    ) -> dict[str, object]:
        context = _request_context(runtime, request)
        try:
            runtime.identity.revoke_delegation(
                delegation_id,
                context=context,
                reason=command.reason,
            )
        except (KeyError, PermissionError, ValueError) as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {"id": delegation_id, "status": "revoked"}

    @app.post("/v1/authorizations")
    async def issue_authorization(
        command: AuthorizationCommand,
        http_request: Request,
    ) -> dict[str, object]:
        context = _request_context(runtime, http_request)
        try:
            _assert_transition_authority(
                runtime,
                context,
                operation="issue-authorization",
                resource=command.resource,
            )
            _assert_effect_authority(
                runtime,
                context,
                action=command.action,
                resource=command.resource,
            )
            auth = runtime.governance.issue_authorization_attested(
                context=context,
                principal=command.principal,
                action=command.action,
                resource=command.resource,
                mandate_id=command.mandate_id,
                decision_id=command.decision_id,
                conditions=command.conditions,
                annotations=command.annotations,
                expires_at=command.expires_at,
                authorization_id=command.id,
            )
        except (KeyError, PermissionError, ValueError) as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {"id": auth.id}

    @app.post("/v1/domain-effects/prepare")
    async def prepare_domain_effect(
        command: DomainEffectPrepareCommand,
        http_request: Request,
    ) -> dict[str, object]:
        context = _request_context(runtime, http_request)
        request = command.request
        try:
            _assert_transition_authority(
                runtime,
                context,
                operation="prepare-domain-effect",
                resource=request.resource or request.resource_ref,
            )
            _assert_effect_authority(
                runtime,
                context,
                action=request.capability,
                resource=request.resource or request.resource_ref or "",
            )
            if request.principal is not None:
                runtime.identity.assert_claimed_principal(context, request.principal)
            if request.actor_ref is not None and request.actor_ref != context.authenticated_principal:
                raise PermissionError("domain effect actor_ref must match authenticated principal")
            effective_request = request.model_copy(
                update={
                    "principal": context.effective_principal,
                    "actor_ref": context.authenticated_principal,
                }
            )
            return runtime.effect_boundary.prepare(
                effective_request,
                provider_id=command.provider_id,
                provider_version=command.provider_version,
                context=context,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except EffectIdentityReboundError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/domain-effects/{idempotency_key}/start")
    async def start_domain_effect(
        idempotency_key: str,
        http_request: Request,
    ) -> dict[str, object]:
        context = _request_context(runtime, http_request)
        try:
            _assert_transition_authority(
                runtime,
                context,
                operation="dispatch-domain-effect",
            )
            return runtime.effect_boundary.start(idempotency_key, context=context)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="domain effect not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v1/domain-effects/{idempotency_key}/result")
    async def record_domain_effect_result(
        idempotency_key: str,
        command: DomainEffectResultCommand,
        http_request: Request,
    ) -> dict[str, object]:
        context = _request_context(runtime, http_request)
        try:
            _assert_transition_authority(
                runtime,
                context,
                operation="record-domain-effect-result",
            )
            result = runtime.effect_boundary.record_result(
                idempotency_key,
                command.result,
                dispatch_generation=command.dispatch_generation,
                context=context,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="domain effect not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except EffectIdentityReboundError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result.model_dump(mode="json")

    @app.get("/v1/domain-effects/{idempotency_key}")
    async def get_domain_effect(
        idempotency_key: str,
        http_request: Request,
    ) -> dict[str, object]:
        context = _request_context(runtime, http_request)
        try:
            value = runtime.effect_boundary.get(idempotency_key)
            attempt = runtime.ledger.project_get(
                "execution.domain-effect-attempt",
                idempotency_key,
            )
            assert attempt is not None
            runtime.effect_boundary._assert_actor(attempt[0], context)
            return value
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="domain effect not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/v1/invoke")
    async def invoke(
        request: CapabilityRequest,
        http_request: Request,
    ) -> dict[str, object]:
        context = _request_context(runtime, http_request)
        try:
            _assert_transition_authority(
                runtime,
                context,
                operation="invoke-capability",
                resource=request.resource or request.resource_ref,
            )
            if request.effect_class not in {"read", "read-only"} or request.authorization_id:
                _assert_effect_authority(
                    runtime,
                    context,
                    action=request.capability,
                    resource=request.resource or request.resource_ref or "",
                )
            if request.principal is not None:
                runtime.identity.assert_claimed_principal(context, request.principal)
            if request.authorization_id is not None:
                authorization = runtime.ledger.project_get(
                    "governance.authorization",
                    request.authorization_id,
                )
                if authorization is None:
                    raise PermissionError("unknown authorization")
                attestation = authorization[0].get("issuer_attestation")
                if not isinstance(attestation, dict):
                    raise PermissionError(
                        "Authorization is not authenticated under Runtime Protocol 2.0"
                    )
            effective_request = request.model_copy(
                update={
                    "principal": context.effective_principal,
                    "actor_ref": context.authenticated_principal,
                }
            )
            result = await runtime.invoke(effective_request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except EffectIdentityReboundError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result.model_dump(mode="json")

    @app.post("/v1/reconcile/{idempotency_key}")
    async def reconcile(idempotency_key: str, http_request: Request) -> dict[str, object]:
        context = _request_context(runtime, http_request)
        try:
            _assert_transition_authority(
                runtime,
                context,
                operation="reconcile-effect",
            )
            attempt = runtime.ledger.project_get("execution.provider-attempt", idempotency_key)
            if attempt is None:
                raise KeyError(idempotency_key)
            _assert_provider_attempt_reader(runtime, context, dict(attempt[0]))
            result = await runtime.recovery.recover(idempotency_key)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="provider attempt not found") from exc
        return result.model_dump(mode="json")

    @app.get("/v1/results/{request_id}")
    async def result(request_id: str, http_request: Request) -> dict[str, object]:
        context = _request_context(runtime, http_request)
        row = runtime.ledger.project_get("execution.provider-result", request_id)
        if row is None:
            raise HTTPException(status_code=404, detail="result not found")
        try:
            _assert_provider_result_reader(runtime, context, request_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return row[0]

    register_agency_protocol_routes(app, runtime)
    register_domain_protocol_routes(app, runtime)
    return app


def create_configured_app() -> FastAPI:
    factory_ref = os.getenv("WORLD_RUNTIME_FACTORY", "").strip()
    if not factory_ref or ":" not in factory_ref:
        raise RuntimeError("WORLD_RUNTIME_FACTORY must be module:function")
    module_name, function_name = factory_ref.split(":", 1)
    module = importlib.import_module(module_name)
    factory = getattr(module, function_name)
    if not callable(factory):
        raise RuntimeError("WORLD_RUNTIME_FACTORY target is not callable")
    runtime = factory()
    if not isinstance(runtime, WorldRuntime):
        raise RuntimeError("WORLD_RUNTIME_FACTORY must return WorldRuntime")
    return create_app(runtime)
