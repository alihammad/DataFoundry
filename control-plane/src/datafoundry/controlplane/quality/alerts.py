"""Alerting on gate failures, contract violations, warning-threshold breaches
(feature 004, T047, FR-016).

Alerts are structured, redacted of secrets, and emitted through the platform's
observability channel (structured logging) plus an audit record. The alert
carries the failing test detail, dataset, run, and severity — never raw
payloads or secret material (SC-007).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from datafoundry.controlplane.audit.service import AuditService

logger = logging.getLogger("datafoundry.quality.alerts")


def emit_alert(
    session: Any,
    *,
    actor: str,
    kind: str,
    dataset_id: uuid.UUID,
    detail: dict[str, Any],
    severity: str = "warning",
) -> None:
    """Emit a structured quality alert (FR-016).

    ``kind`` is one of ``gate.failure``, ``contract.violation``,
    ``warning.threshold``. ``detail`` is a redacted, secret-free mapping
    (failing test name, counts, run id) — never raw payloads. The alert is
    logged (structured) and recorded in the audit trail.
    """
    redacted = _redact(detail)
    logger.warning(
        "quality_alert kind=%s severity=%s dataset_id=%s detail=%s",
        kind,
        severity,
        dataset_id,
        redacted,
    )
    AuditService(session).record(
        actor=actor,
        action=f"quality.alert.{kind}",
        payload={
            "dataset_id": str(dataset_id),
            "severity": severity,
            **redacted,
        },
    )


def _redact(detail: dict[str, Any]) -> dict[str, Any]:
    """Strip secret-like values from an alert detail (SC-007).

    Drops any value that looks like a credential (long high-entropy token,
    AWS access key, etc.) and any nested ``payload``/``raw`` keys.
    """
    redacted: dict[str, Any] = {}
    for key, value in detail.items():
        if key in {"payload", "raw", "secret", "password"}:
            continue
        if isinstance(value, str) and _looks_secret(value):
            redacted[key] = "[redacted]"
        else:
            redacted[key] = value
    return redacted


def _looks_secret(value: str) -> bool:
    """Heuristic: AWS access key or long high-entropy token."""
    if value.startswith("AKIA") and len(value) == 20:
        return True
    return len(value) >= 32 and sum(c.isalnum() for c in value) / max(len(value), 1) > 0.9


__all__ = ["emit_alert"]
