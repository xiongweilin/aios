"""Persist declared obligation tuple order.

Revision ID: 0032_obligation_sequence
Revises: 0031_adaptive_investigation
"""

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0032_obligation_sequence"
down_revision: str | None = "0031_adaptive_investigation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Historical compatibility only. Before this migration the runtime repository
# reconstructed tuple order with these operation priorities because no ordinal
# was persisted. New runtime code never interprets operation names for order.
_LEGACY_OPERATION_ORDER = {
    "purchase_order.create_draft": 0,
    "purchase_order.confirm": 1,
    "vendor_bill.create_draft": 0,
    "expense_report.create": 0,
}


def _legacy_sort_key(row: dict[str, Any]) -> tuple[str, int, str, str, str]:
    operation = str(row["required_operation"])
    return (
        str(row["target_system"]),
        _LEGACY_OPERATION_ORDER.get(operation, 99),
        operation,
        str(row["authority_class"]),
        str(row["obligation_id"]),
    )


def upgrade() -> None:
    op.add_column(
        "administrative_obligation",
        sa.Column("sequence", sa.Integer(), nullable=True),
    )

    connection = op.get_bind()
    rows = (
        connection.execute(
            sa.text(
                "SELECT obligation_id, requirement_id, target_system, "
                "required_operation, authority_class "
                "FROM administrative_obligation"
            )
        )
        .mappings()
        .all()
    )
    grouped: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["requirement_id"]].append(dict(row))

    for obligation_rows in grouped.values():
        for sequence, row in enumerate(sorted(obligation_rows, key=_legacy_sort_key)):
            connection.execute(
                sa.text(
                    "UPDATE administrative_obligation "
                    "SET sequence = :sequence WHERE obligation_id = :obligation_id"
                ),
                {"sequence": sequence, "obligation_id": row["obligation_id"]},
            )

    with op.batch_alter_table("administrative_obligation") as batch_op:
        batch_op.alter_column(
            "sequence",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.create_unique_constraint(
            "uq_admin_obligation_requirement_sequence",
            ["requirement_id", "sequence"],
        )


def downgrade() -> None:
    with op.batch_alter_table("administrative_obligation") as batch_op:
        batch_op.drop_constraint(
            "uq_admin_obligation_requirement_sequence",
            type_="unique",
        )
        batch_op.drop_column("sequence")
