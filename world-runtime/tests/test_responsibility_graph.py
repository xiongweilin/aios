import pytest
from semantic_language import Decision, Responsibility, SemanticKind, SemanticRef

from world_runtime import WorldRuntime


def _evidence(identifier: str) -> SemanticRef:
    return SemanticRef(SemanticKind.EVIDENCE, identifier)


def _responsibility(
    runtime: WorldRuntime,
    identifier: str,
    *,
    domain: str,
) -> Responsibility:
    item = Responsibility(
        id=identifier,
        principal="owner",
        subject=identifier,
        scope={"case": identifier},
    )
    runtime.responsibility.create(item, domain=domain)
    return item


def _decision(
    runtime: WorldRuntime,
    identifier: str,
    *,
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
        basis_refs=(_evidence(f"evidence:{identifier}"),),
    )
    runtime.decisions.record(decision)
    return decision


def _discharge(runtime: WorldRuntime, responsibility_id: str) -> None:
    runtime.responsibility.assess(
        responsibility_id,
        status="satisfied",
        basis_refs=(f"evidence:{responsibility_id}:satisfied",),
    )
    decision = _decision(
        runtime,
        f"decision:discharge:{responsibility_id}",
        target_ref=responsibility_id,
        operation="discharge-responsibility",
        to_status="discharged",
    )
    runtime.responsibility.discharge(responsibility_id, decision_id=decision.id)


def test_hard_dependency_blocks_parent_until_required_responsibility_is_discharged() -> None:
    runtime = WorldRuntime.sqlite()
    parent = _responsibility(runtime, "responsibility:parent", domain="operations")
    child = _responsibility(runtime, "responsibility:child", domain="development")
    decision = _decision(
        runtime,
        "decision:relate",
        target_ref=parent.id,
        operation="relate-responsibility",
        target_responsibility_id=child.id,
        relation="requires",
    )

    relation = runtime.responsibility_graph.create(
        parent.id,
        child.id,
        relation="requires",
        decision_id=decision.id,
        basis_refs=("evidence:dependency",),
        relation_id="responsibility-relation:parent-child",
    )

    assert relation.relation == "requires"
    assert runtime.responsibility_graph.list_from(parent.id) == (relation,)

    with pytest.raises(ValueError, match="unresolved required dependencies"):
        runtime.responsibility.assess(
            parent.id,
            status="satisfied",
            basis_refs=("evidence:parent",),
        )

    _discharge(runtime, child.id)
    runtime.responsibility.assess(
        parent.id,
        status="satisfied",
        basis_refs=("evidence:parent",),
    )
    assert runtime.responsibility.get(parent.id).status == "satisfied"


def test_contributes_to_relation_does_not_become_hidden_completion_authority() -> None:
    runtime = WorldRuntime.sqlite()
    parent = _responsibility(runtime, "responsibility:parent", domain="operations")
    contributor = _responsibility(runtime, "responsibility:contributor", domain="development")
    decision = _decision(
        runtime,
        "decision:contributes",
        target_ref=parent.id,
        operation="relate-responsibility",
        target_responsibility_id=contributor.id,
        relation="contributes-to",
    )
    runtime.responsibility_graph.create(
        parent.id,
        contributor.id,
        relation="contributes-to",
        decision_id=decision.id,
        basis_refs=("evidence:contribution",),
    )

    runtime.responsibility.assess(
        parent.id,
        status="satisfied",
        basis_refs=("evidence:parent",),
    )
    assert runtime.responsibility.get(parent.id).status == "satisfied"
    assert runtime.responsibility.get(contributor.id).status == "active"


def test_requires_graph_rejects_cycles_across_domains() -> None:
    runtime = WorldRuntime.sqlite()
    a = _responsibility(runtime, "responsibility:a", domain="operations")
    b = _responsibility(runtime, "responsibility:b", domain="development")
    c = _responsibility(runtime, "responsibility:c", domain="administrative")

    for identifier, source, target in (
        ("decision:a-b", a.id, b.id),
        ("decision:b-c", b.id, c.id),
    ):
        decision = _decision(
            runtime,
            identifier,
            target_ref=source,
            operation="relate-responsibility",
            target_responsibility_id=target,
            relation="requires",
        )
        runtime.responsibility_graph.create(
            source,
            target,
            relation="requires",
            decision_id=decision.id,
            basis_refs=(f"evidence:{identifier}",),
        )

    cycle = _decision(
        runtime,
        "decision:c-a",
        target_ref=c.id,
        operation="relate-responsibility",
        target_responsibility_id=a.id,
        relation="requires",
    )
    with pytest.raises(ValueError, match="cycle"):
        runtime.responsibility_graph.create(
            c.id,
            a.id,
            relation="requires",
            decision_id=cycle.id,
            basis_refs=("evidence:cycle",),
        )


