from control_plane.epistemic_profile import (
    RepairIntentKind,
    RepairIssueKind,
    RepairTensionKind,
    build_repair_epistemic_profile,
    render_meta_control_directive,
)


def _profile(*, attempt: int, line_endings: bool = False, retry_context: str = ""):
    return build_repair_epistemic_profile(
        controller_ref="controller:test",
        state_version=attempt,
        attempt=attempt,
        attempt_limit=2,
        is_line_ending_cleanup=line_endings,
        has_repo=True,
        has_project=False,
        has_maintenance_capability=line_endings,
        retry_context=retry_context,
    )


def test_first_repair_pass_selects_bounded_evidence_acquisition() -> None:
    profile = _profile(attempt=1)

    assert {issue.kind for issue in profile.issues} == {RepairIssueKind.ACQUISITION_GAP}
    assert profile.self_model.can_attempt("reason.generate")
    assert profile.intent.kind is RepairIntentKind.ACQUIRE_EVIDENCE


def test_reality_failure_changes_next_pass_to_representation_revision() -> None:
    profile = _profile(
        attempt=2,
        retry_context="[verification] status=succeeded; active=true",
    )

    assert RepairIssueKind.CANDIDATE_SPACE_SUSPECTED_INCOMPLETE in {
        issue.kind for issue in profile.issues
    }
    assert RepairTensionKind.REPEATED_REOPEN in {tension.kind for tension in profile.tensions}
    assert RepairTensionKind.PERSISTENT_RESIDUAL in {tension.kind for tension in profile.tensions}
    assert profile.intent.kind is RepairIntentKind.REVISE_REPRESENTATION
    directive = render_meta_control_directive(profile)
    assert "META_INTENT=REVISE_REPRESENTATION" in directive
    assert "authorizes no effect" in directive


def test_line_ending_incident_is_representation_mismatch_not_semantic_failure() -> None:
    profile = _profile(attempt=1, line_endings=True)

    assert RepairIssueKind.REPRESENTATION_MISMATCH in {issue.kind for issue in profile.issues}
    assert RepairTensionKind.REPRESENTATION_INSTABILITY in {
        tension.kind for tension in profile.tensions
    }
    statements = "\n".join(candidate.statement for candidate in profile.candidates)
    assert "line-ending noise" in statements
    assert "semantic content change" in statements
    assert profile.intent.kind is RepairIntentKind.REVISE_REPRESENTATION


def test_self_model_capability_beliefs_do_not_encode_authority() -> None:
    profile = _profile(attempt=1)

    reason = profile.self_model.capability("reason.generate")
    shell = profile.self_model.capability("shell.exec")
    assert reason is not None
    assert shell is not None
    assert "effect authorization" in reason.cannot_establish
    assert "target recovery" in shell.cannot_establish
