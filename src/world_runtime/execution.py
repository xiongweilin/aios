from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
import hashlib
import json
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .common import new_id, utcnow
from .governance import GovernanceService
from .ledger import LedgerConcurrencyConflict, SemanticLedger


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
    def _derive_provider_success(self) -> "CapabilityResult":
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

    def set_enabled(self, provider_id: str, enabled: bool) -> None:
        if provider_id not in self._providers:
            raise KeyError(provider_id)
        self._enabled[provider_id] = enabled

    def list(self) -> list[ProviderDescriptor]:
        return [
            provider.descriptor.model_copy(
                update={"enabled": self._enabled.get(provider.descriptor.id, False)}
            )
            for provider in self._providers.values()
        ]

    def providers_for(self, capability: str) -> list[ProviderDescriptor]:
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


class ExecutionService:
    """Work/Run lifecycle, fencing, and invocation-legality preparation.

    This service never crosses the reality/provider boundary. WorldRuntime.invoke()
    is the sole canonical capability invocation path.
    """

    def __init__(
        self,
        ledger: SemanticLedger,
        governance: GovernanceService,
    ) -> None:
        self.ledger = ledger
        self.governance = governance

    def admit_work(
        self,
        *,
        responsibility_id: str,
        kind: str,
        payload: Mapping[str, Any],
        work_id: str | None = None,
    ) -> Work:
        responsibility = self.ledger.project_get("responsibility.current", responsibility_id)
        if responsibility is None:
            raise ValueError("work admission requires standing responsibility")
        if responsibility[0].get("status") != "active":
            raise ValueError("work admission requires active responsibility")
        identifier = work_id or new_id("work")
        existing = self.ledger.project_get("execution.work", identifier)
        if existing is not None:
            value = existing[0]
            if (
                value.get("responsibility_id") != responsibility_id
                or value.get("kind") != kind
                or dict(value.get("payload", {})) != dict(payload)
            ):
                raise ValueError("work identity rebound")
            current = self.get_work(identifier)
            assert current is not None
            return current

        now = utcnow()
        work = Work(
            identifier,
            responsibility_id,
            kind,
            dict(payload),
            "pending",
            dict(payload.get("metadata", {})) if isinstance(payload.get("metadata"), Mapping) else {},
            now,
            now,
        )
        with self.ledger.transaction():
            self.ledger.project_put(
                "execution.work",
                work.id,
                {
                    "id": work.id,
                    "responsibility_id": responsibility_id,
                    "kind": kind,
                    "payload": dict(payload),
                    "status": "pending",
                    "metadata": dict(work.metadata),
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                },
            )
            self.ledger.append(
                stream=f"work:{work.id}",
                kind="execution.work.admitted",
                payload={"id": work.id, "responsibility_id": responsibility_id},
            )
        return work

    def get_work(self, work_id: str) -> Work | None:
        current = self.ledger.project_get("execution.work", work_id)
        if current is None:
            return None
        value = current[0]
        return Work(
            id=value["id"],
            responsibility_id=value["responsibility_id"],
            kind=value["kind"],
            payload=dict(value.get("payload", {})),
            status=value["status"],
            metadata=dict(value.get("metadata", {})),
            created_at=value.get("created_at"),
            updated_at=value.get("updated_at"),
        )

    def list_work(self, status: str | None = None) -> list[Work]:
        ids: list[str] = []
        for event in self.ledger.events(kind="execution.work.admitted"):
            wid = str(event.payload["id"])
            if wid not in ids:
                ids.append(wid)
        values = [work for wid in ids if (work := self.get_work(wid)) is not None]
        return values if status is None else [work for work in values if work.status == status]

    def update_work_status(self, work_id: str, status: str) -> Work:
        current = self.ledger.project_get("execution.work", work_id)
        if current is None:
            raise KeyError(work_id)
        value, version = current
        value["status"] = status
        value["updated_at"] = utcnow().isoformat()
        with self.ledger.transaction():
            self.ledger.project_put(
                "execution.work",
                work_id,
                value,
                expected_version=version,
            )
            self.ledger.append(
                stream=f"work:{work_id}",
                kind="execution.work.status-changed",
                payload={"work_id": work_id, "status": status},
            )
        updated = self.get_work(work_id)
        assert updated is not None
        return updated

    def start_run(self, work_id: str, *, workflow_id: str) -> Run:
        work = self.get_work(work_id)
        if work is None:
            raise KeyError(work_id)
        if work.status not in {"pending", "running"}:
            raise PermissionError("terminal Work cannot start a fresh Run")
        now = utcnow()
        run = Run(
            id=new_id("run"),
            work_id=work_id,
            workflow_id=workflow_id,
            status="running",
            started_at=now,
        )
        with self.ledger.transaction():
            self.ledger.project_put(
                "execution.run",
                run.id,
                {
                    "id": run.id,
                    "work_id": work_id,
                    "workflow_id": workflow_id,
                    "status": "running",
                    "started_at": now.isoformat(),
                    "ended_at": None,
                    "metadata": {},
                    "lease_owner": None,
                    "lease_generation": 0,
                    "lease_expires_at": None,
                    "heartbeat_at": None,
                },
            )
            self.ledger.append(
                stream=f"work:{work_id}",
                kind="execution.run.started",
                payload={"run_id": run.id, "workflow_id": workflow_id},
            )
        return run

    def get_run(self, run_id: str) -> Run | None:
        row = self.ledger.project_get("execution.run", run_id)
        if row is None:
            return None
        value = row[0]
        return Run(
            id=value["id"],
            work_id=value["work_id"],
            workflow_id=value["workflow_id"],
            status=value["status"],
            started_at=value.get("started_at"),
            ended_at=value.get("ended_at"),
            metadata=dict(value.get("metadata", {})),
            lease_owner=value.get("lease_owner"),
            lease_generation=int(value.get("lease_generation", 0)),
            lease_expires_at=self._parse_datetime(value.get("lease_expires_at")),
            heartbeat_at=self._parse_datetime(value.get("heartbeat_at")),
        )

    def list_runs(self, work_id: str) -> list[Run]:
        run_ids = [
            str(event.payload["run_id"])
            for event in self.ledger.events(stream=f"work:{work_id}")
            if event.kind == "execution.run.started"
        ]
        return [run for run_id in run_ids if (run := self.get_run(run_id)) is not None]

    def acquire_run_lease(
        self,
        run_id: str,
        *,
        owner: str,
        ttl_seconds: float = 30.0,
    ) -> Run:
        if not owner.strip():
            raise ValueError("lease owner must be non-empty")
        if ttl_seconds <= 0:
            raise ValueError("lease ttl must be positive")
        now = utcnow()
        try:
            with self.ledger.transaction():
                current = self.ledger.project_get("execution.run", run_id)
                if current is None:
                    raise KeyError(run_id)
                value, version = current
                expires = self._parse_datetime(value.get("lease_expires_at"))
                current_owner = value.get("lease_owner")
                active = bool(current_owner) and expires is not None and expires > now
                if active:
                    if current_owner != owner:
                        raise PermissionError("run lease is held by another owner")
                    run = self.get_run(run_id)
                    assert run is not None
                    return run
                value["lease_owner"] = owner
                value["lease_generation"] = int(value.get("lease_generation", 0)) + 1
                value["lease_expires_at"] = (
                    now + timedelta(seconds=ttl_seconds)
                ).isoformat()
                value["heartbeat_at"] = now.isoformat()
                self.ledger.project_put(
                    "execution.run",
                    run_id,
                    value,
                    expected_version=version,
                )
                self.ledger.append(
                    stream=f"run:{run_id}",
                    kind="execution.run.lease-acquired",
                    payload={
                        "run_id": run_id,
                        "owner": owner,
                        "lease_generation": value["lease_generation"],
                        "lease_expires_at": value["lease_expires_at"],
                    },
                )
        except LedgerConcurrencyConflict as exc:
            latest = self.get_run(run_id)
            if latest is None:
                raise KeyError(run_id) from exc
            if latest.lease_owner == owner and latest.lease_expires_at is not None:
                if latest.lease_expires_at > utcnow():
                    return latest
            if latest.lease_owner and latest.lease_expires_at is not None:
                if latest.lease_expires_at > utcnow():
                    raise PermissionError("run lease is held by another owner") from exc
            raise PermissionError("run lease acquisition lost a concurrent race") from exc
        run = self.get_run(run_id)
        assert run is not None
        return run

    def heartbeat_run_lease(
        self,
        run_id: str,
        *,
        owner: str,
        lease_generation: int,
        ttl_seconds: float = 30.0,
    ) -> Run:
        if ttl_seconds <= 0:
            raise ValueError("lease ttl must be positive")
        now = utcnow()
        with self.ledger.transaction():
            current = self.ledger.project_get("execution.run", run_id)
            if current is None:
                raise KeyError(run_id)
            value, version = current
            self._assert_lease_identity(
                value,
                owner=owner,
                lease_generation=lease_generation,
                now=now,
            )
            value["lease_expires_at"] = (now + timedelta(seconds=ttl_seconds)).isoformat()
            value["heartbeat_at"] = now.isoformat()
            self.ledger.project_put(
                "execution.run",
                run_id,
                value,
                expected_version=version,
            )
            self.ledger.append(
                stream=f"run:{run_id}",
                kind="execution.run.lease-heartbeat",
                payload={
                    "run_id": run_id,
                    "owner": owner,
                    "lease_generation": lease_generation,
                    "lease_expires_at": value["lease_expires_at"],
                },
            )
        run = self.get_run(run_id)
        assert run is not None
        return run

    def release_run_lease(
        self,
        run_id: str,
        *,
        owner: str,
        lease_generation: int,
    ) -> Run:
        now = utcnow()
        with self.ledger.transaction():
            current = self.ledger.project_get("execution.run", run_id)
            if current is None:
                raise KeyError(run_id)
            value, version = current
            self._assert_lease_identity(
                value,
                owner=owner,
                lease_generation=lease_generation,
                now=now,
            )
            value["lease_owner"] = None
            value["lease_expires_at"] = None
            value["heartbeat_at"] = now.isoformat()
            self.ledger.project_put(
                "execution.run",
                run_id,
                value,
                expected_version=version,
            )
            self.ledger.append(
                stream=f"run:{run_id}",
                kind="execution.run.lease-released",
                payload={
                    "run_id": run_id,
                    "owner": owner,
                    "lease_generation": lease_generation,
                },
            )
        run = self.get_run(run_id)
        assert run is not None
        return run

    def assert_run_fencing(self, request: CapabilityRequest) -> None:
        if request.run_id is None:
            return
        current = self.ledger.project_get("execution.run", request.run_id)
        if current is None:
            raise KeyError(request.run_id)
        value = current[0]
        owner = value.get("lease_owner")
        generation = int(value.get("lease_generation", 0))
        expires = self._parse_datetime(value.get("lease_expires_at"))
        if not owner and generation == 0:
            return
        if not owner:
            raise PermissionError("run lease has been released; reacquire before execution")
        self._assert_lease_identity(
            value,
            owner=request.lease_owner or "",
            lease_generation=request.lease_generation,
            now=utcnow(),
        )
        if expires is None:
            raise PermissionError("leased run is missing lease expiry")

    @staticmethod
    def _assert_lease_identity(
        value: Mapping[str, Any],
        *,
        owner: str,
        lease_generation: int,
        now: datetime,
    ) -> None:
        current_owner = str(value.get("lease_owner") or "")
        current_generation = int(value.get("lease_generation", 0))
        expires = ExecutionService._parse_datetime(value.get("lease_expires_at"))
        if owner != current_owner:
            raise PermissionError("run lease owner mismatch")
        if lease_generation != current_generation:
            raise PermissionError("run lease generation mismatch")
        if expires is None or expires <= now:
            raise PermissionError("run lease has expired")

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))

    def update_run_status(self, run_id: str, status: str) -> Run:
        current = self.ledger.project_get("execution.run", run_id)
        if current is None:
            raise KeyError(run_id)
        value, version = current
        value["status"] = status
        if status != "running":
            value["ended_at"] = utcnow().isoformat()
        self.ledger.project_put("execution.run", run_id, value, expected_version=version)
        run = self.get_run(run_id)
        assert run is not None
        return run

    def validate_effect_identity(
        self,
        request: CapabilityRequest,
        *,
        result_projection: str,
    ) -> str | None:
        effectful = request.effect_class not in {"read", "read-only"}
        key = request.idempotency_key
        if effectful and not key:
            raise PermissionError("effectful capability requires durable idempotency_key")
        if not key:
            return None

        fingerprint = effect_identity_fingerprint(request)
        identity = self.ledger.project_get("execution.effect-identity", key)
        attempt = self.ledger.project_get("execution.provider-attempt", key)
        completed = self.ledger.project_get(result_projection, key)

        historical: list[str] = []
        if identity is not None:
            previous = identity[0].get("fingerprint")
            if not previous:
                raise EffectIdentityReboundError(
                    "durable effect identity is missing its semantic fingerprint"
                )
            historical.append(str(previous))
        if attempt is not None:
            previous = attempt[0].get("effect_fingerprint")
            if not previous:
                raise EffectIdentityReboundError(
                    "historical provider attempt lacks durable effect fingerprint"
                )
            historical.append(str(previous))
        if completed is not None and not historical:
            raise EffectIdentityReboundError(
                "historical idempotent result lacks qualified durable effect identity"
            )
        if any(previous != fingerprint for previous in historical):
            raise EffectIdentityReboundError(
                "idempotency identity rebound to a different semantic effect"
            )
        return fingerprint

    def bind_effect_identity(
        self,
        request: CapabilityRequest,
        *,
        fingerprint: str | None,
    ) -> None:
        if not request.idempotency_key or fingerprint is None:
            return
        key = request.idempotency_key
        existing = self.ledger.project_get("execution.effect-identity", key)
        if existing is not None:
            if existing[0].get("fingerprint") != fingerprint:
                raise EffectIdentityReboundError(
                    "idempotency identity rebound to a different semantic effect"
                )
            return
        value = {
            "idempotency_key": key,
            "fingerprint": fingerprint,
            "semantic_request": effect_identity_payload(request),
        }
        try:
            with self.ledger.transaction():
                self.ledger.project_put(
                    "execution.effect-identity",
                    key,
                    value,
                    expected_version=0,
                )
                self.ledger.append(
                    stream=f"effect-identity:{key}",
                    kind="execution.effect-identity.bound",
                    payload=value,
                )
        except LedgerConcurrencyConflict:
            existing = self.ledger.project_get("execution.effect-identity", key)
            if existing is None:
                raise
            if existing[0].get("fingerprint") != fingerprint:
                raise EffectIdentityReboundError(
                    "idempotency identity rebound to a different semantic effect"
                )

    def prepare_invocation(
        self,
        request: CapabilityRequest,
        *,
        authorization_required: bool,
        record_authorization_use: bool = True,
    ) -> CapabilityRequest:
        """Validate the canonical Runtime execution legality for one fresh invocation.

        Historical idempotent replay/reconciliation happens before this method. Any fresh
        effectful invocation must be bound to current Work and an active Responsibility.
        Read-only invocations may omit Work; if Work/Run references are present they are
        still validated and may never be dangling or cross-boundary.
        """
        effectful = request.effect_class not in {"read", "read-only"}
        if request.run_id is not None and request.work_id is None:
            raise ValueError("run-bound invocation requires work_id")

        work = None
        if request.work_id is not None:
            work = self.get_work(request.work_id)
            if work is None:
                raise KeyError(request.work_id)
            if work.status not in {"pending", "running"}:
                raise PermissionError("fresh invocation requires non-terminal Work")
            responsibility = self.ledger.project_get(
                "responsibility.current",
                work.responsibility_id,
            )
            if responsibility is None or responsibility[0].get("status") != "active":
                raise PermissionError("execution requires active responsibility")
        elif effectful:
            raise PermissionError("effectful capability requires work_id")

        if request.run_id is not None:
            run = self.get_run(request.run_id)
            if run is None:
                raise KeyError(request.run_id)
            if work is None or run.work_id != work.id:
                raise PermissionError("run does not belong to invocation work")
            if run.status != "running":
                raise PermissionError("fresh invocation requires running Run")
            self.assert_run_fencing(request)

        principal = request.principal or request.actor_ref or ""
        resource = request.resource or request.resource_ref or ""
        if effectful and authorization_required:
            if not request.authorization_id:
                raise PermissionError("effectful capability requires authorization")
            self.governance.assert_usable(
                request.authorization_id,
                principal=principal,
                action=request.capability,
                resource=resource,
                context={
                    "request": {
                        "id": request.id,
                        "capability": request.capability,
                        "parameters": dict(request.parameters),
                        "metadata": dict(request.metadata),
                    },
                    "work_id": request.work_id,
                    "run_id": request.run_id,
                    "principal": principal,
                    "resource": resource,
                },
            )
            if record_authorization_use:
                self.governance.record_use(
                    request.authorization_id,
                    effect_request_id=request.id,
                )
        return request

    def mark_work_complete(
        self, work_id: str, *, evidence_refs: tuple[str, ...]
    ) -> None:
        if not evidence_refs:
            raise ValueError("work completion requires evidence")
        current = self.ledger.project_get("execution.work", work_id)
        if current is None:
            raise KeyError(work_id)
        value, version = current
        value["status"] = "completed"
        value["completion_evidence_refs"] = list(evidence_refs)
        self.ledger.project_put(
            "execution.work", work_id, value, expected_version=version
        )
