# Contract: Deployment REST API

**Feature**: 001-one-click-platform-deployment | **Version**: v1 | **Date**: 2026-09-13

REST API exposed by the control plane. Consumed by the CLI (this feature) and the Web UI (feature 007). All endpoints require an authenticated, authorised caller (federated identity via cloud IAM); all traffic over TLS only (FR-017). Errors follow RFC 9457 problem+json.

**Base path**: `/api/v1`

---

## 1. Platforms

### POST /platforms — register & deploy (the "one click", FR-001)

Request:

```json
{
  "config": { "...": "full platform config — see platform-config-schema.md" },
  "approval_ref": "string, required iff environment=production (FR-010)"
}
```

Responses:
- `202 Accepted` — `{ "platform_id": "uuid", "run_id": "uuid", "status": "queued" }`
- `422 Unprocessable Entity` — **all** validation errors at once (FR-003, SC-004):

```json
{
  "type": "https://datafoundry.example/errors/validation",
  "title": "Configuration validation failed",
  "status": 422,
  "errors": [
    { "path": "region", "code": "region_capability_unsupported",
      "message": "Region us-west1 does not support capability 'orchestration'",
      "remediation": "Choose one of: us-central1, europe-west1, australia-southeast1" },
    { "path": "capabilities.semantic_layer", "code": "dependency_missing",
      "message": "semantic_layer requires catalog",
      "remediation": "Enable 'catalog' or disable 'semantic_layer'" }
  ]
}
```

- `409 Conflict` — duplicate platform name in cloud scope (FR-013): `{ "code": "name_taken", "scope": "gcp/projects/acme" }`
- `403 Forbidden` — missing cloud permissions, with precise list (FR-018): `{ "code": "insufficient_permissions", "missing": ["storage.buckets.create", ...] }`

### GET /platforms — list platforms visible to caller

`200` → `{ "items": [PlatformSummary], "next_cursor": "..." }`
PlatformSummary: `id, name, provider, region, environment_type, status, owner, created_at`.

### GET /platforms/{platform_id} — platform detail + latest health (US3)

`200` →

```json
{
  "id": "uuid", "name": "customer-analytics", "provider": "gcp",
  "region": "australia-southeast1", "environment_type": "production",
  "status": "ready", "owner": "alice@corp",
  "capabilities_enabled": ["storage_zones","catalog","ingestion","monitoring"],
  "storage_utilisation": { "bronze_bytes": 0, "silver_bytes": 0, "gold_bytes": 0 },
  "health": [ { "component": "catalog", "status": "healthy", "last_check_at": "...", "detail": null } ],
  "latest_run": { "run_id": "uuid", "status": "succeeded", "finished_at": "...", "duration_seconds": 1310 },
  "recent_failures": [ { "run_id": "uuid", "step": "orchestration", "error": "...", "at": "..." } ]
}
```

(FR-007, US3-AC2/AC3: failed components flagged with reason and last check time.)

### GET /platforms/{platform_id}/config — export configuration (FR-011, US2-AC1)

`200` → `{ "version": 3, "config_yaml": "...", "config_hash": "sha256:...", "git_ref": "abc123" }`
Guarantee: contains no plaintext secrets (secret-scan enforced; SC-006).

### DELETE /platforms/{platform_id} — destroy platform

`202` → `{ "run_id": "uuid", "run_type": "destroy" }`. Production requires `?approval_ref=`.

---

## 2. Deployment Runs

### GET /platforms/{platform_id}/runs — auditable history (FR-014)

`200` → `{ "items": [ { "run_id", "run_type", "status", "initiated_by", "config_version", "started_at", "finished_at", "duration_seconds", "outcome" } ] }`

### GET /runs/{run_id} — progress view (FR-008, US1-AC3)

`200` →

```json
{
  "run_id": "uuid", "platform_id": "uuid", "status": "running",
  "steps": [
    { "position": 1, "key": "validate-config", "status": "succeeded", "started_at": "...", "finished_at": "..." },
    { "position": 7, "key": "storage-zones",   "status": "running" },
    { "position": 11, "key": "catalog",        "status": "pending" },
    { "position": 12, "key": "orchestration",  "status": "skipped", "detail": "capability disabled" }
  ],
  "failure": null
}
```

Failed step shape: `{ "status": "failed", "error_detail": "Quota exceeded: ...", "attempt": 2 }`.

### POST /runs/{run_id}/retry — retry from failed step (FR-009)

`202` → run resumes at the failed step; `409` if run not in `failed`/`paused` state.

### POST /runs/{run_id}/rollback — rollback (FR-009, SC-005)

`202` → destroys resources created by this run only (per-run workspace isolation, R-06); `409` if run not `failed`.

---

## 3. Validation & Capabilities (pre-flight, no side effects)

### POST /validate — validate a config without deploying (SC-004)

Request: `{ "config": {...} }` → `200 { "valid": true }` or `422` with the same all-errors body as POST /platforms.

### GET /capabilities — capability catalog (FR-012)

`200` → `{ "items": [ { "key": "catalog", "display_name": "Metadata Catalog", "selectable": true, "depends_on": ["storage_zones"], "providers": ["aws","gcp"] } ] }`

### GET /providers/{provider}/regions?capability=orchestration — region support matrix

`200` → `{ "regions": [ { "id": "australia-southeast1", "capabilities_supported": [...] } ] }`

---

## 4. Health

### POST /platforms/{platform_id}/health-checks — trigger re-check (US3)

`202` → `{ "check_id": "uuid" }`; results appear via GET platform detail.

### GET /healthz — control-plane liveness (unauthenticated)

`200` → `{ "status": "ok", "version": "..." }`

---

## Cross-cutting rules

- **AuthN/AuthZ**: every mutating endpoint checks the caller is authorised for platform creation/update/destroy (FR-001 "authorised user"); authorisation failures → `403` with missing-permission detail (FR-018).
- **Idempotency**: `POST /platforms` accepts `Idempotency-Key` header; replays return the original run.
- **Audit**: every mutating call writes an AuditRecord (who/when/what/outcome) — FR-014.
- **No secrets in responses or logs** — SC-006.
- **Async model**: deploy/update/destroy/retry/rollback return `202` + run id; clients poll `GET /runs/{run_id}` (UI may add SSE/websocket later without contract change).
