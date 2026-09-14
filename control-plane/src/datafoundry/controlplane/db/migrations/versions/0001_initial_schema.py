"""Initial schema (T013/T014): platforms, config versions, runs, steps,
health results, append-only audit records.

Revision ID: 0001
Revises:
Create Date: 2026-09-14

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Application role used by the control plane (env-configurable; default
# matches docker/docker-compose.dev.yml).
APP_ROLE = "datafoundry_app"


def upgrade() -> None:
    provider = sa.Enum("aws", "gcp", name="provider")
    environment_type = sa.Enum("development", "test", "uat", "production", name="environment_type")
    platform_status = sa.Enum(
        "pending",
        "deploying",
        "ready",
        "degraded",
        "failed",
        "destroying",
        "destroyed",
        name="platform_status",
    )
    run_type = sa.Enum("deploy", "update", "retry", "rollback", "destroy", name="run_type")
    run_status = sa.Enum(
        "queued", "running", "paused", "succeeded", "failed", "rolled_back", name="run_status"
    )
    step_status = sa.Enum(
        "pending", "running", "succeeded", "failed", "skipped", name="step_status"
    )
    config_source = sa.Enum("api", "cli", "git", name="config_source")
    health_status = sa.Enum("healthy", "unhealthy", "unknown", name="health_status")
    for enum in (
        provider,
        environment_type,
        platform_status,
        run_type,
        run_status,
        step_status,
        config_source,
        health_status,
    ):
        enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "platforms",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(63), nullable=False),
        sa.Column("provider", provider, nullable=False),
        sa.Column("cloud_scope_id", sa.String(128), nullable=False),
        sa.Column("region", sa.String(64), nullable=False),
        sa.Column("environment_type", environment_type, nullable=False),
        sa.Column(
            "status",
            platform_status,
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("owner_identity", sa.String(256), nullable=False),
        sa.Column("current_config_version_id", sa.Uuid(), nullable=True),
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
        sa.UniqueConstraint("provider", "cloud_scope_id", "name", name="uq_platform_scope_name"),
        sa.CheckConstraint("name ~ '^[a-z][a-z0-9-]{2,62}$'", name="ck_platform_name_format"),
    )

    op.create_table(
        "platform_config_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "platform_id",
            sa.Uuid(),
            sa.ForeignKey("platforms.id", name="fk_config_version_platform"),
            nullable=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config_yaml", sa.Text(), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("source", config_source, nullable=False),
        sa.Column("git_ref", sa.String(64), nullable=True),
        sa.Column("created_by", sa.String(256), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("platform_id", "version", name="uq_config_version_per_platform"),
        sa.CheckConstraint("version >= 1", name="ck_config_version_positive"),
        sa.CheckConstraint("length(config_hash) = 64", name="ck_config_hash_sha256"),
    )

    op.create_foreign_key(
        "fk_platform_current_config",
        "platforms",
        "platform_config_versions",
        ["current_config_version_id"],
        ["id"],
        use_alter=True,
    )

    op.create_table(
        "deployment_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "platform_id",
            sa.Uuid(),
            sa.ForeignKey("platforms.id", name="fk_run_platform"),
            nullable=False,
        ),
        sa.Column(
            "config_version_id",
            sa.Uuid(),
            sa.ForeignKey("platform_config_versions.id", name="fk_run_config_version"),
            nullable=False,
        ),
        sa.Column("run_type", run_type, nullable=False),
        sa.Column("status", run_status, nullable=False, server_default=sa.text("'queued'")),
        sa.Column("initiated_by", sa.String(256), nullable=False),
        sa.Column("approval_ref", sa.String(256), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terraform_workspace", sa.String(256), nullable=False),
        sa.Column("failure_summary", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("terraform_workspace", name="uq_run_workspace"),
    )
    # One active run per platform (data-model.md invariant 3).
    op.create_index(
        "uq_one_active_run_per_platform",
        "deployment_runs",
        ["platform_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running', 'paused')"),
    )

    op.create_table(
        "deployment_steps",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("deployment_runs.id", name="fk_step_run"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("capability", sa.String(64), nullable=True),
        sa.Column("status", step_status, nullable=False, server_default=sa.text("'pending'")),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("terraform_module", sa.String(256), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.UniqueConstraint("run_id", "position", name="uq_step_position_per_run"),
        sa.CheckConstraint("position >= 1", name="ck_step_position_positive"),
        sa.CheckConstraint("attempt >= 0", name="ck_step_attempt_non_negative"),
    )

    op.create_table(
        "health_check_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "platform_id",
            sa.Uuid(),
            sa.ForeignKey("platforms.id", name="fk_health_platform"),
            nullable=False,
        ),
        sa.Column("component", sa.String(64), nullable=False),
        sa.Column("status", health_status, nullable=False),
        sa.Column(
            "last_check_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("deployment_runs.id", name="fk_health_run"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_health_platform_component", "health_check_results", ["platform_id", "component"]
    )

    op.create_table(
        "audit_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "platform_id",
            sa.Uuid(),
            sa.ForeignKey("platforms.id", name="fk_audit_platform"),
            nullable=True,
        ),
        sa.Column("actor", sa.String(256), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index("ix_audit_platform_occurred", "audit_records", ["platform_id", "occurred_at"])

    # Append-only audit: revoke UPDATE/DELETE from the application role
    # (data-model.md AuditRecord retention). Role may not exist in every
    # environment (e.g. sqlite-based tests) — guard with a DO block.
    # APP_ROLE is a module constant, not user input — no injection vector.
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                    REVOKE UPDATE, DELETE ON audit_records FROM {APP_ROLE};
                    GRANT SELECT, INSERT ON audit_records TO {APP_ROLE};
                END IF;
            END
            $$;
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_audit_platform_occurred", table_name="audit_records")
    op.drop_table("audit_records")
    op.drop_index("ix_health_platform_component", table_name="health_check_results")
    op.drop_table("health_check_results")
    op.drop_table("deployment_steps")
    op.drop_index("uq_one_active_run_per_platform", table_name="deployment_runs")
    op.drop_table("deployment_runs")
    op.drop_constraint("fk_platform_current_config", "platforms", type_="foreignkey")
    op.drop_table("platform_config_versions")
    op.drop_table("platforms")
    for name in (
        "health_status",
        "config_source",
        "step_status",
        "run_status",
        "run_type",
        "platform_status",
        "environment_type",
        "provider",
    ):
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)
