# Contract: Data Contract Schema

**Feature**: 004-data-quality-gates | **Version**: v1 | **Date**: 2026-09-15

Schema agreement for a dataset (FR-006, FR-007). Validated at ingestion; violations classified breaking / non-breaking / warning. Origin explicit or inferred (inferred requires owner approval before gating promotion — constitution V).

**Base path**: contracts are submitted via `POST /datasets/{dataset_id}/contracts/register` or `.../infer` (see [quality-api.md](./quality-api.md)).

---

## Schema

```json
{
  "dataset_id": "uuid",
  "schema_definition": {
    "customer_id": { "type": "integer", "nullable": false },
    "email":       { "type": "string",  "nullable": false },
    "created_at":  { "type": "timestamp", "nullable": false }
  }
}
```

---

## Fields

| Field | Type | Required | Constraints | Notes |
|---|---|---|---|---|
| `dataset_id` | UUID | yes | | |
| `schema_definition` | map | yes | `{column: {type, nullable}}` | column names + types + nullability |

**Column types**: `integer`, `string`, `float`, `boolean`, `timestamp`, `date`, `decimal`, `json`, `binary`.

---

## Violation classification (FR-006, constitution IV)

| Change | Classification | Action |
|---|---|---|
| Column type change (e.g. `integer`→`string`) | `breaking` | blocks promotion |
| Column removed | `breaking` | blocks promotion |
| Additive nullable column | `non_breaking` | allowed, recorded |
| Additive non-nullable column | `breaking` | blocks promotion |
| Nullability relaxed (nullable→non-nullable) | `breaking` | blocks promotion |
| Nullability tightened (non-nullable→nullable) | `non_breaking` | allowed, recorded |
| Other observed deviation | `warning` | recorded, notified |

**Rule**: `breaking` violations block promotion (FR-006, SC-007).

---

## Inference (FR-007, US2-AC3/AC4)

Where no explicit contract exists, the **first** successful ingestion infers a contract from the observed schema and marks it `pending` approval. The owner approves, edits, or rejects it. Only after approval does the contract gate promotion. Inference is deterministic (observed schema → pending approval), never auto-approved (constitution V).

**Approval status**: `pending` → `approved` | `rejected`.