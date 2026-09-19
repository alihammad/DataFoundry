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


# -- security enums (feature 005) ---------------------------------------------


class SecurityLevel(enum.StrEnum):
    public = "public"
    internal = "internal"
    confidential = "confidential"
    restricted = "restricted"
    highly_restricted = "highly_restricted"


class ProtectionMechanism(enum.StrEnum):
    encrypt = "encrypt"
    tokenise = "tokenise"
    mask = "mask"
    hash = "hash"
    redact = "redact"
    pseudonymise = "pseudonymise"


class KmsProvider(enum.StrEnum):
    aws_kms = "aws_kms"
    gcp_cloud_kms = "gcp_cloud_kms"


class KeyLifecycleState(enum.StrEnum):
    active = "active"
    disabled = "disabled"
    revoked = "revoked"


class AuditResult(enum.StrEnum):
    success = "success"
    denied = "denied"
    failed = "failed"


class AccessOutcome(enum.StrEnum):
    granted = "granted"
    denied = "denied"


class VerificationResult(enum.StrEnum):
    verified = "verified"
    failed = "failed"
    not_verified = "not_verified"


# -- processing enums (feature 003) -------------------------------------------


class PromotionState(enum.StrEnum):
    ingested = "ingested"
    ingestion_validated = "ingestion_validated"
    bronze = "bronze"
    bronze_validated = "bronze_validated"
    silver = "silver"
    silver_validated = "silver_validated"
    gold = "gold"
    gold_validated = "gold_validated"
    consumable = "consumable"
    blocked = "blocked"


# -- ingestion enums (feature 002) --------------------------------------------


class SourceType(enum.StrEnum):
    postgres = "postgres"
    sqlserver = "sqlserver"
    object_storage = "object_storage"


class ConnectionState(enum.StrEnum):
    untested = "untested"
    ok = "ok"
    failed = "failed"


class IngestionMode(enum.StrEnum):
    full = "full"
    incremental = "incremental"


class TargetZone(enum.StrEnum):
    bronze = "bronze"


class PipelineState(enum.StrEnum):
    active = "active"
    paused = "paused"


class BatchStatus(enum.StrEnum):
    ingesting = "ingesting"
    ingested = "ingested"
    ingestion_validated = "ingestion_validated"
    failed = "failed"
    quarantined = "quarantined"


class IngestionRunStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    paused = "paused"
    succeeded = "succeeded"
    failed = "failed"


class RunTrigger(enum.StrEnum):
    scheduled = "scheduled"
    manual = "manual"
    retry = "retry"


