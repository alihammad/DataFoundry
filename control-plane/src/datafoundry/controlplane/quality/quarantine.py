"""Quarantine write/read + replay + retention (feature 004, T029/T030, R-05).

- :func:`quarantine_entry` — persist a rejected record/file with full failure
  context (FR-008): payload_ref, failure_reason, failed_test, batch_id,
  retention_expiry, attempt_count, secret-scanned metadata_json.
- :func:`list_quarantine` — read/filter entries (source/pipeline/batch/reason/
  date range) (US3-AC3).
- :func:`replay_entry` — re-enter a quarantined record at the appropriate
  stage (FR-009): idempotent (no duplicate processed records), increments
  ``attempt_count`` on failure, escalates to the owner beyond a threshold, and
  refuses replay after ``retention_expiry`` (FR-010).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from datafoundry.controlplane.db.models import QuarantineEntry
from datafoundry.controlplane.quality.security import (
    scan_quality_json,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

#: Replay attempts beyond this threshold escalate to the dataset owner (FR-009).
REPLAY_ESCALATION_THRESHOLD = 3


class QuarantineNotFoundError(KeyError):
    """Raised when a quarantine entry id does not exist."""


class RetentionExpiredError(RuntimeError):
    """Raised when replay is attempted after ``retention_expiry`` (FR-010)."""


class NotReplayEligibleError(RuntimeError):
    """Raised when an entry is not replay-eligible (FR-009)."""


class ReplayFailedError(RuntimeError):
    """Raised when a replay re-entry fails (FR-009); attempt_count increments."""


def quarantine_entry(
    session: Session,
    *,
    dataset_id: uuid.UUID,
    batch_id: uuid.UUID,
    payload_ref: str,
    failure_reason: str,
    failed_test: str | None,
    retention_expiry: datetime,
    metadata_json: dict[str, Any] | None = None,
    attempt_count: int = 1,
    replay_eligible: bool = True,
) -> QuarantineEntry:
    """Persist a quarantine entry with full failure context (FR-008).

    ``metadata_json`` is secret-scanned before persist (SC-007); detection
    raises :class:`QualitySecretLeakError` and nothing is stored.
    """
    meta = metadata_json or {}
    scan_quality_json(meta)
    entry = QuarantineEntry(
        dataset_id=dataset_id,
        batch_id=batch_id,
        payload_ref=payload_ref,
        failure_reason=failure_reason,
        failed_test=failed_test,
        attempt_count=attempt_count,
        replay_eligible=replay_eligible,
        retention_expiry=retention_expiry,
        metadata_json=meta,
    )
    session.add(entry)
    session.flush()
    return entry


def get_entry(session: Session, entry_id: uuid.UUID) -> QuarantineEntry:
    """Fetch a quarantine entry by id (FR-015 drill-down)."""
    entry = session.get(QuarantineEntry, entry_id)
    if entry is None:
        raise QuarantineNotFoundError(f"no quarantine entry with id {entry_id}")
    return entry


def list_quarantine(
    session: Session,
    *,
    dataset_id: uuid.UUID,
    source: str | None = None,
    pipeline_id: str | None = None,
    batch_id: uuid.UUID | None = None,
    failure_reason: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[QuarantineEntry]:
    """List + filter quarantine entries for a dataset (US3-AC3).

    Filters: ``source``/``pipeline_id`` (metadata_json), ``batch_id``,
    ``failure_reason`` (substring), and ``quarantined_at`` date range.
    """
    stmt = select(QuarantineEntry).where(QuarantineEntry.dataset_id == dataset_id)
    if batch_id is not None:
        stmt = stmt.where(QuarantineEntry.batch_id == batch_id)
    if failure_reason:
        stmt = stmt.where(QuarantineEntry.failure_reason.ilike(f"%{failure_reason}%"))
    if date_from is not None:
        stmt = stmt.where(QuarantineEntry.quarantined_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(QuarantineEntry.quarantined_at <= date_to)

    entries = list(session.scalars(stmt).all())
    if source or pipeline_id:
        entries = [
            e
            for e in entries
            if (not source or (e.metadata_json or {}).get("source") == source)
            and (not pipeline_id or (e.metadata_json or {}).get("pipeline_id") == pipeline_id)
        ]
    return entries


def replay_entry(
    session: Session,
    *,
    entry_id: uuid.UUID,
    gateway: Any,
    owner_identity: str,
    now: datetime | None = None,
) -> uuid.UUID:
    """Replay a quarantined record at the appropriate stage (FR-009).

    - Refuses replay after ``retention_expiry`` (FR-010) or when the entry is
      not replay-eligible.
    - Re-enters the record via the gateway (idempotent — the gateway's
      quarantine store is keyed by ``payload_ref``, so a successful replay
      removes the entry from the active queue and cannot duplicate processed
      records).
    - On failure, increments ``attempt_count`` and escalates to the owner
      beyond :data:`REPLAY_ESCALATION_THRESHOLD`.

    Returns the new ``replay_run_id``.
    """
    entry = get_entry(session, entry_id)
    now = now or datetime.now(UTC)

    # SQLite returns naive datetimes for DateTime(timezone=True); normalise the
    # comparison so retention expiry is evaluated consistently on both dialects.
    expiry = entry.retention_expiry
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    if expiry < now:
        raise RetentionExpiredError(
            f"quarantine entry {entry_id} past retention expiry "
            f"{entry.retention_expiry.isoformat()}"
        )
    if not entry.replay_eligible:
        raise NotReplayEligibleError(f"quarantine entry {entry_id} is not replay-eligible")

    replay_run_id = uuid.uuid4()
    try:
        # Re-enter the record at the appropriate stage. The gateway keys its
        # quarantine store by payload_ref; a successful replay removes the
        # entry from the active queue (no duplicates, FR-009).
        gateway.replay_quarantine(
            dataset_id=str(entry.dataset_id),
            batch_id=str(entry.batch_id),
            payload_ref=entry.payload_ref,
            replay_run_id=str(replay_run_id),
            meta=dict(entry.metadata_json or {}),
        )
    except Exception as exc:
        entry.attempt_count += 1
        if entry.attempt_count > REPLAY_ESCALATION_THRESHOLD:
            _escalate(session, entry, owner_identity)
        raise ReplayFailedError(str(exc)) from exc

    # Successful replay removes the entry from the active queue (US3-AC2).
    session.delete(entry)
    session.flush()
    return replay_run_id


def _escalate(session: Session, entry: QuarantineEntry, owner_identity: str) -> None:
    """Escalate a repeatedly-failing replay to the dataset owner (FR-009).

    Marks the entry not replay-eligible so it stops retrying automatically and
    records the escalation in the audit trail.
    """
    entry.replay_eligible = False
    from datafoundry.controlplane.audit.service import AuditService

    AuditService(session).record(
        actor="system",
        action="quarantine.escalated",
        payload={
            "dataset_id": str(entry.dataset_id),
            "entry_id": str(entry.id),
            "owner_identity": owner_identity,
            "attempt_count": entry.attempt_count,
        },
    )


__all__ = [
    "NotReplayEligibleError",
    "QuarantineNotFoundError",
    "ReplayFailedError",
    "RetentionExpiredError",
    "get_entry",
    "list_quarantine",
    "quarantine_entry",
    "replay_entry",
]
