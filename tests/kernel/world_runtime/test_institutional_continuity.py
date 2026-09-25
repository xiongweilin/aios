from __future__ import annotations

import pytest
from semantic_language import (
    Decision,
    Goal,
    Mandate,
    Revision,
    SemanticKind,
    SemanticRef,
)

from world_runtime import WorldRuntime
from world_runtime.governance import assert_mandate_current
from world_runtime.ontology import SemanticTypeDefinition


def _evidence_ref(identifier: str) -> SemanticRef:
    return SemanticRef(SemanticKind.EVIDENCE, identifier)


def _revision(
    identifier: str,
    *,
    target: SemanticRef,
    previous: SemanticRef,
    reason: str = "new evidence changed the current qualification",
) -> Revision:
    return Revision(
        id=identifier,
        target_ref=target,
        supersedes_ref=previous,
        reason=reason,
        basis_refs=(_evidence_ref(f"evidence:{identifier}"),),
    )


def test_lineage_is_append_only_single_head_and_rejects_branching() -> None:
    runtime = WorldRuntime.sqlite()
    first = SemanticRef(SemanticKind.DECISION, "decision:first")
    second = SemanticRef(SemanticKind.DECISION, "decision:second")
    branch = SemanticRef(SemanticKind.DECISION, "decision:branch")

    revision = _revision("revision:first-second", target=second, previous=first)
    runtime.lineage.record(revision)
    runtime.lineage.record(revision)

    assert runtime.lineage.resolve_current(first) == second
    assert runtime.lineage.root(second) == first
    assert runtime.lineage.is_current(first) is False
    assert runtime.lineage.is_current(second) is True
    assert runtime.lineage.history(first) == (revision,)

    with pytest.raises(ValueError, match="current lineage head"):
        runtime.lineage.record(
            _revision("revision:branch", target=branch, previous=first)
        )


def test_decision_supersession_preserves_history_and_changes_current_applicability() -> None:
    runtime = WorldRuntime.sqlite()
    old = Decision(
        id="decision:old",
        subject="service",
        decided_by="owner",
        selected={
            "target_ref": "resource:1",
            "operation": "authorize-effect",
            "action": "deploy",
        },
        basis_refs=(_evidence_ref("evidence:old"),),
    )
    new = Decision(
        id="decision:new",
        subject="service",
        decided_by="owner",
        selected={
            "target_ref": "resource:1",
            "operation": "authorize-effect",
            "action": "deploy",
            "policy_version": "2",
        },
        basis_refs=(_evidence_ref("evidence:new"),),
    )
    runtime.decisions.record(old)
    runtime.decisions.supersede(
        old.id,
        new,
        _revision(
            "revision:decision",
            target=new.ref,
            previous=old.ref,
        ),
    )

    assert runtime.decisions.get(old.id)["selected"]["action"] == "deploy"
    assert runtime.decisions.get_current(old.id)["id"] == new.id
    runtime.decisions.assert_current(new.id)
    with pytest.raises(ValueError, match="superseded"):
        runtime.decisions.assert_current(old.id)


def test_ontology_requires_revision_for_new_version_and_preserves_history() -> None:
    runtime = WorldRuntime.sqlite()
    first = SemanticTypeDefinition(
        name="customer-account",
        owner="domain:sales",
        version="1",
        description="initial definition",
    )
    second = SemanticTypeDefinition(
        name="customer-account",
        owner="domain:sales",
        version="2",
        description="revised definition",
    )
    runtime.ontology.register(first)

    with pytest.raises(ValueError, match="explicit Revision"):
        runtime.ontology.register(second)

    revision = _revision(
        "revision:ontology",
        target=runtime.ontology.definition_ref(second),
        previous=runtime.ontology.definition_ref(first),
    )
    runtime.ontology.supersede(second, revision)

    assert runtime.ontology.resolve("customer-account") == second
    assert runtime.ontology.resolve_version("customer-account", "1") == first
    assert runtime.ontology.history("customer-account") == (first, second)