class RunOutcome(enum.StrEnum):
    success = "success"
    partial = "partial"
    failed = "failed"


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
        UniqueConstraint("platform_id", "name", name="uq_dataset_platform_name"),
        CheckConstraint(
            "length(name) BETWEEN 3 AND 63 AND name = lower(name) "
            "AND substr(name, 1, 1) BETWEEN 'a' AND 'z'",
            name="ck_dataset_name_format",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    #: Owning platform. Nullable for backward compatibility with feature 004
    #: datasets seeded before platform scoping; F003 always sets it.
    platform_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platforms.id", name="fk_dataset_platform"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(63), nullable=False)
    layer: Mapped[DatasetLayer] = mapped_column(
        Enum(DatasetLayer, name="dataset_layer"), nullable=False
    )
    schema_definition: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)
    owner_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    steward_identity: Mapped[str | None] = mapped_column(String(256), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(63), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    classification: Mapped[DataClassification] = mapped_column(
        Enum(DataClassification, name="data_classification"), nullable=False
    )
    quality_score: Mapped[float | None] = mapped_column(nullable=True)
    refresh_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
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
    versions: Mapped[list[DatasetVersion]] = relationship(back_populates="dataset")
    promotion_states: Mapped[list[PromotionStateRow]] = relationship(back_populates="dataset")
    lineage_out: Mapped[list[LineageLink]] = relationship(
        back_populates="source_dataset", foreign_keys="LineageLink.source_dataset_id"
    )
    lineage_in: Mapped[list[LineageLink]] = relationship(
        back_populates="target_dataset", foreign_keys="LineageLink.target_dataset_id"
    )
    catalog_metadata: Mapped[list[CatalogMetadata]] = relationship(back_populates="dataset")


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


# -- feature 003 processing entities ------------------------------------------


class Transformation(Base):
    """A version-controlled definition converting input to output (FR-005)."""

    __tablename__ = "transformations"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_transformation_name_version"),
        CheckConstraint("version >= 1", name="ck_transformation_version_positive"),
        CheckConstraint(
            "length(name) BETWEEN 3 AND 63 AND name = lower(name) "
            "AND substr(name, 1, 1) BETWEEN 'a' AND 'z'",
            name="ck_transformation_name_format",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(63), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_layer: Mapped[DatasetLayer] = mapped_column(
        Enum(DatasetLayer, name="dataset_layer"), nullable=False
    )
    target_layer: Mapped[DatasetLayer] = mapped_column(
        Enum(DatasetLayer, name="dataset_layer"), nullable=False
    )
    #: Secret-scanned declarative definition (transformation-schema.md).
    logic_definition: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)
    logic_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dedup_keys: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
    reconciliation_tolerance: Mapped[float | None] = mapped_column(nullable=True)
    owner_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    #: GitOps provenance (FR-005): ``source`` (git|api) + ``git_ref``.
    source: Mapped[ConfigSource] = mapped_column(
        Enum(ConfigSource, name="config_source"), nullable=False, default=ConfigSource.api
    )
    git_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    versions: Mapped[list[DatasetVersion]] = relationship(back_populates="transformation")


class DatasetVersion(Base):
    """An immutable snapshot of a dataset produced by a run (FR-012)."""

    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "version", name="uq_dataset_version"),
        CheckConstraint("version >= 1", name="ck_dataset_version_positive"),
        CheckConstraint("record_count >= 0", name="ck_dataset_version_records_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", name="fk_version_dataset"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    transformation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transformations.id", name="fk_version_transformation"), nullable=True
    )
    #: ``{input_dataset: version}`` (FR-017).
    input_versions: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
    table_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quarantined_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gate_report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gate_reports.id", name="fk_version_gate_report"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    dataset: Mapped[Dataset] = relationship(back_populates="versions")
    transformation: Mapped[Transformation | None] = relationship(back_populates="versions")


class PromotionStateRow(Base):
    """A dataset's position in the promotion state machine (FR-007)."""

    __tablename__ = "promotion_states"
    __table_args__ = (UniqueConstraint("dataset_id", name="uq_promotion_state_dataset"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", name="fk_promotion_dataset"), nullable=False
    )
    state: Mapped[PromotionState] = mapped_column(
        Enum(PromotionState, name="promotion_state"), nullable=False
    )
    gate_report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gate_reports.id", name="fk_promotion_gate_report"), nullable=True
    )
    transitioned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    dataset: Mapped[Dataset] = relationship(back_populates="promotion_states")


class LineageLink(Base):
    """A directed relationship between datasets (FR-015, SC-006)."""

    __tablename__ = "lineage_links"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    source_dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", name="fk_lineage_source"), nullable=False
    )
    target_dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", name="fk_lineage_target"), nullable=False
    )
    transformation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transformations.id", name="fk_lineage_transformation"), nullable=True
    )
    transformation_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    source_dataset: Mapped[Dataset] = relationship(
        back_populates="lineage_out", foreign_keys=[source_dataset_id]
    )
    target_dataset: Mapped[Dataset] = relationship(
        back_populates="lineage_in", foreign_keys=[target_dataset_id]
    )


