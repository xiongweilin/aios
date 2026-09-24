from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from administrative_orchestrator.authority import AuthorityRepository, IdentityBinding
from administrative_orchestrator.domain import Principal
from administrative_orchestrator.intake.artifacts import FilesystemArtifactStore
from administrative_orchestrator.intake.documents import (
    DocumentAttachmentProcessor,
    DocumentEvidenceDraft,
    DocumentExtraction,
    DocumentFactDraft,
    DocumentProcessingStatus,
)
from administrative_orchestrator.intake.interpretation import (
    InterpretationClient,
    InterpretationProfile,
    ModelProvenance,
    ModelProviderUnavailable,
    StaticModelGateway,
)
from administrative_orchestrator.intake.models import IntakeVerificationStatus, InterpretationStatus
from administrative_orchestrator.intake.repository import IntakeReceiptConflict, IntakeRepository
from administrative_orchestrator.messaging import OutboxEventRow
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.providers.feishu import (
    FEISHU_SOURCE_SYSTEM,
    FeishuAcceptance,
    FeishuCanonicalAttachment,
    FeishuCanonicalMessage,
    FeishuEventVerifier,
    FeishuInboxPipeline,
    FeishuProviderEvent,
    FeishuTenantAccessTokenProvider,
    FeishuVerificationError,
    FeishuWebhookBoundary,
    HttpFeishuCanonicalFetcher,
)

EVENT_TIME = 1_893_456_000_000


def _event_body(
    *,
    event_id: str = "event-feishu-1",
    message_id: str = "om-message-1",
    token: str = "verification-token",
    tenant: str = "tenant-feishu",
) -> bytes:
    return json.dumps(
        {
            "schema": "2.0",
            "header": {
                "event_id": event_id,
                "event_type": "im.message.receive_v1",
                "tenant_key": tenant,
                "token": token,
                "create_time": str(EVENT_TIME),
            },
            "event": {
                "sender": {"sender_id": {"open_id": "ou_alice"}},
                "message": {
                    "message_id": message_id,
                    "root_id": message_id,
                    "create_time": str(EVENT_TIME),
                    "message_type": "text",
                },
            },
        },
        separators=(",", ":"),
    ).encode()


def _repository() -> tuple[SqlStore, IntakeRepository]:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    return store, IntakeRepository(store)


def _verifier(*, encrypt_key: str | None = None) -> FeishuEventVerifier:
    return FeishuEventVerifier(
        "verification-token",
        encrypt_key=encrypt_key,
        clock=lambda: EVENT_TIME / 1000,
    )


def _canonical(event: FeishuProviderEvent) -> FeishuCanonicalMessage:
    return FeishuCanonicalMessage(
        message_id=event.message_id,
        tenant_ref=event.tenant_ref,
        thread_ref=event.thread_ref,
        sender_external_subject=event.sender_external_subject,
        participant_external_subjects=(event.sender_external_subject,),
        occurred_at=event.occurred_at,
        sequence=event.sequence,
        content="Please onboard employee:1.",
    )


class _Fetcher:
    def __init__(self) -> None:
        self.calls = 0

    def fetch(self, event: FeishuProviderEvent) -> FeishuCanonicalMessage:
        self.calls += 1
        return _canonical(event)


def _pipeline(
    tmp_path: Path,
    store: SqlStore,
    repository: IntakeRepository,
    fetcher: _Fetcher,
    *,
    gateway: StaticModelGateway,
    document_processor: DocumentAttachmentProcessor | None = None,
) -> FeishuInboxPipeline:
    authority = AuthorityRepository(store)
    authority.put_principal(Principal(principal_id="person:alice", display_name="Alice"))
    authority.put_identity_binding(
        IdentityBinding(
            provider=FEISHU_SOURCE_SYSTEM,
            external_subject="ou_alice",
            principal_id="person:alice",
            valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        )
    )
    artifact_store = FilesystemArtifactStore(tmp_path / "artifacts")
    return FeishuInboxPipeline(
        store,
        repository=repository,
        artifact_store=artifact_store,
        canonical_fetcher=fetcher,
        interpretation_client=InterpretationClient(gateway, repository),
        interpretation_profile=InterpretationProfile(
            profile_ref="feishu-onboarding-v1",
            schema_ref="candidate-interpretation-v1",
            instruction="Extract a candidate intent and candidate facts only.",
        ),
        document_processor=document_processor,
    )


