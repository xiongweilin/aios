"""Persist Kernel Work admission lineage.

Revision ID: 0011_kernel_work_admission_refs
Revises: 0010_kernel_submission_refs
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_kernel_work_admission_refs"
down_revision: str | None = "0010_kernel_submission_refs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = "administrative_kernel_bridge_projection"
    op.add_column(table, sa.Column("kernel_work_admission_status", sa.String(length=64)))
    op.add_column(table, sa.Column("kernel_admission_policy_ref", sa.String(length=512)))
    op.add_column(table, sa.Column("kernel_priority_judgment_ref", sa.String(length=512)))
    op.add_column(table, sa.Column("kernel_resource_pool_ref", sa.String(length=512)))
    op.add_column(table, sa.Column("kernel_portfolio_admission_ref", sa.String(length=512)))
    op.add_column(table, sa.Column("kernel_reservation_ref", sa.String(length=512)))
    op.add_column(table, sa.Column("kernel_commitment_ref", sa.String(length=512)))


def downgrade() -> None:
    table = "administrative_kernel_bridge_projection"
    op.drop_column(table, "kernel_commitment_ref")
    op.drop_column(table, "kernel_reservation_ref")
    op.drop_column(table, "kernel_portfolio_admission_ref")
    op.drop_column(table, "kernel_resource_pool_ref")
    op.drop_column(table, "kernel_priority_judgment_ref")
    op.drop_column(table, "kernel_admission_policy_ref")
    op.drop_column(table, "kernel_work_admission_status")
