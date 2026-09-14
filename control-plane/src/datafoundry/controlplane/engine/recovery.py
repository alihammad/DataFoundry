"""Retry-from-failed-step and scoped rollback (T031, R-06, FR-009, SC-005).

- **Retry**: re-applies the failed step's module in the SAME per-run
  workspace and continues with the remaining pending steps. Succeeded steps
  are never re-executed destructively; the failed step's ``attempt``
  increments. Run: ``failed -> running`` (state machine).
- **Rollback**: ``terraform destroy`` in reverse step order, scoped to the
  run's workspace/state only — pre-existing platforms have separate states,
  so rollback cannot touch them (R-06). Afterwards zero orphaned resources
  remain (SC-005) and the platform is ``destroyed``. Run: ``failed ->
  rolled_back``.
- **Credential expiry**: run goes ``paused`` (worker), resumable via retry;
  nothing is ever auto-destroyed (R-06).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from datafoundry.controlplane.config.settings import Settings
from datafoundry.controlplane.db.models import (
    DeploymentRun,
    DeploymentStep,
    Platform,
    PlatformStatus,
    RunStatus,
    StepStatus,
)
from datafoundry.controlplane.db.state_machines import transition_platform, transition_run
from datafoundry.controlplane.engine.gateway import CloudGateway
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class RecoveryError(RuntimeError):
    """A recovery operation was refused (wrong run state, etc.)."""


def _steps(session: Session, run_id: uuid.UUID) -> list[DeploymentStep]:
    stmt = (
        select(DeploymentStep)
        .where(DeploymentStep.run_id == run_id)
        .order_by(DeploymentStep.position)
    )
    return list(session.execute(stmt).scalars())


def find_failed_step(session: Session, run_id: uuid.UUID) -> DeploymentStep | None:
    for step in _steps(session, run_id):
        if step.status is StepStatus.failed:
            return step
    return None


def prepare_retry(session: Session, run: DeploymentRun) -> DeploymentStep:
    """Validate + arm a retry: run must be failed/paused with a failed step.

    Sets the run back to ``running``-eligible state (queued for the worker to
    pick up) and resets the failed step to ``pending`` (attempt increments on
    execution). Raises RecoveryError -> API 409 when not retryable.
    """
    if run.status not in (RunStatus.failed, RunStatus.paused):
        raise RecoveryError(f"run is '{run.status.value}'; retry requires 'failed' or 'paused'")
    failed = find_failed_step(session, run.id)
    if failed is None:
        raise RecoveryError("run has no failed step to retry from")
    failed.status = StepStatus.pending
    failed.error_detail = None
    failed.started_at = None
    failed.finished_at = None
    # Keep the run `failed`/`paused` until the worker picks it up — both
    # states transition to `running` legally (state machine). Clear terminal
    # markers so duration is recomputed.
    run.finished_at = None
    run.failure_summary = None
    session.flush()
    return failed


def prepare_rollback(session: Session, run: DeploymentRun) -> None:
    """Validate a rollback request: run must be ``failed`` (contract §2:
    409 otherwise). Marks the run for the rollback worker pass."""
    if run.status is not RunStatus.failed:
        raise RecoveryError(f"run is '{run.status.value}'; rollback requires 'failed'")
    session.flush()


class RecoveryRunner:
    """Executes retry/rollback passes (driven by the same worker primitives)."""

    def __init__(
        self,
        session: Session,
        *,
        settings: Settings,
        gateway: CloudGateway,
    ) -> None:
        self.session = session
        self.settings = settings
        self.gateway = gateway

    # -- retry ---------------------------------------------------------------

    def retry(self, run_id: uuid.UUID) -> DeploymentRun:
        """Resume the run from its failed step (FR-009).

        The worker's ``_execute_steps`` naturally skips succeeded/skipped
        steps and re-executes the (reset) failed step, incrementing attempt.
        """
        from datafoundry.controlplane.engine.worker import WorkerRunner

        run = self.session.get(DeploymentRun, run_id)
        if run is None:
            raise KeyError(f"run {run_id} not found")
        prepare_retry(self.session, run)
        platform = self.session.get(Platform, run.platform_id)
        assert platform is not None
        if platform.status is PlatformStatus.failed:
            platform.status = transition_platform(platform.status, PlatformStatus.deploying)
        logger.info("run.retry", extra={"run_id": str(run_id)})
        worker = WorkerRunner(self.session, settings=self.settings, gateway=self.gateway)
        return worker.process_run(run_id)

    # -- rollback ---------------------------------------------------------------

    def rollback(self, run_id: uuid.UUID) -> DeploymentRun:
        """Destroy ONLY this run's resources, in reverse step order (R-06).

        Real mode: ``terraform destroy`` inside the run's isolated workspace
        (per-run state => cannot touch other platforms). Simulated mode: the
        gateway removes the run's inventory. Either way the run ends
        ``rolled_back`` and the platform ``destroyed``.
        """
        run = self.session.get(DeploymentRun, run_id)
        if run is None:
            raise KeyError(f"run {run_id} not found")
        prepare_rollback(self.session, run)
        platform = self.session.get(Platform, run.platform_id)
        assert platform is not None

        run.status = transition_run(run.status, RunStatus.running)
        platform.status = transition_platform(platform.status, PlatformStatus.destroying)
        self.session.flush()

        try:
            self._destroy_workspace(run)
        except Exception as exc:
            run.status = transition_run(run.status, RunStatus.failed)
            run.failure_summary = f"rollback failed: {exc}"
            platform.status = transition_platform(platform.status, PlatformStatus.failed)
            self.session.flush()
            raise RecoveryError(str(exc)) from exc

        # Reverse-order bookkeeping: annotate what was torn down; pending
        # steps never executed are marked skipped.
        for step in reversed(_steps(self.session, run.id)):
            if step.status in (StepStatus.succeeded, StepStatus.failed):
                step.detail = ((step.detail or "") + " [rolled back]").strip()
            elif step.status is StepStatus.pending:
                step.status = StepStatus.skipped
                step.detail = "run rolled back before this step"
            step.finished_at = datetime.now(UTC)

        run.status = transition_run(run.status, RunStatus.rolled_back)
        run.finished_at = datetime.now(UTC)
        platform.status = transition_platform(platform.status, PlatformStatus.destroyed)
        self.session.flush()
        logger.info("run.rolled_back", extra={"run_id": str(run_id)})
        return run

    def _destroy_workspace(self, run: DeploymentRun) -> None:
        """terraform destroy scoped to the run's workspace (real mode) +
        gateway inventory cleanup (both modes)."""
        if not self.settings.simulate_cloud:
            import asyncio

            from datafoundry.controlplane.engine.terraform import TerraformCLI

            cli = TerraformCLI(self.settings)
            workdir = self.settings.workspaces_dir / str(run.id)

            async def _destroy() -> None:
                await cli.init(workdir)
                await cli.destroy(workdir, auto_approve=True)

            asyncio.run(_destroy())
        removed = self.gateway.destroy_run_resources(str(run.id))
        logger.info(
            "rollback.resources_removed",
            extra={"run_id": str(run.id), "removed": removed},
        )

    def _destroy_all_platform_runs(self, run: DeploymentRun) -> int:
        """Destroy every run's resources for the platform (full platform destroy).

        A ``destroy`` run has no steps of its own; the platform's resources were
        created across prior deploy/update runs. Remove them all so no orphans
        remain (SC-005).
        """
        run_ids = [
            str(run_id)
            for run_id in self.session.execute(
                select(DeploymentRun.id).where(DeploymentRun.platform_id == run.platform_id)
            ).scalars()
        ]
        total = 0
        for run_id in run_ids:
            total += self.gateway.destroy_run_resources(run_id)
        return total

    # -- destroy ---------------------------------------------------------------

    def destroy(self, run_id: uuid.UUID) -> DeploymentRun:
        """Destroy a whole platform (DELETE /platforms/{id}, T072).

        Creates/executes a ``destroy`` run in reverse order: tears down every
        capability and ends the platform ``destroyed``. Mirrors rollback but
        applies to a ready/degraded platform and does not require the run to
        be ``failed`` first.
        """
        run = self.session.get(DeploymentRun, run_id)
        if run is None:
            raise KeyError(f"run {run_id} not found")
        platform = self.session.get(Platform, run.platform_id)
        assert platform is not None

        run.status = transition_run(run.status, RunStatus.running)
        platform.status = transition_platform(platform.status, PlatformStatus.destroying)
        self.session.flush()

        try:
            self._destroy_all_platform_runs(run)
        except Exception as exc:
            run.status = transition_run(run.status, RunStatus.failed)
            run.failure_summary = f"destroy failed: {exc}"
            platform.status = transition_platform(platform.status, PlatformStatus.failed)
            self.session.flush()
            raise RecoveryError(str(exc)) from exc

        for step in reversed(_steps(self.session, run.id)):
            if step.status in (StepStatus.succeeded, StepStatus.failed):
                step.detail = ((step.detail or "") + " [destroyed]").strip()
            elif step.status is StepStatus.pending:
                step.status = StepStatus.skipped
                step.detail = "platform destroyed before this step"
            step.finished_at = datetime.now(UTC)

        run.status = transition_run(run.status, RunStatus.rolled_back)
        run.finished_at = datetime.now(UTC)
        platform.status = transition_platform(platform.status, PlatformStatus.destroyed)
        self.session.flush()
        logger.info("run.destroyed", extra={"run_id": str(run_id)})
        return run
