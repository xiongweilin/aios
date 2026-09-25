from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx

from ..config import Settings
from ..domain import AdministrativeCase, CaseStatus, EffectRecord
from ..effect_provider import (
    EffectProvider,
    ProviderExecutionResult,
    ProviderExecutionStatus,
    RealityObservation,
)
from ..execution_repository import ExecutionRepository
from ..governance import GovernanceRepository
from ..obligations import ObligationRepository
from ..persistence import SqlStore
from .runtime_capabilities import WORLD_RUNTIME_EFFECT_CAPABILITIES


class WorldRuntimeBoundaryError(RuntimeError):
    pass


def capability_for_effect(effect: EffectRecord) -> str:
    target = effect.target_system.strip().lower().replace("_", "-")
    operation = effect.operation.strip().lower().replace("_", "-")
    if not target or not operation:
        raise ValueError("administrative effect cannot map to an empty capability")
    return f"administrative.{target}.{operation}.v1"


def _stable_ref(kind: str, value: UUID) -> str:
    return f"{kind}_admin_{uuid5(NAMESPACE_URL, f'administrative-runtime:{kind}:{value}').hex}"


def _effect_matches_current_execution(
    case: AdministrativeCase,
    effect: EffectRecord,
) -> bool:
    """A planned effect survives the lifecycle-only AUTHORIZED -> EXECUTING transition.

    effect.case_version identifies the case version at planning/authorization time.
    Dispatch occurs after begin_execution() advances the case by exactly one version
    without changing the authority epoch or semantic governance basis.
    """

    return (
        case.case_id == effect.case_id
        and case.authority_epoch == effect.authority_epoch
        and case.status is CaseStatus.EXECUTING
        and case.version == effect.case_version + 1
    )


