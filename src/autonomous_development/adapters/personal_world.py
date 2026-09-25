from __future__ import annotations

import hashlib
import hmac
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx

from autonomous_development.domain.models import DevelopmentTarget
from autonomous_development.ports.personal_context import (
    PersonalContextBundle,
    PersonalContextItem,
)


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
        service_identity: str = "autonomous-development",
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers = {"X-Service-Identity": service_identity}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        self._service_identity = service_identity
        self._workload_secret = workload_secret.strip() if workload_secret else ""
        self._client = httpx.Client(
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
            canonical = f"{self._service_identity}\n{purpose}\n{timestamp}".encode()
            signature = hmac.new(
                self._workload_secret.encode(), canonical, hashlib.sha256
            ).hexdigest()
            headers["X-Workload-Timestamp"] = timestamp
            headers["X-Workload-Signature"] = signature
        return headers

    def close(self) -> None:
        self._client.close()

    def ensure_contracts(self) -> None:
        response = self._client.get(
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

    def project_target(
        self,
        subject_id: UUID,
        target: DevelopmentTarget,
        *,
        observed_at: datetime | None = None,
    ) -> list[dict[str, Any]]:
        self._ensure_contracts()
        observed = observed_at or datetime.now(UTC)
        response = self._client.post(
            "/v1/domain-projections",
            headers=self._purpose_headers("domain-projection"),
            json={
                "subject_id": str(subject_id),
                "source_domain": self._service_identity,
                "source_object_ref": f"target:{target.id}",
                "source_version": target.target_contract_revision,
                "observed_at": observed.isoformat(),
                "claims": [
                    {
                        "record_kind": "resource-link",
                        "semantic": {
                            "kind": "predicate",
                            "id": "development-repository",
                            "namespace": "development",
                            "version": "0.1",
                        },
                        "value": {
                            "target_id": target.id,
                            "default_branch": target.default_branch,
                            "active_objective_revision_id": target.active_objective_revision_id,
                            "current_release_id": target.current_release_id,
                        },
                        "resource_ref": target.repository,
                        "domain": "development",
                        "relation": "development-target",
                        "metadata": {
                            "target_contract_revision": target.target_contract_revision,
                        },
                    }
                ],
                "metadata": {"projection_kind": "development-target"},
            },
        )
        if response.status_code >= 400:
            raise PersonalWorldBoundaryError(
                "Personal World rejected Development projection: "
                f"HTTP {response.status_code} {response.text[:500]}"
            )
        payload = response.json()
        if not isinstance(payload, list) or not all(
            isinstance(item, dict) for item in payload
        ):
            raise PersonalWorldBoundaryError(
                "Personal World returned malformed projection response"
            )
        return payload

    def model_context(
        self,
        subject_id: UUID,
        *,
        purpose: str,
        query: str,
    ) -> PersonalContextBundle:
        self._ensure_contracts()
        response = self._client.post(
            "/v1/model-context",
            headers=self._purpose_headers(purpose),
            json={
                "subject_id": str(subject_id),
                "purpose": purpose,
                "requested_kinds": ["fact", "preference", "relationship", "resource-link"],
                "query": query,
                "limit": 100,
            },
        )
        if response.status_code >= 400:
            raise PersonalWorldBoundaryError(
                "Personal World rejected model context: "
                f"HTTP {response.status_code} {response.text[:500]}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise PersonalWorldBoundaryError("Personal World model context is malformed")
        returned_purpose = str(payload.get("purpose", ""))
        if returned_purpose != purpose:
            raise PersonalWorldBoundaryError("Personal World model-context purpose mismatch")
        projection_ref = str(payload.get("projection_ref", "")).strip()
        if not projection_ref:
            raise PersonalWorldBoundaryError("Personal World model context lacks projection_ref")
        included = _context_items(payload.get("included_items"), "included_items")
        conflicts = _context_items(payload.get("unresolved_conflicts"), "unresolved_conflicts")
        stale = _context_items(payload.get("stale_items"), "stale_items")
        unknowns_raw = payload.get("unknowns", [])
        if not isinstance(unknowns_raw, list) or not all(
            isinstance(item, str) for item in unknowns_raw
        ):
            raise PersonalWorldBoundaryError("Personal World model-context unknowns are malformed")
        excluded = payload.get("excluded_count", 0)
        if not isinstance(excluded, int) or excluded < 0:
            raise PersonalWorldBoundaryError(
                "Personal World model-context excluded_count is invalid"
            )
        return PersonalContextBundle(
            projection_ref=projection_ref,
            purpose=purpose,
            included_items=included,
            blocked_items=(*conflicts, *stale),
            unknowns=tuple(unknowns_raw),
            excluded_count=excluded,
        )

    def revalidate(
        self,
        subject_id: UUID,
        *,
        purpose: str,
        basis_refs: tuple[str, ...],
    ) -> None:
        if not basis_refs:
            return
        self._ensure_contracts()
        response = self._client.get(
            f"/v1/subjects/{subject_id}/current",
            headers=self._purpose_headers(purpose),
        )
        if response.status_code >= 400:
            raise PersonalWorldBoundaryError(
                "Personal World rejected basis revalidation: "
                f"HTTP {response.status_code} {response.text[:500]}"
            )
        payload = response.json()
        if not isinstance(payload, list):
            raise PersonalWorldBoundaryError("Personal World current records are malformed")
        current: dict[str, tuple[int, str]] = {}
        for raw in payload:
            if not isinstance(raw, dict):
                raise PersonalWorldBoundaryError("Personal World current record is malformed")
            ref = str(raw.get("id", "")).strip()
            revision = raw.get("revision")
            status = str(raw.get("status", "")).strip()
            if not ref or not isinstance(revision, int) or revision < 1 or not status:
                raise PersonalWorldBoundaryError(
                    "Personal World current record identity is malformed"
                )
            current[ref] = (revision, status)

        for basis_ref in basis_refs:
            ref, revision = _parse_basis_ref(basis_ref)
            observed = current.get(ref)
            if observed is None:
                raise PersonalWorldBoundaryError(
                    f"Personal World basis disappeared and requires revalidation: {basis_ref}"
                )
            current_revision, status = observed
            if current_revision != revision or status != "current":
                raise PersonalWorldBoundaryError(
                    "Personal World basis changed and requires revalidation: "
                    f"{basis_ref}; observed personal-world:{ref}@{current_revision} "
                    f"status={status}"
                )

    def _ensure_contracts(self) -> None:
        if not self._contracts_verified:
            self.ensure_contracts()

def _context_items(value: object, label: str) -> tuple[PersonalContextItem, ...]:
    if not isinstance(value, list):
        raise PersonalWorldBoundaryError(f"Personal World {label} is malformed")
    items: list[PersonalContextItem] = []
    for raw in value:
        if not isinstance(raw, dict):
            raise PersonalWorldBoundaryError(f"Personal World {label} item is malformed")
        ref = str(raw.get("id", "")).strip()
        revision = raw.get("revision")
        kind = str(raw.get("kind", "")).strip()
        semantic = raw.get("semantic")
        status = str(raw.get("status", "")).strip()
        if not ref or not isinstance(revision, int) or revision < 1:
            raise PersonalWorldBoundaryError(f"Personal World {label} identity is malformed")
        if kind not in {"fact", "preference", "relationship", "resource-link"}:
            raise PersonalWorldBoundaryError(f"Personal World {label} kind is malformed")
        if not isinstance(semantic, dict):
            raise PersonalWorldBoundaryError(f"Personal World {label} semantic is malformed")
        items.append(
            PersonalContextItem(
                ref=ref,
                revision=revision,
                kind=kind,
                semantic=dict(semantic),
                value=raw.get("value"),
                status=status,
            )
        )
    return tuple(items)

def _parse_basis_ref(value: str) -> tuple[str, int]:
    prefix = "personal-world:"
    if not value.startswith(prefix) or "@" not in value:
        raise PersonalWorldBoundaryError(f"Personal World basis ref is malformed: {value}")
    ref, raw_revision = value[len(prefix):].rsplit("@", 1)
    try:
        revision = int(raw_revision)
    except ValueError as exc:
        raise PersonalWorldBoundaryError(
            f"Personal World basis ref revision is malformed: {value}"
        ) from exc
    if not ref or revision < 1:
        raise PersonalWorldBoundaryError(f"Personal World basis ref is malformed: {value}")
    return ref, revision