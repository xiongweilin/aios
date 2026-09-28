import pytest

from world_runtime import WorldRuntime


def _binding(runtime: WorldRuntime, *, identifier: str, dependency_ref: str, version: str = "v1", review_action: str = "review"):
    return runtime.qualification.register_binding(
        principal="owner",
        binding_id=identifier,
        subject_ref=f"subject:{identifier}",
        dependency_ref=dependency_ref,
        dependency_version=version,
        assumption="dependency remains applicable",
        review_policy={"on_change": review_action},
        basis_refs=(f"evidence:{version}",),
    )


def test_dependency_change_creates_review_without_invalidating_binding() -> None:
    runtime = WorldRuntime.sqlite()
    binding = _binding(
        runtime,
        identifier="qualification-binding:policy",
        dependency_ref="policy:pricing",
        review_action="revalidate",
    )

    reviews = runtime.qualification.observe_dependency_change(
        principal="owner",
        dependency_ref="policy:pricing",
        observed_version="v2",
        basis_refs=("evidence:policy-v2",),
        reason="pricing policy changed",
    )

    assert len(reviews) == 1
    review = reviews[0]
    assert review.binding_id == binding.id
    assert review.required_action == "revalidate"
    assert runtime.qualification.get_binding(binding.id).status == "active"


