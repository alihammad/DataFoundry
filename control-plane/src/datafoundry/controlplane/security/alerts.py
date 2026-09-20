"""Alerting on security failures (feature 005, T046, FR-015).

Failed decryption/detokenisation attempts and restricted-access denials fire
structured alerts through the platform's observability channel (structured
logging) plus an audit record. Alerts are redacted of secrets (SC-007) — they
carry identity, dataset, column, action, and result, never key material or
token values.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from datafoundry.controlplane.audit.service import AuditService

logger = logging.getLogger("datafoundry.security.alerts")


def emit_security_alert(
    session: Any,
    *,
    actor: str,
    kind: str,
    dataset_id: uuid.UUID | None,
    detail: dict[str, Any],
    severity: str = "critical",
) -> None:
    """Emit a structured security alert (FR-015).

    ``kind`` is one of ``failed.decrypt``, ``failed.detokenise``,
    ``restricted.denied``. ``detail`` is a redacted, secret-free mapping
    (identity, dataset, column, action, result) — never key material or token
    values (SC-007). The alert is logged (structured) and recorded in the
    audit trail.
    """
    redacted = _redact(detail)
    logger.warning(
        "security_alert kind=%s severity=%s dataset_id=%s detail=%s",
        kind,
        severity,
        dataset_id,
        redacted,
    )
    AuditService(session).record(
        actor=actor,
        action=f"security.alert.{kind}",
        payload={
            "dataset_id": str(dataset_id) if dataset_id else None,
            "severity": severity,
            **redacted,
        },
    )


def _redact(detail: dict[str, Any]) -> dict[str, Any]:
    """Strip secret-like values from an alert detail (SC-007).

    Drops any value that looks like a credential (long high-entropy token,
    AWS access key, etc.) and any nested ``payload``/``raw``/``token``/
    ``value`` keys.
    """
    redacted: dict[str, Any] = {}
    for key, value in detail.items():
        if key in {"payload", "raw", "secret", "password", "token", "value", "ciphertext"}:
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


__all__ = ["emit_security_alert"]
