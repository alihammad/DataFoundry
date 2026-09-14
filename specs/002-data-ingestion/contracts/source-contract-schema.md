# Contract: Source Data Contract Schema

**Feature**: 002-data-ingestion | **Version**: v1 | **Date**: 2026-09-14

Defines the source data contract (the schema agreement between producer and consumer, constitution IV, FR-010) and the change-classification rules applied when an observed schema differs from a recorded contract.

---

## Contract document

```yaml
contract:
  source: crm-prod
  object: customer
  origin: explicit            # explicit | inferred
  approval_status: approved   # pending | approved | rejected
  schema:
    customer_id:
      type: integer
      nullable: false
    name:
      type: string
      nullable: false
    email:
      type: string
      nullable: false
    created_date:
      type: date
      nullable: false
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `source` | string | yes | source name |
| `object` | string | yes | table name / file pattern |
| `origin` | enum | yes | `explicit` (authored) \| `inferred` (from observed schema) |
| `approval_status` | enum | yes | `pending` \| `approved` \| `rejected` |
| `schema.<col>.type` | enum | yes | `integer` \| `string` \| `boolean` \| `float` \| `date` \| `timestamp` \| `binary` \| `decimal` \| `json` |
| `schema.<col>.nullable` | bool | yes | |

**Inferred contracts** (no explicit contract exists, FR-010, US3-AC3) are generated from the first successful ingestion's observed schema and marked `approval_status: pending`. They do **not** gate promotion until approved (constitution V — deterministic inference, human approval).

---

## Change classification rules (FR-010, constitution IV)

When an observed schema is compared against a recorded contract, each difference is classified:

| Change | Classification | Effect |
|---|---|---|
| New **nullable** column | `warning` | recorded, notified; promotion proceeds |
| Column type widened compatibly (e.g. int → bigint) | `non-breaking` | recorded; promotion proceeds |
| New **non-nullable** column (no default) | `breaking` | blocks promotion; alert |
| Column removed | `breaking` | blocks promotion; alert |
| Type change incompatible (e.g. `integer` → `string`) | `breaking` | blocks promotion; alert |
| Nullability tightened (nullable → non-nullable) | `breaking` | blocks promotion; alert |

**Rule**: any `breaking` change marks the batch `ingested` but **not** `ingestion_validated` (FR-009, SC-004) and raises an alert naming the offending column and change (US3-AC2, FR-020). `warning` and `non-breaking` changes are recorded in batch metadata and do not block.

---

## Validation hand-off

Contract compatibility is checked at ingestion (feature 002). The full severity model (CRITICAL/ERROR/WARNING/INFORMATIONAL), the gate report, and the override workflow are specified in feature 004 (data-quality-gates); this contract defines the schema-level input those gates consume.
