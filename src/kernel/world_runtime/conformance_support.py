from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from semantic_language import SemanticKind, SemanticRef

from .decisions import Decision
from .execution import CapabilityRequest, CapabilityResult, InvocationContext, ProviderDescriptor, ProviderHealth
from .responsibility import Responsibility
from .runtime import WorldRuntime


SUITE_VERSION = "world-runtime-conformance-v11"

_CONFORMANCE_TOKENS: dict[str, str] = {}


def _conformance_token(name: str) -> str:
    value = _CONFORMANCE_TOKENS.get(name)
    if value is None:
        value = secrets.token_urlsafe(32)
        _CONFORMANCE_TOKENS[name] = value
    return value


def conformance_vectors() -> dict[str, Any]:
    resource = files("world_runtime.contracts").joinpath("vectors.json")
    value = json.loads(resource.read_text(encoding="utf-8"))
    if value.get("suite_version") != SUITE_VERSION:
        raise ValueError("World Runtime conformance suite version mismatch")
    if not isinstance(value.get("vectors"), list) or not value["vectors"]:
        raise ValueError("World Runtime conformance vectors are unavailable")
    return value


@dataclass(frozen=True, slots=True)
class ConformanceResult:
    vector_id: str
    passed: bool
    detail: str = ""


class _RecoverableProvider:
    def __init__(self) -> None:
        self.invoke_calls = 0
        self.reconcile_calls = 0
        self._descriptor = ProviderDescriptor(
            id="conformance-provider",
            name="Conformance Provider",
            version="1",
            capabilities=["conformance.effect"],
            reconciliation_protocol_identity="conformance.reconcile",
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
        del context
        self.invoke_calls += 1
        return CapabilityResult(
            request_id=request.id,
            provider_id=self.descriptor.id,
            status="succeeded",
        )

    async def cancel(self, request_id: str) -> None:
        del request_id

    async def reconcile(self, request_id: str) -> CapabilityResult | None:
        self.reconcile_calls += 1
        return CapabilityResult(
            request_id=request_id,
            provider_id=self.descriptor.id,
            status="succeeded",
            reconciled=True,
        )

def _responsibility(runtime: WorldRuntime, identifier: str = "responsibility:conformance") -> None:
    runtime.responsibility.create(
        Responsibility(
            id=identifier,
            principal="service:conformance",
            subject="conformance",
            domain="conformance",
        )
    )

def _decision(
    runtime: WorldRuntime,
    identifier: str = "decision:conformance",
    *,
    target_ref: str = "resource:1",
    operation: str = "authorize-effect",
    selected: dict[str, object] | None = None,
) -> None:
    runtime.decisions.record(
        Decision(
            id=identifier,
            subject="conformance",
            decided_by="service:conformance",
            selected={
                "target_ref": target_ref,
                "operation": operation,
                **dict(selected or {}),
            },
            basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:conformance"),),
        )
    )

