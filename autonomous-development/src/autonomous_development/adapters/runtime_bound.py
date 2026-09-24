from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from autonomous_development.adapters.world_runtime import WorldRuntimeDevelopmentBridge
from autonomous_development.ports.deployment import (
    DeploymentProvider,
    DeploymentRuntime,
    DeploymentSpec,
)
from autonomous_development.ports.repository import (
    CandidateCommit,
    RepositoryBaseline,
    RepositoryProvider,
    Worktree,
)
from autonomous_development.ports.traffic import (
    TrafficDirector,
    TrafficRouteSnapshot,
    TrafficRouteState,
    TrafficSplit,
)


class RuntimeBoundDeploymentProvider:
    def __init__(
        self,
        bridge: WorldRuntimeDevelopmentBridge,
        inner: DeploymentProvider,
        *,
        target_id: str,
    ) -> None:
        self.bridge = bridge
        self.inner = inner
        self.target_id = target_id

    def ensure(self, spec: DeploymentSpec) -> DeploymentRuntime:
        if spec.target_id != self.target_id:
            raise ValueError("deployment target differs from Runtime-bound target")
        key = f"development:deploy:ensure:{spec.deployment_id}:{spec.image_digest}"
        return self.bridge.execute_external_effect(
            target_id=self.target_id,
            capability="development.deploy.ensure",
            resource=f"deployment:{spec.deployment_id}",
            idempotency_key=key,
            parameters=asdict(spec),
            subject_version_refs=[
                f"artifact:{spec.artifact_id}",
                f"image:{spec.image_digest}",
            ],
            provider_id="development:docker-deployment",
            provider_version="1",
            invoke=lambda: self.inner.ensure(spec),
            encode=lambda value: asdict(value),
            decode=lambda value: DeploymentRuntime(**value),
            evidence_refs=lambda value: [value.evidence_ref],
        )

    def stop(self, deployment_id: str) -> None:
        self.bridge.execute_external_effect(
            target_id=self.target_id,
            capability="development.deploy.stop",
            resource=f"deployment:{deployment_id}",
            idempotency_key=f"development:deploy:stop:{deployment_id}",
            parameters={"deployment_id": deployment_id},
            subject_version_refs=[f"deployment:{deployment_id}"],
            provider_id="development:docker-deployment",
            provider_version="1",
            invoke=lambda: self.inner.stop(deployment_id),
            encode=lambda _value: {"stopped": True},
            decode=lambda _value: None,
        )


