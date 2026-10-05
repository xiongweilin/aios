from __future__ import annotations

import os

import httpx
from administrative_orchestrator.integrations.runtime_capabilities import (
    ADMINISTRATIVE_HRIS_EMPLOYEE_DEACTIVATE,
    ADMINISTRATIVE_IAM_IDENTITY_DISABLE,
    ADMINISTRATIVE_IAM_SESSIONS_REVOKE,
)
from world_runtime import WorldRuntime
from world_runtime.execution import (
    CapabilityEffectRule,
    CapabilityRequest,
    CapabilityResult,
    InvocationContext,
    ProviderDescriptor,
    ProviderHealth,
)
from world_runtime.identity import DelegationGrant

CAPABILITIES = (
    ADMINISTRATIVE_HRIS_EMPLOYEE_DEACTIVATE,
    ADMINISTRATIVE_IAM_IDENTITY_DISABLE,
    ADMINISTRATIVE_IAM_SESSIONS_REVOKE,
)

_OPERATION_BY_CAPABILITY = {
    ADMINISTRATIVE_HRIS_EMPLOYEE_DEACTIVATE: ("hris", "employee.deactivate"),
    ADMINISTRATIVE_IAM_IDENTITY_DISABLE: ("iam", "identity.disable"),
    ADMINISTRATIVE_IAM_SESSIONS_REVOKE: ("iam", "sessions.revoke"),
}


def _effect_id(request: CapabilityRequest) -> str:
    prefix = "administrative-effect:"
    value = request.idempotency_key or ""
    if not value.startswith(prefix):
        raise ValueError("network fixture requires Administrative effect idempotency")
    return value[len(prefix):]


class NetworkEffectProvider:
    def __init__(self, sandbox_base: str, *, timeout_seconds: float) -> None:
        self.sandbox_base = sandbox_base.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._request_to_effect: dict[str, str] = {}
        self._descriptor = ProviderDescriptor(
            id="provider:baa-network-sandbox",
            name="BAA network sandbox writer",
            version="1",
            capabilities=list(CAPABILITIES),
            effect_semantics="reconcilable",
            side_effect_class="reconcilable",
            reversibility="irreversible",
            provider_family="baa-network-fixture",
            operator="acceptance",
            execution_domain="network-sandbox:writer",
            credential_domain="fixture:writer",
            data_source_domain="network-sandbox",
            network_domain="docker-network",
            trust_boundary="acceptance-network",
            reconciliation_protocol_identity="baa-network-sandbox-readback",
            reconciliation_protocol_version="1",
            reconciliation_repeatability="repeat-safe",
            reconciliation_contract_version="1",
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    async def health(self) -> ProviderHealth:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(f"{self.sandbox_base}/healthz")
                response.raise_for_status()
        except httpx.HTTPError:
            return ProviderHealth(provider_id=self.descriptor.id, available=False)
        return ProviderHealth(provider_id=self.descriptor.id, available=True)

    async def invoke(
        self,
        request: CapabilityRequest,
        context: InvocationContext,
    ) -> CapabilityResult:
        del context
        effect_id = _effect_id(request)
        self._request_to_effect[request.id] = effect_id
        target_system, operation = _OPERATION_BY_CAPABILITY[request.capability]
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.put(
                    f"{self.sandbox_base}/v1/effects/{effect_id}",
                    json={
                        "target_system": target_system,
                        "operation": operation,
                        "subject_ref": request.parameters.get("subject_ref"),
                        "payload": dict(request.parameters),
                    },
                )
                response.raise_for_status()
                body = response.json()
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            return CapabilityResult(
                request_id=request.id,
                provider_id=self.descriptor.id,
                status="unknown",
                error={"code": type(exc).__name__, "message": str(exc)},
            )
        except httpx.HTTPStatusError as exc:
            return CapabilityResult(
                request_id=request.id,
                provider_id=self.descriptor.id,
                status="failed",
                error={
                    "code": f"http_{exc.response.status_code}",
                    "message": exc.response.text[:300],
                },
            )
        return CapabilityResult(
            request_id=request.id,
            provider_id=self.descriptor.id,
            status="succeeded",
            external_operation_ref=str(body.get("provider_ref") or f"sandbox:{effect_id}"),
        )

    async def cancel(self, request_id: str) -> None:
        del request_id

    async def reconcile(self, request_id: str) -> CapabilityResult | None:
        effect_id = self._request_to_effect.get(request_id)
        if not effect_id:
            return None
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(f"{self.sandbox_base}/v1/effects/{effect_id}")
        except httpx.HTTPError:
            return None
        if response.status_code == 404:
            return None
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            return None
        return CapabilityResult(
            request_id=request_id,
            provider_id=self.descriptor.id,
            status="succeeded",
            external_operation_ref=f"sandbox:{effect_id}",
            reconciled=True,
        )


def build() -> WorldRuntime:
    state_path = os.environ["BAA_NETWORK_RUNTIME_STATE_PATH"]
    sandbox_base = os.environ["BAA_NETWORK_SANDBOX_BASE"]
    token = os.environ["BAA_NETWORK_RUNTIME_TOKEN"]
    principal = os.environ.get(
        "BAA_NETWORK_RUNTIME_PRINCIPAL",
        "service:administrative-orchestrator",
    )
    controller = os.environ.get(
        "BAA_NETWORK_RUNTIME_CONTROLLER",
        "controller:administrative-orchestrator",
    )
    delegation_id = os.environ.get(
        "BAA_NETWORK_RUNTIME_DELEGATION_ID",
        "delegation:baa-network-administrative",
    )
    timeout = float(os.environ.get("BAA_NETWORK_PROVIDER_TIMEOUT_SECONDS", "0.35"))

    runtime = WorldRuntime.sqlite(
        state_path,
        runtime_id="runtime:baa-network-acceptance",
        root_principal=principal,
    )
    bootstrap_token = f"bootstrap-{token}"
    runtime.identity.bind_bearer_token(
        principal=principal,
        token=bootstrap_token,
        credential_id="credential:baa-network-bootstrap",
    )
    runtime.identity.bind_bearer_token(
        principal=controller,
        token=token,
        credential_id="credential:baa-network-controller",
    )
    grantor_context = runtime.identity.authenticate_bearer(
        f"Bearer {bootstrap_token}"
    )
    runtime.identity.grant_delegation(
        DelegationGrant(
            id=delegation_id,
            grantor=principal,
            grantee=controller,
            scope={},
            authority_ceiling={
                "operation": "*",
                "action": "*",
                "resource": "*",
            },
        ),
        context=grantor_context,
    )
    runtime.registry.register(
        NetworkEffectProvider(sandbox_base, timeout_seconds=timeout)
    )

    for capability in CAPABILITIES:
        runtime.contract_registry.register_effect_rule(
            CapabilityEffectRule(
                capability=capability,
                impact_class="write-remote",
                authorization_required=True,
                resource_required=True,
                version_required=True,
                blast_radius=1,
                exposure=1,
            )
        )
    return runtime
