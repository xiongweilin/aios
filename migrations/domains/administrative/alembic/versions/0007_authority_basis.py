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
    # 原始 schema 要求每个 authorization 都指向一个 Decision。
    # 受治理的多方 execution 改为指向 ApprovalSatisfaction，因此
    # legacy decision basis 必须允许为空。batch_alter_table 可以让
    # migration 同时适用于 SQLite smoke test 和 PostgreSQL。
    with op.batch_alter_table("administrative_execution_authorization") as batch_op:
        batch_op.alter_column(
            "decision_id",
            existing_type=sa.Uuid(),
            nullable=True,
        )


def downgrade() -> None:
    # Upgrade/downgrade smoke 在空 schema 上运行。包含
    # approval-backed authorization row 的 deployment 必须先迁移/退役这些 row，
    # 再有意 downgrade 到 decision-only schema。
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
