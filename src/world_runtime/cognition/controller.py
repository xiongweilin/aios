from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from world_runtime.common import new_id
from world_runtime.execution import CapabilityRequest, EffectClass


class ControllerStatus(StrEnum):
    OPEN = "open"
    WAITING = "waiting"
    CLOSED = "closed"
    REOPEN_REQUIRED = "reopen-required"


class ControllerDecisionKind(StrEnum):
    INVOKE_CAPABILITY = "invoke-capability"
    FORM_CLOSURE = "form-closure"
    PROPOSE_WORK = "propose-work"
    ASSESS_REVISION = "assess-revision"
    CLOSE = "close"
    REOPEN = "reopen"
    WAIT = "wait"


class RevisionScope(StrEnum):
    EXECUTION = "execution"
    WORK_SPEC = "work-spec"
    DECISION = "decision"
    REPRESENTATION = "representation"
    INPUTS = "inputs"
    EVIDENCE_ACQUISITION = "evidence-acquisition"
    VERIFICATION = "verification"
    GOAL = "goal"
    AUTHORIZATION = "authorization"
    PROBLEM_DEFINITION = "problem-definition"


class RevisionDisposition(StrEnum):
    RETRY_RUN = "retry-run"
    REVISE_WORK = "revise-work"
    REOPEN_COGNITION = "reopen-cognition"
    ACQUIRE_EVIDENCE = "acquire-evidence"
    REQUEST_AUTHORIZATION = "request-authorization"
    RECONCILE_EFFECT = "reconcile-effect"
    WAIT = "wait"
    CLOSE = "close"


class HandoffDisposition(StrEnum):
    CARRY_FORWARD = "carry-forward"
    RECONSIDER = "reconsider"
    INVALIDATED = "invalidated"
    UNRESOLVED = "unresolved"
    CONTEXT_ONLY = "context-only"


class CognitiveHandoffEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_refs: list[str] = Field(default_factory=list)
    goal_refs: list[str] = Field(default_factory=list)
    constraint_refs: list[str] = Field(default_factory=list)
    assumption_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    observation_refs: list[str] = Field(default_factory=list)
    assertion_refs: list[str] = Field(default_factory=list)
    unknown_refs: list[str] = Field(default_factory=list)
    counterevidence_refs: list[str] = Field(default_factory=list)
    selected_candidate_refs: list[str] = Field(default_factory=list)
    deferred_candidate_refs: list[str] = Field(default_factory=list)
    rejected_candidate_refs: list[str] = Field(default_factory=list)
    authorization_refs: list[str] = Field(default_factory=list)
    closure_refs: list[str] = Field(default_factory=list)
    invalidation_refs: list[str] = Field(default_factory=list)
    reopen_condition_refs: list[str] = Field(default_factory=list)
    dispositions: dict[str, HandoffDisposition] = Field(default_factory=dict)


class CognitiveClosure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: new_id("closure"))
    controller_ref: str
    controller_state_version: int
    responsibility_ref: str | None = None
    subject_ref: str | None = None
    problem_ref: str | None = None
    scope: dict[str, str] = Field(default_factory=dict)
    basis_refs: list[str] = Field(default_factory=list)
    selected_candidate_refs: list[str] = Field(default_factory=list)
    deferred_candidate_refs: list[str] = Field(default_factory=list)
    rejected_candidate_refs: list[str] = Field(default_factory=list)
    deferred_issue_refs: list[str] = Field(default_factory=list)
    selected_direction: str
    rationale: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    verification_plan: list[str] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=list)
    escalation_conditions: list[str] = Field(default_factory=list)
    reopen_conditions: list[str] = Field(default_factory=list)
    requested_capabilities: list[str] = Field(default_factory=list)
    effect_class: EffectClass = EffectClass.READ_ONLY
    policy_ref: str | None = None
    handoff: CognitiveHandoffEnvelope = Field(default_factory=CognitiveHandoffEnvelope)

    @model_validator(mode="after")
    def _validate_closure(self) -> "CognitiveClosure":
        if self.controller_state_version < 0:
            raise ValueError("closure controller_state_version cannot be negative")
        if not self.selected_direction.strip() or not self.basis_refs:
            raise ValueError("closure requires selected_direction and basis_refs")
        if not self.acceptance_criteria or not self.verification_plan or not self.reopen_conditions:
            raise ValueError("closure requires acceptance, verification and reopen conditions")
        return self


class RevisionAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: new_id("revision"))
    controller_ref: str
    controller_state_version: int
    work_ref: str
    closure_ref: str
    run_ref: str | None = None
    outcome_refs: list[str] = Field(default_factory=list)
    verification_refs: list[str] = Field(default_factory=list)
    reason_refs: list[str] = Field(default_factory=list)
    failure_class: str = ""
    revision_scope: RevisionScope
    recommended_disposition: RevisionDisposition
    reason: str
    carry_forward_refs: list[str] = Field(default_factory=list)
    reconsider_refs: list[str] = Field(default_factory=list)
    invalidated_refs: list[str] = Field(default_factory=list)
    unresolved_refs: list[str] = Field(default_factory=list)
    policy_ref: str | None = None
    handoff: CognitiveHandoffEnvelope = Field(default_factory=CognitiveHandoffEnvelope)

    @model_validator(mode="after")
    def _grounded(self) -> "RevisionAssessment":
        if not self.work_ref or not self.closure_ref or not self.reason:
            raise ValueError("revision requires work, closure and reason")
        if not (self.outcome_refs or self.verification_refs):
            raise ValueError("revision requires outcome_refs or verification_refs")
        if self.recommended_disposition is RevisionDisposition.CLOSE and not self.verification_refs:
            raise ValueError("close disposition requires verification_refs")
        return self


class ControllerState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: new_id("controller"))
    responsibility_ref: str | None = None
    subject_ref: str | None = None
    context_refs: list[str] = Field(default_factory=list)
    candidate_refs: list[str] = Field(default_factory=list)
    open_issue_refs: list[str] = Field(default_factory=list)
    status: ControllerStatus = ControllerStatus.OPEN
    version: int = 0
    pending_ref: str | None = None
    active_closure_ref: str | None = None
    work_proposal_ref: str | None = None
    last_revision_ref: str | None = None
    last_decision_ref: str | None = None
    last_result_ref: str | None = None

    @model_validator(mode="after")
    def _valid_state(self) -> "ControllerState":
        if self.version < 0:
            raise ValueError("controller state version cannot be negative")
        if self.status is ControllerStatus.WAITING and not self.pending_ref:
            raise ValueError("waiting controller state requires pending_ref")
        if self.status is not ControllerStatus.WAITING and self.pending_ref is not None:
            raise ValueError("only waiting controller state may carry pending_ref")
        return self


class ControllerDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: new_id("controller-decision"))
    controller_ref: str
    state_version: int
    kind: ControllerDecisionKind
    reason: str = ""
    policy_ref: str | None = None
    capability: str | None = None
    instruction: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    closure: CognitiveClosure | None = None
    closure_ref: str | None = None
    assessment_ref: str | None = None
    work_kind: str = "generic-task"
    work_title: str | None = None
    work_description: str = ""
    requested_capabilities: list[str] = Field(default_factory=list)
    expected_result: str = ""
    stop_conditions: list[str] = Field(default_factory=list)
    escalation_conditions: list[str] = Field(default_factory=list)
    effect_class: str = EffectClass.READ_ONLY.value
    revision: RevisionAssessment | None = None


class ControllerPolicy(Protocol):
    @property
    def policy_ref(self) -> str: ...

    async def select(self, state: ControllerState) -> ControllerDecision: ...


