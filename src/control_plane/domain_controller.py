from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .domain_store import DomainJournal, new_id
from .profile_effect_rules import capability_policy
from .provider_protocol import CapabilityRequest, EffectClass, ProviderRegistry


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
    DECISION = "decision"
    VERIFICATION = "verification"
    PROBLEM_DEFINITION = "problem-definition"


class RevisionDisposition(StrEnum):
    REOPEN_COGNITION = "reopen-cognition"
    WAIT = "wait"
    CLOSE = "close"


class RepairClosure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: new_id("closure"))
    controller_ref: str
    controller_state_version: int
    responsibility_ref: str | None = None
    subject_ref: str | None = None
    problem_ref: str | None = None
    basis_refs: list[str] = Field(default_factory=list)
    selected_direction: str
    rationale: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    verification_plan: list[str] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=list)
    escalation_conditions: list[str] = Field(default_factory=list)
    reopen_conditions: list[str] = Field(default_factory=list)
    requested_capabilities: list[str] = Field(default_factory=list)
    effect_class: EffectClass = EffectClass.READ_ONLY

    @model_validator(mode="after")
    def _valid(self) -> RepairClosure:
        if not self.selected_direction.strip() or not self.basis_refs:
            raise ValueError("repair closure requires direction and basis")
        if not self.acceptance_criteria or not self.verification_plan:
            raise ValueError("repair closure requires acceptance and verification")
        return self


class RepairRevision(BaseModel):
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

    @model_validator(mode="after")
    def _grounded(self) -> RepairRevision:
        if not self.work_ref or not self.closure_ref or not self.reason:
            raise ValueError("repair revision requires work, closure and reason")
        if not (self.outcome_refs or self.verification_refs):
            raise ValueError("repair revision requires outcome or verification refs")
        if self.recommended_disposition is RevisionDisposition.CLOSE and not self.verification_refs:
            raise ValueError("close revision requires verification")
        return self


class ControllerState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: new_id("controller"))
    responsibility_ref: str
    subject_ref: str
    context_refs: list[str] = Field(default_factory=list)
    status: ControllerStatus = ControllerStatus.OPEN
    version: int = 0
    pending_ref: str | None = None
    active_closure_ref: str | None = None
    work_proposal_ref: str | None = None
    last_revision_ref: str | None = None
    last_decision_ref: str | None = None
    last_result_ref: str | None = None


class ControllerDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: new_id("controller-decision"))
    controller_ref: str
    state_version: int
    kind: ControllerDecisionKind
    reason: str = ""
    capability: str | None = None
    instruction: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    closure: RepairClosure | None = None
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
    revision: RepairRevision | None = None


