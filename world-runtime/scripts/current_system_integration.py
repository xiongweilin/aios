from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from world_runtime import WorldRuntime
from world_runtime.execution import (
    CapabilityRequest as RuntimeCapabilityRequest,
    CapabilityResult as RuntimeCapabilityResult,
    InvocationContext as RuntimeInvocationContext,
    ProviderDescriptor as RuntimeProviderDescriptor,
    ProviderHealth as RuntimeProviderHealth,
)
from world_runtime.identity import DelegationGrant
from world_runtime.service import create_app

from control_plane.domain_controller import PersonalController
from control_plane.domain_store import DomainJournal
from control_plane.provider_protocol import (
    CapabilityRequest as ControlPlaneCapabilityRequest,
)
from control_plane.provider_protocol import (
    CapabilityResult as ControlPlaneCapabilityResult,
)
from control_plane.provider_protocol import (
    InvocationContext as ControlPlaneInvocationContext,
)
from control_plane.provider_protocol import (
    ProviderDescriptor as ControlPlaneProviderDescriptor,
)
from control_plane.provider_protocol import (
    ProviderHealth as ControlPlaneProviderHealth,
)
from control_plane.provider_protocol import ProviderRegistry as ControlPlaneProviderRegistry
from control_plane.runtime_bridge import PersonalRuntimeBridge, WorldRuntimeClient

from administrative_orchestrator.config import Settings
from administrative_orchestrator.domain import (
    AuthorityClass,
    EffectRecord,
    EffectReversibility,
)
from administrative_orchestrator.effect_provider import ProviderExecutionStatus
from administrative_orchestrator.integrations.world_runtime import WorldRuntimeBridge
from administrative_orchestrator.persistence import SqlStore

from autonomous_development.adapters.world_runtime import WorldRuntimeDevelopmentBridge
from autonomous_development.domain.enums import (
    CycleState,
    DeploymentState,
    ReleaseDecisionKind,
)
from autonomous_development.domain.models import (
    BuildArtifact,
    CandidateRevision,
    Deployment,
    DevelopmentCycle,
    DevelopmentTarget,
    EvidenceWindow,
    MutationPolicy,
    ProductObjectiveRevision,
    ReleasedVersion,
)


APPROVED_MATRIX = {
    "semantic-language": "eb8c6cb1757256ea9961201bd66ea79952de6134",
    "control-plane": "475cc5b3bbc714e65d71f133f4dfa838b249d817",
    "administrative-orchestrator": "c44ca76daf6e2d9ecd4ab182d170176ff740babb",
    "autonomous-development": "7a738277d3bb0bc71a7e620bbfedda6ebd4d9dd9",
}


class TestClientTransport(httpx.BaseTransport):
    def __init__(self, client: TestClient) -> None:
        self.client = client

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self.client.request(
            request.method,
            str(request.url),
            content=request.read(),
            headers=dict(request.headers),
        )
        return httpx.Response(
            status_code=response.status_code,
            headers=dict(response.headers),
            content=response.content,
            request=request,
        )


class ControlPlaneRealityProvider:
    def __init__(self) -> None:
        self.calls = 0
        self._descriptor = ControlPlaneProviderDescriptor(
            id="current-system-control-plane-provider",
            name="Current System Control Plane Provider",
            version="1",
            capabilities=["notify.send"],
        )

    @property
    def descriptor(self) -> ControlPlaneProviderDescriptor:
        return self._descriptor

    async def health(self) -> ControlPlaneProviderHealth:
        return ControlPlaneProviderHealth(
            provider_id=self.descriptor.id,
            available=True,
        )

    async def invoke(
        self,
        request: ControlPlaneCapabilityRequest,
        context: ControlPlaneInvocationContext,
    ) -> ControlPlaneCapabilityResult:
        self.calls += 1
        if not context.work_id or not context.run_id:
            raise AssertionError(
                "Control Plane effect did not preserve Domain Work/Run binding"
            )
        return ControlPlaneCapabilityResult(
            request_id=request.id,
            provider_id=self.descriptor.id,
            status="succeeded",
            evidence_refs=[f"evidence:control-plane-effect:{self.calls}"],
            metadata={"provider_accepted": True, "delivery_confirmed": True},
        )


class AdministrativeProvider:
    def __init__(self) -> None:
        self.calls = 0
        self._descriptor = RuntimeProviderDescriptor(
            id="current-system-admin-provider",
            name="Current System Administrative Provider",
            version="1",
            capabilities=["administrative.hris.employee.create.v1"],
        )

    @property
    def descriptor(self) -> RuntimeProviderDescriptor:
        return self._descriptor

    async def health(self) -> RuntimeProviderHealth:
        return RuntimeProviderHealth(provider_id=self.descriptor.id, available=True)

    async def invoke(
        self,
        request: RuntimeCapabilityRequest,
        context: RuntimeInvocationContext,
    ) -> RuntimeCapabilityResult:
        self.calls += 1
        if not context.work_id or not context.run_id:
            raise AssertionError("Administrative effect did not preserve Runtime Work/Run binding")
        return RuntimeCapabilityResult(
            request_id=request.id,
            provider_id=self.descriptor.id,
            status="succeeded",
            external_operation_ref=f"administrative-operation:{self.calls}",
        )

    async def cancel(self, request_id: str) -> None:
        del request_id


