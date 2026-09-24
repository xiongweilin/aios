from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .domain_controller import ControllerState, PersonalController
from .domain_store import DomainEvent, DomainJournal, new_id, utcnow
from .profile_effect_rules import capability_policy
from .provider_protocol import CapabilityRequest, CapabilityResult, ProviderRegistry

PERSONAL_RESULT_EVENT = "control-plane.capability-result-observed"
PERSONAL_HUMAN_INSTRUCTION_EVENT = "control-plane.human-instruction-observed"


class WorldRuntimeBoundaryError(RuntimeError):
    pass


class DomainWork(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: new_id("work"))
    responsibility_ref: str
    proposal_ref: str
    kind: str
    status: str = "running"
    runtime_work_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class DomainRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: new_id("run"))
    work_id: str
    workflow_id: str
    status: str = "running"
    runtime_run_ref: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


@dataclass(frozen=True, slots=True)
class PersonalResponsibilityContext:
    title: str
    description: str
    kind: str
    repo: str | None
    project: str | None
    verification_labels: dict[str, str]


class WorldRuntimeClient:
    REQUIRED_RUNTIME_PROTOCOL = "4.0"
    REQUIRED_SEMANTIC_LANGUAGE = "0.2.0"
    REQUIRED_CONTRACTS: ClassVar[dict[str, str]] = {
        "request_authentication": "request-authentication-v2",
        "transition_authority": "transition-authority-v1",
        "read_authorization": "read-authorization-v1",
        "persistent_responsibility": "persistent-responsibility-v3",
        "responsibility_assessment": "responsibility-assessment-v3",
        "responsibility_discharge": "responsibility-discharge-v3",
        "work_admission": "work-admission-v4",
        "decision_record": "decision-record-v4",
        "mandate_registration": "mandate-registration-v4",
        "authorization_issue": "authorization-issue-v4",
        "domain_effect_execution": "domain-effect-execution-v3",
        "domain_assignment": "domain-assignment-v3",
        "domain_report": "domain-report-v3",
    }

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 3.0,
        transport: httpx.BaseTransport | None = None,
        bearer_token: str = "",
        delegation_id: str = "",
    ) -> None:
        headers: dict[str, str] = {}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        if delegation_id:
            headers["X-World-Runtime-Delegation"] = delegation_id
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            headers=headers,
        )
        self._verified = False

    def close(self) -> None:
        self.client.close()

    def ensure_contracts(self) -> None:
        payload = self.get("/v1/contracts", verify=False)
        if str(payload.get("runtime_protocol", "")) != self.REQUIRED_RUNTIME_PROTOCOL:
            raise WorldRuntimeBoundaryError("World Runtime protocol mismatch")
        if str(payload.get("semantic_language", "")) != self.REQUIRED_SEMANTIC_LANGUAGE:
            raise WorldRuntimeBoundaryError("World Runtime semantic-language mismatch")
        contracts = payload.get("contracts")
        if not isinstance(contracts, dict):
            raise WorldRuntimeBoundaryError("World Runtime contract catalog is malformed")
        for name, current in self.REQUIRED_CONTRACTS.items():
            descriptor = contracts.get(name)
            if not isinstance(descriptor, dict) or descriptor.get("current") != current:
                raise WorldRuntimeBoundaryError(
                    f"World Runtime contract mismatch for {name}: expected {current}"
                )
        self._verified = True

    def _ensure(self) -> None:
        if not self._verified:
            self.ensure_contracts()

    def get(self, path: str, *, verify: bool = True) -> dict[str, Any]:
        if verify:
            self._ensure()
        try:
            response = self.client.get(path)
        except httpx.HTTPError as exc:
            raise WorldRuntimeBoundaryError(
                f"World Runtime request failed for {path}: {type(exc).__name__}"
            ) from exc
        if response.status_code >= 400:
            raise WorldRuntimeBoundaryError(
                f"World Runtime rejected {path}: HTTP {response.status_code}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise WorldRuntimeBoundaryError(
                f"World Runtime returned non-object response for {path}"
            )
        return payload

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure()
        try:
            response = self.client.post(path, json=payload)
        except httpx.HTTPError as exc:
            raise WorldRuntimeBoundaryError(
                f"World Runtime request failed for {path}: {type(exc).__name__}"
            ) from exc
        if response.status_code >= 400:
            raise WorldRuntimeBoundaryError(
                f"World Runtime rejected {path}: HTTP {response.status_code}"
            )
        value = response.json()
        if not isinstance(value, dict):
            raise WorldRuntimeBoundaryError(
                f"World Runtime returned non-object response for {path}"
            )
        return value

    def health(self) -> dict[str, Any]:
        try:
            return self.get("/healthz", verify=False)
        except WorldRuntimeBoundaryError as exc:
            return {"status": "unavailable", "error": str(exc)}