class PersonalController:
    """Control-plane-only controller state machine.

    It owns repair/manual-task staging only. Universal responsibility and
    assignment state remain in World Runtime through PersonalRuntimeBridge.
    """

    def __init__(self, journal: DomainJournal, providers: ProviderRegistry) -> None:
        self.ledger = journal
        self.providers = providers

    def create(
        self,
        *,
        responsibility_ref: str,
        subject_ref: str,
        context_refs: list[str] | None = None,
        controller_id: str | None = None,
    ) -> ControllerState:
        state = ControllerState(
            id=controller_id or new_id("controller"),
            responsibility_ref=responsibility_ref,
            subject_ref=subject_ref,
            context_refs=list(context_refs or []),
        )
        if self.get(state.id) is not None:
            raise ValueError(f"controller already exists: {state.id}")
        return self._store_state(state)

    def get(self, controller_id: str) -> ControllerState | None:
        row = self.ledger.project_get("controller.current", controller_id)
        return None if row is None else ControllerState.model_validate(row[0])

    def decisions(self, controller_id: str) -> list[ControllerDecision]:
        return [
            ControllerDecision.model_validate(event.payload["decision"])
            for event in self.ledger.events(stream=f"controller:{controller_id}")
            if event.kind == "control-plane.controller.decision"
        ]

    def closures(self, controller_id: str) -> list[RepairClosure]:
        return [
            RepairClosure.model_validate(event.payload["closure"])
            for event in self.ledger.events(stream=f"controller:{controller_id}")
            if event.kind == "control-plane.controller.closure"
        ]

    def revisions(self, controller_id: str) -> list[RepairRevision]:
        return [
            RepairRevision.model_validate(event.payload["revision"])
            for event in self.ledger.events(stream=f"controller:{controller_id}")
            if event.kind == "control-plane.controller.revision"
        ]

    async def step(self, controller_id: str, policy: StagedDomainPolicy) -> ControllerState:
        state = self.get(controller_id)
        if state is None:
            raise ValueError(f"unknown controller: {controller_id}")
        decision = await policy.select(state.model_copy(deep=True))
        if decision.controller_ref != state.id or decision.state_version != state.version:
            raise ValueError("controller policy returned stale or foreign decision")
        return await self.apply(decision)

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
            return self._transition(state, decision, ControllerStatus.CLOSED, None)
        if decision.kind is ControllerDecisionKind.REOPEN:
            return self._transition(
                state,
                decision,
                ControllerStatus.OPEN,
                None,
                active_closure_ref=None,
                work_proposal_ref=None,
            )
        if decision.kind is ControllerDecisionKind.WAIT:
            return self._transition(
                state,
                decision,
                ControllerStatus.WAITING,
                decision.id,
            )
        raise ValueError(f"unsupported decision kind: {decision.kind}")

    def _require_current(self, decision: ControllerDecision) -> ControllerState:
        state = self.get(decision.controller_ref)
        if state is None or state.version != decision.state_version:
            raise ValueError("stale or unknown controller decision")
        if state.status is ControllerStatus.OPEN:
            allowed = (
                {
                    ControllerDecisionKind.PROPOSE_WORK,
                    ControllerDecisionKind.WAIT,
                    ControllerDecisionKind.CLOSE,
                }
                if state.active_closure_ref
                else {
                    ControllerDecisionKind.INVOKE_CAPABILITY,
                    ControllerDecisionKind.FORM_CLOSURE,
                    ControllerDecisionKind.WAIT,
                    ControllerDecisionKind.CLOSE,
                }
            )
        elif state.status is ControllerStatus.WAITING:
            allowed = (
                {ControllerDecisionKind.ASSESS_REVISION}
                if state.work_proposal_ref
                else {ControllerDecisionKind.REOPEN}
            )
        elif state.status is ControllerStatus.REOPEN_REQUIRED:
            allowed = {ControllerDecisionKind.REOPEN}
        else:
            allowed = set()
        if decision.kind not in allowed:
            raise ValueError(f"{state.status.value} state does not admit {decision.kind.value}")
        return state

    async def _invoke_capability(
        self,
        state: ControllerState,
        decision: ControllerDecision,
    ) -> ControllerState:
        if not decision.capability:
            raise ValueError("invoke-capability requires capability")
        if capability_policy(decision.capability) is not None:
            raise PermissionError(
                "reality-changing capability requires materialized Work and Runtime effect grant"
            )
        request = CapabilityRequest(
            capability=decision.capability,
            instruction=decision.instruction,
            parameters=dict(decision.parameters),
            constraints=dict(decision.constraints),
            metadata={
                "controller_ref": state.id,
                "controller_decision_ref": decision.id,
                "controller_state_version": state.version,
            },
        )
        result = await self.providers.invoke(
            request,
            controller_id=state.id,
        )
        event = self.ledger.append(
            stream=f"controller:{state.id}",
            kind="control-plane.controller.capability-result",
            payload={
                "decision_ref": decision.id,
                "request_ref": request.id,
                "result": result.model_dump(mode="json"),
            },
        )
        return self._store_state(
            state.model_copy(
                update={
                    "version": state.version + 1,
                    "last_decision_ref": decision.id,
                    "last_result_ref": event.id,
                }
            )
        )

    def _form_closure(
        self,
        state: ControllerState,
        decision: ControllerDecision,
    ) -> ControllerState:
        closure = decision.closure
        if closure is None:
            raise ValueError("form-closure requires closure")
        if closure.controller_ref != state.id or closure.controller_state_version != state.version:
            raise ValueError("closure is stale or foreign")
        self.ledger.append(
            stream=f"controller:{state.id}",
            kind="control-plane.controller.closure",
            payload={"decision_ref": decision.id, "closure": closure.model_dump(mode="json")},
        )
        return self._transition(
            state,
            decision,
            ControllerStatus.OPEN,
            None,
            active_closure_ref=closure.id,
        )

    def _propose_work(
        self,
        state: ControllerState,
        decision: ControllerDecision,
    ) -> ControllerState:
        if not state.active_closure_ref:
            raise ValueError("work proposal requires active closure")
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
        self.ledger.project_put("work.proposal", proposal_id, value)
        self.ledger.append(
            stream=f"controller:{state.id}",
            kind="control-plane.controller.work-proposed",
            payload=value,
        )
        return self._transition(
            state,
            decision,
            ControllerStatus.WAITING,
            proposal_id,
            work_proposal_ref=proposal_id,
        )

    def _assess_revision(
        self,
        state: ControllerState,
        decision: ControllerDecision,
    ) -> ControllerState:
        revision = decision.revision
        if revision is None:
            raise ValueError("assess-revision requires revision")
        self.ledger.append(
            stream=f"controller:{state.id}",
            kind="control-plane.controller.revision",
            payload={"decision_ref": decision.id, "revision": revision.model_dump(mode="json")},
        )
        if revision.recommended_disposition is RevisionDisposition.CLOSE:
            status, pending = ControllerStatus.CLOSED, None
        elif revision.recommended_disposition is RevisionDisposition.REOPEN_COGNITION:
            status, pending = ControllerStatus.REOPEN_REQUIRED, None
        else:
            status, pending = ControllerStatus.WAITING, revision.id
        return self._transition(
            state,
            decision,
            status,
            pending,
            last_revision_ref=revision.id,
            last_result_ref=revision.id,
        )

    def _transition(
        self,
        state: ControllerState,
        decision: ControllerDecision,
        status: ControllerStatus,
        pending_ref: str | None,
        **updates: Any,
    ) -> ControllerState:
        value = state.model_copy(
            update={
                "status": status,
                "version": state.version + 1,
                "pending_ref": pending_ref,
                "last_decision_ref": decision.id,
                **updates,
            }
        )
        return self._store_state(value)

    def _store_state(self, state: ControllerState) -> ControllerState:
        row = self.ledger.project_get("controller.current", state.id)
        expected = 0 if row is None else row[1]
        self.ledger.project_put(
            "controller.current",
            state.id,
            state.model_dump(mode="json"),
            expected_version=expected,
        )
        self.ledger.append(
            stream=f"controller:{state.id}",
            kind="control-plane.controller.state",
            payload={"state": state.model_dump(mode="json")},
        )
        return state

    def _record_decision(self, decision: ControllerDecision) -> None:
        self.ledger.append(
            stream=f"controller:{decision.controller_ref}",
            kind="control-plane.controller.decision",
            payload={"decision": decision.model_dump(mode="json")},
        )