def exercise_control_plane(runtime: WorldRuntime, transport: httpx.BaseTransport) -> None:
    journal = DomainJournal(":memory:")
    providers = ControlPlaneProviderRegistry()
    reality_provider = ControlPlaneRealityProvider()
    providers.register(reality_provider)
    client = WorldRuntimeClient(
        "http://runtime.test",
        transport=transport,
        bearer_token="control-plane-controller-token",
        delegation_id="delegation:current-system-control-plane",
    )
    controller = PersonalController(journal, providers)
    bridge = PersonalRuntimeBridge(
        client,
        controller,
        journal,
        providers,
        owner_principal="principal:current-system",
    )
    try:
        client.ensure_contracts()
        state, _ = bridge.begin(
            title="Current-system integration",
            description="Prove the Control Plane boundary against the approved Runtime.",
            kind="integration",
            project="world-runtime",
        )
        proposal_ref = "proposal:current-system-control-plane"
        journal.project_put(
            "work.proposal",
            proposal_ref,
            {
                "kind": "integration-check",
                "closure_ref": "closure:current-system",
                "requested_capabilities": [],
                "expected_result": "runtime boundary accepted",
            },
        )
        state = state.model_copy(update={"work_proposal_ref": proposal_ref})
        work = bridge.materialize_work(state)
        run = bridge.start_run(work.id, workflow_id="current-system")
        effect_key = "current-system:control-plane:notify:1"
        first_effect = asyncio.run(
            bridge.invoke_capability(
                work.id,
                "notify.send",
                run_id=run.id,
                instruction="Current-system reality-boundary proof",
                idempotency_key=effect_key,
            )
        )
        replay_effect = asyncio.run(
            bridge.invoke_capability(
                work.id,
                "notify.send",
                run_id=run.id,
                instruction="Current-system reality-boundary proof",
                idempotency_key=effect_key,
            )
        )
        assert first_effect.status == "succeeded"
        assert replay_effect.status == "succeeded"
        assert reality_provider.calls == 1
        control_effect = runtime.effect_boundary.get(effect_key)
        assert control_effect["status"] == "committed"
        assert control_effect["dispatch_allowed"] is False
        bridge.record_capability_result(
            controller_id=state.id,
            work_id=work.id,
            run_id=run.id,
            stage="verification",
            capability="integration.verify",
            result=ControlPlaneCapabilityResult(
                status="succeeded",
                evidence_refs=["evidence:current-system-control-plane"],
            ),
        )
        bridge.report_completion(state)
        responsibility = runtime.responsibility.get(state.responsibility_ref)
        assignment = runtime.domains.get(bridge.assignment_ref(state.responsibility_ref))
        assert responsibility.status == "discharged"
        assert assignment.status == "completion-proposed"
    finally:
        client.close()
        journal.close()


def exercise_administrative(runtime: WorldRuntime, transport: httpx.BaseTransport) -> None:
    provider = AdministrativeProvider()
    runtime.registry.register(provider)
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    bridge = WorldRuntimeBridge(
        store,
        Settings(
            _env_file=None,
            world_runtime_mode="cutover",
            world_runtime_base_url="http://runtime.test",
            world_runtime_principal="service:administrative-orchestrator",
            world_runtime_bearer_token="administrative-controller-token",
            world_runtime_delegation_id="delegation:current-system-administrative",
        ),
        transport=transport,
    )
    bridge._context = lambda effect: {
        "issuer_principal_id": "service:administrative-current-system",
        "expected_postcondition": {"active": True},
    }
    now = datetime.now(UTC)
    effect = EffectRecord(
        effect_id=uuid4(),
        case_id=uuid4(),
        case_version=1,
        authority_epoch=1,
        authorization_id=uuid4(),
        obligation_id=uuid4(),
        governance_basis_id=uuid4(),
        target_system="hris",
        operation="employee.create",
        subject_ref="employee:current-system",
        reversibility=EffectReversibility.CORRECTABLE,
        authority_class=AuthorityClass.EMPLOYMENT,
        created_at=now,
        updated_at=now,
    )
    try:
        bridge.ensure_contracts()
        result = bridge.execute_effect(effect, {"employee_ref": effect.subject_ref})
        replay = bridge.execute_effect(effect, {"employee_ref": effect.subject_ref})
        assert result.status is ProviderExecutionStatus.SUCCEEDED
        assert replay.status is ProviderExecutionStatus.SUCCEEDED
        assert provider.calls == 1
        admin_work = [
            work
            for work in runtime.list_work()
            if work.kind == "administrative-effect"
        ]
        assert len(admin_work) == 1
        responsibility = runtime.responsibility.get(admin_work[0].responsibility_id)
        assert responsibility.status == "active"
    finally:
        bridge.close()


