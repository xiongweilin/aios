from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from autonomous_development.adapters.runtime_bound import (
    RuntimeBoundDeploymentProvider,
    RuntimeBoundRepositoryProvider,
    RuntimeBoundTrafficDirector,
)
from autonomous_development.adapters.world_runtime import WorldRuntimeDevelopmentBridge
from autonomous_development.ports.deployment import DeploymentRuntime, DeploymentSpec
from autonomous_development.ports.repository import (
    CandidateCommit,
    RepositoryBaseline,
    Worktree,
)
from autonomous_development.ports.traffic import (
    TrafficRouteSnapshot,
    TrafficRouteState,
    TrafficSplit,
)


class RecordingBridge:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def execute_external_effect(self, **kwargs: Any) -> Any:
        self.calls.append(dict(kwargs))
        return kwargs["invoke"]()


class FakeDeployment:
    def __init__(self) -> None:
        self.ensure_calls = 0
        self.stop_calls: list[str] = []

    def ensure(self, spec: DeploymentSpec) -> DeploymentRuntime:
        self.ensure_calls += 1
        return DeploymentRuntime(
            deployment_id=spec.deployment_id,
            container_id="container-1",
            base_url="http://127.0.0.1:18000",
            evidence_ref="evidence:deployment",
        )

    def stop(self, deployment_id: str) -> None:
        self.stop_calls.append(deployment_id)


class FakeTraffic:
    def __init__(self) -> None:
        self.apply_calls = 0
        self.restore_calls = 0
        self.snapshot = TrafficRouteSnapshot(
            experiment_id="experiment-1",
            stage_index=0,
            control_base_url="http://control",
            candidate_base_url="http://candidate",
            candidate_weight_percent=10,
            operation_id="operation-read",
            generation=1,
            evidence_ref="evidence:traffic-read",
            target_id="target-1",
            control_release_id="release-0",
            candidate_deployment_id="deployment-1",
        )

    def read_current(self) -> TrafficRouteSnapshot | None:
        return self.snapshot

    def apply(self, split: TrafficSplit) -> TrafficRouteState:
        self.apply_calls += 1
        return TrafficRouteState(
            experiment_id=split.experiment_id,
            stage_index=split.stage_index,
            candidate_weight_percent=split.candidate_weight_percent,
            generation=self.apply_calls,
            evidence_ref=f"evidence:traffic:{self.apply_calls}",
            target_id=split.target_id,
            control_release_id=split.control_release_id,
            candidate_deployment_id=split.candidate_deployment_id,
        )

    def restore_control(
        self,
        *,
        experiment_id: str,
        stage_index: int,
        control_base_url: str,
        candidate_base_url: str,
        operation_id: str,
    ) -> TrafficRouteState:
        del control_base_url, candidate_base_url, operation_id
        self.restore_calls += 1
        return TrafficRouteState(
            experiment_id=experiment_id,
            stage_index=stage_index,
            candidate_weight_percent=0,
            generation=10 + self.restore_calls,
            evidence_ref="evidence:traffic-restore",
        )


class FakeRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.promote_calls = 0
        self.restore_calls = 0
        self.internal_calls: list[str] = []

    def verify_baseline(self, repository_root: Path, default_branch: str) -> RepositoryBaseline:
        self.internal_calls.append("verify")
        return RepositoryBaseline(repository_root, "a" * 40, "b" * 40, default_branch)

    def create_worktree(
        self,
        baseline: RepositoryBaseline,
        *,
        cycle_id: str,
        worktree_root: Path,
    ) -> Worktree:
        del baseline, cycle_id
        self.internal_calls.append("create-worktree")
        return Worktree(worktree_root.resolve(), "autodev/cycle", "a" * 40)

    def changed_paths(self, worktree: Worktree) -> tuple[str, ...]:
        del worktree
        self.internal_calls.append("changed-paths")
        return ("src/app.py",)

    def recover_candidate(
        self,
        worktree: Worktree,
        *,
        expected_message: str,
    ) -> CandidateCommit | None:
        del worktree, expected_message
        self.internal_calls.append("recover")
        return None

    def commit_candidate(
        self,
        worktree: Worktree,
        *,
        message: str,
        codex_thread_id: str,
    ) -> CandidateCommit:
        del worktree, message
        self.internal_calls.append("commit")
        return CandidateCommit("c" * 40, "d" * 40, ("src/app.py",), codex_thread_id)

    def promote_candidate(
        self,
        repository_root: Path,
        default_branch: str,
        *,
        baseline_commit: str,
        candidate_commit: str,
        candidate_tree: str,
    ) -> CandidateCommit:
        del repository_root, default_branch, baseline_commit
        self.promote_calls += 1
        return CandidateCommit(candidate_commit, candidate_tree, ("src/app.py",), None)

    def restore_baseline(
        self,
        repository_root: Path,
        default_branch: str,
        *,
        baseline_commit: str,
    ) -> RepositoryBaseline:
        self.restore_calls += 1
        return RepositoryBaseline(repository_root, baseline_commit, "b" * 40, default_branch)

    def remove_worktree(self, baseline: RepositoryBaseline, worktree: Worktree) -> None:
        del baseline, worktree
        self.internal_calls.append("remove-worktree")

    def cleanup_cycle(
        self,
        repository_root: Path,
        *,
        cycle_id: str,
        worktree_root: Path,
    ) -> None:
        del repository_root, cycle_id, worktree_root
        self.internal_calls.append("cleanup")


