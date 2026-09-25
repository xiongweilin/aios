"""Add durable audit records for authorized outbox replay.

Revision ID: 0023_outbox_replay_audit
Revises: 0022_identity_binding_history
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0023_outbox_replay_audit"
down_revision: str | None = "0022_identity_binding_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "administrative_outbox_replay_audit",
        sa.Column("audit_id", sa.Uuid(), primary_key=True),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("actor_principal_id", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.String(length=2000), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["administrative_outbox_event.event_id"]),
    )
    op.create_index(
        "ix_admin_outbox_replay_audit_event_time",
        "administrative_outbox_replay_audit",
        ["event_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_admin_outbox_replay_audit_event_time",
        table_name="administrative_outbox_replay_audit",
    )
    op.drop_table("administrative_outbox_replay_audit")
