from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx

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


def _policy() -> MutationPolicy:
    return MutationPolicy(allowed_paths=("src",), max_changed_files=3)


def _objective() -> ProductObjectiveRevision:
    return ProductObjectiveRevision(
        id="objective-1",
        target_id="target-1",
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
        id="target-1",
        repository="/repo",
        default_branch="main",
        target_contract_revision="contract-1",
        active_objective_revision_id="objective-1",
        mutation_policy=_policy(),
        current_release_id="release-0",
    )


def _baseline() -> ReleasedVersion:
    return ReleasedVersion(
        id="release-0",
        target_id="target-1",
        source_commit="a" * 40,
        source_tree="a" * 40,
        artifact_digest="sha256:" + "0" * 64,
        objective_revision_id="objective-1",
        deployment_id="deployment-0",
        promoted_at=datetime.now(UTC),
    )


def _window() -> EvidenceWindow:
    now = datetime.now(UTC)
    return EvidenceWindow(
        id="window-1",
        target_id="target-1",
        release_ids=("release-0",),
        opened_at=now,
        closed_at=now,
        telemetry_refs=("evidence:telemetry",),
    )


def _cycle() -> DevelopmentCycle:
    return DevelopmentCycle(
        id="cycle-1",
        target_id="target-1",
        objective_revision_id="objective-1",
        baseline_release_id="release-0",
        state=CycleState.PROMOTED,
        version=12,
        candidate_id="candidate-1",
        artifact_id="artifact-1",
        candidate_deployment_id="deployment-1",
        release_decision=ReleaseDecisionKind.PROMOTE,
    )


def _candidate() -> CandidateRevision:
    return CandidateRevision(
        id="candidate-1",
        cycle_id="cycle-1",
        worktree_path="/private/domain/worktree",
        branch_name="autodev/cycle-1",
        base_commit="a" * 40,
        candidate_commit="b" * 40,
        tree_hash="c" * 40,
        changed_paths=("src/app.py",),
        codex_thread_id="thread-1",
        implementation_attempt=1,
    )


def _artifact() -> BuildArtifact:
    return BuildArtifact(
        id="artifact-1",
        candidate_id="candidate-1",
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
        id="deployment-1",
        target_id="target-1",
        artifact_id="artifact-1",
        environment="local-candidate",
        state=DeploymentState.SERVING,
        observed_at=datetime.now(UTC),
        observation_refs=("evidence:ready",),
    )


def _release() -> ReleasedVersion:
    return ReleasedVersion(
        id="release-1",
        target_id="target-1",
        source_commit="b" * 40,
        source_tree="c" * 40,
        artifact_digest="sha256:" + "d" * 64,
        objective_revision_id="objective-1",
        deployment_id="deployment-1",
        promoted_at=datetime.now(UTC),
    )


