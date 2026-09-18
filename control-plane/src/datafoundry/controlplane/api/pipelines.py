"""API router: ingestion pipelines (T040, contracts/ingestion-api.md §3).

- ``GET /pipelines`` — list pipelines with state/schedule/source/last run.
- ``POST /pipelines/{id}/run`` — manual trigger (FR-011, US4-AC1): 202
  {run_id, trigger}; 409 if a run is already active (R-10, partial unique
  index).
- ``POST /pipelines/{id}/pause`` / ``resume`` — schedule control (FR-014,
  US4-AC3).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import (
    get_db,
    get_ingestion_dispatcher,
)
from datafoundry.controlplane.api.errors import ConflictError, NotFoundError
from datafoundry.controlplane.audit.service import AuditService
from datafoundry.controlplane.db.models import (
    IngestionPipeline,
    IngestionRun,
    IngestionRunStatus,
    PipelineState,
    RunTrigger,
)
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(tags=["pipelines"])

_ACTIVE_STATUSES = (
    IngestionRunStatus.queued,
    IngestionRunStatus.running,
    IngestionRunStatus.paused,
)


# -- response models ------------------------------------------------------------


class PipelineItem(BaseModel):
    pipeline_id: uuid.UUID
    name: str
    state: str
    schedule: str | None
    source: str
    last_run_status: str | None
    last_run_at: datetime | None


class PipelineList(BaseModel):
    items: list[PipelineItem]


class RunTriggered(BaseModel):
    run_id: uuid.UUID
    trigger: str


class PipelineStateResponse(BaseModel):
    state: str


# -- helpers ---------------------------------------------------------------------


def _get_pipeline(session: Session, pipeline_id: uuid.UUID) -> IngestionPipeline:
    pipeline = session.get(IngestionPipeline, pipeline_id)
    if pipeline is None:
        raise NotFoundError(f"no pipeline with id {pipeline_id}")
    return pipeline


def _active_run(session: Session, pipeline_id: uuid.UUID) -> IngestionRun | None:
    return (
        session.execute(
            select(IngestionRun).where(
                IngestionRun.pipeline_id == pipeline_id,
                IngestionRun.status.in_(_ACTIVE_STATUSES),
            )
        )
        .scalars()
        .first()
    )


def _last_run(session: Session, pipeline_id: uuid.UUID) -> IngestionRun | None:
    return (
        session.execute(
            select(IngestionRun)
            .where(IngestionRun.pipeline_id == pipeline_id)
            .order_by(IngestionRun.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


def _queue_and_dispatch(
    session: Session,
    *,
    pipeline: IngestionPipeline,
    trigger: RunTrigger,
    actor: str,
    dispatcher,
    retry_of: uuid.UUID | None = None,
) -> IngestionRun:
    """Create a queued run, write audit, and hand it to the dispatcher."""
    run = IngestionRun(
        pipeline_id=pipeline.id,
        trigger=trigger,
        retry_of=retry_of,
        status=IngestionRunStatus.queued,
    )
    session.add(run)
    session.flush()

    audit = AuditService(session)
    if trigger == RunTrigger.retry:
        audit.run_retried(
            actor=actor,
            platform_id=pipeline.source.platform_id,
            pipeline_id=pipeline.id,
            run_id=run.id,
            retry_of=retry_of,
        )
    else:
        audit.run_triggered(
            actor=actor,
            platform_id=pipeline.source.platform_id,
            pipeline_id=pipeline.id,
            run_id=run.id,
            trigger=trigger.value,
        )
    session.flush()
    dispatcher(run.id)
    return run


# -- routes ----------------------------------------------------------------------


@router.get("/pipelines", response_model=PipelineList)
def list_pipelines(
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> PipelineList:
    """List pipelines with state/schedule/source/last run (FR-013)."""
    pipelines = session.execute(
        select(IngestionPipeline).order_by(IngestionPipeline.created_at)
    ).scalars()
    items = []
    for pipeline in pipelines:
        last = _last_run(session, pipeline.id)
        items.append(
            PipelineItem(
                pipeline_id=pipeline.id,
                name=pipeline.name,
                state=pipeline.state.value,
                schedule=pipeline.schedule,
                source=pipeline.source.name,
                last_run_status=last.status.value if last else None,
                last_run_at=last.created_at if last else None,
            )
        )
    return PipelineList(items=items)


@router.post("/pipelines/{pipeline_id}/run", status_code=202, response_model=RunTriggered)
def trigger_run(
    pipeline_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
    dispatcher=Depends(get_ingestion_dispatcher),
) -> RunTriggered:
    """Manually trigger a pipeline run (FR-011, US4-AC1)."""
    pipeline = _get_pipeline(session, pipeline_id)
    if _active_run(session, pipeline.id) is not None:
        raise ConflictError(
            "active_run",
            f"pipeline {pipeline.id} already has an active run",
        )
    run = _queue_and_dispatch(
        session,
        pipeline=pipeline,
        trigger=RunTrigger.manual,
        actor=caller.identity,
        dispatcher=dispatcher,
    )
    return RunTriggered(run_id=run.id, trigger=RunTrigger.manual.value)


@router.post("/pipelines/{pipeline_id}/pause", response_model=PipelineStateResponse)
def pause_pipeline(
    pipeline_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> PipelineStateResponse:
    """Pause the pipeline schedule (FR-014, US4-AC3)."""
    pipeline = _get_pipeline(session, pipeline_id)
    pipeline.state = PipelineState.paused
    AuditService(session).pipeline_paused(
        actor=caller.identity,
        platform_id=pipeline.source.platform_id,
        pipeline_id=pipeline.id,
    )
    session.flush()
    return PipelineStateResponse(state=PipelineState.paused.value)


@router.post("/pipelines/{pipeline_id}/resume", response_model=PipelineStateResponse)
def resume_pipeline(
    pipeline_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> PipelineStateResponse:
    """Resume the pipeline schedule (FR-014)."""
    pipeline = _get_pipeline(session, pipeline_id)
    pipeline.state = PipelineState.active
    AuditService(session).pipeline_resumed(
        actor=caller.identity,
        platform_id=pipeline.source.platform_id,
        pipeline_id=pipeline.id,
    )
    session.flush()
    return PipelineStateResponse(state=PipelineState.active.value)
