"""Persist Kernel bounded execution lineage.

Revision ID: 0012_kernel_execution_refs
Revises: 0011_kernel_work_admission_refs
Create Date: 2026-09-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_kernel_execution_refs"
down_revision: str | None = "0011_kernel_work_admission_refs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = "administrative_kernel_bridge_projection"
    op.add_column(table, sa.Column("kernel_execution_status", sa.String(length=64)))
    op.add_column(table, sa.Column("kernel_execution_ref", sa.String(length=512)))
    op.add_column(table, sa.Column("kernel_request_ref", sa.String(length=512)))
    op.add_column(table, sa.Column("kernel_authorization_ref", sa.String(length=512)))
    op.add_column(table, sa.Column("kernel_provider_id", sa.String(length=512)))
    op.add_column(table, sa.Column("kernel_action_ref", sa.String(length=512)))
    op.add_column(table, sa.Column("kernel_outcome_ref", sa.String(length=512)))
    op.add_column(table, sa.Column("kernel_evidence_ref", sa.String(length=512)))
    op.add_column(table, sa.Column("kernel_execution_responsibility_ref", sa.String(length=512)))
    op.add_column(table, sa.Column("kernel_execution_processed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    table = "administrative_kernel_bridge_projection"
    op.drop_column(table, "kernel_execution_processed_at")
    op.drop_column(table, "kernel_execution_responsibility_ref")
    op.drop_column(table, "kernel_evidence_ref")
    op.drop_column(table, "kernel_outcome_ref")
    op.drop_column(table, "kernel_action_ref")
    op.drop_column(table, "kernel_provider_id")
    op.drop_column(table, "kernel_authorization_ref")
    op.drop_column(table, "kernel_request_ref")
    op.drop_column(table, "kernel_execution_ref")
    op.drop_column(table, "kernel_execution_status")
