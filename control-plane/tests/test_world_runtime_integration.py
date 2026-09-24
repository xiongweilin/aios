from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("world_runtime")

from world_runtime import WorldRuntime
from world_runtime.identity import DelegationGrant
from world_runtime.service import create_app

from control_plane.domain_controller import PersonalController
from control_plane.domain_store import DomainJournal
from control_plane.provider_protocol import (
    CapabilityRequest,
    CapabilityResult,
    InvocationContext,
    ProviderDescriptor,
    ProviderHealth,
    ProviderRegistry,
)
from control_plane.runtime_bridge import PersonalRuntimeBridge, WorldRuntimeClient


class TestClientTransport(httpx.BaseTransport):
    def __init__(self, client: TestClient) -> None:
        self.client = client

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self.client.request(
            request.method,
            str(request.url),
            content=request.read(),
            headers=dict(request.headers),
        )
        return httpx.Response(
            status_code=response.status_code,
            headers=dict(response.headers),
            content=response.content,
            request=request,
        )


class RecordingRealityProvider:
    def __init__(self) -> None:
        self.calls = 0
        self._descriptor = ProviderDescriptor(
            id="control-plane:test-reality-provider",
            name="Control Plane Test Reality Provider",
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
        assert context.work_id
        return CapabilityResult(
            request_id=request.id,
            provider_id=self.descriptor.id,
            status="succeeded",
            metadata={
                "provider_accepted": True,
                "delivery_confirmed": True,
                "delivery_confirmation": "test",
            },
            evidence_refs=[f"evidence:notify:{self.calls}"],
        )


@pytest.mark.asyncio
async def test_control_plane_conforms_to_real_world_runtime_4_0(tmp_path: Path) -> None:
    runtime = WorldRuntime.sqlite(runtime_id="runtime:control-plane-contract")
    runtime.identity.bind_bearer_token(
        principal="principal:integration",
        token="owner-token",
        credential_id="credential:integration-owner",
    )
    runtime.identity.bind_bearer_token(
        principal="controller:control-plane",
        token="controller-token",
        credential_id="credential:control-plane",
    )
    owner = runtime.identity.authenticate_bearer("Bearer owner-token")
    runtime.identity.grant_delegation(
        DelegationGrant(
            id="delegation:control-plane-integration",
            grantor="principal:integration",
            grantee="controller:control-plane",
            scope={"resource": "*"},
            authority_ceiling={"operation": "*", "action": "*", "resource": "*"},
        ),
        context=owner,
    )
    app = create_app(runtime)
    journal = DomainJournal(tmp_path / "control-plane-real-runtime.db")
    providers = ProviderRegistry()
    reality_provider = RecordingRealityProvider()
    providers.register(reality_provider)

    with TestClient(app) as test_client:
        client = WorldRuntimeClient(
            "http://testserver",
            transport=TestClientTransport(test_client),
            bearer_token="controller-token",
            delegation_id="delegation:control-plane-integration",
        )
        controller = PersonalController(journal, providers)
        bridge = PersonalRuntimeBridge(
            client,
            controller,
            journal,
            providers,
            owner_principal="principal:integration",
        )
        try:
            client.ensure_contracts()
            state, _ = bridge.begin(
                title="Runtime 4.0 integration",
                description="Exercise real Control Plane completion semantics.",
                kind="integration",
                project="world-runtime",
            )
            proposal_ref = "proposal:runtime-4.0-integration"
            journal.project_put(
                "work.proposal",
                proposal_ref,
                {
                    "kind": "integration-check",
                    "closure_ref": "closure:runtime-4.0-integration",
                    "requested_capabilities": [],
                    "expected_result": "real Runtime accepts completion",
                },
            )
            state = state.model_copy(update={"work_proposal_ref": proposal_ref})
            work = bridge.materialize_work(state)
            run = bridge.start_run(work.id, workflow_id="runtime-4.0")
            effect = await bridge.invoke_capability(
                work.id,
                "notify.send",
                run_id=run.id,
                instruction="Runtime 4.0 reality-boundary integration",
                idempotency_key="effect:control-plane-runtime-4.0",
            )
            replay = await bridge.invoke_capability(
                work.id,
                "notify.send",
                run_id=run.id,
                instruction="Runtime 4.0 reality-boundary integration",
                idempotency_key="effect:control-plane-runtime-4.0",
            )
            assert effect.status == "succeeded"
            assert replay.status == "succeeded"
            assert reality_provider.calls == 1
            attempt = runtime.effect_boundary.get("effect:control-plane-runtime-4.0")
            assert attempt["status"] == "committed"
            assert attempt["dispatch_allowed"] is False
            bridge.record_capability_result(
                controller_id=state.id,
                work_id=work.id,
                run_id=run.id,
                stage="verification",
                capability="integration.verify",
                result=CapabilityResult(
                    status="succeeded",
                    evidence_refs=["evidence:runtime-4.0-control-plane"],
                ),
            )
            bridge.report_completion(state)

            responsibility = runtime.responsibility.get(state.responsibility_ref)
            assignment = runtime.domains.get(bridge.assignment_ref(state.responsibility_ref))
            assert responsibility.status == "discharged"
            assert assignment.status == "completion-proposed"
            reports = runtime.domains.reports(assignment.id)
            assert [report.kind for report in reports] == [
                "accepted",
                "outcome-candidate",
                "completion-proposal",
            ]
        finally:
            client.close()
            journal.close()
            runtime.close()