def _bridge(recording: RecordingBridge) -> WorldRuntimeDevelopmentBridge:
    return cast(WorldRuntimeDevelopmentBridge, recording)


def test_deployment_wrapper_routes_mutations_through_runtime() -> None:
    recording = RecordingBridge()
    inner = FakeDeployment()
    wrapper = RuntimeBoundDeploymentProvider(
        _bridge(recording),
        inner,
        target_id="target-1",
    )
    spec = DeploymentSpec(
        deployment_id="deployment-1",
        target_id="target-1",
        artifact_id="artifact-1",
        image_digest="sha256:" + "a" * 64,
        container_port=8000,
    )

    runtime = wrapper.ensure(spec)
    wrapper.stop("deployment-1")

    assert runtime.deployment_id == "deployment-1"
    assert inner.ensure_calls == 1
    assert inner.stop_calls == ["deployment-1"]
    assert [item["capability"] for item in recording.calls] == [
        "development.deploy.ensure",
        "development.deploy.stop",
    ]
    assert recording.calls[0]["evidence_refs"](runtime) == ["evidence:deployment"]

    wrong = replace(spec, target_id="target-2")
    try:
        wrapper.ensure(wrong)
    except ValueError as exc:
        assert "target differs" in str(exc)
    else:
        raise AssertionError("foreign deployment target must be rejected")


def test_traffic_wrapper_keeps_reads_local_and_routes_writes() -> None:
    recording = RecordingBridge()
    inner = FakeTraffic()
    wrapper = RuntimeBoundTrafficDirector(
        _bridge(recording),
        inner,
        target_id="target-1",
    )

    assert wrapper.read_current() is inner.snapshot
    assert recording.calls == []

    split = TrafficSplit(
        experiment_id="experiment-1",
        stage_index=1,
        control_base_url="http://control",
        candidate_base_url="http://candidate",
        candidate_weight_percent=25,
        operation_id="traffic-op-1",
        target_id="target-1",
        control_release_id="release-0",
        candidate_deployment_id="deployment-1",
    )
    applied = wrapper.apply(split)
    restored = wrapper.restore_control(
        experiment_id="experiment-1",
        stage_index=2,
        control_base_url="http://control",
        candidate_base_url="http://candidate",
        operation_id="traffic-op-2",
    )

    assert applied.candidate_weight_percent == 25
    assert restored.candidate_weight_percent == 0
    assert [item["capability"] for item in recording.calls] == [
        "development.traffic.apply",
        "development.traffic.restore",
    ]
    assert inner.apply_calls == 1
    assert inner.restore_calls == 1

    foreign = replace(split, target_id="target-2", operation_id="foreign")
    try:
        wrapper.apply(foreign)
    except ValueError as exc:
        assert "target differs" in str(exc)
    else:
        raise AssertionError("foreign traffic target must be rejected")


def test_repository_wrapper_only_routes_source_promotion_and_restore(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    recording = RecordingBridge()
    inner = FakeRepository(root)
    wrapper = RuntimeBoundRepositoryProvider(
        _bridge(recording),
        inner,
        target_id="target-1",
    )

    baseline = wrapper.verify_baseline(root, "main")
    worktree = wrapper.create_worktree(
        baseline,
        cycle_id="cycle-1",
        worktree_root=(tmp_path / "worktree").resolve(),
    )
    assert wrapper.changed_paths(worktree) == ("src/app.py",)
    assert wrapper.recover_candidate(worktree, expected_message="expected") is None
    committed = wrapper.commit_candidate(
        worktree,
        message="candidate",
        codex_thread_id="thread-1",
    )
    wrapper.remove_worktree(baseline, worktree)
    wrapper.cleanup_cycle(root, cycle_id="cycle-1", worktree_root=tmp_path)

    assert committed.codex_thread_id == "thread-1"
    assert recording.calls == []

    promoted = wrapper.promote_candidate(
        root,
        "main",
        baseline_commit="a" * 40,
        candidate_commit="c" * 40,
        candidate_tree="d" * 40,
    )
    restored = wrapper.restore_baseline(
        root,
        "main",
        baseline_commit="a" * 40,
    )

    assert promoted.commit == "c" * 40
    assert restored.commit == "a" * 40
    assert inner.promote_calls == 1
    assert inner.restore_calls == 1
    assert [item["capability"] for item in recording.calls] == [
        "development.source.promote",
        "development.source.restore",
    ]
    assert inner.internal_calls == [
        "verify",
        "create-worktree",
        "changed-paths",
        "recover",
        "commit",
        "remove-worktree",
        "cleanup",
    ]