def test_world_runtime_bridge_keeps_development_semantics_outside_runtime() -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    responsibility_status = {"value": "active"}
    effects: dict[str, dict[str, object]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content or b"{}")
        calls.append((request.url.path, payload))
        path = request.url.path
        if request.method == "GET" and path == "/v1/contracts":
            return httpx.Response(
                200,
                json={
                    "runtime_protocol": WorldRuntimeDevelopmentBridge.REQUIRED_RUNTIME_PROTOCOL,
                    "semantic_language": WorldRuntimeDevelopmentBridge.REQUIRED_SEMANTIC_LANGUAGE,
                    "contracts": {
                        name: {"current": current}
                        for name, current in (
                            WorldRuntimeDevelopmentBridge.REQUIRED_CONTRACTS.items()
                        )
                    },
                },
            )
        if request.method == "GET" and path == "/v1/responsibilities/development:cycle-1":
            return httpx.Response(
                200,
                json={"id": "development:cycle-1", "status": responsibility_status["value"]},
            )
        if path == "/v1/responsibilities":
            return httpx.Response(200, json={"id": payload["id"], "status": "active"})
        if path == "/v1/mandates":
            return httpx.Response(200, json={"id": payload["id"], "status": "active"})
        if path == "/v1/authorizations":
            return httpx.Response(200, json={"id": payload["id"]})
        if path == "/v1/domain-effects/prepare":
            request_payload = dict(payload["request"])
            key = str(request_payload["idempotency_key"])
            current = effects.get(key)
            if current is None:
                current = {
                    "grant_id": "effect-grant:1",
                    "idempotency_key": key,
                    "request_id": request_payload["id"],
                    "provider_id": payload["provider_id"],
                    "provider_version": payload["provider_version"],
                    "status": "authorized",
                    "dispatch_generation": 0,
                    "start_allowed": True,
                    "dispatch_allowed": False,
                    "result": None,
                }
                effects[key] = current
            return httpx.Response(200, json=current)
        if path.startswith("/v1/domain-effects/") and path.endswith("/start"):
            key = path.split("/")[3]
            current = effects[key]
            if current["status"] != "authorized":
                return httpx.Response(409, json={"detail": "already started"})
            current["status"] = "started"
            current["dispatch_generation"] = 1
            current["start_allowed"] = False
            return httpx.Response(200, json={**current, "dispatch_allowed": True})
        if path.startswith("/v1/domain-effects/") and path.endswith("/result"):
            key = path.split("/")[3]
            current = effects[key]
            result = dict(payload["result"])
            current["status"] = "committed"
            current["start_allowed"] = False
            current["dispatch_allowed"] = False
            current["result"] = result
            return httpx.Response(200, json=result)
        if path == "/v1/domain-assignments":
            return httpx.Response(
                200,
                json={"id": payload["id"], "status": "offered"},
            )
        if path.startswith("/v1/domain-assignments/") and path.endswith("/reports"):
            status = (
                "completion-proposed"
                if payload.get("kind") == "completion-proposal"
                else "active"
            )
            return httpx.Response(
                200,
                json={
                    "id": payload.get("id"),
                    "kind": payload.get("kind"),
                    "assignment_status": status,
                },
            )
        if path == "/v1/work":
            return httpx.Response(200, json={"id": "work-1", "status": "pending"})
        if path == "/v1/runs":
            return httpx.Response(200, json={"id": "run-1", "status": "running"})
        if path.endswith("/assess"):
            responsibility_status["value"] = "satisfied"
            return httpx.Response(
                200,
                json={
                    "status": "satisfied",
                    "assessment_ref": "assessment-1",
                },
            )
        if path == "/v1/decisions":
            return httpx.Response(200, json={"id": payload["id"]})
        if path.endswith("/discharge"):
            responsibility_status["value"] = "discharged"
            return httpx.Response(
                200,
                json={
                    "status": "discharged",
                    "transition_ref": "transition-1",
                },
            )
        return httpx.Response(404)

    bridge = WorldRuntimeDevelopmentBridge(
        "http://runtime.test",
        transport=httpx.MockTransport(handler),
    )
    bridge.ensure_contracts()
    bridge.ensure_assignment(
        cycle=_cycle(),
        target=_target(),
        objective=_objective(),
        baseline=_baseline(),
        evidence_window=_window(),
    )
    bridge.complete_promoted_release(
        cycle=_cycle(),
        candidate=_candidate(),
        artifact=_artifact(),
        deployment=_deployment(),
        release=_release(),
    )

    provider_calls = {"count": 0}

    def invoke_domain_effect() -> dict[str, object]:
        provider_calls["count"] += 1
        return {"receipt": "development-effect-1"}

    first_effect = bridge.execute_external_effect(
        target_id="target-1",
        capability="development.test.apply",
        resource="development:test:target-1",
        idempotency_key="development:test-effect:1",
        parameters={"mode": "apply"},
        subject_version_refs=["target:target-1:v1"],
        provider_id="development:test-provider",
        provider_version="1",
        invoke=invoke_domain_effect,
        encode=lambda value: dict(value),
        decode=lambda value: dict(value),
    )
    replay_effect = bridge.execute_external_effect(
        target_id="target-1",
        capability="development.test.apply",
        resource="development:test:target-1",
        idempotency_key="development:test-effect:1",
        parameters={"mode": "apply"},
        subject_version_refs=["target:target-1:v1"],
        provider_id="development:test-provider",
        provider_version="1",
        invoke=invoke_domain_effect,
        encode=lambda value: dict(value),
        decode=lambda value: dict(value),
    )
    assert first_effect == {"receipt": "development-effect-1"}
    assert replay_effect == first_effect
    assert provider_calls["count"] == 1
    bridge.complete_promoted_release(
        cycle=_cycle(),
        candidate=_candidate(),
        artifact=_artifact(),
        deployment=_deployment(),
        release=_release(),
    )

    paths = [path for path, _ in calls]
    assert paths.count("/v1/responsibilities") == 3
    assert paths.count("/v1/domain-assignments") == 1
    assert paths.count("/v1/domain-assignments/development-assignment:cycle-1/reports") == 3
    assert paths.count("/v1/work") == 3
    assert paths.count("/v1/runs") == 1
    assert paths.count("/v1/decisions") == 3

    domain_reports = [
        payload
        for path, payload in calls
        if path == "/v1/domain-assignments/development-assignment:cycle-1/reports"
    ]
    outcome = next(item for item in domain_reports if item["kind"] == "outcome-candidate")
    assert all(ref["kind"] == "evidence" for ref in outcome["evidence_refs"])
    assert {ref["kind"] for ref in outcome["basis_refs"]} == {
        "development-cycle",
        "candidate",
        "artifact",
        "deployment",
        "release",
    }
    assert outcome["outcome_refs"] == [
        {
            "kind": "outcome",
            "id": "release-1",
            "namespace": "development",
            "version": "0.1",
        }
    ]
    assert paths.count("/v1/responsibilities/development:cycle-1/assess") == 1
    assert paths.count("/v1/responsibilities/development:cycle-1/discharge") == 1
    assert paths.count("/v1/mandates") == 2
    assert paths.count("/v1/authorizations") == 2
    assert paths.count("/v1/domain-effects/prepare") == 2
    assert paths.count("/v1/domain-effects/development:test-effect:1/start") == 1
    assert paths.count("/v1/domain-effects/development:test-effect:1/result") == 1

    reality_responsibilities = [
        payload
        for path, payload in calls
        if path == "/v1/responsibilities"
        and str(payload.get("id", "")).startswith("responsibility:development-reality:")
    ]
    assert len(reality_responsibilities) == 2
    assert all(item["scope"]["kind"] == "reality-effects" for item in reality_responsibilities)

    serialized = json.dumps(calls, sort_keys=True)
    for forbidden in (
        "worktree_path",
        "branch_name",
        "changed_paths",
        "docker",
        "canary",
        "candidate_weight",
    ):
        assert forbidden not in serialized
    assert "development.release.promoted" in serialized


