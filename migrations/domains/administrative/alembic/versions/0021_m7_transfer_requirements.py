"""Add durable Administrative transfer requirements.

Revision ID: 0021_m7_transfer_requirements
Revises: 0020_m7_governance_scope
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0021_m7_transfer_requirements"
down_revision: str | None = "0020_m7_governance_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "administrative_transfer_requirement",
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("authority_epoch", sa.Integer(), nullable=False),
        sa.Column("governance_basis_id", sa.Uuid(), nullable=False),
        sa.Column("departing_principal_id", sa.String(length=255), nullable=False),
        sa.Column("relationship_kind", sa.String(length=64), nullable=False),
        sa.Column("relationship_ref", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=128), nullable=False),
        sa.Column("organization_scope", sa.String(length=255), nullable=False),
        sa.Column("transfer_mode", sa.String(length=32), nullable=False),
        sa.Column("successor_principal_id", sa.String(length=255), nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("qualification_reason", sa.String(length=1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["administrative_case.case_id"]),
        sa.PrimaryKeyConstraint("requirement_id"),
        sa.UniqueConstraint(
            "case_id",
            "authority_epoch",
            "governance_basis_id",
            "relationship_kind",
            "relationship_ref",
            name="uq_admin_transfer_case_epoch_relationship",
        ),
    )


def downgrade() -> None:
    op.drop_table("administrative_transfer_requirement")