def test_memory_distinguishes_historical_experience_from_current_applicability() -> None:
    runtime = WorldRuntime.sqlite()
    old = runtime.memory.propose(
        scope={"service": "checkout"},
        lesson={"retry_policy": "fixed"},
        basis_refs=("evidence:memory-old",),
    )
    runtime.memory.qualify(old.id, assessment_refs=("assessment:old",))
    assert runtime.memory.is_applicable(old.id) is True

    runtime.memory.invalidate(
        old.id,
        reason="traffic mix changed",
        basis_refs=("evidence:invalidated",),
    )
    assert runtime.memory.is_applicable(old.id) is False

    runtime.memory.reopen(
        old.id,
        reason="re-evaluate under new traffic",
        basis_refs=("evidence:reopen",),
    )
    runtime.memory.qualify(old.id, assessment_refs=("assessment:requalified",))

    successor = runtime.memory.propose(
        scope={"service": "checkout"},
        lesson={"retry_policy": "adaptive"},
        basis_refs=("evidence:memory-new",),
    )
    runtime.memory.qualify(successor.id, assessment_refs=("assessment:new",))
    revision = _revision(
        "revision:memory",
        target=runtime.memory.experience_ref(successor.id),
        previous=runtime.memory.experience_ref(old.id),
    )
    runtime.memory.supersede(old.id, successor.id, revision)

    assert runtime.memory.get(old.id).status == "superseded"
    assert runtime.memory.get_current(old.id).id == successor.id
    assert runtime.memory.is_applicable(old.id) is False
    assert runtime.memory.is_applicable(successor.id) is True


def test_mandate_supersession_preserves_historical_authorization_but_removes_current_qualification() -> None:
    runtime = WorldRuntime.sqlite()
    old = Mandate(
        id="mandate:old",
        principal="owner",
        scope={"resource": "resource:1"},
        authority_ceiling={"action": "deploy", "resource": "resource:1"},
    )
    runtime.governance.register_mandate(old)
    decision = Decision(
        id="decision:authorize-old",
        subject="resource:1",
        decided_by="owner",
        selected={
            "target_ref": "resource:1",
            "operation": "authorize-effect",
            "action": "deploy",
        },
        basis_refs=(_evidence_ref("evidence:authorize-old"),),
    )
    runtime.decisions.record(decision)
    authorization = runtime.governance.issue_authorization(
        authorization_id="authorization:old",
        principal="owner",
        action="deploy",
        resource="resource:1",
        mandate_id=old.id,
        decision_id=decision.id,
    )

    successor = Mandate(
        id="mandate:new",
        principal="owner",
        scope={"resource": "resource:1"},
        authority_ceiling={
            "actions": ["deploy", "rollback"],
            "resource": "resource:1",
        },
    )
    runtime.governance.supersede_mandate(
        old.id,
        successor,
        _revision(
            "revision:mandate",
            target=successor.ref,
            previous=old.ref,
        ),
    )

    historical = runtime.ledger.project_get(
        "governance.authorization",
        authorization.id,
    )
    assert historical is not None
    assert historical[0]["mandate_id"] == old.id
    assert runtime.governance.get_current_mandate(old.id)["id"] == successor.id
    with pytest.raises(PermissionError, match="superseded"):
        assert_mandate_current(runtime.ledger, old.id)
    with pytest.raises(PermissionError):
        runtime.governance.assert_usable(
            authorization.id,
            principal="owner",
            action="deploy",
            resource="resource:1",
        )


