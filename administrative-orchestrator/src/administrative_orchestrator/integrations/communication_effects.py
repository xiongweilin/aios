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
        recipient = str(parameters.get("recipient_open_id") or subject_ref).strip()
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
                    "recipientOpenId": recipient,
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


class FeishuCommunicationVerifier:
    """Independent Feishu readback; it never asserts that a human read a message."""

    def __init__(
        self,
        *,
        base_url: str,
        app_id: str,
        app_secret: CredentialRef,
        gateway_base_url: str = "",
        gateway_secret: CredentialRef | None = None,
        timeout_seconds: float = 10.0,
        credentials: CredentialResolver | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        _validate_base_url(base_url, allow_insecure_http=False)
        self.base_url = base_url.rstrip("/")
        self.app_id = app_id
        self.app_secret = app_secret
        self.gateway_base_url = gateway_base_url.rstrip("/")
        self.gateway_secret = gateway_secret
        self.timeout_seconds = timeout_seconds
        self.credentials = credentials or EnvironmentCredentialResolver()
        self.client = client

    async def observe(
        self,
        *,
        subject_ref: str,
        expected_postcondition: dict[str, Any],
    ) -> ConnectorResult:
        message_id = str(expected_postcondition.get("provider_message_ref") or "").strip()
        request_client = self.client
        owns_client = request_client is None
        ledger: dict[str, Any] | None = None
        try:
            if owns_client:
                request_client = httpx.AsyncClient(timeout=self.timeout_seconds)
            assert request_client is not None
            if not message_id and self.gateway_base_url and self.gateway_secret is not None:
                event_id = str(expected_postcondition.get("communication_event_id") or "").strip()
                if event_id:
                    gateway_secret = self.credentials.resolve(self.gateway_secret)
                    timestamp = str(int(time.time()))
                    signature = hmac.new(
                        gateway_secret.encode("utf-8"),
                        f"{timestamp}\n{event_id}\n{hashlib.sha256(b'').hexdigest()}".encode(),
                        hashlib.sha256,
                    ).hexdigest()
                    ledger_response = await request_client.get(
                        f"{self.gateway_base_url}/v1/administrative/communications/{event_id}",
                        headers={
                            "X-Event-ID": event_id,
                            "X-Timestamp": timestamp,
                            "X-Signature": signature,
                        },
                    )
                    if ledger_response.status_code < 400:
                        raw_ledger = ledger_response.json()
                        ledger = raw_ledger if isinstance(raw_ledger, dict) else None
                        if isinstance(ledger, dict):
                            message_id = str(ledger.get("providerMessageRef") or "").strip()
            if not message_id:
                return ConnectorResult(
                    ConnectorStatus.UNAVAILABLE,
                    error_code="ProviderMessageRefUnavailable",
                    error_message="Feishu message reference is unavailable",
                )
            expected_recipient = str(
                expected_postcondition.get("recipient_external_subject") or ""
            ).strip()
            expected_content_digest = str(
                expected_postcondition.get("content_digest") or ""
            ).strip()
            if not expected_recipient or len(expected_content_digest) != 64:
                return ConnectorResult(
                    ConnectorStatus.UNAVAILABLE,
                    error_code="ReadbackExpectationIncomplete",
                    error_message="Feishu readback expectation is incomplete",
                )
            secret = self.credentials.resolve(self.app_secret)
            token_response = await request_client.post(
                f"{self.base_url}/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": secret},
            )
            token_response.raise_for_status()
            token_raw = token_response.json()
            token = token_raw.get("tenant_access_token") if isinstance(token_raw, dict) else None
            if not isinstance(token, str) or not token:
                return ConnectorResult(
                    ConnectorStatus.UNAVAILABLE,
                    error_code="FeishuVerifierAuthenticationFailed",
                    error_message="Feishu verifier authentication failed",
                )
            response = await request_client.get(
                f"{self.base_url}/open-apis/im/v1/messages/{message_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            raw = response.json()
            if not isinstance(raw, dict) or raw.get("code") not in (0, None):
                return ConnectorResult(
                    ConnectorStatus.UNAVAILABLE,
                    error_code="FeishuMessageReadbackRejected",
                    error_message="Feishu message readback was rejected",
                )
            data = raw.get("data")
            if not isinstance(data, dict):
                return ConnectorResult(
                    ConnectorStatus.UNAVAILABLE,
                    error_code="FeishuMessageReadbackMalformed",
                    error_message="Feishu message readback did not contain message data",
                )
            items = data.get("items")
            if isinstance(items, list):
                if len(items) != 1 or not isinstance(items[0], dict):
                    return ConnectorResult(
                        ConnectorStatus.UNAVAILABLE,
                        error_code="FeishuMessageReadbackMalformed",
                        error_message="Feishu message readback did not contain one message",
                    )
                data = items[0]
            body = data.get("body")
            content = body.get("content") if isinstance(body, dict) else None
            message_text: str | None = None
            if isinstance(content, str):
                try:
                    content_object = json.loads(content)
                except json.JSONDecodeError:
                    content_object = None
                if isinstance(content_object, dict) and isinstance(content_object.get("text"), str):
                    message_text = content_object["text"]
                elif content:
                    message_text = content
            if message_text is None:
                return ConnectorResult(
                    ConnectorStatus.UNAVAILABLE,
                    error_code="FeishuMessageContentUnavailable",
                    error_message="Feishu message content was unavailable for verification",
                )
            if hashlib.sha256(message_text.encode("utf-8")).hexdigest() != expected_content_digest:
                return ConnectorResult(
                    ConnectorStatus.UNAVAILABLE,
                    error_code="FeishuMessageContentDigestMismatch",
                    error_message="Feishu message content digest did not match the frozen draft",
                )
            if not self.gateway_base_url or self.gateway_secret is None:
                return ConnectorResult(
                    ConnectorStatus.UNAVAILABLE,
                    error_code="RecipientReadbackUnavailable",
                    error_message="Feishu recipient verification requires the Gateway ledger",
                )
            event_id = str(expected_postcondition.get("communication_event_id") or "").strip()
            if not event_id:
                return ConnectorResult(
                    ConnectorStatus.UNAVAILABLE,
                    error_code="CommunicationEventUnavailable",
                    error_message="Feishu recipient verification lacks a communication event",
                )
            gateway_secret = self.credentials.resolve(self.gateway_secret)
            timestamp = str(int(time.time()))
            signature = hmac.new(
                gateway_secret.encode("utf-8"),
                f"{timestamp}\n{event_id}\n{hashlib.sha256(b'').hexdigest()}".encode(),
                hashlib.sha256,
            ).hexdigest()
            if ledger is None:
                ledger_response = await request_client.get(
                    f"{self.gateway_base_url}/v1/administrative/communications/{event_id}",
                    headers={
                        "X-Event-ID": event_id,
                        "X-Timestamp": timestamp,
                        "X-Signature": signature,
                    },
                )
                ledger_response.raise_for_status()
                raw_ledger = ledger_response.json()
                ledger = raw_ledger if isinstance(raw_ledger, dict) else None
            recipient_digest = ledger.get("recipientDigest") if ledger is not None else None
            if recipient_digest != hashlib.sha256(expected_recipient.encode("utf-8")).hexdigest():
                return ConnectorResult(
                    ConnectorStatus.UNAVAILABLE,
                    error_code="FeishuRecipientDigestMismatch",
                    error_message="Feishu recipient did not match the governed recipient binding",
                )
            ledger_message_id = ledger.get("providerMessageRef") if ledger is not None else None
            if ledger_message_id and ledger_message_id != message_id:
                return ConnectorResult(
                    ConnectorStatus.UNAVAILABLE,
                    error_code="FeishuMessageReferenceMismatch",
                    error_message="Gateway and Feishu message references did not match",
                )
            observed_postcondition = dict(expected_postcondition)
            observed_postcondition["provider_message_ref"] = message_id
            return ConnectorResult(
                ConnectorStatus.SUCCEEDED,
                external_operation_ref=message_id,
                observed_postcondition=observed_postcondition,
                reconciled=True,
            )
        except (httpx.HTTPError, ValueError) as exc:
            return ConnectorResult(
                ConnectorStatus.UNAVAILABLE,
                error_code=type(exc).__name__,
                error_message="Feishu message readback unavailable",
            )
        finally:
            if owns_client and request_client is not None:
                await request_client.aclose()


__all__ = [
    "AdministrativeCommunicationEffectConnection",
    "AdministrativeCommunicationEffectConnector",
    "FeishuCommunicationVerifier",
]
