# Contract: Ingestion REST API

**Feature**: 002-data-ingestion | **Version**: v1 | **Date**: 2026-09-14

REST API exposed by the control plane for self-service ingestion. Consumed by the CLI (this feature) and the Web UI (feature 007, "Add Data Source" wizard). AuthN/AuthZ reuses feature 001 (`api/auth.py`, federated identity); all traffic TLS-only (FR-016); errors follow RFC 9457 problem+json.

**Base path**: `/api/v1`

---

## 1. Data Sources

### POST /sources — register a source (wizard step 1, FR-002)

Request (database example):

```json
{
  "platform_id": "uuid",
  "name": "crm-prod",
  "type": "postgres",
  "config": {
    "host": "crm.internal", "port": 5432, "database": "crm",
    "credentials": { "secretRef": "crm-ro-user" }
  }
}
```

Object-storage example:

```json
{
  "platform_id": "uuid",
  "name": "events-drop",
  "type": "object_storage",
  "config": { "location": "s3://acme-landing/events", "format": "parquet" }
}
```

Responses:
- `201 Created` — `{ "source_id": "uuid" }`
- `422` — all validation errors at once (unknown source type, bad `secretRef` naming, missing fields).

### POST /sources/{source_id}/test — test connectivity (FR-004, US1-AC1/AC4)

`200` →

```json
{
  "ok": true,
  "detail": null,
  "discovered_schema": [
    { "object": "customer", "columns": [
      { "name": "customer_id", "type": "integer", "nullable": false },
      { "name": "email", "type": "string", "nullable": false } ] }
  ]
}
```

Failure (`ok:false`) classifies the error (US1-AC4):

```json
{ "ok": false, "detail": "authentication_failed", "message": "Credentials rejected by host crm.internal" }
```

`detail` is one of `authentication_failed`, `network_unreachable`, `database_not_found`, `invalid_format`. Credentials are never echoed.

### GET /sources — list sources visible to caller

`200` → `{ "items": [ { "source_id", "name", "type", "owner", "connection_state", "last_test_at" } ] }`

### GET /sources/{source_id} — source detail

`200` → source fields + `secretRef` name only (never a value).

---

## 2. Ingestion Configuration

### POST /sources/{source_id}/config — create/update ingestion config (FR-002)

Request: full ingestion config (see [source-config-schema.md](./source-config-schema.md)).

Responses:
- `201` — `{ "config_id": "uuid", "version": 1, "pipeline_id": "uuid" }` (pipeline created automatically, FR-002 "no custom code")
- `422` — all errors at once (invalid schedule, incremental without cursor column, secret-scan hit).

### GET /sources/{source_id}/config — export config (FR-017)

`200` → `{ "version": 3, "config_yaml": "...", "config_hash": "sha256:..." }`. Guarantee: no plaintext secrets (SC-007).

---

## 3. Pipelines

### GET /pipelines — list pipelines

`200` → `{ "items": [ { "pipeline_id", "name", "state", "schedule", "source", "last_run_status", "last_run_at" } ] }`

### POST /pipelines/{pipeline_id}/run — manual trigger (US4-AC1, FR-011)

`202` → `{ "run_id": "uuid", "trigger": "manual" }`. `409` if a run is already active (R-10).

### POST /pipelines/{pipeline_id}/pause — pause schedule (FR-014, US4-AC3)

`200` → `{ "state": "paused" }`

### POST /pipelines/{pipeline_id}/resume — resume schedule (FR-014)

`200` → `{ "state": "active" }`

### POST /runs/{run_id}/retry — retry a failed run (FR-014, US4-AC2)

`202` → `{ "run_id": "uuid", "trigger": "retry", "retry_of": "uuid" }`. Retry re-reads from the uncommitted watermark so already-ingested records are not duplicated (R-06).

---

## 4. Runs, Batches & History

### GET /pipelines/{pipeline_id}/runs — execution history (FR-013)

`200` → `{ "items": [ { "run_id", "trigger", "status", "outcome", "records_processed", "started_at", "finished_at", "duration_seconds", "failure_reason" } ] }`

### GET /runs/{run_id} — run detail with batches (US4)

`200` →

```json
{
  "run_id": "uuid", "pipeline_id": "uuid", "trigger": "scheduled", "status": "succeeded",
  "outcome": "partial",
  "batches": [
    { "batch_id": "uuid", "source_object": "customer", "status": "ingestion_validated", "record_count": 1000000 },
    { "batch_id": "uuid", "source_object": "orders", "status": "quarantined", "record_count": 0 }
  ]
}
```

### GET /batches/{batch_id} — batch detail + metadata (FR-008, SC-003)

`200` → `{ "batch_id", "source_system", "source_object", "ingested_at", "record_count", "checksum", "status", "metadata": {...} }`

### GET /runs/{run_id}/logs — structured log reference (FR-013)

`200` → `{ "log_ref": "gs://.../runs/<run_id>/log.jsonl" }`

---

## 5. Contracts & Quarantine

### GET /sources/{source_id}/contracts — list contracts

`200` → `{ "items": [ { "contract_id", "object_name", "origin", "approval_status" } ] }`

### POST /contracts/{contract_id}/approve — approve an inferred contract (US3-AC3, FR-010)

`200` → `{ "approval_status": "approved" }`. Requires owner authorisation (constitution V).

### GET /quarantine — list/filter quarantine records (feature 004 extends with replay)

`200` → `{ "items": [ { "record_id", "pipeline_id", "batch_id", "source_object", "failure_reason", "failed_check", "severity", "quarantined_at" } ] }`

Query params: `source_id`, `pipeline_id`, `batch_id`, `failed_check`, `since`, `until` (filtering per BRD §23M).

---

## Cross-cutting rules

- All mutating operations produce an `AuditRecord` (feature 001 `audit/service.py`) and are secret-scanned.
- All run/batch/error payloads are redacted of secret patterns before persistence or response (SC-007).
- Contract validation occurs during ingestion; a breaking change blocks promotion (FR-009) and raises an alert to the owner (FR-020).
