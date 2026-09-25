from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Uuid, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from ..persistence import Base, SqlStore
from .models import DocumentRepresentation


class DocumentRepresentationConflict(RuntimeError):
    """One representation identity was reused with different semantics."""


class DocumentRepresentationRow(Base):
    __tablename__ = "administrative_document_representation"

    representation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_artifact_ref: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_source_artifact.artifact_id"), nullable=False
    )
    representation_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    extractor_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(256), nullable=False)
    content_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_ref: Mapped[str] = mapped_column(String(2000), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False)


def _from_row(row: DocumentRepresentationRow) -> DocumentRepresentation:
    return DocumentRepresentation.model_validate(
        {
            "representation_id": row.representation_id,
            "source_artifact_ref": row.source_artifact_ref,
            "representation_kind": row.representation_kind,
            "extractor_ref": row.extractor_ref,
            "extractor_version": row.extractor_version,
            "content_digest": row.content_digest,
            "storage_ref": row.storage_ref,
            "size": row.size,
            "created_at": row.created_at,
            "page_count": row.page_count,
            "metadata": row.metadata_json,
        }
    )


class DocumentRepository:
    """Durable document representation records without parser/business logic."""

    def __init__(self, store: SqlStore) -> None:
        self.store = store

    def append_representation(
        self, representation: DocumentRepresentation
    ) -> DocumentRepresentation:
        with self.store.sessions.begin() as db:
            existing = db.get(DocumentRepresentationRow, representation.representation_id)
            if existing is not None:
                restored = _from_row(existing)
                if restored != representation:
                    raise DocumentRepresentationConflict(
                        "representation identity was reused with different semantics"
                    )
                return restored
            existing_semantic = (
                db.execute(
                    select(DocumentRepresentationRow).where(
                        DocumentRepresentationRow.source_artifact_ref
                        == representation.source_artifact_ref,
                        DocumentRepresentationRow.content_digest
                        == representation.content_digest,
                        DocumentRepresentationRow.extractor_ref == representation.extractor_ref,
                        DocumentRepresentationRow.extractor_version
                        == representation.extractor_version,
                    )
                )
                .scalars()
                .first()
            )
            if existing_semantic is not None:
                restored = _from_row(existing_semantic)
                if restored != representation:
                    raise DocumentRepresentationConflict(
                        "representation semantics already exist with different identity"
                    )
                return restored
            db.add(
                DocumentRepresentationRow(
                    representation_id=representation.representation_id,
                    source_artifact_ref=representation.source_artifact_ref,
                    representation_kind=representation.representation_kind,
                    extractor_ref=representation.extractor_ref,
                    extractor_version=representation.extractor_version,
                    content_digest=representation.content_digest,
                    storage_ref=representation.storage_ref,
                    size=representation.size,
                    created_at=representation.created_at,
                    page_count=representation.page_count,
                    metadata_json=dict(representation.metadata),
                )
            )
            try:
                db.flush()
            except IntegrityError as exc:
                raise DocumentRepresentationConflict(
                    "representation was concurrently inserted"
                ) from exc
            return representation

    def get(self, representation_id: UUID) -> DocumentRepresentation | None:
        with self.store.sessions() as db:
            row = db.get(DocumentRepresentationRow, representation_id)
            return None if row is None else _from_row(row)

    def list_for_artifact(self, artifact_id: UUID) -> list[DocumentRepresentation]:
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(DocumentRepresentationRow)
                    .where(DocumentRepresentationRow.source_artifact_ref == artifact_id)
                    .order_by(DocumentRepresentationRow.created_at, DocumentRepresentationRow.representation_id)
                )
                .scalars()
                .all()
            )
            return [_from_row(row) for row in rows]


__all__ = [
    "DocumentRepository",
    "DocumentRepresentationConflict",
    "DocumentRepresentationRow",
]
