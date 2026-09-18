"""Add feature 003 processing schema: extend datasets (platform_id + metadata),
transformations, dataset_versions, promotion_states, lineage_links,
catalog_metadata.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-18

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Application role used by the control plane (env-configurable; default
# matches docker/docker-compose.dev.yml).
APP_ROLE = "datafoundry_app"


def upgrade() -> None:
    promotion_state = sa.Enum(
        "ingested",
        "ingestion_validated",
        "bronze",
        "bronze_validated",
        "silver",
        "silver_validated",
        "gold",
        "gold_validated",
        "consumable",
        "blocked",
        name="promotion_state",
    )
    dataset_layer = sa.Enum("bronze", "silver", "gold", name="dataset_layer")
    for enum in (promotion_state,):
        enum.create(op.get_bind(), checkfirst=True)

    # -- extend datasets (feature 003) --------------------------------------
    op.add_column(
        "datasets",
        sa.Column(
            "platform_id",
            sa.Uuid(),
            sa.ForeignKey("platforms.id", name="fk_dataset_platform"),
            nullable=True,
        ),
    )
    op.add_column("datasets", sa.Column("steward_identity", sa.String(256), nullable=True))
    op.add_column("datasets", sa.Column("domain", sa.String(63), nullable=True))
    op.add_column("datasets", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("datasets", sa.Column("quality_score", sa.Float(), nullable=True))
    op.add_column(
        "datasets",
        sa.Column("refresh_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # Uniqueness moves from (name) to (platform_id, name).
    op.drop_constraint("uq_dataset_name", "datasets", type_="unique")
    op.create_unique_constraint("uq_dataset_platform_name", "datasets", ["platform_id", "name"])

    # -- transformations -----------------------------------------------------
    op.create_table(
        "transformations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(63), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_layer", dataset_layer, nullable=False),
        sa.Column("target_layer", dataset_layer, nullable=False),
        sa.Column(
            "logic_definition",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("logic_hash", sa.String(64), nullable=False),
        sa.Column("dedup_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reconciliation_tolerance", sa.Float(), nullable=True),
        sa.Column("owner_identity", sa.String(256), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("name", "version", name="uq_transformation_name_version"),
        sa.CheckConstraint("version >= 1", name="ck_transformation_version_positive"),
        sa.CheckConstraint("name ~ '^[a-z][a-z0-9-]{2,62}$'", name="ck_transformation_name_format"),
    )

    # -- dataset_versions -----------------------------------------------------
    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.Uuid(),
            sa.ForeignKey("datasets.id", name="fk_version_dataset"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "transformation_id",
            sa.Uuid(),
            sa.ForeignKey("transformations.id", name="fk_version_transformation"),
            nullable=True,
        ),
        sa.Column("input_versions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("table_ref", sa.String(256), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quarantined_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "gate_report_id",
            sa.Uuid(),
            sa.ForeignKey("gate_reports.id", name="fk_version_gate_report"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("dataset_id", "version", name="uq_dataset_version"),
        sa.CheckConstraint("version >= 1", name="ck_dataset_version_positive"),
        sa.CheckConstraint("record_count >= 0", name="ck_dataset_version_records_non_negative"),
    )

    # -- promotion_states -----------------------------------------------------
    op.create_table(
        "promotion_states",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.Uuid(),
            sa.ForeignKey("datasets.id", name="fk_promotion_dataset"),
            nullable=False,
        ),
        sa.Column("state", promotion_state, nullable=False),
        sa.Column(
            "gate_report_id",
            sa.Uuid(),
            sa.ForeignKey("gate_reports.id", name="fk_promotion_gate_report"),
            nullable=True,
        ),
        sa.Column(
            "transitioned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.UniqueConstraint("dataset_id", name="uq_promotion_state_dataset"),
    )

    # -- lineage_links ---------------------------------------------------------
    op.create_table(
        "lineage_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "source_dataset_id",
            sa.Uuid(),
            sa.ForeignKey("datasets.id", name="fk_lineage_source"),
            nullable=False,
        ),
        sa.Column(
            "target_dataset_id",
            sa.Uuid(),
            sa.ForeignKey("datasets.id", name="fk_lineage_target"),
            nullable=False,
        ),
        sa.Column(
            "transformation_id",
            sa.Uuid(),
            sa.ForeignKey("transformations.id", name="fk_lineage_transformation"),
            nullable=True,
        ),
        sa.Column("transformation_version", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # -- catalog_metadata -------------------------------------------------------
    op.create_table(
        "catalog_metadata",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.Uuid(),
            sa.ForeignKey("datasets.id", name="fk_catalog_dataset"),
            nullable=False,
        ),
        sa.Column("catalog_endpoint", sa.String(256), nullable=False),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    # Append-only processing tables: revoke UPDATE/DELETE from the application
    # role (constitution Principle III — immutable snapshots/lineage).
    op.execute(
        f"""
        REVOKE UPDATE, DELETE ON dataset_versions FROM {APP_ROLE};
        REVOKE UPDATE, DELETE ON promotion_states FROM {APP_ROLE};
        REVOKE UPDATE, DELETE ON lineage_links FROM {APP_ROLE};
        REVOKE UPDATE, DELETE ON catalog_metadata FROM {APP_ROLE};
        GRANT SELECT, INSERT ON dataset_versions TO {APP_ROLE};
        GRANT SELECT, INSERT ON promotion_states TO {APP_ROLE};
        GRANT SELECT, INSERT ON lineage_links TO {APP_ROLE};
        GRANT SELECT, INSERT ON catalog_metadata TO {APP_ROLE};
        """
    )


def downgrade() -> None:
    op.drop_table("catalog_metadata")
    op.drop_table("lineage_links")
    op.drop_table("promotion_states")
    op.drop_table("dataset_versions")
    op.drop_table("transformations")
    op.drop_constraint("uq_dataset_platform_name", "datasets", type_="unique")
    op.create_unique_constraint("uq_dataset_name", "datasets", ["name"])
    op.drop_column("datasets", "refresh_metadata")
    op.drop_column("datasets", "quality_score")
    op.drop_column("datasets", "description")
    op.drop_column("datasets", "domain")
    op.drop_column("datasets", "steward_identity")
    op.drop_column("datasets", "platform_id")
    sa.Enum(name="promotion_state").drop(op.get_bind(), checkfirst=True)
