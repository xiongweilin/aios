"""Separate authority epoch from case state version.

Revision ID: 0002_authority_epoch
Revises: 0001_initial
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_authority_epoch"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "administrative_case",
    "administrative_policy_evaluation",
    "administrative_decision",
    "administrative_execution_authorization",
    "administrative_effect",
    "administrative_confirmed_outcome",
)


def upgrade() -> None:
    for table_name in _TABLES:
        op.add_column(
            table_name,
            sa.Column(
                "authority_epoch",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            ),
        )


def downgrade() -> None:
    for table_name in reversed(_TABLES):
        op.drop_column(table_name, "authority_epoch")
