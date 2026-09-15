"""SQLAlchemy 2 ORM models (T013) per data-model.md.

Entities: Platform, PlatformConfigVersion, DeploymentRun, DeploymentStep,
HealthCheckResult, AuditRecord.

Key invariants enforced at the schema level:
- Platform uniqueness: ``(provider, cloud_scope_id, name)`` (FR-013, R-12).
- One active run per platform: partial unique index on DeploymentRun
  ``WHERE status IN ('queued','running','paused')``.
- AuditRecord is append-only: the migration revokes UPDATE/DELETE from the
  application role (T014).
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

#: JSONB on PostgreSQL; plain JSON elsewhere (SQLite test harness).
JSONVariant = JSONB().with_variant(JSON(), "sqlite")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


# -- enums -------------------------------------------------------------------


class Provider(enum.StrEnum):
    aws = "aws"
    gcp = "gcp"


class EnvironmentType(enum.StrEnum):
    development = "development"
    test = "test"
    uat = "uat"
    production = "production"


class PlatformStatus(enum.StrEnum):
    pending = "pending"
    deploying = "deploying"
    ready = "ready"
    degraded = "degraded"
    failed = "failed"
    destroying = "destroying"
    destroyed = "destroyed"


class RunType(enum.StrEnum):
    deploy = "deploy"
    update = "update"
    retry = "retry"
    rollback = "rollback"
    destroy = "destroy"


class RunStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    paused = "paused"
    succeeded = "succeeded"
    failed = "failed"
    rolled_back = "rolled_back"


class StepStatus(enum.StrEnum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"


class ConfigSource(enum.StrEnum):
    api = "api"
    cli = "cli"
    git = "git"


class HealthStatus(enum.StrEnum):
    healthy = "healthy"
    unhealthy = "unhealthy"
    unknown = "unknown"


# -- quality enums (feature 004) ---------------------------------------------


class LayerTransition(enum.StrEnum):
    ingestion_to_bronze = "ingestion_to_bronze"
    bronze_to_silver = "bronze_to_silver"
    silver_to_gold = "silver_to_gold"
    gold_to_consumable = "gold_to_consumable"


class TestCategory(enum.StrEnum):
    schema = "schema"
    type = "type"
    nullability = "nullability"
    uniqueness = "uniqueness"
    completeness = "completeness"
    validity = "validity"
    referential_integrity = "referential_integrity"
    reconciliation = "reconciliation"
    freshness = "freshness"
    volume = "volume"
    distribution = "distribution"
    business_rule = "business_rule"
    security = "security"
    contract = "contract"
    transformation = "transformation"
    statistical = "statistical"


class TestSeverity(enum.StrEnum):
    critical = "critical"
    error = "error"
    warning = "warning"
    informational = "informational"


class TestResultStatus(enum.StrEnum):
    passed = "passed"
    failed = "failed"
    warning = "warning"
    error = "error"
    not_run = "not_run"


class GateDecision(enum.StrEnum):
    promote = "promote"
    block = "block"


class OverallStatus(enum.StrEnum):
    passed = "passed"
    failed = "failed"
    warning = "warning"
    error = "error"


class ContractOrigin(enum.StrEnum):
    explicit = "explicit"
    inferred = "inferred"


class ApprovalStatus(enum.StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ViolationClassification(enum.StrEnum):
    breaking = "breaking"
    non_breaking = "non_breaking"
    warning = "warning"


class OverrideStatus(enum.StrEnum):
    active = "active"
    expired = "expired"
    revoked = "revoked"


class DatasetLayer(enum.StrEnum):
    bronze = "bronze"
    silver = "silver"
    gold = "gold"


class DataClassification(enum.StrEnum):
    public = "public"
    internal = "internal"
    confidential = "confidential"
    restricted = "restricted"
    highly_restricted = "highly_restricted"


# -- entities ------------------------------------------------------------------


class Platform(Base):
    __tablename__ = "platforms"
    __table_args__ = (
        UniqueConstraint("provider", "cloud_scope_id", "name", name="uq_platform_scope_name"),
        # Portable form of ^[a-z][a-z0-9-]{2,62}$ (the Postgres migration uses
        # the regex operator; this expression also compiles on SQLite so the
        # test harness can create_all). Full regex validation lives in the
        # Pydantic schema (config/schema.py).
        CheckConstraint(
            "length(name) BETWEEN 3 AND 63 AND name = lower(name) "
            "AND substr(name, 1, 1) BETWEEN 'a' AND 'z'",
            name="ck_platform_name_format",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(63), nullable=False)
    provider: Mapped[Provider] = mapped_column(Enum(Provider, name="provider"), nullable=False)
    cloud_scope_id: Mapped[str] = mapped_column(String(128), nullable=False)
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    environment_type: Mapped[EnvironmentType] = mapped_column(
        Enum(EnvironmentType, name="environment_type"), nullable=False
    )
    status: Mapped[PlatformStatus] = mapped_column(
        Enum(PlatformStatus, name="platform_status"),
        nullable=False,
        default=PlatformStatus.pending,
    )
    owner_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    current_config_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "platform_config_versions.id", use_alter=True, name="fk_platform_current_config"
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    config_versions: Mapped[list[PlatformConfigVersion]] = relationship(
        back_populates="platform",
        foreign_keys="PlatformConfigVersion.platform_id",
        order_by="PlatformConfigVersion.version",
    )
    runs: Mapped[list[DeploymentRun]] = relationship(back_populates="platform")
    health_results: Mapped[list[HealthCheckResult]] = relationship(back_populates="platform")
    audit_records: Mapped[list[AuditRecord]] = relationship(back_populates="platform")


class PlatformConfigVersion(Base):
    __tablename__ = "platform_config_versions"
    __table_args__ = (
        UniqueConstraint("platform_id", "version", name="uq_config_version_per_platform"),
        CheckConstraint("version >= 1", name="ck_config_version_positive"),
        CheckConstraint("length(config_hash) = 64", name="ck_config_hash_sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    platform_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platforms.id", name="fk_config_version_platform"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Validated config YAML — no plaintext secrets (SC-006), secret-scanned
    #: before persist.
    config_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[ConfigSource] = mapped_column(
        Enum(ConfigSource, name="config_source"), nullable=False
    )
    git_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    platform: Mapped[Platform | None] = relationship(
        back_populates="config_versions", foreign_keys=[platform_id]
    )
    runs: Mapped[list[DeploymentRun]] = relationship(back_populates="config_version")


class DeploymentRun(Base):
    __tablename__ = "deployment_runs"
    __table_args__ = (
        # One active run per platform (data-model.md invariant 3, R-12).
        Index(
            "uq_one_active_run_per_platform",
            "platform_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running', 'paused')"),
            sqlite_where=text("status IN ('queued', 'running', 'paused')"),
        ),
        UniqueConstraint("terraform_workspace", name="uq_run_workspace"),
        UniqueConstraint("idempotency_key", name="uq_run_idempotency_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    platform_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platforms.id", name="fk_run_platform"), nullable=False
    )
    config_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform_config_versions.id", name="fk_run_config_version"), nullable=False
    )
    run_type: Mapped[RunType] = mapped_column(Enum(RunType, name="run_type"), nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, name="run_status"), nullable=False, default=RunStatus.queued
    )
    initiated_by: Mapped[str] = mapped_column(String(256), nullable=False)
    approval_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terraform_workspace: Mapped[str] = mapped_column(String(256), nullable=False)
    failure_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Client-supplied Idempotency-Key (deployment-api.md cross-cutting
    #: rules): replays of POST /platforms return the original run.
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    platform: Mapped[Platform] = relationship(back_populates="runs")
    config_version: Mapped[PlatformConfigVersion] = relationship(back_populates="runs")
    steps: Mapped[list[DeploymentStep]] = relationship(
        back_populates="run", order_by="DeploymentStep.position"
    )


class DeploymentStep(Base):
    __tablename__ = "deployment_steps"
    __table_args__ = (
        UniqueConstraint("run_id", "position", name="uq_step_position_per_run"),
        CheckConstraint("position >= 1", name="ck_step_position_positive"),
        CheckConstraint("attempt >= 0", name="ck_step_attempt_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("deployment_runs.id", name="fk_step_run"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    capability: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[StepStatus] = mapped_column(
        Enum(StepStatus, name="step_status"), nullable=False, default=StepStatus.pending
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Human-readable failure reason (US1-AC3) — secret-scanned before write.
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    terraform_module: Mapped[str | None] = mapped_column(String(256), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[DeploymentRun] = relationship(back_populates="steps")


class HealthCheckResult(Base):
    __tablename__ = "health_check_results"
    __table_args__ = (Index("ix_health_platform_component", "platform_id", "component"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    platform_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platforms.id", name="fk_health_platform"), nullable=False
    )
    component: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[HealthStatus] = mapped_column(
        Enum(HealthStatus, name="health_status"), nullable=False
    )
    last_check_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("deployment_runs.id", name="fk_health_run"), nullable=True
    )

    platform: Mapped[Platform] = relationship(back_populates="health_results")


class AuditRecord(Base):
    """Append-only audit log (FR-014). No UPDATE/DELETE for the app role."""

    __tablename__ = "audit_records"
    __table_args__ = (Index("ix_audit_platform_occurred", "platform_id", "occurred_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    platform_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platforms.id", name="fk_audit_platform"), nullable=True
    )
    actor: Mapped[str] = mapped_column(String(256), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    #: Secret-scanned JSON payload (SC-006 invariant 1).
    payload: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)

    platform: Mapped[Platform | None] = relationship(back_populates="audit_records")


# -- feature 003 Dataset (stub) ----------------------------------------------
#
# Feature 003 (medallion-processing) owns the full Dataset entity. This minimal
# model provides the FK target that feature 004 quality entities reference and
# that the test harness seeds; feature 003 will extend it with the remaining
# fields (platform_id, steward, domain, description, quality_score,
# refresh_metadata) in its own migration.


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint("name", name="uq_dataset_name"),
        CheckConstraint(
            "length(name) BETWEEN 3 AND 63 AND name = lower(name) "
            "AND substr(name, 1, 1) BETWEEN 'a' AND 'z'",
            name="ck_dataset_name_format",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(63), nullable=False)
    layer: Mapped[DatasetLayer] = mapped_column(
        Enum(DatasetLayer, name="dataset_layer"), nullable=False
    )
    schema_definition: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)
    owner_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    classification: Mapped[DataClassification] = mapped_column(
        Enum(DataClassification, name="data_classification"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    gates: Mapped[list[QualityGate]] = relationship(back_populates="dataset")
    contracts: Mapped[list[DataContract]] = relationship(back_populates="dataset")
    quarantine_entries: Mapped[list[QuarantineEntry]] = relationship(back_populates="dataset")
    overrides: Mapped[list[GateOverride]] = relationship(back_populates="dataset")
    scores: Mapped[list[QualityScore]] = relationship(back_populates="dataset")


# -- feature 004 quality entities ---------------------------------------------


class QualityGate(Base):
    """The test set bound to a layer transition for a dataset (FR-001)."""

    __tablename__ = "quality_gates"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id", "transition", "config_version", name="uq_gate_version_per_dataset"
        ),
        CheckConstraint("config_version >= 1", name="ck_gate_config_version_positive"),
        CheckConstraint("length(config_hash) = 64", name="ck_gate_config_hash_sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", name="fk_gate_dataset"), nullable=False
    )
    transition: Mapped[LayerTransition] = mapped_column(
        Enum(LayerTransition, name="layer_transition"), nullable=False
    )
    config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Canonical gate definition — secret-scanned before persist (SC-007).
    config_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    environment_overrides: Mapped[dict[str, Any]] = mapped_column(
        JSONVariant, nullable=False, default=dict
    )
    created_by: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    dataset: Mapped[Dataset] = relationship(back_populates="gates")
    tests: Mapped[list[QualityTest]] = relationship(
        back_populates="gate", order_by="QualityTest.name"
    )
    reports: Mapped[list[GateReport]] = relationship(back_populates="gate")


class QualityTest(Base):
    """A single quality rule (spec Key Entity, FR-003/FR-004)."""

    __tablename__ = "quality_tests"
    __table_args__ = (UniqueConstraint("gate_id", "name", name="uq_test_name_per_gate"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    gate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("quality_gates.id", name="fk_test_gate"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(63), nullable=False)
    category: Mapped[TestCategory] = mapped_column(
        Enum(TestCategory, name="test_category"), nullable=False
    )
    severity: Mapped[TestSeverity] = mapped_column(
        Enum(TestSeverity, name="test_severity"), nullable=False
    )
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)
    owner_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    gate: Mapped[QualityGate] = relationship(back_populates="tests")
    results: Mapped[list[TestResult]] = relationship(back_populates="test")


class TestResult(Base):
    """One test's outcome in one run (spec Key Entity, FR-013)."""

    __tablename__ = "test_results"
    __table_args__ = (
        UniqueConstraint("test_id", "report_id", name="uq_result_per_test_report"),
        CheckConstraint("failed_record_count >= 0", name="ck_result_failed_count_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    test_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("quality_tests.id", name="fk_result_test"), nullable=False
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gate_reports.id", name="fk_result_report"), nullable=False
    )
    status: Mapped[TestResultStatus] = mapped_column(
        Enum(TestResultStatus, name="test_result_status"), nullable=False
    )
    measured_value: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
    failed_record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_record_refs: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ran_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    test: Mapped[QualityTest] = relationship(back_populates="results")
    report: Mapped[GateReport] = relationship(back_populates="results")


class GateReport(Base):
    """The aggregate decision for a run (spec Key Entity, FR-001/FR-013)."""

    __tablename__ = "gate_reports"
    __table_args__ = (
        UniqueConstraint("gate_id", "run_id", name="uq_report_per_gate_run"),
        CheckConstraint("config_version >= 1", name="ck_report_config_version_positive"),
        CheckConstraint("tests_run >= 0", name="ck_report_tests_run_non_negative"),
        CheckConstraint("tests_passed >= 0", name="ck_report_tests_passed_non_negative"),
        CheckConstraint("tests_warned >= 0", name="ck_report_tests_warned_non_negative"),
        CheckConstraint("tests_failed >= 0", name="ck_report_tests_failed_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    gate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("quality_gates.id", name="fk_report_gate"), nullable=False
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", name="fk_report_dataset"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[GateDecision] = mapped_column(
        Enum(GateDecision, name="gate_decision"), nullable=False
    )
    overall_status: Mapped[OverallStatus] = mapped_column(
        Enum(OverallStatus, name="overall_status"), nullable=False
    )
    tests_run: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tests_passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tests_warned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tests_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_score_contribution: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    gate: Mapped[QualityGate] = relationship(back_populates="reports")
    dataset: Mapped[Dataset] = relationship()
    results: Mapped[list[TestResult]] = relationship(back_populates="report")
    overrides: Mapped[list[GateOverride]] = relationship(back_populates="report")


class DataContract(Base):
    """Schema agreement for a dataset (spec Key Entity, FR-006/FR-007)."""

    __tablename__ = "data_contracts"
    __table_args__ = (
        UniqueConstraint("dataset_id", "version", name="uq_contract_version_per_dataset"),
        CheckConstraint("version >= 1", name="ck_contract_version_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", name="fk_contract_dataset"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_definition: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)
    origin: Mapped[ContractOrigin] = mapped_column(
        Enum(ContractOrigin, name="contract_origin"), nullable=False
    )
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, name="approval_status"),
        nullable=False,
        default=ApprovalStatus.pending,
    )
    created_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    dataset: Mapped[Dataset] = relationship(back_populates="contracts")
    violations: Mapped[list[ContractViolation]] = relationship(back_populates="contract")


class ContractViolation(Base):
    """A detected deviation from a contract (spec Key Entity, FR-006)."""

    __tablename__ = "contract_violations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_contracts.id", name="fk_violation_contract"), nullable=False
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    change_description: Mapped[str] = mapped_column(Text, nullable=False)
    classification: Mapped[ViolationClassification] = mapped_column(
        Enum(ViolationClassification, name="violation_classification"), nullable=False
    )
    action_taken: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    contract: Mapped[DataContract] = relationship(back_populates="violations")


