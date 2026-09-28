from __future__ import annotations

from typing import Any, Mapping

import httpx

from aios.runtime_compat import SEMANTIC_KERNEL_VERSION, WORLD_RUNTIME_PROTOCOL


class WorldRuntimeBoundaryError(RuntimeError):
    pass


class WorldRuntimeHttpClient:
    """Shared HTTP and contract-negotiation boundary for domain Runtime adapters."""

    REQUIRED_CONTRACTS: Mapping[str, str] = {}

    def __init__(
        self,
        base_url: str,
        *,
        required_contracts: Mapping[str, str] | None = None,
        timeout_seconds: float = 3.0,
        transport: httpx.BaseTransport | None = None,
        bearer_token: str = "",
        delegation_id: str = "",
        component: str = "",
    ) -> None:
        headers: dict[str, str] = {}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        if delegation_id:
            headers["X-World-Runtime-Delegation"] = delegation_id
        self._required_contracts = dict(required_contracts or self.REQUIRED_CONTRACTS)
        self._component = component
        self._verified = False
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            headers=headers,
        )

    def close(self) -> None:
        self.client.close()

    def ensure_contracts(self) -> None:
        payload = self.get("/v1/contracts", verify=False)
        runtime_protocol = str(payload.get("runtime_protocol", ""))
        semantic_language = str(payload.get("semantic_language", ""))
        if runtime_protocol != WORLD_RUNTIME_PROTOCOL:
            suffix = f" is incompatible with {self._component}" if self._component else " mismatch"
            raise WorldRuntimeBoundaryError(f"World Runtime protocol{suffix}")
        if semantic_language != SEMANTIC_KERNEL_VERSION:
            if self._component:
                raise WorldRuntimeBoundaryError(
                    f"World Runtime semantic-language version is incompatible with {self._component}"
                )
            raise WorldRuntimeBoundaryError("World Runtime semantic-language mismatch")
        contracts = payload.get("contracts")
        if not isinstance(contracts, dict):
            raise WorldRuntimeBoundaryError("World Runtime contract catalog is malformed")
        for name, expected in self._required_contracts.items():
            descriptor = contracts.get(name)
            if not isinstance(descriptor, dict) or descriptor.get("current") != expected:
                raise WorldRuntimeBoundaryError(
                    f"World Runtime contract mismatch for {name}: expected {expected}"
                )
        self._verified = True

    def _ensure_contracts(self) -> None:
        if not self._verified:
            self.ensure_contracts()

    def get(self, path: str, *, verify: bool = True) -> dict[str, Any]:
        if verify:
            self._ensure_contracts()
        return self._object_response(path, self._send("GET", path))

    def get_optional(self, path: str) -> dict[str, Any] | None:
        self._ensure_contracts()
        response = self._send("GET", path)
        if response.status_code == 404:
            return None
        return self._object_response(path, response)

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_contracts()
        return self._object_response(path, self._send("POST", path, payload))

    def _send(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> httpx.Response:
        try:
            return self.client.request(method, path, json=payload)
        except httpx.HTTPError as exc:
            raise WorldRuntimeBoundaryError(
                f"World Runtime request failed for {path}: {type(exc).__name__}"
            ) from exc

    @staticmethod
    def _object_response(path: str, response: httpx.Response) -> dict[str, Any]:
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

    def health(self) -> dict[str, Any]:
        try:
            return self.get("/healthz", verify=False)
        except WorldRuntimeBoundaryError as exc:
            return {"status": "unavailable", "error": str(exc)}


__all__ = ["WorldRuntimeBoundaryError", "WorldRuntimeHttpClient"]