class CognitiveController:
    """Durable cognitive controller over the World Ledger."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.ledger = runtime.ledger

    def create(
        self,
        *,
        responsibility_ref: str | None = None,
        subject_ref: str | None = None,
        context_refs: list[str] | None = None,
        candidate_refs: list[str] | None = None,
        open_issue_refs: list[str] | None = None,
        controller_id: str | None = None,
    ) -> ControllerState:
        state = ControllerState(
            id=controller_id or new_id("controller"),
            responsibility_ref=responsibility_ref,
            subject_ref=subject_ref,
            context_refs=list(context_refs or []),
            candidate_refs=list(candidate_refs or []),
            open_issue_refs=list(open_issue_refs or []),
        )
        if self.get(state.id) is not None:
            raise ValueError(f"controller already exists: {state.id}")
        return self._store_state(state)

    def get(self, controller_id: str) -> ControllerState | None:
        row = self.ledger.project_get("cognition.controller", controller_id)
        return None if row is None else ControllerState.model_validate(row[0])

    def decisions(self, controller_id: str) -> list[ControllerDecision]:
        return [
            ControllerDecision.model_validate(event.payload["decision"])
            for event in self.ledger.events(stream=f"controller:{controller_id}")
            if event.kind == "cognition.controller.decision"
        ]

    def closures(self, controller_id: str) -> list[CognitiveClosure]:
        return [
            CognitiveClosure.model_validate(event.payload["closure"])
            for event in self.ledger.events(stream=f"controller:{controller_id}")
            if event.kind == "cognition.controller.closure"
        ]

    def revisions(self, controller_id: str) -> list[RevisionAssessment]:
        return [
            RevisionAssessment.model_validate(event.payload["revision"])
            for event in self.ledger.events(stream=f"controller:{controller_id}")
            if event.kind == "cognition.controller.revision"
        ]

    async def step(self, controller_id: str, policy: ControllerPolicy) -> ControllerState:
        state = self.get(controller_id)
        if state is None:
            raise ValueError(f"unknown controller: {controller_id}")
        decision = await policy.select(state.model_copy(deep=True))
        if decision.controller_ref != state.id or decision.state_version != state.version:
            raise ValueError("controller policy returned stale or foreign decision")
        return await self.apply(
            decision.model_copy(update={"policy_ref": policy.policy_ref})
        )

    async def apply(self, decision: ControllerDecision) -> ControllerState:
        state = self._require_current(decision)
        self._record_decision(decision)
        if decision.kind is ControllerDecisionKind.INVOKE_CAPABILITY:
            return await self._invoke_capability(state, decision)
        if decision.kind is ControllerDecisionKind.FORM_CLOSURE:
            return self._form_closure(state, decision)
        if decision.kind is ControllerDecisionKind.PROPOSE_WORK:
            return self._propose_work(state, decision)
        if decision.kind is ControllerDecisionKind.ASSESS_REVISION:
            return self._assess_revision(state, decision)
        if decision.kind is ControllerDecisionKind.CLOSE:
            return self._transition(
                state, decision, status=ControllerStatus.CLOSED, pending_ref=None
            )
        if decision.kind is ControllerDecisionKind.REOPEN:
            return self._transition(
                state,
                decision,
                status=ControllerStatus.OPEN,
                pending_ref=None,
                active_closure_ref=None,
                work_proposal_ref=None,
            )
        if decision.kind is ControllerDecisionKind.WAIT:
            return self._transition(
                state,
                decision,
                status=ControllerStatus.WAITING,
                pending_ref=decision.id,
            )
        raise ValueError(f"unsupported decision: {decision.kind}")

    def _require_current(self, decision: ControllerDecision) -> ControllerState:
        state = self.get(decision.controller_ref)
        if state is None or state.version != decision.state_version:
            raise ValueError("stale or unknown controller decision")
        if state.status is ControllerStatus.OPEN:
            allowed = (
                {
                    ControllerDecisionKind.PROPOSE_WORK,
                    ControllerDecisionKind.CLOSE,
                    ControllerDecisionKind.WAIT,
                }
                if state.active_closure_ref
                else {
                    ControllerDecisionKind.INVOKE_CAPABILITY,
                    ControllerDecisionKind.FORM_CLOSURE,
                    ControllerDecisionKind.CLOSE,
                    ControllerDecisionKind.WAIT,
                }
            )
        elif state.status is ControllerStatus.WAITING:
            allowed = (
                {ControllerDecisionKind.ASSESS_REVISION}
                if state.work_proposal_ref
                else {ControllerDecisionKind.REOPEN}
            )
        else:
            allowed = {ControllerDecisionKind.REOPEN}
        if decision.kind not in allowed:
            raise ValueError(
                f"{state.status.value} controller state does not admit {decision.kind.value}"
            )
        return state

    async def _invoke_capability(
        self, state: ControllerState, decision: ControllerDecision
    ) -> ControllerState:
        if not decision.capability:
            raise ValueError("invoke-capability requires capability")
        request = CapabilityRequest(
            capability=decision.capability,
            instruction=decision.instruction,
            parameters=dict(decision.parameters),
            constraints=dict(decision.constraints),
            effect_class="read",
            metadata={
                "controller_ref": state.id,
                "controller_decision_ref": decision.id,
                "controller_state_version": state.version,
            },
        )
        waiting = self._transition(
            state, decision, status=ControllerStatus.WAITING, pending_ref=request.id
        )
        result = await self.runtime.invoke(request)
        event = self.ledger.append(
            stream=f"controller:{state.id}",
            kind="cognition.controller.capability-result",
            payload={
                "decision_ref": decision.id,
                "request_ref": request.id,
                "result": result.model_dump(mode="json"),
            },
        )
        return self._store_state(
            waiting.model_copy(
                update={
                    "status": ControllerStatus.OPEN,
                    "version": waiting.version + 1,
                    "pending_ref": None,
                    "last_result_ref": event.id,
                }
            )
        )

    def _form_closure(
        self, state: ControllerState, decision: ControllerDecision
    ) -> ControllerState:
        closure = decision.closure
        if closure is None:
            raise ValueError("form-closure requires closure")
        if (
            closure.controller_ref != state.id
            or closure.controller_state_version != state.version
        ):
            raise ValueError("closure is stale or foreign")
        self.ledger.append(
            stream=f"controller:{state.id}",
            kind="cognition.controller.closure",
            payload={
                "decision_ref": decision.id,
                "closure": closure.model_dump(mode="json"),
            },
        )
        return self._transition(
            state,
            decision,
            status=ControllerStatus.OPEN,
            pending_ref=None,
            active_closure_ref=closure.id,
        )

    def _propose_work(
        self, state: ControllerState, decision: ControllerDecision
    ) -> ControllerState:
        if not state.responsibility_ref or not state.active_closure_ref:
            raise ValueError("work proposal requires responsibility and active closure")
        proposal_id = new_id("work-proposal")
        value = {
            "id": proposal_id,
            "controller_ref": state.id,
            "responsibility_ref": state.responsibility_ref,
            "closure_ref": state.active_closure_ref,
            "assessment_ref": decision.assessment_ref,
            "kind": decision.work_kind,
            "title": decision.work_title or decision.work_kind,
            "description": decision.work_description,
            "requested_capabilities": list(decision.requested_capabilities),
            "expected_result": decision.expected_result,
            "stop_conditions": list(decision.stop_conditions),
            "escalation_conditions": list(decision.escalation_conditions),
            "effect_class": decision.effect_class,
            "status": "proposed",
        }
        self.ledger.project_put("cognition.work-proposal", proposal_id, value)
        self.ledger.append(
            stream=f"controller:{state.id}",
            kind="cognition.controller.work-proposed",
            payload=value,
        )
        return self._transition(
            state,
            decision,
            status=ControllerStatus.WAITING,
            pending_ref=proposal_id,
            work_proposal_ref=proposal_id,
        )

    def _assess_revision(
        self, state: ControllerState, decision: ControllerDecision
    ) -> ControllerState:
        revision = decision.revision
        if revision is None:
            raise ValueError("assess-revision requires revision")
        if (
            revision.controller_ref != state.id
            or revision.controller_state_version != state.version
        ):
            raise ValueError("revision is stale or foreign")
        self.ledger.append(
            stream=f"controller:{state.id}",
            kind="cognition.controller.revision",
            payload={
                "decision_ref": decision.id,
                "revision": revision.model_dump(mode="json"),
            },
        )
        if revision.recommended_disposition is RevisionDisposition.CLOSE:
            status, pending = ControllerStatus.CLOSED, None
        elif revision.recommended_disposition in {
            RevisionDisposition.REVISE_WORK,
            RevisionDisposition.REOPEN_COGNITION,
            RevisionDisposition.ACQUIRE_EVIDENCE,
        }:
            status, pending = ControllerStatus.REOPEN_REQUIRED, None
        else:
            status, pending = ControllerStatus.WAITING, revision.id
        return self._transition(
            state,
            decision,
            status=status,
            pending_ref=pending,
            last_revision_ref=revision.id,
            last_result_ref=revision.id,
        )

    def _transition(
        self,
        state: ControllerState,
        decision: ControllerDecision,
        *,
        status: ControllerStatus,
        pending_ref: str | None,
        active_closure_ref: str | None | object = ...,
        work_proposal_ref: str | None | object = ...,
        last_revision_ref: str | None | object = ...,
        last_result_ref: str | None | object = ...,
    ) -> ControllerState:
        update: dict[str, Any] = {
            "status": status,
            "version": state.version + 1,
            "pending_ref": pending_ref,
            "last_decision_ref": decision.id,
        }
        for name, value in {
            "active_closure_ref": active_closure_ref,
            "work_proposal_ref": work_proposal_ref,
            "last_revision_ref": last_revision_ref,
            "last_result_ref": last_result_ref,
        }.items():
            if value is not ...:
                update[name] = value
        return self._store_state(state.model_copy(update=update))

    def _store_state(self, state: ControllerState) -> ControllerState:
        current = self.ledger.project_get("cognition.controller", state.id)
        expected = 0 if current is None else current[1]
        self.ledger.project_put(
            "cognition.controller",
            state.id,
            state.model_dump(mode="json"),
            expected_version=expected,
        )
        self.ledger.append(
            stream=f"controller:{state.id}",
            kind="cognition.controller.state",
            payload={"state": state.model_dump(mode="json")},
        )
        return state

    def _record_decision(self, decision: ControllerDecision) -> None:
        self.ledger.append(
            stream=f"controller:{decision.controller_ref}",
            kind="cognition.controller.decision",
            payload={"decision": decision.model_dump(mode="json")},
        )


def latest_controller_decision(
    controller: CognitiveController, controller_id: str
) -> ControllerDecision | None:
    values = controller.decisions(controller_id)
    return values[-1] if values else None


def controller_capability_result(
    controller: CognitiveController, controller_id: str, decision_id: str
) -> dict[str, Any] | None:
    for event in reversed(
        controller.ledger.events(stream=f"controller:{controller_id}")
    ):
        if (
            event.kind == "cognition.controller.capability-result"
            and event.payload.get("decision_ref") == decision_id
        ):
            raw = event.payload.get("result")
            return dict(raw) if isinstance(raw, dict) else None
    return None
