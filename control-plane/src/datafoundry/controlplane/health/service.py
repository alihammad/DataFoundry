"""Health check service (T080, FR-007, US3-AC2/AC3).

On-demand re-check (``POST /platforms/{id}/health-checks``) and the readiness
rule engine:

- ``ready`` iff every ENABLED capability's latest result is ``healthy``.
- any ``unhealthy`` => ``degraded`` with the component flagged (detail +
  last check time), per US3-AC3.
- ``unknown`` (no result yet) => ``unknown``.

Re-checks persist fresh ``HealthCheckResult`` rows and update the platform
status. Targets are resolved the same way as the deploy-time health step
(worker ``_resolve_targets``) so re-checks reflect live component state.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import yaml

from datafoundry.controlplane.capabilities.registry import default_registry
from datafoundry.controlplane.config.schema import PlatformConfig
from datafoundry.controlplane.db.models import (
    HealthCheckResult,
    HealthStatus,
    Platform,
    PlatformStatus,
)
from datafoundry.controlplane.db.state_machines import transition_platform
from datafoundry.controlplane.engine.gateway import CloudGateway
from datafoundry.controlplane.engine.init_jobs import platform_bucket
from datafoundry.controlplane.health.framework import (
    HealthCheckTarget,
    evaluate_platform_status,
)
from datafoundry.controlplane.health.runners import default_runners
from sqlalchemy import select
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class HealthCheckOutcomeSet:
    """Results of one re-check pass."""

    check_id: uuid.UUID
    latest_by_component: dict[str, HealthStatus]
    overall: HealthStatus


def latest_results(session: Session, platform_id: uuid.UUID) -> dict[str, HealthCheckResult]:
    """Latest HealthCheckResult per component for a platform."""
    stmt = (
        select(HealthCheckResult)
        .where(HealthCheckResult.platform_id == platform_id)
        .order_by(HealthCheckResult.last_check_at.desc())
    )
    latest: dict[str, HealthCheckResult] = {}
    for result in session.execute(stmt).scalars():
        latest.setdefault(result.component, result)
    return latest


def _resolve_targets(platform: Platform, config: PlatformConfig):
    """Synthesise deterministic health targets (mirrors worker._resolve_targets)."""
    enabled = default_registry.resolve_enabled(config.capabilities.explicitly_enabled())
    bucket = platform_bucket(
        platform.name, platform.environment_type.value, platform.provider.value
    )
    catalog_endpoint = f"https://catalog.{platform.name}.datafoundry.internal"
    targets: dict[str, HealthCheckTarget] = {}
    name = platform.name
    for capability in sorted(enabled):
        runner_id = default_registry.get(capability).health_check
        target = ""
        context = None
        if capability == "networking":
            target = f"vpc.{name}.datafoundry.internal"
        elif capability == "secrets":
            target = config.encryption.at_rest.kms_key_ref if config.encryption else "platform-cmk"
        elif capability == "storage_zones":
            target = bucket
            context = {"bucket": bucket}
        elif capability == "iam":
            target = f"datafoundry-{name}-role"
        elif capability == "compute":
            target = f"compute.{name}.datafoundry.internal"
        elif capability == "database":
            target = f"db.{name}.datafoundry.internal:5432"
        elif capability == "catalog":
            target = catalog_endpoint
        elif capability == "orchestration":
            target = f"https://airflow.{name}.datafoundry.internal"
        elif capability == "ingestion":
            target = f"https://ingestion.{name}.datafoundry.internal"
        elif capability == "quality":
            target = f"quality-runner.{name}.datafoundry.internal"
        elif capability == "semantic_layer":
            target = f"https://semantic.{name}.datafoundry.internal"
        elif capability == "monitoring":
            target = f"otel-collector.{name}.datafoundry.internal"
        targets[capability] = HealthCheckTarget(
            capability=capability, runner_id=runner_id, target=target, context=context
        )
    return targets


class HealthService:
    """Runs health checks and applies the readiness rule (FR-007, US3-AC3)."""

    def __init__(self, session: Session, *, gateway: CloudGateway) -> None:
        self.session = session
        self.gateway = gateway
        self.runners = default_runners

    def run_checks(self, platform: Platform) -> HealthCheckOutcomeSet:
        """Run every enabled capability's runner and persist fresh results."""
        raw_config = self._load_raw_config(platform)
        config = PlatformConfig.model_validate(raw_config)
        targets = _resolve_targets(platform, config)
        enabled = default_registry.resolve_enabled(config.capabilities.explicitly_enabled())

        check_id = uuid.uuid4()
        latest: dict[str, HealthStatus] = {}
        for capability in sorted(enabled):
            target = targets[capability]
            runner = self.runners.get(target.runner_id)
            outcome = runner.run(target, self.gateway)
            latest[capability] = outcome.status
            self.session.add(
                HealthCheckResult(
                    platform_id=platform.id,
                    component=capability,
                    status=outcome.status,
                    last_check_at=outcome.checked_at(),
                    detail=outcome.detail,
                    run_id=None,
                )
            )
        self.session.flush()

        overall = evaluate_platform_status(latest, enabled)
        # Apply the readiness rule to the platform status.
        if overall is HealthStatus.healthy and platform.status is PlatformStatus.degraded:
            platform.status = transition_platform(platform.status, PlatformStatus.ready)
        elif overall is HealthStatus.unhealthy and platform.status is not PlatformStatus.degraded:
            platform.status = transition_platform(platform.status, PlatformStatus.degraded)
        self.session.flush()
        return HealthCheckOutcomeSet(
            check_id=check_id, latest_by_component=latest, overall=overall
        )

    def _load_raw_config(self, platform: Platform) -> dict:
        version = platform.current_config_version_id
        if version is None:
            raise KeyError(f"platform {platform.id} has no config version")
        from datafoundry.controlplane.db.models import PlatformConfigVersion

        stored = self.session.get(PlatformConfigVersion, version)
        assert stored is not None
        return yaml.safe_load(stored.config_yaml)


def recompute_platform_status(
    session: Session, platform: Platform, latest: dict[str, HealthStatus], enabled: set[str]
) -> HealthStatus:
    """Apply the readiness rule without running probes (status-only helper)."""
    overall = evaluate_platform_status(latest, enabled)
    if overall is HealthStatus.healthy and platform.status is PlatformStatus.degraded:
        platform.status = transition_platform(platform.status, PlatformStatus.ready)
    elif overall is HealthStatus.unhealthy and platform.status is not PlatformStatus.degraded:
        platform.status = transition_platform(platform.status, PlatformStatus.degraded)
    session.flush()
    return overall
