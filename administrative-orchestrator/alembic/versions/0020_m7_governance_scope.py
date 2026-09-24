"""Add governance dependency scope for expected self-induced change.

Revision ID: 0020_m7_governance_scope
Revises: 0019_m7_obligation_fulfillment
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0020_m7_governance_scope"
down_revision: str | None = "0019_m7_obligation_fulfillment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("administrative_governance_basis") as batch_op:
        batch_op.add_column(
            sa.Column("fact_dependency_keys_json", sa.JSON(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "fact_dependency_values_json",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            )
        )
        batch_op.add_column(
            sa.Column(
                "expected_change_keys_json",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("administrative_governance_basis") as batch_op:
        batch_op.drop_column("expected_change_keys_json")
        batch_op.drop_column("fact_dependency_values_json")
        batch_op.drop_column("fact_dependency_keys_json")

