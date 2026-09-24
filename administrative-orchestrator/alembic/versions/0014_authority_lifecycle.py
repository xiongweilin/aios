"""Add audited authority lifecycle events.

Revision ID: 0014_authority_lifecycle
Revises: 0013_m5_fact_provenance
Create Date: 2026-09-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_authority_lifecycle"
down_revision: str | None = "0013_m5_fact_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "administrative_authority_lifecycle_event",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("actor_principal_id", sa.String(length=255), nullable=False),
        sa.Column("target_ref", sa.String(length=1000), nullable=False),
        sa.Column("reason", sa.String(length=2000), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_admin_authority_lifecycle_time",
        "administrative_authority_lifecycle_event",
        ["occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_admin_authority_lifecycle_time",
        table_name="administrative_authority_lifecycle_event",
    )
    op.drop_table("administrative_authority_lifecycle_event")
