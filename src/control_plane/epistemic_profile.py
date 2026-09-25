from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RepairIssueKind(StrEnum):
    ACQUISITION_GAP = "acquisition-gap"
    CANDIDATE_SPACE_SUSPECTED_INCOMPLETE = "candidate-space-suspected-incomplete"
    REPRESENTATION_MISMATCH = "representation-mismatch"


class RepairTensionKind(StrEnum):
    REPEATED_REOPEN = "repeated-reopen"
    PERSISTENT_RESIDUAL = "persistent-residual"
    REPRESENTATION_INSTABILITY = "representation-instability"


class RepairIntentKind(StrEnum):
    ACQUIRE_EVIDENCE = "acquire-evidence"
    REVISE_REPRESENTATION = "revise-representation"
    WAIT = "wait"


@dataclass(frozen=True, slots=True)
class RepairIssue:
    kind: RepairIssueKind
    statement: str


@dataclass(frozen=True, slots=True)
class RepairTension:
    kind: RepairTensionKind
    statement: str


@dataclass(frozen=True, slots=True)
class RepairCandidate:
    kind: str
    statement: str
    redundancy_key: str


@dataclass(frozen=True, slots=True)
class RepairCapabilityBelief:
    capability_ref: str
    can_observe: tuple[str, ...]
    cannot_establish: tuple[str, ...]
    effect_class: str


@dataclass(frozen=True, slots=True)
class RepairSelfModel:
    capabilities: tuple[RepairCapabilityBelief, ...]
    remaining_autonomous_attempts: int

    def capability(self, capability_ref: str) -> RepairCapabilityBelief | None:
        return next(
            (item for item in self.capabilities if item.capability_ref == capability_ref),
            None,
        )

    def can_attempt(self, capability_ref: str) -> bool:
        return self.capability(capability_ref) is not None


@dataclass(frozen=True, slots=True)
class RepairIntent:
    kind: RepairIntentKind
    candidate_ref: str | None = None


@dataclass(frozen=True, slots=True)
class RepairEpistemicProfile:
    """Domain-local metacognitive profile.

    These are control-plane planning distinctions only. They do not establish
    universal truth, mint authority, or define World Runtime cognition.
    """

    issues: tuple[RepairIssue, ...]
    tensions: tuple[RepairTension, ...]
    candidates: tuple[RepairCandidate, ...]
    self_model: RepairSelfModel
    intent: RepairIntent
    basis_refs: tuple[str, ...]


