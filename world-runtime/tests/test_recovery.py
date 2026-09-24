import pytest

from world_runtime import WorldRuntime
from world_runtime.execution import (
    CapabilityRequest,
    CapabilityResult,
    InvocationContext,
    ProviderDescriptor,
    ProviderHealth,
    reconciliation_contract_for,
)
from world_runtime.recovery import (
    RecoveryDispositionKind,
    RecoveryResolutionStatus,
)


class RecoverableProvider:
    def __init__(self) -> None:
        self.reconcile_calls = 0
        self._descriptor = ProviderDescriptor(
            id="recoverable",
            name="Recoverable",
            version="test",
            capabilities=["demo.effect"],
            reconciliation_protocol_identity="demo.reconcile",
            reconciliation_protocol_version="1",
            reconciliation_repeatability="repeat-safe",
            reconciliation_contract_version="1",
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
        del request, context
        raise AssertionError("recovery must never fresh-invoke the provider")

    async def cancel(self, request_id: str) -> None:
        del request_id

    async def reconcile(self, request_id: str) -> CapabilityResult | None:
        self.reconcile_calls += 1
        return CapabilityResult(
            request_id=request_id,
            provider_id=self.descriptor.id,
            status="succeeded",
            data={"source": "reconciliation"},
        )


class OpaqueProvider:
    def __init__(self) -> None:
        self._descriptor = ProviderDescriptor(
            id="opaque",
            name="Opaque",
            version="test",
            capabilities=["demo.effect"],
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
        del request, context
        raise AssertionError("recovery must never fresh-invoke the provider")

    async def cancel(self, request_id: str) -> None:
        del request_id


def _attempt(runtime: WorldRuntime, *, key: str, provider) -> None:
    contract = reconciliation_contract_for(provider.descriptor)
    runtime.ledger.project_put(
        "execution.provider-attempt",
        key,
        {
            "request_id": f"request:{key}",
            "provider_id": provider.descriptor.id,
            "provider_version": provider.descriptor.version,
            "capability": "demo.effect",
            "status": "started",
            "reconciliation_contract": (
                contract.model_dump(mode="json") if contract is not None else None
            ),
        },
    )


@pytest.mark.asyncio
async def test_recovery_records_disposition_application_and_terminal_resolution() -> None:
    runtime = WorldRuntime.sqlite()
    provider = RecoverableProvider()
    runtime.registry.register(provider)
    _attempt(runtime, key="effect-1", provider=provider)

    disposition = runtime.recovery.classify("effect-1")
    assert disposition.kind is RecoveryDispositionKind.RECONCILE

    result = await runtime.recovery.recover("effect-1")
    assert result.status == "succeeded"
    assert result.reconciled is True
    assert provider.reconcile_calls == 1

    resolution = runtime.recovery.inspect("effect-1")
    assert resolution is not None
    assert resolution.status is RecoveryResolutionStatus.RECOVERED_SUCCEEDED
    assert runtime.ledger.project_get("recovery.application", "effect-1") is not None

    replay = await runtime.recovery.recover("effect-1")
    assert replay.status == "succeeded"
    assert provider.reconcile_calls == 1


@pytest.mark.asyncio
async def test_recovery_without_reconcile_is_manual_and_never_redispatches() -> None:
    runtime = WorldRuntime.sqlite()
    provider = OpaqueProvider()
    runtime.registry.register(provider)
    _attempt(runtime, key="effect-2", provider=provider)

    result = await runtime.recovery.recover("effect-2")
    assert result.status == "unknown"
    assert result.error["code"] == "ManualResolutionRequired"

    resolution = runtime.recovery.inspect("effect-2")
    assert resolution is not None
    assert resolution.status is RecoveryResolutionStatus.MANUAL_REQUIRED


@pytest.mark.asyncio
async def test_recovery_fails_closed_when_reconciliation_contract_drifts() -> None:
    runtime = WorldRuntime.sqlite()
    provider = RecoverableProvider()
    runtime.registry.register(provider)
    _attempt(runtime, key="effect-drift", provider=provider)

    provider._descriptor = provider.descriptor.model_copy(
        update={"reconciliation_protocol_version": "2"}
    )

    result = await runtime.recovery.recover("effect-drift")
    assert result.status == "unknown"
    assert result.error["code"] == "ManualResolutionRequired"
    resolution = runtime.recovery.inspect("effect-drift")
    assert resolution is not None
    assert "drifted" in resolution.reason
    assert provider.reconcile_calls == 0
