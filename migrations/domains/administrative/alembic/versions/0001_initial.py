"""Initial administrative domain schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "administrative_request",
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("requester_principal_id", sa.String(length=255), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("intent", sa.String(length=1000), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_ref", sa.String(length=1000), nullable=True),
        sa.PrimaryKeyConstraint("request_id"),
    )

    op.create_table(
        "administrative_case",
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("case_kind", sa.String(length=128), nullable=False),
        sa.Column("requester_principal_id", sa.String(length=255), nullable=False),
        sa.Column("subject_ref", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("policy_json", sa.JSON(), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("reopen_reason", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["request_id"], ["administrative_request.request_id"]),
        sa.PrimaryKeyConstraint("case_id"),
    )
    op.create_index(
        "ix_administrative_case_status_updated_at",
        "administrative_case",
        ["status", "updated_at"],
    )

    op.create_table(
        "administrative_policy_evaluation",
        sa.Column("sequence", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("policy_json", sa.JSON(), nullable=False),
        sa.Column("evaluation_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["administrative_case.case_id"]),
        sa.PrimaryKeyConstraint("sequence"),
    )
    op.create_index(
        "ix_policy_evaluation_case_sequence",
        "administrative_policy_evaluation",
        ["case_id", "sequence"],
    )

    op.create_table(
        "administrative_decision",
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("principal_id", sa.String(length=255), nullable=False),
        sa.Column("disposition", sa.String(length=64), nullable=False),
        sa.Column("rationale", sa.String(length=2000), nullable=False),
        sa.Column("policy_json", sa.JSON(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["administrative_case.case_id"]),
        sa.PrimaryKeyConstraint("decision_id"),
    )
    op.create_index(
        "ix_administrative_decision_case",
        "administrative_decision",
        ["case_id", "decided_at"],
    )

    op.create_table(
        "administrative_execution_authorization",
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("issuer_principal_id", sa.String(length=255), nullable=False),
        sa.Column("target_system", sa.String(length=255), nullable=False),
        sa.Column("subject_ref", sa.String(length=512), nullable=False),
        sa.Column("allowed_operations", sa.JSON(), nullable=False),
        sa.Column("authority_class", sa.String(length=64), nullable=False),
        sa.Column("policy_json", sa.JSON(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["administrative_case.case_id"]),
        sa.ForeignKeyConstraint(["decision_id"], ["administrative_decision.decision_id"]),
        sa.PrimaryKeyConstraint("authorization_id"),
    )
    op.create_index(
        "ix_execution_authorization_case",
        "administrative_execution_authorization",
        ["case_id", "case_version"],
    )

    op.create_table(
        "administrative_effect",
        sa.Column("effect_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("target_system", sa.String(length=255), nullable=False),
        sa.Column("operation", sa.String(length=255), nullable=False),
        sa.Column("subject_ref", sa.String(length=512), nullable=False),
        sa.Column("reversibility", sa.String(length=64), nullable=False),
        sa.Column("authority_class", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("provider_ref", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["authorization_id"], ["administrative_execution_authorization.authorization_id"]),
        sa.ForeignKeyConstraint(["case_id"], ["administrative_case.case_id"]),
        sa.PrimaryKeyConstraint("effect_id"),
    )
    op.create_index(
        "ix_administrative_effect_case_status",
        "administrative_effect",
        ["case_id", "status"],
    )

    op.create_table(
        "administrative_effect_realization",
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("effect_id", sa.Uuid(), nullable=False),
        sa.Column("disposition", sa.String(length=64), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["effect_id"], ["administrative_effect.effect_id"]),
        sa.PrimaryKeyConstraint("assessment_id"),
    )

    op.create_table(
        "administrative_confirmed_outcome",
        sa.Column("outcome_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("effect_id", sa.Uuid(), nullable=False),
        sa.Column("realization_assessment_id", sa.Uuid(), nullable=False),
        sa.Column("outcome_kind", sa.String(length=255), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["administrative_case.case_id"]),
        sa.ForeignKeyConstraint(["effect_id"], ["administrative_effect.effect_id"]),
        sa.ForeignKeyConstraint(
            ["realization_assessment_id"],
            ["administrative_effect_realization.assessment_id"],
        ),
        sa.PrimaryKeyConstraint("outcome_id"),
    )

    op.create_table(
        "administrative_audit_event",
        sa.Column("sequence", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["administrative_case.case_id"]),
        sa.PrimaryKeyConstraint("sequence"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index(
        "ix_administrative_audit_case_sequence",
        "administrative_audit_event",
        ["case_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_index("ix_administrative_audit_case_sequence", table_name="administrative_audit_event")
    op.drop_table("administrative_audit_event")
    op.drop_table("administrative_confirmed_outcome")
    op.drop_table("administrative_effect_realization")
    op.drop_index("ix_administrative_effect_case_status", table_name="administrative_effect")
    op.drop_table("administrative_effect")
    op.drop_index(
        "ix_execution_authorization_case",
        table_name="administrative_execution_authorization",
    )
    op.drop_table("administrative_execution_authorization")
    op.drop_index("ix_administrative_decision_case", table_name="administrative_decision")
    op.drop_table("administrative_decision")
    op.drop_index(
        "ix_policy_evaluation_case_sequence",
        table_name="administrative_policy_evaluation",
    )
    op.drop_table("administrative_policy_evaluation")
    op.drop_index("ix_administrative_case_status_updated_at", table_name="administrative_case")
    op.drop_table("administrative_case")
    op.drop_table("administrative_request")
