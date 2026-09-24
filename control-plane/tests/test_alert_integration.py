from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from control_plane.app import ALERT_FINISHED_EVENT, ALERT_QUEUED_EVENT, create_app
from control_plane.config import ControlPlaneConfig
from control_plane.provider_protocol import (
    CapabilityRequest,
    CapabilityResult,
    InvocationContext,
    ProviderDescriptor,
    ProviderHealth,
)
from tests.runtime_stub import RuntimeStub


def _config(tmp_path: Path) -> ControlPlaneConfig:
    return ControlPlaneConfig(
        api_key="test-key",
        state_db=tmp_path / "control-plane-domain.db",
        artifact_root=tmp_path / "artifacts",
        agent_session_dir=tmp_path / "sessions",
        codex_worktree_root=tmp_path / "worktrees",
        prometheus_url="",
        alertmanager_url="",
        notification_enabled=False,
        environment_enabled=False,
        game_mode_enabled=False,
        allowed_repo_roots=(str(tmp_path),),
        project_dirs={"test": str(tmp_path)},
        allowed_auto_projects=(),
    )


class RecordingCodexProvider:
    def __init__(self) -> None:
        self.phases: list[str] = []
        self._descriptor = ProviderDescriptor(
            id="integration-codex",
            name="Integration Codex Provider",
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
        self.phases.append(phase)
        message = (
            "SAFETY_CLASS=REVERSIBLE\nbounded diagnosis"
            if phase == "diagnosis"
            else "bounded execution result"
        )
        return CapabilityResult(
            request_id=request.id,
            provider_id=self.descriptor.id,
            status="succeeded",
            message=message,
        )


class InactiveAlertProvider:
    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id="integration-monitor",
            name="Integration Alert Monitor",
            version="test",
            capabilities=["monitor.alert.active"],
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
            status="succeeded",
            message="alert is no longer active",
            metadata={"active": False, "matches": 0},
        )


async def test_alert_ingress_persists_domain_journal_and_reports_completion(
    tmp_path: Path,
) -> None:
    runtime = RuntimeStub()
    app = create_app(
        _config(tmp_path),
        runtime_transport=runtime.transport(),
    )
    journal = app.state.domain_journal
    registry = app.state.provider_registry
    codex = RecordingCodexProvider()
    registry.unregister("codex-primary")
    registry.register(codex)
    registry.unregister("personal-monitoring")
    registry.register(InactiveAlertProvider())

    payload = {
        "alerts": [
            {
                "status": "firing",
                "fingerprint": "integration-alert-1",
                "labels": {
                    "alertname": "IntegrationAlert",
                    "job": "control-plane",
                    "instance": "node-test",
                },
                "annotations": {
                    "summary": "integration summary",
                    "description": "integration description",
                },
            }
        ]
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/alerts/alertmanager",
            json=payload,
            headers={"X-Control-Plane-Key": "test-key"},
        )

    assert response.status_code == 200
    assert response.json()["queued"] == 1

    finished = []
    for _ in range(100):
        events = journal.events(stream="alert:alertmanager:integration-alert-1")
        finished = [event for event in events if event.kind == ALERT_FINISHED_EVENT]
        if finished:
            break
        await asyncio.sleep(0.01)

    events = journal.events()
    assert any(event.kind == ALERT_QUEUED_EVENT for event in events)
    assert any(
        event.kind == "control-plane.controller.decision"
        and event.payload.get("decision", {}).get("capability") == "reason.generate"
        for event in events
    )
    assert any(event.kind == "control-plane.controller.capability-result" for event in events)
    assert finished, "alert worker did not persist a finished event"
    assert finished[-1].payload["status"] == "closed"
    assert codex.phases == ["diagnosis", "execution"]
    assert any(
        path.endswith("/reports") and body.get("kind") == "completion-proposal"
        for _method, path, body in runtime.calls
    )
