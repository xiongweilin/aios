from semantic_language import Decision, Goal, Mandate, SemanticKind, SemanticRef

from world_runtime import WorldRuntime


def _admitted_goal(runtime: WorldRuntime) -> Goal:
    mandate = Mandate(id="mandate:strategy-lifecycle", principal="owner")
    runtime.governance.register_mandate(mandate)
    decision = Decision(
        id="decision:strategy-admit",
        subject="service",
        decided_by="owner",
        selected={
            "target_ref": "goal:strategy-lifecycle",
            "operation": "admit-goal",
        },
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:admit"),),
    )
    runtime.decisions.record(decision)
    goal = Goal(
        id="goal:strategy-lifecycle",
        subject="service",
        desired_state={"state": "improved"},
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:admit"),),
    )
    runtime.strategy.register_goal(
        goal,
        mandate_id=mandate.id,
        decision_id=decision.id,
    )
    return goal


def test_strategy_assessment_does_not_mutate_goal_without_decision() -> None:
    runtime = WorldRuntime.sqlite()
    goal = _admitted_goal(runtime)
    assessment = runtime.strategy.assess_goal(
        goal.id,
        disposition="stop",
        basis_refs=("evidence:stop",),
    )

    assert assessment.disposition == "stop"
    assert runtime.strategy.get_goal(goal.id)["status"] == "active"


def test_goal_lifecycle_transition_requires_assessment_and_decision() -> None:
    runtime = WorldRuntime.sqlite()
    goal = _admitted_goal(runtime)
    assessment = runtime.strategy.assess_goal(
        goal.id,
        disposition="stop",
        basis_refs=("evidence:stop",),
    )

    try:
        runtime.strategy.transition_goal(
            goal.id,
            to_status="stopped",
            assessment_id=assessment.id,
            decision_id="decision:missing",
            basis_refs=("evidence:stop",),
        )
    except ValueError as exc:
        assert "required decision is not recorded" in str(exc)
    else:
        raise AssertionError("goal transition must require a Decision")

    decision = Decision(
        id="decision:strategy-stop",
        subject="service",
        decided_by="owner",
        selected={
            "target_ref": goal.id,
            "operation": "transition-goal",
            "to_status": "stopped",
            "assessment_id": assessment.id,
        },
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:stop"),),
    )
    runtime.decisions.record(decision)
    transition = runtime.strategy.transition_goal(
        goal.id,
        to_status="stopped",
        assessment_id=assessment.id,
        decision_id=decision.id,
        basis_refs=("evidence:stop",),
    )

    assert transition.from_status == "active"
    assert transition.to_status == "stopped"
    assert runtime.strategy.get_goal(goal.id)["status"] == "stopped"
