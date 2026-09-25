from __future__ import annotations

import builtins
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def new_id(prefix: str) -> str:
    return f"{prefix}:{uuid4().hex}"


class EffectClass(StrEnum):
    READ_ONLY = "read-only"
    INTERNAL_REVERSIBLE = "internal-reversible"
    EXTERNAL_EFFECT = "external-effect"


class ProviderDescriptor(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    name: str
    version: str
    capabilities: list[str] = Field(default_factory=list)
    enabled: bool = True
    priority: int = 0
    tags: set[str] = Field(default_factory=set)
    metadata: dict[str, Any] = Field(default_factory=dict)
    effect_semantics: str = "pure"
    side_effect_class: str = "pure"
    reversibility: str = "unknown"
    provider_family: str | None = None
    execution_domain: str | None = None
    network_domain: str | None = None
    trust_boundary: str | None = None


class ProviderHealth(BaseModel):
    provider_id: str
    available: bool
    detail: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class InvocationContext(BaseModel):
    model_config = ConfigDict(extra="allow")
    controller_id: str | None = None
    work_id: str | None = None
    run_id: str | None = None
    idempotency_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = Field(default_factory=lambda: new_id("request"))
    capability: str
    instruction: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    run_id: str | None = None
    timeout_seconds: float | None = None
    subject_version_refs: list[str] = Field(default_factory=list)
    resource_ref: str | None = None
    actor_ref: str | None = None
    effect_class: str = EffectClass.READ_ONLY.value


class CapabilityResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    request_id: str = ""
    provider_id: str = ""
    status: str = "succeeded"
    message: str | None = None
    error: dict[str, Any] | str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    provider_success: bool | None = None

    @model_validator(mode="after")
    def _provider_success(self) -> CapabilityResult:
        if self.provider_success is None:
            self.provider_success = self.status == "succeeded"
        return self


class CapabilityProvider(Protocol):
    @property
    def descriptor(self) -> ProviderDescriptor: ...

    async def health(self) -> ProviderHealth: ...

    async def invoke(
        self,
        request: CapabilityRequest,
        context: InvocationContext,
    ) -> CapabilityResult: ...


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, CapabilityProvider] = {}

    def register(self, provider: CapabilityProvider) -> None:
        self._providers[provider.descriptor.id] = provider

    def unregister(self, provider_id: str) -> None:
        self._providers.pop(provider_id, None)

    def list(self) -> builtins.list[ProviderDescriptor]:
        return [provider.descriptor for provider in self._providers.values()]

    def select(self, capability: str) -> CapabilityProvider:
        candidates = [
            provider
            for provider in self._providers.values()
            if provider.descriptor.enabled and capability in provider.descriptor.capabilities
        ]
        if not candidates:
            raise LookupError(f"no control-plane provider for capability {capability}")
        return max(candidates, key=lambda item: item.descriptor.priority)

    async def invoke(
        self,
        request: CapabilityRequest,
        *,
        controller_id: str | None = None,
        work_id: str | None = None,
        run_id: str | None = None,
    ) -> CapabilityResult:
        provider = self.select(request.capability)
        result = await provider.invoke(
            request,
            InvocationContext(
                controller_id=controller_id,
                work_id=work_id,
                run_id=run_id,
                idempotency_key=request.idempotency_key,
                metadata=dict(request.metadata),
            ),
        )
        if not result.request_id:
            result = result.model_copy(update={"request_id": request.id})
        if not result.provider_id:
            result = result.model_copy(update={"provider_id": provider.descriptor.id})
        return result

    async def health(self) -> builtins.list[dict[str, Any]]:
        values: builtins.list[dict[str, Any]] = []
        for provider in self._providers.values():
            values.append((await provider.health()).model_dump(mode="json"))
        return values


__all__ = [
    "CapabilityProvider",
    "CapabilityRequest",
    "CapabilityResult",
    "EffectClass",
    "InvocationContext",
    "ProviderDescriptor",
    "ProviderHealth",
    "ProviderRegistry",
    "new_id",
]
