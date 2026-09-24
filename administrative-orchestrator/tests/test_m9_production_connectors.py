from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from administrative_orchestrator.integrations.credentials import CredentialRef
from administrative_orchestrator.integrations.production_effects import (
    ConnectorStatus,
    FeishuCommunicationVerifier,
)


class _Resolver:
    def resolve(self, ref: CredentialRef) -> str:
        assert ref.configuration_ref
        return "test-secret"


@pytest.mark.asyncio
async def test_feishu_communication_readback_verifies_content_and_recipient() -> None:
    message_text = "已确认：完成 M9 follow-up。"
    recipient = "ou_committer"
    expected = {
        "communication_event_id": "event-m9-readback",
        "recipient_external_subject": recipient,
        "content_digest": hashlib.sha256(message_text.encode("utf-8")).hexdigest(),
        "transport_accepted": True,
        "delivery_confirmed": True,
        "read_state": "unknown",
    }
    recipient_digest = hashlib.sha256(recipient.encode("utf-8")).hexdigest()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/administrative/communications/event-m9-readback"):
            return httpx.Response(
                200,
                json={
                    "eventId": "event-m9-readback",
                    "status": "transport_accepted",
                    "transportAccepted": True,
                    "deliveryConfirmed": False,
                    "attempts": 1,
                    "bodyDigest": "b" * 64,
                    "recipientDigest": recipient_digest,
                    "providerMessageRef": "om_readback",
                    "lastErrorCode": "",
                    "createdAt": 1,
                    "updatedAt": 2,
                },
                request=request,
            )
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200,
                json={"code": 0, "tenant_access_token": "tenant-token"},
                request=request,
            )
        if request.url.path.endswith("/open-apis/im/v1/messages/om_readback"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "items": [
                            {
                                "message_id": "om_readback",
                                "msg_type": "text",
                                "body": {"content": json.dumps({"text": message_text})},
                            }
                        ],
                    },
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    verifier = FeishuCommunicationVerifier(
        base_url="https://open.feishu.example.test",
        app_id="cli_m9",
        app_secret=CredentialRef("feishu:verifier", "M9_FEISHU_SECRET"),
        gateway_base_url="https://gateway.example.test",
        gateway_secret=CredentialRef("gateway:verifier", "M9_GATEWAY_SECRET"),
        credentials=_Resolver(),
        client=client,
    )
    try:
        result = await verifier.observe(
            subject_ref="commitment:event-m9-readback",
            expected_postcondition=expected,
        )
    finally:
        await client.aclose()

    assert result.status is ConnectorStatus.SUCCEEDED
    assert result.external_operation_ref == "om_readback"
    assert result.observed_postcondition is not None
    assert result.observed_postcondition["provider_message_ref"] == "om_readback"
