"""Persist governed decision roles and approval authorization basis.

Revision ID: 0007_authority_basis
Revises: 0006_authority_policy_plane
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_authority_basis"
down_revision: str | None = "0006_authority_policy_plane"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "administrative_decision",
        sa.Column("decision_role", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "administrative_execution_authorization",
        sa.Column("approval_satisfaction_id", sa.Uuid(), nullable=True),
    )
    # The original schema required every authorization to point at one Decision.
    # Governed multi-party execution instead points at ApprovalSatisfaction, so
    # the legacy decision basis must become nullable. batch_alter_table keeps
    # the migration portable across the SQLite smoke test and PostgreSQL.
    with op.batch_alter_table("administrative_execution_authorization") as batch_op:
        batch_op.alter_column(
            "decision_id",
            existing_type=sa.Uuid(),
            nullable=True,
        )


def downgrade() -> None:
    # Upgrade/downgrade smoke runs on an empty schema. Deployments containing
    # approval-backed authorization rows must migrate/retire those rows before
    # intentionally downgrading to the decision-only schema.
    with op.batch_alter_table("administrative_execution_authorization") as batch_op:
        batch_op.alter_column(
            "decision_id",
            existing_type=sa.Uuid(),
            nullable=False,
        )
    op.drop_column(
        "administrative_execution_authorization",
        "approval_satisfaction_id",
    )
    op.drop_column("administrative_decision", "decision_role")
