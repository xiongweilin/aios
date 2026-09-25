from __future__ import annotations

from pathlib import Path

from administrative_orchestrator.intake.artifacts import FilesystemArtifactStore
from administrative_orchestrator.intake.document_repository import DocumentRepository
from administrative_orchestrator.intake.documents import (
    ContentAwareDocumentParser,
    DocumentAttachmentProcessor,
    MessageAttachment,
    PdfTextDocumentParser,
    PlainTextDocumentParser,
)
from administrative_orchestrator.intake.repository import IntakeRepository
from administrative_orchestrator.persistence import SqlStore


def _attachment(*, content: bytes, mime_type: str, filename: str) -> MessageAttachment:
    return MessageAttachment(
        attachment_ref="document-1",
        message_ref="message-1",
        source_system="test-provider",
        tenant_ref="tenant:test",
        source_event_ref="event-1",
        filename=filename,
        mime_type=mime_type,
        content=content,
    )


def _minimal_text_pdf(text: str) -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (
            f"<< /Length {len(text) + 34} >>\nstream\n"
            f"BT\n/F1 12 Tf\n72 720 Td\n({text}) Tj\nET\n"
            "endstream"
        ).encode("latin-1"),
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


def test_representation_is_durable_and_spans_reference_exact_object(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    sql_store = SqlStore("sqlite+pysqlite:///:memory:")
    sql_store.init_schema()
    intake = IntakeRepository(sql_store)
    documents = DocumentRepository(sql_store)
    result = DocumentAttachmentProcessor(
        store,
        PlainTextDocumentParser(),
        intake,
        documents,
    ).process(
        _attachment(content=b"invoice 100.00 USD", mime_type="text/plain", filename="invoice.txt")
    )

    assert result.representation is not None
    representation = documents.get(result.representation.representation_id)
    assert representation == result.representation
    assert store.get(representation.storage_ref, representation.content_digest) == b"invoice 100.00 USD"
    assert result.evidence_spans[0].representation_ref == representation.representation_id


def test_pdf_text_parser_produces_page_local_exact_lineage(tmp_path: Path) -> None:
    content = _minimal_text_pdf("Invoice 100.00 USD")
    result = DocumentAttachmentProcessor(
        FilesystemArtifactStore(tmp_path / "artifacts"),
        PdfTextDocumentParser(),
    ).process(_attachment(content=content, mime_type="application/pdf", filename="invoice.pdf"))

    assert result.status.value == "succeeded"
    assert result.representation is not None
    assert result.representation.representation_kind == "pdf-text"
    assert result.representation.page_count == 1
    assert result.evidence_spans[0].locator["page"] == 1
    assert result.evidence_spans[0].locator["text_sha256"]


def test_content_aware_parser_selects_pdf_and_plain_text_boundaries(tmp_path: Path) -> None:
    parser = ContentAwareDocumentParser()
    pdf = parser.parse(
        _attachment(content=_minimal_text_pdf("Invoice 100.00 USD"), mime_type="application/pdf", filename="invoice.pdf"),
        _minimal_text_pdf("Invoice 100.00 USD"),
    )
    text = parser.parse(
        _attachment(content=b"plain text", mime_type="text/plain", filename="note.txt"),
        b"plain text",
    )

    assert pdf.representation_kind == "pdf-text"
    assert text.representation == "plain text"
