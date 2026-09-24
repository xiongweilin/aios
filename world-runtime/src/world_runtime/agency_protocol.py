from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from .identity import AuthenticatedRequestContext
from .runtime import WorldRuntime
from .strategic_portfolio import ResourceBudgetLine


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StrategicIssueCommand(_ClosedModel):
    id: str
    subject: str
    question: str
    mandate_id: str
    basis_refs: list[str] = Field(default_factory=list)


class StrategicOptionCommand(_ClosedModel):
    id: str | None = None
    hypothesis: dict[str, Any] = Field(default_factory=dict)
    evaluation: dict[str, Any] = Field(default_factory=dict)
    basis_refs: list[str] = Field(default_factory=list)


class ResourceBudgetLineCommand(_ClosedModel):
    amount: float
    unit: str


class PortfolioProposalCommand(_ClosedModel):
    id: str | None = None
    option_ids: list[str] = Field(default_factory=list)
    goal_refs: list[str] = Field(default_factory=list)
    resource_budget: dict[str, ResourceBudgetLineCommand] = Field(default_factory=dict)
    basis_refs: list[str] = Field(default_factory=list)


class PortfolioActivateCommand(_ClosedModel):
    id: str | None = None
    decision_id: str


class ResourceAllocationCommand(_ClosedModel):
    id: str | None = None
    responsibility_id: str
    resource_type: str
    amount: float
    unit: str
    decision_id: str
    basis_refs: list[str] = Field(default_factory=list)


class PortfolioRetireCommand(_ClosedModel):
    decision_id: str
    basis_refs: list[str] = Field(default_factory=list)


class StrategicIssueCloseCommand(_ClosedModel):
    decision_id: str
    basis_refs: list[str] = Field(default_factory=list)


class QualificationDependencyCommand(_ClosedModel):
    id: str | None = None
    principal: str
    subject_ref: str
    dependency_ref: str
    dependency_version: str
    assumption: str
    scope: dict[str, Any] = Field(default_factory=dict)
    review_policy: dict[str, Any] = Field(default_factory=dict)
    basis_refs: list[str] = Field(default_factory=list)
    supersedes_dependency_id: str | None = None


class QualificationChangeCommand(_ClosedModel):
    dependency_ref: str
    observed_version: str
    basis_refs: list[str] = Field(default_factory=list)
    reason: str = ""


class QualificationAssessmentCommand(_ClosedModel):
    id: str | None = None
    disposition: str
    basis_refs: list[str] = Field(default_factory=list)
    rationale: str = ""


class QualificationResolutionCommand(_ClosedModel):
    resolution_ref: str
    basis_refs: list[str] = Field(default_factory=list)


class QualificationAdvanceCommand(_ClosedModel):
    obligation_id: str
    assessment_id: str
    new_version: str
    basis_refs: list[str] = Field(default_factory=list)
    successor_id: str | None = None


