# Contract: Dataset Schema

**Feature**: 003-medallion-processing | **Version**: v1 | **Date**: 2026-09-15

Logical dataset definition in a Medallion layer (FR-001, FR-014). Cloud-independent JSON; validated by a strict Pydantic model. Secret-scanned on every write.

**Base path**: datasets are submitted via `POST /datasets` (see [processing-api.md](./processing-api.md)).

---

## Schema

```json
{
  "platform_id": "uuid",
  "name": "customer_silver",
  "layer": "silver",
  "schema_definition": {
    "customer_id": { "type": "integer", "nullable": false },
    "email":       { "type": "string",  "nullable": false },
    "created_at":  { "type": "timestamp", "nullable": false }
  },
  "owner_identity": "user@acme.com",
  "steward_identity": "steward@acme.com",
  "domain": "customer",
  "description": "Cleaned customer master",
  "classification": "internal",
  "refresh_metadata": { "schedule": "daily", "freshness_target_minutes": 1440 }
}
```

---

## Fields

| Field | Type | Required | Constraints | Notes |
|---|---|---|---|---|
| `platform_id` | UUID | yes | | |
| `name` | string | yes | `^[a-z][a-z0-9-]{2,62}$` | unique per platform |
| `layer` | enum | yes | `bronze`/`silver`/`gold` | FR-001 |
| `schema_definition` | map | yes | `{column: {type, nullable}}` | |
| `owner_identity` | string | yes | | FR-009 |
| `steward_identity` | string | no | | FR-014 |
| `domain` | string | no | | FR-014 |
| `description` | text | no | | FR-014 |
| `classification` | enum | yes | `public`/`internal`/`confidential`/`restricted`/`highly_restricted` | FR-014 |
| `refresh_metadata` | map | no | schedule/freshness | FR-014 |

**Column types**: `integer`, `string`, `float`, `boolean`, `timestamp`, `date`, `decimal`, `json`, `binary`.

**Rule**: Gold datasets require `owner_identity`, `description`, `quality_score`, and `refresh_metadata` before reaching CONSUMABLE (FR-009).