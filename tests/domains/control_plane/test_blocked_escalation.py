from pathlib import Path

from control_plane.alert_policy import ManualTaskPolicy
from control_plane.domain_controller import ControllerDecisionKind, ControllerStatus
from control_plane.provider_protocol import (
    CapabilityRequest,
    CapabilityResult,
    InvocationContext,
    ProviderDescriptor,
    ProviderHealth,
)
from tests.domain_harness import make_harness


class FailedDiagnosisProvider:
    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id="failed-diagnosis",
            name="Failed diagnosis",
            version="test",
            capabilities=["reason.generate"],
            priority=100,
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider_id=self.descriptor.id, available=True)

    async def invoke(
        self,
        request: CapabilityRequest,
        context: InvocationContext,
    ) -> CapabilityResult:
        del context
        return CapabilityResult(
            request_id=request.id,
            provider_id=self.descriptor.id,
            status="failed",
            message="diagnosis unavailable",
        )


async def test_failed_diagnosis_waits_without_closure_or_work(tmp_path: Path) -> None:
    harness = make_harness(tmp_path, providers=[FailedDiagnosisProvider()])
    try:
        state, _assessment_ref = harness.bridge.begin(
            title="Personal task",
            description="fix it",
            kind="personal-command",
            repo=str(tmp_path),
        )
        policy = ManualTaskPolicy(
            controller=harness.controller,
            bridge=harness.bridge,
            prompt="fix it",
            diagnosis_model="gpt-6-luna",
            execution_model="gpt-6-luna",
            repo=str(tmp_path),
        )

        diagnosis = await policy.select(state)
        assert diagnosis.kind is ControllerDecisionKind.INVOKE_CAPABILITY
        observed = await harness.controller.apply(diagnosis)
        wait_decision = await policy.select(observed)
        assert wait_decision.kind is ControllerDecisionKind.WAIT
        waiting = await harness.controller.apply(wait_decision)

        assert waiting.status is ControllerStatus.WAITING
        assert waiting.active_closure_ref is None
        assert waiting.work_proposal_ref is None
        assert harness.bridge.list_work() == []
    finally:
        harness.close()
