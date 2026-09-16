"""Add feature 002 ingestion schema: data sources, ingestion configs, source
contracts, ingestion pipelines, ingestion batches, ingestion runs, quarantine
records.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-16

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Application role used by the control plane (env-configurable; default
# matches docker/docker-compose.dev.yml).
APP_ROLE = "datafoundry_app"


def upgrade() -> None:
    source_type = sa.Enum("postgres", "sqlserver", "object_storage", name="source_type")
    connection_state = sa.Enum("untested", "ok", "failed", name="connection_state")
    ingestion_mode = sa.Enum("full", "incremental", name="ingestion_mode")
    target_zone = sa.Enum("bronze", name="target_zone")
    pipeline_state = sa.Enum("active", "paused", name="pipeline_state")
    batch_status = sa.Enum(
        "ingesting",
        "ingested",
        "ingestion_validated",
        "failed",
        "quarantined",
        name="batch_status",
    )
    ingestion_run_status = sa.Enum(
        "queued", "running", "paused", "succeeded", "failed", name="ingestion_run_status"
    )
    run_trigger = sa.Enum("scheduled", "manual", "retry", name="run_trigger")
    run_outcome = sa.Enum("success", "partial", "failed", name="run_outcome")

    # contract_origin, approval_status, test_severity already exist (0003).
    for enum in (
        source_type,
        connection_state,
        ingestion_mode,
        target_zone,
        pipeline_state,
        batch_status,
        ingestion_run_status,
        run_trigger,
        run_outcome,
    ):
        enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "data_sources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "platform_id",
            sa.Uuid(),
            sa.ForeignKey("platforms.id", name="fk_source_platform"),
            nullable=False,
        ),
        sa.Column("name", sa.String(63), nullable=False),
        sa.Column("type", source_type, nullable=False),
        sa.Column(
            "config_ref",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("owner_identity", sa.String(256), nullable=False),
        sa.Column(
            "connection_state",
            connection_state,
            nullable=False,
            server_default=sa.text("'untested'"),
        ),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_detail", sa.Text(), nullable=True),
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
        sa.UniqueConstraint("platform_id", "name", name="uq_source_name_per_platform"),
        sa.CheckConstraint("name ~ '^[a-z][a-z0-9-]{2,62}$'", name="ck_source_name_format"),
    )

    op.create_table(
        "ingestion_configs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "source_id",
            sa.Uuid(),
            sa.ForeignKey("data_sources.id", name="fk_ingestion_config_source"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config_yaml", sa.Text(), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("source_type", source_type, nullable=False),
        sa.Column(
            "selected_objects",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("ingestion_mode", ingestion_mode, nullable=False),
        sa.Column("schedule", sa.String(128), nullable=True),
        sa.Column(
            "target_zone",
            target_zone,
            nullable=False,
            server_default=sa.text("'bronze'"),
        ),
        sa.Column(
            "validation_settings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_by", sa.String(256), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("source_id", "version", name="uq_ingestion_config_version"),
        sa.CheckConstraint("version >= 1", name="ck_ingestion_config_version_positive"),
        sa.CheckConstraint("length(config_hash) = 64", name="ck_ingestion_config_hash_sha256"),
    )

    op.create_table(
        "source_contracts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "source_id",
            sa.Uuid(),
            sa.ForeignKey("data_sources.id", name="fk_source_contract_source"),
            nullable=False,
        ),
        sa.Column("object_name", sa.String(256), nullable=False),
        sa.Column(
            "schema_definition",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("origin", sa.Enum(name="contract_origin"), nullable=False),
        sa.Column(
            "approval_status",
            sa.Enum(name="approval_status"),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("created_by", sa.String(256), nullable=True),
        sa.Column("approved_by", sa.String(256), nullable=True),
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
        sa.UniqueConstraint("source_id", "object_name", name="uq_contract_per_source_object"),
    )

    op.create_table(
        "ingestion_pipelines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "config_id",
            sa.Uuid(),
            sa.ForeignKey("ingestion_configs.id", name="fk_pipeline_config"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.Uuid(),
            sa.ForeignKey("data_sources.id", name="fk_pipeline_source"),
            nullable=False,
        ),
        sa.Column("name", sa.String(63), nullable=False),
        sa.Column(
            "state",
            pipeline_state,
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("schedule", sa.String(128), nullable=True),
        sa.Column("owner_identity", sa.String(256), nullable=False),
        sa.Column(
            "high_watermarks",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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
        sa.CheckConstraint("name ~ '^[a-z][a-z0-9-]{2,62}$'", name="ck_pipeline_name_format"),
    )

    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "pipeline_id",
            sa.Uuid(),
            sa.ForeignKey("ingestion_pipelines.id", name="fk_run_pipeline"),
            nullable=False,
        ),
        sa.Column("trigger", run_trigger, nullable=False),
        sa.Column(
            "status",
            ingestion_run_status,
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column(
            "retry_of",
            sa.Uuid(),
            sa.ForeignKey("ingestion_runs.id", name="fk_run_retry_of"),
            nullable=True,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "records_processed",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("outcome", run_outcome, nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("log_ref", sa.String(256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("records_processed >= 0", name="ck_run_records_non_negative"),
    )
    op.create_index(
        "uq_one_active_ingestion_run_per_pipeline",
        "ingestion_runs",
        ["pipeline_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running', 'paused')"),
    )

    op.create_table(
        "ingestion_batches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("ingestion_runs.id", name="fk_batch_run"),
            nullable=False,
        ),
        sa.Column(
            "pipeline_id",
            sa.Uuid(),
            sa.ForeignKey("ingestion_pipelines.id", name="fk_batch_pipeline"),
            nullable=False,
        ),
        sa.Column("source_object", sa.String(256), nullable=False),
        sa.Column("source_system", sa.String(256), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column(
            "status",
            batch_status,
            nullable=False,
            server_default=sa.text("'ingesting'"),
        ),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint("record_count >= 0", name="ck_batch_record_count_non_negative"),
        sa.CheckConstraint("length(checksum) = 64", name="ck_batch_checksum_sha256"),
    )

    op.create_table(
        "quarantine_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "pipeline_id",
            sa.Uuid(),
            sa.ForeignKey("ingestion_pipelines.id", name="fk_quarantine_pipeline"),
            nullable=False,
        ),
        sa.Column(
            "batch_id",
            sa.Uuid(),
            sa.ForeignKey("ingestion_batches.id", name="fk_quarantine_batch"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.Uuid(),
            sa.ForeignKey("data_sources.id", name="fk_quarantine_source"),
            nullable=False,
        ),
        sa.Column("payload_ref", sa.String(512), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=False),
        sa.Column("failed_check", sa.String(64), nullable=False),
        sa.Column("severity", sa.Enum(name="test_severity"), nullable=False),
        sa.Column(
            "quarantined_at",
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
    op.create_index(
        "ix_quarantine_source_quarantined",
        "quarantine_records",
        ["source_id", "quarantined_at"],
    )

    # Append-only ingestion tables: revoke UPDATE/DELETE from the application
    # role (data-model.md cross-entity invariant 2 — batches, runs, quarantine
    # records are append-only). Role may not exist in every environment (e.g.
    # sqlite-based tests) — guard with a DO block.
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                    REVOKE UPDATE, DELETE ON ingestion_batches FROM {APP_ROLE};
                    REVOKE UPDATE, DELETE ON ingestion_runs FROM {APP_ROLE};
                    REVOKE UPDATE, DELETE ON quarantine_records FROM {APP_ROLE};
                    GRANT SELECT, INSERT ON ingestion_batches TO {APP_ROLE};
                    GRANT SELECT, INSERT ON ingestion_runs TO {APP_ROLE};
                    GRANT SELECT, INSERT ON quarantine_records TO {APP_ROLE};
                END IF;
            END
            $$;
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_quarantine_source_quarantined", table_name="quarantine_records")
    op.drop_table("quarantine_records")
    op.drop_table("ingestion_batches")
    op.drop_index("uq_one_active_ingestion_run_per_pipeline", table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
    op.drop_table("ingestion_pipelines")
    op.drop_table("source_contracts")
    op.drop_table("ingestion_configs")
    op.drop_table("data_sources")
    for name in (
        "run_outcome",
        "run_trigger",
        "ingestion_run_status",
        "batch_status",
        "pipeline_state",
        "target_zone",
        "ingestion_mode",
        "connection_state",
        "source_type",
    ):
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)
