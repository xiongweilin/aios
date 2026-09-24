from datetime import timedelta

import pytest
from semantic_language import Decision, Goal, Mandate, Responsibility, SemanticKind, SemanticRef

import world_runtime.governance as governance_module
from world_runtime import DomainAssignment, WorldRuntime
from world_runtime.common import utcnow


def _evidence_ref(identifier: str = "evidence:integrity") -> SemanticRef:
    return SemanticRef(SemanticKind.EVIDENCE, identifier)


def _decision(
    runtime: WorldRuntime,
    *,
    identifier: str,
    target_ref: str,
    operation: str,
    **selected: object,
) -> Decision:
    decision = Decision(
        id=identifier,
        subject=target_ref,
        decided_by="owner",
        selected={
            "target_ref": target_ref,
            "operation": operation,
            **selected,
        },
        basis_refs=(_evidence_ref(),),
    )
    runtime.decisions.record(decision)
    return decision


def test_canonical_identity_rejects_rebinding_and_does_not_reactivate() -> None:
    runtime = WorldRuntime.sqlite()
    decision = _decision(
        runtime,
        identifier="decision:identity",
        target_ref="goal:identity",
        operation="admit-goal",
    )
    runtime.decisions.record(decision)
    with pytest.raises(ValueError, match="decision identity rebound"):
        runtime.decisions.record(
            Decision(
                id=decision.id,
                subject="other",
                decided_by="owner",
                selected={"target_ref": "other", "operation": "admit-goal"},
                basis_refs=(_evidence_ref("evidence:other"),),
            )
        )

    mandate = Mandate(id="mandate:identity", principal="owner", scope={"resource": "r:1"})
    runtime.governance.register_mandate(mandate)
    runtime.governance.revoke_mandate(mandate.id, reason="superseded")
    runtime.governance.register_mandate(mandate)
    row = runtime.ledger.project_get("governance.mandate", mandate.id)
    assert row is not None and row[0]["status"] == "revoked"
    with pytest.raises(ValueError, match="mandate identity rebound"):
        runtime.governance.register_mandate(
            Mandate(id=mandate.id, principal="owner", scope={"resource": "r:2"})
        )

    responsibility = Responsibility(id="responsibility:identity", principal="p", subject="s")
    runtime.responsibility.create(responsibility, domain="test")
    with pytest.raises(ValueError, match="responsibility identity rebound"):
        runtime.responsibility.create(
            Responsibility(id=responsibility.id, principal="p", subject="other"),
            domain="test",
        )


def test_discharged_responsibility_cannot_reopen_admit_work_or_receive_assignment() -> None:
    runtime = WorldRuntime.sqlite()
    responsibility = Responsibility(id="responsibility:terminal", principal="p", subject="s")
    runtime.responsibility.create(responsibility, domain="test")
    runtime.responsibility.assess(
        responsibility.id,
        status="satisfied",
        basis_refs=("evidence:satisfied",),
    )
    decision = _decision(
        runtime,
        identifier="decision:discharge-terminal",
        target_ref=responsibility.id,
        operation="discharge-responsibility",
        to_status="discharged",
    )
    runtime.responsibility.discharge(responsibility.id, decision_id=decision.id)

    with pytest.raises(ValueError):
        runtime.responsibility.assess(
            responsibility.id,
            status="active",
            basis_refs=("evidence:reopen",),
        )
    with pytest.raises(ValueError, match="active responsibility"):
        runtime.execution.admit_work(
            responsibility_id=responsibility.id,
            kind="late-work",
            payload={},
        )
    with pytest.raises(ValueError, match="active responsibility"):
        runtime.domains.offer(
            DomainAssignment(
                id="assignment:late",
                responsibility_ref=responsibility.id,
                domain="test",
                controller="controller:test",
            )
        )


def test_governance_enforces_current_mandate_ceiling_expiry_conditions_and_decision_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = WorldRuntime.sqlite()
    now = utcnow()
    mandate = Mandate(
        id="mandate:governance",
        principal="owner",
        scope={"resource": "resource:1"},
        authority_ceiling={"action": "deploy", "resource": "resource:1"},
        expires_at=now + timedelta(hours=2),
    )
    runtime.governance.register_mandate(mandate)

    unrelated = _decision(
        runtime,
        identifier="decision:unrelated",
        target_ref="resource:other",
        operation="authorize-effect",
        action="deploy",
    )
    with pytest.raises(ValueError, match="decision does not apply"):
        runtime.governance.issue_authorization(
            principal="controller",
            action="deploy",
            resource="resource:1",
            mandate_id=mandate.id,
            decision_id=unrelated.id,
        )

    decision = _decision(
        runtime,
        identifier="decision:authorize",
        target_ref="resource:1",
        operation="authorize-effect",
        action="deploy",
    )
    with pytest.raises(PermissionError, match="authority ceiling"):
        runtime.governance.issue_authorization(
            principal="controller",
            action="delete",
            resource="resource:1",
            mandate_id=mandate.id,
            decision_id=decision.id,
        )

    auth = runtime.governance.issue_authorization(
        authorization_id="authorization:governance",
        principal="controller",
        action="deploy",
        resource="resource:1",
        mandate_id=mandate.id,
        decision_id=decision.id,
        conditions={
            "required_context": {
                "request.metadata.change_ticket": "CHG-1",
            }
        },
        expires_at=now + timedelta(hours=1),
    )
    with pytest.raises(PermissionError, match="condition is not satisfied"):
        runtime.governance.assert_usable(
            auth.id,
            principal="controller",
            action="deploy",
            resource="resource:1",
            context={"request": {"metadata": {"change_ticket": "CHG-2"}}},
        )
    runtime.governance.assert_usable(
        auth.id,
        principal="controller",
        action="deploy",
        resource="resource:1",
        context={"request": {"metadata": {"change_ticket": "CHG-1"}}},
    )

    monkeypatch.setattr(
        governance_module,
        "utcnow",
        lambda: now + timedelta(hours=3),
    )
    with pytest.raises(PermissionError, match="authorization has expired|mandate has expired"):
        runtime.governance.assert_usable(
            auth.id,
            principal="controller",
            action="deploy",
            resource="resource:1",
            context={"request": {"metadata": {"change_ticket": "CHG-1"}}},
        )


def test_goal_transition_and_discharge_require_the_specific_applicable_decision() -> None:
    runtime = WorldRuntime.sqlite()
    mandate = Mandate(id="mandate:goal", principal="owner")
    runtime.governance.register_mandate(mandate)
    goal = Goal(
        id="goal:integrity",
        subject="service",
        desired_state={"done": True},
        basis_refs=(_evidence_ref(),),
    )
    admit = _decision(
        runtime,
        identifier="decision:goal-admit",
        target_ref=goal.id,
        operation="admit-goal",
    )
    runtime.strategy.register_goal(goal, mandate_id=mandate.id, decision_id=admit.id)
    assessment = runtime.strategy.assess_goal(
        goal.id,
        disposition="stop",
        basis_refs=("evidence:stop",),
    )
    wrong = _decision(
        runtime,
        identifier="decision:wrong-goal",
        target_ref="goal:other",
        operation="transition-goal",
        to_status="stopped",
        assessment_id=assessment.id,
    )
    with pytest.raises(ValueError, match="decision does not apply"):
        runtime.strategy.transition_goal(
            goal.id,
            to_status="stopped",
            assessment_id=assessment.id,
            decision_id=wrong.id,
            basis_refs=("evidence:stop",),
        )
