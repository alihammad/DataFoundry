"""Add GitOps provenance to transformations (feature 003, T046, FR-005).

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-19

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    config_source = sa.Enum("api", "cli", "git", name="config_source")
    config_source.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "transformations",
        sa.Column(
            "source",
            sa.Enum("api", "cli", "git", name="config_source"),
            nullable=False,
            server_default="api",
        ),
    )
    op.add_column("transformations", sa.Column("git_ref", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("transformations", "git_ref")
    op.drop_column("transformations", "source")
    sa.Enum(name="config_source").drop(op.get_bind(), checkfirst=True)
