from __future__ import annotations

from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from semantic_language import SemanticKind, SemanticRef

from .domains import DomainAssignment
from .runtime import WorldRuntime


class DomainAssignmentCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    responsibility_ref: str
    domain: str
    controller: str
    mandate_refs: list[str] = Field(default_factory=list)
    goal_refs: list[str] = Field(default_factory=list)
    constraint_refs: list[str] = Field(default_factory=list)
    authority_refs: list[str] = Field(default_factory=list)
    acceptance_refs: list[str] = Field(default_factory=list)
    evidence_requirements: list[dict[str, Any]] = Field(default_factory=list)
    resource_budget: dict[str, Any] = Field(default_factory=dict)
    review_conditions: list[dict[str, Any]] = Field(default_factory=list)


class SemanticRefCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    id: str
    namespace: str
    version: Literal["0.1"]

    @model_validator(mode="after")
    def _validate_namespace(self) -> "SemanticRefCommand":
        universal = {item.value for item in SemanticKind}
        if self.namespace == "universal" and self.kind not in universal:
            raise ValueError("domain-specific SemanticRef kind requires non-universal namespace")
        return self

    def to_semantic_ref(self) -> SemanticRef:
        try:
            kind: SemanticKind | str = SemanticKind(self.kind)
        except ValueError:
            kind = self.kind
        return SemanticRef(
            kind=kind,
            id=self.id,
            namespace=self.namespace,
            version=self.version,
        )


class DomainReportCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal[
        "accepted",
        "rejected",
        "progress",
        "evidence-submission",
        "outcome-candidate",
        "escalation",
        "completion-proposal",
    ]
    basis_refs: list[SemanticRefCommand] = Field(default_factory=list)
    evidence_refs: list[SemanticRefCommand] = Field(default_factory=list)
    outcome_refs: list[SemanticRefCommand] = Field(default_factory=list)
    detail: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_typed_refs(self) -> "DomainReportCommand":
        if any(ref.kind != SemanticKind.EVIDENCE.value for ref in self.evidence_refs):
            raise ValueError("evidence_refs must contain only Evidence refs")
        if any(ref.kind != SemanticKind.OUTCOME.value for ref in self.outcome_refs):
            raise ValueError("outcome_refs must contain only Outcome refs")
        if any(ref.namespace == "universal" for ref in self.outcome_refs):
            raise ValueError("domain outcome refs require an explicit domain namespace")
        return self


