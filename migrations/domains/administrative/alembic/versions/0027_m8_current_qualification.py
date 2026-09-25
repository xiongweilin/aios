"""Bind current qualification identity and governance basis references.

Revision ID: 0027_m8_current_qualification
Revises: 0026_m8_transaction_evidence
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0027_m8_current_qualification"
down_revision: str | None = "0026_m8_transaction_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "administrative_transaction_qualification_assessment",
        sa.Column("supersedes_assessment_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "uq_transaction_qualification_assessment_supersedes",
        "administrative_transaction_qualification_assessment",
        ["supersedes_assessment_id"],
        unique=True,
    )
    op.add_column(
        "administrative_governance_basis",
        sa.Column("transaction_qualifications_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("administrative_governance_basis", "transaction_qualifications_json")
    op.drop_index(
        "uq_transaction_qualification_assessment_supersedes",
        table_name="administrative_transaction_qualification_assessment",
    )
    op.drop_column(
        "administrative_transaction_qualification_assessment",
        "supersedes_assessment_id",
    )
