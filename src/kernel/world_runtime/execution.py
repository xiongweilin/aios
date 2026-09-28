from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from .common import new_id, utcnow
from .execution_types import (
    CapabilityContractRegistry as CapabilityContractRegistry,
    CapabilityEffectRule as CapabilityEffectRule,
    CapabilityProvider as CapabilityProvider,
    CapabilityRequest as CapabilityRequest,
    CapabilityResult as CapabilityResult,
    EffectClass as EffectClass,
    EffectIdentityReboundError as EffectIdentityReboundError,
    InvocationContext as InvocationContext,
    ProviderDescriptor as ProviderDescriptor,
    ProviderHealth as ProviderHealth,
    ProviderRegistry as ProviderRegistry,
    ReconciliationContract as ReconciliationContract,
    Run as Run,
    Work as Work,
    assert_closed_capability_request as assert_closed_capability_request,
    effect_identity_fingerprint as effect_identity_fingerprint,
    effect_identity_payload as effect_identity_payload,
    reconciliation_contract_for as reconciliation_contract_for,
)
from .governance import GovernanceService
from .ledger import LedgerConcurrencyConflict, SemanticLedger


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


__all__ = [
    "CapabilityContractRegistry",
    "CapabilityEffectRule",
    "CapabilityProvider",
    "CapabilityRequest",
    "CapabilityResult",
    "EffectClass",
    "EffectIdentityReboundError",
    "ExecutionService",
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
