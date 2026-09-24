from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SourceRow(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_class: Mapped[str] = mapped_column(String(40), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(500))
    actor_ref: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ObservationRow(Base):
    __tablename__ = "observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    semantic_namespace: Mapped[str] = mapped_column(String(120), nullable=False)
    semantic_kind: Mapped[str] = mapped_column(String(120), nullable=False)
    semantic_id: Mapped[str] = mapped_column(String(500), nullable=False)
    semantic_version: Mapped[str] = mapped_column(String(40), nullable=False)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    temporal_json: Mapped[str] = mapped_column(Text, nullable=False)
    sensitivity: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClaimRow(Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    semantic_namespace: Mapped[str] = mapped_column(String(120), nullable=False)
    semantic_kind: Mapped[str] = mapped_column(String(120), nullable=False)
    semantic_id: Mapped[str] = mapped_column(String(500), nullable=False)
    semantic_version: Mapped[str] = mapped_column(String(40), nullable=False)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    observation_refs_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    temporal_json: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[str | None] = mapped_column(String(32))
    sensitivity: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecordRow(Base):
    __tablename__ = "records"
    __table_args__ = (
        UniqueConstraint("lineage_id", "revision", name="uq_record_lineage_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    lineage_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    subject_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    semantic_namespace: Mapped[str] = mapped_column(String(120), nullable=False)
    semantic_kind: Mapped[str] = mapped_column(String(120), nullable=False)
    semantic_id: Mapped[str] = mapped_column(String(500), nullable=False)
    semantic_version: Mapped[str] = mapped_column(String(40), nullable=False)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_refs_json: Mapped[str] = mapped_column(Text, nullable=False)
    claim_refs_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    temporal_json: Mapped[str] = mapped_column(Text, nullable=False)
    sensitivity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    context_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    supersedes_id: Mapped[str | None] = mapped_column(String(36))
    preference_origin: Mapped[str | None] = mapped_column(String(40))
    strength: Mapped[str | None] = mapped_column(String(32))
    target_ref: Mapped[str | None] = mapped_column(String(500))
    relation_namespace: Mapped[str | None] = mapped_column(String(120))
    resource_ref: Mapped[str | None] = mapped_column(String(500))
    domain: Mapped[str | None] = mapped_column(String(120))
    relation: Mapped[str | None] = mapped_column(String(120))
    credential_ref: Mapped[str | None] = mapped_column(String(500))
    qualified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    qualification_reason: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccessProfileRow(Base):
    __tablename__ = "access_profiles"

    service_identity: Mapped[str] = mapped_column(String(200), primary_key=True)
    allowed_purposes_json: Mapped[str] = mapped_column(Text, nullable=False)
    allowed_kinds_json: Mapped[str] = mapped_column(Text, nullable=False)
    max_sensitivity: Mapped[int] = mapped_column(Integer, nullable=False)


class DisclosureAuditRow(Base):
    __tablename__ = "disclosure_audit"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    service_identity: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    subject_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    record_refs_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    excluded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def create_database_engine(url: str) -> Engine:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    kwargs = {"future": True, "pool_pre_ping": True, "connect_args": connect_args}
    if url in {"sqlite://", "sqlite:///:memory:"}:
        kwargs["poolclass"] = StaticPool
    return create_engine(url, **kwargs)
