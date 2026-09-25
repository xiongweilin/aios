"""Add organizational authority and persisted policy plane.

Revision ID: 0006_authority_policy_plane
Revises: 0005_fact_history_ingress
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_authority_policy_plane"
down_revision: str | None = "0005_fact_history_ingress"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "administrative_principal",
        sa.Column("principal_id", sa.String(length=255), primary_key=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "administrative_identity_binding",
        sa.Column("binding_id", sa.Uuid(), primary_key=True),
        sa.Column("provider", sa.String(length=255), nullable=False),
        sa.Column("external_subject", sa.String(length=512), nullable=False),
        sa.Column(
            "principal_id",
            sa.String(length=255),
            sa.ForeignKey("administrative_principal.principal_id"),
            nullable=False,
        ),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "provider",
            "external_subject",
            name="uq_admin_identity_provider_subject",
        ),
    )
    op.create_table(
        "administrative_role_assignment",
        sa.Column("assignment_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "principal_id",
            sa.String(length=255),
            sa.ForeignKey("administrative_principal.principal_id"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=128), nullable=False),
        sa.Column("organization_scope", sa.String(length=512), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_admin_role_principal_role",
        "administrative_role_assignment",
        ["principal_id", "role"],
    )
    op.create_table(
        "administrative_delegation",
        sa.Column("delegation_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "from_principal_id",
            sa.String(length=255),
            sa.ForeignKey("administrative_principal.principal_id"),
            nullable=False,
        ),
        sa.Column(
            "to_principal_id",
            sa.String(length=255),
            sa.ForeignKey("administrative_principal.principal_id"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=128), nullable=False),
        sa.Column("organization_scope", sa.String(length=512), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_admin_delegation_recipient_role",
        "administrative_delegation",
        ["to_principal_id", "role"],
    )
    op.create_table(
        "administrative_decision_authority_binding",
        sa.Column(
            "decision_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_decision.decision_id"),
            primary_key=True,
        ),
        sa.Column("decision_role", sa.String(length=128), nullable=False),
        sa.Column("organization_scope", sa.String(length=512), nullable=False),
        sa.Column(
            "authenticated_principal_id",
            sa.String(length=255),
            sa.ForeignKey("administrative_principal.principal_id"),
            nullable=False,
        ),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "administrative_approval_satisfaction",
        sa.Column("satisfaction_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_case.case_id"),
            nullable=False,
        ),
        sa.Column("authority_epoch", sa.Integer(), nullable=False),
        sa.Column("policy_json", sa.JSON(), nullable=False),
        sa.Column("decision_ids_json", sa.JSON(), nullable=False),
        sa.Column("satisfied_roles_json", sa.JSON(), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_admin_approval_satisfaction_case_epoch",
        "administrative_approval_satisfaction",
        ["case_id", "authority_epoch"],
    )
    op.create_table(
        "administrative_policy_version",
        sa.Column("policy_id", sa.String(length=255), primary_key=True),
        sa.Column("version", sa.String(length=128), primary_key=True),
        sa.Column("owner", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("definition_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_admin_policy_status_effective",
        "administrative_policy_version",
        ["policy_id", "status", "effective_from"],
    )


def downgrade() -> None:
    op.drop_index("ix_admin_policy_status_effective", table_name="administrative_policy_version")
    op.drop_table("administrative_policy_version")
    op.drop_index(
        "ix_admin_approval_satisfaction_case_epoch",
        table_name="administrative_approval_satisfaction",
    )
    op.drop_table("administrative_approval_satisfaction")
    op.drop_table("administrative_decision_authority_binding")
    op.drop_index(
        "ix_admin_delegation_recipient_role",
        table_name="administrative_delegation",
    )
    op.drop_table("administrative_delegation")
    op.drop_index(
        "ix_admin_role_principal_role",
        table_name="administrative_role_assignment",
    )
    op.drop_table("administrative_role_assignment")
    op.drop_table("administrative_identity_binding")
    op.drop_table("administrative_principal")
