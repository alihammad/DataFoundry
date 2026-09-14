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
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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


# -- entities ------------------------------------------------------------------


class Platform(Base):
    __tablename__ = "platforms"
    __table_args__ = (
        UniqueConstraint("provider", "cloud_scope_id", "name", name="uq_platform_scope_name"),
        CheckConstraint("name ~ '^[a-z][a-z0-9-]{2,62}$'", name="ck_platform_name_format"),
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
            postgresql_where=Text("status IN ('queued', 'running', 'paused')"),
        ),
        UniqueConstraint("terraform_workspace", name="uq_run_workspace"),
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
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    platform: Mapped[Platform | None] = relationship(back_populates="audit_records")


__all__ = [
    "AuditRecord",
    "Base",
    "ConfigSource",
    "DeploymentRun",
    "DeploymentStep",
    "EnvironmentType",
    "HealthCheckResult",
    "HealthStatus",
    "Platform",
    "PlatformConfigVersion",
    "PlatformStatus",
    "Provider",
    "RunStatus",
    "RunType",
    "StepStatus",
]
