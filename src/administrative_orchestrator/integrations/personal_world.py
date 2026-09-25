from __future__ import annotations

import hashlib
import hmac
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx

from ..domain import RoleAssignment


class PersonalWorldBoundaryError(RuntimeError):
    pass


class PersonalWorldProjectionClient:
    REQUIRED_CONTRACT = "personal-world-contracts-v1"
    REQUIRED_CONFORMANCE = "personal-world-conformance-v1"
    REQUIRED_PACKAGE = "1.0.0"
    REQUIRED_SEMANTIC_LANGUAGE = "0.2.0"

    def __init__(
        self,
        base_url: str,
        *,
        bearer_token: str | None = None,
        workload_secret: str | None = None,
        service_identity: str = "administrative-orchestrator",
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers = {"X-Service-Identity": service_identity}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        self.service_identity = service_identity
        self._workload_secret = workload_secret.strip() if workload_secret else ""
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
            headers=headers,
        )
        self._contracts_verified = False

    def _purpose_headers(self, purpose: str) -> dict[str, str]:
        headers = {"X-Purpose": purpose}
        if self._workload_secret:
            timestamp = str(int(time.time()))
            canonical = f"{self.service_identity}\n{purpose}\n{timestamp}".encode()
            signature = hmac.new(
                self._workload_secret.encode(), canonical, hashlib.sha256
            ).hexdigest()
            headers["X-Workload-Timestamp"] = timestamp
            headers["X-Workload-Signature"] = signature
        return headers

    def close(self) -> None:
        self.client.close()

    def ensure_contracts(self) -> None:
        response = self.client.get(
            "/v1/contracts",
            headers=self._purpose_headers("contract-discovery"),
        )
        if response.status_code >= 400:
            raise PersonalWorldBoundaryError(
                f"Personal World rejected contract discovery: HTTP {response.status_code}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise PersonalWorldBoundaryError("Personal World contract catalog is malformed")
        expected = {
            "manifest": self.REQUIRED_CONTRACT,
            "conformance": self.REQUIRED_CONFORMANCE,
            "package": self.REQUIRED_PACKAGE,
            "semantic_language": self.REQUIRED_SEMANTIC_LANGUAGE,
        }
        for key, value in expected.items():
            if str(payload.get(key, "")) != value:
                raise PersonalWorldBoundaryError(
                    f"Personal World contract mismatch for {key}: expected {value}"
                )
        self._contracts_verified = True

    def project_role_assignment(
        self,
        subject_id: UUID,
        assignment: RoleAssignment,
        *,
        observed_at: datetime | None = None,
    ) -> list[dict[str, Any]]:
        self._ensure_contracts()
        observed = observed_at or datetime.now(UTC)
        claim: dict[str, Any] = {
            "record_kind": "relationship",
            "semantic": {
                "kind": "predicate",
                "id": "employee-of",
                "namespace": "administrative",
                "version": "0.1",
            },
            "value": {
                "assignment_id": str(assignment.assignment_id),
                "principal_id": assignment.principal_id,
                "role": assignment.role,
            },
            "target_ref": assignment.organization_scope,
            "relation_namespace": "administrative.employment",
            "valid_from": assignment.valid_from.isoformat(),
            "metadata": {
                "role": assignment.role,
                "principal_id": assignment.principal_id,
            },
        }
        if assignment.valid_until is not None:
            claim["valid_until"] = assignment.valid_until.isoformat()

        response = self.client.post(
            "/v1/domain-projections",
            headers=self._purpose_headers("domain-projection"),
            json={
                "subject_id": str(subject_id),
                "source_domain": self.service_identity,
                "source_object_ref": f"role-assignment:{assignment.assignment_id}",
                "observed_at": observed.isoformat(),
                "claims": [claim],
                "metadata": {"projection_kind": "administrative-role-assignment"},
            },
        )
        if response.status_code >= 400:
            raise PersonalWorldBoundaryError(
                "Personal World rejected Administrative projection: "
                f"HTTP {response.status_code} {response.text[:500]}"
            )
        payload = response.json()
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise PersonalWorldBoundaryError(
                "Personal World returned malformed projection response"
            )
        return payload

    def _ensure_contracts(self) -> None:
        if not self._contracts_verified:
            self.ensure_contracts()