class QuarantineEntry(Base):
    """A rejected record/file with full failure context (spec Key Entity)."""

    __tablename__ = "quarantine_entries"
    __table_args__ = (
        Index("ix_quarantine_dataset_quarantined", "dataset_id", "quarantined_at"),
        CheckConstraint("attempt_count >= 1", name="ck_quarantine_attempt_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", name="fk_quarantine_dataset"), nullable=False
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    payload_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    failure_reason: Mapped[str] = mapped_column(Text, nullable=False)
    failed_test: Mapped[str | None] = mapped_column(String(63), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    replay_eligible: Mapped[bool] = mapped_column(nullable=False, default=True)
    retention_expiry: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quarantined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    #: Secret-scanned JSON payload (pipeline id, source, error details).
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)

    dataset: Mapped[Dataset] = relationship(back_populates="quarantine_entries")


class GateOverride(Base):
    """A granted bypass of a blocked gate (spec Key Entity, FR-011/FR-012)."""

    __tablename__ = "gate_overrides"
    __table_args__ = (Index("ix_override_report", "report_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gate_reports.id", name="fk_override_report"), nullable=False
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", name="fk_override_dataset"), nullable=False
    )
    authorising_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    expiry: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Secret-scanned impact assessment (SC-007).
    impact_assessment: Mapped[str] = mapped_column(Text, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    status: Mapped[OverrideStatus] = mapped_column(
        Enum(OverrideStatus, name="override_status"),
        nullable=False,
        default=OverrideStatus.active,
    )

    report: Mapped[GateReport] = relationship(back_populates="overrides")
    dataset: Mapped[Dataset] = relationship(back_populates="overrides")


class QualityScore(Base):
    """A dataset's current quality measure (spec Key Entity, FR-014)."""

    __tablename__ = "quality_scores"
    __table_args__ = (CheckConstraint("score >= 0 AND score <= 100", name="ck_score_range"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", name="fk_score_dataset"), nullable=False
    )
    score: Mapped[float] = mapped_column(nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    history_json: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)

    dataset: Mapped[Dataset] = relationship(back_populates="scores")


__all__ = [
    "ApprovalStatus",
    "AuditRecord",
    "Base",
    "ConfigSource",
    "ContractOrigin",
    "ContractViolation",
    "DataClassification",
    "DataContract",
    "Dataset",
    "DatasetLayer",
    "DeploymentRun",
    "DeploymentStep",
    "EnvironmentType",
    "GateDecision",
    "GateOverride",
    "GateReport",
    "HealthCheckResult",
    "HealthStatus",
    "LayerTransition",
    "OverallStatus",
    "OverrideStatus",
    "Platform",
    "PlatformConfigVersion",
    "PlatformStatus",
    "Provider",
    "QualityGate",
    "QualityScore",
    "QualityTest",
    "QuarantineEntry",
    "RunStatus",
    "RunType",
    "StepStatus",
    "TestCategory",
    "TestResult",
    "TestResultStatus",
    "TestSeverity",
    "ViolationClassification",
]
