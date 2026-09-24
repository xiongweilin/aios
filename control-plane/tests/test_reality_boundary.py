from __future__ import annotations

from pathlib import Path

import pytest

from control_plane.domain_controller import ControllerDecision, ControllerDecisionKind
from control_plane.provider_protocol import (
    CapabilityRequest,
    CapabilityResult,
    InvocationContext,
    ProviderDescriptor,
    ProviderHealth,
)
from control_plane.runtime_bridge import (
    DomainRun,
    DomainWork,
    PersonalRuntimeBridge,
    WorldRuntimeBoundaryError,
)
from tests.domain_harness import make_harness


class RecordingNotificationProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail
        self._descriptor = ProviderDescriptor(
            id="provider:test-notify",
            name="Test Notification Provider",
            version="1",
            capabilities=["notify.send"],
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
        self.calls += 1
        assert context.work_id is not None
        if self.fail:
            raise RuntimeError("provider acknowledgement lost")
        return CapabilityResult(
            request_id=request.id,
            provider_id=self.descriptor.id,
            status="succeeded",
            metadata={
                "provider_accepted": True,
                "delivery_confirmed": True,
                "delivery_confirmation": "test",
            },
            evidence_refs=[f"evidence:notification:{self.calls}"],
        )


@pytest.mark.asyncio
async def test_reality_effect_committed_replay_does_not_redispatch(tmp_path: Path) -> None:
    provider = RecordingNotificationProvider()
    harness = make_harness(tmp_path, providers=[provider])
    try:
        work = harness.bridge.ensure_auxiliary_work("notifications")
        replayed_work = harness.bridge.ensure_auxiliary_work("notifications")
        assert replayed_work.id == work.id
        assert replayed_work.runtime_work_ref == work.runtime_work_ref

        first = await harness.bridge.invoke_capability(
            work.id,
            "notify.send",
            instruction="notify once",
            idempotency_key="effect:test-notification",
        )
        second = await harness.bridge.invoke_capability(
            work.id,
            "notify.send",
            instruction="notify once",
            idempotency_key="effect:test-notification",
        )

        assert first.status == second.status == "succeeded"
        assert first.evidence_refs == second.evidence_refs == ["evidence:notification:1"]
        assert provider.calls == 1
        effect = harness.stub.effects["effect:test-notification"]
        assert effect["status"] == "committed"
        assert effect["dispatch_allowed"] is False
        assert effect["result"] is not None
    finally:
        harness.close()


@pytest.mark.asyncio
async def test_ambiguous_reality_effect_requires_reconciliation_instead_of_retry(
    tmp_path: Path,
) -> None:
    provider = RecordingNotificationProvider(fail=True)
    harness = make_harness(tmp_path, providers=[provider])
    try:
        work = harness.bridge.ensure_auxiliary_work("notifications")

        with pytest.raises(RuntimeError, match="acknowledgement lost"):
            await harness.bridge.invoke_capability(
                work.id,
                "notify.send",
                instruction="notify with lost acknowledgement",
                idempotency_key="effect:ambiguous-notification",
            )

        assert provider.calls == 1
        effect = harness.stub.effects["effect:ambiguous-notification"]
        assert effect["status"] == "ambiguous"

        replay = await harness.bridge.invoke_capability(
            work.id,
            "notify.send",
            instruction="notify with lost acknowledgement",
            idempotency_key="effect:ambiguous-notification",
        )
        assert replay.status == "unknown"
        assert replay.error is not None
        assert replay.metadata["runtime_effect_status"] == "ambiguous"
        assert provider.calls == 1
    finally:
        harness.close()


@pytest.mark.asyncio
async def test_pre_work_cognition_cannot_execute_reality_capability(tmp_path: Path) -> None:
    provider = RecordingNotificationProvider()
    harness = make_harness(tmp_path, providers=[provider])
    try:
        state = harness.controller.create(
            responsibility_ref="responsibility:test-cognition",
            subject_ref="subject:test",
        )
        decision = ControllerDecision(
            controller_ref=state.id,
            state_version=state.version,
            kind=ControllerDecisionKind.INVOKE_CAPABILITY,
            capability="notify.send",
            instruction="this must not dispatch before Work exists",
        )

        with pytest.raises(PermissionError, match="materialized Work"):
            await harness.controller.apply(decision)
        assert provider.calls == 0
    finally:
        harness.close()


@pytest.mark.asyncio
async def test_reality_effect_enforces_resource_and_version_policy(tmp_path: Path) -> None:
    class GitProvider(RecordingNotificationProvider):
        def __init__(self) -> None:
            super().__init__()
            self._descriptor = ProviderDescriptor(
                id="provider:test-git",
                name="Test Git Provider",
                version="1",
                capabilities=["git.push"],
            )

    provider = GitProvider()
    harness = make_harness(tmp_path, providers=[provider])
    try:
        work = harness.bridge.ensure_auxiliary_work("repository-effects")

        with pytest.raises(ValueError, match="requires resource_ref"):
            await harness.bridge.invoke_capability(
                work.id,
                "git.push",
                idempotency_key="effect:git-missing-resource",
            )

        with pytest.raises(ValueError, match="requires subject_version_refs"):
            await harness.bridge.invoke_capability(
                work.id,
                "git.push",
                resource_ref="repository:test",
                idempotency_key="effect:git-missing-version",
            )

        result = await harness.bridge.invoke_capability(
            work.id,
            "git.push",
            resource_ref="repository:test",
            subject_version_refs=["git:abc123"],
            idempotency_key="effect:git-complete",
        )
        assert result.status == "succeeded"
        assert provider.calls == 1
    finally:
        harness.close()


@pytest.mark.asyncio
async def test_unbound_local_work_is_bound_before_reality_effect(tmp_path: Path) -> None:
    provider = RecordingNotificationProvider()
    harness = make_harness(tmp_path, providers=[provider])
    try:
        work = DomainWork(
            id="work:legacy-unbound",
            responsibility_ref="responsibility:legacy-unbound",
            proposal_ref="proposal:legacy-unbound",
            kind="notifications",
            runtime_work_ref=None,
            metadata={"legacy": True},
        )
        harness.journal.project_put(
            "work.current",
            work.id,
            work.model_dump(mode="json"),
        )

        result = await harness.bridge.invoke_capability(
            work.id,
            "notify.send",
            instruction="bind before dispatch",
        )
        rebound = harness.bridge.get_work(work.id)

        assert result.status == "succeeded"
        assert provider.calls == 1
        assert rebound is not None
        assert rebound.runtime_work_ref == f"control-plane:{work.id}"
        assert len(harness.stub.effects) == 1
        effect = next(iter(harness.stub.effects.values()))
        assert effect["status"] == "committed"
    finally:
        harness.close()


@pytest.mark.asyncio
async def test_reality_effect_rejects_missing_and_foreign_run(tmp_path: Path) -> None:
    provider = RecordingNotificationProvider()
    harness = make_harness(tmp_path, providers=[provider])
    try:
        work = harness.bridge.ensure_auxiliary_work("notifications")
        with pytest.raises(KeyError, match="run:missing"):
            await harness.bridge.invoke_capability(
                work.id,
                "notify.send",
                run_id="run:missing",
                idempotency_key="effect:missing-run",
            )

        other_work = harness.bridge.ensure_auxiliary_work("other-notifications")
        foreign_run = DomainRun(
            id="run:foreign",
            work_id=other_work.id,
            workflow_id="foreign",
            runtime_run_ref="run:runtime-foreign",
        )
        harness.journal.project_put(
            "run.current",
            foreign_run.id,
            foreign_run.model_dump(mode="json"),
        )
        with pytest.raises(ValueError, match="does not belong"):
            await harness.bridge.invoke_capability(
                work.id,
                "notify.send",
                run_id=foreign_run.id,
                idempotency_key="effect:foreign-run",
            )
        assert provider.calls == 0
    finally:
        harness.close()


@pytest.mark.asyncio
async def test_committed_replay_fails_closed_when_runtime_result_is_malformed(
    tmp_path: Path,
) -> None:
    provider = RecordingNotificationProvider()
    harness = make_harness(tmp_path, providers=[provider])
    try:
        work = harness.bridge.ensure_auxiliary_work("notifications")
        for key, result, message in (
            ("effect:missing-result", None, "missing provider result"),
            (
                "effect:missing-domain-result",
                {"status": "succeeded", "data": {}},
                "lacks Control Plane replay data",
            ),
        ):
            harness.stub.effects[key] = {
                "grant_id": f"grant:{key}",
                "idempotency_key": key,
                "request_id": f"request:{key}",
                "provider_id": provider.descriptor.id,
                "provider_version": provider.descriptor.version,
                "status": "committed",
                "dispatch_generation": 1,
                "start_allowed": False,
                "dispatch_allowed": False,
                "result": result,
            }
            with pytest.raises(WorldRuntimeBoundaryError, match=message):
                await harness.bridge.invoke_capability(
                    work.id,
                    "notify.send",
                    instruction="malformed replay",
                    idempotency_key=key,
                )
        assert provider.calls == 0
    finally:
        harness.close()


@pytest.mark.asyncio
async def test_runtime_start_must_explicitly_grant_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = RecordingNotificationProvider()
    harness = make_harness(tmp_path, providers=[provider])
    original_post = harness.client.post

    def guarded_post(path: str, payload: dict[str, object]) -> dict[str, object]:
        value = original_post(path, payload)
        if path.endswith("/start") and path.startswith("/v1/domain-effects/"):
            return {**value, "dispatch_allowed": False}
        return value

    monkeypatch.setattr(harness.client, "post", guarded_post)
    try:
        work = harness.bridge.ensure_auxiliary_work("notifications")
        with pytest.raises(WorldRuntimeBoundaryError, match="did not grant"):
            await harness.bridge.invoke_capability(
                work.id,
                "notify.send",
                instruction="must not dispatch",
                idempotency_key="effect:no-dispatch-grant",
            )
        assert provider.calls == 0
    finally:
        harness.close()


def test_effect_identity_is_deterministic_without_explicit_idempotency_key() -> None:
    request = CapabilityRequest(
        capability="notify.send",
        instruction="deterministic effect",
        parameters={"channel": "alerts"},
        effect_class="write-remote",
    )
    first = PersonalRuntimeBridge._effect_identity_key(request, "work:runtime")
    second = PersonalRuntimeBridge._effect_identity_key(request, "work:runtime")
    assert first == second
    assert first.startswith("control-plane-effect:")