class RuntimeBoundTrafficDirector:
    def __init__(
        self,
        bridge: WorldRuntimeDevelopmentBridge,
        inner: TrafficDirector,
        *,
        target_id: str,
    ) -> None:
        self.bridge = bridge
        self.inner = inner
        self.target_id = target_id

    def read_current(self) -> TrafficRouteSnapshot | None:
        return self.inner.read_current()

    def apply(self, split: TrafficSplit) -> TrafficRouteState:
        if split.target_id is not None and split.target_id != self.target_id:
            raise ValueError("traffic target differs from Runtime-bound target")
        refs = [
            value
            for value in (
                f"release:{split.control_release_id}" if split.control_release_id else None,
                (
                    f"deployment:{split.candidate_deployment_id}"
                    if split.candidate_deployment_id
                    else None
                ),
            )
            if value is not None
        ]
        return self.bridge.execute_external_effect(
            target_id=self.target_id,
            capability="development.traffic.apply",
            resource=f"traffic:{self.target_id}",
            idempotency_key=f"development:traffic:apply:{split.operation_id}",
            parameters=asdict(split),
            subject_version_refs=refs,
            provider_id="development:traffic-director",
            provider_version="1",
            invoke=lambda: self.inner.apply(split),
            encode=lambda value: asdict(value),
            decode=lambda value: TrafficRouteState(**value),
            evidence_refs=lambda value: [value.evidence_ref],
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
        parameters = {
            "experiment_id": experiment_id,
            "stage_index": stage_index,
            "control_base_url": control_base_url,
            "candidate_base_url": candidate_base_url,
            "operation_id": operation_id,
        }
        return self.bridge.execute_external_effect(
            target_id=self.target_id,
            capability="development.traffic.restore",
            resource=f"traffic:{self.target_id}",
            idempotency_key=f"development:traffic:restore:{operation_id}",
            parameters=parameters,
            subject_version_refs=[f"experiment:{experiment_id}"],
            provider_id="development:traffic-director",
            provider_version="1",
            invoke=lambda: self.inner.restore_control(
                experiment_id=experiment_id,
                stage_index=stage_index,
                control_base_url=control_base_url,
                candidate_base_url=candidate_base_url,
                operation_id=operation_id,
            ),
            encode=lambda value: asdict(value),
            decode=lambda value: TrafficRouteState(**value),
            evidence_refs=lambda value: [value.evidence_ref],
        )


class RuntimeBoundRepositoryProvider:
    def __init__(
        self,
        bridge: WorldRuntimeDevelopmentBridge,
        inner: RepositoryProvider,
        *,
        target_id: str,
    ) -> None:
        self.bridge = bridge
        self.inner = inner
        self.target_id = target_id

    def verify_baseline(self, repository_root: Path, default_branch: str) -> RepositoryBaseline:
        return self.inner.verify_baseline(repository_root, default_branch)

    def create_worktree(
        self,
        baseline: RepositoryBaseline,
        *,
        cycle_id: str,
        worktree_root: Path,
    ) -> Worktree:
        return self.inner.create_worktree(
            baseline,
            cycle_id=cycle_id,
            worktree_root=worktree_root,
        )

    def changed_paths(self, worktree: Worktree) -> tuple[str, ...]:
        return self.inner.changed_paths(worktree)

    def recover_candidate(
        self,
        worktree: Worktree,
        *,
        expected_message: str,
    ) -> CandidateCommit | None:
        return self.inner.recover_candidate(worktree, expected_message=expected_message)

    def commit_candidate(
        self,
        worktree: Worktree,
        *,
        message: str,
        codex_thread_id: str,
    ) -> CandidateCommit:
        return self.inner.commit_candidate(
            worktree,
            message=message,
            codex_thread_id=codex_thread_id,
        )

    def promote_candidate(
        self,
        repository_root: Path,
        default_branch: str,
        *,
        baseline_commit: str,
        candidate_commit: str,
        candidate_tree: str,
    ) -> CandidateCommit:
        parameters = {
            "default_branch": default_branch,
            "baseline_commit": baseline_commit,
            "candidate_commit": candidate_commit,
            "candidate_tree": candidate_tree,
        }
        return self.bridge.execute_external_effect(
            target_id=self.target_id,
            capability="development.source.promote",
            resource=f"development-repository:{self.target_id}:{default_branch}",
            idempotency_key=(
                f"development:source:promote:{self.target_id}:"
                f"{baseline_commit}:{candidate_commit}:{candidate_tree}"
            ),
            parameters=parameters,
            subject_version_refs=[
                f"git:{baseline_commit}",
                f"git:{candidate_commit}",
                f"tree:{candidate_tree}",
            ],
            provider_id="development:git-repository",
            provider_version="1",
            invoke=lambda: self.inner.promote_candidate(
                repository_root,
                default_branch,
                baseline_commit=baseline_commit,
                candidate_commit=candidate_commit,
                candidate_tree=candidate_tree,
            ),
            encode=lambda value: {
                "commit": value.commit,
                "tree": value.tree,
                "changed_paths": list(value.changed_paths),
                "codex_thread_id": value.codex_thread_id,
            },
            decode=lambda value: CandidateCommit(
                commit=str(value["commit"]),
                tree=str(value["tree"]),
                changed_paths=tuple(str(item) for item in value.get("changed_paths", [])),
                codex_thread_id=(
                    str(value["codex_thread_id"])
                    if value.get("codex_thread_id") is not None
                    else None
                ),
            ),
        )

    def restore_baseline(
        self,
        repository_root: Path,
        default_branch: str,
        *,
        baseline_commit: str,
    ) -> RepositoryBaseline:
        parameters = {
            "default_branch": default_branch,
            "baseline_commit": baseline_commit,
        }
        return self.bridge.execute_external_effect(
            target_id=self.target_id,
            capability="development.source.restore",
            resource=f"development-repository:{self.target_id}:{default_branch}",
            idempotency_key=(
                f"development:source:restore:{self.target_id}:"
                f"{default_branch}:{baseline_commit}"
            ),
            parameters=parameters,
            subject_version_refs=[f"git:{baseline_commit}"],
            provider_id="development:git-repository",
            provider_version="1",
            invoke=lambda: self.inner.restore_baseline(
                repository_root,
                default_branch,
                baseline_commit=baseline_commit,
            ),
            encode=lambda value: {
                "repository_root": str(value.repository_root),
                "commit": value.commit,
                "tree": value.tree,
                "branch": value.branch,
            },
            decode=lambda value: RepositoryBaseline(
                repository_root=Path(str(value["repository_root"])),
                commit=str(value["commit"]),
                tree=str(value["tree"]),
                branch=str(value["branch"]),
            ),
        )

    def remove_worktree(self, baseline: RepositoryBaseline, worktree: Worktree) -> None:
        self.inner.remove_worktree(baseline, worktree)

    def cleanup_cycle(
        self,
        repository_root: Path,
        *,
        cycle_id: str,
        worktree_root: Path,
    ) -> None:
        self.inner.cleanup_cycle(
            repository_root,
            cycle_id=cycle_id,
            worktree_root=worktree_root,
        )


__all__ = [
    "RuntimeBoundDeploymentProvider",
    "RuntimeBoundRepositoryProvider",
    "RuntimeBoundTrafficDirector",
]
