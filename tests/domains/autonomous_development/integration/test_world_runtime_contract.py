from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from world_runtime import WorldRuntime
from world_runtime.service import create_app

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

pytestmark = pytest.mark.integration


class TestClientTransport(httpx.BaseTransport):
    def __init__(self, client: TestClient) -> None:
        self.client = client

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = request.read()
        response = self.client.request(
            request.method,
            str(request.url),
            content=body,
            headers=dict(request.headers),
        )
        return httpx.Response(
            status_code=response.status_code,
            headers=dict(response.headers),
            content=response.content,
            request=request,
        )


def _policy() -> MutationPolicy:
    return MutationPolicy(allowed_paths=("src",), max_changed_files=3)


def _objective() -> ProductObjectiveRevision:
    return ProductObjectiveRevision(
        id="objective-runtime-1",
        target_id="target-runtime-1",
        statement="Improve checkout reliability.",
        acceptance_criteria=("checkout remains correct",),
        primary_metrics=("correctness",),
        reliability_constraints=("no availability regression",),
        performance_constraints=(),
        security_constraints=(),
        mutation_policy=_policy(),
        created_at=datetime.now(UTC),
    )


def _target() -> DevelopmentTarget:
    return DevelopmentTarget(
        id="target-runtime-1",
        repository="/repo",
        default_branch="main",
        target_contract_revision="contract-1",
        active_objective_revision_id="objective-runtime-1",
        mutation_policy=_policy(),
        current_release_id="release-runtime-0",
    )


def _baseline() -> ReleasedVersion:
    return ReleasedVersion(
        id="release-runtime-0",
        target_id="target-runtime-1",
        source_commit="a" * 40,
        source_tree="a" * 40,
        artifact_digest="sha256:" + "0" * 64,
        objective_revision_id="objective-runtime-1",
        deployment_id="deployment-runtime-0",
        promoted_at=datetime.now(UTC),
    )


def _window() -> EvidenceWindow:
    now = datetime.now(UTC)
    return EvidenceWindow(
        id="window-runtime-1",
        target_id="target-runtime-1",
        release_ids=("release-runtime-0",),
        opened_at=now,
        closed_at=now,
        telemetry_refs=("evidence:telemetry",),
    )


def _cycle() -> DevelopmentCycle:
    return DevelopmentCycle(
        id="cycle-runtime-1",
        target_id="target-runtime-1",
        objective_revision_id="objective-runtime-1",
        baseline_release_id="release-runtime-0",
        state=CycleState.PROMOTED,
        version=12,
        candidate_id="candidate-runtime-1",
        artifact_id="artifact-runtime-1",
        candidate_deployment_id="deployment-runtime-1",
        release_decision=ReleaseDecisionKind.PROMOTE,
    )


def _candidate() -> CandidateRevision:
    return CandidateRevision(
        id="candidate-runtime-1",
        cycle_id="cycle-runtime-1",
        worktree_path="/private/development/worktree",
        branch_name="autodev/cycle-runtime-1",
        base_commit="a" * 40,
        candidate_commit="b" * 40,
        tree_hash="c" * 40,
        changed_paths=("src/app.py",),
        codex_thread_id="thread-runtime-1",
        implementation_attempt=1,
    )


def _artifact() -> BuildArtifact:
    return BuildArtifact(
        id="artifact-runtime-1",
        candidate_id="candidate-runtime-1",
        image_digest="sha256:" + "d" * 64,
        source_tree_hash="c" * 40,
        build_definition_digest="sha256:" + "e" * 64,
        dependency_lock_digest="sha256:" + "f" * 64,
        build_evidence_ref="evidence:build",
        sbom_digest="sha256:" + "1" * 64,
        sbom_ref="evidence:sbom",
        vulnerability_scan_ref="evidence:scan",
    )


def _deployment() -> Deployment:
    return Deployment(
        id="deployment-runtime-1",
        target_id="target-runtime-1",
        artifact_id="artifact-runtime-1",
        environment="local-candidate",
        state=DeploymentState.SERVING,
        observed_at=datetime.now(UTC),
        observation_refs=("evidence:ready",),
    )


