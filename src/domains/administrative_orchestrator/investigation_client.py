from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID

import httpx
from pydantic import Field

from .domain import UtcModel
from .investigation_models import (
    InvestigationConstraints,
    InvestigationProposal,
    InvestigationTriggerType,
)


def _secret(value: object) -> str:
    get_secret_value = getattr(value, "get_secret_value", None)
    if get_secret_value is None:
        return ""
    resolved = get_secret_value()
    return resolved.strip() if isinstance(resolved, str) else ""


def _read_secret_file(path: str) -> str:
    candidate = path.strip()
    if not candidate:
        return ""
    secret_path = Path(candidate)
    if not secret_path.is_file() or secret_path.is_symlink():
        return ""
    return secret_path.read_text(encoding="utf-8").strip()


class InvestigationClientError(RuntimeError):
    pass


class InvestigationRequestEnvelope(UtcModel):
    """Bounded advisory input; it intentionally contains references, not secrets."""

    protocol_version: str = "administrative-investigation-v1"
    investigation_id: UUID
    case_id: UUID
    tenant_id: str = Field(min_length=1, max_length=512)
    case_kind: str = Field(min_length=1, max_length=128)
    case_status: str = Field(min_length=1, max_length=64)
    authority_epoch: int = Field(ge=1)
    trigger_type: InvestigationTriggerType
    requested_question: str = Field(min_length=1, max_length=4000)
    allowed_evidence_refs: tuple[str, ...] = ()
    current_fact_snapshot_ref: str | None = None
    current_governance_basis_ref: str | None = None
    current_obligation_refs: tuple[str, ...] = ()
    current_commitment_refs: tuple[str, ...] = ()
    constraints: InvestigationConstraints


class InvestigationClient(Protocol):
    def investigate(self, request: InvestigationRequestEnvelope) -> InvestigationProposal:
        """Return advisory output only; never execute or authorize an effect."""


class UnavailableInvestigationClient:
    """Fail-closed default when no advisory service is configured."""

    def investigate(self, request: InvestigationRequestEnvelope) -> InvestigationProposal:
        del request
        raise InvestigationClientError("investigation advisory client is unavailable")


class HttpInvestigationClient:
    """Production-shaped narrow HTTP adapter for a separately owned advisory service."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10.0,
        bearer_token: str = "",
    ) -> None:
        self.base_url = base_url.strip().rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.bearer_token = bearer_token.strip()
        if not self.base_url:
            raise ValueError("investigation client base_url must not be blank")
        if timeout_seconds <= 0:
            raise ValueError("investigation client timeout must be positive")

    def investigate(self, request: InvestigationRequestEnvelope) -> InvestigationProposal:
        headers = {"Content-Type": "application/json"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        try:
            response = httpx.post(
                f"{self.base_url}/v1/investigations",
                json=request.model_dump(mode="json"),
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise InvestigationClientError("investigation advisory request failed") from exc
        if isinstance(payload, dict) and isinstance(payload.get("proposal"), dict):
            payload = payload["proposal"]
        if not isinstance(payload, dict):
            raise InvestigationClientError("investigation advisory response is not an object")
        try:
            return InvestigationProposal.model_validate(payload)
        except ValueError as exc:
            raise InvestigationClientError("investigation advisory response failed schema validation") from exc


def build_investigation_client(settings: object) -> InvestigationClient:
    """Build only the advisory boundary; no Administrative or provider client is exposed."""

    base_url = str(getattr(settings, "investigation_client_url", "")).strip()
    client_token = _secret(getattr(settings, "investigation_client_api_key", None))
    if not client_token:
        client_token = _read_secret_file(
            str(getattr(settings, "investigation_client_api_key_file", ""))
        )
    timeout_seconds = float(
        getattr(settings, "investigation_client_timeout_seconds", 10.0)
    )
    if base_url:
        return HttpInvestigationClient(
            base_url,
            timeout_seconds=timeout_seconds,
            bearer_token=client_token,
        )

    model_url = str(getattr(settings, "investigation_model_url", "")).strip()
    if model_url:
        from .model_investigation_client import ModelInvestigationClient

        model_token = _secret(getattr(settings, "investigation_model_api_key", None))
        if not model_token:
            model_token = _read_secret_file(
                str(getattr(settings, "investigation_model_api_key_file", ""))
            )

        return ModelInvestigationClient(
            model_url,
            model=str(getattr(settings, "investigation_model_name", "")),
            protocol=str(
                getattr(settings, "investigation_model_protocol", "openai-chat")
            ),
            timeout_seconds=timeout_seconds,
            bearer_token=model_token,
            provider=str(
                getattr(settings, "investigation_model_provider", "configured-model-gateway")
            ),
            model_version=str(
                getattr(settings, "investigation_model_version", "configured")
            ),
            prompt_ref=str(
                getattr(settings, "investigation_model_prompt_ref", "adaptive-investigation-v1")
            ),
            max_tokens=int(getattr(settings, "investigation_model_max_tokens", 2000)),
        )
    return UnavailableInvestigationClient()


__all__ = [
    "HttpInvestigationClient",
    "InvestigationClient",
    "InvestigationClientError",
    "InvestigationRequestEnvelope",
    "UnavailableInvestigationClient",
    "build_investigation_client",
]
