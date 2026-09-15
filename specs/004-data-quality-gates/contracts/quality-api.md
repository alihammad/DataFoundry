# Contract: Quality REST API

**Feature**: 004-data-quality-gates | **Version**: v1 | **Date**: 2026-09-15

REST API exposed by the control plane for the quality control system. Consumed by the CLI (this feature) and the Web UI (feature 007, quality dashboards). AuthN/AuthZ reuses feature 001 (`api/auth.py`, federated identity); all traffic TLS-only; errors follow RFC 9457 problem+json.

**Base path**: `/api/v1`

---

## 1. Gates

### POST /datasets/{dataset_id}/gates/{transition} — define a gate (FR-001, FR-018)

`transition` is one of `ingestion_to_bronze`, `bronze_to_silver`, `silver_to_gold`, `gold_to_consumable`.

Request: full gate config (see [gate-config-schema.md](./gate-config-schema.md)).

Responses:
- `201` — `{ "gate_id": "uuid", "config_version": 1 }`
- `422` — all errors at once (unknown category, invalid severity, gate with no CRITICAL/ERROR test, secret-scan hit).

### GET /datasets/{dataset_id}/gates/{transition} — export gate config (FR-018)

`200` → `{ "gate_id", "transition", "config_version": 3, "config_yaml": "...", "config_hash": "sha256:..." }`.

### POST /gates/{gate_id}/run — run the gate against a batch (FR-001, FR-013)

Request:

```json
{ "run_id": "uuid", "batch_id": "uuid", "environment": "production" }
```

`200` →

```json
{
  "report_id": "uuid",
  "decision": "block",
  "overall_status": "failed",
  "tests_run": 4, "tests_passed": 3, "tests_warned": 0, "tests_failed": 1,
  "config_version": 3,
  "results": [
    { "test": "uniqueness_customer_id", "category": "uniqueness",
      "status": "failed", "failed_record_count": 3, "measured_value": { "duplicates": 3 } }
  ]
}
```

`decision` is `promote` iff no CRITICAL/ERROR test is `failed` or `not_run` (R-03, FR-002).

### GET /gates/{gate_id}/reports/{report_id} — gate report detail (US1-AC3, FR-015)

`200` → full report + per-test results with failed-record refs for drill-down (FR-015).

---

## 2. Tests

Test definitions live inside gate configs (gate-config-schema.md). Read-only listing helper:

### GET /datasets/{dataset_id}/tests — list configured tests for a dataset

`200` → `{ "items": [ { "test_id", "name", "category", "severity", "parameters" } ] }`.

---

## 3. Contracts (data contracts, FR-006, FR-007)

### POST /datasets/{dataset_id}/contracts/register — register an explicit contract

Request: schema definition (see [contract-schema.md](./contract-schema.md)).

Responses:
- `201` — `{ "contract_id": "uuid", "version": 1, "origin": "explicit" }` (approved immediately, FR-006, US2-AC1)
- `422` — invalid schema definition rejected at once.

### POST /datasets/{dataset_id}/contracts/infer — infer a contract from observed schema (FR-007, US2-AC3)

`201` → `{ "contract_id": "uuid", "version": 1, "origin": "inferred", "approval_status": "pending" }`. Never auto-approved (constitution V).

### POST /contracts/{contract_id}/approve — approve an inferred contract (FR-007, US2-AC4)

`200` → `{ "approval_status": "approved" }` (or `reject` variant). Only after approval does the contract gate promotion (FR-007 rule in data-model.md).

### GET /datasets/{dataset_id}/contracts — list contracts + violations

`200` → `{ "items": [ { "contract_id", "version", "origin", "approval_status", "violations": [ { "classification", "change_description", "action_taken" } ] } ] }`.

---

## 4. Quarantine (FR-008, FR-009, FR-010, US3-AC1/AC2/AC3, FR-015 drill-down target)

### GET /datasets/{dataset_id}/quarantine — list quarantine entries (US3-AC3)

Query params: `source`, `pipeline_id`, `batch_id`, `failure_reason`, `date_from`, `date_to`.

`200` → `{ "items": [ { "entry_id", "batch_id", "payload_ref", "failure_reason", "failed_test", "attempt_count", "replay_eligible", "retention_expiry", "quarantined_at" } ] }`.

### POST /quarantine/{entry_id}/replay — replay a quarantined record (FR-009, US3-AC2)

`202` → `{ "replay_run_id": "uuid" }`. Replay re-enters the record at the appropriate stage; must not duplicate processed records (FR-009). `409` if `retention_expiry` passed (FR-010) or entry not replay-eligible.

### GET /quarantine/{entry_id} — quarantine entry detail (FR-015 drill-down)

`200` → full entry + failure context (FR-008).

---

## 5. Overrides (FR-011, FR-012, US5-AC1/AC2/AC3)

### POST /reports/{report_id}/override — grant an override for a blocked run

Request:

```json
{
  "authorising_identity": "user@acme.com",
  "reason": "Known upstream incident; data verified manually",
  "expiry": "2026-09-16T00:00:00Z",
  "impact_assessment": "3 downstream dashboards affected for <24h"
}
```

Responses:
- `201` — `{ "override_id": "uuid", "status": "active" }`
- `422` — incomplete override rejected (missing reason/expiry/impact/identity) (FR-011)
- `403` — caller lacks override authority; attempt recorded (US5-AC2).

### GET /datasets/{dataset_id}/overrides — list overrides (audit history, FR-012)

`200` → `{ "items": [ { "override_id", "report_id", "authorising_identity", "reason", "expiry", "status", "granted_at" } ] }`.

---

## 6. Quality scores & observability (FR-013, FR-014, FR-015, US6-AC1/AC2)

### GET /datasets/{dataset_id}/quality — current score + history

`200` →

```json
{
  "dataset_id": "uuid",
  "score": 87.5,
  "window_start": "...", "window_end": "...",
  "history": [ { "report_id", "decision", "overall_status", "tests_failed", "ran_at" } ]
}
```

### GET /datasets/{dataset_id}/quality/history — per-run results for trend (US6-AC1)

`200` → `{ "items": [ { "report_id", "decision", "overall_status", "tests_run", "tests_passed", "tests_warned", "tests_failed", "config_version", "ran_at" } ] }`.

### GET /reports/{report_id} — drill into a run (US6-AC2, FR-015)

`200` → report + per-test results + failed-record refs + related quarantine entries.