def test_same_change_is_idempotent_and_new_version_creates_new_review() -> None:
    runtime = WorldRuntime.sqlite()
    _binding(
        runtime,
        identifier="qualification-binding:vendor",
        dependency_ref="vendor:sla",
        version="2026-01",
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
    assert len(runtime.qualification.open_reviews()) == 2


def test_assessment_and_resolution_are_distinct_states_on_one_review() -> None:
    runtime = WorldRuntime.sqlite()
    _binding(
        runtime,
        identifier="qualification-binding:authority",
        dependency_ref="authority-source:owner",
        version="epoch-1",
        review_action="reauthorize",
    )
    review = runtime.qualification.observe_dependency_change(
        principal="owner",
        dependency_ref="authority-source:owner",
        observed_version="epoch-2",
        basis_refs=("evidence:epoch-2",),
    )[0]

    assessed = runtime.qualification.assess_review(
        review.id,
        assessment_id="review-assessment:authority",
        disposition="reauthorize",
        basis_refs=("evidence:review",),
        rationale="authority changed and requires explicit reauthorization",
    )

    assert assessed.status == "assessed"
    assert assessed.assessment_id == "review-assessment:authority"
    assert assessed.disposition == "reauthorize"
    assert runtime.qualification.open_reviews() == ()
    assert runtime.qualification.pending_reviews() == (assessed,)

    resolved = runtime.qualification.resolve_review(
        review.id,
        resolution_ref="mandate:operations:v2",
        basis_refs=("evidence:reauthorized",),
    )
    assert resolved.status == "resolved"
    assert resolved.resolution_ref == "mandate:operations:v2"
    assert runtime.qualification.pending_reviews() == ()


def test_binding_replacement_requires_resolved_review_and_preserves_lineage() -> None:
    runtime = WorldRuntime.sqlite()
    old = _binding(
        runtime,
        identifier="qualification-binding:contract",
        dependency_ref="contract:vendor",
    )
    review = runtime.qualification.observe_dependency_change(
        principal="owner",
        dependency_ref="contract:vendor",
        observed_version="v2",
        basis_refs=("evidence:contract-v2",),
    )[0]
    resolved = runtime.qualification.assess_review(
        review.id,
        disposition="continue",
        basis_refs=("evidence:reviewed-v2",),
    )

    successor = runtime.qualification.advance_binding_after_review(
        old.id,
        review_id=resolved.id,
        new_version="v2",
        basis_refs=("evidence:reviewed-v2",),
        successor_id="qualification-binding:contract:v2",
    )

    assert runtime.qualification.get_binding(old.id).status == "superseded"
    assert successor.status == "active"
    assert successor.supersedes_binding_id == old.id

    third = runtime.qualification.observe_dependency_change(
        principal="owner",
        dependency_ref="contract:vendor",
        observed_version="v3",
        basis_refs=("evidence:contract-v3",),
    )
    assert len(third) == 1
    assert third[0].binding_id == successor.id


def test_qualification_state_survives_bundle_restore() -> None:
    source = WorldRuntime.sqlite()
    _binding(
        source,
        identifier="qualification-binding:portable",
        dependency_ref="market:assumption",
    )
    review = source.qualification.observe_dependency_change(
        principal="owner",
        dependency_ref="market:assumption",
        observed_version="v2",
        basis_refs=("evidence:market-v2",),
    )[0]

    bundle = source.state_bundle.export()
    restored = WorldRuntime.sqlite()
    restored.state_bundle.import_bundle(bundle)

    assert restored.qualification.get_review(review.id).status == "open"
    assert restored.qualification.open_reviews()[0].binding_id == "qualification-binding:portable"


def test_review_cannot_be_assessed_twice() -> None:
    runtime = WorldRuntime.sqlite()
    _binding(
        runtime,
        identifier="qualification-binding:once",
        dependency_ref="policy:once",
    )
    review = runtime.qualification.observe_dependency_change(
        principal="owner",
        dependency_ref="policy:once",
        observed_version="v2",
        basis_refs=("evidence:2",),
    )[0]
    runtime.qualification.assess_review(
        review.id,
        disposition="continue",
        basis_refs=("evidence:review",),
    )

    with pytest.raises(ValueError, match="already assessed or resolved"):
        runtime.qualification.assess_review(
            review.id,
            disposition="continue",
            basis_refs=("evidence:review-again",),
        )


def test_non_continue_review_cannot_advance_binding_before_resolution() -> None:
    runtime = WorldRuntime.sqlite()
    old = _binding(
        runtime,
        identifier="qualification-binding:reauthorize",
        dependency_ref="authority-source:owner",
        version="epoch-1",
        review_action="reauthorize",
    )
    review = runtime.qualification.observe_dependency_change(
        principal="owner",
        dependency_ref="authority-source:owner",
        observed_version="epoch-2",
        basis_refs=("evidence:epoch-2",),
    )[0]
    assessed = runtime.qualification.assess_review(
        review.id,
        disposition="reauthorize",
        basis_refs=("evidence:review",),
    )

    with pytest.raises(ValueError, match="must be resolved"):
        runtime.qualification.advance_binding_after_review(
            old.id,
            review_id=assessed.id,
            new_version="epoch-2",
            basis_refs=("evidence:new-authority",),
        )

    resolved = runtime.qualification.resolve_review(
        review.id,
        resolution_ref="authorization:replacement",
        basis_refs=("evidence:new-authority",),
    )
    successor = runtime.qualification.advance_binding_after_review(
        old.id,
        review_id=resolved.id,
        new_version="epoch-2",
        basis_refs=("evidence:new-authority",),
        successor_id="qualification-binding:reauthorize:v2",
    )
    assert successor.dependency_version == "epoch-2"


def test_continue_assessment_resolves_review_without_mutating_subject() -> None:
    runtime = WorldRuntime.sqlite()
    _binding(
        runtime,
        identifier="qualification-binding:continue",
        dependency_ref="policy:continue",
    )
    review = runtime.qualification.observe_dependency_change(
        principal="owner",
        dependency_ref="policy:continue",
        observed_version="v2",
        basis_refs=("evidence:v2",),
    )[0]
    resolved = runtime.qualification.assess_review(
        review.id,
        disposition="continue",
        basis_refs=("evidence:reviewed",),
    )

    assert resolved.status == "resolved"
    assert resolved.resolution_ref == resolved.assessment_id
    assert runtime.qualification.pending_reviews() == ()
