"""Allow non-overlapping identity binding history.

Revision ID: 0022_identity_binding_history
Revises: 0021_m7_transfer_requirements
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0022_identity_binding_history"
down_revision: str | None = "0021_m7_transfer_requirements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("administrative_identity_binding") as batch_op:
        batch_op.drop_constraint(
            "uq_admin_identity_provider_subject",
            type_="unique",
        )
    op.create_index(
        "ix_admin_identity_provider_subject",
        "administrative_identity_binding",
        ["provider", "external_subject"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_admin_identity_provider_subject",
        table_name="administrative_identity_binding",
    )
    with op.batch_alter_table("administrative_identity_binding") as batch_op:
        batch_op.create_unique_constraint(
            "uq_admin_identity_provider_subject",
            ["provider", "external_subject"],
        )
