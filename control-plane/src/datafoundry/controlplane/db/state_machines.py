"""Platform and DeploymentRun status state machines (data-model.md).

Platform::

    pending ──deploy──▶ deploying ──all health pass──▶ ready
                           │                              │
                           ├──health failures──▶ degraded │
                           ├──step failed──▶ failed       │
    failed ──retry──▶ deploying                           │
    failed ──rollback──▶ destroying ──▶ destroyed         │
    ready/degraded ──config change──▶ deploying ──────────┘
    ready/degraded ──destroy──▶ destroying ──▶ destroyed

DeploymentRun::

    queued ──worker picks up──▶ running ──all steps done──▶ succeeded
    running ──step failed──▶ failed
    failed ──retry-from-step──▶ running (same run, new attempt on step)
    failed ──rollback requested──▶ running (rollback steps) ──▶ rolled_back
    running ──credentials expired──▶ paused ──refresh+resume──▶ running

``destroying ──▶ destroyed`` also applies from ready/degraded (destroy flow).
"""

from __future__ import annotations

from datafoundry.controlplane.db.models import PlatformStatus, RunStatus

#: Allowed Platform status transitions.
PLATFORM_TRANSITIONS: dict[PlatformStatus, frozenset[PlatformStatus]] = {
    PlatformStatus.pending: frozenset({PlatformStatus.deploying}),
    PlatformStatus.deploying: frozenset(
        {
            PlatformStatus.ready,
            PlatformStatus.degraded,
            PlatformStatus.failed,
            PlatformStatus.destroying,
        }
    ),
    PlatformStatus.ready: frozenset(
        {PlatformStatus.deploying, PlatformStatus.degraded, PlatformStatus.destroying}
    ),
    PlatformStatus.degraded: frozenset(
        {PlatformStatus.deploying, PlatformStatus.ready, PlatformStatus.destroying}
    ),
    PlatformStatus.failed: frozenset({PlatformStatus.deploying, PlatformStatus.destroying}),
    PlatformStatus.destroying: frozenset({PlatformStatus.destroyed, PlatformStatus.failed}),
    PlatformStatus.destroyed: frozenset(),  # terminal
}

#: Allowed DeploymentRun status transitions.
RUN_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.queued: frozenset({RunStatus.running, RunStatus.failed}),
    RunStatus.running: frozenset({RunStatus.succeeded, RunStatus.failed, RunStatus.paused}),
    RunStatus.paused: frozenset({RunStatus.running, RunStatus.failed}),
    RunStatus.failed: frozenset({RunStatus.running, RunStatus.rolled_back}),
    RunStatus.succeeded: frozenset(),  # terminal
    RunStatus.rolled_back: frozenset(),  # terminal
}

#: Run statuses that count as "active" (one per platform invariant).
ACTIVE_RUN_STATUSES: frozenset[RunStatus] = frozenset(
    {RunStatus.queued, RunStatus.running, RunStatus.paused}
)


class InvalidTransitionError(ValueError):
    """Raised when a status transition is not allowed by the state machine."""

    def __init__(self, entity: str, current: str, requested: str) -> None:
        super().__init__(f"invalid {entity} status transition: {current} -> {requested}")
        self.entity = entity
        self.current = current
        self.requested = requested


def can_transition_platform(current: PlatformStatus, requested: PlatformStatus) -> bool:
    return requested in PLATFORM_TRANSITIONS.get(current, frozenset())


def transition_platform(current: PlatformStatus, requested: PlatformStatus) -> PlatformStatus:
    if current == requested:
        return current
    if not can_transition_platform(current, requested):
        raise InvalidTransitionError("platform", current.value, requested.value)
    return requested


def can_transition_run(current: RunStatus, requested: RunStatus) -> bool:
    return requested in RUN_TRANSITIONS.get(current, frozenset())


def transition_run(current: RunStatus, requested: RunStatus) -> RunStatus:
    if current == requested:
        return current
    if not can_transition_run(current, requested):
        raise InvalidTransitionError("run", current.value, requested.value)
    return requested


def is_terminal_platform(status: PlatformStatus) -> bool:
    return not PLATFORM_TRANSITIONS.get(status, frozenset())


def is_terminal_run(status: RunStatus) -> bool:
    return not RUN_TRANSITIONS.get(status, frozenset())
