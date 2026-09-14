"""Audit service (T019, FR-014).

Append-only AuditRecord writes for every mutating operation: actor, action,
occurred_at, and a secret-scanned JSONB payload (SC-006 invariant 1 — the
scan pass runs on every write path; payloads containing secret material are
rejected, never stored).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from datafoundry.controlplane.config.secret_scan import SecretFinding, scan_json_payload
from datafoundry.controlplane.db.models import AuditRecord
from sqlalchemy.orm import Session


class AuditSecretLeakError(RuntimeError):
    """Raised when an audit payload contains secret-like material (SC-006)."""

    def __init__(self, findings: list[SecretFinding]) -> None:
        self.findings = findings
        summary = ", ".join(f"{f.path}:{f.kind}" for f in findings)
        super().__init__(f"audit payload rejected — secret material detected ({summary})")


class AuditService:
    """Writes append-only audit records."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        *,
        actor: str,
        action: str,
        payload: dict[str, Any] | None = None,
        platform_id: uuid.UUID | None = None,
        occurred_at: datetime | None = None,
    ) -> AuditRecord:
        """Persist one audit record.

        The payload is secret-scanned before write; detection raises
        ``AuditSecretLeakError`` and nothing is stored (fail closed).
        """
        findings = scan_json_payload(payload or {})
        if findings:
            raise AuditSecretLeakError(findings)

        record = AuditRecord(
            platform_id=platform_id,
            actor=actor,
            action=action,
            occurred_at=occurred_at or datetime.now(UTC),
            payload=payload or {},
        )
        self.session.add(record)
        self.session.flush()
        return record

    # Convenience wrappers for the canonical mutating actions (FR-014).

    def deploy_requested(
        self,
        *,
        actor: str,
        platform_id: uuid.UUID,
        run_id: uuid.UUID,
        config_version: int,
        config_hash: str,
    ) -> AuditRecord:
        return self.record(
            actor=actor,
            action="deploy.requested",
            platform_id=platform_id,
            payload={
                "run_id": str(run_id),
                "config_version": config_version,
                "config_hash": config_hash,
            },
        )

    def retry_executed(
        self, *, actor: str, platform_id: uuid.UUID, run_id: uuid.UUID, from_step: str
    ) -> AuditRecord:
        return self.record(
            actor=actor,
            action="run.retry",
            platform_id=platform_id,
            payload={"run_id": str(run_id), "from_step": from_step},
        )

    def rollback_executed(
        self, *, actor: str, platform_id: uuid.UUID, run_id: uuid.UUID
    ) -> AuditRecord:
        return self.record(
            actor=actor,
            action="rollback.executed",
            platform_id=platform_id,
            payload={"run_id": str(run_id)},
        )

    def destroy_requested(
        self,
        *,
        actor: str,
        platform_id: uuid.UUID,
        run_id: uuid.UUID,
        approval_ref: str | None = None,
    ) -> AuditRecord:
        return self.record(
            actor=actor,
            action="destroy.requested",
            platform_id=platform_id,
            payload={"run_id": str(run_id), "approval_ref": approval_ref},
        )

    def config_exported(
        self, *, actor: str, platform_id: uuid.UUID, version: int, config_hash: str
    ) -> AuditRecord:
        return self.record(
            actor=actor,
            action="config.exported",
            platform_id=platform_id,
            payload={"version": version, "config_hash": config_hash},
        )
