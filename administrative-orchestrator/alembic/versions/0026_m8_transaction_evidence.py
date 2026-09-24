"""Persist transaction evidence links and qualification assessments.

Revision ID: 0026_m8_transaction_evidence
Revises: 0025_m8_document_repr
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0026_m8_transaction_evidence"
down_revision: str | None = "0025_m8_document_repr"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "administrative_case_evidence_link",
        sa.Column("link_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_case.case_id"),
            nullable=False,
        ),
        sa.Column("authority_epoch", sa.Integer(), nullable=False),
        sa.Column(
            "artifact_ref",
            sa.Uuid(),
            sa.ForeignKey("administrative_source_artifact.artifact_id"),
            nullable=False,
        ),
        sa.Column(
            "representation_ref",
            sa.Uuid(),
            sa.ForeignKey("administrative_document_representation.representation_id"),
            nullable=True,
        ),
        sa.Column("declared_role", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=512), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("linked_by", sa.String(length=255), nullable=False),
        sa.UniqueConstraint(
            "case_id",
            "authority_epoch",
            "artifact_ref",
            "representation_ref",
            "declared_role",
            name="uq_case_evidence_link_semantics",
        ),
    )
    op.create_index(
        "ix_case_evidence_link_case_epoch",
        "administrative_case_evidence_link",
        ["case_id", "authority_epoch"],
    )
    op.create_table(
        "administrative_transaction_qualification_assessment",
        sa.Column("assessment_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_case.case_id"),
            nullable=False,
        ),
        sa.Column("authority_epoch", sa.Integer(), nullable=False),
        sa.Column("assessment_kind", sa.String(length=128), nullable=False),
        sa.Column("input_refs_json", sa.JSON(), nullable=False),
        sa.Column("rule_ref", sa.String(length=512), nullable=False),
        sa.Column("result", sa.String(length=64), nullable=False),
        sa.Column("blocking_reasons_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_transaction_qualification_assessment_case_epoch",
        "administrative_transaction_qualification_assessment",
        ["case_id", "authority_epoch"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_transaction_qualification_assessment_case_epoch",
        table_name="administrative_transaction_qualification_assessment",
    )
    op.drop_table("administrative_transaction_qualification_assessment")
    op.drop_index(
        "ix_case_evidence_link_case_epoch",
        table_name="administrative_case_evidence_link",
    )
    op.drop_table("administrative_case_evidence_link")
