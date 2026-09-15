"""API router: quality scores & observability (T045, contracts/quality-api.md §6).

- ``GET /datasets/{dataset_id}/quality`` — current score + history (FR-014).
- ``GET /datasets/{dataset_id}/quality/history`` — per-run results for trend
  (US6-AC1, FR-013).
- ``GET /reports/{report_id}`` — drill into a run: per-test results +
  failed-record refs + related quarantine entries (US6-AC2, FR-015).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db
from datafoundry.controlplane.api.errors import NotFoundError
from datafoundry.controlplane.db.models import Dataset
from datafoundry.controlplane.quality.score import compute_score, drill_down, history
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

router = APIRouter(tags=["quality"])


# -- response models ------------------------------------------------------------


class HistoryItem(BaseModel):
    report_id: uuid.UUID
    decision: str
    overall_status: str
    tests_run: int
    tests_passed: int
    tests_warned: int
    tests_failed: int
    config_version: int
    ran_at: datetime


class QualityResponse(BaseModel):
    dataset_id: uuid.UUID
    score: float
    window_start: datetime
    window_end: datetime
    history: list[HistoryItem]


class HistoryResponse(BaseModel):
    items: list[HistoryItem]


class DrillResultItem(BaseModel):
    test_id: uuid.UUID
    status: str
    failed_record_count: int = 0
    failed_record_refs: list[Any] | None = None
    measured_value: dict[str, Any] | None = None
    duration_ms: int | None = None


class QuarantineRef(BaseModel):
    entry_id: uuid.UUID
    batch_id: uuid.UUID
    payload_ref: str
    failure_reason: str
    failed_test: str | None


class DrillDownResponse(BaseModel):
    report_id: uuid.UUID
    gate_id: uuid.UUID
    dataset_id: uuid.UUID
    run_id: uuid.UUID
    decision: str
    overall_status: str
    tests_run: int
    tests_passed: int
    tests_warned: int
    tests_failed: int
    config_version: int
    results: list[DrillResultItem]
    quarantine_entries: list[QuarantineRef]


# -- helpers --------------------------------------------------------------------


def _get_dataset(session: Session, dataset_id: uuid.UUID) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise NotFoundError(f"no dataset with id {dataset_id}")
    return dataset


# -- routes ---------------------------------------------------------------------


@router.get(
    "/datasets/{dataset_id}/quality",
    response_model=QualityResponse,
)
def get_quality(
    dataset_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> QualityResponse:
    """Current quality score + history for a dataset (FR-014)."""
    _get_dataset(session, dataset_id)
    score = compute_score(session, dataset_id=dataset_id)
    hist = history(session, dataset_id=dataset_id)
    return QualityResponse(
        dataset_id=dataset_id,
        score=score,
        window_start=hist[-1]["ran_at"] if hist else datetime.now(),
        window_end=hist[0]["ran_at"] if hist else datetime.now(),
        history=[HistoryItem(**h) for h in hist],
    )


@router.get(
    "/datasets/{dataset_id}/quality/history",
    response_model=HistoryResponse,
)
def get_quality_history(
    dataset_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> HistoryResponse:
    """Per-run results for trend (US6-AC1, FR-013)."""
    _get_dataset(session, dataset_id)
    return HistoryResponse(
        items=[HistoryItem(**h) for h in history(session, dataset_id=dataset_id)]
    )


@router.get(
    "/reports/{report_id}",
    response_model=DrillDownResponse,
)
def get_report_drill_down(
    report_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> DrillDownResponse:
    """Drill into a run: results + failed records + quarantine (FR-015)."""
    try:
        data = drill_down(session, report_id=report_id)
    except KeyError as exc:
        raise NotFoundError(str(exc)) from exc
    return DrillDownResponse(**data)
