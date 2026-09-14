"""API router: deployment runs (T036, contracts/deployment-api.md §2).

``GET  /api/v1/runs/{run_id}``          — ordered step progress (FR-008).
``POST /api/v1/runs/{run_id}/retry``    — retry from failed step (FR-009).
``POST /api/v1/runs/{run_id}/rollback`` — scoped rollback (FR-009, SC-005).

Retry/rollback return 202 and are executed by the recovery runner; 409 when
the run is not in a retryable/rollbackable state.
"""

from __future__ import annotations

import uuid

from datafoundry.controlplane.api.auth import ACTION_UPDATE_PLATFORM, Caller, require_action
from datafoundry.controlplane.api.deps import (
    get_cloud_gateway,
    get_db,
    get_settings_from_app,
)
from datafoundry.controlplane.api.errors import ConflictError, NotFoundError
from datafoundry.controlplane.audit.service import AuditService
from datafoundry.controlplane.config.settings import Settings
from datafoundry.controlplane.db.models import DeploymentRun, DeploymentStep, RunStatus
from datafoundry.controlplane.engine.recovery import RecoveryError, RecoveryRunner
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(tags=["runs"])


# -- response models -----------------------------------------------------------


class StepView(BaseModel):
    position: int
    key: str
    status: str
    capability: str | None = None
    attempt: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    error_detail: str | None = None
    detail: str | None = None


class RunView(BaseModel):
    run_id: uuid.UUID
    platform_id: uuid.UUID
    status: str
    steps: list[StepView]
    failure: str | None = None


class RecoveryAccepted(BaseModel):
    run_id: uuid.UUID
    status: str


# -- helpers ---------------------------------------------------------------------


def _load_run(session: Session, run_id: uuid.UUID) -> DeploymentRun:
    run = session.get(DeploymentRun, run_id)
    if run is None:
        raise NotFoundError(f"run {run_id} not found")
    return run


def _ordered_steps(session: Session, run_id: uuid.UUID) -> list[DeploymentStep]:
    stmt = (
        select(DeploymentStep)
        .where(DeploymentStep.run_id == run_id)
        .order_by(DeploymentStep.position)
    )
    return list(session.execute(stmt).scalars())


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


# -- GET /platforms/{platform_id}/runs ----------------------------------------------------


class RunHistoryItem(BaseModel):
    run_id: uuid.UUID
    run_type: str
    status: str
    initiated_by: str
    config_version: int
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None
    outcome: str | None = None


class RunHistory(BaseModel):
    items: list[RunHistoryItem]


@router.get("/platforms/{platform_id}/runs", response_model=RunHistory)
def list_platform_runs(platform_id: uuid.UUID, session: Session = Depends(get_db)) -> RunHistory:
    """Auditable run history (FR-014, deployment-api.md §2)."""
    from datafoundry.controlplane.db.models import Platform, PlatformConfigVersion

    if session.get(Platform, platform_id) is None:
        raise NotFoundError(f"platform {platform_id} not found")
    stmt = (
        select(DeploymentRun, PlatformConfigVersion.version)
        .join(
            PlatformConfigVersion,
            DeploymentRun.config_version_id == PlatformConfigVersion.id,
        )
        .where(DeploymentRun.platform_id == platform_id)
        .order_by(DeploymentRun.created_at.desc())
    )
    items = []
    for run, version in session.execute(stmt):
        duration = (
            (run.finished_at - run.started_at).total_seconds()
            if run.started_at and run.finished_at
            else None
        )
        items.append(
            RunHistoryItem(
                run_id=run.id,
                run_type=run.run_type.value,
                status=run.status.value,
                initiated_by=run.initiated_by,
                config_version=version,
                started_at=_iso(run.started_at),
                finished_at=_iso(run.finished_at),
                duration_seconds=duration,
                outcome=run.failure_summary,
            )
        )
    return RunHistory(items=items)


# -- GET /runs/{run_id} --------------------------------------------------------------


@router.get("/runs/{run_id}", response_model=RunView)
def get_run(run_id: uuid.UUID, session: Session = Depends(get_db)) -> RunView:
    run = _load_run(session, run_id)
    steps = [
        StepView(
            position=step.position,
            key=step.key,
            status=step.status.value,
            capability=step.capability,
            attempt=step.attempt,
            started_at=_iso(step.started_at),
            finished_at=_iso(step.finished_at),
            error_detail=step.error_detail,
            detail=step.detail,
        )
        for step in _ordered_steps(session, run_id)
    ]
    return RunView(
        run_id=run.id,
        platform_id=run.platform_id,
        status=run.status.value,
        steps=steps,
        failure=run.failure_summary,
    )


# -- POST /runs/{run_id}/retry ----------------------------------------------------------


@router.post(
    "/runs/{run_id}/retry",
    status_code=202,
    response_model=RecoveryAccepted,
)
def retry_run(
    run_id: uuid.UUID,
    caller: Caller = Depends(require_action(ACTION_UPDATE_PLATFORM)),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_app),
    gateway=Depends(get_cloud_gateway),
) -> RecoveryAccepted:
    run = _load_run(session, run_id)
    if run.status not in (RunStatus.failed, RunStatus.paused):
        raise ConflictError(
            "run_not_retryable",
            f"run is '{run.status.value}'; retry requires 'failed' or 'paused'",
        )
    recovery = RecoveryRunner(session, settings=settings, gateway=gateway)
    failed_step = next(
        (s for s in _ordered_steps(session, run_id) if s.status.value == "failed"), None
    )
    try:
        recovery.retry(run_id)
    except RecoveryError as exc:
        raise ConflictError("run_not_retryable", str(exc)) from exc
    AuditService(session).retry_executed(
        actor=caller.identity,
        platform_id=run.platform_id,
        run_id=run.id,
        from_step=failed_step.key if failed_step else "unknown",
    )
    session.refresh(run)
    return RecoveryAccepted(run_id=run.id, status=run.status.value)


# -- POST /runs/{run_id}/rollback ----------------------------------------------------------


@router.post(
    "/runs/{run_id}/rollback",
    status_code=202,
    response_model=RecoveryAccepted,
)
def rollback_run(
    run_id: uuid.UUID,
    caller: Caller = Depends(require_action(ACTION_UPDATE_PLATFORM)),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_app),
    gateway=Depends(get_cloud_gateway),
) -> RecoveryAccepted:
    run = _load_run(session, run_id)
    if run.status is not RunStatus.failed:
        raise ConflictError(
            "run_not_rollbackable",
            f"run is '{run.status.value}'; rollback requires 'failed'",
        )
    recovery = RecoveryRunner(session, settings=settings, gateway=gateway)
    try:
        recovery.rollback(run_id)
    except RecoveryError as exc:
        raise ConflictError("rollback_failed", str(exc)) from exc
    AuditService(session).rollback_executed(
        actor=caller.identity, platform_id=run.platform_id, run_id=run.id
    )
    session.refresh(run)
    return RecoveryAccepted(run_id=run.id, status=run.status.value)