def _authenticate(runtime: WorldRuntime, request: Request):
    try:
        return runtime.identity.authenticate_bearer(
            request.headers.get("authorization"),
            delegation_id=request.headers.get("x-world-runtime-delegation"),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _assert_transition_authority(
    runtime: WorldRuntime,
    context,
    *,
    operation: str,
    resource: str | None = None,
) -> None:
    runtime.identity.assert_transition_authority(
        context,
        operation=operation,
        resource=resource,
    )


def _assert_assignment_reader(runtime: WorldRuntime, context, assignment: DomainAssignment) -> None:
    if context.authenticated_principal == assignment.controller:
        return
    responsibility = runtime.responsibility.get(assignment.responsibility_ref)
    runtime.identity.assert_claimed_principal(context, responsibility.principal)


def register_domain_protocol_routes(app: FastAPI, runtime: WorldRuntime) -> None:
    @app.post("/v1/domain-assignments")
    async def offer_domain_assignment(
        command: DomainAssignmentCommand,
        http_request: Request,
    ) -> dict[str, object]:
        context = _authenticate(runtime, http_request)
        try:
            responsibility = runtime.responsibility.get(command.responsibility_ref)
            runtime.identity.assert_claimed_principal(context, responsibility.principal)
            _assert_transition_authority(
                runtime,
                context,
                operation="offer-domain-assignment",
                resource=command.responsibility_ref,
            )
            item = runtime.domains.offer(
                DomainAssignment(
                    id=command.id,
                    responsibility_ref=command.responsibility_ref,
                    domain=command.domain,
                    controller=command.controller,
                    mandate_refs=tuple(command.mandate_refs),
                    goal_refs=tuple(command.goal_refs),
                    constraint_refs=tuple(command.constraint_refs),
                    authority_refs=tuple(command.authority_refs),
                    acceptance_refs=tuple(command.acceptance_refs),
                    evidence_requirements=tuple(command.evidence_requirements),
                    resource_budget=command.resource_budget,
                    review_conditions=tuple(command.review_conditions),
                )
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "id": item.id,
            "responsibility_ref": item.responsibility_ref,
            "domain": item.domain,
            "controller": item.controller,
            "status": item.status,
        }

    @app.get("/v1/domain-assignments/{assignment_id}")
    async def get_domain_assignment(
        assignment_id: str,
        http_request: Request,
    ) -> dict[str, object]:
        context = _authenticate(runtime, http_request)
        try:
            item = runtime.domains.get(assignment_id)
            _assert_assignment_reader(runtime, context, item)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="domain assignment not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {
            "id": item.id,
            "responsibility_ref": item.responsibility_ref,
            "domain": item.domain,
            "controller": item.controller,
            "mandate_refs": list(item.mandate_refs),
            "goal_refs": list(item.goal_refs),
            "constraint_refs": list(item.constraint_refs),
            "authority_refs": list(item.authority_refs),
            "acceptance_refs": list(item.acceptance_refs),
            "evidence_requirements": [dict(v) for v in item.evidence_requirements],
            "resource_budget": dict(item.resource_budget),
            "review_conditions": [dict(v) for v in item.review_conditions],
            "status": item.status,
        }

    @app.post("/v1/domain-assignments/{assignment_id}/reports")
    async def report_domain_assignment(
        assignment_id: str,
        command: DomainReportCommand,
        http_request: Request,
    ) -> dict[str, object]:
        context = _authenticate(runtime, http_request)
        try:
            assignment = runtime.domains.get(assignment_id)
            if context.authenticated_principal != assignment.controller:
                raise PermissionError(
                    "domain report actor must authenticate as the assigned controller"
                )
            report = runtime.domains.report(
                assignment_id,
                kind=command.kind,
                report_id=command.id,
                basis_refs=tuple(ref.to_semantic_ref() for ref in command.basis_refs),
                evidence_refs=tuple(ref.to_semantic_ref() for ref in command.evidence_refs),
                outcome_refs=tuple(ref.to_semantic_ref() for ref in command.outcome_refs),
                detail=command.detail,
            )
            assignment = runtime.domains.get(assignment_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="domain assignment not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "id": report.id,
            "assignment_id": report.assignment_id,
            "kind": report.kind,
            "basis_refs": [runtime.domains._ref_value(ref) for ref in report.basis_refs],
            "evidence_refs": [runtime.domains._ref_value(ref) for ref in report.evidence_refs],
            "outcome_refs": [runtime.domains._ref_value(ref) for ref in report.outcome_refs],
            "detail": dict(report.detail),
            "assignment_status": assignment.status,
        }

    @app.get("/v1/domain-assignments/{assignment_id}/reports")
    async def list_domain_reports(
        assignment_id: str,
        http_request: Request,
    ) -> dict[str, object]:
        context = _authenticate(runtime, http_request)
        try:
            assignment = runtime.domains.get(assignment_id)
            _assert_assignment_reader(runtime, context, assignment)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="domain assignment not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {
            "reports": [
                {
                    "id": item.id,
                    "assignment_id": item.assignment_id,
                    "kind": item.kind,
                    "basis_refs": [runtime.domains._ref_value(ref) for ref in item.basis_refs],
                    "evidence_refs": [runtime.domains._ref_value(ref) for ref in item.evidence_refs],
                    "outcome_refs": [runtime.domains._ref_value(ref) for ref in item.outcome_refs],
                    "detail": dict(item.detail),
                }
                for item in runtime.domains.reports(assignment_id)
            ]
        }


__all__ = [
    "DomainAssignmentCommand",
    "DomainReportCommand",
    "SemanticRefCommand",
    "register_domain_protocol_routes",
]
