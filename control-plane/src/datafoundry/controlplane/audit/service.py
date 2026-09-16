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

    # -- feature 004 quality actions (T012, FR-011/FR-012, SC-007) ----------
    #
    # Quality entities are dataset-scoped; the audit record's ``platform_id``
    # is left unset and the dataset id is carried in the payload. Every payload
    # is secret-scanned by ``record`` before persist (SC-007).

    def gate_defined(
        self,
        *,
        actor: str,
        dataset_id: uuid.UUID,
        gate_id: uuid.UUID,
        transition: str,
        config_version: int,
        config_hash: str,
    ) -> AuditRecord:
        return self.record(
            actor=actor,
            action="gate.defined",
            payload={
                "dataset_id": str(dataset_id),
                "gate_id": str(gate_id),
                "transition": transition,
                "config_version": config_version,
                "config_hash": config_hash,
            },
        )

    def gate_updated(
        self,
        *,
        actor: str,
        dataset_id: uuid.UUID,
        gate_id: uuid.UUID,
        transition: str,
        config_version: int,
        config_hash: str,
    ) -> AuditRecord:
        return self.record(
            actor=actor,
            action="gate.updated",
            payload={
                "dataset_id": str(dataset_id),
                "gate_id": str(gate_id),
                "transition": transition,
                "config_version": config_version,
                "config_hash": config_hash,
            },
        )

    def gate_run(
        self,
        *,
        actor: str,
        dataset_id: uuid.UUID,
        gate_id: uuid.UUID,
        report_id: uuid.UUID,
        run_id: uuid.UUID,
        decision: str,
        config_version: int,
    ) -> AuditRecord:
        return self.record(
            actor=actor,
            action="gate.run",
            payload={
                "dataset_id": str(dataset_id),
                "gate_id": str(gate_id),
                "report_id": str(report_id),
                "run_id": str(run_id),
                "decision": decision,
                "config_version": config_version,
            },
        )

    def contract_registered(
        self,
        *,
        actor: str,
        dataset_id: uuid.UUID,
        contract_id: uuid.UUID,
        version: int,
        origin: str,
    ) -> AuditRecord:
        return self.record(
            actor=actor,
            action="contract.registered",
            payload={
                "dataset_id": str(dataset_id),
                "contract_id": str(contract_id),
                "version": version,
                "origin": origin,
            },
        )

    def contract_inferred(
        self,
        *,
        actor: str,
        dataset_id: uuid.UUID,
        contract_id: uuid.UUID,
        version: int,
    ) -> AuditRecord:
        return self.record(
            actor=actor,
            action="contract.inferred",
            payload={
                "dataset_id": str(dataset_id),
                "contract_id": str(contract_id),
                "version": version,
            },
        )

    def contract_approved(
        self,
        *,
        actor: str,
        dataset_id: uuid.UUID,
        contract_id: uuid.UUID,
        version: int,
        approval_status: str,
    ) -> AuditRecord:
        return self.record(
            actor=actor,
            action="contract.approved",
            payload={
                "dataset_id": str(dataset_id),
                "contract_id": str(contract_id),
                "version": version,
                "approval_status": approval_status,
            },
        )

    def quarantine_replayed(
        self,
        *,
        actor: str,
        dataset_id: uuid.UUID,
        entry_id: uuid.UUID,
        replay_run_id: uuid.UUID,
        attempt_count: int,
    ) -> AuditRecord:
        return self.record(
            actor=actor,
            action="quarantine.replayed",
            payload={
                "dataset_id": str(dataset_id),
                "entry_id": str(entry_id),
                "replay_run_id": str(replay_run_id),
                "attempt_count": attempt_count,
            },
        )

    def override_granted(
        self,
        *,
        actor: str,
        dataset_id: uuid.UUID,
        report_id: uuid.UUID,
        override_id: uuid.UUID,
        authorising_identity: str,
        expiry: str,
    ) -> AuditRecord:
        return self.record(
            actor=actor,
            action="override.granted",
            payload={
                "dataset_id": str(dataset_id),
                "report_id": str(report_id),
                "override_id": str(override_id),
                "authorising_identity": authorising_identity,
                "expiry": expiry,
            },
        )

    def override_expired(
        self,
        *,
        actor: str,
        dataset_id: uuid.UUID,
        override_id: uuid.UUID,
        report_id: uuid.UUID,
    ) -> AuditRecord:
        return self.record(
            actor=actor,
            action="override.expired",
            payload={
                "dataset_id": str(dataset_id),
                "override_id": str(override_id),
                "report_id": str(report_id),
            },
        )

    # -- feature 002 ingestion actions (T013, FR-014, SC-007) -----------------

    def source_registered(
        self,
        *,
        actor: str,
        platform_id: uuid.UUID,
        source_id: uuid.UUID,
        source_name: str,
        source_type: str,
    ) -> AuditRecord:
        return self.record(
            actor=actor,
            action="source.registered",
            platform_id=platform_id,
            payload={
                "source_id": str(source_id),
                "source_name": source_name,
                "source_type": source_type,
            },
        )

    def source_tested(
        self,
        *,
        actor: str,
        platform_id: uuid.UUID,
        source_id: uuid.UUID,
        ok: bool,
        detail: str | None = None,
    ) -> AuditRecord:
        return self.record(
            actor=actor,
            action="source.tested",
            platform_id=platform_id,
            payload={
                "source_id": str(source_id),
                "ok": ok,
                "detail": detail,
            },
        )

    def config_created(
        self,
        *,
        actor: str,
        platform_id: uuid.UUID,
        source_id: uuid.UUID,
        config_id: uuid.UUID,
        version: int,
        config_hash: str,
    ) -> AuditRecord:
        return self.record(
            actor=actor,
            action="config.created",
            platform_id=platform_id,
            payload={
                "source_id": str(source_id),
                "config_id": str(config_id),
                "version": version,
                "config_hash": config_hash,
            },
        )

    def config_updated(
        self,
        *,
        actor: str,
        platform_id: uuid.UUID,
        source_id: uuid.UUID,
        config_id: uuid.UUID,
        version: int,
        config_hash: str,
    ) -> AuditRecord:
        return self.record(
            actor=actor,
            action="config.updated",
            platform_id=platform_id,
            payload={
                "source_id": str(source_id),
                "config_id": str(config_id),
                "version": version,
                "config_hash": config_hash,
            },
        )

    def pipeline_paused(
        self,
        *,
        actor: str,
        platform_id: uuid.UUID,
        pipeline_id: uuid.UUID,
    ) -> AuditRecord:
        return self.record(
            actor=actor,
            action="pipeline.paused",
            platform_id=platform_id,
            payload={"pipeline_id": str(pipeline_id)},
        )

    def pipeline_resumed(
        self,
        *,
        actor: str,
        platform_id: uuid.UUID,
        pipeline_id: uuid.UUID,
    ) -> AuditRecord:
        return self.record(
            actor=actor,
            action="pipeline.resumed",
            platform_id=platform_id,
            payload={"pipeline_id": str(pipeline_id)},
        )

    def run_triggered(
        self,
        *,
        actor: str,
        platform_id: uuid.UUID,
        pipeline_id: uuid.UUID,
        run_id: uuid.UUID,
        trigger: str,
    ) -> AuditRecord:
        return self.record(
            actor=actor,
            action="run.triggered",
            platform_id=platform_id,
            payload={
                "pipeline_id": str(pipeline_id),
                "run_id": str(run_id),
                "trigger": trigger,
            },
        )

    def run_retried(
        self,
        *,
        actor: str,
        platform_id: uuid.UUID,
        pipeline_id: uuid.UUID,
        run_id: uuid.UUID,
        retry_of: uuid.UUID,
    ) -> AuditRecord:
        return self.record(
            actor=actor,
            action="run.retried",
            platform_id=platform_id,
            payload={
                "pipeline_id": str(pipeline_id),
                "run_id": str(run_id),
                "retry_of": str(retry_of),
            },
        )
