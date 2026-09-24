"""Store Personal World basis used by requirement analysis.

Revision ID: 0011_personal_context_basis
Revises: 0010_operator_requirements
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_personal_context_basis"
down_revision: str | None = "0010_operator_requirements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "requirement_analyses",
        sa.Column("personal_context_projection_ref", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "requirement_analyses",
        sa.Column(
            "personal_context_basis_refs_json",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "requirement_analyses",
        sa.Column(
            "personal_context_revalidation_refs_json",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("requirement_analyses", "personal_context_revalidation_refs_json")
    op.drop_column("requirement_analyses", "personal_context_basis_refs_json")
    op.drop_column("requirement_analyses", "personal_context_projection_ref")