def test_feishu_ingress_verifies_token_and_deduplicates_without_processing() -> None:
    store, repository = _repository()
    fetcher = _Fetcher()
    boundary = FeishuWebhookBoundary(repository, _verifier())
    body = _event_body()

    first = boundary.accept(body, {})
    assert isinstance(first, FeishuAcceptance)
    assert first.created is True
    assert fetcher.calls == 0

    duplicate = boundary.accept(body, {})
    assert isinstance(duplicate, FeishuAcceptance)
    assert duplicate.created is False
    assert duplicate.receipt.receipt_id == first.receipt.receipt_id

    with store.sessions() as db:
        rows = db.query(OutboxEventRow).all()
        assert len(rows) == 1
        assert rows[0].event_id == first.outbox_event_id
        assert "content" not in rows[0].payload_json
        assert "body" not in rows[0].payload_json


def test_feishu_ingress_rejects_invalid_token_and_digest_replay() -> None:
    _, repository = _repository()
    boundary = FeishuWebhookBoundary(repository, _verifier())

    with pytest.raises(FeishuVerificationError):
        boundary.accept(_event_body(token="wrong-token"), {})

    boundary.accept(_event_body(), {})
    with pytest.raises(IntakeReceiptConflict):
        boundary.accept(_event_body(event_id="event-feishu-1", message_id="different"), {})


def test_long_connection_handoff_requires_gateway_secret_when_callback_token_is_absent() -> None:
    store, repository = _repository()
    verifier = FeishuEventVerifier(
        "verification-token",
        gateway_shared_secret="gateway-secret",
        clock=lambda: EVENT_TIME / 1000,
    )
    boundary = FeishuWebhookBoundary(repository, verifier)
    decoded = json.loads(_event_body())
    decoded["header"].pop("token")
    body = json.dumps(decoded, separators=(",", ":")).encode()

    with pytest.raises(FeishuVerificationError):
        boundary.accept(body, {})
    with pytest.raises(FeishuVerificationError):
        boundary.accept(body, {"X-Administrative-Ingress-Token": "wrong"})

    accepted = boundary.accept(body, {"X-Administrative-Ingress-Token": "gateway-secret"})
    assert isinstance(accepted, FeishuAcceptance)
    assert accepted.created is True


def test_long_connection_handoff_can_use_gateway_secret_without_callback_token() -> None:
    _, repository = _repository()
    verifier = FeishuEventVerifier(
        None,
        gateway_shared_secret="gateway-secret",
        clock=lambda: EVENT_TIME / 1000,
    )
    boundary = FeishuWebhookBoundary(repository, verifier)
    decoded = json.loads(_event_body())
    decoded["header"].pop("token")
    body = json.dumps(decoded, separators=(",", ":")).encode()

    accepted = boundary.accept(
        body,
        {"X-Administrative-Ingress-Token": "gateway-secret"},
    )

    assert isinstance(accepted, FeishuAcceptance)
    assert accepted.created is True


def test_long_connection_handoff_rejects_conflicting_provider_token() -> None:
    _, repository = _repository()
    verifier = FeishuEventVerifier(
        "verification-token",
        gateway_shared_secret="gateway-secret",
        clock=lambda: EVENT_TIME / 1000,
    )
    boundary = FeishuWebhookBoundary(repository, verifier)

    with pytest.raises(FeishuVerificationError):
        boundary.accept(
            _event_body(token="conflicting-token"),
            {"X-Administrative-Ingress-Token": "gateway-secret"},
        )


