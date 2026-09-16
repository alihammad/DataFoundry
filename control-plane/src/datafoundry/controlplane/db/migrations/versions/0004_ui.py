"""Add feature 007 web UI schema: UI roles, role assignments, saved queries,
saved query shares, notification channels.

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
    sharing_mode = sa.Enum("private", "shared", name="sharing_mode")
    channel_type = sa.Enum("email", "webhook", "slack", name="channel_type")
    role_scope = sa.Enum("platform", "dataset", "column", name="role_scope")

    sharing_mode.create(op.get_bind(), checkfirst=True)
    channel_type.create(op.get_bind(), checkfirst=True)
    role_scope.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "ui_roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=63), nullable=False),
        sa.Column("scope", role_scope, nullable=False),
        sa.Column("permissions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("platform_scope", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("dataset_scope", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_ui_roles_name"),
    )

    op.create_table(
        "ui_role_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("user_identity", sa.String(length=256), nullable=False),
        sa.Column("granted_by", sa.String(length=256), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["ui_roles.id"], name="fk_assignment_role"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role_id", "user_identity", name="uq_role_assignment"),
    )

    op.create_table(
        "saved_queries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=127), nullable=False),
        sa.Column("owner_identity", sa.String(length=256), nullable=False),
        sa.Column("sql_text", sa.Text(), nullable=False),
        sa.Column("dataset_bindings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sharing", sharing_mode, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "saved_query_shares",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("query_id", sa.Uuid(), nullable=False),
        sa.Column("shared_with_identity", sa.String(length=256), nullable=False),
        sa.Column("shared_by", sa.String(length=256), nullable=False),
        sa.Column("shared_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["query_id"], ["saved_queries.id"], name="fk_share_query"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("query_id", "shared_with_identity", name="uq_query_share"),
    )

    op.create_table(
        "notification_channels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("platform_id", sa.Uuid(), nullable=False),
        sa.Column("channel_type", channel_type, nullable=False),
        sa.Column("name", sa.String(length=63), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("event_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["platform_id"], ["platforms.id"], name="fk_channel_platform"),
        sa.PrimaryKeyConstraint("id"),
    )

    # UI-owned tables are mutable (roles/assignments/queries/channels are
    # edited through the UI), so no UPDATE/DELETE revocation here — unlike the
    # append-only audit table.


def downgrade() -> None:
    op.drop_table("notification_channels")
    op.drop_table("saved_query_shares")
    op.drop_table("saved_queries")
    op.drop_table("ui_role_assignments")
    op.drop_table("ui_roles")

    role_scope = sa.Enum(name="role_scope")
    channel_type = sa.Enum(name="channel_type")
    sharing_mode = sa.Enum(name="sharing_mode")
    sharing_mode.drop(op.get_bind(), checkfirst=True)
    channel_type.drop(op.get_bind(), checkfirst=True)
    role_scope.drop(op.get_bind(), checkfirst=True)
