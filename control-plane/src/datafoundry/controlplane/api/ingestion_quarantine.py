"""API router: ingestion quarantine (T030, contracts/ingestion-api.md §5).

``GET /quarantine`` — list/filter ingestion quarantine records (FR-006,
US2-AC2). Query params: ``source_id``, ``pipeline_id``, ``batch_id``,
``failed_check``, ``since``, ``until`` (BRD §23M). Feature 004 extends with
replay.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db
from datafoundry.controlplane.db.models import QuarantineRecord
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(tags=["ingestion-quarantine"])


class QuarantineItem(BaseModel):
    record_id: uuid.UUID
    pipeline_id: uuid.UUID
    batch_id: uuid.UUID
    source_object: str
    failure_reason: str
    failed_check: str
    severity: str
    quarantined_at: datetime


class QuarantineListResponse(BaseModel):
    items: list[QuarantineItem]


@router.get("/quarantine", response_model=QuarantineListResponse)
def list_ingestion_quarantine(
    source_id: uuid.UUID | None = None,
    pipeline_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    failed_check: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> QuarantineListResponse:
    """List + filter ingestion quarantine records (ingestion-api.md §5)."""
    stmt = select(QuarantineRecord).order_by(QuarantineRecord.quarantined_at.desc())
    if source_id is not None:
        stmt = stmt.where(QuarantineRecord.source_id == source_id)
    if pipeline_id is not None:
        stmt = stmt.where(QuarantineRecord.pipeline_id == pipeline_id)
    if batch_id is not None:
        stmt = stmt.where(QuarantineRecord.batch_id == batch_id)
    if failed_check is not None:
        stmt = stmt.where(QuarantineRecord.failed_check == failed_check)
    if since is not None:
        stmt = stmt.where(QuarantineRecord.quarantined_at >= since)
    if until is not None:
        stmt = stmt.where(QuarantineRecord.quarantined_at <= until)

    records = session.execute(stmt).scalars().all()
    return QuarantineListResponse(
        items=[
            QuarantineItem(
                record_id=r.id,
                pipeline_id=r.pipeline_id,
                batch_id=r.batch_id,
                source_object=r.payload_ref,
                failure_reason=r.failure_reason,
                failed_check=r.failed_check,
                severity=r.severity.value,
                quarantined_at=r.quarantined_at,
            )
            for r in records
        ]
    )
