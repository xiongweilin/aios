"""m6 final intake assessment uniqueness

Revision ID: 0016_m6_assess_unique
Revises: 0015_m6_intake_core
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0016_m6_assess_unique"
down_revision: str | None = "0015_m6_intake_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_intake_final_assessment_candidate",
        "administrative_intake_assessment",
        ["candidate_ref"],
        unique=True,
        sqlite_where=sa.text("is_final = 1"),
        postgresql_where=sa.text("is_final"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_intake_final_assessment_candidate",
        table_name="administrative_intake_assessment",
    )
