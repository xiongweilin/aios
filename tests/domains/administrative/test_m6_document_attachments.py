from __future__ import annotations

from pathlib import Path

from administrative_orchestrator.intake.artifacts import FilesystemArtifactStore
from administrative_orchestrator.intake.documents import (
    DocumentAttachmentProcessor,
    DocumentErrorCode,
    DocumentEvidenceDraft,
    DocumentExtraction,
    DocumentFactDraft,
    DocumentParseError,
    DocumentProcessingStatus,
    MessageAttachment,
    PlainTextDocumentParser,
)
from administrative_orchestrator.intake.repository import IntakeRepository
from administrative_orchestrator.persistence import SqlStore


def _attachment(content: bytes = b"Employee Alice starts on 2026-09-15.") -> MessageAttachment:
    return MessageAttachment(
        attachment_id="file-1",
        message_ref="message-1",
        source_system="test-provider",
        tenant_ref="tenant:test",
        source_event_ref="event-1",
        filename="onboarding.txt",
        mime_type="text/plain",
        content=content,
    )


def test_attachment_is_stored_before_parser_and_fact_lineage_is_exact(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    sql_store = SqlStore("sqlite+pysqlite:///:memory:")
    sql_store.init_schema()
    repository = IntakeRepository(sql_store)

    class Parser:
        def parse(self, attachment, content):
            assert content == attachment.content
            text = content.decode("utf-8")
            start = text.index("2026-09-15")
            return DocumentExtraction(
                representation=text,
                extractor_ref="test-ocr-v1",
                evidence=(
                    DocumentEvidenceDraft(
                        text="2026-09-15",
                        char_start=start,
                        char_end=start + len("2026-09-15"),
                        locator={"page": 1, "block": 3},
                    ),
                ),
                facts=(
                    DocumentFactDraft(
                        fact_key="start_date",
                        value="2026-09-15",
                        evidence_indexes=(0,),
                    ),
                ),
            )

    result = DocumentAttachmentProcessor(store, Parser(), repository).process(_attachment())

    assert result.status is DocumentProcessingStatus.SUCCEEDED
    assert store.get(result.artifact.storage_ref, result.artifact.content_digest) == _attachment().content
    assert result.artifact.source_kind == "message_attachment"
    assert len(result.evidence_spans) == 1
    span = result.evidence_spans[0]
    assert span.artifact_ref == result.artifact.artifact_id
    assert span.locator["char_start"] == 25
    assert span.locator["char_end"] == 35
    assert span.locator["page"] == 1
    assert result.facts[0].source_refs == (result.artifact.artifact_id,)
    assert result.facts[0].evidence_span_refs == (span.evidence_span_id,)
    assert repository.get_candidate_fact(result.facts[0].candidate_fact_id) == result.facts[0]


def test_parser_failure_retains_raw_artifact_and_emits_no_facts(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")

    class FailingParser:
        def parse(self, attachment, content):
            assert content == attachment.content
            raise DocumentParseError(
                "parser dependency is unavailable",
                code=DocumentErrorCode.PARSER_UNAVAILABLE,
            )

    result = DocumentAttachmentProcessor(store, FailingParser()).process(_attachment(b"binary"))

    assert result.status is DocumentProcessingStatus.FAILED
    assert result.error_code == DocumentErrorCode.PARSER_UNAVAILABLE.value
    assert result.evidence_spans == ()
    assert result.facts == ()
    assert store.get(result.artifact.storage_ref, result.artifact.content_digest) == b"binary"


def test_unbound_parser_fact_fails_closed_without_fabricating_lineage(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")

    class InvalidParser:
        def parse(self, attachment, content):
            return DocumentExtraction(
                representation=content.decode("utf-8"),
                extractor_ref="invalid-parser-v1",
                evidence=(),
                facts=(
                    DocumentFactDraft(
                        fact_key="employee_ref",
                        value="person:alice",
                        evidence_indexes=(0,),
                    ),
                ),
            )

    result = DocumentAttachmentProcessor(store, InvalidParser()).process(_attachment())

    assert result.status is DocumentProcessingStatus.FAILED
    assert result.error_code == DocumentErrorCode.LINEAGE_INVALID.value
    assert result.evidence_spans == ()
    assert result.facts == ()
    assert store.get(result.artifact.storage_ref) == _attachment().content


def test_plain_text_parser_produces_a_single_exact_evidence_span(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    attachment = _attachment(b"plain text")

    result = DocumentAttachmentProcessor(store, PlainTextDocumentParser()).process(attachment)

    assert result.status is DocumentProcessingStatus.SUCCEEDED
    assert result.facts == ()
    assert result.evidence_spans[0].locator["char_start"] == 0
    assert result.evidence_spans[0].locator["char_end"] == len("plain text")
    assert result.evidence_spans[0].extractor_ref == "plain-text-parser-v1"
