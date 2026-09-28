from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from .persistence import Base


class ConversationRow(Base):
    __tablename__ = "administrative_conversation"

    conversation_ref: Mapped[str] = mapped_column(String(1000), primary_key=True)
    provider: Mapped[str] = mapped_column(String(255), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    thread_ref: Mapped[str] = mapped_column(String(1000), nullable=False)
    sender_external_subject: Mapped[str] = mapped_column(String(1000), nullable=False)
    participants_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    last_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_message_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    bound_case_id: Mapped[UUID | None] = mapped_column(ForeignKey("administrative_case.case_id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConversationMessageRow(Base):
    __tablename__ = "administrative_conversation_message"
    __table_args__ = (
        UniqueConstraint("conversation_ref", "provider_message_id", name="uq_conversation_provider_message"),
        UniqueConstraint("conversation_ref", "source_event_id", name="uq_conversation_source_event"),
        UniqueConstraint("conversation_ref", "sequence", name="uq_conversation_sequence"),
    )

    message_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    conversation_ref: Mapped[str] = mapped_column(ForeignKey("administrative_conversation.conversation_ref"), nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(512), nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(512), nullable=False)
    sender_external_subject: Mapped[str] = mapped_column(String(1000), nullable=False)
    displayed_sender: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    participants_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    interpretation_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    candidate_fact_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    candidate_ref: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    case_update_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