class StagedDomainPolicy(ABC):
    controller: PersonalController

    @property
    @abstractmethod
    def policy_ref(self) -> str: ...

    @abstractmethod
    def _diagnosis(self, state: ControllerState) -> ControllerDecision: ...

    @abstractmethod
    def _form_closure(
        self,
        state: ControllerState,
        diagnosis_result: dict[str, Any] | None,
    ) -> ControllerDecision: ...

    @abstractmethod
    def _propose_work(self, state: ControllerState) -> ControllerDecision: ...

    @abstractmethod
    def _current_revision(self, state: ControllerState) -> Any | None: ...

    @abstractmethod
    def _revision(self, state: ControllerState) -> ControllerDecision: ...

    @abstractmethod
    def _human_reopen_revision(self, state: ControllerState) -> ControllerDecision: ...

    def _has_human_followup(self) -> bool:
        value = getattr(self, "human_instruction", None)
        return isinstance(value, str) and bool(value.strip())

    async def select(self, state: ControllerState) -> ControllerDecision:
        if state.status is ControllerStatus.CLOSED:
            raise ValueError("closed controller must not restart implicitly")
        if state.status is ControllerStatus.REOPEN_REQUIRED:
            return ControllerDecision(
                controller_ref=state.id,
                state_version=state.version,
                kind=ControllerDecisionKind.REOPEN,
                reason="revision requires a new domain investigation pass",
            )
        if state.status is ControllerStatus.WAITING:
            if state.work_proposal_ref:
                if self._current_revision(state) is None:
                    return self._revision(state)
                if self._has_human_followup():
                    return self._human_reopen_revision(state)
                raise ValueError("waiting controller requires explicit follow-up")
            return ControllerDecision(
                controller_ref=state.id,
                state_version=state.version,
                kind=ControllerDecisionKind.REOPEN,
                reason="resume explicit domain wait",
            )
        if state.active_closure_ref:
            return self._propose_work(state)

        decisions = self.controller.decisions(state.id)
        last = decisions[-1] if decisions else None
        if last is None or last.kind is ControllerDecisionKind.REOPEN:
            return self._diagnosis(state)
        if (
            last.kind is ControllerDecisionKind.INVOKE_CAPABILITY
            and last.parameters.get("phase") == "diagnosis"
        ):
            result = None
            for event in reversed(self.controller.ledger.events(stream=f"controller:{state.id}")):
                if (
                    event.kind == "control-plane.controller.capability-result"
                    and event.payload.get("decision_ref") == last.id
                ):
                    raw = event.payload.get("result")
                    result = dict(raw) if isinstance(raw, dict) else None
                    break
            if not result or str(result.get("status", "")) != "succeeded":
                return ControllerDecision(
                    controller_ref=state.id,
                    state_version=state.version,
                    kind=ControllerDecisionKind.WAIT,
                    reason="diagnosis failed; wait rather than invent closure",
                )
            return self._form_closure(state, result)
        raise ValueError(f"unexpected controller stage after {last.kind.value}")


__all__ = [
    "ControllerDecision",
    "ControllerDecisionKind",
    "ControllerState",
    "ControllerStatus",
    "PersonalController",
    "RepairClosure",
    "RepairRevision",
    "RevisionDisposition",
    "RevisionScope",
    "StagedDomainPolicy",
]
