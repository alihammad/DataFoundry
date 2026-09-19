"""Security audit module (feature 005, T014).

Tamper-evident chained-hash SecurityAuditRecord, searchable by time/identity/
dataset/action (FR-014); failed decryption/detokenisation recorded + alertable
(FR-015).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from datafoundry.controlplane.db.models import AuditResult, SecurityAuditRecord
from sqlalchemy import select
from sqlalchemy.orm import Session


def _chain_hash(prev_hash: str | None, payload: dict[str, Any]) -> str:
    """Chained hash over the prior record's hash + this record's payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{prev_hash or ''}:{canonical}".encode()).hexdigest()


def record_audit(
    session: Session,
    *,
    identity: str,
    action: str,
    result: AuditResult,
    dataset_id: uuid.UUID | None = None,
    column: str | None = None,
    purpose: str | None = None,
    protection_service_ref: str | None = None,
) -> SecurityAuditRecord:
    """Append a tamper-evident security audit record (FR-014, R-05)."""
    prev = session.execute(
        select(SecurityAuditRecord).order_by(SecurityAuditRecord.occurred_at.desc()).limit(1)
    ).scalar_one_or_none()
    prev_hash = prev.hash if prev else None
    payload = {
        "identity": identity,
        "action": action,
        "result": result.value,
        "dataset_id": str(dataset_id) if dataset_id else None,
        "column": column,
        "purpose": purpose,
        "protection_service_ref": protection_service_ref,
    }
    record = SecurityAuditRecord(
        occurred_at=datetime.now(UTC),
        identity=identity,
        dataset_id=dataset_id,
        column=column,
        action=action,
        purpose=purpose,
        result=result,
        protection_service_ref=protection_service_ref,
        prev_hash=prev_hash,
        hash=_chain_hash(prev_hash, payload),
    )
    session.add(record)
    session.flush()
    return record


def search_audit(
    session: Session,
    *,
    identity: str | None = None,
    dataset_id: uuid.UUID | None = None,
    action: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[SecurityAuditRecord]:
    """Search audit records by time/identity/dataset/action (US6-AC3)."""
    query = select(SecurityAuditRecord).order_by(SecurityAuditRecord.occurred_at.desc())
    if identity:
        query = query.where(SecurityAuditRecord.identity == identity)
    if dataset_id:
        query = query.where(SecurityAuditRecord.dataset_id == dataset_id)
    if action:
        query = query.where(SecurityAuditRecord.action == action)
    if date_from:
        query = query.where(SecurityAuditRecord.occurred_at >= date_from)
    if date_to:
        query = query.where(SecurityAuditRecord.occurred_at <= date_to)
    return list(session.scalars(query).all())


def verify_chain(session: Session) -> bool:
    """Verify the tamper-evident hash chain (US6-AC1).

    Recomputes each record's hash from its predecessor and confirms it matches
    the stored hash. Returns False when any record has been tampered with.
    """
    records = list(
        session.scalars(
            select(SecurityAuditRecord).order_by(SecurityAuditRecord.occurred_at.asc())
        ).all()
    )
    prev_hash = None
    for record in records:
        payload = {
            "identity": record.identity,
            "action": record.action,
            "result": record.result.value,
            "dataset_id": str(record.dataset_id) if record.dataset_id else None,
            "column": record.column,
            "purpose": record.purpose,
            "protection_service_ref": record.protection_service_ref,
        }
        expected = _chain_hash(prev_hash, payload)
        if record.hash != expected:
            return False
        prev_hash = record.hash
    return True
