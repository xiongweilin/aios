from pathlib import Path

from control_plane.alert_policy import ManualTaskPolicy, classify_safety, drive_policy
from control_plane.domain_controller import ControllerStatus
from control_plane.provider_protocol import (
    CapabilityRequest,
    CapabilityResult,
    InvocationContext,
    ProviderDescriptor,
    ProviderHealth,
)
from tests.domain_harness import make_harness


class SuccessfulPersonalProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self._descriptor = ProviderDescriptor(
            id="successful-personal",
            name="Successful personal provider",
            version="test",
            capabilities=["reason.generate"],
            priority=100,
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider_id=self.descriptor.id, available=True)

    async def invoke(
        self,
        request: CapabilityRequest,
        context: InvocationContext,
    ) -> CapabilityResult:
        del context
        phase = str(request.parameters.get("phase", ""))
        self.calls.append((request.capability, phase))
        message = "bounded diagnosis" if phase == "diagnosis" else "bounded execution result"
        return CapabilityResult(
            request_id=request.id,
            provider_id=self.descriptor.id,
            status="succeeded",
            message=message,
        )


def test_classify_safety_requires_one_explicit_successful_marker() -> None:
    assert classify_safety(None) == "invalid"
    assert classify_safety({"status": "failed", "message": "SAFETY_CLASS=REVERSIBLE"}) == "invalid"
    assert classify_safety({"status": "succeeded", "message": "no marker"}) == "invalid"
    assert (
        classify_safety(
            {"status": "succeeded", "message": "SAFETY_CLASS=REVERSIBLE\nbounded repair"}
        )
        == "reversible"
    )
    assert (
        classify_safety(
            {"status": "succeeded", "message": "SAFETY_CLASS=UNKNOWN\ninsufficient evidence"}
        )
        == "unknown"
    )


async def test_manual_task_closes_only_after_work_and_revision(tmp_path: Path) -> None:
    provider = SuccessfulPersonalProvider()
    harness = make_harness(tmp_path, providers=[provider])
    try:
        state, _assessment_ref = harness.bridge.begin(
            title="Personal task",
            description="summarize the bounded issue",
            kind="personal-command",
        )
        policy = ManualTaskPolicy(
            controller=harness.controller,
            bridge=harness.bridge,
            prompt="summarize the bounded issue",
            diagnosis_model="gpt-5.6-luna",
            execution_model="gpt-5.6-luna",
        )

        final_state = await drive_policy(harness.controller, state.id, policy)

        assert final_state.status is ControllerStatus.CLOSED
        work = harness.bridge.work_for_state(final_state)
        assert work is not None
        assert work.kind == "personal-command"
        assert work.status == "completed"
        assert harness.controller.closures(state.id)
        assert harness.controller.revisions(state.id)
        assert provider.calls == [
            ("reason.generate", "diagnosis"),
            ("reason.generate", "execution"),
        ]
        assert any(
            path.endswith("/reports") and payload.get("kind") == "completion-proposal"
            for _method, path, payload in harness.stub.calls
        )
        responsibility = harness.stub.responsibilities[final_state.responsibility_ref]
        assert responsibility["status"] == "discharged"
    finally:
        harness.close()
