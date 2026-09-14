"""Deployment orchestrator (T030, R-11, R-12, FR-008, FR-010).

Builds the canonical step sequence for a run, persists Platform /
PlatformConfigVersion / DeploymentRun / DeploymentStep rows, and enforces the
one-active-run-per-platform invariant with a row lock (``SELECT ... FOR
UPDATE`` on the platform row; the DB partial unique index is the race-free
backstop).

Canonical order (research.md R-11)::

    1  validate-config      9  compute
    2  generate-tf          10 database
    3  validate-tf          11 catalog (+ zone/catalog init, FR-005)
    4  permission-check     12 orchestration
    4b approval-gate (production only, FR-010)
    5  networking           13 ingestion / quality / semantic_layer
    6  secrets-kms          14 monitoring
    7  storage-zones        15 health-checks -> ready
    8  iam

Disabled capabilities produce steps recorded ``skipped`` (FR-012).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from datafoundry.controlplane.capabilities.registry import (
    CapabilityRegistry,
    default_registry,
)
from datafoundry.controlplane.config.schema import PlatformConfig
from datafoundry.controlplane.config.validation import canonical_yaml, config_hash
from datafoundry.controlplane.db.models import (
    ConfigSource,
    DeploymentRun,
    DeploymentStep,
    EnvironmentType,
    Platform,
    PlatformConfigVersion,
    PlatformStatus,
    Provider,
    RunStatus,
    RunType,
    StepStatus,
)
from datafoundry.controlplane.db.state_machines import transition_platform
from sqlalchemy import select
from sqlalchemy.orm import Session

#: Fixed pre-flight steps (positions 1-4 per R-11).
PRE_FLIGHT_STEPS: tuple[str, ...] = (
    "validate-config",
    "generate-tf",
    "validate-tf",
    "permission-check",
)

#: Inserted before networking for production deployments (FR-010).
APPROVAL_GATE_STEP = "approval-gate"

#: Final step: health checks -> platform ready (R-08, FR-007).
HEALTH_CHECKS_STEP = "health-checks"

#: Capability key -> canonical step key (R-11 naming).
CAPABILITY_STEP_KEYS: dict[str, str] = {
    "networking": "networking",
    "secrets": "secrets-kms",
    "storage_zones": "storage-zones",
    "iam": "iam",
    "compute": "compute",
    "database": "database",
    "catalog": "catalog",
    "orchestration": "orchestration",
    "ingestion": "ingestion",
    "quality": "quality",
    "semantic_layer": "semantic",
    "monitoring": "monitoring",
}


def step_key_for_capability(capability_key: str) -> str:
    return CAPABILITY_STEP_KEYS[capability_key]


@dataclass(frozen=True)
class PlannedStep:
    """One step of the run plan (persisted as DeploymentStep)."""

    key: str
    capability: str | None
    status: StepStatus  # pending, or skipped for disabled capabilities
    detail: str | None = None
    terraform_module: str | None = None


class StepPlanner:
    """Builds the canonical ordered step list for a config (R-11)."""

    def __init__(self, registry: CapabilityRegistry | None = None) -> None:
        self.registry = registry or default_registry

    def plan(self, config: PlatformConfig) -> list[PlannedStep]:
        steps: list[PlannedStep] = [
            PlannedStep(key=key, capability=None, status=StepStatus.pending)
            for key in PRE_FLIGHT_STEPS
        ]
        if config.is_production:
            steps.append(
                PlannedStep(key=APPROVAL_GATE_STEP, capability=None, status=StepStatus.pending)
            )

        enabled_keys = self.registry.resolve_enabled(config.capabilities.explicitly_enabled())
        # All capabilities in canonical deploy order; disabled ones are
        # recorded `skipped` at their position (FR-012, US3-AC1).
        all_capabilities = sorted(
            self.registry.capabilities.values(),
            key=lambda c: (c.deploy_step, c.key),
        )
        for capability in all_capabilities:
            module_path = capability.module_path(config.platform.provider)
            if capability.key in enabled_keys:
                steps.append(
                    PlannedStep(
                        key=step_key_for_capability(capability.key),
                        capability=capability.key,
                        status=StepStatus.pending,
                        terraform_module=module_path,
                    )
                )
            else:
                steps.append(
                    PlannedStep(
                        key=step_key_for_capability(capability.key),
                        capability=capability.key,
                        status=StepStatus.skipped,
                        detail="capability disabled",
                    )
                )

        steps.append(
            PlannedStep(key=HEALTH_CHECKS_STEP, capability=None, status=StepStatus.pending)
        )
        return steps


_default_planner = StepPlanner()


def plan_steps(config: PlatformConfig) -> list[PlannedStep]:
    return _default_planner.plan(config)


class ActiveRunError(RuntimeError):
    """Raised when a platform already has an active run (R-12)."""


def lock_platform_for_update(session: Session, platform_id: uuid.UUID) -> Platform:
    """``SELECT ... FOR UPDATE`` the platform row (R-12 advisory lock).

    SQLite (tests) has no FOR UPDATE; with_for_update() is a no-op there but
    the partial unique index still enforces one active run.
    """
    stmt = select(Platform).where(Platform.id == platform_id).with_for_update()
    platform = session.execute(stmt).scalar_one_or_none()
    if platform is None:
        raise KeyError(f"platform {platform_id} not found")
    return platform


def has_active_run(session: Session, platform_id: uuid.UUID) -> bool:
    stmt = select(DeploymentRun.id).where(
        DeploymentRun.platform_id == platform_id,
        DeploymentRun.status.in_([RunStatus.queued, RunStatus.running, RunStatus.paused]),
    )
    return session.execute(stmt).first() is not None


class Orchestrator:
    """Registers platforms/config versions and queues deployment runs."""

    def __init__(
        self,
        session: Session,
        *,
        registry: CapabilityRegistry | None = None,
        planner: StepPlanner | None = None,
    ) -> None:
        self.session = session
        self.registry = registry or default_registry
        self.planner = planner or StepPlanner(self.registry)

    # -- platform registration ------------------------------------------------

    def register_platform(
        self,
        *,
        config: PlatformConfig,
        raw_config: dict,
        owner_identity: str,
        cloud_scope_id: str,
        source: ConfigSource = ConfigSource.api,
        git_ref: str | None = None,
    ) -> tuple[Platform, PlatformConfigVersion]:
        """Create Platform + version-1 PlatformConfigVersion (immutable)."""
        platform = Platform(
            name=config.platform.name,
            provider=Provider(config.platform.provider),
            cloud_scope_id=cloud_scope_id,
            region=config.platform.region,
            environment_type=EnvironmentType(config.platform.environment),
            status=PlatformStatus.pending,
            owner_identity=owner_identity,
        )
        self.session.add(platform)
        self.session.flush()

        yaml_text = canonical_yaml(raw_config)
        version = PlatformConfigVersion(
            platform_id=platform.id,
            version=1,
            config_yaml=yaml_text,
            config_hash=config_hash(raw_config),
            source=source,
            git_ref=git_ref,
            created_by=owner_identity,
        )
        self.session.add(version)
        self.session.flush()

        platform.current_config_version_id = version.id
        self.session.flush()
        return platform, version

    def next_config_version(self, platform_id: uuid.UUID) -> int:
        stmt = (
            select(PlatformConfigVersion.version)
            .where(PlatformConfigVersion.platform_id == platform_id)
            .order_by(PlatformConfigVersion.version.desc())
            .limit(1)
        )
        current = self.session.execute(stmt).scalar_one_or_none()
        return (current or 0) + 1

    # -- run queueing -----------------------------------------------------------

    def queue_run(
        self,
        *,
        platform: Platform,
        config: PlatformConfig,
        config_version: PlatformConfigVersion,
        run_type: RunType = RunType.deploy,
        initiated_by: str,
        approval_ref: str | None = None,
        idempotency_key: str | None = None,
    ) -> DeploymentRun:
        """Create a queued run + its full ordered step list.

        Enforces one active run per platform (R-12): the caller must hold the
        platform row lock (``lock_platform_for_update``).
        """
        if has_active_run(self.session, platform.id):
            raise ActiveRunError(f"platform {platform.name} already has an active run")
        run = DeploymentRun(
            platform_id=platform.id,
            config_version_id=config_version.id,
            run_type=run_type,
            status=RunStatus.queued,
            initiated_by=initiated_by,
            approval_ref=approval_ref,
            terraform_workspace=f"run-{uuid.uuid4().hex[:12]}",
            idempotency_key=idempotency_key,
        )
        self.session.add(run)
        self.session.flush()

        for position, planned in enumerate(self.planner.plan(config), start=1):
            self.session.add(
                DeploymentStep(
                    run_id=run.id,
                    position=position,
                    key=planned.key,
                    capability=planned.capability,
                    status=planned.status,
                    detail=planned.detail,
                    terraform_module=planned.terraform_module,
                    attempt=0,
                )
            )
        self.session.flush()
        return run

    # -- status transitions -------------------------------------------------------

    def mark_platform_deploying(self, platform: Platform) -> None:
        platform.status = transition_platform(platform.status, PlatformStatus.deploying)

    def set_platform_status(self, platform: Platform, status: PlatformStatus) -> None:
        platform.status = transition_platform(platform.status, status)
