import pytest

from world_runtime import WorldRuntime
from world_runtime.execution import (
    CapabilityEffectRule,
    CapabilityRequest,
    CapabilityResult,
    InvocationContext,
    ProviderDescriptor,
    ProviderHealth,
)


class RecordingProvider:
    def __init__(self) -> None:
        self.seen_effect_class: str | None = None
        self._descriptor = ProviderDescriptor(
            id="recording",
            name="Recording Provider",
            version="1",
            capabilities=["write.safe", "write.protected"],
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider_id=self.descriptor.id, available=True)

    async def invoke(
        self, request: CapabilityRequest, context: InvocationContext
    ) -> CapabilityResult:
        del context
        self.seen_effect_class = request.effect_class
        return CapabilityResult(
            request_id=request.id,
            provider_id=self.descriptor.id,
            status="succeeded",
        )

    async def cancel(self, request_id: str) -> None:
        del request_id


@pytest.mark.asyncio
async def test_contract_prevents_caller_from_downclassifying_effect() -> None:
    runtime = WorldRuntime.sqlite()
    provider = RecordingProvider()
    runtime.registry.register(provider)
    runtime.contract_registry.register_effect_rule(
        CapabilityEffectRule(
            capability="write.safe",
            impact_class="write-local",
            authorization_required=False,
            resource_required=True,
            version_required=False,
        )
    )

    runtime.responsibility.create(
        __import__("semantic_language", fromlist=["Responsibility"]).Responsibility(
            id="responsibility:write-safe",
            principal="principal:test",
            subject="safe write",
        ),
        domain="test",
    )
    work = runtime.execution.admit_work(
        responsibility_id="responsibility:write-safe",
        kind="effect",
        payload={},
    )
    result = await runtime.invoke(
        CapabilityRequest(
            capability="write.safe",
            work_id=work.id,
            effect_class="read",
            resource_ref="repo:test",
            idempotency_key="effect:write-safe",
        )
    )

    assert result.status == "succeeded"
    assert provider.seen_effect_class == "write-local"


@pytest.mark.asyncio
async def test_contract_requires_authorization_before_provider_invocation() -> None:
    runtime = WorldRuntime.sqlite()
    provider = RecordingProvider()
    runtime.registry.register(provider)
    runtime.contract_registry.register_effect_rule(
        CapabilityEffectRule(
            capability="write.protected",
            impact_class="write-remote",
            authorization_required=True,
            resource_required=True,
            version_required=False,
        )
    )

    runtime.responsibility.create(
        __import__("semantic_language", fromlist=["Responsibility"]).Responsibility(
            id="responsibility:write-protected",
            principal="principal:test",
            subject="protected write",
        ),
        domain="test",
    )
    work = runtime.execution.admit_work(
        responsibility_id="responsibility:write-protected",
        kind="effect",
        payload={},
    )
    with pytest.raises(PermissionError, match="requires authorization"):
        await runtime.invoke(
            CapabilityRequest(
                capability="write.protected",
                work_id=work.id,
                actor_ref="principal:test",
                resource_ref="repo:test",
                idempotency_key="effect:write-protected",
            )
        )

    assert provider.seen_effect_class is None
