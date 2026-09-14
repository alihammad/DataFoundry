"""Add idempotency_key to deployment_runs (T035: Idempotency-Key replay).

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-14

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "deployment_runs",
        sa.Column("idempotency_key", sa.String(128), nullable=True),
    )
    op.create_unique_constraint("uq_run_idempotency_key", "deployment_runs", ["idempotency_key"])


def downgrade() -> None:
    op.drop_constraint("uq_run_idempotency_key", "deployment_runs", type_="unique")
    op.drop_column("deployment_runs", "idempotency_key")
