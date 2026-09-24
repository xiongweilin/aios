from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

from .consolidation import (
    ConsolidationStatus,
    ExperienceCandidate,
    ExperienceConsolidator,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class ExperienceStage(StrEnum):
    SCOPED_CONDITIONAL = "scoped-conditional"
    POLICY_CANDIDATE = "policy-candidate"


@dataclass(frozen=True, slots=True)
class ExperienceRecord:
    summary: str
    scope: str
    evidence_refs: tuple[str, ...]
    policy_effects: tuple[str, ...]
    reopen_conditions: tuple[str, ...]
    negative_evidence_refs: tuple[str, ...] = ()
    validation_count: int = 1
    stage: ExperienceStage = ExperienceStage.SCOPED_CONDITIONAL
    id: str = field(default_factory=lambda: _new_id("experience"))

    def __post_init__(self) -> None:
        if not self.summary.strip() or not self.scope.strip():
            raise ValueError("experience record requires summary and bounded scope")
        if not self.evidence_refs or not self.policy_effects:
            raise ValueError("experience record requires evidence and future policy effect")
        if self.validation_count < 1:
            raise ValueError("validation_count must be positive")


class ExperienceLifecycle:
    def __init__(self, consolidator: ExperienceConsolidator | None = None) -> None:
        self.consolidator = consolidator or ExperienceConsolidator()

    def from_candidate(self, candidate: ExperienceCandidate) -> ExperienceRecord:
        assessment = self.consolidator.assess(candidate)
        if assessment.status is ConsolidationStatus.REJECTED:
            raise ValueError(assessment.reason)
        stage = (
            ExperienceStage.SCOPED_CONDITIONAL
            if assessment.status is ConsolidationStatus.SCOPED_CONDITIONAL
            else ExperienceStage.POLICY_CANDIDATE
        )
        return ExperienceRecord(
            summary=candidate.summary,
            scope=candidate.scope,
            evidence_refs=candidate.evidence_refs,
            policy_effects=candidate.policy_effects,
            reopen_conditions=candidate.reopen_conditions,
            validation_count=candidate.repeated_validation_count,
            stage=stage,
        )

    def validate(
        self,
        record: ExperienceRecord,
        *,
        evidence_ref: str,
        negative: bool = False,
    ) -> ExperienceRecord:
        if not evidence_ref.strip():
            raise ValueError("validation requires a non-empty evidence_ref")
        if negative:
            return ExperienceRecord(
                summary=record.summary,
                scope=record.scope,
                evidence_refs=record.evidence_refs,
                negative_evidence_refs=tuple(
                    dict.fromkeys((*record.negative_evidence_refs, evidence_ref))
                ),
                policy_effects=record.policy_effects,
                reopen_conditions=record.reopen_conditions,
                validation_count=record.validation_count,
                stage=record.stage,
            )
        if evidence_ref in record.evidence_refs:
            raise ValueError("positive validation requires a new evidence_ref")
        count = record.validation_count + 1
        return ExperienceRecord(
            summary=record.summary,
            scope=record.scope,
            evidence_refs=tuple(dict.fromkeys((*record.evidence_refs, evidence_ref))),
            negative_evidence_refs=record.negative_evidence_refs,
            policy_effects=record.policy_effects,
            reopen_conditions=record.reopen_conditions,
            validation_count=count,
            stage=(
                ExperienceStage.POLICY_CANDIDATE
                if count >= 2
                else ExperienceStage.SCOPED_CONDITIONAL
            ),
        )


class PolicyRuleStatus(StrEnum):
    CANDIDATE = "candidate"
    SHADOW = "shadow"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class PolicyRule:
    summary: str
    scope: str
    directives: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    reopen_conditions: tuple[str, ...]
    negative_evidence_refs: tuple[str, ...] = ()
    status: PolicyRuleStatus = PolicyRuleStatus.CANDIDATE
    id: str = field(default_factory=lambda: _new_id("policy_rule"))

    def __post_init__(self) -> None:
        if not self.summary.strip() or not self.scope.strip() or not self.directives:
            raise ValueError("policy rule requires summary, scope and directives")
        if not self.evidence_refs:
            raise ValueError("policy rule requires reality-grounded evidence")


@dataclass(frozen=True, slots=True)
class PolicyEvaluation:
    rule_ref: str
    passed: bool
    replay_cases: int
    regressions: tuple[str, ...] = ()
    improvements: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.rule_ref.strip():
            raise ValueError("policy evaluation requires a rule_ref")
        if self.replay_cases < 0:
            raise ValueError("replay_cases cannot be negative")


@dataclass(frozen=True, slots=True)
class PolicyVersion:
    version: int
    rules: tuple[PolicyRule, ...]
    parent_ref: str | None = None
    basis_refs: tuple[str, ...] = ()
    id: str = field(default_factory=lambda: _new_id("policy_version"))

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("policy version must be positive")


class PolicyPromoter:
    """Explicit promotion gate; experience never self-activates as policy."""

    def propose(self, experience: ExperienceRecord) -> PolicyRule:
        if experience.stage is not ExperienceStage.POLICY_CANDIDATE:
            raise ValueError("scoped one-shot experience cannot become a policy candidate")
        return PolicyRule(
            summary=experience.summary,
            scope=experience.scope,
            directives=experience.policy_effects,
            evidence_refs=experience.evidence_refs,
            negative_evidence_refs=experience.negative_evidence_refs,
            reopen_conditions=experience.reopen_conditions,
        )

    def shadow(self, rule: PolicyRule) -> PolicyRule:
        if rule.status is not PolicyRuleStatus.CANDIDATE:
            raise ValueError("only candidate rules enter shadow evaluation")
        return PolicyRule(
            summary=rule.summary,
            scope=rule.scope,
            directives=rule.directives,
            evidence_refs=rule.evidence_refs,
            negative_evidence_refs=rule.negative_evidence_refs,
            reopen_conditions=rule.reopen_conditions,
            status=PolicyRuleStatus.SHADOW,
            id=rule.id,
        )

    def promote(
        self,
        current: PolicyVersion,
        rule: PolicyRule,
        evaluation: PolicyEvaluation,
    ) -> PolicyVersion:
        if rule.status is not PolicyRuleStatus.SHADOW:
            raise ValueError("rule must complete shadow stage before activation")
        if evaluation.rule_ref != rule.id:
            raise ValueError("evaluation belongs to another policy rule")
        if evaluation.replay_cases < 1:
            raise ValueError("policy promotion requires at least one replay/shadow case")
        if not evaluation.passed or evaluation.regressions:
            raise ValueError("policy rule did not pass replay/shadow evaluation")
        active = PolicyRule(
            summary=rule.summary,
            scope=rule.scope,
            directives=rule.directives,
            evidence_refs=tuple(dict.fromkeys((*rule.evidence_refs, *evaluation.evidence_refs))),
            negative_evidence_refs=rule.negative_evidence_refs,
            reopen_conditions=rule.reopen_conditions,
            status=PolicyRuleStatus.ACTIVE,
            id=rule.id,
        )
        retained = tuple(item for item in current.rules if item.id != rule.id)
        return PolicyVersion(
            version=current.version + 1,
            parent_ref=current.id,
            rules=(*retained, active),
            basis_refs=tuple(
                dict.fromkeys((*current.basis_refs, *evaluation.evidence_refs, rule.id))
            ),
        )