def _release() -> ReleasedVersion:
    return ReleasedVersion(
        id="release-runtime-1",
        target_id="target-runtime-1",
        source_commit="b" * 40,
        source_tree="c" * 40,
        artifact_digest="sha256:" + "d" * 64,
        objective_revision_id="objective-runtime-1",
        deployment_id="deployment-runtime-1",
        promoted_at=datetime.now(UTC),
    )


def test_development_controller_conforms_to_real_world_runtime_http_surface() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="runtime:development-contract")
    runtime.identity.bind_bearer_token(
        principal="controller:autonomous-development",
        token="development-runtime-token",
        credential_id="credential:autonomous-development",
    )
    app = create_app(runtime)

    with TestClient(app) as client:
        bridge = WorldRuntimeDevelopmentBridge(
            "http://testserver",
            transport=TestClientTransport(client),
            bearer_token="development-runtime-token",
        )
        bridge.ensure_contracts()
        bridge.ensure_assignment(
            cycle=_cycle(),
            target=_target(),
            objective=_objective(),
            baseline=_baseline(),
            evidence_window=_window(),
        )
        provider_calls = {"count": 0}

        def invoke_external() -> dict[str, object]:
            provider_calls["count"] += 1
            return {"external_ref": "development-operation:1"}

        first = bridge.execute_external_effect(
            target_id="target-runtime-1",
            capability="development.test.apply",
            resource="development:test:target-runtime-1",
            idempotency_key="development:runtime-effect:1",
            parameters={"mode": "apply"},
            subject_version_refs=["target:target-runtime-1:v1"],
            provider_id="development:test-provider",
            provider_version="1",
            invoke=invoke_external,
            encode=lambda value: dict(value),
            decode=lambda value: dict(value),
        )
        replay = bridge.execute_external_effect(
            target_id="target-runtime-1",
            capability="development.test.apply",
            resource="development:test:target-runtime-1",
            idempotency_key="development:runtime-effect:1",
            parameters={"mode": "apply"},
            subject_version_refs=["target:target-runtime-1:v1"],
            provider_id="development:test-provider",
            provider_version="1",
            invoke=invoke_external,
            encode=lambda value: dict(value),
            decode=lambda value: dict(value),
        )
        assert first == replay == {"external_ref": "development-operation:1"}
        assert provider_calls["count"] == 1
        runtime_effect = runtime.effect_boundary.get("development:runtime-effect:1")
        assert runtime_effect["status"] == "committed"
        assert runtime_effect["dispatch_allowed"] is False

        bridge.complete_promoted_release(
            cycle=_cycle(),
            candidate=_candidate(),
            artifact=_artifact(),
            deployment=_deployment(),
            release=_release(),
        )

    responsibility = runtime.responsibility.get("development:cycle-runtime-1")
    assert responsibility.domain == "development"
    assert responsibility.status == "discharged"

    assignment = runtime.domains.get("development-assignment:cycle-runtime-1")
    assert assignment.domain == "development"
    assert assignment.status == "completion-proposed"
    report_kinds = [item.kind for item in runtime.domains.reports(assignment.id)]
    assert report_kinds == ["accepted", "outcome-candidate", "completion-proposal"]

    works = runtime.list_work()
    assert len(works) == 2
    cycle_work = next(item for item in works if item.kind == "development-cycle")
    reality_work = next(item for item in works if item.kind == "development-reality-effect")
    assert cycle_work.id == "development-cycle-work:cycle-runtime-1"
    assert cycle_work.responsibility_id == responsibility.id
    assert reality_work.id == "work:development-reality:target-runtime-1"
    runs = runtime.list_runs(cycle_work.id)
    assert len(runs) == 1

    serialized_runtime_payload = json.dumps(
        {
            "responsibility": responsibility.scope,
            "work": cycle_work.payload,
            "reality_work": reality_work.payload,
        },
        sort_keys=True,
    )
    for forbidden in (
        "worktree_path",
        "branch_name",
        "changed_paths",
        "docker",
        "canary",
        "candidate_weight",
        "rollback",
    ):
        assert forbidden not in serialized_runtime_payload
