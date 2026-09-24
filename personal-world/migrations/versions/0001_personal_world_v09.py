"""Personal World v0.9 baseline.

Revision ID: 0001_personal_world_v09
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_personal_world_v09"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_class", sa.String(length=40), nullable=False),
        sa.Column("external_ref", sa.String(length=500)),
        sa.Column("actor_ref", sa.String(length=500)),
        sa.Column("description", sa.Text()),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "observations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("semantic_namespace", sa.String(length=120), nullable=False),
        sa.Column("semantic_kind", sa.String(length=120), nullable=False),
        sa.Column("semantic_id", sa.String(length=500), nullable=False),
        sa.Column("semantic_version", sa.String(length=40), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("temporal_json", sa.Text(), nullable=False),
        sa.Column("sensitivity", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_observations_subject_id", "observations", ["subject_id"])
    op.create_index("ix_observations_source_id", "observations", ["source_id"])

    op.create_table(
        "claims",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("semantic_namespace", sa.String(length=120), nullable=False),
        sa.Column("semantic_kind", sa.String(length=120), nullable=False),
        sa.Column("semantic_id", sa.String(length=500), nullable=False),
        sa.Column("semantic_version", sa.String(length=40), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("observation_refs_json", sa.Text(), nullable=False),
        sa.Column("temporal_json", sa.Text(), nullable=False),
        sa.Column("confidence", sa.String(length=32)),
        sa.Column("sensitivity", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_claims_subject_id", "claims", ["subject_id"])
    op.create_index("ix_claims_source_id", "claims", ["source_id"])

    op.create_table(
        "records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("lineage_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("semantic_namespace", sa.String(length=120), nullable=False),
        sa.Column("semantic_kind", sa.String(length=120), nullable=False),
        sa.Column("semantic_id", sa.String(length=500), nullable=False),
        sa.Column("semantic_version", sa.String(length=40), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("source_refs_json", sa.Text(), nullable=False),
        sa.Column("claim_refs_json", sa.Text(), nullable=False),
        sa.Column("temporal_json", sa.Text(), nullable=False),
        sa.Column("sensitivity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("context_json", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("supersedes_id", sa.String(length=36)),
        sa.Column("preference_origin", sa.String(length=40)),
        sa.Column("strength", sa.String(length=32)),
        sa.Column("target_ref", sa.String(length=500)),
        sa.Column("relation_namespace", sa.String(length=120)),
        sa.Column("resource_ref", sa.String(length=500)),
        sa.Column("domain", sa.String(length=120)),
        sa.Column("relation", sa.String(length=120)),
        sa.Column("credential_ref", sa.String(length=500)),
        sa.Column("qualified_at", sa.DateTime(timezone=True)),
        sa.Column("qualification_reason", sa.Text()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("lineage_id", "revision", name="uq_record_lineage_revision"),
    )
    op.create_index("ix_records_lineage_id", "records", ["lineage_id"])
    op.create_index("ix_records_kind", "records", ["kind"])
    op.create_index("ix_records_subject_id", "records", ["subject_id"])
    op.create_index("ix_records_status", "records", ["status"])

    op.create_table(
        "access_profiles",
        sa.Column("service_identity", sa.String(length=200), primary_key=True),
        sa.Column("allowed_purposes_json", sa.Text(), nullable=False),
        sa.Column("allowed_kinds_json", sa.Text(), nullable=False),
        sa.Column("max_sensitivity", sa.Integer(), nullable=False),
    )

    op.create_table(
        "disclosure_audit",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("service_identity", sa.String(length=200), nullable=False),
        sa.Column("purpose", sa.String(length=200), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("record_refs_json", sa.Text(), nullable=False),
        sa.Column("excluded_count", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_disclosure_audit_service_identity",
        "disclosure_audit",
        ["service_identity"],
    )
    op.create_index("ix_disclosure_audit_purpose", "disclosure_audit", ["purpose"])
    op.create_index("ix_disclosure_audit_subject_id", "disclosure_audit", ["subject_id"])


def downgrade() -> None:
    op.drop_index("ix_disclosure_audit_subject_id", table_name="disclosure_audit")
    op.drop_index("ix_disclosure_audit_purpose", table_name="disclosure_audit")
    op.drop_index("ix_disclosure_audit_service_identity", table_name="disclosure_audit")
    op.drop_table("disclosure_audit")

    op.drop_table("access_profiles")

    op.drop_index("ix_records_status", table_name="records")
    op.drop_index("ix_records_subject_id", table_name="records")
    op.drop_index("ix_records_kind", table_name="records")
    op.drop_index("ix_records_lineage_id", table_name="records")
    op.drop_table("records")

    op.drop_index("ix_claims_source_id", table_name="claims")
    op.drop_index("ix_claims_subject_id", table_name="claims")
    op.drop_table("claims")

    op.drop_index("ix_observations_source_id", table_name="observations")
    op.drop_index("ix_observations_subject_id", table_name="observations")
    op.drop_table("observations")

    op.drop_table("sources")