def test_long_connection_handoff_gateway_header_alone_is_insufficient() -> None:
    _, repository = _repository()
    verifier = FeishuEventVerifier(
        "verification-token",
        clock=lambda: EVENT_TIME / 1000,
    )
    boundary = FeishuWebhookBoundary(repository, verifier)
    decoded = json.loads(_event_body())
    decoded["header"].pop("token")
    body = json.dumps(decoded, separators=(",", ":")).encode()

    with pytest.raises(FeishuVerificationError):
        boundary.accept(body, {"X-Administrative-Ingress-Token": "gateway-secret"})


def test_feishu_callback_signature_and_challenge_are_verified() -> None:
    _, repository = _repository()
    verifier = _verifier(encrypt_key="encrypt-key")
    boundary = FeishuWebhookBoundary(repository, verifier)
    body = _event_body()
    timestamp = str(EVENT_TIME // 1000)
    nonce = "nonce-1"
    signature = hashlib.sha256(
        (timestamp + nonce + "encrypt-key").encode() + body
    ).hexdigest()
    headers = {
        "X-Lark-Request-Timestamp": timestamp,
        "X-Lark-Request-Nonce": nonce,
        "X-Lark-Signature": signature,
    }
    accepted = boundary.accept(body, headers)
    assert isinstance(accepted, FeishuAcceptance)

    challenge_body = json.dumps(
        {"type": "url_verification", "token": "verification-token", "challenge": "challenge-1"}
    ).encode()
    challenge_headers = {
        **headers,
        "X-Lark-Signature": hashlib.sha256(
            (timestamp + nonce + "encrypt-key").encode() + challenge_body
        ).hexdigest(),
    }
    challenge = boundary.accept(challenge_body, challenge_headers)
    assert challenge.challenge == "challenge-1"

    bad_headers = {**headers, "X-Lark-Signature": "0" * 64}
    with pytest.raises(FeishuVerificationError):
        boundary.accept(body, bad_headers)


def test_feishu_pipeline_completes_source_to_candidate_and_is_replay_safe(tmp_path: Path) -> None:
    store, repository = _repository()
    boundary = FeishuWebhookBoundary(repository, _verifier())
    body = _event_body()
    accepted = boundary.accept(body, {})
    assert isinstance(accepted, FeishuAcceptance)
    event = _verifier().verify(body, {})
    assert isinstance(event, FeishuProviderEvent)

    gateway_calls = 0

    def output(_request):
        nonlocal gateway_calls
        gateway_calls += 1
        return json.dumps(
            {
                "candidate_intent": "onboard employee:1",
                "candidate_facts": [],
                "draft_response": "Review is required before admission.",
            }
        )

    fetcher = _Fetcher()
    pipeline = _pipeline(
        tmp_path,
        store,
        repository,
        fetcher,
        gateway=StaticModelGateway(
            output,
            provenance=ModelProvenance(
                provider="test-model-gateway",
                model_identity="test-model",
                model_version="v1",
            ),
        ),
    )

    first = pipeline.process_event(event)
    assert first.interpretation.status is InterpretationStatus.SUCCEEDED
    assert first.candidate is not None
    assert first.conversation is not None
    assert first.identity.principal_id == "person:alice"
    assert first.receipt.verification_status is IntakeVerificationStatus.VERIFIED
    assert first.receipt.artifact_ref == first.artifact.artifact_id
    assert fetcher.calls == 1
    assert gateway_calls == 1

    replay = pipeline.process_event(event)
    assert replay.candidate is not None
    assert replay.candidate.candidate_id == first.candidate.candidate_id
    assert replay.conversation is not None
    assert replay.conversation.created is False
    assert fetcher.calls == 2
    assert gateway_calls == 1
    assert len(repository.list_candidates()) == 1
    assert len(pipeline.conversation_service.list_messages(first.conversation.message.conversation_ref)) == 1


def test_feishu_model_failure_retains_source_without_candidate(tmp_path: Path) -> None:
    store, repository = _repository()
    boundary = FeishuWebhookBoundary(repository, _verifier())
    body = _event_body(event_id="event-feishu-failure", message_id="om-message-failure")
    accepted = boundary.accept(body, {})
    assert isinstance(accepted, FeishuAcceptance)
    event = _verifier().verify(body, {})
    assert isinstance(event, FeishuProviderEvent)

    class FailingGateway(StaticModelGateway):
        def complete(self, request, *, timeout_seconds):
            raise ModelProviderUnavailable("provider unavailable")

    pipeline = _pipeline(
        tmp_path,
        store,
        repository,
        _Fetcher(),
        gateway=FailingGateway(
            "unused",
            provenance=ModelProvenance(
                provider="test-model-gateway",
                model_identity="test-model",
                model_version="v1",
            ),
        ),
    )
    result = pipeline.process_event(event)
    assert result.interpretation.status is InterpretationStatus.FAILED
    assert result.candidate is None
    assert repository.list_candidates() == []
    assert result.receipt.artifact_ref == result.artifact.artifact_id


def test_feishu_pipeline_retries_invalid_interpretation_append_only(tmp_path: Path) -> None:
    store, repository = _repository()
    boundary = FeishuWebhookBoundary(repository, _verifier())
    body = _event_body(event_id="event-feishu-retry", message_id="om-message-retry")
    accepted = boundary.accept(body, {})
    assert isinstance(accepted, FeishuAcceptance)
    event = _verifier().verify(body, {})
    assert isinstance(event, FeishuProviderEvent)

    outputs = iter(
        (
            "{}",
            json.dumps(
                {
                    "candidate_intent": "onboard employee:1",
                    "candidate_facts": [],
                }
            ),
        )
    )
    pipeline = _pipeline(
        tmp_path,
        store,
        repository,
        _Fetcher(),
        gateway=StaticModelGateway(
            lambda _request: next(outputs),
            provenance=ModelProvenance(
                provider="test-model-gateway",
                model_identity="test-model",
                model_version="v1",
            ),
        ),
    )

    first = pipeline.process_event(event)
    assert first.interpretation.status is InterpretationStatus.INVALID
    assert first.candidate is None

    second = pipeline.process_event(event)
    assert second.interpretation.status is InterpretationStatus.SUCCEEDED
    assert second.candidate is not None
    assert len(repository.list_interpretations(second.artifact.artifact_id)) == 2


def test_feishu_pipeline_persists_attachment_evidence_and_candidate_fact(tmp_path: Path) -> None:
    store, repository = _repository()
    boundary = FeishuWebhookBoundary(repository, _verifier())
    body = _event_body(event_id="event-feishu-attachment", message_id="om-message-attachment")
    accepted = boundary.accept(body, {})
    assert isinstance(accepted, FeishuAcceptance)
    event = _verifier().verify(body, {})
    assert isinstance(event, FeishuProviderEvent)

    class AttachmentFetcher(_Fetcher):
        def fetch(self, event: FeishuProviderEvent) -> FeishuCanonicalMessage:
            self.calls += 1
            message = _canonical(event)
            return message.model_copy(
                update={
                    "attachments": (
                        FeishuCanonicalAttachment(
                            attachment_ref="file-key-1",
                            filename="employee.txt",
                            mime_type="text/plain",
                            content=b"employee_id=employee:1",
                        ),
                    )
                }
            )

    class AttachmentParser:
        def parse(self, attachment, content) -> DocumentExtraction:
            del attachment
            text = content.decode("utf-8")
            return DocumentExtraction(
                representation=text,
                extractor_ref="test-attachment-parser-v1",
                evidence=(
                    DocumentEvidenceDraft(text=text, char_start=0, char_end=len(text)),
                ),
                facts=(
                    DocumentFactDraft(
                        fact_key="employee_id",
                        value="employee:1",
                        evidence_indexes=(0,),
                    ),
                ),
            )

    artifact_store = FilesystemArtifactStore(tmp_path / "artifacts")
    fetcher = AttachmentFetcher()
    pipeline = _pipeline(
        tmp_path,
        store,
        repository,
        fetcher,
        gateway=StaticModelGateway(
            json.dumps(
                {
                    "candidate_intent": "onboard employee:1",
                    "candidate_facts": [],
                    "draft_response": "Review is required before admission.",
                }
            ),
            provenance=ModelProvenance(
                provider="test-model-gateway",
                model_identity="test-model",
                model_version="v1",
            ),
        ),
        document_processor=DocumentAttachmentProcessor(
            artifact_store,
            AttachmentParser(),
            repository,
        ),
    )

    result = pipeline.process_event(event)

    assert result.candidate is not None
    assert result.conversation is not None
    assert len(result.document_attachments) == 1
    document = result.document_attachments[0]
    assert document.status is DocumentProcessingStatus.SUCCEEDED
    assert document.artifact.source_kind == "message_attachment"
    assert len(document.evidence_spans) == 1
    assert len(document.facts) == 1
    assert document.facts[0].fact_key == "employee_id"
    assert result.candidate.candidate_fact_refs == (document.facts[0].candidate_fact_id,)
    assert result.candidate.source_refs == (
        result.artifact.artifact_id,
        document.artifact.artifact_id,
    )
    assert result.conversation.message.source_refs == result.candidate.source_refs


def test_http_feishu_fetcher_reads_file_attachment_resource() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/resources/file-key-1"):
            return httpx.Response(
                200,
                content=b"employee_id=employee:1",
                headers={"content-type": "text/plain; charset=utf-8"},
            )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "items": [
                        {
                            "message_id": "om-message-1",
                            "root_id": "om-message-1",
                            "create_time": str(EVENT_TIME),
                            "tenant_key": "tenant-feishu",
                            "sender_id": {"open_id": "ou_alice"},
                            "msg_type": "file",
                            "body": {
                                "content": json.dumps(
                                    {"file_key": "file-key-1", "file_name": "employee.txt"}
                                )
                            },
                        }
                    ]
                },
            },
        )

    event = FeishuProviderEvent(
        event_id="event-feishu-1",
        tenant_ref="tenant-feishu",
        message_id="om-message-1",
        thread_ref="om-message-1",
        sender_external_subject="ou_alice",
        occurred_at=datetime.fromtimestamp(EVENT_TIME / 1000, tz=UTC),
        sequence=EVENT_TIME,
        delivery_digest="a" * 64,
    )
    fetcher = HttpFeishuCanonicalFetcher(
        "https://open.feishu.invalid",
        lambda: "test-access-token",
        transport=httpx.MockTransport(handler),
    )
    try:
        message = fetcher.fetch(event)
    finally:
        fetcher.close()

    assert message.content == "[Feishu attachment: employee.txt]"
    assert len(message.attachments) == 1
    assert message.attachments[0].content == b"employee_id=employee:1"
    assert message.attachments[0].mime_type == "text/plain"
    assert requests[1].url.params["type"] == "file"