def test_goal_supersession_requires_revision_required_state_and_explicit_admission_decision() -> None:
    runtime = WorldRuntime.sqlite()
    mandate = Mandate(id="mandate:strategy", principal="owner")
    runtime.governance.register_mandate(mandate)

    old = Goal(
        id="goal:old",
        subject="service",
        desired_state={"latency": "<500ms"},
        basis_refs=(_evidence_ref("evidence:goal-old"),),
    )
    admit_old = Decision(
        id="decision:admit-old",
        subject="service",
        decided_by="owner",
        selected={"target_ref": old.id, "operation": "admit-goal"},
        basis_refs=(_evidence_ref("evidence:admit-old"),),
    )
    runtime.decisions.record(admit_old)
    runtime.strategy.register_goal(
        old,
        mandate_id=mandate.id,
        decision_id=admit_old.id,
    )

    assessment = runtime.strategy.assess_goal(
        old.id,
        disposition="revise",
        basis_refs=("evidence:strategy-revise",),
    )
    revise_decision = Decision(
        id="decision:require-revision",
        subject="service",
        decided_by="owner",
        selected={
            "target_ref": old.id,
            "operation": "transition-goal",
            "to_status": "revision-required",
            "assessment_id": assessment.id,
        },
        basis_refs=(_evidence_ref("evidence:strategy-revise"),),
    )
    runtime.decisions.record(revise_decision)
    runtime.strategy.transition_goal(
        old.id,
        to_status="revision-required",
        assessment_id=assessment.id,
        decision_id=revise_decision.id,
        basis_refs=("evidence:strategy-revise",),
    )

    successor = Goal(
        id="goal:new",
        subject="service",
        desired_state={"latency": "<350ms"},
        basis_refs=(_evidence_ref("evidence:goal-new"),),
    )
    admit_new = Decision(
        id="decision:admit-new",
        subject="service",
        decided_by="owner",
        selected={
            "target_ref": successor.id,
            "operation": "admit-goal",
            "supersedes_goal_id": old.id,
        },
        basis_refs=(_evidence_ref("evidence:admit-new"),),
    )
    runtime.decisions.record(admit_new)
    runtime.strategy.supersede_goal(
        old.id,
        successor,
        _revision(
            "revision:goal",
            target=successor.ref,
            previous=old.ref,
        ),
        mandate_id=mandate.id,
        decision_id=admit_new.id,
    )

    assert runtime.strategy.get_goal(old.id)["status"] == "retired"
    assert runtime.strategy.get_current_goal(old.id)["id"] == successor.id
    with pytest.raises(ValueError, match="superseded"):
        runtime.strategy.assess_goal(
            old.id,
            disposition="continue",
            basis_refs=("evidence:late",),
        )


def test_decision_revocation_preserves_history_but_removes_current_applicability() -> None:
    runtime = WorldRuntime.sqlite()
    decision = Decision(
        id="decision:revocable",
        subject="resource:revocable",
        decided_by="owner",
        selected={
            "target_ref": "resource:revocable",
            "operation": "authorize-effect",
            "action": "deploy",
        },
        basis_refs=(_evidence_ref("evidence:decision-revocable"),),
    )
    runtime.decisions.record(decision)
    runtime.decisions.revoke(
        decision.id,
        reason="policy withdrawn",
        basis_refs=("evidence:decision-revoked",),
    )

    assert runtime.decisions.get(decision.id)["id"] == decision.id
    with pytest.raises(ValueError, match="revoked"):
        runtime.decisions.assert_current(decision.id)
    events = runtime.ledger.events(stream=f"decision:{decision.id}")
    assert [event.kind for event in events][-1] == "decision.revoked"


