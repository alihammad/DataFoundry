"""API router: quarantine (T031, contracts/quality-api.md §4).

- ``GET /datasets/{dataset_id}/quarantine`` — list + filter quarantine entries
  (US3-AC3): source/pipeline_id/batch_id/failure_reason/date_from/date_to.
- ``POST /quarantine/{entry_id}/replay`` — replay a quarantined record
  (FR-009, US3-AC2): 202 replay_run_id; 409 on retention expiry (FR-010) or
  not eligible; audit ``quarantine.replayed``.
- ``GET /quarantine/{entry_id}`` — full entry + failure context (FR-015
  drill-down).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db, get_quality_gateway
from datafoundry.controlplane.api.errors import (
    ConflictError,
    NotFoundError,
)
from datafoundry.controlplane.audit.service import AuditService
from datafoundry.controlplane.db.models import Dataset, QuarantineEntry
from datafoundry.controlplane.quality.quarantine import (
    NotReplayEligibleError,
    QuarantineNotFoundError,
    ReplayFailedError,
    RetentionExpiredError,
    get_entry,
    list_quarantine,
    replay_entry,
)
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

router = APIRouter(tags=["quarantine"])


# -- response models ------------------------------------------------------------


class QuarantineItem(BaseModel):
    entry_id: uuid.UUID
    batch_id: uuid.UUID
    payload_ref: str
    failure_reason: str
    failed_test: str | None
    attempt_count: int
    replay_eligible: bool
    retention_expiry: datetime
    quarantined_at: datetime


class QuarantineListResponse(BaseModel):
    items: list[QuarantineItem]


class ReplayResponse(BaseModel):
    replay_run_id: uuid.UUID


class QuarantineDetailResponse(QuarantineItem):
    metadata: dict


# -- helpers --------------------------------------------------------------------


def _get_dataset(session: Session, dataset_id: uuid.UUID) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise NotFoundError(f"no dataset with id {dataset_id}")
    return dataset


def _item(entry: QuarantineEntry) -> QuarantineItem:
    return QuarantineItem(
        entry_id=entry.id,
        batch_id=entry.batch_id,
        payload_ref=entry.payload_ref,
        failure_reason=entry.failure_reason,
        failed_test=entry.failed_test,
        attempt_count=entry.attempt_count,
        replay_eligible=entry.replay_eligible,
        retention_expiry=entry.retention_expiry,
        quarantined_at=entry.quarantined_at,
    )


# -- routes ---------------------------------------------------------------------


@router.get(
    "/datasets/{dataset_id}/quarantine",
    response_model=QuarantineListResponse,
)
def list_quarantine_endpoint(
    dataset_id: uuid.UUID,
    source: str | None = None,
    pipeline_id: str | None = None,
    batch_id: uuid.UUID | None = None,
    failure_reason: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> QuarantineListResponse:
    """List + filter quarantine entries for a dataset (US3-AC3)."""
    _get_dataset(session, dataset_id)
    entries = list_quarantine(
        session,
        dataset_id=dataset_id,
        source=source,
        pipeline_id=pipeline_id,
        batch_id=batch_id,
        failure_reason=failure_reason,
        date_from=date_from,
        date_to=date_to,
    )
    return QuarantineListResponse(items=[_item(e) for e in entries])


@router.post(
    "/quarantine/{entry_id}/replay",
    status_code=202,
    response_model=ReplayResponse,
)
def replay_quarantine_endpoint(
    entry_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
    gateway=Depends(get_quality_gateway),
) -> ReplayResponse:
    """Replay a quarantined record (FR-009, US3-AC2)."""
    try:
        entry = get_entry(session, entry_id)
    except QuarantineNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc

    dataset = _get_dataset(session, entry.dataset_id)
    try:
        replay_run_id = replay_entry(
            session,
            entry_id=entry_id,
            gateway=gateway,
            owner_identity=dataset.owner_identity,
        )
    except RetentionExpiredError as exc:
        raise ConflictError("retention_expired", str(exc)) from exc
    except NotReplayEligibleError as exc:
        raise ConflictError("not_eligible", str(exc)) from exc
    except ReplayFailedError as exc:
        raise ConflictError("replay_failed", str(exc)) from exc

    AuditService(session).quarantine_replayed(
        actor=caller.identity,
        dataset_id=entry.dataset_id,
        entry_id=entry.id,
        replay_run_id=replay_run_id,
        attempt_count=entry.attempt_count,
    )
    return ReplayResponse(replay_run_id=replay_run_id)


@router.get(
    "/quarantine/{entry_id}",
    response_model=QuarantineDetailResponse,
)
def get_quarantine_entry_endpoint(
    entry_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> QuarantineDetailResponse:
    """Full quarantine entry + failure context (FR-015 drill-down)."""
    try:
        entry = get_entry(session, entry_id)
    except QuarantineNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    item = _item(entry)
    return QuarantineDetailResponse(**item.model_dump(), metadata=dict(entry.metadata_json or {}))
