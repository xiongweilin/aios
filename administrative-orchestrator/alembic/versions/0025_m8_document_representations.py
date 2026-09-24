"""Persist immutable derived document representations and exact span links.

Revision ID: 0025_m8_document_repr
Revises: 0024_m8_obligation_unique
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_m8_document_repr"
down_revision: str | None = "0024_m8_obligation_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "administrative_document_representation",
        sa.Column("representation_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "source_artifact_ref",
            sa.Uuid(),
            sa.ForeignKey("administrative_source_artifact.artifact_id"),
            nullable=False,
        ),
        sa.Column("representation_kind", sa.String(length=128), nullable=False),
        sa.Column("extractor_ref", sa.String(length=512), nullable=False),
        sa.Column("extractor_version", sa.String(length=256), nullable=False),
        sa.Column("content_digest", sa.String(length=128), nullable=False),
        sa.Column("storage_ref", sa.String(length=2000), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "source_artifact_ref",
            "content_digest",
            "extractor_ref",
            "extractor_version",
            name="uq_document_representation_semantics",
        ),
    )
    op.add_column(
        "administrative_evidence_span",
        sa.Column("representation_ref", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_evidence_span_representation_ref",
        "administrative_evidence_span",
        ["representation_ref"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_evidence_span_representation_ref",
        table_name="administrative_evidence_span",
    )
    op.drop_column("administrative_evidence_span", "representation_ref")
    op.drop_table("administrative_document_representation")
