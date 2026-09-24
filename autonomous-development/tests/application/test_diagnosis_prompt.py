from datetime import UTC, datetime

from autonomous_development.application.diagnosis import _diagnosis_prompt
from autonomous_development.domain.enums import FeedbackKind
from autonomous_development.domain.models import (
    EvidenceWindow,
    MutationPolicy,
    ProductObjectiveRevision,
    UserFeedback,
)


def test_diagnosis_prompt_names_exact_structured_output_contract() -> None:
    objective = ProductObjectiveRevision(
        id="objective-1",
        target_id="target-1",
        statement="bounded objective",
        acceptance_criteria=("criterion",),
        primary_metrics=("metric",),
        reliability_constraints=("reliability",),
        performance_constraints=("performance",),
        security_constraints=("security",),
        mutation_policy=MutationPolicy(allowed_paths=("app.py",)),
        created_at=datetime.now(UTC),
    )
    window = EvidenceWindow(
        id="window-1",
        target_id="target-1",
        release_ids=("release-1",),
        opened_at=datetime.now(UTC),
        closed_at=datetime.now(UTC),
        telemetry_refs=("telemetry:1",),
        feedback_refs=("feedback:1",),
    )
    feedback = UserFeedback(
        id="feedback-1",
        target_id="target-1",
        received_at=datetime.now(UTC),
        kind=FeedbackKind.EXPLICIT,
        category="incorrect-result",
        severity=4,
        provenance="feedback-api",
        release_id="release-1",
        free_text="wrong result",
    )

    prompt = _diagnosis_prompt(window, objective, (feedback,))

    assert "exactly one JSON object with these ten keys and no others" in prompt
    assert "observed_problem, affected_journey, confidence" in prompt
    assert "Do not use alternate wrappers or fields" in prompt
    assert "confidence` must be a JSON number between 0 and 1" in prompt