def test_authorization_revocation_is_durable_and_blocks_future_use() -> None:
    runtime = WorldRuntime.sqlite()
    mandate = Mandate(
        id="mandate:authorization-revoke",
        principal="owner",
        scope={"resource": "resource:1"},
        authority_ceiling={"action": "deploy", "resource": "resource:1"},
    )
    runtime.governance.register_mandate(mandate)
    decision = Decision(
        id="decision:authorization-revoke",
        subject="resource:1",
        decided_by="owner",
        selected={
            "target_ref": "resource:1",
            "operation": "authorize-effect",
            "action": "deploy",
        },
        basis_refs=(_evidence_ref("evidence:authorization-revoke"),),
    )
    runtime.decisions.record(decision)
    authorization = runtime.governance.issue_authorization(
        authorization_id="authorization:revocable",
        principal="owner",
        action="deploy",
        resource="resource:1",
        mandate_id=mandate.id,
        decision_id=decision.id,
    )
    runtime.governance.record_use(
        authorization.id,
        effect_request_id="request:before-revoke",
    )
    runtime.governance.revoke_authorization(
        authorization.id,
        reason="authority withdrawn",
        basis_refs=("evidence:authorization-withdrawn",),
    )

    stored = runtime.ledger.project_get(
        "governance.authorization",
        authorization.id,
    )
    assert stored is not None
    assert stored[0]["status"] == "revoked"
    assert stored[0]["uses"] == 1
    with pytest.raises(PermissionError, match="not active"):
        runtime.governance.assert_usable(
            authorization.id,
            principal="owner",
            action="deploy",
            resource="resource:1",
        )
    with pytest.raises(PermissionError, match="not active"):
        runtime.governance.record_use(
            authorization.id,
            effect_request_id="request:after-revoke",
        )
    events = runtime.ledger.events(stream=f"authorization:{authorization.id}")
    assert [event.kind for event in events] == [
        "governance.authorization.issued",
        "governance.authorization.used",
        "governance.authorization.revoked",
    ]


def test_mandate_revocation_is_append_only_history() -> None:
    runtime = WorldRuntime.sqlite()
    mandate = Mandate(
        id="mandate:revocation-history",
        principal="owner",
        authority_ceiling={"action": "*", "resource": "*"},
    )
    runtime.governance.register_mandate(mandate)
    runtime.governance.revoke_mandate(
        mandate.id,
        reason="institutional authority ended",
    )

    events = runtime.ledger.events(stream=f"mandate:{mandate.id}")
    assert [event.kind for event in events] == [
        "governance.mandate.registered",
        "governance.mandate.revoked",
    ]


def test_strategy_reassessment_requires_explicit_single_head_lineage() -> None:
    runtime = WorldRuntime.sqlite()
    mandate = Mandate(id="mandate:reassessment", principal="owner")
    runtime.governance.register_mandate(mandate)
    goal = Goal(
        id="goal:reassessment",
        subject="service",
        desired_state={"latency": "<500ms"},
        basis_refs=(_evidence_ref("evidence:goal-reassessment"),),
    )
    decision = Decision(
        id="decision:admit-reassessment",
        subject="service",
        decided_by="owner",
        selected={"target_ref": goal.id, "operation": "admit-goal"},
        basis_refs=(_evidence_ref("evidence:admit-reassessment"),),
    )
    runtime.decisions.record(decision)
    runtime.strategy.register_goal(
        goal,
        mandate_id=mandate.id,
        decision_id=decision.id,
    )
    first = runtime.strategy.assess_goal(
        goal.id,
        disposition="continue",
        basis_refs=("evidence:first-assessment",),
        rationale="initial evidence supports continuation",
    )

    with pytest.raises(ValueError, match="explicitly supersede"):
        runtime.strategy.assess_goal(
            goal.id,
            disposition="revise",
            basis_refs=("evidence:second-assessment",),
        )

    second = runtime.strategy.assess_goal(
        goal.id,
        disposition="revise",
        basis_refs=("evidence:second-assessment",),
        rationale="new evidence requires revision",
        supersedes_assessment_id=first.id,
        revision_reason="new evidence invalidated the first strategic assessment",
        revision_basis_refs=("evidence:second-assessment",),
    )

    assert runtime.strategy.get_assessment(first.id).id == first.id
    assert runtime.strategy.get_current_assessment(first.id).id == second.id
    assert runtime.strategy.latest_assessment(goal.id).id == second.id
    assert runtime.lineage.is_current(runtime.strategy.assessment_ref(first.id)) is False
    assert runtime.lineage.is_current(runtime.strategy.assessment_ref(second.id)) is True
