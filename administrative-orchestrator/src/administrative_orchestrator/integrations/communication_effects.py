from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..intake.artifacts import FilesystemArtifactStore
from .credentials import CredentialRef, CredentialResolver, EnvironmentCredentialResolver
from .effect_common import (
    ConnectorConfigurationError,
    ConnectorResult,
    ConnectorStatus,
    _validate_base_url,
)


@dataclass(frozen=True, slots=True)
class AdministrativeCommunicationEffectConnection:
    """Transport-only connection for the governed internal message capability."""

    gateway_base_url: str
    transport_credential: CredentialRef
    artifact_root: Path
    timeout_seconds: float = 10.0
    allow_insecure_http: bool = False

    def __post_init__(self) -> None:
        _validate_base_url(self.gateway_base_url, allow_insecure_http=self.allow_insecure_http)
        if self.timeout_seconds <= 0:
            raise ConnectorConfigurationError("communication timeout must be positive")


class AdministrativeCommunicationEffectConnector:
    def __init__(
        self,
        connection: AdministrativeCommunicationEffectConnection,
        *,
        credentials: CredentialResolver | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.connection = connection
        self.credentials = credentials or EnvironmentCredentialResolver()
        self.client = client
        self.artifacts = FilesystemArtifactStore(connection.artifact_root)

    async def invoke(
        self,
        *,
        request_ref: str,
        subject_ref: str,
        parameters: dict[str, Any],
    ) -> ConnectorResult:
        event_id = str(parameters.get("communication_event_id") or request_ref).strip()
        recipient = str(parameters.get("recipient_ref") or subject_ref).strip()
        storage_ref = str(parameters.get("content_storage_ref") or "").strip()
        digest = str(parameters.get("content_digest") or "").strip()
        draft_kind = str(parameters.get("draft_kind") or "confirmation").strip()
        if not recipient or not storage_ref or len(digest) != 64:
            return ConnectorResult(
                ConnectorStatus.FAILED,
                error_code="CommunicationParametersIncomplete",
                error_message="communication transport parameters are incomplete",
            )
        try:
            text = self.artifacts.get(storage_ref, expected_digest=digest).decode("utf-8")
            body = json.dumps(
                {
                    "eventId": event_id,
                    "recipientRef": recipient,
                    "text": text,
                    "draftKind": draft_kind,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            timestamp = str(int(time.time()))
            body_digest = hashlib.sha256(body).hexdigest()
            secret = self.credentials.resolve(self.connection.transport_credential)
            signature = hmac.new(
                secret.encode("utf-8"),
                f"{timestamp}\n{event_id}\n{body_digest}".encode(),
                hashlib.sha256,
            ).hexdigest()
            request_headers = {
                "Content-Type": "application/json",
                "X-Event-ID": event_id,
                "X-Timestamp": timestamp,
                "X-Signature": signature,
            }
            if self.client is not None:
                response = await self.client.post(
                    f"{self.connection.gateway_base_url.rstrip('/')}/v1/administrative/communications",
                    content=body,
                    headers=request_headers,
                )
            else:
                async with httpx.AsyncClient(timeout=self.connection.timeout_seconds) as client:
                    response = await client.post(
                        f"{self.connection.gateway_base_url.rstrip('/')}/v1/administrative/communications",
                        content=body,
                        headers=request_headers,
                    )
            if response.status_code >= 500:
                return ConnectorResult(
                    ConnectorStatus.UNKNOWN,
                    error_code=f"GatewayHTTP{response.status_code}",
                    error_message="communication transport outcome is unknown",
                )
            if response.status_code >= 400:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code=f"GatewayHTTP{response.status_code}",
                    error_message="communication gateway rejected the transport request",
                )
            raw = response.json()
            if not isinstance(raw, dict):
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="InvalidCommunicationReceipt",
                    error_message="communication gateway receipt is not an object",
                )
            return ConnectorResult(
                ConnectorStatus.SUCCEEDED,
                external_operation_ref=(
                    str(raw["providerMessageRef"])
                    if raw.get("providerMessageRef")
                    else None
                ),
                observed_postcondition={
                    "target_system": "communication",
                    "operation": "message.send",
                    "subject_ref": subject_ref,
                    "communication_event_id": event_id,
                    "transport_accepted": bool(raw.get("transportAccepted")),
                    "delivery_confirmed": bool(raw.get("deliveryConfirmed")),
                    "read_state": "unknown",
                },
            )
        except (httpx.HTTPError, ValueError, UnicodeError) as exc:
            return ConnectorResult(
                ConnectorStatus.UNKNOWN,
                error_code=type(exc).__name__,
                error_message="communication transport outcome is unknown",
            )

    async def reconcile(self, request_ref: str) -> ConnectorResult | None:
        # A lost writer ACK is reconciled by the durable Gateway event id. The
        # Kernel request ref alone cannot be used to invent a new send.
        del request_ref
        return None


__all__ = ["AdministrativeCommunicationEffectConnection", "AdministrativeCommunicationEffectConnector"]
