# Contract: Source (Ingestion) Configuration Schema

**Feature**: 002-data-ingestion | **Version**: v1 | **Date**: 2026-09-14

Cloud-independent declarative schema for an ingestion configuration (FR-017, SC-008). Mirrors the feature 001 Platform Config philosophy: strict, unknown fields rejected, no plaintext secrets (SC-007), portable across AWS and GCP unchanged.

**API version / kind**: `datafoundry/v1` / `IngestionConfig`

---

## Top-level structure

```yaml
apiVersion: datafoundry/v1
kind: IngestionConfig
metadata:
  name: crm-to-bronze            # ^[a-z][a-z0-9-]{2,62}$
  source: crm-prod               # source name (registered via POST /sources)
source:
  type: postgres                 # postgres | sqlserver | object_storage
  objects:                       # selected tables or files
    - name: customer
      mode: incremental          # full | incremental
      cursor_column: updated_at  # required iff mode=incremental (FR-003)
    - name: orders
      mode: full
  filePattern: "*.parquet"       # object_storage only
schedule: "every 15 minutes"     # or "hourly" | "daily" | cron; omit = manual only
target:
  zone: bronze                   # fixed for MVP (FR-018)
validation:
  reconciliation_tolerance: 0    # max allowed |source - ingested| (FR-009)
  contract_mode: enforce         # enforce | infer (FR-010)
```

---

## Field reference

| Path | Type | Required | Constraints |
|---|---|---|---|
| `apiVersion` | string | yes | `"datafoundry/v1"` |
| `kind` | string | yes | `"IngestionConfig"` |
| `metadata.name` | string | yes | `^[a-z][a-z0-9-]{2,62}$` |
| `metadata.source` | string | yes | existing source name |
| `source.type` | enum | yes | `postgres` \| `sqlserver` \| `object_storage` |
| `source.objects[]` | array | yes* | *database sources; ≥1 object |
| `source.objects[].name` | string | yes | table name |
| `source.objects[].mode` | enum | yes | `full` \| `incremental` |
| `source.objects[].cursor_column` | string | cond | required iff `mode=incremental` |
| `source.filePattern` | string | cond | required iff `type=object_storage` |
| `schedule` | string | no | interval/cron; omitted = manual |
| `target.zone` | enum | yes | `bronze` (MVP) |
| `validation.reconciliation_tolerance` | int | no | default 0 |
| `validation.contract_mode` | enum | no | `enforce` (default) \| `infer` |

---

## Validation rules (all errors returned at once)

1. Schema conformance + strict unknown-field rejection.
2. `source.type` matches the registered source's type.
3. Every `incremental` object declares a valid `cursor_column`.
4. `schedule`, if present, is a well-formed interval or cron expression.
5. `filePattern` present iff `object_storage`; `objects[]` present iff database type.
6. Secret-scan passes on the entire document (no credential values anywhere — SC-007).

---

## Portability guarantee (SC-008)

The same `IngestionConfig` document deploys and runs on both AWS and GCP without modification. Cloud-specific details (bucket locations, secret-manager backend) are resolved from the owning platform's runtime state, never encoded in the config. Object-storage `location` values use `s3://` / `gs://` schemes that map to the platform's `CloudGateway` adapters structurally.