class CatalogMetadata(Base):
    """Catalog registration for a dataset (FR-014, SC-002)."""

    __tablename__ = "catalog_metadata"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", name="fk_catalog_dataset"), nullable=False
    )
    catalog_endpoint: Mapped[str] = mapped_column(String(256), nullable=False)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    #: Secret-scanned owner/steward/domain/description/classification/quality/
    #: lineage/refresh metadata (FR-014).
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)

    dataset: Mapped[Dataset] = relationship(back_populates="catalog_metadata")


# -- feature 002 ingestion entities -------------------------------------------


class DataSource(Base):
    """A configured origin of data (spec Key Entity, FR-005)."""

    __tablename__ = "data_sources"
    __table_args__ = (
        UniqueConstraint("platform_id", "name", name="uq_source_name_per_platform"),
        CheckConstraint(
            "length(name) BETWEEN 3 AND 63 AND name = lower(name) "
            "AND substr(name, 1, 1) BETWEEN 'a' AND 'z'",
            name="ck_source_name_format",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    platform_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platforms.id", name="fk_source_platform"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(63), nullable=False)
    type: Mapped[SourceType] = mapped_column(Enum(SourceType, name="source_type"), nullable=False)
    #: Secret-scanned connection reference (host/database or location); the
    #: credential is always a ``secretRef``, never a value (FR-005, SC-007).
    config_ref: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)
    owner_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    connection_state: Mapped[ConnectionState] = mapped_column(
        Enum(ConnectionState, name="connection_state"),
        nullable=False,
        default=ConnectionState.untested,
    )
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    platform: Mapped[Platform] = relationship()
    configs: Mapped[list[IngestionConfig]] = relationship(back_populates="source")
    contracts: Mapped[list[SourceContract]] = relationship(back_populates="source")
    pipelines: Mapped[list[IngestionPipeline]] = relationship(back_populates="source")
    quarantine_records: Mapped[list[QuarantineRecord]] = relationship(back_populates="source")


class IngestionConfig(Base):
    """Per-source definition (spec Key Entity, FR-017)."""

    __tablename__ = "ingestion_configs"
    __table_args__ = (
        UniqueConstraint("source_id", "version", name="uq_ingestion_config_version"),
        CheckConstraint("version >= 1", name="ck_ingestion_config_version_positive"),
        CheckConstraint("length(config_hash) = 64", name="ck_ingestion_config_hash_sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", name="fk_ingestion_config_source"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Canonical YAML — no plaintext secrets (SC-007), secret-scanned before persist.
    config_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, name="source_type"), nullable=False
    )
    #: Selected tables (with cursor column) or file pattern.
    selected_objects: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)
    ingestion_mode: Mapped[IngestionMode] = mapped_column(
        Enum(IngestionMode, name="ingestion_mode"), nullable=False
    )
    schedule: Mapped[str | None] = mapped_column(String(128), nullable=True)
    target_zone: Mapped[TargetZone] = mapped_column(
        Enum(TargetZone, name="target_zone"), nullable=False, default=TargetZone.bronze
    )
    #: reconciliation tolerance, contract mode (FR-009).
    validation_settings: Mapped[dict[str, Any]] = mapped_column(
        JSONVariant, nullable=False, default=dict
    )
    created_by: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    source: Mapped[DataSource] = relationship(back_populates="configs")
    pipelines: Mapped[list[IngestionPipeline]] = relationship(back_populates="config")


