# Contract: Semantic REST API

**Feature**: 006-semantic-layer | **Version**: v1 | **Date**: 2026-09-15

REST API exposed by the control plane for the semantic layer. Consumed by the CLI (this feature) and the Web UI (feature 007, catalog display). AuthN/AuthZ reuses feature 001 (`api/auth.py`, federated identity) + feature 005 access policies; all traffic TLS-only; errors follow RFC 9457 problem+json.

**Base path**: `/api/v1`

---

## 1. Semantic models

### POST /semantic/models — define a semantic model (FR-001, FR-003)

Request: full semantic model config (see [semantic-model-schema.md](./semantic-model-schema.md)).

Responses:
- `201` — `{ "model_id": "uuid", "version": 1, "certification_state": "draft" }`
- `422` — all errors at once (unknown category, invalid formula, duplicate business term, secret-scan hit).

### GET /semantic/models/{model_id} — export a semantic model (FR-003)

`200` → `{ "model_id", "domain", "version", "certification_state", "config_yaml", "config_hash" }`.

### GET /semantic/models — list semantic models

`200` → `{ "items": [ { "model_id", "domain", "version", "certification_state" } ] }`.

---

## 2. Metrics

### POST /semantic/models/{model_id}/metrics — define a metric (FR-001, FR-006)

Request: metric definition (name, business_definition, formula, dimensions, bound_datasets, owner).

Responses:
- `201` — `{ "metric_id": "uuid" }`
- `422` — invalid formula, duplicate business term, secret-scan hit.

### GET /semantic/metrics/{metric_id} — describe a metric (US1-AC3, FR-006)

`200` → `{ "metric_id", "name", "business_definition", "formula", "dimensions", "bound_datasets", "owner_identity", "quality_score", "freshness", "lineage", "certification_state", "version" }`.

### POST /semantic/metrics/{metric_id}/query — query a metric (FR-002, FR-007, FR-008, FR-012)

Request:

```json
{
  "dimensions": ["customer", "time"],
  "filters": { "time": { "gte": "2026-01-01", "lt": "2026-02-01" } },
  "as_of": "2026-09-01"
}
```

`200` →

```json
{
  "metric_id": "uuid",
  "value": 12345.67,
  "dimensions": { "customer": "acme", "time": "2026-01" },
  "definition_version": 3,
  "dataset_versions": { "gold_orders": 7 },
  "freshness": "2026-09-14T00:00:00Z",
  "quality_state": "passed",
  "deprecation_notice": null
}
```

`403` if the caller is not authorised for the metric's classification (FR-007). `409` if the underlying data failed its quality gate and policy refuses (FR-008). `410` if the metric is deprecated past its availability period (FR-010).

---

## 3. Semantic tests (FR-004, FR-014)

### POST /semantic/models/{model_id}/tests — define a semantic test

Request: test definition (see [semantic-test-schema.md](./semantic-test-schema.md)).

`201` → `{ "test_id": "uuid" }`.

### POST /semantic/tests/{test_id}/run — run a semantic test

`200` → `{ "test_id", "status": "passed", "measured_value": { "actual": 100, "expected": 100 } }`.

---

## 4. Publications (FR-003, FR-004, FR-005)

### POST /semantic/models/{model_id}/publish — propose a publication

Request: `{ "change_classification": "breaking" }`.

Responses:
- `201` — `{ "publication_id": "uuid", "approval_status": "pending" }` (breaking requires approval)
- `422` — semantic tests failed; publication blocked with failure detail (FR-004).

### POST /publications/{publication_id}/approve — approve a publication (FR-005)

`200` → `{ "approval_status": "approved", "published_at": "..." }`. Notifies registered consumers of breaking changes (FR-005).

### GET /semantic/models/{model_id}/publications — list publications + history

`200` → `{ "items": [ { "publication_id", "version", "change_classification", "approval_status", "published_at" } ] }`.

---

## 5. Consumers (FR-005, FR-010)

### POST /semantic/metrics/{metric_id}/consumers — register a consumer

Request: `{ "consumer_identity": "team@acme.com", "consumption_path": "bi" }`.

`201` → `{ "registration_id": "uuid" }`.

### GET /semantic/metrics/{metric_id}/consumers — list registered consumers

`200` → `{ "items": [ { "registration_id", "consumer_identity", "consumption_path" } ] }`.

---

## 6. Discovery (FR-011, US4)

### GET /semantic/discovery?q=customer+revenue — search business terms

`200` → `{ "items": [ { "metric_id", "name", "business_definition", "owner_identity", "quality_score", "freshness", "lineage", "certification_state", "consuming_teams" } ] }`.

Certified (published) definitions distinguished from drafts; drafts hidden from general users or clearly marked (US4-AC2).

---

## 7. Deprecation (FR-010)

### POST /semantic/metrics/{metric_id}/deprecate — deprecate a metric

Request: `{ "successor_metric_id": "uuid", "deprecation_period_days": 30 }`.

`200` → `{ "certification_state": "deprecated", "successor_metric_id": "uuid" }`. Notifies registered consumers (FR-010). Queries return a deprecation notice with results, or are refused after the deprecation period (FR-010).