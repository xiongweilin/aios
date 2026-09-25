"""Persist metadata-only governed M9 communication drafts and effects."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0030_m9_communications"
down_revision: str | None = "0029_m9_commitments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "administrative_communication_draft",
        sa.Column("draft_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_case.case_id"),
            nullable=False,
        ),
        sa.Column("authority_epoch", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(64), nullable=False),
        sa.Column("recipient_principal_id", sa.String(255), nullable=False),
        sa.Column("recipient_external_subject", sa.String(1000), nullable=False),
        sa.Column("content_storage_ref", sa.String(2000), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("content_size", sa.Integer(), nullable=False),
        sa.Column("draft_kind", sa.String(128), nullable=False),
        sa.Column("generator_ref", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_by", sa.Uuid(), nullable=True),
    )
    op.create_table(
        "administrative_communication_effect",
        sa.Column("communication_event_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_case.case_id"),
            nullable=False,
        ),
        sa.Column("authority_epoch", sa.Integer(), nullable=False),
        sa.Column(
            "draft_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_communication_draft.draft_id"),
            nullable=False,
        ),
        sa.Column(
            "effect_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_effect.effect_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("delivery_state", sa.String(64), nullable=False),
        sa.Column("read_state", sa.String(64), nullable=False),
        sa.Column("provider_message_ref", sa.String(1000), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_admin_communication_effect_case_epoch",
        "administrative_communication_effect",
        ["case_id", "authority_epoch"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_admin_communication_effect_case_epoch",
        table_name="administrative_communication_effect",
    )
    op.drop_table("administrative_communication_effect")
    op.drop_table("administrative_communication_draft")