class SourceContract(Base):
    """Expected schema agreement for a source object (spec Key Entity, FR-010)."""

    __tablename__ = "source_contracts"
    __table_args__ = (
        UniqueConstraint("source_id", "object_name", name="uq_contract_per_source_object"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", name="fk_source_contract_source"), nullable=False
    )
    object_name: Mapped[str] = mapped_column(String(256), nullable=False)
    #: ``{column: {type, nullable}}`` (contracts/source-contract-schema.md).
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

    source: Mapped[DataSource] = relationship(back_populates="contracts")


class IngestionPipeline(Base):
    """Executable unit created from an IngestionConfig (spec Key Entity)."""

    __tablename__ = "ingestion_pipelines"
    __table_args__ = (
        CheckConstraint(
            "length(name) BETWEEN 3 AND 63 AND name = lower(name) "
            "AND substr(name, 1, 1) BETWEEN 'a' AND 'z'",
            name="ck_pipeline_name_format",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    config_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingestion_configs.id", name="fk_pipeline_config"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", name="fk_pipeline_source"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(63), nullable=False)
    state: Mapped[PipelineState] = mapped_column(
        Enum(PipelineState, name="pipeline_state"), nullable=False, default=PipelineState.active
    )
    schedule: Mapped[str | None] = mapped_column(String(128), nullable=True)
    owner_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    #: Next scheduled run time (UTC) — advanced on each scheduled dispatch
    #: (R-04) so a restart does not re-fire an elapsed run.
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: ``{object: cursor_value}`` — advanced only on validated commit (R-06).
    high_watermarks: Mapped[dict[str, Any]] = mapped_column(
        JSONVariant, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    config: Mapped[IngestionConfig] = relationship(back_populates="pipelines")
    source: Mapped[DataSource] = relationship(back_populates="pipelines")
    runs: Mapped[list[IngestionRun]] = relationship(back_populates="pipeline")
    batches: Mapped[list[IngestionBatch]] = relationship(back_populates="pipeline")
    quarantine_records: Mapped[list[QuarantineRecord]] = relationship(back_populates="pipeline")


class IngestionBatch(Base):
    """One unit of ingested data (spec Key Entity, FR-008)."""

    __tablename__ = "ingestion_batches"
    __table_args__ = (
        CheckConstraint("record_count >= 0", name="ck_batch_record_count_non_negative"),
        CheckConstraint("length(checksum) = 64", name="ck_batch_checksum_sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingestion_runs.id", name="fk_batch_run"), nullable=False
    )
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingestion_pipelines.id", name="fk_batch_pipeline"), nullable=False
    )
    source_object: Mapped[str] = mapped_column(String(256), nullable=False)
    source_system: Mapped[str] = mapped_column(String(256), nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[BatchStatus] = mapped_column(
        Enum(BatchStatus, name="batch_status"), nullable=False, default=BatchStatus.ingesting
    )
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Secret-scanned full batch metadata (SC-003).
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)

    run: Mapped[IngestionRun] = relationship(back_populates="batches")
    pipeline: Mapped[IngestionPipeline] = relationship(back_populates="batches")
    quarantine_records: Mapped[list[QuarantineRecord]] = relationship(back_populates="batch")


class IngestionRun(Base):
    """One pipeline execution (spec Key Entity, FR-013)."""

    __tablename__ = "ingestion_runs"
    __table_args__ = (
        # One active run per pipeline (data-model.md invariant 5, R-10).
        Index(
            "uq_one_active_ingestion_run_per_pipeline",
            "pipeline_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running', 'paused')"),
            sqlite_where=text("status IN ('queued', 'running', 'paused')"),
        ),
        CheckConstraint("records_processed >= 0", name="ck_run_records_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingestion_pipelines.id", name="fk_run_pipeline"), nullable=False
    )
    trigger: Mapped[RunTrigger] = mapped_column(
        Enum(RunTrigger, name="run_trigger"), nullable=False
    )
    status: Mapped[IngestionRunStatus] = mapped_column(
        Enum(IngestionRunStatus, name="ingestion_run_status"),
        nullable=False,
        default=IngestionRunStatus.queued,
    )
    retry_of: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingestion_runs.id", name="fk_run_retry_of"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    records_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outcome: Mapped[RunOutcome | None] = mapped_column(
        Enum(RunOutcome, name="run_outcome"), nullable=True
    )
    #: Redacted failure reason (FR-013, US1-AC4).
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    pipeline: Mapped[IngestionPipeline] = relationship(back_populates="runs")
    batches: Mapped[list[IngestionBatch]] = relationship(back_populates="run")