def test_world_runtime_contract_handshake_fails_closed_on_version_drift() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/contracts":
            return httpx.Response(
                200,
                json={
                    "runtime_protocol": "1.1",
                    "semantic_language": "0.2.0",
                    "contracts": {},
                },
            )
        return httpx.Response(404)

    bridge = WorldRuntimeDevelopmentBridge(
        "http://runtime.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        bridge.ensure_contracts()
    except Exception as exc:
        assert "protocol is incompatible" in str(exc)
    else:
        raise AssertionError("runtime protocol drift must fail closed")


def test_world_runtime_contract_handshake_requires_exact_contract_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/contracts":
            contracts = {
                name: {"current": current}
                for name, current in WorldRuntimeDevelopmentBridge.REQUIRED_CONTRACTS.items()
            }
            contracts["domain_report"] = {"current": "domain-report-v1"}
            return httpx.Response(
                200,
                json={
                    "runtime_protocol": WorldRuntimeDevelopmentBridge.REQUIRED_RUNTIME_PROTOCOL,
                    "semantic_language": "0.2.0",
                    "contracts": contracts,
                },
            )
        return httpx.Response(404)

    bridge = WorldRuntimeDevelopmentBridge(
        "http://runtime.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        bridge.ensure_contracts()
    except Exception as exc:
        assert "contract mismatch for domain_report" in str(exc)
    else:
        raise AssertionError("contract identity drift must fail closed")


def test_requirement_driven_assignment_omits_the_evidence_window_reference() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content or b"{}")
        calls.append((request.url.path, payload))
        path = request.url.path
        if path == "/v1/responsibilities":
            return httpx.Response(200, json={"id": payload["id"], "status": "active"})
        if path == "/v1/domain-assignments":
            return httpx.Response(200, json={"id": payload["id"], "status": "offered"})
        if path.startswith("/v1/domain-assignments/") and path.endswith("/reports"):
            return httpx.Response(
                200,
                json={
                    "id": payload.get("id"),
                    "kind": payload.get("kind"),
                    "assignment_status": "active",
                },
            )
        if path == "/v1/work":
            return httpx.Response(200, json={"id": payload["id"], "status": "pending"})
        if path == "/v1/runs":
            return httpx.Response(200, json={"id": "run-1", "status": "running"})
        return httpx.Response(404)

    bridge = WorldRuntimeDevelopmentBridge(
        "http://runtime.test",
        transport=httpx.MockTransport(handler),
    )

    # A requirement-driven cycle has no product evidence window yet.
    bridge.ensure_assignment(
        cycle=_cycle(),
        target=_target(),
        objective=_objective(),
        baseline=_baseline(),
    )
    assignment = next(payload for path, payload in calls if path == "/v1/domain-assignments")
    requirements = assignment["evidence_requirements"]
    assert isinstance(requirements, list)
    assert "evidence_window_ref" not in requirements[0]
    work = next(payload for path, payload in calls if path == "/v1/work")
    payload = work["payload"]
    assert isinstance(payload, dict)
    assert "evidence_window_ref" not in payload

    # An evidence-driven cycle still carries the immutable window reference.
    calls.clear()
    window = _window()
    bridge.ensure_assignment(
        cycle=_cycle(),
        target=_target(),
        objective=_objective(),
        baseline=_baseline(),
        evidence_window=window,
    )
    assignment = next(payload for path, payload in calls if path == "/v1/domain-assignments")
    requirements = assignment["evidence_requirements"]
    assert isinstance(requirements, list)
    first = requirements[0]
    assert isinstance(first, dict)
    assert first["evidence_window_ref"] == window.id
