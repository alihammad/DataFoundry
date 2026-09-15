"""Add feature 004 quality schema: datasets (stub), quality gates, tests,
test results, gate reports, data contracts, contract violations, quarantine
entries, gate overrides, quality scores.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-15

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Application role used by the control plane (env-configurable; default
# matches docker/docker-compose.dev.yml).
APP_ROLE = "datafoundry_app"


def upgrade() -> None:
    dataset_layer = sa.Enum("bronze", "silver", "gold", name="dataset_layer")
    data_classification = sa.Enum(
        "public",
        "internal",
        "confidential",
        "restricted",
        "highly_restricted",
        name="data_classification",
    )
    layer_transition = sa.Enum(
        "ingestion_to_bronze",
        "bronze_to_silver",
        "silver_to_gold",
        "gold_to_consumable",
        name="layer_transition",
    )
    test_category = sa.Enum(
        "schema",
        "type",
        "nullability",
        "uniqueness",
        "completeness",
        "validity",
        "referential_integrity",
        "reconciliation",
        "freshness",
        "volume",
        "distribution",
        "business_rule",
        "security",
        "contract",
        "transformation",
        "statistical",
        name="test_category",
    )
    test_severity = sa.Enum("critical", "error", "warning", "informational", name="test_severity")
    test_result_status = sa.Enum(
        "passed", "failed", "warning", "error", "not_run", name="test_result_status"
    )
    gate_decision = sa.Enum("promote", "block", name="gate_decision")
    overall_status = sa.Enum("passed", "failed", "warning", "error", name="overall_status")
    contract_origin = sa.Enum("explicit", "inferred", name="contract_origin")
    approval_status = sa.Enum("pending", "approved", "rejected", name="approval_status")
    violation_classification = sa.Enum(
        "breaking", "non_breaking", "warning", name="violation_classification"
    )
    override_status = sa.Enum("active", "expired", "revoked", name="override_status")

    for enum in (
        dataset_layer,
        data_classification,
        layer_transition,
        test_category,
        test_severity,
        test_result_status,
        gate_decision,
        overall_status,
        contract_origin,
        approval_status,
        violation_classification,
        override_status,
    ):
        enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "datasets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(63), nullable=False),
        sa.Column("layer", dataset_layer, nullable=False),
        sa.Column(
            "schema_definition",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("owner_identity", sa.String(256), nullable=False),
        sa.Column("classification", data_classification, nullable=False),
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
        sa.UniqueConstraint("name", name="uq_dataset_name"),
        sa.CheckConstraint("name ~ '^[a-z][a-z0-9-]{2,62}$'", name="ck_dataset_name_format"),
    )

    op.create_table(
        "quality_gates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.Uuid(),
            sa.ForeignKey("datasets.id", name="fk_gate_dataset"),
            nullable=False,
        ),
        sa.Column("transition", layer_transition, nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("config_yaml", sa.Text(), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column(
            "environment_overrides",
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "dataset_id", "transition", "config_version", name="uq_gate_version_per_dataset"
        ),
        sa.CheckConstraint("config_version >= 1", name="ck_gate_config_version_positive"),
        sa.CheckConstraint("length(config_hash) = 64", name="ck_gate_config_hash_sha256"),
    )

    op.create_table(
        "quality_tests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "gate_id",
            sa.Uuid(),
            sa.ForeignKey("quality_gates.id", name="fk_test_gate"),
            nullable=False,
        ),
        sa.Column("name", sa.String(63), nullable=False),
        sa.Column("category", test_category, nullable=False),
        sa.Column("severity", test_severity, nullable=False),
        sa.Column(
            "parameters",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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
        sa.UniqueConstraint("gate_id", "name", name="uq_test_name_per_gate"),
    )

    op.create_table(
        "gate_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "gate_id",
            sa.Uuid(),
            sa.ForeignKey("quality_gates.id", name="fk_report_gate"),
            nullable=False,
        ),
        sa.Column(
            "dataset_id",
            sa.Uuid(),
            sa.ForeignKey("datasets.id", name="fk_report_dataset"),
            nullable=False,
        ),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("decision", gate_decision, nullable=False),
        sa.Column("overall_status", overall_status, nullable=False),
        sa.Column("tests_run", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tests_passed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tests_warned", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tests_failed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("quality_score_contribution", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("gate_id", "run_id", name="uq_report_per_gate_run"),
        sa.CheckConstraint("config_version >= 1", name="ck_report_config_version_positive"),
        sa.CheckConstraint("tests_run >= 0", name="ck_report_tests_run_non_negative"),
        sa.CheckConstraint("tests_passed >= 0", name="ck_report_tests_passed_non_negative"),
        sa.CheckConstraint("tests_warned >= 0", name="ck_report_tests_warned_non_negative"),
        sa.CheckConstraint("tests_failed >= 0", name="ck_report_tests_failed_non_negative"),
    )

    op.create_table(
        "test_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "test_id",
            sa.Uuid(),
            sa.ForeignKey("quality_tests.id", name="fk_result_test"),
            nullable=False,
        ),
        sa.Column(
            "report_id",
            sa.Uuid(),
            sa.ForeignKey("gate_reports.id", name="fk_result_report"),
            nullable=False,
        ),
        sa.Column("status", test_result_status, nullable=False),
        sa.Column("measured_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "failed_record_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("failed_record_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "ran_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("test_id", "report_id", name="uq_result_per_test_report"),
        sa.CheckConstraint("failed_record_count >= 0", name="ck_result_failed_count_non_negative"),
    )

    op.create_table(
        "data_contracts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.Uuid(),
            sa.ForeignKey("datasets.id", name="fk_contract_dataset"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "schema_definition",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("origin", contract_origin, nullable=False),
        sa.Column(
            "approval_status",
            approval_status,
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
        sa.UniqueConstraint("dataset_id", "version", name="uq_contract_version_per_dataset"),
        sa.CheckConstraint("version >= 1", name="ck_contract_version_positive"),
    )

    op.create_table(
        "contract_violations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "contract_id",
            sa.Uuid(),
            sa.ForeignKey("data_contracts.id", name="fk_violation_contract"),
            nullable=False,
        ),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("change_description", sa.Text(), nullable=False),
        sa.Column("classification", violation_classification, nullable=False),
        sa.Column("action_taken", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "quarantine_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.Uuid(),
            sa.ForeignKey("datasets.id", name="fk_quarantine_dataset"),
            nullable=False,
        ),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("payload_ref", sa.String(512), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=False),
        sa.Column("failed_test", sa.String(63), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("replay_eligible", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("retention_expiry", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint("attempt_count >= 1", name="ck_quarantine_attempt_positive"),
    )
    op.create_index(
        "ix_quarantine_dataset_quarantined",
        "quarantine_entries",
        ["dataset_id", "quarantined_at"],
    )

    op.create_table(
        "gate_overrides",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "report_id",
            sa.Uuid(),
            sa.ForeignKey("gate_reports.id", name="fk_override_report"),
            nullable=False,
        ),
        sa.Column(
            "dataset_id",
            sa.Uuid(),
            sa.ForeignKey("datasets.id", name="fk_override_dataset"),
            nullable=False,
        ),
        sa.Column("authorising_identity", sa.String(256), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("expiry", sa.DateTime(timezone=True), nullable=False),
        sa.Column("impact_assessment", sa.Text(), nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "status",
            override_status,
            nullable=False,
            server_default=sa.text("'active'"),
        ),
    )
    op.create_index("ix_override_report", "gate_overrides", ["report_id"])

    op.create_table(
        "quality_scores",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.Uuid(),
            sa.ForeignKey("datasets.id", name="fk_score_dataset"),
            nullable=False,
        ),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("history_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint("score >= 0 AND score <= 100", name="ck_score_range"),
    )

    # Append-only quality tables: revoke UPDATE/DELETE from the application
    # role (data-model.md cross-entity invariant 2 — test results, gate
    # reports, contract violations, quarantine entries, overrides, scores are
    # append-only). Role may not exist in every environment (e.g. sqlite-based
    # tests) — guard with a DO block.
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                    REVOKE UPDATE, DELETE ON test_results FROM {APP_ROLE};
                    REVOKE UPDATE, DELETE ON gate_reports FROM {APP_ROLE};
                    REVOKE UPDATE, DELETE ON contract_violations FROM {APP_ROLE};
                    REVOKE UPDATE, DELETE ON quarantine_entries FROM {APP_ROLE};
                    REVOKE UPDATE, DELETE ON gate_overrides FROM {APP_ROLE};
                    REVOKE UPDATE, DELETE ON quality_scores FROM {APP_ROLE};
                    GRANT SELECT, INSERT ON test_results TO {APP_ROLE};
                    GRANT SELECT, INSERT ON gate_reports TO {APP_ROLE};
                    GRANT SELECT, INSERT ON contract_violations TO {APP_ROLE};
                    GRANT SELECT, INSERT ON quarantine_entries TO {APP_ROLE};
                    GRANT SELECT, INSERT ON gate_overrides TO {APP_ROLE};
                    GRANT SELECT, INSERT ON quality_scores TO {APP_ROLE};
                END IF;
            END
            $$;
            """
        )
    )


def downgrade() -> None:
    op.drop_table("quality_scores")
    op.drop_index("ix_override_report", table_name="gate_overrides")
    op.drop_table("gate_overrides")
    op.drop_index("ix_quarantine_dataset_quarantined", table_name="quarantine_entries")
    op.drop_table("quarantine_entries")
    op.drop_table("contract_violations")
    op.drop_table("data_contracts")
    op.drop_table("test_results")
    op.drop_table("gate_reports")
    op.drop_table("quality_tests")
    op.drop_table("quality_gates")
    op.drop_table("datasets")
    for name in (
        "override_status",
        "violation_classification",
        "approval_status",
        "contract_origin",
        "overall_status",
        "gate_decision",
        "test_result_status",
        "test_severity",
        "test_category",
        "layer_transition",
        "data_classification",
        "dataset_layer",
    ):
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)
