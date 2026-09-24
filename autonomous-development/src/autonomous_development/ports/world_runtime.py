from __future__ import annotations

from typing import Protocol

from autonomous_development.domain.models import (
    BuildArtifact,
    CandidateRevision,
    Deployment,
    DevelopmentCycle,
    DevelopmentTarget,
    EvidenceWindow,
    ProductObjectiveRevision,
    ReleasedVersion,
)


class DevelopmentRuntimePort(Protocol):
    """Generic Runtime boundary used by the Development domain.

    The Runtime sees bounded responsibility and opaque domain evidence references.
    It does not own Git, build, canary, deployment, or release semantics.
    """

    def ensure_assignment(
        self,
        *,
        cycle: DevelopmentCycle,
        target: DevelopmentTarget,
        objective: ProductObjectiveRevision,
        baseline: ReleasedVersion,
        evidence_window: EvidenceWindow | None = None,
    ) -> None: ...

    def complete_promoted_release(
        self,
        *,
        cycle: DevelopmentCycle,
        candidate: CandidateRevision,
        artifact: BuildArtifact,
        deployment: Deployment,
        release: ReleasedVersion,
    ) -> None: ...


__all__ = ["DevelopmentRuntimePort"]
