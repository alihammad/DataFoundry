"""Ingestion alerting (T036, FR-020).

Emits structured alerts to the pipeline owner on run failure, breaking schema
change, or reconciliation failure. Alerts are written as append-only audit
records (FR-014) with a secret-scanned, redacted payload (SC-006/SC-007) and
also surfaced through the structured JSON logger (R-09).
"""

from __future__ import annotations

import logging
from typing import Any

from datafoundry.controlplane.audit.service import AuditService
from datafoundry.controlplane.ingestion.security import redact_ingestion
from sqlalchemy.orm import Session

logger = logging.getLogger("datafoundry.ingestion.alerts")


def _emit(
    session: Session,
    *,
    actor: str,
    action: str,
    platform_id: Any,
    payload: dict[str, Any],
) -> None:
    """Persist an audit alert and log it (both redacted)."""
    safe = redact_ingestion(payload)
    try:
        AuditService(session).record(
            actor=actor,
            action=action,
            platform_id=platform_id,
            payload=safe,
        )
    except Exception:  # alerting must never break the ingestion run
        logger.exception("failed to persist ingestion alert %s", action)
    logger.warning("ingestion alert %s: %s", action, safe)


def alert_run_failure(
    session: Session,
    *,
    actor: str,
    platform_id: Any,
    pipeline_id: Any,
    run_id: Any,
    source_id: Any,
    object_name: str,
    reason: str,
) -> None:
    """Alert the pipeline owner that a run/object failed (FR-020)."""
    _emit(
        session,
        actor=actor,
        action="ingestion.alert.run_failure",
        platform_id=platform_id,
        payload={
            "pipeline_id": str(pipeline_id),
            "run_id": str(run_id),
            "source_id": str(source_id),
            "object_name": object_name,
            "reason": reason,
        },
    )


def alert_breaking_change(
    session: Session,
    *,
    actor: str,
    platform_id: Any,
    pipeline_id: Any,
    run_id: Any,
    source_id: Any,
    object_name: str,
    violations: list[dict[str, Any]],
) -> None:
    """Alert the pipeline owner of a breaking schema change (FR-020)."""
    _emit(
        session,
        actor=actor,
        action="ingestion.alert.breaking_change",
        platform_id=platform_id,
        payload={
            "pipeline_id": str(pipeline_id),
            "run_id": str(run_id),
            "source_id": str(source_id),
            "object_name": object_name,
            "violations": violations,
        },
    )


def alert_reconciliation_failure(
    session: Session,
    *,
    actor: str,
    platform_id: Any,
    pipeline_id: Any,
    run_id: Any,
    source_id: Any,
    object_name: str,
    source_count: int,
    ingested_count: int,
    difference: int,
    tolerance: int,
) -> None:
    """Alert the pipeline owner of a record-count reconciliation failure."""
    _emit(
        session,
        actor=actor,
        action="ingestion.alert.reconciliation_failure",
        platform_id=platform_id,
        payload={
            "pipeline_id": str(pipeline_id),
            "run_id": str(run_id),
            "source_id": str(source_id),
            "object_name": object_name,
            "source_count": source_count,
            "ingested_count": ingested_count,
            "difference": difference,
            "tolerance": tolerance,
        },
    )
