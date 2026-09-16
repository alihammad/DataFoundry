"""Ingestion engine core (T009).

Executes the batch pipeline ``extract -> validate -> land/quarantine``,
staging-then-commit Bronze landing (R-05), batch metadata writes, and
per-source-object high-watermark persistence advanced only on a validated
commit (R-06, FR-003/FR-014/SC-005).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from datafoundry.controlplane.db.models import (
    BatchStatus,
    IngestionBatch,
    IngestionPipeline,
    IngestionRun,
    IngestionRunStatus,
    RunOutcome,
    SourceContract,
)
from datafoundry.controlplane.ingestion.contract import infer_contract
from datafoundry.controlplane.ingestion.gateway import LandingGateway, SourceGateway
from datafoundry.controlplane.ingestion.security import redact_ingestion
from datafoundry.controlplane.ingestion.validation import (
    validate_contract_compat,
    validate_file,
)
from sqlalchemy.orm import Session


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _ingestion_date(now: datetime) -> str:
    return now.date().isoformat()


def run_ingestion(
    session: Session,
    *,
    gateway: SourceGateway,
    run_id: str,
    landing: LandingGateway | None = None,
) -> IngestionRun:
    """Execute an ingestion run to its next terminal state.

    ``gateway`` is the source gateway (extract); ``landing`` is the Bronze
    landing gateway (defaults to a simulated one). Tests drive this directly
    via the ``process_ingestion_run`` fixture.
    """
    from datafoundry.controlplane.ingestion.gateway import SimulatedLandingGateway

    landing = landing or SimulatedLandingGateway()

    run = session.get(IngestionRun, run_id)
    if run is None:
        raise ValueError(f"no ingestion run {run_id}")
    if run.status != IngestionRunStatus.queued:
        return run

    pipeline = session.get(IngestionPipeline, run.pipeline_id)
    source = pipeline.source
    config = pipeline.config

    run.status = IngestionRunStatus.running
    run.started_at = _utcnow()
    session.flush()

    now = _utcnow()
    date_str = _ingestion_date(now)
    total_records = 0
    outcomes: list[RunOutcome] = []
    failed = False

    # Determine the objects to process: database tables or object-storage files.
    objects = _resolve_objects(config, gateway, source.id)

    for obj in objects:
        batch = IngestionBatch(
            run_id=run.id,
            pipeline_id=pipeline.id,
            source_object=obj["name"],
            source_system=source.name,
            status=BatchStatus.ingesting,
        )
        session.add(batch)
        session.flush()

        try:
            if source.type == "object_storage":
                _process_file_object(
                    session,
                    gateway=gateway,
                    landing=landing,
                    pipeline=pipeline,
                    source=source,
                    batch=batch,
                    obj=obj,
                    date_str=date_str,
                    now=now,
                )
            else:
                _process_table_object(
                    session,
                    gateway=gateway,
                    landing=landing,
                    pipeline=pipeline,
                    source=source,
                    config=config,
                    batch=batch,
                    obj=obj,
                    date_str=date_str,
                    now=now,
                )
            total_records += batch.record_count
            outcomes.append(RunOutcome.success)
        except Exception as exc:
            batch.status = BatchStatus.failed
            batch.metadata_json = {
                **batch.metadata_json,
                "failure_reason": redact_ingestion(str(exc)),
            }
            failed = True
            outcomes.append(RunOutcome.failed)
            session.flush()

    run.records_processed = total_records
    if failed:
        run.status = IngestionRunStatus.failed
        run.outcome = RunOutcome.failed
        run.failure_reason = "one or more source objects failed to ingest"
    else:
        run.status = IngestionRunStatus.succeeded
        run.outcome = RunOutcome.success
    run.finished_at = _utcnow()
    session.flush()
    return run


def _resolve_objects(config, gateway: SourceGateway, source_id: str) -> list[dict[str, Any]]:
    """Resolve the list of objects to process for a run.

    Database sources: the configured tables. Object-storage sources: the files
    currently present (each file is one object).
    """
    if config.source_type == "object_storage":
        files = gateway.list_files(str(source_id))
        return [{"name": f["name"], "file": f} for f in files]
    return [dict(o) for o in config.selected_objects.get("objects", [])]


def _process_table_object(
    session: Session,
    *,
    gateway: SourceGateway,
    landing: LandingGateway,
    pipeline: IngestionPipeline,
    source,
    config,
    batch: IngestionBatch,
    obj: dict[str, Any],
    date_str: str,
    now: datetime,
) -> None:
    """Extract + land one database table object."""
    object_name = obj["name"]
    mode = obj.get("mode", "full")
    cursor_column = obj.get("cursor_column")
    watermark = None
    if mode == "incremental" and cursor_column:
        watermark = pipeline.high_watermarks.get(object_name)

    rows = gateway.extract(
        str(source.id),
        object_name=object_name,
        cursor_column=cursor_column if mode == "incremental" else None,
        watermark=watermark if mode == "incremental" else None,
    )

    # Serialise rows to JSON payload for staging.
    payload = json.dumps(rows, default=str).encode("utf-8")
    landing.write_staging(
        batch_id=str(batch.id),
        source_object=object_name,
        source_name=source.name,
        ingestion_date=date_str,
        payload=payload,
        filename=f"{object_name}.json",
    )

    # Contract compatibility check (US3) — blocking critical changes.
    contract = _get_contract(session, source.id, object_name)
    if contract is not None:
        observed = _observed_schema(rows)
        violations = validate_contract_compat(contract.schema_definition, observed)
        breaking = [v for v in violations if v["classification"] == "breaking"]
        if breaking:
            batch.status = BatchStatus.ingested
            batch.record_count = len(rows)
            batch.ingested_at = now
            batch.metadata_json = {
                "source_object": object_name,
                "source_system": source.name,
                "ingestion_date": date_str,
                "batch_id": str(batch.id),
                "pipeline_id": str(pipeline.id),
                "record_count": len(rows),
                "status": "ingested",
                "contract_violations": violations,
            }
            landing.commit_batch(
                batch_id=str(batch.id),
                source_object=object_name,
                source_name=source.name,
                ingestion_date=date_str,
                metadata=batch.metadata_json,
            )
            # Blocked from promotion: stays ingested, never ingestion_validated.
            return

    # Land + validate.
    batch.record_count = len(rows)
    batch.ingested_at = now
    batch.status = BatchStatus.ingestion_validated
    batch.metadata_json = {
        "source_object": object_name,
        "source_system": source.name,
        "ingestion_date": date_str,
        "batch_id": str(batch.id),
        "pipeline_id": str(pipeline.id),
        "record_count": len(rows),
        "status": "ingestion_validated",
    }
    landing.commit_batch(
        batch_id=str(batch.id),
        source_object=object_name,
        source_name=source.name,
        ingestion_date=date_str,
        metadata=batch.metadata_json,
    )

    # Infer a contract on first successful ingestion (US3-AC3).
    if contract is None:
        infer_contract(
            session,
            source_id=source.id,
            object_name=object_name,
            schema_definition=_observed_schema(rows),
            created_by=source.owner_identity,
        )

    # Advance high-watermark only on a validated commit (R-06).
    if mode == "incremental" and cursor_column and rows:
        max_cursor = max(r[cursor_column] for r in rows if r.get(cursor_column) is not None)
        if max_cursor is not None:
            pipeline.high_watermarks[object_name] = max_cursor
            session.flush()


def _process_file_object(
    session: Session,
    *,
    gateway: SourceGateway,
    landing: LandingGateway,
    pipeline: IngestionPipeline,
    source,
    batch: IngestionBatch,
    obj: dict[str, Any],
    date_str: str,
    now: datetime,
) -> None:
    """Validate + land/quarantine one object-storage file."""
    file = obj["file"]
    file_name = file["name"]
    content = gateway.read_file(str(source.id), file_name)

    # File validation (FR-006): exists, readable, format, encoding, checksum.
    validation = validate_file(
        content=content,
        file_name=file_name,
        declared_format=file.get("format"),
        declared_checksum=file.get("checksum"),
    )
    if not validation["ok"]:
        # Route to quarantine; batch is quarantined (partial success).
        batch.status = BatchStatus.quarantined
        batch.record_count = 0
        batch.ingested_at = now
        batch.metadata_json = {
            "source_object": file_name,
            "source_system": source.name,
            "ingestion_date": date_str,
            "batch_id": str(batch.id),
            "pipeline_id": str(pipeline.id),
            "record_count": 0,
            "status": "quarantined",
            "failure_reason": validation["reason"],
            "failed_check": validation["failed_check"],
        }
        landing.write_quarantine(
            batch_id=str(batch.id),
            source_object=file_name,
            payload_ref=file_name,
            metadata=batch.metadata_json,
        )
        return

    # Valid file: land with file-level metadata (FR-008).
    batch.record_count = 1
    batch.checksum = file.get("checksum")
    batch.ingested_at = now
    batch.status = BatchStatus.ingestion_validated
    batch.metadata_json = {
        "source_object": file_name,
        "source_system": source.name,
        "ingestion_date": date_str,
        "batch_id": str(batch.id),
        "pipeline_id": str(pipeline.id),
        "record_count": 1,
        "status": "ingestion_validated",
        "file": {
            "name": file_name,
            "size": file.get("size"),
            "checksum": file.get("checksum"),
            "ingestion_timestamp": now.isoformat(),
        },
    }
    landing.commit_batch(
        batch_id=str(batch.id),
        source_object=file_name,
        source_name=source.name,
        ingestion_date=date_str,
        metadata=batch.metadata_json,
    )


def _get_contract(
    session: Session, source_id: str, object_name: str
) -> SourceContract | None:
    return (
        session.query(SourceContract)
        .filter_by(source_id=source_id, object_name=object_name)
        .first()
    )


def _observed_schema(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Infer a ``{column: {type, nullable}}`` schema from extracted rows."""
    schema: dict[str, Any] = {}
    for row in rows:
        for col, value in row.items():
            if col not in schema:
                schema[col] = {
                    "type": _py_type(value),
                    "nullable": value is None,
                }
    return schema


def _py_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


def sha256_hex(data: bytes) -> str:
    """SHA-256 hex digest (config_hash / checksum)."""
    return hashlib.sha256(data).hexdigest()