class WorldRuntimeBridge:
    """Compile governed Administrative effects into the generic World Runtime surface."""

    REQUIRED_RUNTIME_PROTOCOL = "4.0"
    REQUIRED_SEMANTIC_LANGUAGE = "0.2.0"
    REQUIRED_CONTRACTS = {
        "request_authentication": "request-authentication-v2",
        "transition_authority": "transition-authority-v1",
        "read_authorization": "read-authorization-v1",
        "persistent_responsibility": "persistent-responsibility-v3",
        "responsibility_assessment": "responsibility-assessment-v3",
        "responsibility_discharge": "responsibility-discharge-v3",
        "work_admission": "work-admission-v4",
        "run_lifecycle": "run-lifecycle-v2",
        "decision_record": "decision-record-v4",
        "mandate_registration": "mandate-registration-v4",
        "authorization_issue": "authorization-issue-v4",
        "capability_invocation": "capability-invocation-v6",
        "reconciliation": "provider-reconciliation-v1",
        "domain_assignment": "domain-assignment-v3",
        "domain_report": "domain-report-v3",
    }

    def __init__(
        self,
        store: SqlStore,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.execution = ExecutionRepository(store)
        self.governance = GovernanceRepository(store)
        self.obligations = ObligationRepository(store)
        runtime_token = (
            settings.world_runtime_bearer_token.get_secret_value()
            if settings.world_runtime_bearer_token is not None
            else ""
        )
        headers: dict[str, str] = {}
        if runtime_token:
            headers["Authorization"] = f"Bearer {runtime_token}"
        if settings.world_runtime_delegation_id:
            headers["X-World-Runtime-Delegation"] = settings.world_runtime_delegation_id
        self.client = httpx.Client(
            base_url=settings.world_runtime_base_url.rstrip("/"),
            timeout=settings.world_runtime_timeout_seconds,
            transport=transport,
            headers=headers,
        )
        self._contracts_verified = False

    @property
    def enabled(self) -> bool:
        return self.settings.world_runtime_mode != "disabled"

    @property
    def cutover(self) -> bool:
        return self.settings.world_runtime_mode == "cutover"

    def close(self) -> None:
        self.client.close()

    @staticmethod
    def assignment_ref_for_responsibility(responsibility_ref: str) -> str:
        return f"administrative-assignment:{responsibility_ref}"

    @staticmethod
    def _ref(
        kind: str,
        identifier: str,
        *,
        namespace: str = "universal",
    ) -> dict[str, str]:
        return {
            "kind": kind,
            "id": identifier,
            "namespace": namespace,
            "version": "0.1",
        }

    def ensure_contracts(self) -> None:
        response = self.client.get("/v1/contracts")
        if response.status_code >= 400:
            raise WorldRuntimeBoundaryError(
                f"World Runtime rejected /v1/contracts: HTTP {response.status_code}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise WorldRuntimeBoundaryError("World Runtime contract catalog is malformed")
        if str(payload.get("runtime_protocol", "")) != self.REQUIRED_RUNTIME_PROTOCOL:
            raise WorldRuntimeBoundaryError(
                "World Runtime protocol is incompatible with Administrative"
            )
        if str(payload.get("semantic_language", "")) != self.REQUIRED_SEMANTIC_LANGUAGE:
            raise WorldRuntimeBoundaryError(
                "World Runtime semantic-language version is incompatible with Administrative"
            )
        contracts = payload.get("contracts")
        if not isinstance(contracts, dict):
            raise WorldRuntimeBoundaryError("World Runtime contract catalog is malformed")
        for name, expected in self.REQUIRED_CONTRACTS.items():
            descriptor = contracts.get(name)
            if not isinstance(descriptor, dict) or descriptor.get("current") != expected:
                raise WorldRuntimeBoundaryError(
                    f"World Runtime contract mismatch for {name}: expected {expected}"
                )
        self._contracts_verified = True

    def _ensure_contracts(self) -> None:
        if not self._contracts_verified:
            self.ensure_contracts()

    def execute_effect(
        self,
        effect: EffectRecord,
        payload: dict[str, Any],
    ) -> ProviderExecutionResult:
        capability = capability_for_effect(effect)
        if capability not in WORLD_RUNTIME_EFFECT_CAPABILITIES:
            return ProviderExecutionResult(
                status=ProviderExecutionStatus.FAILED,
                error=f"capability is outside the Administrative Runtime cutover set: {capability}",
                retryable=False,
            )
        try:
            context = self._context(effect)
            responsibility_ref = _stable_ref("responsibility", effect.effect_id)
            decision_ref = _stable_ref("decision", effect.effect_id)
            mandate_ref = _stable_ref("mandate", effect.effect_id)
            authorization_ref = _stable_ref("authorization", effect.effect_id)
            request_ref = _stable_ref("request", effect.effect_id)
            resource_ref = f"administrative:{effect.target_system}:{effect.subject_ref}"

            self._post(
                "/v1/responsibilities",
                {
                    "id": responsibility_ref,
                    "principal": self.settings.world_runtime_principal,
                    "subject": effect.subject_ref,
                    "domain": "administrative",
                    "scope": {
                        "case_id": str(effect.case_id),
                        "case_version": effect.case_version,
                        "authority_epoch": effect.authority_epoch,
                        "obligation_id": str(effect.obligation_id),
                        "governance_basis_id": str(effect.governance_basis_id),
                        "administrative_authorization_id": str(effect.authorization_id),
                        "target_system": effect.target_system,
                        "operation": effect.operation,
                    },
                },
            )
            assignment_ref = self.assignment_ref_for_responsibility(responsibility_ref)
            self._post(
                "/v1/domain-assignments",
                {
                    "id": assignment_ref,
                    "responsibility_ref": responsibility_ref,
                    "domain": "administrative",
                    "controller": "controller:administrative-orchestrator",
                    "authority_refs": [
                        f"administrative-authorization:{effect.authorization_id}",
                        f"governance-basis:{effect.governance_basis_id}",
                    ],
                    "evidence_requirements": [
                        {
                            "kind": "administrative-postcondition-readback",
                            "expected": context["expected_postcondition"],
                        }
                    ],
                    "review_conditions": [
                        {
                            "trigger": "authority-epoch-change",
                            "authority_epoch": effect.authority_epoch,
                        }
                    ],
                },
            )
            self._post(
                f"/v1/domain-assignments/{assignment_ref}/reports",
                {
                    "id": f"{assignment_ref}:accepted",
                    "kind": "accepted",
                },
            )
            work = self._post(
                "/v1/work",
                {
                    "responsibility_id": responsibility_ref,
                    "kind": "administrative-effect",
                    "payload": {
                        "effect_id": str(effect.effect_id),
                        "requested_capabilities": [capability],
                        "expected_postcondition": context["expected_postcondition"],
                        "metadata": {
                            "administrative_case_id": str(effect.case_id),
                            "authority_epoch": effect.authority_epoch,
                            "obligation_id": str(effect.obligation_id),
                        },
                    },
                },
            )
            run = self._post(
                "/v1/runs",
                {
                    "work_id": work["id"],
                    "workflow_id": "administrative-effect",
                },
            )
            basis_refs = [
                f"administrative-authorization:{effect.authorization_id}",
                f"administrative-obligation:{effect.obligation_id}",
                f"governance-basis:{effect.governance_basis_id}",
            ]
            self._post(
                "/v1/decisions",
                {
                    "id": decision_ref,
                    "subject": effect.subject_ref,
                    "decided_by": self.settings.world_runtime_principal,
                    "selected": {
                        "target_ref": resource_ref,
                        "operation": "authorize-effect",
                        "action": capability,
                        "effect_id": str(effect.effect_id),
                        "administrative_issuer_principal_id": context["issuer_principal_id"],
                    },
                    "basis_refs": basis_refs,
                },
            )
            self._post(
                "/v1/mandates",
                {
                    "id": mandate_ref,
                    "principal": self.settings.world_runtime_principal,
                    "scope": {
                        "case_id": str(effect.case_id),
                        "authority_epoch": effect.authority_epoch,
                        "obligation_id": str(effect.obligation_id),
                    },
                    "authority_ceiling": {
                        "action": capability,
                        "resource": resource_ref,
                    },
                },
            )
            runtime_auth = self._post(
                "/v1/authorizations",
                {
                    "id": authorization_ref,
                    "principal": self.settings.world_runtime_principal,
                    "action": capability,
                    "resource": resource_ref,
                    "mandate_id": mandate_ref,
                    "decision_id": decision_ref,
                    "annotations": {
                        "administrative_authorization_id": str(effect.authorization_id),
                        "governance_basis_id": str(effect.governance_basis_id),
                        "administrative_issuer_principal_id": context["issuer_principal_id"],
                    },
                },
            )
            result = self._post(
                "/v1/invoke",
                {
                    "id": request_ref,
                    "capability": capability,
                    "work_id": work["id"],
                    "run_id": run["id"],
                    "parameters": {**payload, "subject_ref": effect.subject_ref},
                    "idempotency_key": self.idempotency_key_for_effect(effect.effect_id),
                    "actor_ref": self.settings.world_runtime_principal,
                    "principal": self.settings.world_runtime_principal,
                    "resource_ref": resource_ref,
                    "resource": resource_ref,
                    "subject_version_refs": [
                        f"administrative-case:{effect.case_id}:v{effect.case_version}",
                        f"authority-epoch:{effect.authority_epoch}",
                    ],
                    "authorization_id": runtime_auth["id"],
                    "effect_class": "external-effect",
                },
            )
        except (WorldRuntimeBoundaryError, ValueError) as exc:
            return ProviderExecutionResult(
                status=ProviderExecutionStatus.FAILED,
                error=str(exc),
                retryable=False,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            return ProviderExecutionResult(
                status=ProviderExecutionStatus.OUTCOME_UNKNOWN,
                error=str(exc),
                retryable=False,
            )

        status = str(result.get("status", "unknown"))
        provider_ref = (
            result.get("external_ref")
            or result.get("external_operation_ref")
            or f"world-runtime:{result.get('provider_id', 'unknown')}:{result.get('request_id', request_ref)}"
        )
        if status == "succeeded":
            mapped = ProviderExecutionStatus.SUCCEEDED
        elif status in {"unknown", "unavailable"}:
            mapped = ProviderExecutionStatus.OUTCOME_UNKNOWN
        else:
            mapped = ProviderExecutionStatus.FAILED
        return ProviderExecutionResult(
            status=mapped,
            provider_ref=str(provider_ref) if provider_ref else None,
            error=None if mapped is ProviderExecutionStatus.SUCCEEDED else str(result.get("error") or status),
            retryable=False,
        )

    def provision_responsibility(
        self,
        *,
        responsibility_ref: str,
        principal: str,
        subject: str,
        scope: dict[str, Any],
    ) -> None:
        self._post(
            "/v1/responsibilities",
            {
                "id": responsibility_ref,
                "principal": principal,
                "subject": subject,
                "domain": "administrative",
                "scope": scope,
            },
        )
        assignment_ref = self.assignment_ref_for_responsibility(responsibility_ref)
        self._post(
            "/v1/domain-assignments",
            {
                "id": assignment_ref,
                "responsibility_ref": responsibility_ref,
                "domain": "administrative",
                "controller": "controller:administrative-orchestrator",
            },
        )
        self._post(
            f"/v1/domain-assignments/{assignment_ref}/reports",
            {"id": f"{assignment_ref}:accepted", "kind": "accepted"},
        )

    def request_ref_for_effect(self, effect_id: UUID) -> str:
        return _stable_ref("request", effect_id)

    def idempotency_key_for_effect(self, effect_id: UUID) -> str:
        return f"administrative-effect:{effect_id}"

    def reconcile_effect(self, effect_id: UUID) -> dict[str, Any]:
        return self._post(
            f"/v1/reconcile/{self.idempotency_key_for_effect(effect_id)}",
            {},
        )

    def responsibility_ref_for_effect(self, effect_id: UUID) -> str:
        return _stable_ref("responsibility", effect_id)

    def responsibility_status(self, responsibility_ref: str) -> str:
        return str(self._get(f"/v1/responsibilities/{responsibility_ref}")["status"])

    def discharge_responsibility(
        self,
        responsibility_ref: str,
        *,
        decision_ref: str,
        decided_by: str,
        subject_ref: str,
        basis_refs: tuple[str, ...],
    ) -> tuple[str, str, str]:
        assignment_ref = self.assignment_ref_for_responsibility(responsibility_ref)
        assignment_path = f"/v1/domain-assignments/{assignment_ref}"
        self._ensure_contracts()
        response = self.client.get(assignment_path)
        if response.status_code == 404:
            assignment = self._post(
                "/v1/domain-assignments",
                {
                    "id": assignment_ref,
                    "responsibility_ref": responsibility_ref,
                    "domain": "administrative",
                    "controller": "controller:administrative-orchestrator",
                },
            )
        elif response.status_code >= 400:
            raise WorldRuntimeBoundaryError(
                "World Runtime rejected "
                f"{assignment_path}: HTTP {response.status_code} {response.text[:500]}"
            )
        else:
            raw_assignment = response.json()
            if not isinstance(raw_assignment, dict):
                raise WorldRuntimeBoundaryError(
                    "World Runtime returned non-object domain assignment"
                )
            assignment = raw_assignment

        if (
            str(assignment.get("id", "")) != assignment_ref
            or str(assignment.get("responsibility_ref", "")) != responsibility_ref
            or str(assignment.get("domain", "")) != "administrative"
            or str(assignment.get("controller", ""))
            != "controller:administrative-orchestrator"
        ):
            raise WorldRuntimeBoundaryError(
                "World Runtime domain assignment does not match Administrative responsibility"
            )
        if str(assignment.get("status", "")) == "offered":
            self._post(
                f"/v1/domain-assignments/{assignment_ref}/reports",
                {"id": f"{assignment_ref}:accepted", "kind": "accepted"},
            )
        self._post(
            f"/v1/domain-assignments/{assignment_ref}/reports",
            {
                "id": f"{assignment_ref}:completion",
                "kind": "completion-proposal",
                "basis_refs": [
                    self._ref(
                        "administrative-subject",
                        subject_ref,
                        namespace="administrative",
                    )
                ],
                "evidence_refs": [
                    self._ref("evidence", ref)
                    for ref in basis_refs
                ],
                "detail": {"subject_ref": subject_ref},
            },
        )
        assessment = self._post(
            f"/v1/responsibilities/{responsibility_ref}/assess",
            {"status": "satisfied", "basis_refs": list(basis_refs)},
        )
        self._post(
            "/v1/decisions",
            {
                "id": decision_ref,
                "subject": subject_ref,
                "decided_by": decided_by,
                "selected": {
                    "target_ref": responsibility_ref,
                    "operation": "discharge-responsibility",
                    "to_status": "discharged",
                },
                "basis_refs": [*basis_refs, str(assessment["assessment_ref"])],
            },
        )
        transition = self._post(
            f"/v1/responsibilities/{responsibility_ref}/discharge",
            {"decision_id": decision_ref},
        )
        return (
            str(assessment["assessment_ref"]),
            decision_ref,
            str(transition["transition_ref"]),
        )

    def _context(self, effect: EffectRecord) -> dict[str, Any]:
        if effect.obligation_id is None or effect.governance_basis_id is None:
            raise WorldRuntimeBoundaryError("runtime effect requires obligation and governance lineage")
        case = self.store.get_case(effect.case_id)
        if case is None:
            raise WorldRuntimeBoundaryError("administrative case is unavailable")
        if not _effect_matches_current_execution(case, effect):
            raise WorldRuntimeBoundaryError("effect is stale against the current Administrative case")
        authorization = self.execution.get_authorization(effect.authorization_id)
        if authorization is None:
            raise WorldRuntimeBoundaryError("administrative execution authorization is unavailable")
        if authorization.revoked_at is not None:
            raise WorldRuntimeBoundaryError("administrative execution authorization is revoked")
        if (
            authorization.case_id != effect.case_id
            or authorization.authority_epoch != effect.authority_epoch
            or authorization.target_system != effect.target_system
            or effect.operation not in authorization.allowed_operations
            or authorization.subject_ref != effect.subject_ref
        ):
            raise WorldRuntimeBoundaryError("administrative execution authorization does not match effect")
        basis = self.governance.get_current_for_case(effect.case_id, effect.authority_epoch)
        if basis is None or basis.basis_id != effect.governance_basis_id:
            raise WorldRuntimeBoundaryError("current governance basis does not match effect")
        validation = self.governance.revalidate(basis, case)
        if not validation.valid:
            raise WorldRuntimeBoundaryError(
                "administrative governance basis is stale: " + "; ".join(validation.reasons)
            )
        obligation_set = self.obligations.get_current(effect.case_id, effect.authority_epoch)
        if obligation_set is None:
            raise WorldRuntimeBoundaryError("current administrative obligation set is unavailable")
        obligation = next(
            (
                item
                for item in obligation_set.obligations
                if item.obligation_id == effect.obligation_id
            ),
            None,
        )
        if obligation is None:
            raise WorldRuntimeBoundaryError("effect obligation is not current")
        if (
            obligation.target_system != effect.target_system
            or obligation.required_operation != effect.operation
            or obligation.subject_ref != effect.subject_ref
            or obligation.governance_basis_id != effect.governance_basis_id
        ):
            raise WorldRuntimeBoundaryError("effect does not implement its current obligation")
        return {
            "issuer_principal_id": authorization.issuer_principal_id,
            "expected_postcondition": dict(obligation.expected_postcondition),
        }

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_contracts()
        response = self.client.post(path, json=payload)
        if response.status_code >= 400:
            raise WorldRuntimeBoundaryError(
                f"World Runtime rejected {path}: HTTP {response.status_code} {response.text[:500]}"
            )
        raw = response.json()
        if not isinstance(raw, dict):
            raise WorldRuntimeBoundaryError(f"World Runtime returned non-object response for {path}")
        return raw

    def _get(self, path: str) -> dict[str, Any]:
        self._ensure_contracts()
        response = self.client.get(path)
        if response.status_code >= 400:
            raise WorldRuntimeBoundaryError(
                f"World Runtime rejected {path}: HTTP {response.status_code} {response.text[:500]}"
            )
        raw = response.json()
        if not isinstance(raw, dict):
            raise WorldRuntimeBoundaryError(f"World Runtime returned non-object response for {path}")
        return raw


class WorldRuntimeEffectProvider:
    """Use World Runtime for execution while keeping domain read-back independent."""

    def __init__(
        self,
        fallback: EffectProvider,
        bridge: WorldRuntimeBridge,
    ) -> None:
        self.fallback = fallback
        self.bridge = bridge

    def execute(self, effect: EffectRecord, payload: dict[str, Any]) -> ProviderExecutionResult:
        if not self.bridge.cutover or capability_for_effect(effect) not in WORLD_RUNTIME_EFFECT_CAPABILITIES:
            return self.fallback.execute(effect, payload)
        return self.bridge.execute_effect(effect, payload)

    def observe(self, effect: EffectRecord) -> RealityObservation:
        return self.fallback.observe(effect)
