from pathlib import Path

from .cognition import CognitionEngine
from .decisions import DecisionLedger
from .domains import DomainProtocolService
from .effect_boundary import DomainEffectBoundaryService
from .epistemics import EpistemicLedger
from .execution import (
    CapabilityContractRegistry,
    CapabilityRequest,
    CapabilityResult,
    ExecutionService,
    InvocationContext,
    ProviderRegistry,
    Run,
    Work,
    assert_closed_capability_request,
    effect_identity_payload,
    reconciliation_contract_for,
)
from .governance import GovernanceService
from .identity import IdentityService
from .ledger import LedgerConcurrencyConflict, SemanticLedger, SQLiteLedger
from .lineage import RevisionLineageService
from .memory import MemoryService
from .ontology import OntologyRegistry
from .recovery import RecoveryService
from .qualification import QualificationService
from .responsibility import ResponsibilityService
from .responsibility_graph import ResponsibilityGraphService
from .state_bundle import StateBundleService
from .strategy import StrategyService
from .strategic_portfolio import StrategicPortfolioService


class WorldRuntime:
    def __init__(
        self,
        ledger: SemanticLedger,
        *,
        runtime_id: str = "world-runtime",
        root_principal: str | None = None,
    ) -> None:
        if root_principal is not None and not root_principal.strip():
            raise ValueError("root_principal must be non-empty when configured")
        self.runtime_id = runtime_id
        self.root_principal = root_principal
        self.ledger = ledger
        self.registry = ProviderRegistry()
        self.recovery = RecoveryService(ledger, self.registry)
        self.contract_registry = CapabilityContractRegistry()
        self.lineage = RevisionLineageService(ledger)
        self.ontology = OntologyRegistry(ledger, self.lineage)
        self.epistemics = EpistemicLedger(ledger)
        self.cognition = CognitionEngine(ledger, self.epistemics)
        self.memory = MemoryService(ledger, self.lineage)
        self.qualification = QualificationService(ledger)
        self.decisions = DecisionLedger(ledger, self.lineage)
        self.domains = DomainProtocolService(ledger)
        self.governance = GovernanceService(ledger, self.lineage)
        self.identity = IdentityService(ledger)
        self.strategy = StrategyService(ledger, self.lineage)
        self.state_bundle = StateBundleService(ledger)
        self.responsibility = ResponsibilityService(ledger)
        self.responsibility_graph = ResponsibilityGraphService(ledger, self.responsibility)
        self.responsibility.bind_graph(self.responsibility_graph)
        self.portfolio = StrategicPortfolioService(ledger, self.strategy, self.responsibility)
        self.execution = ExecutionService(ledger, self.governance)
        self.effect_boundary = DomainEffectBoundaryService(ledger, self.execution)

    @classmethod
    def sqlite(
        cls,
        path: str | Path = ":memory:",
        *,
        runtime_id: str = "world-runtime",
        root_principal: str | None = None,
    ) -> "WorldRuntime":
        return cls(
            SQLiteLedger(path),
            runtime_id=runtime_id,
            root_principal=root_principal,
        )

    @classmethod
    def postgres(
        cls,
        dsn: str,
        *,
        schema: str = "public",
        runtime_id: str = "world-runtime",
        root_principal: str | None = None,
    ) -> "WorldRuntime":
        try:
            from .postgres_ledger import PostgresLedger
        except ModuleNotFoundError as exc:
            if exc.name == "psycopg":
                raise RuntimeError(
                    "PostgreSQL support requires the 'postgres' package extra"
                ) from exc
            raise
        return cls(
            PostgresLedger(dsn, schema=schema),
            runtime_id=runtime_id,
            root_principal=root_principal,
        )

    async def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        assert_closed_capability_request(request)
        try:
            rule = self.contract_registry.effect_rule(request.capability)
        except KeyError:
            rule = None

        effective_request = request
        authorization_required = request.effect_class not in {"read", "read-only"}
        if rule is not None:
            resource = request.resource or request.resource_ref or ""
            if rule.resource_required and not resource:
                raise PermissionError(
                    f"{request.capability} requires an explicit resource boundary"
                )
            if rule.version_required and not request.subject_version_refs:
                raise PermissionError(
                    f"{request.capability} requires explicit subject version refs"
                )
            effective_request = request.model_copy(
                update={"effect_class": rule.impact_class}
            )
            authorization_required = rule.authorization_required
        elif effective_request.effect_class not in {"read", "read-only"}:
            authorization_required = True

        fingerprint = self.execution.validate_effect_identity(
            effective_request,
            result_projection="execution.provider-idempotency",
        )
        if effective_request.idempotency_key:
            replay = self.ledger.project_get(
                "execution.provider-idempotency", effective_request.idempotency_key
            )
            if replay is not None:
                return CapabilityResult(**replay[0])
            attempt = self.ledger.project_get(
                "execution.provider-attempt", effective_request.idempotency_key
            )
            if attempt is not None:
                return await self.recovery.recover(effective_request.idempotency_key)

        self.execution.prepare_invocation(
            effective_request,
            authorization_required=authorization_required,
            record_authorization_use=not bool(effective_request.idempotency_key),
        )
        provider = self.registry.select(effective_request)
        if effective_request.idempotency_key:
            reconciliation_contract = reconciliation_contract_for(provider.descriptor)
            attempt_value = {
                "request_id": effective_request.id,
                "provider_id": provider.descriptor.id,
                "provider_version": provider.descriptor.version,
                "capability": effective_request.capability,
                "effect_fingerprint": fingerprint,
                "effect_identity": effect_identity_payload(effective_request),
                "status": "started",
                "reconciliation_contract": (
                    reconciliation_contract.model_dump(mode="json")
                    if reconciliation_contract is not None
                    else None
                ),
            }
            for reservation_attempt in range(3):
                try:
                    with self.ledger.transaction():
                        self.execution.prepare_invocation(
                            effective_request,
                            authorization_required=authorization_required,
                            record_authorization_use=False,
                        )
                        self.ledger.project_put(
                            "execution.provider-attempt",
                            effective_request.idempotency_key,
                            attempt_value,
                            expected_version=0,
                        )
                        self.execution.bind_effect_identity(
                            effective_request,
                            fingerprint=fingerprint,
                        )
                        if authorization_required and effective_request.authorization_id:
                            self.governance.record_use(
                                effective_request.authorization_id,
                                effect_request_id=effective_request.id,
                            )
                        self.ledger.append(
                            stream=f"provider-request:{effective_request.id}",
                            kind="execution.provider-attempt.started",
                            payload={
                                "request_id": effective_request.id,
                                "provider_id": provider.descriptor.id,
                                "capability": effective_request.capability,
                                "idempotency_key": effective_request.idempotency_key,
                                "effect_fingerprint": fingerprint,
                            },
                        )
                    break
                except LedgerConcurrencyConflict:
                    existing_attempt = self.ledger.project_get(
                        "execution.provider-attempt",
                        effective_request.idempotency_key,
                    )
                    if existing_attempt is not None:
                        return await self.recovery.recover(
                            effective_request.idempotency_key
                        )
                    if reservation_attempt == 2:
                        raise
        else:
            self.execution.prepare_invocation(
                effective_request,
                authorization_required=authorization_required,
            )
            self.execution.bind_effect_identity(
                effective_request,
                fingerprint=fingerprint,
            )
        result = await provider.invoke(
            effective_request,
            InvocationContext(
                runtime_id=self.runtime_id,
                work_id=effective_request.work_id,
                run_id=effective_request.run_id,
                idempotency_key=effective_request.idempotency_key,
                lease_generation=effective_request.lease_generation,
                lease_owner=effective_request.lease_owner,
                metadata=dict(effective_request.metadata),
            ),
        )
        if not result.request_id:
            result = result.model_copy(update={"request_id": effective_request.id})
        if not result.provider_id:
            result = result.model_copy(update={"provider_id": provider.descriptor.id})
        value = result.model_dump(mode="json")
        result_access = {
            "request_id": effective_request.id,
            "principal": effective_request.principal,
            "authenticated_actor": effective_request.actor_ref,
            "work_id": effective_request.work_id,
            "run_id": effective_request.run_id,
        }
        with self.ledger.transaction():
            self.ledger.append(
                stream=f"provider-request:{effective_request.id}",
                kind="execution.provider-result.observed",
                payload={
                    "capability": effective_request.capability,
                    "effect_class": effective_request.effect_class,
                    "provider_id": result.provider_id,
                    "status": result.status,
                    "result": value,
                },
            )
            self.ledger.project_put(
                "execution.provider-result",
                effective_request.id,
                value,
            )
            self.ledger.project_put(
                "execution.provider-result-access",
                effective_request.id,
                result_access,
            )
            if effective_request.idempotency_key:
                self.ledger.project_put(
                    "execution.provider-idempotency",
                    effective_request.idempotency_key,
                    value,
                )
                current_attempt = self.ledger.project_get(
                    "execution.provider-attempt",
                    effective_request.idempotency_key,
                )
                if current_attempt is not None:
                    attempt_value, attempt_version = current_attempt
                    attempt_value["status"] = "committed"
                    self.ledger.project_put(
                        "execution.provider-attempt",
                        effective_request.idempotency_key,
                        attempt_value,
                        expected_version=attempt_version,
                    )
        return result

    def get_work(self, work_id: str) -> Work | None:
        return self.execution.get_work(work_id)

    def list_work(self, status: str | None = None) -> list[Work]:
        return self.execution.list_work(status)

    def start_run(self, work_id: str, *, workflow_id: str) -> Run:
        return self.execution.start_run(work_id, workflow_id=workflow_id)

    def list_runs(self, work_id: str) -> list[Run]:
        return self.execution.list_runs(work_id)

    async def run_capability(
        self,
        work_id: str,
        capability: str,
        *,
        run_id: str | None = None,
        instruction: str | None = None,
        parameters: dict[str, object] | None = None,
        constraints: dict[str, object] | None = None,
        idempotency_key: str | None = None,
        timeout_seconds: float | None = None,
        subject_version_refs: list[str] | None = None,
        resource_ref: str | None = None,
        actor_ref: str | None = None,
        preferred_provider_ids: list[str] | None = None,
        excluded_provider_ids: list[str] | None = None,
        effect_class: str = "read",
        principal: str | None = None,
        resource: str | None = None,
        authorization_id: str | None = None,
        lease_generation: int = 0,
        lease_owner: str | None = None,
    ) -> CapabilityResult:
        request = CapabilityRequest(
            capability=capability,
            work_id=work_id,
            run_id=run_id,
            instruction=instruction,
            parameters=dict(parameters or {}),
            constraints=dict(constraints or {}),
            idempotency_key=idempotency_key,
            timeout_seconds=timeout_seconds,
            subject_version_refs=list(subject_version_refs or []),
            resource_ref=resource_ref,
            actor_ref=actor_ref,
            preferred_provider_ids=list(preferred_provider_ids or []),
            excluded_provider_ids=list(excluded_provider_ids or []),
            effect_class=effect_class,
            principal=principal,
            resource=resource,
            authorization_id=authorization_id,
            lease_generation=lease_generation,
            lease_owner=lease_owner,
        )
        return await self.invoke(request)

    async def health(self) -> dict[str, object]:
        providers = [
            (await self.registry.health(d.id)).model_dump(mode="json")
            for d in self.registry.list()
        ]
        return {"runtime_id": self.runtime_id, "providers": providers}

    def close(self) -> None:
        self.ledger.close()
