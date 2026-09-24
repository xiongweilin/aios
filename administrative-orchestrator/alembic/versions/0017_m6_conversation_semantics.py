"""Add durable M6 conversation and provider-message semantics.

Revision ID: 0017_m6_conversation
Revises: 0016_m6_assess_unique
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0017_m6_conversation"
down_revision: str | None = "0016_m6_assess_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "administrative_conversation",
        sa.Column("conversation_ref", sa.String(length=1000), primary_key=True),
        sa.Column("provider", sa.String(length=255), nullable=False),
        sa.Column("tenant_ref", sa.String(length=512), nullable=False),
        sa.Column("thread_ref", sa.String(length=1000), nullable=False),
        sa.Column("sender_external_subject", sa.String(length=1000), nullable=False),
        sa.Column("participants_json", sa.JSON(), nullable=False),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.Column("last_message_id", sa.Uuid(), nullable=True),
        sa.Column(
            "bound_case_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_case.case_id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_administrative_conversation_tenant",
        "administrative_conversation",
        ["provider", "tenant_ref", "thread_ref"],
    )

    op.create_table(
        "administrative_conversation_message",
        sa.Column("message_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_ref",
            sa.String(length=1000),
            sa.ForeignKey("administrative_conversation.conversation_ref"),
            nullable=False,
        ),
        sa.Column("provider_message_id", sa.String(length=512), nullable=False),
        sa.Column("source_event_id", sa.String(length=512), nullable=False),
        sa.Column("sender_external_subject", sa.String(length=1000), nullable=False),
        sa.Column("displayed_sender", sa.String(length=1000), nullable=True),
        sa.Column("participants_json", sa.JSON(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_digest", sa.String(length=128), nullable=True),
        sa.Column("source_refs_json", sa.JSON(), nullable=False),
        sa.Column("interpretation_refs_json", sa.JSON(), nullable=False),
        sa.Column("candidate_fact_refs_json", sa.JSON(), nullable=False),
        sa.Column("candidate_ref", sa.Uuid(), nullable=True),
        sa.Column("case_update_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "conversation_ref",
            "provider_message_id",
            name="uq_conversation_provider_message",
        ),
        sa.UniqueConstraint(
            "conversation_ref",
            "source_event_id",
            name="uq_conversation_source_event",
        ),
        sa.UniqueConstraint(
            "conversation_ref",
            "sequence",
            name="uq_conversation_sequence",
        ),
    )
    op.create_index(
        "ix_conversation_message_event",
        "administrative_conversation_message",
        ["conversation_ref", "source_event_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_message_event",
        table_name="administrative_conversation_message",
    )
    op.drop_table("administrative_conversation_message")
    op.drop_index(
        "ix_administrative_conversation_tenant",
        table_name="administrative_conversation",
    )
    op.drop_table("administrative_conversation")
