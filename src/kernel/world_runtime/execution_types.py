from __future__ import annotations

import builtins
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .common import new_id


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
    constraints: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    effect_semantics: str = "pure"
    side_effect_class: str = "pure"
    reversibility: str = "unknown"
    provider_family: str | None = None
    model_family: str | None = None
    operator: str | None = None
    execution_domain: str | None = None
    credential_domain: str | None = None
    data_source_domain: str | None = None
    evaluation_domain: str | None = None
    network_domain: str | None = None
    trust_boundary: str | None = None
    reconciliation_protocol_identity: str | None = None
    reconciliation_protocol_version: str | None = None
    reconciliation_repeatability: str = "unknown"
    reconciliation_contract_version: str | None = None


class ReconciliationContract(BaseModel):
    provider_id: str
    provider_version: str
    protocol_identity: str
    protocol_version: str
    repeatability_mode: str
    contract_version: str
    digest: str


def reconciliation_contract_for(
    descriptor: ProviderDescriptor,
) -> ReconciliationContract | None:
    identity = descriptor.reconciliation_protocol_identity
    version = descriptor.reconciliation_protocol_version
    contract_version = descriptor.reconciliation_contract_version
    mode = descriptor.reconciliation_repeatability
    if not identity or not version or not contract_version:
        return None
    payload = {
        "provider_id": descriptor.id,
        "provider_version": descriptor.version,
        "protocol_identity": identity,
        "protocol_version": version,
        "repeatability_mode": mode,
        "contract_version": contract_version,
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return ReconciliationContract(**payload, digest=digest)


class ProviderHealth(BaseModel):
    provider_id: str
    available: bool
    detail: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class InvocationContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    runtime_id: str
    work_id: str | None = None
    run_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    lease_generation: int = 0
    lease_owner: str | None = None
    idempotency_key: str | None = None


class CapabilityRequest(BaseModel):
    """Provider request plus optional governance binding.

    principal/resource are semantic authorization coordinates. actor_ref/resource_ref
    remain provider-facing coordinates and do not themselves confer authority.

    The top-level request schema is closed. Provider-specific executable semantics
    must be carried by declared fields such as parameters, constraints, or metadata,
    all of which participate in durable effect identity.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("request"))
    capability: str
    work_id: str | None = None
    run_id: str | None = None
    instruction: str | None = None
    input_artifact_refs: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    preferred_provider_ids: list[str] = Field(default_factory=list)
    excluded_provider_ids: list[str] = Field(default_factory=list)
    timeout_seconds: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    step_key: str | None = None
    actor_ref: str | None = None
    resource_ref: str | None = None
    subject_version_refs: list[str] = Field(default_factory=list)
    effect_class: str = "read"
    lease_generation: int = 0
    lease_owner: str | None = None
    principal: str | None = None
    resource: str | None = None
    authorization_id: str | None = None


class EffectIdentityReboundError(ValueError):
    """One durable idempotency identity was reused for a different semantic request."""


def assert_closed_capability_request(request: CapabilityRequest) -> None:
    """Reject undeclared fields even on preconstructed/tainted Python model objects."""
    declared = set(CapabilityRequest.model_fields)
    extras = set(request.__dict__) - declared
    model_extra = getattr(request, "__pydantic_extra__", None)
    if isinstance(model_extra, dict):
        extras.update(model_extra)
    if extras:
        rendered = ", ".join(sorted(str(value) for value in extras))
        raise ValueError(f"CapabilityRequest contains undeclared fields: {rendered}")


def effect_identity_payload(request: CapabilityRequest) -> dict[str, Any]:
    assert_closed_capability_request(request)
    raw = request.model_dump(mode="json")
    keys = (
        "capability",
        "work_id",
        "run_id",
        "instruction",
        "input_artifact_refs",
        "parameters",
        "constraints",
        "metadata",
        "step_key",
        "actor_ref",
        "resource_ref",
        "subject_version_refs",
        "effect_class",
        "principal",
        "resource",
    )
    return {key: raw.get(key) for key in keys}


def effect_identity_fingerprint(request: CapabilityRequest) -> str:
    payload = effect_identity_payload(request)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class CapabilityResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    request_id: str = ""
    provider_id: str = ""
    status: str = "succeeded"
    output_artifact_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    message: str | None = None
    error: dict[str, Any] | str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    external_operation_ref: str | None = None
    reconciled: bool = False
    provider_success: bool | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    external_ref: str | None = None

    @model_validator(mode="after")
    def _derive_provider_success(self) -> CapabilityResult:
        if self.provider_success is None:
            self.provider_success = self.status == "succeeded"
        if self.external_ref is None and self.external_operation_ref is not None:
            self.external_ref = self.external_operation_ref
        return self


class CapabilityProvider(Protocol):
    @property
    def descriptor(self) -> ProviderDescriptor: ...

    async def health(self) -> ProviderHealth: ...

    async def invoke(
        self, request: CapabilityRequest, context: InvocationContext
    ) -> CapabilityResult: ...

    async def cancel(self, request_id: str) -> None: ...


class ProviderRegistry:
    """Live provider registry. Registration never owns durable semantic truth."""

    def __init__(self) -> None:
        self._providers: dict[str, CapabilityProvider] = {}
        self._enabled: dict[str, bool] = {}

    def register(self, provider: CapabilityProvider) -> ProviderDescriptor:
        descriptor = provider.descriptor
        if descriptor.id in self._providers:
            raise ValueError(f"provider already registered: {descriptor.id}")
        self._providers[descriptor.id] = provider
        self._enabled[descriptor.id] = descriptor.enabled
        return descriptor

    def get(self, provider_id: str) -> CapabilityProvider:
        return self._providers[provider_id]

    def unregister(self, provider_id: str) -> CapabilityProvider:
        provider = self._providers.pop(provider_id)
        self._enabled.pop(provider_id, None)
        return provider

    def list(self) -> builtins.list[ProviderDescriptor]:
        return [
            provider.descriptor.model_copy(
                update={"enabled": self._enabled.get(provider.descriptor.id, False)}
            )
            for provider in self._providers.values()
        ]

    def providers_for(self, capability: str) -> builtins.list[ProviderDescriptor]:
        values = [
            descriptor
            for descriptor in self.list()
            if descriptor.enabled and capability in descriptor.capabilities
        ]
        return sorted(values, key=lambda value: (-value.priority, value.id))

    def select(self, request: CapabilityRequest) -> CapabilityProvider:
        excluded = set(request.excluded_provider_ids)
        candidates = [
            descriptor
            for descriptor in self.providers_for(request.capability)
            if descriptor.id not in excluded
        ]
        if request.preferred_provider_ids:
            order = {value: index for index, value in enumerate(request.preferred_provider_ids)}
            candidates.sort(
                key=lambda d: (order.get(d.id, len(order)), -d.priority, d.id)
            )
        if not candidates:
            raise KeyError(f"no provider for capability {request.capability!r}")
        return self.get(candidates[0].id)

    async def health(self, provider_id: str) -> ProviderHealth:
        provider = self._providers[provider_id]
        try:
            value = await provider.health()
        except Exception as exc:
            return ProviderHealth(provider_id=provider_id, available=False, detail=str(exc))
        if not self._enabled.get(provider_id, False):
            return value.model_copy(update={"available": False, "detail": "disabled"})
        return value


@dataclass(frozen=True, slots=True)
class CapabilityEffectRule:
    """Generic governance metadata for one capability.

    Rules describe effect requirements only. They do not authorize an invocation.
    """
    capability: str
    impact_class: str
    authorization_required: bool
    resource_required: bool
    version_required: bool
    blast_radius: int = 0
    exposure: int = 0


class CapabilityContractRegistry:
    def __init__(self) -> None:
        self._effect_rules: dict[str, CapabilityEffectRule] = {}

    def register_effect_rule(self, rule: CapabilityEffectRule) -> None:
        if not rule.capability.strip():
            raise ValueError("capability must be non-empty")
        self._effect_rules[rule.capability] = rule

    def effect_rule(self, capability: str) -> CapabilityEffectRule:
        return self._effect_rules[capability]

    def list_effect_rules(self) -> tuple[CapabilityEffectRule, ...]:
        return tuple(self._effect_rules[key] for key in sorted(self._effect_rules))


@dataclass(frozen=True, slots=True)
class Work:
    id: str
    responsibility_id: str
    kind: str
    payload: Mapping[str, Any]
    status: str = "pending"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: Any = None
    updated_at: Any = None


@dataclass(frozen=True, slots=True)
class Run:
    id: str
    work_id: str
    workflow_id: str
    status: str = "running"
    started_at: Any = None
    ended_at: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    lease_owner: str | None = None
    lease_generation: int = 0
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None

__all__ = [
    "CapabilityContractRegistry",
    "CapabilityEffectRule",
    "CapabilityProvider",
    "CapabilityRequest",
    "CapabilityResult",
    "EffectClass",
    "EffectIdentityReboundError",
    "InvocationContext",
    "ProviderDescriptor",
    "ProviderHealth",
    "ProviderRegistry",
    "ReconciliationContract",
    "Run",
    "Work",
    "assert_closed_capability_request",
    "effect_identity_fingerprint",
    "effect_identity_payload",
    "reconciliation_contract_for",
]
