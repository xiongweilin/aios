import pytest
from semantic_language import Responsibility, SemanticKind, SemanticRef

from world_runtime import DomainAssignment, WorldRuntime


def test_domain_assignment_is_idempotent_across_acceptance() -> None:
    runtime = WorldRuntime.sqlite()
    responsibility = Responsibility(
        id="responsibility:domain-test",
        principal="controller:test",
        subject="bounded domain work",
    )
    runtime.responsibility.create(responsibility, domain="test-domain")
    assignment = DomainAssignment(
        id="assignment:test",
        responsibility_ref=responsibility.id,
        domain="test-domain",
        controller="controller:test-domain",
        resource_budget={"tokens": 10},
    )

    runtime.domains.offer(assignment)
    runtime.domains.report(
        assignment.id,
        kind="accepted",
        report_id="report:test:accepted",
    )
    replay = runtime.domains.offer(assignment)

    assert replay.status == "active"
    assert [item.kind for item in runtime.domains.reports(assignment.id)] == ["accepted"]


def test_domain_outcome_candidate_requires_domain_evidence_and_identity() -> None:
    runtime = WorldRuntime.sqlite()
    responsibility = Responsibility(
        id="responsibility:domain-outcome",
        principal="controller:test",
        subject="bounded domain outcome",
    )
    runtime.responsibility.create(responsibility, domain="test-domain")
    assignment = runtime.domains.offer(
        DomainAssignment(
            id="assignment:outcome",
            responsibility_ref=responsibility.id,
            domain="test-domain",
            controller="controller:test-domain",
        )
    )
    runtime.domains.report(
        assignment.id,
        kind="accepted",
        report_id="report:outcome:accepted",
    )
    report = runtime.domains.report(
        assignment.id,
        kind="outcome-candidate",
        evidence_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:domain-verification"),),
        outcome_refs=(
            SemanticRef(
                SemanticKind.OUTCOME,
                "outcome:1",
                namespace="test-domain",
            ),
        ),
        report_id="report:outcome:candidate",
    )

    assert report.outcome_refs[0].kind is SemanticKind.OUTCOME
    assert report.outcome_refs[0].namespace == "test-domain"
    assert runtime.responsibility.get(responsibility.id).status == "active"


def test_completion_requires_prior_acceptance_and_old_accept_replay_is_idempotent() -> None:
    runtime = WorldRuntime.sqlite()
    responsibility = Responsibility(
        id="responsibility:domain-transition",
        principal="controller:test",
        subject="bounded transition",
    )
    runtime.responsibility.create(responsibility, domain="test-domain")
    assignment = runtime.domains.offer(
        DomainAssignment(
            id="assignment:transition",
            responsibility_ref=responsibility.id,
            domain="test-domain",
            controller="controller:test-domain",
        )
    )

    try:
        runtime.domains.report(
            assignment.id,
            kind="completion-proposal",
            evidence_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:premature"),),
            report_id="report:premature",
        )
    except ValueError as exc:
        assert "does not admit" in str(exc)
    else:
        raise AssertionError("completion proposal must fail before assignment acceptance")

    runtime.domains.report(
        assignment.id,
        kind="accepted",
        report_id="report:transition:accepted",
    )
    runtime.domains.report(
        assignment.id,
        kind="completion-proposal",
        evidence_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:verified"),),
        report_id="report:transition:completion",
    )

    replay = runtime.domains.report(
        assignment.id,
        kind="accepted",
        report_id="report:transition:accepted",
    )
    assert replay.kind == "accepted"
    assert runtime.domains.get(assignment.id).status == "completion-proposed"


def test_rejected_is_only_valid_from_offered_and_assignment_status_is_runtime_owned() -> None:
    runtime = WorldRuntime.sqlite()
    responsibility = Responsibility(
        id="responsibility:reject-state",
        principal="controller:test",
        subject="bounded transition",
    )
    runtime.responsibility.create(responsibility, domain="test-domain")

    with pytest.raises(TypeError):
        DomainAssignment(
            id="assignment:forged-status",
            responsibility_ref=responsibility.id,
            domain="test-domain",
            controller="controller:test-domain",
            status="completion-proposed",
        )

    assignment = runtime.domains.offer(
        DomainAssignment(
            id="assignment:reject-state",
            responsibility_ref=responsibility.id,
            domain="test-domain",
            controller="controller:test-domain",
        )
    )
    runtime.domains.report(
        assignment.id,
        kind="accepted",
        report_id="report:reject-state:accepted",
    )
    with pytest.raises(ValueError, match="does not admit"):
        runtime.domains.report(
            assignment.id,
            kind="rejected",
            report_id="report:reject-state:rejected",
        )


def test_domain_report_requires_typed_evidence_and_namespaced_outcome_refs() -> None:
    runtime = WorldRuntime.sqlite()
    responsibility = Responsibility(
        id="responsibility:typed-refs",
        principal="controller:test",
        subject="typed refs",
    )
    runtime.responsibility.create(responsibility, domain="test-domain")
    assignment = runtime.domains.offer(
        DomainAssignment(
            id="assignment:typed-refs",
            responsibility_ref=responsibility.id,
            domain="test-domain",
            controller="controller:test-domain",
        )
    )
    runtime.domains.report(
        assignment.id,
        kind="accepted",
        report_id="report:typed-refs:accepted",
    )

    with pytest.raises(ValueError, match="Evidence refs"):
        runtime.domains.report(
            assignment.id,
            kind="outcome-candidate",
            report_id="report:typed-refs:bad-evidence",
            evidence_refs=(SemanticRef(SemanticKind.GOAL, "goal:not-evidence"),),
            outcome_refs=(
                SemanticRef(
                    SemanticKind.OUTCOME,
                    "outcome:1",
                    namespace="test-domain",
                ),
            ),
        )

    with pytest.raises(ValueError, match="domain namespace"):
        runtime.domains.report(
            assignment.id,
            kind="outcome-candidate",
            report_id="report:typed-refs:bad-outcome",
            evidence_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:1"),),
            outcome_refs=(SemanticRef(SemanticKind.OUTCOME, "outcome:1"),),
        )
