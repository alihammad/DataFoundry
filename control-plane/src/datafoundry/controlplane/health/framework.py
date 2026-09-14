"""Health check framework (T033, R-08, FR-007).

Runners are registered per capability (registry ``health_check`` id) and
produce :class:`HealthCheckOutcome` values persisted as HealthCheckResult
rows. Platform readiness rule: ``ready`` iff every ENABLED capability's
latest result is ``healthy``; any ``unhealthy`` => ``degraded`` with the
component flagged (US3-AC2/AC3).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from datafoundry.controlplane.db.models import HealthStatus


@dataclass(frozen=True)
class HealthCheckOutcome:
    """One runner result (capability-catalog.md health check contract)."""

    component: str
    status: HealthStatus
    detail: str | None = None
    last_check_at: datetime | None = None

    def checked_at(self) -> datetime:
        return self.last_check_at or datetime.now(UTC)


@dataclass(frozen=True)
class HealthCheckTarget:
    """What a runner probes for one capability of one platform."""

    capability: str
    runner_id: str
    #: Endpoint/URL/bucket/key produced by the capability's terraform outputs
    #: (``health_target``) — resolved by the worker from run outputs.
    target: str = ""
    #: Extra context (bucket name for zone-head, key ref for kms probe...).
    context: dict[str, Any] | None = None


class HealthCheckRunner(abc.ABC):
    """Base class for health check runners (R-08)."""

    runner_id: str = ""

    @abc.abstractmethod
    def run(self, target: HealthCheckTarget, gateway: Any) -> HealthCheckOutcome:
        """Probe ``target`` and return the outcome."""


class RunnerRegistry:
    """Registry of runner id -> runner instance."""

    def __init__(self) -> None:
        self._runners: dict[str, HealthCheckRunner] = {}

    def register(self, runner: HealthCheckRunner) -> None:
        if not runner.runner_id:
            raise ValueError("runner must define runner_id")
        self._runners[runner.runner_id] = runner

    def get(self, runner_id: str) -> HealthCheckRunner:
        try:
            return self._runners[runner_id]
        except KeyError:
            raise KeyError(f"unknown health check runner '{runner_id}'") from None

    def runner_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._runners))


def evaluate_platform_status(
    latest_by_component: dict[str, HealthStatus],
    enabled_components: set[str],
) -> HealthStatus:
    """Readiness rule (FR-007): healthy iff all enabled components healthy."""
    for component in enabled_components:
        status = latest_by_component.get(component, HealthStatus.unknown)
        if status is HealthStatus.unhealthy:
            return HealthStatus.unhealthy
        if status is HealthStatus.unknown:
            return HealthStatus.unknown
    return HealthStatus.healthy
