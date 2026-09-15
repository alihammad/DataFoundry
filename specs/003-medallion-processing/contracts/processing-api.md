# Contract: Processing REST API

**Feature**: 003-medallion-processing | **Version**: v1 | **Date**: 2026-09-15

REST API exposed by the control plane for the Medallion processing layer. Consumed by the CLI (this feature) and the Web UI (feature 007, dataset/lineage views). AuthN/AuthZ reuses feature 001 (`api/auth.py`, federated identity); all traffic TLS-only; errors follow RFC 9457 problem+json.

**Base path**: `/api/v1`

---

## 1. Datasets

### POST /datasets — register a dataset (FR-014)

Request:

```json
{
  "platform_id": "uuid",
  "name": "customer_silver",
  "layer": "silver",
  "schema_definition": { "customer_id": { "type": "integer", "nullable": false } },
  "owner_identity": "user@acme.com",
  "classification": "internal"
}
```

Responses:
- `201` — `{ "dataset_id": "uuid" }`
- `422` — all validation errors at once (unknown layer, bad name, missing owner).

### GET /datasets — list datasets visible to caller

`200` → `{ "items": [ { "dataset_id", "name", "layer", "owner", "classification", "promotion_state", "quality_score" } ] }`.

### GET /datasets/{dataset_id} — dataset detail (US4-AC3)

`200` → dataset fields + current `promotion_state`, the gate results that produced it, and the last transition timestamp.

---

## 2. Transformations (FR-005, FR-017)

### POST /transformations — define a transformation

Request: full transformation definition (see [transformation-schema.md](./transformation-schema.md)).

Responses:
- `201` — `{ "transformation_id": "uuid", "version": 1 }`
- `422` — all errors at once (invalid source/target layer, bad logic, secret-scan hit).

### GET /transformations/{transformation_id} — export transformation (FR-005)

`200` → `{ "transformation_id", "version": 3, "logic_definition": "...", "logic_hash": "sha256:..." }`.

### POST /transformations/{transformation_id}/run — run the transformation (FR-005, FR-017)

Request:

```json
{ "input_dataset_id": "uuid", "environment": "production" }
```

`200` →

```json
{
  "output_dataset_id": "uuid",
  "output_version": 4,
  "record_count": 1234,
  "quarantined_count": 3,
  "gate_report_id": "uuid",
  "promotion_state": "silver_validated"
}
```

`promotion_state` reflects the gate decision (feature 004): `silver_validated` on pass, `blocked` on a failed critical gate (FR-007, US4-AC1).

### GET /transformations/{transformation_id}/runs — run history (FR-017)

`200` → `{ "items": [ { "run_id", "input_version", "output_version", "record_count", "gate_report_id", "promotion_state", "ran_at" } ] }`.

---

## 3. Promotion (FR-007, FR-008, US4)

### GET /datasets/{dataset_id}/promotion — current state + history (US4-AC3)

`200` →

```json
{
  "dataset_id": "uuid",
  "current_state": "silver",
  "history": [ { "state", "gate_report_id", "transitioned_at", "blocked_reason" } ]
}
```

### POST /datasets/{dataset_id}/promotion/override — override a blocked gate (FR-008, US5)

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
- `201` — `{ "override_id": "uuid", "status": "active" }`; promotion proceeds (US5-AC1)
- `422` — incomplete override rejected (FR-008)
- `403` — caller lacks override authority; attempt recorded (US5-AC2).

---

## 4. Lineage (FR-015, SC-006)

### GET /datasets/{dataset_id}/lineage — lineage for a dataset

`200` → `{ "upstream": [ { "dataset_id", "layer", "transformation_id", "transformation_version" } ], "downstream": [ ... ] }`. Navigable in both directions (FR-015).

---

## 5. Query (FR-016, US5)

### POST /datasets/{dataset_id}/query — run a SQL query against Silver/Gold

Request:

```json
{ "sql": "SELECT customer_id, SUM(amount) FROM customer_silver GROUP BY customer_id" }
```

`200` →

```json
{
  "columns": [ "customer_id", "sum" ],
  "rows": [ [ 1, 250.0 ], [ 2, 180.0 ] ],
  "row_count": 2
}
```

Lightweight, no warehouse load (DuckDB, R-03). `403` if the caller is not authorised for the dataset (US5-AC2).

### POST /datasets/{dataset_id}/query/download — download a result set (US5-AC3)

`200` → CSV/Parquet download. Column-level protection policies applied: protected columns remain masked/tokenised per policy (FR-016, US5-AC3).