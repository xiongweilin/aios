import pytest

from world_runtime import WorldRuntime


def test_dependency_change_creates_targeted_review_not_silent_invalidation() -> None:
    runtime = WorldRuntime.sqlite()
    dependency = runtime.qualification.register_dependency(
        principal="owner",
        dependency_id="qualification-dependency:policy",
        subject_ref="decision:pricing",
        dependency_ref="policy:pricing",
        dependency_version="v1",
        assumption="pricing policy remains applicable",
        scope={"market": "jp"},
        review_policy={"on_change": "revalidate"},
        basis_refs=("evidence:policy-v1",),
    )

    obligations = runtime.qualification.observe_dependency_change(
        principal="owner",
        dependency_ref="policy:pricing",
        observed_version="v2",
        basis_refs=("evidence:policy-v2",),
        reason="pricing policy changed",
    )

    assert len(obligations) == 1
    obligation = obligations[0]
    assert obligation.dependency_id == dependency.id
    assert obligation.required_action == "revalidate"
    assert runtime.qualification.get_dependency(dependency.id).status == "active"


def test_same_observed_change_is_idempotent_and_new_change_creates_new_review() -> None:
    runtime = WorldRuntime.sqlite()
    runtime.qualification.register_dependency(
        principal="owner",
        dependency_id="qualification-dependency:vendor",
        subject_ref="experience:vendor-a",
        dependency_ref="vendor:sla",
        dependency_version="2026-01",
        assumption="SLA remains unchanged",
        basis_refs=("evidence:sla-old",),
    )

    first = runtime.qualification.observe_dependency_change(
        principal="owner",
        dependency_ref="vendor:sla",
        observed_version="2026-06",
        basis_refs=("evidence:sla-new",),
    )
    replay = runtime.qualification.observe_dependency_change(
        principal="owner",
        dependency_ref="vendor:sla",
        observed_version="2026-06",
        basis_refs=("evidence:sla-new",),
    )
    later = runtime.qualification.observe_dependency_change(
        principal="owner",
        dependency_ref="vendor:sla",
        observed_version="2026-09",
        basis_refs=("evidence:sla-later",),
    )

    assert first[0].id == replay[0].id
    assert later[0].id != first[0].id
    assert len(runtime.qualification.open_obligations()) == 2


def test_review_assessment_does_not_automatically_mutate_owned_subject() -> None:
    runtime = WorldRuntime.sqlite()
    runtime.qualification.register_dependency(
        principal="owner",
        dependency_id="qualification-dependency:authority",
        subject_ref="mandate:operations",
        dependency_ref="authority-source:owner",
        dependency_version="epoch-1",
        assumption="owner authority remains current",
        review_policy={"on_change": "reauthorize"},
        basis_refs=("evidence:epoch-1",),
    )
    obligation = runtime.qualification.observe_dependency_change(
        principal="owner",
        dependency_ref="authority-source:owner",
        observed_version="epoch-2",
        basis_refs=("evidence:epoch-2",),
    )[0]

    assessment = runtime.qualification.assess_review(
        obligation.id,
        assessment_id="revalidation-assessment:authority",
        disposition="reauthorize",
        basis_refs=("evidence:review",),
        rationale="authority changed and requires explicit reauthorization",
    )

    assert assessment.disposition == "reauthorize"
    assessed = runtime.qualification.get_obligation(obligation.id)
    assert assessed.status == "assessed"
    assert assessed.assessment_id == assessment.id
    assert runtime.qualification.open_obligations() == ()
    assert runtime.qualification.pending_obligations() == (assessed,)

    resolved = runtime.qualification.resolve_review(
        obligation.id,
        resolution_ref="mandate:operations:v2",
        basis_refs=("evidence:reauthorized",),
    )
    assert resolved.status == "resolved"
    assert resolved.resolution_ref == "mandate:operations:v2"
    assert runtime.qualification.pending_obligations() == ()


def test_dependency_replacement_preserves_historical_basis() -> None:
    runtime = WorldRuntime.sqlite()
    old = runtime.qualification.register_dependency(
        principal="owner",
        dependency_id="qualification-dependency:old",
        subject_ref="decision:supply",
        dependency_ref="contract:vendor",
        dependency_version="v1",
        assumption="commercial terms remain valid",
        scope={"vendor": "A"},
        basis_refs=("evidence:contract-v1",),
    )
    obligation = runtime.qualification.observe_dependency_change(
        principal="owner",
        dependency_ref="contract:vendor",
        observed_version="v2",
        basis_refs=("evidence:contract-v2",),
    )[0]
    assessment = runtime.qualification.assess_review(
        obligation.id,
        assessment_id="revalidation-assessment:contract",
        disposition="continue",
        basis_refs=("evidence:reviewed-v2",),
    )
    successor = runtime.qualification.supersede_dependency_after_review(
        old.id,
        obligation_id=obligation.id,
        assessment_id=assessment.id,
        new_version="v2",
        basis_refs=("evidence:reviewed-v2",),
        successor_id="qualification-dependency:new",
    )

    assert runtime.qualification.get_dependency(old.id).status == "superseded"
    assert successor.status == "active"
    assert successor.supersedes_dependency_id == old.id

    third = runtime.qualification.observe_dependency_change(
        principal="owner",
        dependency_ref="contract:vendor",
        observed_version="v3",
        basis_refs=("evidence:contract-v3",),
    )
    assert len(third) == 1
    assert third[0].dependency_id == successor.id