def test_dependency_retirement_is_explicit_and_preserves_history() -> None:
    runtime = WorldRuntime.sqlite()
    parent = _responsibility(runtime, "responsibility:parent", domain="operations")
    child = _responsibility(runtime, "responsibility:child", domain="development")
    create_decision = _decision(
        runtime,
        "decision:relate",
        target_ref=parent.id,
        operation="relate-responsibility",
        target_responsibility_id=child.id,
        relation="requires",
    )
    relation = runtime.responsibility_graph.create(
        parent.id,
        child.id,
        relation="requires",
        decision_id=create_decision.id,
        basis_refs=("evidence:create",),
        relation_id="responsibility-relation:retirable",
    )

    retire_decision = _decision(
        runtime,
        "decision:retire",
        target_ref=relation.id,
        operation="retire-responsibility-relation",
    )
    retired = runtime.responsibility_graph.retire(
        relation.id,
        decision_id=retire_decision.id,
        basis_refs=("evidence:retire",),
    )

    assert retired.status == "retired"
    assert runtime.responsibility_graph.list_from(parent.id) == ()
    assert runtime.responsibility_graph.list_from(parent.id, active_only=False) == (retired,)
    events = runtime.ledger.events(stream=f"responsibility-relation:{relation.id}")
    assert [event.kind for event in events] == [
        "responsibility.relation.created",
        "responsibility.relation.retired",
    ]

    runtime.responsibility.assess(
        parent.id,
        status="satisfied",
        basis_refs=("evidence:parent",),
    )


def test_state_bundle_preserves_responsibility_graph_and_dependency_behavior() -> None:
    source = WorldRuntime.sqlite()
    parent = _responsibility(source, "responsibility:parent", domain="operations")
    child = _responsibility(source, "responsibility:child", domain="development")
    decision = _decision(
        source,
        "decision:relate",
        target_ref=parent.id,
        operation="relate-responsibility",
        target_responsibility_id=child.id,
        relation="requires",
    )
    source.responsibility_graph.create(
        parent.id,
        child.id,
        relation="requires",
        decision_id=decision.id,
        basis_refs=("evidence:dependency",),
        relation_id="responsibility-relation:portable",
    )

    bundle = source.state_bundle.export()
    restored = WorldRuntime.sqlite()
    restored.state_bundle.import_bundle(bundle)

    relation = restored.responsibility_graph.get("responsibility-relation:portable")
    assert relation.source_responsibility_id == parent.id
    assert relation.target_responsibility_id == child.id
    with pytest.raises(ValueError, match="unresolved required dependencies"):
        restored.responsibility.assess(
            parent.id,
            status="satisfied",
            basis_refs=("evidence:parent",),
        )


def test_responsibility_relation_rejects_invalid_identity_and_cross_principal_edges() -> None:
    runtime = WorldRuntime.sqlite()
    parent = _responsibility(runtime, "responsibility:edge-parent", domain="operations")
    child = _responsibility(runtime, "responsibility:edge-child", domain="development")

    with pytest.raises(ValueError, match="cannot target itself"):
        runtime.responsibility_graph.create(
            parent.id,
            parent.id,
            relation="requires",
            decision_id="decision:unused",
            basis_refs=("evidence:self",),
        )

    decision = _decision(
        runtime,
        "decision:edge",
        target_ref=parent.id,
        operation="relate-responsibility",
        target_responsibility_id=child.id,
        relation="requires",
    )
    with pytest.raises(ValueError, match="requires basis refs"):
        runtime.responsibility_graph.create(
            parent.id,
            child.id,
            relation="requires",
            decision_id=decision.id,
            basis_refs=(),
        )

    other = Responsibility(
        id="responsibility:other-principal",
        principal="other-owner",
        subject="other-principal",
    )
    runtime.responsibility.create(other, domain="finance")
    other_decision = _decision(
        runtime,
        "decision:cross-principal",
        target_ref=parent.id,
        operation="relate-responsibility",
        target_responsibility_id=other.id,
        relation="requires",
    )
    with pytest.raises(ValueError, match="cross-principal"):
        runtime.responsibility_graph.create(
            parent.id,
            other.id,
            relation="requires",
            decision_id=other_decision.id,
            basis_refs=("evidence:cross-principal",),
        )


def test_responsibility_relation_identity_is_idempotent_but_cannot_rebind() -> None:
    runtime = WorldRuntime.sqlite()
    parent = _responsibility(runtime, "responsibility:identity-parent", domain="operations")
    child = _responsibility(runtime, "responsibility:identity-child", domain="development")
    decision = _decision(
        runtime,
        "decision:identity",
        target_ref=parent.id,
        operation="relate-responsibility",
        target_responsibility_id=child.id,
        relation="requires",
    )
    relation = runtime.responsibility_graph.create(
        parent.id,
        child.id,
        relation="requires",
        decision_id=decision.id,
        basis_refs=("evidence:identity",),
        relation_id="responsibility-relation:identity",
    )
    replay = runtime.responsibility_graph.create(
        parent.id,
        child.id,
        relation="requires",
        decision_id=decision.id,
        basis_refs=("evidence:identity",),
        relation_id=relation.id,
    )
    assert replay == relation
    assert runtime.responsibility_graph.list_to(child.id) == (relation,)

    different = _responsibility(
        runtime,
        "responsibility:identity-different",
        domain="administrative",
    )
    rebound_decision = _decision(
        runtime,
        "decision:identity-rebound",
        target_ref=parent.id,
        operation="relate-responsibility",
        target_responsibility_id=different.id,
        relation="requires",
    )
    with pytest.raises(ValueError, match="identity rebound"):
        runtime.responsibility_graph.create(
            parent.id,
            different.id,
            relation="requires",
            decision_id=rebound_decision.id,
            basis_refs=("evidence:identity",),
            relation_id=relation.id,
        )
