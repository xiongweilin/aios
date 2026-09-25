"""Allow provider conversation sequences larger than a 32-bit integer.

Revision ID: 0018_m6_seq_width
Revises: 0017_m6_conversation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0018_m6_seq_width"
down_revision: str | None = "0017_m6_conversation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("administrative_conversation") as batch_op:
        batch_op.alter_column(
            "last_sequence",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )
    with op.batch_alter_table("administrative_conversation_message") as batch_op:
        batch_op.alter_column(
            "sequence",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("administrative_conversation_message") as batch_op:
        batch_op.alter_column(
            "sequence",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=False,
        )
    with op.batch_alter_table("administrative_conversation") as batch_op:
        batch_op.alter_column(
            "last_sequence",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=False,
        )
