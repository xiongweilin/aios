"""Add Kernel admission and assessment receipt references.

Revision ID: 0010_kernel_submission_refs
Revises: 0009_kernel_bridge
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_kernel_submission_refs"
down_revision: str | None = "0009_kernel_bridge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "administrative_kernel_bridge_projection",
        sa.Column("kernel_admission_ref", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "administrative_kernel_bridge_projection",
        sa.Column("kernel_assessment_ref", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("administrative_kernel_bridge_projection", "kernel_assessment_ref")
    op.drop_column("administrative_kernel_bridge_projection", "kernel_admission_ref")