def _development_fixture() -> tuple[
    DevelopmentCycle,
    DevelopmentTarget,
    ProductObjectiveRevision,
    ReleasedVersion,
    EvidenceWindow,
    CandidateRevision,
    BuildArtifact,
    Deployment,
    ReleasedVersion,
]:
    now = datetime.now(UTC)
    policy = MutationPolicy(allowed_paths=("src",), max_changed_files=3)
    objective = ProductObjectiveRevision(
        id="objective-current-system",
        target_id="target-current-system",
        statement="Improve checkout reliability.",
        acceptance_criteria=("checkout remains correct",),
        primary_metrics=("correctness",),
        reliability_constraints=("no availability regression",),
        performance_constraints=(),
        security_constraints=(),
        mutation_policy=policy,
        created_at=now,
    )
    target = DevelopmentTarget(
        id="target-current-system",
        repository="/repo",
        default_branch="main",
        target_contract_revision="contract-current-system",
        active_objective_revision_id=objective.id,
        mutation_policy=policy,
        current_release_id="release-current-system-0",
    )
    baseline = ReleasedVersion(
        id="release-current-system-0",
        target_id=target.id,
        source_commit="a" * 40,
        source_tree="a" * 40,
        artifact_digest="sha256:" + "0" * 64,
        objective_revision_id=objective.id,
        deployment_id="deployment-current-system-0",
        promoted_at=now,
    )
    window = EvidenceWindow(
        id="window-current-system",
        target_id=target.id,
        release_ids=(baseline.id,),
        opened_at=now,
        closed_at=now,
        telemetry_refs=("evidence:telemetry-current-system",),
    )
    cycle = DevelopmentCycle(
        id="cycle-current-system",
        target_id=target.id,
        objective_revision_id=objective.id,
        baseline_release_id=baseline.id,
        state=CycleState.PROMOTED,
        version=1,
        candidate_id="candidate-current-system",
        artifact_id="artifact-current-system",
        candidate_deployment_id="deployment-current-system-1",
        release_decision=ReleaseDecisionKind.PROMOTE,
    )
    candidate = CandidateRevision(
        id="candidate-current-system",
        cycle_id=cycle.id,
        worktree_path="/private/current-system/worktree",
        branch_name="autodev/current-system",
        base_commit="a" * 40,
        candidate_commit="b" * 40,
        tree_hash="c" * 40,
        changed_paths=("src/app.py",),
        codex_thread_id="thread-current-system",
        implementation_attempt=1,
    )
    artifact = BuildArtifact(
        id="artifact-current-system",
        candidate_id=candidate.id,
        image_digest="sha256:" + "d" * 64,
        source_tree_hash="c" * 40,
        build_definition_digest="sha256:" + "e" * 64,
        dependency_lock_digest="sha256:" + "f" * 64,
        build_evidence_ref="evidence:build-current-system",
        sbom_digest="sha256:" + "1" * 64,
        sbom_ref="evidence:sbom-current-system",
        vulnerability_scan_ref="evidence:scan-current-system",
    )
    deployment = Deployment(
        id="deployment-current-system-1",
        target_id=target.id,
        artifact_id=artifact.id,
        environment="local-candidate",
        state=DeploymentState.SERVING,
        observed_at=now,
        observation_refs=("evidence:ready-current-system",),
    )
    release = ReleasedVersion(
        id="release-current-system-1",
        target_id=target.id,
        source_commit="b" * 40,
        source_tree="c" * 40,
        artifact_digest="sha256:" + "d" * 64,
        objective_revision_id=objective.id,
        deployment_id=deployment.id,
        promoted_at=now,
    )
    return cycle, target, objective, baseline, window, candidate, artifact, deployment, release