def test_http_feishu_fetcher_reads_canonical_text_without_leaking_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "items": [
                        {
                            "message_id": "om-message-1",
                            "root_id": "om-message-1",
                            "create_time": str(EVENT_TIME),
                            "tenant_key": "tenant-feishu",
                            "sender_id": {"open_id": "ou_alice"},
                            "msg_type": "text",
                            "body": {"content": json.dumps({"text": "canonical text"})},
                        }
                    ]
                },
            },
        )

    event = FeishuProviderEvent(
        event_id="event-feishu-1",
        tenant_ref="tenant-feishu",
        message_id="om-message-1",
        thread_ref="om-message-1",
        sender_external_subject="ou_alice",
        occurred_at=datetime.fromtimestamp(EVENT_TIME / 1000, tz=UTC),
        sequence=EVENT_TIME,
        delivery_digest="a" * 64,
    )
    fetcher = HttpFeishuCanonicalFetcher(
        "https://open.feishu.invalid",
        lambda: "test-access-token",
        transport=httpx.MockTransport(handler),
    )
    try:
        message = fetcher.fetch(event)
    finally:
        fetcher.close()
    assert message.content == "canonical text"
    assert requests[0].headers["Authorization"] == "Bearer test-access-token"


def test_http_feishu_fetcher_reads_official_sender_id_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "items": [
                        {
                            "message_id": "om-message-1",
                            "create_time": str(EVENT_TIME),
                            "tenant_key": "tenant-feishu",
                            "sender": {
                                "id": "ou_alice",
                                "id_type": "open_id",
                                "sender_type": "user",
                                "tenant_key": "tenant-feishu",
                            },
                            "msg_type": "text",
                            "body": {"content": json.dumps({"text": "canonical text"})},
                        }
                    ]
                },
            },
        )

    event = FeishuProviderEvent(
        event_id="event-feishu-1",
        tenant_ref="tenant-feishu",
        message_id="om-message-1",
        thread_ref="om-message-1",
        sender_external_subject="ou_alice",
        occurred_at=datetime.fromtimestamp(EVENT_TIME / 1000, tz=UTC),
        sequence=EVENT_TIME,
        delivery_digest="a" * 64,
    )
    fetcher = HttpFeishuCanonicalFetcher(
        "https://open.feishu.invalid",
        lambda: "test-access-token",
        transport=httpx.MockTransport(handler),
    )
    try:
        message = fetcher.fetch(event)
    finally:
        fetcher.close()

    assert message.sender_external_subject == "ou_alice"
    assert message.thread_ref == "om-message-1"
    assert message.content == "canonical text"


