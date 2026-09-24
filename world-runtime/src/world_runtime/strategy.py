from dataclasses import dataclass
from typing import Mapping

from semantic_language import Goal, Revision, SemanticKind, SemanticRef

from .common import new_id
from .decisions import assert_decision_applies
from .governance import assert_mandate_current
from .ledger import SemanticLedger
from .lineage import RevisionLineageService


@dataclass(frozen=True, slots=True)
class StrategicOption:
    id: str
    subject: str
    hypothesis: Mapping[str, object]
    evaluation: Mapping[str, object]
    basis_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StrategyAssessment:
    id: str
    goal_id: str
    disposition: str
    basis_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...] = ()
    outcome_refs: tuple[str, ...] = ()
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class GoalLifecycleTransition:
    id: str
    goal_id: str
    from_status: str
    to_status: str
    assessment_id: str
    decision_id: str
    basis_refs: tuple[str, ...]


class StrategyService:
    def __init__(
        self,
        ledger: SemanticLedger,
        lineage: RevisionLineageService | None = None,
    ) -> None:
        self.ledger = ledger
        self.lineage = lineage or RevisionLineageService(ledger)

    ASSESSMENT_NAMESPACE = "world-runtime.strategy"
    ASSESSMENT_KIND = "strategy-assessment"

    @classmethod
    def assessment_ref(cls, assessment_id: str) -> SemanticRef:
        return SemanticRef(
            kind=cls.ASSESSMENT_KIND,
            id=assessment_id,
            namespace=cls.ASSESSMENT_NAMESPACE,
        )

    @staticmethod
    def _assessment_from_value(value: Mapping[str, object]) -> StrategyAssessment:
        return StrategyAssessment(
            id=str(value["id"]),
            goal_id=str(value["goal_id"]),
            disposition=str(value["disposition"]),
            basis_refs=tuple(str(v) for v in value.get("basis_refs", [])),
            evidence_refs=tuple(str(v) for v in value.get("evidence_refs", [])),
            outcome_refs=tuple(str(v) for v in value.get("outcome_refs", [])),
            rationale=str(value.get("rationale", "")),
        )

    def register_goal(self, goal: Goal, *, mandate_id: str, decision_id: str) -> None:
        assert_mandate_current(self.ledger, mandate_id)
        assert_decision_applies(
            self.ledger,
            decision_id,
            target_ref=goal.id,
            operation="admit-goal",
        )
        value = {
            "id": goal.id,
            "subject": goal.subject,
            "desired_state": dict(goal.desired_state),
            "basis_refs": [r.id for r in goal.basis_refs],
            "mandate_id": mandate_id,
            "decision_id": decision_id,
            "status": "active",
        }
        existing = self.ledger.project_get("strategy.goal", goal.id)
        if existing is not None:
            existing_identity = {
                key: existing[0].get(key)
                for key in (
                    "id",
                    "subject",
                    "desired_state",
                    "basis_refs",
                    "mandate_id",
                    "decision_id",
                )
            }
            incoming_identity = {
                key: value.get(key)
                for key in (
                    "id",
                    "subject",
                    "desired_state",
                    "basis_refs",
                    "mandate_id",
                    "decision_id",
                )
            }
            if existing_identity != incoming_identity:
                raise ValueError("goal identity rebound")
            return
        with self.ledger.transaction():
            self.ledger.project_put("strategy.goal", goal.id, value)
            self.ledger.append(
                stream=f"goal:{goal.id}",
                kind="strategy.goal.admitted",
                payload=value,
            )

    def propose_option(
        self,
        *,
        subject: str,
        hypothesis: Mapping[str, object],
        evaluation: Mapping[str, object],
        basis_refs: tuple[str, ...],
    ) -> StrategicOption:
        if not basis_refs:
            raise ValueError("strategic option requires basis")
        return StrategicOption(
            new_id("strategic-option"),
            subject,
            dict(hypothesis),
            dict(evaluation),
            basis_refs,
        )

    def get_goal(self, goal_id: str) -> Mapping[str, object]:
        row = self.ledger.project_get("strategy.goal", goal_id)
        if row is None:
            raise KeyError(goal_id)
        return row[0]

    def assess_goal(
        self,
        goal_id: str,
        *,
        disposition: str,
        basis_refs: tuple[str, ...],
        evidence_refs: tuple[str, ...] = (),
        outcome_refs: tuple[str, ...] = (),
        rationale: str = "",
        supersedes_assessment_id: str | None = None,
        revision_reason: str = "",
        revision_basis_refs: tuple[str, ...] = (),
    ) -> StrategyAssessment:
        self.lineage.assert_current(SemanticRef(SemanticKind.GOAL, goal_id))
        if disposition not in {"continue", "revise", "stop"}:
            raise ValueError("strategy disposition must be continue, revise, or stop")
        if not basis_refs:
            raise ValueError("strategy assessment requires basis refs")
        self.get_goal(goal_id)

        current = self.ledger.project_get("strategy.assessment", goal_id)
        revision: Revision | None = None
        if current is None:
            if supersedes_assessment_id is not None:
                raise ValueError("first strategy assessment cannot supersede another assessment")
            if revision_reason or revision_basis_refs:
                raise ValueError("first strategy assessment must not carry revision lineage")
        else:
            current_id = str(current[0]["id"])
            if supersedes_assessment_id != current_id:
                raise ValueError(
                    "new strategy assessment must explicitly supersede the current assessment"
                )
            if not revision_reason.strip():
                raise ValueError("strategy assessment supersession requires revision reason")
            if not revision_basis_refs:
                raise ValueError("strategy assessment supersession requires revision basis refs")

        assessment = StrategyAssessment(
            id=new_id("strategy-assessment"),
            goal_id=goal_id,
            disposition=disposition,
            basis_refs=tuple(basis_refs),
            evidence_refs=tuple(evidence_refs),
            outcome_refs=tuple(outcome_refs),
            rationale=rationale,
        )
        value: dict[str, object] = {
            "id": assessment.id,
            "goal_id": assessment.goal_id,
            "disposition": assessment.disposition,
            "basis_refs": list(assessment.basis_refs),
            "evidence_refs": list(assessment.evidence_refs),
            "outcome_refs": list(assessment.outcome_refs),
            "rationale": assessment.rationale,
        }

        if current is not None:
            current_id = str(current[0]["id"])
            revision = Revision(
                id=new_id("revision"),
                target_ref=self.assessment_ref(assessment.id),
                supersedes_ref=self.assessment_ref(current_id),
                reason=revision_reason,
                basis_refs=tuple(
                    SemanticRef(SemanticKind.EVIDENCE, ref)
                    for ref in revision_basis_refs
                ),
            )
            value["revision_id"] = revision.id
            value["supersedes_assessment_id"] = current_id

        with self.ledger.transaction():
            if current is not None:
                current_id = str(current[0]["id"])
                if self.ledger.project_get(
                    "strategy.assessment-record",
                    current_id,
                ) is None:
                    self.ledger.project_put(
                        "strategy.assessment-record",
                        current_id,
                        current[0],
                        expected_version=0,
                    )
            self.ledger.project_put(
                "strategy.assessment-record",
                assessment.id,
                value,
                expected_version=0,
            )
            if revision is not None:
                self.lineage.record(revision)
            self.ledger.project_put(
                "strategy.assessment",
                goal_id,
                value,
                expected_version=0 if current is None else current[1],
            )
            self.ledger.append(
                stream=f"goal:{goal_id}",
                kind=(
                    "strategy.goal.assessed"
                    if revision is None
                    else "strategy.goal.reassessed"
                ),
                payload=value,
            )
        return assessment

    def transition_goal(
        self,
        goal_id: str,
        *,
        to_status: str,
        assessment_id: str,
        decision_id: str,
        basis_refs: tuple[str, ...],
    ) -> GoalLifecycleTransition:
        if not basis_refs:
            raise ValueError("goal lifecycle transition requires basis refs")
        self.lineage.assert_current(SemanticRef(SemanticKind.GOAL, goal_id))
        goal_row = self.ledger.project_get("strategy.goal", goal_id)
        if goal_row is None:
            raise KeyError(goal_id)
        goal_value, goal_version = goal_row
        assessment_row = self.ledger.project_get("strategy.assessment", goal_id)
        if (
            assessment_row is None
            or str(assessment_row[0].get("id")) != assessment_id
        ):
            raise ValueError("goal lifecycle transition requires current strategy assessment")
        self.lineage.assert_current(self.assessment_ref(assessment_id))
        assert_decision_applies(
            self.ledger,
            decision_id,
            target_ref=goal_id,
            operation="transition-goal",
            expected={
                "to_status": to_status,
                "assessment_id": assessment_id,
            },
        )

        from_status = str(goal_value.get("status", "active"))
        allowed = {
            "active": {"revision-required", "stopped"},
            "revision-required": {"active", "stopped", "retired"},
            "stopped": {"retired"},
            "retired": set(),
        }
        if to_status not in allowed.get(from_status, set()):
            raise ValueError(
                f"goal status {from_status} does not admit transition to {to_status}"
            )

        assessment_disposition = str(assessment_row[0].get("disposition", ""))
        required_by_disposition = {
            "continue": {"active"},
            "revise": {"revision-required"},
            "stop": {"stopped", "retired"},
        }
        if to_status not in required_by_disposition.get(
            assessment_disposition,
            set(),
        ):
            raise ValueError(
                "goal lifecycle transition conflicts with strategy assessment"
            )

        transition = GoalLifecycleTransition(
            id=new_id("goal-transition"),
            goal_id=goal_id,
            from_status=from_status,
            to_status=to_status,
            assessment_id=assessment_id,
            decision_id=decision_id,
            basis_refs=tuple(basis_refs),
        )
        transition_value = {
            "id": transition.id,
            "goal_id": transition.goal_id,
            "from_status": transition.from_status,
            "to_status": transition.to_status,
            "assessment_id": transition.assessment_id,
            "decision_id": transition.decision_id,
            "basis_refs": list(transition.basis_refs),
        }
        goal_value["status"] = to_status
        goal_value["last_transition_id"] = transition.id
        with self.ledger.transaction():
            self.ledger.project_put(
                "strategy.goal",
                goal_id,
                goal_value,
                expected_version=goal_version,
            )
            self.ledger.project_put(
                "strategy.goal-transition",
                transition.id,
                transition_value,
            )
            self.ledger.append(
                stream=f"goal:{goal_id}",
                kind="strategy.goal.transitioned",
                payload=transition_value,
            )
        return transition

    def supersede_goal(
        self,
        previous_id: str,
        successor: Goal,
        revision: Revision,
        *,
        mandate_id: str,
        decision_id: str,
    ) -> None:
        previous_ref = SemanticRef(SemanticKind.GOAL, previous_id)
        if revision.supersedes_ref != previous_ref:
            raise ValueError("Goal Revision must supersede the selected Goal")
        if revision.target_ref != successor.ref:
            raise ValueError("Goal Revision target must be the successor Goal")

        previous_row = self.ledger.project_get("strategy.goal", previous_id)
        if previous_row is None:
            raise KeyError(previous_id)
        previous, previous_version = previous_row
        if previous.get("status") != "revision-required":
            raise ValueError(
                "Goal must be revision-required before successor admission"
            )
        self.lineage.assert_current(previous_ref)
        assert_mandate_current(self.ledger, mandate_id)
        assert_decision_applies(
            self.ledger,
            decision_id,
            target_ref=successor.id,
            operation="admit-goal",
            expected={"supersedes_goal_id": previous_id},
        )

        retired_previous = dict(previous)
        retired_previous["status"] = "retired"
        retired_previous["superseded_by"] = successor.id
        retired_previous["revision_id"] = revision.id

        with self.ledger.transaction():
            self.register_goal(
                successor,
                mandate_id=mandate_id,
                decision_id=decision_id,
            )
            self.lineage.record(revision)
            self.ledger.project_put(
                "strategy.goal",
                previous_id,
                retired_previous,
                expected_version=previous_version,
            )
            self.ledger.append(
                stream=f"goal:{previous_id}",
                kind="strategy.goal.superseded",
                payload={
                    "successor_id": successor.id,
                    "revision_id": revision.id,
                    "basis_refs": [ref.id for ref in revision.basis_refs],
                    "decision_id": decision_id,
                },
            )

    def get_current_goal(self, goal_id: str) -> Mapping[str, object]:
        current = self.lineage.resolve_current(
            SemanticRef(SemanticKind.GOAL, goal_id)
        )
        return self.get_goal(current.id)

    def get_assessment(self, assessment_id: str) -> StrategyAssessment:
        row = self.ledger.project_get("strategy.assessment-record", assessment_id)
        if row is None:
            for projection in self.ledger.export_projection_rows():
                if (
                    projection["namespace"] == "strategy.assessment"
                    and str(projection["value"].get("id")) == assessment_id
                ):
                    return self._assessment_from_value(projection["value"])
            raise KeyError(assessment_id)
        return self._assessment_from_value(row[0])

    def get_current_assessment(self, assessment_id: str) -> StrategyAssessment:
        current = self.lineage.resolve_current(self.assessment_ref(assessment_id))
        return self.get_assessment(current.id)

    def latest_assessment(self, goal_id: str) -> StrategyAssessment | None:
        row = self.ledger.project_get("strategy.assessment", goal_id)
        if row is None:
            return None
        return self._assessment_from_value(row[0])


__all__ = [
    "GoalLifecycleTransition",
    "StrategicOption",
    "StrategyAssessment",
    "StrategyService",
]