def build_repair_epistemic_profile(
    *,
    controller_ref: str,
    state_version: int,
    attempt: int,
    attempt_limit: int,
    is_line_ending_cleanup: bool,
    has_repo: bool,
    has_project: bool,
    has_maintenance_capability: bool,
    retry_context: str,
) -> RepairEpistemicProfile:
    if attempt < 1 or attempt_limit < 1:
        raise ValueError("repair attempt values must be positive")
    if state_version < 0:
        raise ValueError("state_version cannot be negative")

    basis = (f"controller:{controller_ref}:v{state_version}",)
    issues: list[RepairIssue] = []
    tensions: list[RepairTension] = []
    candidates: list[RepairCandidate] = []

    if attempt == 1:
        issues.append(
            RepairIssue(
                RepairIssueKind.ACQUISITION_GAP,
                "The incident has not yet been localized by a current discriminating diagnosis.",
            )
        )
    else:
        issues.append(
            RepairIssue(
                RepairIssueKind.CANDIDATE_SPACE_SUSPECTED_INCOMPLETE,
                (
                    "Reality contradicted the previous repair closure; repeating the "
                    "same root-cause partition is not sufficient."
                ),
            )
        )
        tensions.append(
            RepairTension(
                RepairTensionKind.REPEATED_REOPEN,
                "The next pass must introduce a new distinction.",
            )
        )
        if retry_context.strip():
            tensions.append(
                RepairTension(
                    RepairTensionKind.PERSISTENT_RESIDUAL,
                    "Prior execution/verification contains an unresolved residual.",
                )
            )
        candidates.append(
            RepairCandidate(
                kind="representation",
                statement=(
                    "Repartition the live root-cause hypotheses and identify which "
                    "assumption in the previous closure failed."
                ),
                redundancy_key=f"representation-revision:{attempt}",
            )
        )

    if is_line_ending_cleanup:
        issues.append(
            RepairIssue(
                RepairIssueKind.REPRESENTATION_MISMATCH,
                (
                    "Repository dirtiness may collapse semantic change and "
                    "line-ending representation noise."
                ),
            )
        )
        tensions.append(
            RepairTension(
                RepairTensionKind.REPRESENTATION_INSTABILITY,
                "Repository state is unstable under line-ending equivalence.",
            )
        )
        candidates.append(
            RepairCandidate(
                kind="representation",
                statement=(
                    "Separate semantic content change from line-ending noise using "
                    "the exact normalization equivalence."
                ),
                redundancy_key="line-ending-representation-equivalence",
            )
        )

    candidates.append(
        RepairCandidate(
            kind="acquisition",
            statement=(
                "Acquire one bounded diagnosis that distinguishes the live root-cause hypotheses."
            ),
            redundancy_key=f"bounded-diagnosis:{attempt}",
        )
    )

    capabilities = [
        RepairCapabilityBelief(
            "reason.generate",
            ("bounded diagnosis output",),
            ("target recovery", "effect authorization"),
            "read-only",
        ),
        RepairCapabilityBelief(
            "monitor.alert.active",
            ("triggering alert active state",),
            ("root cause",),
            "read-only",
        ),
    ]
    if has_repo:
        capabilities.append(
            RepairCapabilityBelief(
                "shell.exec",
                ("bounded repository-local execution outcome",),
                ("target recovery",),
                "internal-reversible",
            )
        )
    if has_project:
        capabilities.append(
            RepairCapabilityBelief(
                "docker.compose.up",
                ("bounded project apply result",),
                ("alert recovery",),
                "external-effect",
            )
        )
    if has_maintenance_capability:
        capabilities.append(
            RepairCapabilityBelief(
                "maintenance.profile-action",
                ("bounded maintenance result",),
                ("alert recovery",),
                "internal-reversible",
            )
        )

    revise = bool(
        is_line_ending_cleanup
        or attempt > 1
        or any(item.kind is RepairTensionKind.REPEATED_REOPEN for item in tensions)
    )
    if revise:
        intent = RepairIntent(
            RepairIntentKind.REVISE_REPRESENTATION,
            candidates[0].redundancy_key if candidates else None,
        )
    elif capabilities:
        intent = RepairIntent(
            RepairIntentKind.ACQUIRE_EVIDENCE,
            candidates[-1].redundancy_key,
        )
    else:
        intent = RepairIntent(RepairIntentKind.WAIT)

    return RepairEpistemicProfile(
        issues=tuple(issues),
        tensions=tuple(tensions),
        candidates=tuple(candidates),
        self_model=RepairSelfModel(
            tuple(capabilities),
            max(0, attempt_limit - attempt + 1),
        ),
        intent=intent,
        basis_refs=basis,
    )


def render_meta_control_directive(profile: RepairEpistemicProfile) -> str:
    """Render bounded domain planning guidance; never authority."""

    if profile.intent.kind is RepairIntentKind.REVISE_REPRESENTATION:
        return (
            "META_INTENT=REVISE_REPRESENTATION\n"
            "Do not repeat the previous root-cause partition. Change the working "
            "distinctions first and name one new observable difference. "
            "This directive authorizes no effect."
        )
    if profile.intent.kind is RepairIntentKind.ACQUIRE_EVIDENCE:
        return (
            "META_INTENT=ACQUIRE_EVIDENCE\n"
            "Acquire one bounded discriminating diagnosis. Provider success is "
            "evidence only for the bounded proposition and does not establish "
            "target recovery."
        )
    return (
        "META_INTENT=WAIT\n"
        "No admissible discriminating action is available. Do not manufacture "
        "a closure."
    )


__all__ = [
    "RepairCandidate",
    "RepairCapabilityBelief",
    "RepairEpistemicProfile",
    "RepairIntent",
    "RepairIntentKind",
    "RepairIssue",
    "RepairIssueKind",
    "RepairSelfModel",
    "RepairTension",
    "RepairTensionKind",
    "build_repair_epistemic_profile",
    "render_meta_control_directive",
]
