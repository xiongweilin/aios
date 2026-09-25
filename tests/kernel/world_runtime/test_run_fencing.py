import pytest

from semantic_language import Responsibility

from world_runtime import WorldRuntime
from world_runtime.execution import (
    CapabilityRequest,
    CapabilityResult,
    InvocationContext,
    ProviderDescriptor,
    ProviderHealth,
)


class LeaseProvider:
    def __init__(self) -> None:
        self.calls = 0
        self._descriptor = ProviderDescriptor(
            id="lease-provider",
            name="Lease Provider",
            version="test",
            capabilities=["demo.read"],
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
        return CapabilityResult(
            request_id=request.id,
            provider_id=self.descriptor.id,
            status="succeeded",
            data={
                "lease_generation": context.lease_generation,
                "lease_owner": context.lease_owner,
            },
        )

    async def cancel(self, request_id: str) -> None:
        del request_id


def _run(runtime: WorldRuntime):
    runtime.responsibility.create(
        Responsibility(
            id="responsibility:lease-test",
            principal="service:test",
            subject="lease test",
        ),
        domain="test",
    )
    work = runtime.execution.admit_work(
        responsibility_id="responsibility:lease-test",
        kind="test",
        payload={},
    )
    return runtime.start_run(work.id, workflow_id="test")


@pytest.mark.asyncio
async def test_run_fencing_rejects_missing_and_stale_lease_identity() -> None:
    runtime = WorldRuntime.sqlite()
    provider = LeaseProvider()
    runtime.registry.register(provider)
    run = _run(runtime)
    lease = runtime.execution.acquire_run_lease(run.id, owner="worker:a", ttl_seconds=60)

    with pytest.raises(PermissionError, match="owner mismatch"):
        await runtime.invoke(
            CapabilityRequest(
                capability="demo.read",
                work_id=run.work_id,
                run_id=run.id,
            )
        )

    result = await runtime.invoke(
        CapabilityRequest(
            capability="demo.read",
            work_id=run.work_id,
            run_id=run.id,
            lease_owner="worker:a",
            lease_generation=lease.lease_generation,
        )
    )
    assert result.status == "succeeded"
    assert result.data["lease_owner"] == "worker:a"

    runtime.execution.release_run_lease(
        run.id,
        owner="worker:a",
        lease_generation=lease.lease_generation,
    )
    reacquired = runtime.execution.acquire_run_lease(
        run.id,
        owner="worker:b",
        ttl_seconds=60,
    )
    assert reacquired.lease_generation == lease.lease_generation + 1

    with pytest.raises(PermissionError, match="owner mismatch"):
        await runtime.invoke(
            CapabilityRequest(
                capability="demo.read",
                work_id=run.work_id,
                run_id=run.id,
                lease_owner="worker:a",
                lease_generation=lease.lease_generation,
            )
        )
    assert provider.calls == 1


def test_run_lease_competing_owner_fails_closed() -> None:
    runtime = WorldRuntime.sqlite()
    run = _run(runtime)
    lease = runtime.execution.acquire_run_lease(run.id, owner="worker:a", ttl_seconds=60)
    same = runtime.execution.acquire_run_lease(run.id, owner="worker:a", ttl_seconds=60)
    assert same.lease_generation == lease.lease_generation

    with pytest.raises(PermissionError, match="another owner"):
        runtime.execution.acquire_run_lease(run.id, owner="worker:b", ttl_seconds=60)
