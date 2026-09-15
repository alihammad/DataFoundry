# Contract: Security REST API

**Feature**: 005-security-data-protection | **Version**: v1 | **Date**: 2026-09-15

REST API exposed by the control plane for the security & data-protection system. Consumed by the CLI (this feature) and the Web UI (feature 007, security dashboards). AuthN/AuthZ reuses feature 001 (`api/auth.py`, federated identity); all traffic TLS-only; errors follow RFC 9457 problem+json.

**Base path**: `/api/v1`

---

## 1. Classification (FR-001, FR-002, FR-020)

### POST /datasets/{dataset_id}/classification — set a dataset/column classification

Request:

```json
{ "level": "restricted", "column": null, "policy_id": "uuid" }
```

Responses:
- `201` — `{ "classification_id": "uuid", "level": "restricted", "policy_id": "uuid" }`
- `422` — invalid level, unknown policy, or (on downgrade) missing authorisation.
- `403` — caller lacks authorisation to downgrade (FR-020).

### GET /datasets/{dataset_id}/classification — get classification + protection metadata (FR-017)

`200` → `{ "dataset_id", "level", "policy_id", "columns": [ { "column", "mechanism", "masking_status", "authorised_roles", "key_ref_id" } ] }`. Never returns key material (SC-003).

---

## 2. Protection policies (FR-002, FR-003)

### POST /policies — define a protection policy

Request:

```json
{
  "name": "restricted-encrypt",
  "classification": "restricted",
  "mechanism": "encrypt",
  "key_ref_id": "uuid",
  "authorised_roles": ["data-engineer"],
  "detokenise_roles": ["security-officer"]
}
```

Responses:
- `201` — `{ "policy_id": "uuid" }`
- `422` — invalid mechanism, missing key_ref for encrypt/tokenise, secret-scan hit.

### GET /policies — list policies

`200` → `{ "items": [ { "policy_id", "name", "classification", "mechanism", "authorised_roles" } ] }`.

---

## 3. Keys (FR-008, FR-009, FR-010)

### POST /keys — register a key reference (no material)

Request:

```json
{ "kms": "aws_kms", "key_id": "alias/restricted", "version": 1, "rotation_schedule": "90d", "usage_permissions": ["data-engineer"] }
```

Responses:
- `201` — `{ "key_ref_id": "uuid", "version": 1 }`
- `422` — invalid kms, missing key_id, secret-scan hit (key material must never be submitted).

### POST /keys/{key_ref_id}/rotate — rotate to a new version (FR-009)

`200` → `{ "key_ref_id", "version": 2, "lifecycle_state": "active" }`. Historical data remains readable via prior versions; rotation audited.

### POST /keys/{key_ref_id}/revoke — revoke a key (FR-008)

`200` → `{ "lifecycle_state": "revoked" }`. Further decryption with it fails and is audited.

### GET /keys/{key_ref_id} — key reference status (never material)

`200` → `{ "key_ref_id", "kms", "key_id", "version", "lifecycle_state", "rotation_schedule", "usage_permissions" }`.

---

## 4. Tokens (FR-011, FR-012)

### POST /datasets/{dataset_id}/tokens/tokenise — tokenise a column value

Request:

```json
{ "column": "email", "value": "a@x.com", "deterministic": true }
```

Responses:
- `200` — `{ "token": "tok_abc123" }` (deterministic: same input → same token, FR-011).
- `403` — caller lacks tokenisation permission.

### POST /datasets/{dataset_id}/tokens/detokenise — detokenise (authorised only, FR-012)

Request:

```json
{ "column": "email", "token": "tok_abc123", "purpose": "approved-analytics" }
```

Responses:
- `200` — `{ "value": "a@x.com" }` (audited with purpose, FR-012).
- `403` — caller lacks detokenisation right; attempt recorded (FR-015).

---

## 5. Access enforcement (FR-013)

### POST /access/decide — evaluate the enforcement chain for a request

Request:

```json
{ "identity": "user@acme.com", "resource": "dataset:uuid:column:email", "action": "read" }
```

`200` →

```json
{
  "outcome": "denied",
  "classification_consulted": "restricted",
  "policy_applied": "uuid",
  "reason": "masked per policy; detokenisation requires key-use permission"
}
```

Evaluated at query time — no cached grants (spec Edge Cases).

---

## 6. Security audit (FR-014, FR-015)

### GET /security-audit — search audit records

Query params: `identity`, `dataset_id`, `action`, `date_from`, `date_to`.

`200` → `{ "items": [ { "audit_id", "occurred_at", "identity", "dataset_id", "column", "action", "purpose", "result", "protection_service_ref" } ] }`. Tamper-evident (chained hash) — see data-model.md.

### GET /security-audit/{audit_id} — full record incl. hash chain

`200` → full record + `prev_hash` + `hash` for tamper verification (US6-AC1).