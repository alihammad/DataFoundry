"""API router: security audit (T042, contracts/security-api.md §6).

- ``GET /security-audit`` — search audit records by identity/dataset/action/
  date range (FR-014).
- ``GET /security-audit/{id}`` — full record incl. prev_hash/hash for tamper
  verification (US6-AC1).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db
from datafoundry.controlplane.api.errors import NotFoundError
from datafoundry.controlplane.db.models import SecurityAuditRecord
from datafoundry.controlplane.security.audit import search_audit
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

router = APIRouter(tags=["security-audit"])


class AuditItem(BaseModel):
    audit_id: uuid.UUID
    occurred_at: datetime
    identity: str
    dataset_id: uuid.UUID | None
    column: str | None
    action: str
    purpose: str | None
    result: str
    protection_service_ref: str | None


class AuditList(BaseModel):
    items: list[AuditItem]


class AuditDetail(AuditItem):
    prev_hash: str | None
    hash: str


def _to_item(record) -> AuditItem:
    return AuditItem(
        audit_id=record.id,
        occurred_at=record.occurred_at,
        identity=record.identity,
        dataset_id=record.dataset_id,
        column=record.column,
        action=record.action,
        purpose=record.purpose,
        result=record.result.value,
        protection_service_ref=record.protection_service_ref,
    )


@router.get("/security-audit", response_model=AuditList)
def list_security_audit(
    identity: str | None = Query(None),
    dataset_id: uuid.UUID | None = Query(None),
    action: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> AuditList:
    """Search audit records (FR-014, US6-AC3)."""
    records = search_audit(
        session,
        identity=identity,
        dataset_id=dataset_id,
        action=action,
        date_from=date_from,
        date_to=date_to,
    )
    return AuditList(items=[_to_item(r) for r in records])


@router.get("/security-audit/{audit_id}", response_model=AuditDetail)
def get_security_audit(
    audit_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> AuditDetail:
    """Full record incl. hash chain for tamper verification (US6-AC1)."""
    record = session.get(SecurityAuditRecord, audit_id)
    if record is None:
        raise NotFoundError(f"no security audit record with id {audit_id}")
    item = _to_item(record)
    return AuditDetail(
        **item.model_dump(),
        prev_hash=record.prev_hash,
        hash=record.hash,
    )
