"""Add feature 006 semantic schema: semantic_models, semantic_metrics,
semantic_dimensions, semantic_measures, semantic_relationships, semantic_tests,
semantic_test_results, semantic_publications, semantic_consumer_registrations,
semantic_query_result_versions.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-20

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Application role used by the control plane (env-configurable; default
# matches docker/docker-compose.dev.yml).
APP_ROLE = "datafoundry_app"


def upgrade() -> None:
    certification_state = sa.Enum("draft", "published", "deprecated", name="certification_state")
    semantic_test_category = sa.Enum(
        "calculation", "reconciliation", "relationship", "filter", name="semantic_test_category"
    )
    semantic_test_status = sa.Enum("passed", "failed", "error", name="semantic_test_status")
    semantic_test_trigger = sa.Enum("publish", "schedule", name="semantic_test_trigger")
    change_classification = sa.Enum("breaking", "non_breaking", name="change_classification")
    consumption_path = sa.Enum("bi", "analyst_sql", "ai_ml", "application", name="consumption_path")
    quality_state = sa.Enum("passed", "failed", "unknown", name="quality_state")
    for enum in (
        certification_state,
        semantic_test_category,
        semantic_test_status,
        semantic_test_trigger,
        change_classification,
        consumption_path,
        quality_state,
    ):
        enum.create(op.get_bind(), checkfirst=True)

    jsonb = postgresql.JSONB()

    op.create_table(
        "semantic_models",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("domain", sa.String(63), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config_yaml", sa.Text(), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("certification_state", certification_state, nullable=False),
        sa.Column("created_by", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("domain", "version", name="uq_semantic_model_domain_version"),
        sa.UniqueConstraint("domain", name="uq_semantic_model_domain"),
    )
    op.create_table(
        "semantic_metrics",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "model_id",
            sa.Uuid(),
            sa.ForeignKey("semantic_models.id", name="fk_metric_model"),
            nullable=False,
        ),
        sa.Column("name", sa.String(63), nullable=False),
        sa.Column("business_definition", sa.Text(), nullable=False),
        sa.Column("formula", jsonb, nullable=False),
        sa.Column("dimensions", jsonb, nullable=False),
        sa.Column("bound_datasets", jsonb, nullable=False),
        sa.Column("owner_identity", sa.String(256), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("freshness", sa.DateTime(timezone=True), nullable=True),
        sa.Column("successor_metric_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("model_id", "name", name="uq_semantic_metric_model_name"),
    )
    op.create_table(
        "semantic_dimensions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "model_id",
            sa.Uuid(),
            sa.ForeignKey("semantic_models.id", name="fk_dimension_model"),
            nullable=False,
        ),
        sa.Column("name", sa.String(63), nullable=False),
        sa.Column("members", jsonb, nullable=False),
        sa.Column("relationships", jsonb, nullable=True),
        sa.Column(
            "protection_status",
            sa.Enum(
                "public",
                "internal",
                "confidential",
                "restricted",
                "highly_restricted",
                name="security_level",
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("model_id", "name", name="uq_semantic_dimension_model_name"),
    )
    op.create_table(
        "semantic_measures",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "model_id",
            sa.Uuid(),
            sa.ForeignKey("semantic_models.id", name="fk_measure_model"),
            nullable=False,
        ),
        sa.Column("name", sa.String(63), nullable=False),
        sa.Column(
            "dataset_id",
            sa.Uuid(),
            sa.ForeignKey("datasets.id", name="fk_measure_dataset"),
            nullable=False,
        ),
        sa.Column("column", sa.String(63), nullable=False),
        sa.Column("data_type", sa.String(63), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("model_id", "name", name="uq_semantic_measure_model_name"),
    )
    op.create_table(
        "semantic_relationships",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "model_id",
            sa.Uuid(),
            sa.ForeignKey("semantic_models.id", name="fk_relationship_model"),
            nullable=False,
        ),
        sa.Column("name", sa.String(63), nullable=False),
        sa.Column(
            "left_dataset_id",
            sa.Uuid(),
            sa.ForeignKey("datasets.id", name="fk_relationship_left"),
            nullable=False,
        ),
        sa.Column(
            "right_dataset_id",
            sa.Uuid(),
            sa.ForeignKey("datasets.id", name="fk_relationship_right"),
            nullable=False,
        ),
        sa.Column("join_key", sa.String(63), nullable=False),
        sa.Column("join_type", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("model_id", "name", name="uq_semantic_relationship_model_name"),
    )
    op.create_table(
        "semantic_tests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "model_id",
            sa.Uuid(),
            sa.ForeignKey("semantic_models.id", name="fk_semantic_test_model"),
            nullable=False,
        ),
        sa.Column("name", sa.String(63), nullable=False),
        sa.Column("category", semantic_test_category, nullable=False),
        sa.Column("parameters", jsonb, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("model_id", "name", name="uq_semantic_test_model_name"),
    )
    op.create_table(
        "semantic_publications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "model_id",
            sa.Uuid(),
            sa.ForeignKey("semantic_models.id", name="fk_publication_model"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("change_classification", change_classification, nullable=False),
        sa.Column(
            "approval_status",
            sa.Enum("pending", "approved", "rejected", name="approval_status"),
            nullable=False,
        ),
        sa.Column("approved_by", sa.String(256), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "semantic_test_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "test_id",
            sa.Uuid(),
            sa.ForeignKey("semantic_tests.id", name="fk_test_result_test"),
            nullable=False,
        ),
        sa.Column(
            "publication_id",
            sa.Uuid(),
            sa.ForeignKey("semantic_publications.id", name="fk_test_result_publication"),
            nullable=True,
        ),
        sa.Column("status", semantic_test_status, nullable=False),
        sa.Column("measured_value", jsonb, nullable=True),
        sa.Column("ran_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trigger", semantic_test_trigger, nullable=False),
    )
    op.create_table(
        "semantic_consumer_registrations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "metric_id",
            sa.Uuid(),
            sa.ForeignKey("semantic_metrics.id", name="fk_consumer_metric"),
            nullable=False,
        ),
        sa.Column("consumer_identity", sa.String(256), nullable=False),
        sa.Column("consumption_path", consumption_path, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "semantic_query_result_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "metric_id",
            sa.Uuid(),
            sa.ForeignKey("semantic_metrics.id", name="fk_query_result_metric"),
            nullable=False,
        ),
        sa.Column("model_version", sa.Integer(), nullable=False),
        sa.Column("dataset_versions", jsonb, nullable=False),
        sa.Column("freshness", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quality_state", quality_state, nullable=False),
        sa.Column("queried_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("semantic_query_result_versions")
    op.drop_table("semantic_consumer_registrations")
    op.drop_table("semantic_test_results")
    op.drop_table("semantic_publications")
    op.drop_table("semantic_tests")
    op.drop_table("semantic_relationships")
    op.drop_table("semantic_measures")
    op.drop_table("semantic_dimensions")
    op.drop_table("semantic_metrics")
    op.drop_table("semantic_models")
    for name in (
        "quality_state",
        "consumption_path",
        "change_classification",
        "semantic_test_trigger",
        "semantic_test_status",
        "semantic_test_category",
        "certification_state",
    ):
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)
