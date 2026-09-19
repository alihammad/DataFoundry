"""Add feature 005 security schema: classifications, protection_policies,
key_references, token_references, security_audit_records, access_decisions,
encryption_metadata.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-19

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Application role used by the control plane (env-configurable; default
# matches docker/docker-compose.dev.yml).
APP_ROLE = "datafoundry_app"


def upgrade() -> None:
    security_level = sa.Enum(
        "public",
        "internal",
        "confidential",
        "restricted",
        "highly_restricted",
        name="security_level",
    )
    protection_mechanism = sa.Enum(
        "encrypt",
        "tokenise",
        "mask",
        "hash",
        "redact",
        "pseudonymise",
        name="protection_mechanism",
    )
    kms_provider = sa.Enum("aws_kms", "gcp_cloud_kms", name="kms_provider")
    key_lifecycle_state = sa.Enum("active", "disabled", "revoked", name="key_lifecycle_state")
    audit_result = sa.Enum("success", "denied", "failed", name="audit_result")
    access_outcome = sa.Enum("granted", "denied", name="access_outcome")
    verification_result = sa.Enum("verified", "failed", "not_verified", name="verification_result")
    for enum in (
        security_level,
        protection_mechanism,
        kms_provider,
        key_lifecycle_state,
        audit_result,
        access_outcome,
        verification_result,
    ):
        enum.create(op.get_bind(), checkfirst=True)

    jsonb = postgresql.JSONB()

    op.create_table(
        "protection_policies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(63), nullable=False),
        sa.Column("classification", security_level, nullable=False),
        sa.Column("mechanism", protection_mechanism, nullable=False),
        sa.Column("key_ref_id", sa.Uuid(), sa.ForeignKey("key_references.id"), nullable=True),
        sa.Column("token_service_ref", sa.String(256), nullable=True),
        sa.Column("authorised_roles", jsonb, nullable=False),
        sa.Column("detokenise_roles", jsonb, nullable=True),
        sa.Column("masking_rule", jsonb, nullable=True),
        sa.Column("created_by", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_protection_policy_name"),
    )
    op.create_table(
        "key_references",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kms", kms_provider, nullable=False),
        sa.Column("key_id", sa.String(256), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("lifecycle_state", key_lifecycle_state, nullable=False),
        sa.Column("rotation_schedule", sa.String(64), nullable=True),
        sa.Column("usage_permissions", jsonb, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "classifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.Uuid(),
            sa.ForeignKey("datasets.id", name="fk_classification_dataset"),
            nullable=False,
        ),
        sa.Column("level", security_level, nullable=False),
        sa.Column("column", sa.String(63), nullable=True),
        sa.Column(
            "policy_id",
            sa.Uuid(),
            sa.ForeignKey("protection_policies.id", name="fk_classification_policy"),
            nullable=False,
        ),
        sa.Column("changed_by", sa.String(256), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_level", security_level, nullable=True),
        sa.UniqueConstraint("dataset_id", "column", name="uq_classification_dataset_column"),
    )
    op.create_table(
        "token_references",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.Uuid(),
            sa.ForeignKey("datasets.id", name="fk_token_dataset"),
            nullable=False,
        ),
        sa.Column("column", sa.String(63), nullable=False),
        sa.Column("token", sa.String(256), nullable=False),
        sa.Column("original_hash", sa.String(64), nullable=False),
        sa.Column("deterministic", sa.Boolean(), nullable=False),
        sa.Column("token_service_ref", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("dataset_id", "column", "token", name="uq_token_dataset_column_token"),
    )
    op.create_table(
        "security_audit_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("identity", sa.String(256), nullable=False),
        sa.Column(
            "dataset_id",
            sa.Uuid(),
            sa.ForeignKey("datasets.id", name="fk_security_audit_dataset"),
            nullable=True,
        ),
        sa.Column("column", sa.String(63), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("purpose", sa.String(256), nullable=True),
        sa.Column("result", audit_result, nullable=False),
        sa.Column("protection_service_ref", sa.String(256), nullable=True),
        sa.Column("prev_hash", sa.String(64), nullable=True),
        sa.Column("hash", sa.String(64), nullable=False),
    )
    op.create_index("ix_security_audit_identity", "security_audit_records", ["identity"])
    op.create_index("ix_security_audit_dataset", "security_audit_records", ["dataset_id"])
    op.create_index("ix_security_audit_action", "security_audit_records", ["action"])
    op.create_table(
        "access_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("identity", sa.String(256), nullable=False),
        sa.Column("resource", sa.String(256), nullable=False),
        sa.Column("classification_consulted", security_level, nullable=False),
        sa.Column(
            "policy_applied",
            sa.Uuid(),
            sa.ForeignKey("protection_policies.id", name="fk_access_policy"),
            nullable=True,
        ),
        sa.Column("outcome", access_outcome, nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "encryption_metadata",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("file_ref", sa.String(256), nullable=False),
        sa.Column("mechanism", sa.String(64), nullable=False),
        sa.Column(
            "key_ref_id",
            sa.Uuid(),
            sa.ForeignKey("key_references.id", name="fk_encryption_key_ref"),
            nullable=True,
        ),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column("verification_result", verification_result, nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )

    # SecurityAuditRecord is append-only: revoke UPDATE/DELETE (FR-014).
    op.execute(f"REVOKE UPDATE, DELETE ON security_audit_records FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("encryption_metadata")
    op.drop_table("access_decisions")
    op.drop_index("ix_security_audit_action", table_name="security_audit_records")
    op.drop_index("ix_security_audit_dataset", table_name="security_audit_records")
    op.drop_index("ix_security_audit_identity", table_name="security_audit_records")
    op.drop_table("security_audit_records")
    op.drop_table("token_references")
    op.drop_table("classifications")
    op.drop_table("key_references")
    op.drop_table("protection_policies")
    for name in (
        "verification_result",
        "access_outcome",
        "audit_result",
        "key_lifecycle_state",
        "kms_provider",
        "protection_mechanism",
        "security_level",
    ):
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)