class QuarantineRecord(Base):
    """A rejected file/record/batch with full context (spec Key Entity, FR-006)."""

    __tablename__ = "quarantine_records"
    __table_args__ = (Index("ix_quarantine_source_quarantined", "source_id", "quarantined_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingestion_pipelines.id", name="fk_quarantine_pipeline"), nullable=False
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingestion_batches.id", name="fk_quarantine_batch"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", name="fk_quarantine_source"), nullable=False
    )
    payload_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    failure_reason: Mapped[str] = mapped_column(Text, nullable=False)
    failed_check: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[TestSeverity] = mapped_column(
        Enum(TestSeverity, name="test_severity"), nullable=False
    )
    quarantined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    #: Secret-scanned original reference + error details (SC-007).
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)

    pipeline: Mapped[IngestionPipeline] = relationship(back_populates="quarantine_records")
    batch: Mapped[IngestionBatch] = relationship(back_populates="quarantine_records")
    source: Mapped[DataSource] = relationship(back_populates="quarantine_records")


# -- feature 005 security entities --------------------------------------------


class Classification(Base):
    """A dataset/column sensitivity level (FR-001, FR-020)."""

    __tablename__ = "classifications"
    __table_args__ = (
        UniqueConstraint("dataset_id", "column", name="uq_classification_dataset_column"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", name="fk_classification_dataset"), nullable=False
    )
    level: Mapped[SecurityLevel] = mapped_column(
        Enum(SecurityLevel, name="security_level"), nullable=False
    )
    column: Mapped[str | None] = mapped_column(String(63), nullable=True)
    policy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("protection_policies.id", name="fk_classification_policy"), nullable=False
    )
    changed_by: Mapped[str] = mapped_column(String(256), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    previous_level: Mapped[SecurityLevel | None] = mapped_column(
        Enum(SecurityLevel, name="security_level"), nullable=True
    )

    dataset: Mapped[Dataset] = relationship()


class ProtectionPolicy(Base):
    """The enforceable rule set for a classification (FR-002, FR-003)."""

    __tablename__ = "protection_policies"
    __table_args__ = (UniqueConstraint("name", name="uq_protection_policy_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(63), nullable=False)
    classification: Mapped[SecurityLevel] = mapped_column(
        Enum(SecurityLevel, name="security_level"), nullable=False
    )
    mechanism: Mapped[ProtectionMechanism] = mapped_column(
        Enum(ProtectionMechanism, name="protection_mechanism"), nullable=False
    )
    key_ref_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("key_references.id", name="fk_policy_key_ref"), nullable=True
    )
    token_service_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    authorised_roles: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)
    detokenise_roles: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
    masking_rule: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
    created_by: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class KeyReference(Base):
    """A cryptographic key reference in an approved KMS (FR-008, FR-009)."""

    __tablename__ = "key_references"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    kms: Mapped[KmsProvider] = mapped_column(Enum(KmsProvider, name="kms_provider"), nullable=False)
    key_id: Mapped[str] = mapped_column(String(256), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lifecycle_state: Mapped[KeyLifecycleState] = mapped_column(
        Enum(KeyLifecycleState, name="key_lifecycle_state"),
        nullable=False,
        default=KeyLifecycleState.active,
    )
    rotation_schedule: Mapped[str | None] = mapped_column(String(64), nullable=True)
    usage_permissions: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class TokenReference(Base):
    """A surrogate for a sensitive value held in the token service (FR-011)."""

    __tablename__ = "token_references"
    __table_args__ = (
        UniqueConstraint("dataset_id", "column", "token", name="uq_token_dataset_column_token"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", name="fk_token_dataset"), nullable=False
    )
    column: Mapped[str] = mapped_column(String(63), nullable=False)
    token: Mapped[str] = mapped_column(String(256), nullable=False)
    original_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    deterministic: Mapped[bool] = mapped_column(nullable=False, default=False)
    token_service_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class SecurityAuditRecord(Base):
    """One security-sensitive event, tamper-evident (FR-014, R-05)."""

    __tablename__ = "security_audit_records"
    __table_args__ = (
        Index("ix_security_audit_identity", "identity"),
        Index("ix_security_audit_dataset", "dataset_id"),
        Index("ix_security_audit_action", "action"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    identity: Mapped[str] = mapped_column(String(256), nullable=False)
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("datasets.id", name="fk_security_audit_dataset"), nullable=True
    )
    column: Mapped[str | None] = mapped_column(String(63), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str | None] = mapped_column(String(256), nullable=True)
    result: Mapped[AuditResult] = mapped_column(
        Enum(AuditResult, name="audit_result"), nullable=False
    )
    protection_service_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)


class AccessDecision(Base):
    """The outcome of the enforcement chain for a request (FR-013)."""

    __tablename__ = "access_decisions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    identity: Mapped[str] = mapped_column(String(256), nullable=False)
    resource: Mapped[str] = mapped_column(String(256), nullable=False)
    classification_consulted: Mapped[SecurityLevel] = mapped_column(
        Enum(SecurityLevel, name="security_level"), nullable=False
    )
    policy_applied: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("protection_policies.id", name="fk_access_policy"), nullable=True
    )
    outcome: Mapped[AccessOutcome] = mapped_column(
        Enum(AccessOutcome, name="access_outcome"), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class EncryptionMetadata(Base):
    """Per-file/per-batch record of source-side encryption (FR-006)."""

    __tablename__ = "encryption_metadata"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    batch_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    file_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    mechanism: Mapped[str] = mapped_column(String(64), nullable=False)
    key_ref_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("key_references.id", name="fk_encryption_key_ref"), nullable=True
    )
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verification_result: Mapped[VerificationResult] = mapped_column(
        Enum(VerificationResult, name="verification_result"), nullable=False
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = [
    "AccessDecision",
    "AccessOutcome",
    "ApprovalStatus",
    "AuditRecord",
    "AuditResult",
    "Base",
    "BatchStatus",
    "CatalogMetadata",
    "Classification",
    "ConfigSource",
    "ConnectionState",
    "ContractOrigin",
    "ContractViolation",
    "DataClassification",
    "DataContract",
    "DataSource",
    "Dataset",
    "DatasetLayer",
    "DatasetVersion",
    "DeploymentRun",
    "DeploymentStep",
    "EncryptionMetadata",
    "EnvironmentType",
    "GateDecision",
    "GateOverride",
    "GateReport",
    "HealthCheckResult",
    "HealthStatus",
    "IngestionBatch",
    "IngestionConfig",
    "IngestionMode",
    "IngestionPipeline",
    "IngestionRun",
    "IngestionRunStatus",
    "KeyLifecycleState",
    "KeyReference",
    "KmsProvider",
    "LayerTransition",
    "LineageLink",
    "OverallStatus",
    "OverrideStatus",
    "PipelineState",
    "Platform",
    "PlatformConfigVersion",
    "PlatformStatus",
    "PromotionState",
    "PromotionStateRow",
    "ProtectionMechanism",
    "ProtectionPolicy",
    "Provider",
    "QualityGate",
    "QualityScore",
    "QualityTest",
    "QuarantineEntry",
    "QuarantineRecord",
    "RunOutcome",
    "RunStatus",
    "RunTrigger",
    "RunType",
    "SecurityAuditRecord",
    "SecurityLevel",
    "SourceContract",
    "SourceType",
    "StepStatus",
    "TargetZone",
    "TestCategory",
    "TestResult",
    "TestResultStatus",
    "TestSeverity",
    "TokenReference",
    "Transformation",
    "VerificationResult",
    "ViolationClassification",
]
