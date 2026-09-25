from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any, ClassVar, TypeVar

import httpx

from autonomous_development.domain.models import (
    BuildArtifact,
    CandidateRevision,
    Deployment,
    DevelopmentCycle,
    DevelopmentTarget,
    EvidenceWindow,
    ProductObjectiveRevision,
    ReleasedVersion,
)

T = TypeVar("T")


class WorldRuntimeBoundaryError(RuntimeError):
    pass


class WorldRuntimeDevelopmentBridge:
    """HTTP-only adapter from Development semantics to generic World Runtime contracts."""

    REQUIRED_RUNTIME_PROTOCOL = "4.0"
    REQUIRED_SEMANTIC_LANGUAGE = "0.2.0"
    REQUIRED_CONTRACTS: ClassVar[dict[str, str]] = {
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
        "domain_effect_execution": "domain-effect-execution-v3",
        "domain_assignment": "domain-assignment-v3",
        "domain_report": "domain-report-v3",
    }

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 3.0,
        transport: httpx.BaseTransport | None = None,
        bearer_token: str = "",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._transport = transport
        self._bearer_token = bearer_token

    @staticmethod
    def responsibility_ref(cycle_id: str) -> str:
        return f"development:{cycle_id}"

    @staticmethod
    def assignment_ref(cycle_id: str) -> str:
        return f"development-assignment:{cycle_id}"

    def ensure_contracts(self) -> None:
        payload = self._get("/v1/contracts")
        if str(payload.get("runtime_protocol", "")) != self.REQUIRED_RUNTIME_PROTOCOL:
            raise WorldRuntimeBoundaryError(
                "World Runtime protocol is incompatible with Development"
            )
        if str(payload.get("semantic_language", "")) != self.REQUIRED_SEMANTIC_LANGUAGE:
            raise WorldRuntimeBoundaryError(
                "World Runtime semantic-language version is incompatible with Development"
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

    def ensure_assignment(
        self,
        *,
        cycle: DevelopmentCycle,
        target: DevelopmentTarget,
        objective: ProductObjectiveRevision,
        baseline: ReleasedVersion,
        evidence_window: EvidenceWindow | None = None,
    ) -> None:
        if (
            cycle.target_id != target.id
            or cycle.objective_revision_id != objective.id
            or cycle.baseline_release_id != baseline.id
        ):
            raise ValueError("development assignment identities do not agree")
        responsibility_ref = self.responsibility_ref(cycle.id)
        self._post(
            "/v1/responsibilities",
            {
                "id": responsibility_ref,
                "principal": "controller:autonomous-development",
                "subject": objective.statement,
                "domain": "development",
                "scope": {
                    "cycle_ref": cycle.id,
                    "target_ref": target.id,
                    "objective_revision_ref": objective.id,
                    "baseline_release_ref": baseline.id,
                },
            },
        )
        assignment_ref = self.assignment_ref(cycle.id)
        # A requirement-driven cycle has no product evidence window yet; the Runtime
        # still needs the Responsibility and DomainAssignment before the cycle may
        # change reality, so the evidence reference is omitted rather than invented.
        evidence_requirement: dict[str, object] = {
            "kind": "development-acceptance",
            "criteria": list(objective.acceptance_criteria),
        }
        work_payload: dict[str, object] = {
            "cycle_ref": cycle.id,
            "target_ref": target.id,
            "objective_revision_ref": objective.id,
            "baseline_release_ref": baseline.id,
            "acceptance_criteria": list(objective.acceptance_criteria),
        }
        if evidence_window is not None:
            evidence_requirement["evidence_window_ref"] = evidence_window.id
            work_payload["evidence_window_ref"] = evidence_window.id
        self._post(
            "/v1/domain-assignments",
            {
                "id": assignment_ref,
                "responsibility_ref": responsibility_ref,
                "domain": "development",
                "controller": "controller:autonomous-development",
                "evidence_requirements": [evidence_requirement],
                "review_conditions": [
                    {"trigger": "objective-revision", "ref": objective.id}
                ],
            },
        )
        self._post(
            f"/v1/domain-assignments/{assignment_ref}/reports",
            {
                "id": f"development-report:accepted:{cycle.id}",
                "kind": "accepted",
            },
        )
        work = self._post(
            "/v1/work",
            {
                "id": f"development-cycle-work:{cycle.id}",
                "responsibility_id": responsibility_ref,
                "kind": "development-cycle",
                "payload": work_payload,
            },
        )
        self._post(
            "/v1/runs",
            {
                "work_id": str(work["id"]),
                "workflow_id": f"development-cycle:{cycle.id}",
            },
        )

    def complete_promoted_release(
        self,
        *,
        cycle: DevelopmentCycle,
        candidate: CandidateRevision,
        artifact: BuildArtifact,
        deployment: Deployment,
        release: ReleasedVersion,
    ) -> None:
        responsibility_ref = self.responsibility_ref(cycle.id)
        current = self._get(f"/v1/responsibilities/{responsibility_ref}")
        status = str(current.get("status", ""))
        if status == "discharged":
            return
        if status == "failed":
            raise WorldRuntimeBoundaryError(
                "Development Runtime responsibility is already failed"
            )
        basis_refs, evidence_refs = self._completion_refs(
            cycle=cycle,
            candidate=candidate,
            artifact=artifact,
            deployment=deployment,
            release=release,
        )
        assignment_ref = self.assignment_ref(cycle.id)
        self._post(
            f"/v1/domain-assignments/{assignment_ref}/reports",
            {
                "id": f"development-report:outcome:{cycle.id}",
                "kind": "outcome-candidate",
                "basis_refs": list(basis_refs),
                "evidence_refs": list(evidence_refs),
                "outcome_refs": [
                    self._ref("outcome", release.id, namespace="development")
                ],
                "detail": {
                    "release_ref": release.id,
                    "target_ref": cycle.target_id,
                },
            },
        )
        self._post(
            f"/v1/domain-assignments/{assignment_ref}/reports",
            {
                "id": f"development-report:completion:{cycle.id}",
                "kind": "completion-proposal",
                "basis_refs": list(basis_refs),
                "evidence_refs": list(evidence_refs),
                "outcome_refs": [
                    self._ref("outcome", release.id, namespace="development")
                ],
            },
        )
        if status == "active":
            self._post(
                f"/v1/responsibilities/{responsibility_ref}/assess",
                {
                    "status": "satisfied",
                    "basis_refs": [
                        ref["id"] for ref in evidence_refs
                    ],
                },
            )
        elif status != "satisfied":
            raise WorldRuntimeBoundaryError(
                f"unexpected Development Runtime responsibility status: {status}"
            )

        decision_ref = f"development-discharge:{cycle.id}"
        self._post(
            "/v1/decisions",
            {
                "id": decision_ref,
                "subject": cycle.target_id,
                "decided_by": "controller:autonomous-development",
                "selected": {
                    "target_ref": responsibility_ref,
                    "operation": "discharge-responsibility",
                    "to_status": "discharged",
                    "outcome_type": "development.release.promoted",
                    "release_ref": release.id,
                    "development_target_ref": cycle.target_id,
                },
                "basis_refs": [ref["id"] for ref in evidence_refs],
            },
        )
        self._post(
            f"/v1/responsibilities/{responsibility_ref}/discharge",
            {"decision_id": decision_ref},
        )

    @staticmethod
    def reality_responsibility_ref(target_id: str) -> str:
        return f"responsibility:development-reality:{target_id}"

    @staticmethod
    def reality_work_ref(target_id: str) -> str:
        return f"work:development-reality:{target_id}"

    def ensure_reality_work(self, target_id: str) -> str:
        responsibility_ref = self.reality_responsibility_ref(target_id)
        self._post(
            "/v1/responsibilities",
            {
                "id": responsibility_ref,
                "principal": "controller:autonomous-development",
                "subject": f"Development target {target_id} reality-changing effects",
                "domain": "development",
                "scope": {"target_ref": target_id, "kind": "reality-effects"},
            },
        )
        work_ref = self.reality_work_ref(target_id)
        value = self._post(
            "/v1/work",
            {
                "id": work_ref,
                "responsibility_id": responsibility_ref,
                "kind": "development-reality-effect",
                "payload": {
                    "target_ref": target_id,
                    "domain": "development",
                    "standing": True,
                },
            },
        )
        return str(value["id"])

    def execute_external_effect(
        self,
        *,
        target_id: str,
        capability: str,
        resource: str,
        idempotency_key: str,
        parameters: dict[str, Any],
        subject_version_refs: list[str],
        provider_id: str,
        provider_version: str,
        invoke: Callable[[], T],
        encode: Callable[[T], dict[str, Any]],
        decode: Callable[[dict[str, Any]], T],
        evidence_refs: Callable[[T], list[str]] | None = None,
    ) -> T:
        if not idempotency_key.strip():
            raise ValueError("Development external effect requires idempotency_key")
        work_ref = self.ensure_reality_work(target_id)
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        decision_id = f"development-effect-decision:{digest}"
        mandate_id = f"development-effect-mandate:{digest}"
        authorization_id = f"development-effect-authorization:{digest}"
        request_id = f"development-effect-request:{digest}"

        self._post(
            "/v1/decisions",
            {
                "id": decision_id,
                "subject": resource,
                "decided_by": "controller:autonomous-development",
                "selected": {
                    "target_ref": resource,
                    "operation": "authorize-effect",
                    "action": capability,
                    "development_target_ref": target_id,
                },
                "basis_refs": [f"evidence:development-reality-work:{target_id}"],
            },
        )
        self._post(
            "/v1/mandates",
            {
                "id": mandate_id,
                "principal": "controller:autonomous-development",
                "scope": {"resource": resource},
                "authority_ceiling": {
                    "action": capability,
                    "resource": resource,
                },
            },
        )
        self._post(
            "/v1/authorizations",
            {
                "id": authorization_id,
                "principal": "controller:autonomous-development",
                "action": capability,
                "resource": resource,
                "mandate_id": mandate_id,
                "decision_id": decision_id,
            },
        )
        effect_request = {
            "id": request_id,
            "capability": capability,
            "work_id": work_ref,
            "effect_class": "external-effect",
            "principal": "controller:autonomous-development",
            "actor_ref": "controller:autonomous-development",
            "resource": resource,
            "resource_ref": resource,
            "authorization_id": authorization_id,
            "idempotency_key": idempotency_key,
            "parameters": dict(parameters),
            "subject_version_refs": list(subject_version_refs),
        }
        prepared = self._post(
            "/v1/domain-effects/prepare",
            {
                "request": effect_request,
                "provider_id": provider_id,
                "provider_version": provider_version,
            },
        )
        if prepared.get("status") == "committed":
            stored = prepared.get("result")
            if not isinstance(stored, dict):
                raise WorldRuntimeBoundaryError(
                    "committed Development effect is missing Runtime result"
                )
            data = stored.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("domain_result"), dict):
                raise WorldRuntimeBoundaryError(
                    "committed Development effect lacks domain replay result"
                )
            return decode(dict(data["domain_result"]))
        if prepared.get("status") != "authorized":
            raise WorldRuntimeBoundaryError(
                "Development effect requires reconciliation before any redispatch"
            )

        started = self._post(
            f"/v1/domain-effects/{idempotency_key}/start",
            {},
        )
        if started.get("dispatch_allowed") is not True:
            raise WorldRuntimeBoundaryError("Runtime did not grant Development provider dispatch")
        dispatch_generation = int(started["dispatch_generation"])

        try:
            result = invoke()
        except Exception as exc:
            self._post(
                f"/v1/domain-effects/{idempotency_key}/result",
                {
                    "dispatch_generation": dispatch_generation,
                    "result": {
                        "request_id": request_id,
                        "provider_id": provider_id,
                        "status": "unknown",
                        "error": {
                            "type": type(exc).__name__,
                            "message": str(exc)[:500],
                        },
                    },
                },
            )
            raise

        encoded = encode(result)
        refs = evidence_refs(result) if evidence_refs is not None else []
        self._post(
            f"/v1/domain-effects/{idempotency_key}/result",
            {
                "dispatch_generation": dispatch_generation,
                "result": {
                    "request_id": request_id,
                    "provider_id": provider_id,
                    "status": "succeeded",
                    "evidence_refs": refs,
                    "data": {"domain_result": encoded},
                },
            },
        )
        return result

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

    @classmethod
    def _completion_refs(
        cls,
        *,
        cycle: DevelopmentCycle,
        candidate: CandidateRevision,
        artifact: BuildArtifact,
        deployment: Deployment,
        release: ReleasedVersion,
    ) -> tuple[tuple[dict[str, str], ...], tuple[dict[str, str], ...]]:
        basis = (
            cls._ref(
                "development-cycle",
                f"{cycle.id}:v{cycle.version}",
                namespace="development",
            ),
            cls._ref("candidate", candidate.id, namespace="development"),
            cls._ref("artifact", artifact.id, namespace="development"),
            cls._ref("deployment", deployment.id, namespace="development"),
            cls._ref("release", release.id, namespace="development"),
        )
        evidence_ids = {
            artifact.build_evidence_ref,
            artifact.sbom_ref,
            artifact.vulnerability_scan_ref,
            *deployment.observation_refs,
        }
        evidence = tuple(
            cls._ref("evidence", identifier)
            for identifier in sorted(evidence_ids)
        )
        return basis, evidence

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with httpx.Client(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
                trust_env=False,
                follow_redirects=False,
                transport=self._transport,
                headers=(
                    {"Authorization": f"Bearer {self._bearer_token}"}
                    if self._bearer_token
                    else {}
                ),
            ) as client:
                response = client.post(path, json=payload)
        except httpx.HTTPError as exc:
            raise WorldRuntimeBoundaryError(
                f"World Runtime request failed for {path}: {type(exc).__name__}"
            ) from exc
        if response.status_code >= 400:
            raise WorldRuntimeBoundaryError(
                f"World Runtime rejected {path}: HTTP {response.status_code}"
            )
        value = response.json()
        if not isinstance(value, dict):
            raise WorldRuntimeBoundaryError(
                f"World Runtime returned non-object response for {path}"
            )
        return value

    def _get(self, path: str) -> dict[str, Any]:
        try:
            with httpx.Client(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
                trust_env=False,
                follow_redirects=False,
                transport=self._transport,
                headers=(
                    {"Authorization": f"Bearer {self._bearer_token}"}
                    if self._bearer_token
                    else {}
                ),
            ) as client:
                response = client.get(path)
        except httpx.HTTPError as exc:
            raise WorldRuntimeBoundaryError(
                f"World Runtime request failed for {path}: {type(exc).__name__}"
            ) from exc
        if response.status_code >= 400:
            raise WorldRuntimeBoundaryError(
                f"World Runtime rejected {path}: HTTP {response.status_code}"
            )
        value = response.json()
        if not isinstance(value, dict):
            raise WorldRuntimeBoundaryError(
                f"World Runtime returned non-object response for {path}"
            )
        return value


__all__ = ["WorldRuntimeBoundaryError", "WorldRuntimeDevelopmentBridge"]