class PersonalRuntimeBridge:
    """External Domain Controller boundary.

    World Runtime owns only universal Responsibility/Assignment/Decision state.
    Control-plane owns its local repair/manual-task lifecycle and concrete
    providers, and reports typed evidence/outcome candidates back over HTTP.
    """

    def __init__(
        self,
        runtime: WorldRuntimeClient,
        controller: PersonalController,
        journal: DomainJournal,
        providers: ProviderRegistry,
        *,
        owner_principal: str,
    ) -> None:
        self.runtime = runtime
        self.controller = controller
        self.journal = journal
        self.providers = providers
        self.owner_principal = owner_principal

    @staticmethod
    def assignment_ref(responsibility_ref: str) -> str:
        return f"control-plane-assignment:{responsibility_ref}"

    @staticmethod
    def _ref(
        kind: str,
        identifier: str,
        *,
        namespace: str = "universal",
    ) -> dict[str, str]:
        return {
            "kind": kind,
            "id": identifier,
            "namespace": namespace,
            "version": "0.1",
        }

    def begin(
        self,
        *,
        title: str,
        description: str,
        kind: str,
        repo: str | None = None,
        project: str | None = None,
        verification_labels: dict[str, str] | None = None,
        parent_controller_id: str | None = None,
    ) -> tuple[ControllerState, str]:
        responsibility_ref = new_id("responsibility")
        assignment_ref = self.assignment_ref(responsibility_ref)
        scope = {
            "profile": "control-plane",
            "title": title,
            "kind": kind,
            "repo": repo or "",
            "project": project or "",
            "verification_labels": dict(verification_labels or {}),
        }
        self.runtime.post(
            "/v1/responsibilities",
            {
                "id": responsibility_ref,
                "principal": self.owner_principal,
                "subject": description,
                "domain": "control-plane",
                "scope": scope,
            },
        )
        self.runtime.post(
            "/v1/domain-assignments",
            {
                "id": assignment_ref,
                "responsibility_ref": responsibility_ref,
                "domain": "control-plane",
                "controller": "controller:control-plane",
                "review_conditions": [
                    {"trigger": "human-revision"},
                    {"trigger": "verification-failure"},
                ],
            },
        )
        self.runtime.post(
            f"/v1/domain-assignments/{assignment_ref}/reports",
            {"id": f"{assignment_ref}:accepted", "kind": "accepted"},
        )

        self.journal.project_put(
            "responsibility.context",
            responsibility_ref,
            {
                "title": title,
                "description": description,
                "kind": kind,
                "repo": repo,
                "project": project,
                "verification_labels": dict(verification_labels or {}),
            },
        )
        assessment_ref = new_id("assessment")
        subject_ref = f"personal:{responsibility_ref}"
        self.journal.append(
            stream=f"responsibility:{responsibility_ref}",
            kind="control-plane.responsibility-actionable",
            event_id=assessment_ref,
            payload={
                "responsibility_ref": responsibility_ref,
                "subject_ref": subject_ref,
                "basis_refs": ["control-plane:explicit-owner-task"],
            },
        )
        context_refs = [assessment_ref]
        if parent_controller_id:
            context_refs.append(parent_controller_id)
        state = self.controller.create(
            responsibility_ref=responsibility_ref,
            subject_ref=subject_ref,
            context_refs=context_refs,
        )
        return state, assessment_ref

    def context(self, state: ControllerState) -> PersonalResponsibilityContext:
        row = self.journal.project_get(
            "responsibility.context",
            state.responsibility_ref,
        )
        if row is None:
            raise ValueError("personal responsibility context is unavailable")
        value = row[0]
        labels = value.get("verification_labels", {})
        return PersonalResponsibilityContext(
            title=str(value.get("title", "Personal task")),
            description=str(value.get("description", "")),
            kind=str(value.get("kind", "personal-task")),
            repo=str(value.get("repo") or "") or None,
            project=str(value.get("project") or "") or None,
            verification_labels=(
                {str(k): str(v) for k, v in labels.items()} if isinstance(labels, dict) else {}
            ),
        )

    def assessment_ref(self, state: ControllerState) -> str:
        for ref in state.context_refs:
            if ref.startswith("assessment:"):
                return ref
        raise ValueError("personal controller has no responsibility assessment")

    def work_for_proposal(self, proposal_ref: str) -> DomainWork | None:
        row = self.journal.project_get("work.by-proposal", proposal_ref)
        if row is None:
            return None
        work_row = self.journal.project_get("work.current", str(row[0]["work_id"]))
        return None if work_row is None else DomainWork.model_validate(work_row[0])

    def work_for_state(self, state: ControllerState) -> DomainWork | None:
        if not state.work_proposal_ref:
            return None
        return self.work_for_proposal(state.work_proposal_ref)

    def materialize_work(self, state: ControllerState) -> DomainWork:
        proposal_ref = state.work_proposal_ref
        if not proposal_ref:
            raise ValueError("controller has no handed-off work proposal")
        existing = self.work_for_proposal(proposal_ref)
        if existing is not None:
            if existing.runtime_work_ref is None:
                existing = self._bind_runtime_work(existing)
                row = self.journal.project_get("work.current", existing.id)
                if row is None:
                    raise KeyError(existing.id)
                self.journal.project_put(
                    "work.current",
                    existing.id,
                    existing.model_dump(mode="json"),
                    expected_version=row[1],
                )
            return existing
        raw = self.journal.project_get("work.proposal", proposal_ref)
        if raw is None:
            raise ValueError("controller work proposal is unavailable")
        proposal = raw[0]
        work = DomainWork(
            responsibility_ref=state.responsibility_ref,
            proposal_ref=proposal_ref,
            kind=str(proposal.get("kind", "personal-task")),
            metadata={
                "controller_ref": state.id,
                "closure_ref": proposal.get("closure_ref"),
                "requested_capabilities": list(proposal.get("requested_capabilities", [])),
                "expected_result": proposal.get("expected_result", ""),
            },
        )
        work = self._bind_runtime_work(work)
        self.journal.project_put(
            "work.current",
            work.id,
            work.model_dump(mode="json"),
        )
        self.journal.project_put(
            "work.by-proposal",
            proposal_ref,
            {"work_id": work.id},
        )
        return work

    def list_work(self) -> list[DomainWork]:
        return [
            DomainWork.model_validate(item) for item in self.journal.project_list("work.current")
        ]

    def get_work(self, work_id: str) -> DomainWork | None:
        row = self.journal.project_get("work.current", work_id)
        return None if row is None else DomainWork.model_validate(row[0])

    def update_work_status(self, work_id: str, status: str) -> DomainWork:
        row = self.journal.project_get("work.current", work_id)
        if row is None:
            raise KeyError(work_id)
        value, version = row
        value["status"] = status
        value["updated_at"] = utcnow().isoformat()
        self.journal.project_put(
            "work.current",
            work_id,
            value,
            expected_version=version,
        )
        return DomainWork.model_validate(value)

    def start_run(self, work_id: str, *, workflow_id: str) -> DomainRun:
        work = self.get_work(work_id)
        if work is None:
            raise KeyError(work_id)
        if work.runtime_work_ref is None:
            work = self._bind_runtime_work(work)
            row = self.journal.project_get("work.current", work.id)
            if row is None:
                raise KeyError(work.id)
            self.journal.project_put(
                "work.current",
                work.id,
                work.model_dump(mode="json"),
                expected_version=row[1],
            )
        runtime_run = self.runtime.post(
            "/v1/runs",
            {
                "work_id": work.runtime_work_ref,
                "workflow_id": workflow_id,
            },
        )
        run = DomainRun(
            work_id=work_id,
            workflow_id=workflow_id,
            runtime_run_ref=str(runtime_run["id"]),
        )
        self.journal.project_put("run.current", run.id, run.model_dump(mode="json"))
        return run

    def list_runs(self, work_id: str) -> list[DomainRun]:
        return [
            DomainRun.model_validate(item)
            for item in self.journal.project_list("run.current")
            if str(item.get("work_id")) == work_id
        ]

    def update_run_status(self, run_id: str, status: str) -> DomainRun:
        row = self.journal.project_get("run.current", run_id)
        if row is None:
            raise KeyError(run_id)
        value, version = row
        value["status"] = status
        value["updated_at"] = utcnow().isoformat()
        self.journal.project_put(
            "run.current",
            run_id,
            value,
            expected_version=version,
        )
        return DomainRun.model_validate(value)

    async def invoke_capability(
        self,
        work_id: str,
        capability: str,
        *,
        run_id: str | None = None,
        instruction: str | None = None,
        parameters: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        subject_version_refs: list[str] | None = None,
        resource_ref: str | None = None,
    ) -> CapabilityResult:
        policy = capability_policy(capability)
        request = CapabilityRequest(
            capability=capability,
            instruction=instruction,
            parameters=dict(parameters or {}),
            idempotency_key=idempotency_key,
            run_id=run_id,
            subject_version_refs=list(subject_version_refs or []),
            resource_ref=resource_ref,
            actor_ref=self.owner_principal,
            effect_class=(policy.impact_class if policy is not None else "read-only"),
        )
        if policy is None:
            return await self.providers.invoke(
                request,
                controller_id=None,
                work_id=work_id,
                run_id=run_id,
            )
        return await self._invoke_reality_effect(
            work_id,
            request,
            policy_resource_required=policy.resource_required,
            policy_version_required=policy.version_required,
        )

    def _bind_runtime_work(self, work: DomainWork) -> DomainWork:
        runtime_work_id = f"control-plane:{work.id}"
        value = self.runtime.post(
            "/v1/work",
            {
                "id": runtime_work_id,
                "responsibility_id": work.responsibility_ref,
                "kind": work.kind,
                "payload": {
                    "domain_work_ref": work.id,
                    "proposal_ref": work.proposal_ref,
                    "metadata": dict(work.metadata),
                },
            },
        )
        return work.model_copy(update={"runtime_work_ref": str(value["id"])})

    def ensure_auxiliary_work(self, kind: str) -> DomainWork:
        safe_kind = kind.strip().replace(" ", "-")
        if not safe_kind:
            raise ValueError("auxiliary work kind must be non-empty")
        local_id = f"work:control-plane-auxiliary:{safe_kind}"
        existing = self.get_work(local_id)
        if existing is not None:
            if existing.runtime_work_ref is None:
                existing = self._bind_runtime_work(existing)
                row = self.journal.project_get("work.current", existing.id)
                if row is None:
                    raise KeyError(existing.id)
                self.journal.project_put(
                    "work.current",
                    existing.id,
                    existing.model_dump(mode="json"),
                    expected_version=row[1],
                )
            return existing
        responsibility_ref = f"responsibility:control-plane-auxiliary:{safe_kind}"
        self.runtime.post(
            "/v1/responsibilities",
            {
                "id": responsibility_ref,
                "principal": self.owner_principal,
                "subject": f"Control Plane standing {safe_kind} effects",
                "domain": "control-plane",
                "scope": {"profile": "control-plane", "kind": safe_kind},
            },
        )
        work = DomainWork(
            id=local_id,
            responsibility_ref=responsibility_ref,
            proposal_ref=f"auxiliary:{safe_kind}",
            kind=safe_kind,
            metadata={"standing": True},
        )
        work = self._bind_runtime_work(work)
        self.journal.project_put("work.current", work.id, work.model_dump(mode="json"))
        return work

    @staticmethod
    def _effect_identity_key(request: CapabilityRequest, runtime_work_ref: str) -> str:
        if request.idempotency_key:
            return request.idempotency_key
        semantic = {
            "capability": request.capability,
            "runtime_work_ref": runtime_work_ref,
            "instruction": request.instruction,
            "parameters": request.parameters,
            "subject_version_refs": request.subject_version_refs,
            "resource_ref": request.resource_ref,
            "effect_class": request.effect_class,
        }
        digest = hashlib.sha256(
            json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return f"control-plane-effect:{digest}"

    async def _invoke_reality_effect(
        self,
        work_id: str,
        request: CapabilityRequest,
        *,
        policy_resource_required: bool,
        policy_version_required: bool,
    ) -> CapabilityResult:
        work = self.get_work(work_id)
        if work is None:
            raise KeyError(work_id)
        if work.runtime_work_ref is None:
            work = self._bind_runtime_work(work)
            row = self.journal.project_get("work.current", work.id)
            if row is None:
                raise KeyError(work.id)
            self.journal.project_put(
                "work.current",
                work.id,
                work.model_dump(mode="json"),
                expected_version=row[1],
            )
        if policy_resource_required and not request.resource_ref:
            raise ValueError(f"{request.capability} requires resource_ref")
        if policy_version_required and not request.subject_version_refs:
            raise ValueError(f"{request.capability} requires subject_version_refs")

        run_ref = None
        if request.run_id:
            run = self.journal.project_get("run.current", request.run_id)
            if run is None:
                raise KeyError(request.run_id)
            domain_run = DomainRun.model_validate(run[0])
            if domain_run.work_id != work.id:
                raise ValueError("run does not belong to Control Plane Work")
            run_ref = domain_run.runtime_run_ref

        if work.runtime_work_ref is None:
            raise WorldRuntimeBoundaryError("Control Plane Work is not bound to Runtime")
        provider = self.providers.select(request.capability)
        resource = request.resource_ref or f"capability:{request.capability}"
        effect_key = self._effect_identity_key(request, work.runtime_work_ref)
        digest = hashlib.sha256(effect_key.encode("utf-8")).hexdigest()
        decision_id = f"control-plane-effect-decision:{digest}"
        mandate_id = f"control-plane-effect-mandate:{digest}"
        authorization_id = f"control-plane-effect-authorization:{digest}"
        request_id = f"control-plane-effect-request:{digest}"

        self.runtime.post(
            "/v1/decisions",
            {
                "id": decision_id,
                "subject": resource,
                "decided_by": self.owner_principal,
                "selected": {
                    "target_ref": resource,
                    "operation": "authorize-effect",
                    "action": request.capability,
                    "domain_work_ref": work.id,
                },
                "basis_refs": [f"evidence:control-plane-work:{work.id}"],
            },
        )
        self.runtime.post(
            "/v1/mandates",
            {
                "id": mandate_id,
                "principal": self.owner_principal,
                "scope": {"resource": resource},
                "authority_ceiling": {
                    "action": request.capability,
                    "resource": resource,
                },
            },
        )
        self.runtime.post(
            "/v1/authorizations",
            {
                "id": authorization_id,
                "principal": self.owner_principal,
                "action": request.capability,
                "resource": resource,
                "mandate_id": mandate_id,
                "decision_id": decision_id,
            },
        )

        runtime_request = {
            "id": request_id,
            "capability": request.capability,
            "work_id": work.runtime_work_ref,
            "run_id": run_ref,
            "instruction": request.instruction,
            "parameters": dict(request.parameters),
            "constraints": dict(request.constraints),
            "metadata": dict(request.metadata),
            "idempotency_key": effect_key,
            "actor_ref": "controller:control-plane",
            "resource_ref": resource,
            "subject_version_refs": list(request.subject_version_refs),
            "effect_class": request.effect_class,
            "principal": self.owner_principal,
            "resource": resource,
            "authorization_id": authorization_id,
        }
        prepared = self.runtime.post(
            "/v1/domain-effects/prepare",
            {
                "request": runtime_request,
                "provider_id": provider.descriptor.id,
                "provider_version": provider.descriptor.version,
            },
        )
        if prepared.get("status") == "committed":
            stored = prepared.get("result")
            if not isinstance(stored, dict):
                raise WorldRuntimeBoundaryError("committed effect is missing provider result")
            data = stored.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("capability_result"), dict):
                raise WorldRuntimeBoundaryError("committed effect lacks Control Plane replay data")
            return CapabilityResult.model_validate(data["capability_result"])
        if prepared.get("status") != "authorized":
            return CapabilityResult(
                request_id=request.id,
                provider_id=provider.descriptor.id,
                status="unknown",
                error={
                    "code": "RuntimeReconciliationRequired",
                    "message": "effect has already started and cannot be blindly redispatched",
                },
                metadata={
                    "runtime_effect_status": prepared.get("status"),
                    "runtime_effect_key": effect_key,
                },
            )

        started = self.runtime.post(f"/v1/domain-effects/{effect_key}/start", {})
        if started.get("dispatch_allowed") is not True:
            raise WorldRuntimeBoundaryError("Runtime did not grant provider dispatch")
        generation = int(started["dispatch_generation"])

        local_request = request.model_copy(
            update={
                "id": request_id,
                "idempotency_key": effect_key,
                "actor_ref": self.owner_principal,
                "resource_ref": resource,
            }
        )
        try:
            result = await self.providers.invoke(
                local_request,
                controller_id=None,
                work_id=work.id,
                run_id=request.run_id,
            )
        except Exception as exc:
            self.runtime.post(
                f"/v1/domain-effects/{effect_key}/result",
                {
                    "dispatch_generation": generation,
                    "result": {
                        "request_id": request_id,
                        "provider_id": provider.descriptor.id,
                        "status": "unknown",
                        "error": {
                            "type": type(exc).__name__,
                            "message": str(exc)[:500],
                        },
                    },
                },
            )
            raise

        local_value = result.model_dump(mode="json")
        runtime_result = {
            **local_value,
            "request_id": request_id,
            "provider_id": provider.descriptor.id,
            "data": {"capability_result": local_value},
        }
        self.runtime.post(
            f"/v1/domain-effects/{effect_key}/result",
            {
                "dispatch_generation": generation,
                "result": runtime_result,
            },
        )
        return result

    def record_capability_result(
        self,
        *,
        controller_id: str,
        work_id: str,
        run_id: str,
        stage: str,
        capability: str,
        result: CapabilityResult,
    ) -> DomainEvent:
        return self.journal.append(
            stream=f"controller:{controller_id}",
            kind=PERSONAL_RESULT_EVENT,
            payload={
                "work_ref": work_id,
                "run_ref": run_id,
                "stage": stage,
                "capability": capability,
                "result": result.model_dump(mode="json"),
            },
        )

    def result_events(
        self,
        controller_id: str,
        *,
        work_id: str | None = None,
    ) -> list[DomainEvent]:
        return [
            event
            for event in self.journal.events(stream=f"controller:{controller_id}")
            if event.kind == PERSONAL_RESULT_EVENT
            and (work_id is None or event.payload.get("work_ref") == work_id)
        ]

    def latest_result(self, controller_id: str) -> dict[str, Any] | None:
        events = self.result_events(controller_id)
        if events:
            raw = events[-1].payload.get("result")
            return dict(raw) if isinstance(raw, dict) else None
        values = [
            event
            for event in self.journal.events(stream=f"controller:{controller_id}")
            if event.kind == "control-plane.controller.capability-result"
        ]
        if not values:
            return None
        raw = values[-1].payload.get("result")
        return dict(raw) if isinstance(raw, dict) else None

    def latest_human_instruction_event(
        self,
        controller_id: str,
    ) -> DomainEvent | None:
        values = [
            event
            for event in self.journal.events(stream=f"controller:{controller_id}")
            if event.kind == PERSONAL_HUMAN_INSTRUCTION_EVENT
        ]
        return values[-1] if values else None

    def report_completion(self, state: ControllerState) -> None:
        work = self.work_for_state(state)
        if work is None:
            return
        result_events = self.result_events(state.id, work_id=work.id)
        if not result_events:
            return
        evidence_refs = [self._ref("evidence", f"evidence:{event.id}") for event in result_events]
        basis_refs = [
            self._ref("domain-event", event.id, namespace="control-plane")
            for event in result_events
        ]
        assignment_ref = self.assignment_ref(state.responsibility_ref)
        outcome_ref = self._ref(
            "outcome",
            f"controller-completed:{state.id}",
            namespace="control-plane",
        )
        self.runtime.post(
            f"/v1/domain-assignments/{assignment_ref}/reports",
            {
                "id": f"{assignment_ref}:outcome",
                "kind": "outcome-candidate",
                "basis_refs": basis_refs,
                "evidence_refs": evidence_refs,
                "outcome_refs": [outcome_ref],
            },
        )
        self.runtime.post(
            f"/v1/domain-assignments/{assignment_ref}/reports",
            {
                "id": f"{assignment_ref}:completion",
                "kind": "completion-proposal",
                "basis_refs": basis_refs,
                "evidence_refs": evidence_refs,
                "outcome_refs": [outcome_ref],
            },
        )
        evidence_ids = [ref["id"] for ref in evidence_refs]
        self.runtime.post(
            f"/v1/responsibilities/{state.responsibility_ref}/assess",
            {"status": "satisfied", "basis_refs": evidence_ids},
        )
        decision_id = f"control-plane-discharge:{state.responsibility_ref}"
        self.runtime.post(
            "/v1/decisions",
            {
                "id": decision_id,
                "subject": state.subject_ref,
                "decided_by": self.owner_principal,
                "selected": {
                    "target_ref": state.responsibility_ref,
                    "operation": "discharge-responsibility",
                    "to_status": "discharged",
                    "outcome_ref": outcome_ref["id"],
                    "controller_ref": state.id,
                },
                "basis_refs": evidence_ids,
            },
        )
        self.runtime.post(
            f"/v1/responsibilities/{state.responsibility_ref}/discharge",
            {"decision_id": decision_id},
        )
        self.update_work_status(work.id, "completed")


__all__ = [
    "PERSONAL_HUMAN_INSTRUCTION_EVENT",
    "PERSONAL_RESULT_EVENT",
    "DomainRun",
    "DomainWork",
    "PersonalResponsibilityContext",
    "PersonalRuntimeBridge",
    "WorldRuntimeBoundaryError",
    "WorldRuntimeClient",
]