def test_feishu_tenant_token_provider_caches_and_refreshes_near_expiry() -> None:
    requests: list[httpx.Request] = []
    now = [1_000.0]
    issued = iter(("tenant-token-1", "tenant-token-2"))

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "tenant_access_token": next(issued),
                "expire": 100,
            },
        )

    provider = FeishuTenantAccessTokenProvider(
        "https://open.feishu.invalid",
        "app-id",
        "app-secret",
        transport=httpx.MockTransport(handler),
        clock=lambda: now[0],
    )
    try:
        assert provider() == "tenant-token-1"
        assert provider() == "tenant-token-1"
        now[0] = 1_091.0
        assert provider() == "tenant-token-2"
    finally:
        provider.close()

    assert len(requests) == 2
    assert requests[0].url.path.endswith("/tenant_access_token/internal")


def test_http_feishu_fetcher_invalidates_and_retries_dynamic_token_after_401() -> None:
    requests: list[httpx.Request] = []
    issued = iter(("tenant-token-1", "tenant-token-2"))

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "tenant_access_token": next(issued),
                    "expire": 3_600,
                },
            )
        if request.headers["Authorization"] == "Bearer tenant-token-1":
            return httpx.Response(401)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "items": [
                        {
                            "message_id": "om-message-1",
                            "root_id": "om-message-1",
                            "create_time": str(EVENT_TIME),
                            "tenant_key": "tenant-feishu",
                            "sender_id": {"open_id": "ou_alice"},
                            "msg_type": "text",
                            "body": {"content": json.dumps({"text": "canonical text"})},
                        }
                    ]
                },
            },
        )

    event = FeishuProviderEvent(
        event_id="event-feishu-1",
        tenant_ref="tenant-feishu",
        message_id="om-message-1",
        thread_ref="om-message-1",
        sender_external_subject="ou_alice",
        occurred_at=datetime.fromtimestamp(EVENT_TIME / 1000, tz=UTC),
        sequence=EVENT_TIME,
        delivery_digest="a" * 64,
    )
    provider = FeishuTenantAccessTokenProvider(
        "https://open.feishu.invalid",
        "app-id",
        "app-secret",
        transport=httpx.MockTransport(handler),
    )
    fetcher = HttpFeishuCanonicalFetcher(
        "https://open.feishu.invalid",
        provider,
        transport=httpx.MockTransport(handler),
    )
    try:
        message = fetcher.fetch(event)
    finally:
        fetcher.close()
        provider.close()

    assert message.content == "canonical text"
    assert [request.headers.get("Authorization") for request in requests if request.url.path.endswith("/messages/om-message-1")] == [
        "Bearer tenant-token-1",
        "Bearer tenant-token-2",
    ]