def exercise_development(runtime: WorldRuntime, transport: httpx.BaseTransport) -> None:
    bridge = WorldRuntimeDevelopmentBridge(
        "http://runtime.test",
        transport=transport,
        bearer_token="development-controller-token",
    )
    cycle, target, objective, baseline, window, candidate, artifact, deployment, release = (
        _development_fixture()
    )
    bridge.ensure_contracts()
    bridge.ensure_assignment(
        cycle=cycle,
        target=target,
        objective=objective,
        baseline=baseline,
        evidence_window=window,
    )
    provider_calls = {"count": 0}

    def invoke_development_effect() -> dict[str, str]:
        provider_calls["count"] += 1
        return {"external_ref": "development-operation:1"}

    effect_key = "current-system:development:effect:1"
    first_effect = bridge.execute_external_effect(
        target_id=target.id,
        capability="development.test.apply",
        resource=f"development:test:{target.id}",
        idempotency_key=effect_key,
        parameters={"mode": "apply"},
        subject_version_refs=[f"target:{target.id}:v1"],
        provider_id="current-system-development-provider",
        provider_version="1",
        invoke=invoke_development_effect,
        encode=lambda value: dict(value),
        decode=lambda value: dict(value),
    )
    replay_effect = bridge.execute_external_effect(
        target_id=target.id,
        capability="development.test.apply",
        resource=f"development:test:{target.id}",
        idempotency_key=effect_key,
        parameters={"mode": "apply"},
        subject_version_refs=[f"target:{target.id}:v1"],
        provider_id="current-system-development-provider",
        provider_version="1",
        invoke=invoke_development_effect,
        encode=lambda value: dict(value),
        decode=lambda value: dict(value),
    )
    assert first_effect == replay_effect == {"external_ref": "development-operation:1"}
    assert provider_calls["count"] == 1
    development_effect = runtime.effect_boundary.get(effect_key)
    assert development_effect["status"] == "committed"
    assert development_effect["dispatch_allowed"] is False
    bridge.complete_promoted_release(
        cycle=cycle,
        candidate=candidate,
        artifact=artifact,
        deployment=deployment,
        release=release,
    )
    responsibility = runtime.responsibility.get(
        WorldRuntimeDevelopmentBridge.responsibility_ref(cycle.id)
    )
    assignment = runtime.domains.get(
        WorldRuntimeDevelopmentBridge.assignment_ref(cycle.id)
    )
    assert responsibility.status == "discharged"
    assert assignment.status == "completion-proposed"


def main() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="runtime:current-system-integration")

    runtime.identity.bind_bearer_token(
        principal="principal:current-system",
        token="current-system-owner-token",
        credential_id="credential:current-system-owner",
    )
    runtime.identity.bind_bearer_token(
        principal="controller:control-plane",
        token="control-plane-controller-token",
        credential_id="credential:current-system-control-plane",
    )
    control_owner = runtime.identity.authenticate_bearer(
        "Bearer current-system-owner-token"
    )
    runtime.identity.grant_delegation(
        DelegationGrant(
            id="delegation:current-system-control-plane",
            grantor="principal:current-system",
            grantee="controller:control-plane",
            scope={"resource": "*"},
            authority_ceiling={"operation": "*", "action": "*", "resource": "*"},
        ),
        context=control_owner,
    )

    runtime.identity.bind_bearer_token(
        principal="service:administrative-orchestrator",
        token="administrative-root-token",
        credential_id="credential:current-system-administrative-root",
    )
    runtime.identity.bind_bearer_token(
        principal="controller:administrative-orchestrator",
        token="administrative-controller-token",
        credential_id="credential:current-system-administrative-controller",
    )
    administrative_root = runtime.identity.authenticate_bearer(
        "Bearer administrative-root-token"
    )
    runtime.identity.grant_delegation(
        DelegationGrant(
            id="delegation:current-system-administrative",
            grantor="service:administrative-orchestrator",
            grantee="controller:administrative-orchestrator",
            scope={
                "case_id": "*",
                "authority_epoch": "*",
                "obligation_id": "*",
            },
            authority_ceiling={"operation": "*", "action": "*", "resource": "*"},
        ),
        context=administrative_root,
    )

    runtime.identity.bind_bearer_token(
        principal="controller:autonomous-development",
        token="development-controller-token",
        credential_id="credential:current-system-development",
    )

    app = create_app(runtime)
    with TestClient(app) as client:
        transport = TestClientTransport(client)
        catalog = client.get("/v1/contracts").json()
        assert catalog["runtime_protocol"] == "4.0"
        assert catalog["semantic_language"] == "0.2.0"
        assert catalog["contracts"]["request_authentication"]["current"] == "request-authentication-v2"
        assert catalog["contracts"]["decision_record"]["current"] == "decision-record-v4"
        assert catalog["contracts"]["work_admission"]["current"] == "work-admission-v4"
        assert (
            catalog["contracts"]["domain_effect_execution"]["current"]
            == "domain-effect-execution-v3"
        )
        assert catalog["contracts"]["capability_invocation"]["current"] == "capability-invocation-v6"
        exercise_control_plane(runtime, transport)
        exercise_administrative(runtime, transport)
        exercise_development(runtime, transport)
    runtime.close()
    print("current-system-integration PASS")
    for repo, sha in APPROVED_MATRIX.items():
        print(f"{repo} {sha}")


if __name__ == "__main__":
    main()