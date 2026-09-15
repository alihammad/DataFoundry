# Contract: Gate Configuration Schema

**Feature**: 004-data-quality-gates | **Version**: v1 | **Date**: 2026-09-15

Declarative, version-controlled definition of a quality gate bound to a layer transition for a dataset (FR-001, FR-018). Cloud-independent YAML; validated by a strict Pydantic model (mirrors feature 001 PlatformConfig strictness). Secret-scanned on every write (no plaintext secrets).

**Base path**: gate configs are submitted via `POST /datasets/{dataset_id}/gates/{transition}` (see [quality-api.md](./quality-api.md)).

---

## Schema

```yaml
transition: bronze_to_silver        # ingestion_to_bronze | bronze_to_silver |
                                   # silver_to_gold | gold_to_consumable
environment_overrides:             # optional; per-environment severity (FR-005)
  production:
    uniqueness_customer_id: critical
  development:
    volume_check: warning
tests:
  - name: uniqueness_customer_id
    category: uniqueness
    severity: critical
    parameters:
      columns: [customer_id]
  - name: nullability_email
    category: nullability
    severity: error
    parameters:
      columns: [email]
  - name: freshness_check
    category: freshness
    severity: warning
    parameters:
      max_staleness_minutes: 30
  - name: volume_check
    category: volume
    severity: critical
    parameters:
      min_records: 1000
      max_deviation_pct: 20
  - name: reconciliation_totals
    category: reconciliation
    severity: critical
    parameters:
      sql: "SELECT SUM(amount) AS total FROM silver_orders"
      tolerance_pct: 0.5
```

---

## Fields

| Field | Type | Required | Constraints | Notes |
|---|---|---|---|---|
| `transition` | enum | yes | one of the four transitions | FR-001 |
| `environment_overrides` | map | no | `{env: {test_name: severity}}` | per-environment severity (FR-005) |
| `tests` | list | yes | ≥1 test; at least one CRITICAL or ERROR | fail-closed guarantee (FR-002) |
| `tests[].name` | string | yes | unique per gate | |
| `tests[].category` | enum | yes | one of the 17 categories (FR-003) | |
| `tests[].severity` | enum | yes | `critical`/`error`/`warning`/`informational` | FR-004 |
| `tests[].parameters` | map | yes | category-specific thresholds/expressions | per category |

**Test categories** (FR-003): `schema`, `type`, `nullability`, `uniqueness`, `completeness`, `validity`, `referential_integrity`, `reconciliation`, `freshness`, `volume`, `distribution`, `business_rule`, `security`, `contract`, `transformation`, `statistical`.

**Severity semantics** (FR-004): `critical`/`error` block by default; `warning` continues with notification; `informational` records only.

**Validation rules** (all errors at once):
1. Schema conformance (strict Pydantic model).
2. At least one test with severity `critical` or `error` (fail-closed, FR-002).
3. Test names unique within the gate.
4. Parameters valid for the category (e.g. `freshness` requires `max_staleness_minutes`; `uniqueness` requires `columns`).
5. Secret-scan passes on the whole config.

**Versioning**: each accepted config increments `config_version` per `(dataset, transition)`; the version active when a batch started is recorded with its results (FR-013, R-03).