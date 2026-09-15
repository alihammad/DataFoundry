# Contract: Transformation Definition Schema

**Feature**: 003-medallion-processing | **Version**: v1 | **Date**: 2026-09-15

Declarative, version-controlled definition of a transformation converting input dataset(s) to an output dataset (FR-005, FR-017). Cloud-independent JSON; validated by a strict Pydantic model (mirrors feature 001 PlatformConfig strictness). Secret-scanned on every write (no plaintext secrets).

**Base path**: transformations are submitted via `POST /transformations` (see [processing-api.md](./processing-api.md)).

---

## Schema

```json
{
  "name": "customer_silver_transform",
  "source_layer": "bronze",
  "target_layer": "silver",
  "dedup_keys": ["customer_id"],
  "reconciliation_tolerance": 0.5,
  "logic": {
    "type": "silver",
    "cleansing": [
      { "column": "email", "op": "trim" },
      { "column": "age", "op": "coerce_type", "to": "integer" }
    ],
    "standardisation": [
      { "column": "country", "op": "upper" }
    ],
    "schema_enforcement": {
      "customer_id": { "type": "integer", "nullable": false },
      "email": { "type": "string", "nullable": false }
    }
  }
}
```

Gold example (aggregation + reconciliation):

```json
{
  "name": "customer_360_gold",
  "source_layer": "silver",
  "target_layer": "gold",
  "reconciliation_tolerance": 0.5,
  "logic": {
    "type": "gold",
    "aggregation": {
      "group_by": ["customer_id"],
      "measures": [ { "name": "total_amount", "op": "sum", "column": "amount" } ]
    },
    "reconciliation": {
      "sql": "SELECT SUM(amount) AS total FROM silver_orders",
      "tolerance_pct": 0.5
    }
  }
}
```

---

## Fields

| Field | Type | Required | Constraints | Notes |
|---|---|---|---|---|
| `name` | string | yes | unique per platform | |
| `source_layer` | enum | yes | `bronze` or `silver` | one layer below target (FR-005) |
| `target_layer` | enum | yes | `silver` or `gold` | |
| `dedup_keys` | array | no | column names | business keys for dedup (US2-AC3) |
| `reconciliation_tolerance` | float | no | ≥0 | Gold reconciliation tolerance (FR-010) |
| `logic` | object | yes | type-specific | declarative definition |

**`logic.type`**: `silver` (cleansing/type-convert/standardise/dedup/schema-enforce) or `gold` (aggregate/reconcile).

**Validation rules** (all errors at once):
1. Schema conformance (strict Pydantic model).
2. `source_layer` is one layer below `target_layer`.
3. `dedup_keys` reference columns in the input schema.
4. `logic` valid for the type (e.g. `gold` requires `aggregation`; `reconciliation` requires `tolerance_pct`).
5. Secret-scan passes on the whole definition.

**Versioning**: each accepted definition increments `version` per `name`; every run records the transformation version, input dataset versions, output version, gate results, and quarantined counts (FR-017). Prior runs remain traceable to the version that produced them (US2-AC4).