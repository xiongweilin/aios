from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..persistence import Base

class SourceArtifactRow(Base):
    __tablename__ = "administrative_source_artifact"
    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "tenant_ref",
            "canonical_source_ref",
            "source_revision",
            name="uq_source_artifact_revision",
        ),
    )

    artifact_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    source_system: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    canonical_source_ref: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_revision: Mapped[str] = mapped_column(String(256), nullable=False)
    source_event_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    actor_external_identity_ref: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    content_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_ref: Mapped[str] = mapped_column(String(2000), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    authenticity_class: Mapped[str] = mapped_column(String(128), nullable=False)
    retention_class: Mapped[str] = mapped_column(String(128), nullable=False)

class IntakeReceiptRow(Base):
    __tablename__ = "administrative_intake_receipt"
    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "tenant_ref",
            "source_event_id",
            name="uq_intake_receipt_delivery",
        ),
    )

    receipt_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_system: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(512), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False)
    artifact_ref: Mapped[UUID | None] = mapped_column(
        ForeignKey("administrative_source_artifact.artifact_id"), nullable=True
    )
    delivery_digest: Mapped[str] = mapped_column(String(128), nullable=False)

class EvidenceSpanRow(Base):
    __tablename__ = "administ