def test_qualification_state_survives_bundle_restore() -> None:
    source = WorldRuntime.sqlite()
    source.qualification.register_dependency(
        principal="owner",
        dependency_id="qualification-dependency:portable",
        subject_ref="goal:portable",
        dependency_ref="market:assumption",
        dependency_version="v1",
        assumption="market remains open",
        basis_refs=("evidence:market",),
    )
    obligation = source.qualification.observe_dependency_change(
        principal="owner",
        dependency_ref="market:assumption",
        observed_version="v2",
        basis_refs=("evidence:market-v2",),
    )[0]

    bundle = source.state_bundle.export()
    restored = WorldRuntime.sqlite()
    restored.state_bundle.import_bundle(bundle)

    assert restored.qualification.get_obligation(obligation.id).status == "open"
    assert restored.qualification.open_obligations()[0].subject_ref == "goal:portable"


def test_review_cannot_be_assessed_twice() -> None:
    runtime = WorldRuntime.sqlite()
    runtime.qualification.register_dependency(
        principal="owner",
        dependency_id="qualification-dependency:once",
        subject_ref="decision:once",
        dependency_ref="policy:once",
        dependency_version="1",
        assumption="policy remains stable",
        basis_refs=("evidence:1",),
    )
    obligation = runtime.qualification.observe_dependency_change(
        principal="owner",
        dependency_ref="policy:once",
        observed_version="2",
        basis_refs=("evidence:2",),
    )[0]
    runtime.qualification.assess_review(
        obligation.id,
        disposition="continue",
        basis_refs=("evidence:review",),
    )

    with pytest.raises(ValueError, match="already resolved"):
        runtime.qualification.assess_review(
            obligation.id,
            disposition="continue",
            basis_refs=("evidence:review-again",),
        )


def test_non_continue_review_cannot_replace_dependency_before_owning_action_resolves() -> None:
    runtime = WorldRuntime.sqlite()
    old = runtime.qualification.register_dependency(
        principal="owner",
        dependency_id="qualification-dependency:reauthorize",
        subject_ref="authorization:long-lived",
        dependency_ref="authority-source:owner",
        dependency_version="epoch-1",
        assumption="owner authority remains current",
        review_policy={"on_change": "reauthorize"},
        basis_refs=("evidence:epoch-1",),
    )
    obligation = runtime.qualification.observe_dependency_change(
        principal="owner",
        dependency_ref="authority-source:owner",
        observed_version="epoch-2",
        basis_refs=("evidence:epoch-2",),
    )[0]
    assessment = runtime.qualification.assess_review(
        obligation.id,
        disposition="reauthorize",
        basis_refs=("evidence:review",),
    )

    with pytest.raises(ValueError, match="must be resolved"):
        runtime.qualification.supersede_dependency_after_review(
            old.id,
            obligation_id=obligation.id,
            assessment_id=assessment.id,
            new_version="epoch-2",
            basis_refs=("evidence:new-authority",),
        )

    runtime.qualification.resolve_review(
        obligation.id,
        resolution_ref="authorization:replacement",
        basis_refs=("evidence:new-authority",),
    )
    successor = runtime.qualification.supersede_dependency_after_review(
        old.id,
        obligation_id=obligation.id,
        assessment_id=assessment.id,
        new_version="epoch-2",
        basis_refs=("evidence:new-authority",),
        successor_id="qualification-dependency:reauthorize:v2",
    )
    assert successor.dependency_version == "epoch-2"


def test_continue_review_is_resolved_by_assessment_without_mutating_subject() -> None:
    runtime = WorldRuntime.sqlite()
    runtime.qualification.register_dependency(
        principal="owner",
        dependency_id="qualification-dependency:continue",
        subject_ref="decision:continue",
        dependency_ref="policy:continue",
        dependency_version="v1",
        assumption="change remains compatible",
        basis_refs=("evidence:v1",),
    )
    obligation = runtime.qualification.observe_dependency_change(
        principal="owner",
        dependency_ref="policy:continue",
        observed_version="v2",
        basis_refs=("evidence:v2",),
    )[0]
    assessment = runtime.qualification.assess_review(
        obligation.id,
        disposition="continue",
        basis_refs=("evidence:reviewed",),
    )

    resolved = runtime.qualification.get_obligation(obligation.id)
    assert resolved.status == "resolved"
    assert resolved.resolution_ref == assessment.id
    assert runtime.qualification.pending_obligations() == ()