def _authenticate(runtime: WorldRuntime, request: Request) -> AuthenticatedRequestContext:
    try:
        return runtime.identity.authenticate_bearer(
            request.headers.get("authorization"),
            delegation_id=request.headers.get("x-world-runtime-delegation"),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _assert_strategic_principal(
    runtime: WorldRuntime,
    context: AuthenticatedRequestContext,
    *,
    issue_id: str,
) -> None:
    issue = runtime.portfolio.get_issue(issue_id)
    runtime.identity.assert_claimed_principal(context, issue.principal)


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


def _portfolio_value(portfolio) -> dict[str, object]:
    return {
        "id": portfolio.id,
        "proposal_id": portfolio.proposal_id,
        "issue_id": portfolio.issue_id,
        "decision_id": portfolio.decision_id,
        "option_ids": list(portfolio.option_ids),
        "goal_refs": list(portfolio.goal_refs),
        "resource_budget": {
            key: {"amount": line.amount, "unit": line.unit}
            for key, line in portfolio.resource_budget.items()
        },
        "status": portfolio.status,
    }


def _review_value(item) -> dict[str, object]:
    return {
        "id": item.id,
        "principal": item.principal,
        "dependency_id": item.dependency_id,
        "subject_ref": item.subject_ref,
        "dependency_ref": item.dependency_ref,
        "previous_version": item.previous_version,
        "observed_version": item.observed_version,
        "reason": item.reason,
        "required_action": item.required_action,
        "basis_refs": list(item.basis_refs),
        "status": item.status,
        "assessment_id": item.assessment_id,
        "disposition": item.disposition,
        "resolution_ref": item.resolution_ref,
    }


def register_agency_protocol_routes(app: FastAPI, runtime: WorldRuntime) -> None:
    @app.post("/v1/strategy/issues")
    async def open_strategic_issue(
        command: StrategicIssueCommand,
        request: Request,
    ) -> dict[str, object]:
        context = _authenticate(runtime, request)
        try:
            mandate = runtime.ledger.project_get("governance.mandate", command.mandate_id)
            if mandate is None:
                raise KeyError(command.mandate_id)
            runtime.identity.assert_claimed_principal(
                context,
                str(mandate[0]["principal"]),
            )
            _assert_transition_authority(
                runtime,
                context,
                operation="open-strategic-issue",
                resource=command.subject,
            )
            item = runtime.portfolio.open_issue(
                issue_id=command.id,
                subject=command.subject,
                question=command.question,
                mandate_id=command.mandate_id,
                basis_refs=tuple(command.basis_refs),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="mandate not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "id": item.id,
            "principal": item.principal,
            "subject": item.subject,
            "question": item.question,
            "mandate_id": item.mandate_id,
            "basis_refs": list(item.basis_refs),
            "status": item.status,
        }

    @app.get("/v1/strategy/issues/{issue_id}")
    async def get_strategic_issue(issue_id: str, request: Request) -> dict[str, object]:
        context = _authenticate(runtime, request)
        try:
            item = runtime.portfolio.get_issue(issue_id)
            runtime.identity.assert_claimed_principal(context, item.principal)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="strategic issue not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {
            "id": item.id,
            "principal": item.principal,
            "subject": item.subject,
            "question": item.question,
            "mandate_id": item.mandate_id,
            "basis_refs": list(item.basis_refs),
            "status": item.status,
        }

    @app.post("/v1/strategy/issues/{issue_id}/options")
    async def record_strategic_option(
        issue_id: str,
        command: StrategicOptionCommand,
        request: Request,
    ) -> dict[str, object]:
        context = _authenticate(runtime, request)
        try:
            _assert_strategic_principal(runtime, context, issue_id=issue_id)
            _assert_transition_authority(
                runtime,
                context,
                operation="record-strategic-option",
                resource=issue_id,
            )
            item = runtime.portfolio.record_option(
                issue_id,
                option_id=command.id,
                hypothesis=command.hypothesis,
                evaluation=command.evaluation,
                basis_refs=tuple(command.basis_refs),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="strategic issue not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "id": item.id,
            "subject": item.subject,
            "hypothesis": dict(item.hypothesis),
            "evaluation": dict(item.evaluation),
            "basis_refs": list(item.basis_refs),
        }

    @app.post("/v1/strategy/issues/{issue_id}/portfolio-proposals")
    async def propose_strategic_portfolio(
        issue_id: str,
        command: PortfolioProposalCommand,
        request: Request,
    ) -> dict[str, object]:
        context = _authenticate(runtime, request)
        try:
            _assert_strategic_principal(runtime, context, issue_id=issue_id)
            _assert_transition_authority(
                runtime,
                context,
                operation="propose-strategic-portfolio",
                resource=issue_id,
            )
            item = runtime.portfolio.propose_portfolio(
                issue_id,
                proposal_id=command.id,
                option_ids=tuple(command.option_ids),
                goal_refs=tuple(command.goal_refs),
                resource_budget={
                    key: ResourceBudgetLine(value.amount, value.unit)
                    for key, value in command.resource_budget.items()
                },
                basis_refs=tuple(command.basis_refs),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "id": item.id,
            "issue_id": item.issue_id,
            "option_ids": list(item.option_ids),
            "goal_refs": list(item.goal_refs),
            "resource_budget": {
                key: {"amount": line.amount, "unit": line.unit}
                for key, line in item.resource_budget.items()
            },
            "basis_refs": list(item.basis_refs),
        }

    @app.post("/v1/strategy/portfolio-proposals/{proposal_id}/activate")
    async def activate_strategic_portfolio(
        proposal_id: str,
        command: PortfolioActivateCommand,
        request: Request,
    ) -> dict[str, object]:
        context = _authenticate(runtime, request)
        try:
            proposal = runtime.portfolio.get_proposal(proposal_id)
            _assert_strategic_principal(runtime, context, issue_id=proposal.issue_id)
            _assert_transition_authority(
                runtime,
                context,
                operation="activate-portfolio",
                resource=proposal_id,
            )
            runtime.decisions.assert_attested(command.decision_id, context=context)
            item = runtime.portfolio.activate_portfolio(
                proposal_id,
                decision_id=command.decision_id,
                portfolio_id=command.id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _portfolio_value(item)

    @app.get("/v1/strategy/portfolios/{portfolio_id}")
    async def get_strategic_portfolio(
        portfolio_id: str,
        request: Request,
    ) -> dict[str, object]:
        context = _authenticate(runtime, request)
        try:
            item = runtime.portfolio.get_portfolio(portfolio_id)
            _assert_strategic_principal(runtime, context, issue_id=item.issue_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="strategic portfolio not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return _portfolio_value(item)

    @app.post("/v1/strategy/portfolios/{portfolio_id}/allocations")
    async def allocate_strategic_resource(
        portfolio_id: str,
        command: ResourceAllocationCommand,
        request: Request,
    ) -> dict[str, object]:
        context = _authenticate(runtime, request)
        try:
            portfolio = runtime.portfolio.get_portfolio(portfolio_id)
            _assert_strategic_principal(runtime, context, issue_id=portfolio.issue_id)
            _assert_transition_authority(
                runtime,
                context,
                operation="allocate-resource",
                resource=portfolio_id,
            )
            runtime.decisions.assert_attested(command.decision_id, context=context)
            item = runtime.portfolio.allocate(
                portfolio_id,
                command.responsibility_id,
                allocation_id=command.id,
                resource_type=command.resource_type,
                amount=command.amount,
                unit=command.unit,
                decision_id=command.decision_id,
                basis_refs=tuple(command.basis_refs),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "id": item.id,
            "portfolio_id": item.portfolio_id,
            "responsibility_id": item.responsibility_id,
            "resource_type": item.resource_type,
            "amount": item.amount,
            "unit": item.unit,
            "decision_id": item.decision_id,
            "basis_refs": list(item.basis_refs),
            "status": item.status,
        }

    @app.post("/v1/strategy/portfolios/{portfolio_id}/retire")
    async def retire_strategic_portfolio(
        portfolio_id: str,
        command: PortfolioRetireCommand,
        request: Request,
    ) -> dict[str, object]:
        context = _authenticate(runtime, request)
        try:
            portfolio = runtime.portfolio.get_portfolio(portfolio_id)
            _assert_strategic_principal(runtime, context, issue_id=portfolio.issue_id)
            _assert_transition_authority(
                runtime,
                context,
                operation="retire-portfolio",
                resource=portfolio_id,
            )
            runtime.decisions.assert_attested(command.decision_id, context=context)
            item = runtime.portfolio.retire_portfolio(
                portfolio_id,
                decision_id=command.decision_id,
                basis_refs=tuple(command.basis_refs),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _portfolio_value(item)

    @app.post("/v1/strategy/issues/{issue_id}/close")
    async def close_strategic_issue(
        issue_id: str,
        command: StrategicIssueCloseCommand,
        request: Request,
    ) -> dict[str, object]:
        context = _authenticate(runtime, request)
        try:
            _assert_strategic_principal(runtime, context, issue_id=issue_id)
            _assert_transition_authority(
                runtime,
                context,
                operation="close-strategic-issue",
                resource=issue_id,
            )
            runtime.decisions.assert_attested(command.decision_id, context=context)
            item = runtime.portfolio.close_issue(
                issue_id,
                decision_id=command.decision_id,
                basis_refs=tuple(command.basis_refs),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "id": item.id,
            "principal": item.principal,
            "status": item.status,
        }

    @app.post("/v1/qualification/dependencies")
    async def register_qualification_dependency(
        command: QualificationDependencyCommand,
        request: Request,
    ) -> dict[str, object]:
        context = _authenticate(runtime, request)
        try:
            runtime.identity.assert_claimed_principal(context, command.principal)
            _assert_transition_authority(
                runtime,
                context,
                operation="register-qualification-dependency",
                resource=command.subject_ref,
            )
            item = runtime.qualification.register_dependency(
                dependency_id=command.id,
                principal=command.principal,
                subject_ref=command.subject_ref,
                dependency_ref=command.dependency_ref,
                dependency_version=command.dependency_version,
                assumption=command.assumption,
                scope=command.scope,
                review_policy=command.review_policy,
                basis_refs=tuple(command.basis_refs),
                supersedes_dependency_id=command.supersedes_dependency_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "id": item.id,
            "principal": item.principal,
            "subject_ref": item.subject_ref,
            "dependency_ref": item.dependency_ref,
            "dependency_version": item.dependency_version,
            "assumption": item.assumption,
            "scope": dict(item.scope),
            "review_policy": dict(item.review_policy),
            "basis_refs": list(item.basis_refs),
            "status": item.status,
            "supersedes_dependency_id": item.supersedes_dependency_id,
        }

    @app.post("/v1/qualification/changes")
    async def observe_qualification_change(
        command: QualificationChangeCommand,
        request: Request,
    ) -> dict[str, object]:
        context = _authenticate(runtime, request)
        try:
            _assert_transition_authority(
                runtime,
                context,
                operation="observe-qualification-change",
                resource=command.dependency_ref,
            )
            items = runtime.qualification.observe_dependency_change(
                principal=context.effective_principal,
                dependency_ref=command.dependency_ref,
                observed_version=command.observed_version,
                basis_refs=tuple(command.basis_refs),
                reason=command.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"reviews": [_review_value(item) for item in items]}

    @app.get("/v1/qualification/reviews")
    async def list_qualification_reviews(
        request: Request,
        subject_ref: str | None = Query(default=None),
    ) -> dict[str, object]:
        context = _authenticate(runtime, request)
        return {
            "reviews": [
                _review_value(item)
                for item in runtime.qualification.pending_obligations(
                    principal=context.effective_principal,
                    subject_ref=subject_ref,
                )
            ]
        }

    @app.post("/v1/qualification/reviews/{obligation_id}/assess")
    async def assess_qualification_review(
        obligation_id: str,
        command: QualificationAssessmentCommand,
        request: Request,
    ) -> dict[str, object]:
        context = _authenticate(runtime, request)
        try:
            obligation = runtime.qualification.get_obligation(obligation_id)
            runtime.identity.assert_claimed_principal(context, obligation.principal)
            _assert_transition_authority(
                runtime,
                context,
                operation="assess-qualification-review",
                resource=obligation_id,
            )
            assessment = runtime.qualification.assess_review(
                obligation_id,
                assessment_id=command.id,
                disposition=command.disposition,
                basis_refs=tuple(command.basis_refs),
                rationale=command.rationale,
            )
            updated = runtime.qualification.get_obligation(obligation_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="review obligation not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "assessment": {
                "id": assessment.id,
                "obligation_id": assessment.obligation_id,
                "disposition": assessment.disposition,
                "basis_refs": list(assessment.basis_refs),
                "rationale": assessment.rationale,
            },
            "review": _review_value(updated),
        }

    @app.post("/v1/qualification/reviews/{obligation_id}/resolve")
    async def resolve_qualification_review(
        obligation_id: str,
        command: QualificationResolutionCommand,
        request: Request,
    ) -> dict[str, object]:
        context = _authenticate(runtime, request)
        try:
            obligation = runtime.qualification.get_obligation(obligation_id)
            runtime.identity.assert_claimed_principal(context, obligation.principal)
            _assert_transition_authority(
                runtime,
                context,
                operation="resolve-qualification-review",
                resource=obligation_id,
            )
            updated = runtime.qualification.resolve_review(
                obligation_id,
                resolution_ref=command.resolution_ref,
                basis_refs=tuple(command.basis_refs),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="review obligation not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _review_value(updated)

    @app.post("/v1/qualification/dependencies/{dependency_id}/advance")
    async def advance_qualification_dependency(
        dependency_id: str,
        command: QualificationAdvanceCommand,
        request: Request,
    ) -> dict[str, object]:
        context = _authenticate(runtime, request)
        try:
            current = runtime.qualification.get_dependency(dependency_id)
            runtime.identity.assert_claimed_principal(context, current.principal)
            _assert_transition_authority(
                runtime,
                context,
                operation="advance-qualification-dependency",
                resource=dependency_id,
            )
            item = runtime.qualification.supersede_dependency_after_review(
                dependency_id,
                obligation_id=command.obligation_id,
                assessment_id=command.assessment_id,
                new_version=command.new_version,
                basis_refs=tuple(command.basis_refs),
                successor_id=command.successor_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "id": item.id,
            "principal": item.principal,
            "subject_ref": item.subject_ref,
            "dependency_ref": item.dependency_ref,
            "dependency_version": item.dependency_version,
            "status": item.status,
            "supersedes_dependency_id": item.supersedes_dependency_id,
        }


__all__ = [
    "PortfolioActivateCommand",
    "PortfolioProposalCommand",
    "PortfolioRetireCommand",
    "QualificationAdvanceCommand",
    "QualificationAssessmentCommand",
    "QualificationChangeCommand",
    "QualificationDependencyCommand",
    "QualificationResolutionCommand",
    "ResourceAllocationCommand",
    "ResourceBudgetLineCommand",
    "StrategicIssueCloseCommand",
    "StrategicIssueCommand",
    "StrategicOptionCommand",
    "register_agency_protocol_routes",
]
