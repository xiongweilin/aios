"""Add obligation fulfillment kinds and verified domain-state fulfillments.

Revision ID: 0019_m7_obligation_fulfillment
Revises: 0018_m6_seq_width
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0019_m7_obligation_fulfillment"
down_revision: str | None = "0018_m6_seq_width"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("administrative_obligation") as batch_op:
        batch_op.add_column(
            sa.Column(
                "fulfillment_kind",
                sa.String(length=32),
                nullable=False,
                server_default="external_effect_verified",
            )
        )
    op.create_table(
        "administrative_obligation_fulfillment",
        sa.Column("fulfillment_id", sa.Uuid(), nullable=False),
        sa.Column("obligation_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("authority_epoch", sa.Integer(), nullable=False),
        sa.Column("governance_basis_id", sa.Uuid(), nullable=False),
        sa.Column("fulfillment_kind", sa.String(length=32), nullable=False),
        sa.Column("verified_by", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.String(length=2000), nullable=False),
        sa.Column("observed_state_digest", sa.String(length=128), nullable=False),
        sa.Column("evidence_ref", sa.String(length=1000), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["obligation_id"], ["administrative_obligation.obligation_id"]
        ),
        sa.ForeignKeyConstraint(["case_id"], ["administrative_case.case_id"]),
        sa.PrimaryKeyConstraint("fulfillment_id"),
        sa.UniqueConstraint("obligation_id"),
    )


def downgrade() -> None:
    op.drop_table("administrative_obligation_fulfillment")
    with op.batch_alter_table("administrative_obligation") as batch_op:
        batch_op.drop_column("fulfillment_kind")

