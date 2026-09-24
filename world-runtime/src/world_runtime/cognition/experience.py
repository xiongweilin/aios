from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExperienceRule:
    id: str
    summary: str
    required_tags: frozenset[str]
    directives: tuple[str, ...]
    source_classes: tuple[str, ...]


DEFAULT_EXPERIENCE_RULES: tuple[ExperienceRule, ...] = (
    ExperienceRule(
        id="freshness-before-reuse-v1",
        summary="Historical validity does not establish current-use validity.",
        required_tags=frozenset({"historical-use"}),
        directives=(
            "Re-ground the experience in current scope, environment and evidence "
            "before relying on it.",
            "Treat historical success as provenance or a prior, not as a current decision.",
        ),
        source_classes=("ratio", "agent-kernel-experience-use"),
    ),
    ExperienceRule(
        id="new-evidence-before-retry-v1",
        summary="A repeated cognitive pass should consume a new discriminating reality difference.",
        required_tags=frozenset({"retry"}),
        directives=(
            "Carry forward the prior attempt evidence explicitly.",
            "Prefer a new observation, test or representation change over an equivalent "
            "blind retry.",
        ),
        source_classes=("control-plane", "ratio"),
    ),
    ExperienceRule(
        id="proxy-target-separation-v1",
        summary="A proxy/source/provider state does not directly establish the target state.",
        required_tags=frozenset({"proxy-observation"}),
        directives=(
            "State exactly what the observation proves and what target proposition remains "
            "unverified.",
            "Use an independent target observation when the action depends on target truth.",
        ),
        source_classes=("control-plane", "ratio"),
    ),
    ExperienceRule(
        id="unknown-no-effect-v1",
        summary="UNKNOWN can justify acquisition but cannot authorize an effect.",
        required_tags=frozenset({"unknown"}),
        directives=(
            "Prefer read-class evidence acquisition while the relevant distinction remains "
            "unresolved.",
            "Do not widen effect scope merely because the current classifier cannot decide.",
        ),
        source_classes=("control-plane", "ratio"),
    ),
    ExperienceRule(
        id="narrow-before-broaden-v1",
        summary="Localize the failure before increasing blast radius.",
        required_tags=frozenset({"failure-localization"}),
        directives=(
            "Choose the smallest action that can discriminate among live failure hypotheses.",
            "Increase scope only when narrower observations cannot resolve the "
            "decision-relevant ambiguity.",
        ),
        source_classes=("ratio-runbook", "control-plane"),
    ),
    ExperienceRule(
        id="scoped-generalization-v1",
        summary=(
            "One verified success yields scoped conditional experience, not a universal procedure."
        ),
        required_tags=frozenset({"experience-consolidation"}),
        directives=(
            "Retain scope, conditions, evidence boundary and reopen triggers with the lesson.",
            "Require repeated independent validation before promoting a lesson to a general "
            "policy rule.",
        ),
        source_classes=("ratio",),
    ),
    ExperienceRule(
        id="representation-equivalence-v1",
        summary=(
            "Surface difference may be representational noise rather than task-relevant "
            "semantic difference."
        ),
        required_tags=frozenset({"representation-mismatch"}),
        directives=(
            "Test an explicit equivalence relation before creating a new semantic failure class.",
            "Keep the equivalence check deterministic and narrower than the effect it can enable.",
        ),
        source_classes=("control-plane-line-ending-case", "ratio"),
    ),
)


class ExperienceResolver:
    """Resolve scoped policy hints; resolution itself grants no truth or authority."""

    def __init__(self, rules: Iterable[ExperienceRule] = DEFAULT_EXPERIENCE_RULES) -> None:
        self._rules = tuple(rules)

    @property
    def rules(self) -> tuple[ExperienceRule, ...]:
        return self._rules

    def resolve(self, tags: Iterable[str]) -> tuple[ExperienceRule, ...]:
        available = frozenset(tags)
        return tuple(rule for rule in self._rules if rule.required_tags <= available)

    def render(self, tags: Iterable[str]) -> str:
        rules = self.resolve(tags)
        if not rules:
            return ""
        lines = ["Epistemic policy hints (historical/scoped, re-ground in current evidence):"]
        for rule in rules:
            lines.append(f"- {rule.id}: {rule.summary}")
            lines.extend(f"  - {directive}" for directive in rule.directives)
        return "\n".join(lines)
