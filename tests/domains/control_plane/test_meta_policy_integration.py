from pathlib import Path

from control_plane.alert_policy import AutonomousRepairPolicy, ManualTaskPolicy
from control_plane.domain_controller import ControllerDecisionKind, StagedDomainPolicy
from tests.domain_harness import make_harness


def test_control_plane_policies_use_domain_local_staging() -> None:
    assert issubclass(AutonomousRepairPolicy, StagedDomainPolicy)
    assert issubclass(ManualTaskPolicy, StagedDomainPolicy)
    assert AutonomousRepairPolicy.select is StagedDomainPolicy.select
    assert ManualTaskPolicy.select is StagedDomainPolicy.select


def test_autonomous_repair_diagnosis_consumes_domain_meta_control(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)
    try:
        state, _assessment_ref = harness.bridge.begin(
            title="Repair alert",
            description="repair the current incident",
            kind="personal-incident-repair",
            repo=str(tmp_path),
            project="test",
            verification_labels={"alertname": "Broken"},
        )
        policy = AutonomousRepairPolicy(
            controller=harness.controller,
            bridge=harness.bridge,
            prompt="repair the current incident",
            diagnosis_model="codex/gpt-6-luna",
            execution_model="codex/gpt-6-luna",
            repo=str(tmp_path),
            project="test",
            verification_labels={"alertname": "Broken"},
        )

        diagnosis = policy._diagnosis(state)

        assert diagnosis.kind is ControllerDecisionKind.INVOKE_CAPABILITY
        assert diagnosis.capability == "reason.generate"
        assert diagnosis.parameters["phase"] == "diagnosis"
        assert diagnosis.parameters["meta_intent"] == "acquire-evidence"
        assert diagnosis.parameters["meta_candidate_ref"]
        assert diagnosis.instruction is not None
        assert "META_INTENT=ACQUIRE_EVIDENCE" in diagnosis.instruction
        assert "does not establish target recovery" in diagnosis.instruction
    finally:
        harness.close()
