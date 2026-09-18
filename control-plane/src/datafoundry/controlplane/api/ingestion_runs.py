"""API router: ingestion runs, batches & history (T041, contracts/ingestion-api.md §4).

- ``GET /pipelines/{id}/runs`` — execution history (FR-013).
- ``GET /runs/{id}`` — run detail with batches.
- ``GET /batches/{id}`` — batch detail + metadata (FR-008, SC-003).
- ``GET /runs/{id}/logs`` — structured log reference (FR-013).
- ``POST /runs/{id}/retry`` — retry a failed run (FR-014, US4-AC2): re-reads
  from the uncommitted watermark so already-ingested records are not
  duplicated (R-06).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import (
    get_cloud_gateway,
    get_db,
    get_ingestion_dispatcher,
    get_settings_from_app,
)
from datafoundry.controlplane.api.errors import ConflictError, NotFoundError
from datafoundry.controlplane.db.models import (
    IngestionBatch,
    IngestionPipeline,
    IngestionRun,
    IngestionRunStatus,
    RunTrigger,
)
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(tags=["ingestion-runs"])

_ACTIVE_STATUSES = (
    IngestionRunStatus.queued,
    IngestionRunStatus.running,
    IngestionRunStatus.paused,
)


# -- response models ------------------------------------------------------------


class RunHistoryItem(BaseModel):
    run_id: uuid.UUID
    trigger: str
    status: str
    outcome: str | None
    records_processed: int
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: float | None
    failure_reason: str | None


class RunHistory(BaseModel):
    items: list[RunHistoryItem]


class BatchSummary(BaseModel):
    batch_id: uuid.UUID
    source_object: str
    status: str
    record_count: int


class RunDetail(BaseModel):
    run_id: uuid.UUID
    pipeline_id: uuid.UUID
    trigger: str
    status: str
    outcome: str | None
    records_processed: int
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: float | None
    failure_reason: str | None
    batches: list[BatchSummary]


class BatchDetail(BaseModel):
    batch_id: uuid.UUID
    source_system: str
    source_object: str
    ingested_at: datetime | None
    record_count: int
    checksum: str | None
    status: str
    metadata: dict[str, Any]


class LogRef(BaseModel):
    log_ref: str | None


class RetryTriggered(BaseModel):
    run_id: uuid.UUID
    trigger: str
    retry_of: uuid.UUID


# -- helpers ---------------------------------------------------------------------


def _get_run(session: Session, run_id: uuid.UUID) -> IngestionRun:
    run = session.get(IngestionRun, run_id)
    if run is None:
        raise NotFoundError(f"no ingestion run with id {run_id}")
    return run


def _is_deployment_run(session: Session, run_id: uuid.UUID) -> bool:
    """True if the run id belongs to a deployment run (feature 001).

    The ``/runs/{run_id}`` and ``/runs/{run_id}/retry`` paths are shared with
    the deployment API (deployment-api.md §2). This router is registered first
    and dispatches by run type so both features keep working.
    """
    from datafoundry.controlplane.db.models import DeploymentRun

    return session.get(DeploymentRun, run_id) is not None


def _get_batch(session: Session, batch_id: uuid.UUID) -> IngestionBatch:
    batch = session.get(IngestionBatch, batch_id)
    if batch is None:
        raise NotFoundError(f"no ingestion batch with id {batch_id}")
    return batch


def _duration(run: IngestionRun) -> float | None:
    if run.started_at is None or run.finished_at is None:
        return None
    return (run.finished_at - run.started_at).total_seconds()


def _history_item(run: IngestionRun) -> RunHistoryItem:
    return RunHistoryItem(
        run_id=run.id,
        trigger=run.trigger.value,
        status=run.status.value,
        outcome=run.outcome.value if run.outcome else None,
        records_processed=run.records_processed,
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_seconds=_duration(run),
        failure_reason=run.failure_reason,
    )


# -- routes ----------------------------------------------------------------------


@router.get("/pipelines/{pipeline_id}/runs", response_model=RunHistory)
def list_pipeline_runs(
    pipeline_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> RunHistory:
    """Execution history for a pipeline (FR-013)."""
    pipeline = session.get(IngestionPipeline, pipeline_id)
    if pipeline is None:
        raise NotFoundError(f"no pipeline with id {pipeline_id}")
    runs = session.execute(
        select(IngestionRun)
        .where(IngestionRun.pipeline_id == pipeline_id)
        .order_by(IngestionRun.created_at.desc())
    ).scalars()
    return RunHistory(items=[_history_item(r) for r in runs])


@router.get("/runs/{run_id}")
def get_run(
    run_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> Any:
    """Run detail with its batches (US4).

    Dispatches to the deployment run view when the run is a deployment run
    (shared ``/runs/{run_id}`` path, deployment-api.md §2).
    """
    if _is_deployment_run(session, run_id):
        from datafoundry.controlplane.api.runs import get_deployment_run

        return get_deployment_run(run_id, session=session)
    run = _get_run(session, run_id)
    batches = session.execute(
        select(IngestionBatch).where(IngestionBatch.run_id == run.id)
    ).scalars()
    return RunDetail(
        run_id=run.id,
        pipeline_id=run.pipeline_id,
        trigger=run.trigger.value,
        status=run.status.value,
        outcome=run.outcome.value if run.outcome else None,
        records_processed=run.records_processed,
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_seconds=_duration(run),
        failure_reason=run.failure_reason,
        batches=[
            BatchSummary(
                batch_id=b.id,
                source_object=b.source_object,
                status=b.status.value,
                record_count=b.record_count,
            )
            for b in batches
        ],
    )


@router.get("/batches/{batch_id}", response_model=BatchDetail)
def get_batch(
    batch_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> BatchDetail:
    """Batch detail + metadata (FR-008, SC-003)."""
    batch = _get_batch(session, batch_id)
    return BatchDetail(
        batch_id=batch.id,
        source_system=batch.source_system,
        source_object=batch.source_object,
        ingested_at=batch.ingested_at,
        record_count=batch.record_count,
        checksum=batch.checksum,
        status=batch.status.value,
        metadata=dict(batch.metadata_json or {}),
    )


@router.get("/runs/{run_id}/logs", response_model=LogRef)
def get_run_logs(
    run_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> LogRef:
    """Structured log reference for a run (FR-013)."""
    run = _get_run(session, run_id)
    return LogRef(log_ref=run.log_ref)


@router.post("/runs/{run_id}/retry", status_code=202)
def retry_run(
    run_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
    dispatcher=Depends(get_ingestion_dispatcher),
    settings=Depends(get_settings_from_app),
    gateway=Depends(get_cloud_gateway),
) -> Any:
    """Retry a failed run (FR-014, US4-AC2).

    Dispatches to the deployment retry when the run is a deployment run
    (shared ``/runs/{run_id}/retry`` path, deployment-api.md §2).
    """
    if _is_deployment_run(session, run_id):
        from datafoundry.controlplane.api.runs import retry_deployment_run

        return retry_deployment_run(
            run_id, caller=caller, session=session, settings=settings, gateway=gateway
        )
    original = _get_run(session, run_id)
    pipeline = session.get(IngestionPipeline, original.pipeline_id)
    if pipeline is None:
        raise NotFoundError(f"no pipeline with id {original.pipeline_id}")

    active = (
        session.execute(
            select(IngestionRun).where(
                IngestionRun.pipeline_id == pipeline.id,
                IngestionRun.status.in_(_ACTIVE_STATUSES),
            )
        )
        .scalars()
        .first()
    )
    if active is not None:
        raise ConflictError(
            "active_run",
            f"pipeline {pipeline.id} already has an active run",
        )

    retry = IngestionRun(
        pipeline_id=pipeline.id,
        trigger=RunTrigger.retry,
        retry_of=original.id,
        status=IngestionRunStatus.queued,
    )
    session.add(retry)
    session.flush()

    from datafoundry.controlplane.audit.service import AuditService

    AuditService(session).run_retried(
        actor=caller.identity,
        platform_id=pipeline.source.platform_id,
        pipeline_id=pipeline.id,
        run_id=retry.id,
        retry_of=original.id,
    )
    session.flush()
    dispatcher(retry.id)
    return RetryTriggered(
        run_id=retry.id,
        trigger=RunTrigger.retry.value,
        retry_of=original.id,
    )
