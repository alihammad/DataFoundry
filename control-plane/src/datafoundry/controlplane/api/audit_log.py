"""Audit-log search API router (feature 007, T041/T046, ui-api.md §6).

- ``GET /ui/audit-log`` — search the existing audit service (feature 001) by
  time, identity, resource (action), with cursor pagination (FR-014).
"""

from __future__ import annotations

from datetime import datetime

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db
from datafoundry.controlplane.db.models import AuditRecord
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/ui/audit-log", tags=["ui-audit-log"])


@router.get("")
def search_audit_log(
    from_: datetime | None = None,
    to: datetime | None = None,
    identity: str | None = None,
    resource: str | None = None,
    action: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> dict:
    stmt = select(AuditRecord).order_by(AuditRecord.occurred_at.desc())
    if from_ is not None:
        stmt = stmt.where(AuditRecord.occurred_at >= from_)
    if to is not None:
        stmt = stmt.where(AuditRecord.occurred_at <= to)
    if identity is not None:
        stmt = stmt.where(AuditRecord.actor == identity)
    if action is not None:
        stmt = stmt.where(AuditRecord.action == action)
    if resource is not None:
        stmt = stmt.where(AuditRecord.action.like(f"%{resource}%"))
    if cursor is not None:
        stmt = stmt.where(AuditRecord.occurred_at < datetime.fromisoformat(cursor))
    stmt = stmt.limit(limit + 1)

    rows = session.execute(stmt).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [
            {
                "id": str(r.id),
                "actor_identity": r.actor,
                "action": r.action,
                "resource": r.action,
                "before_state": None,
                "after_state": r.payload,
                "created_at": r.occurred_at.isoformat(),
            }
            for r in rows
        ],
        "next_cursor": rows[-1].occurred_at.isoformat() if has_more and rows else None,
    }
