"""Preserve fact authority and field-level provenance in immutable history.

Revision ID: 0013_m5_fact_provenance
Revises: 0012_kernel_execution_refs
Create Date: 2026-09-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_m5_fact_provenance"
down_revision: str | None = "0012_kernel_execution_refs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "administrative_fact_snapshot_history",
        sa.Column("authority", sa.String(length=32), nullable=False, server_default="claim"),
    )
    op.add_column(
        "administrative_fact_snapshot_history",
        sa.Column("source_ref", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "administrative_fact_snapshot_history",
        sa.Column("source_version", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "administrative_fact_snapshot_history",
        sa.Column("assertions_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column("administrative_fact_snapshot_history", "assertions_json")
    op.drop_column("administrative_fact_snapshot_history", "source_version")
    op.drop_column("administrative_fact_snapshot_history", "source_ref")
    op.drop_column("administrative_fact_snapshot_history", "authority")
