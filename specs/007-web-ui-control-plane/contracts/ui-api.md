# Contract: UI-Owned Backend REST API

**Feature**: 007-web-ui-control-plane | **Version**: v1 | **Date**: 2026-09-16

REST API exposed by the control plane for the UI-owned capabilities (saved queries, notification channels, UI roles, pending approvals, audit-log search, static serving). Consumed by the Web UI (this feature). AuthN/AuthZ reuses feature 001 (`api/auth.py`, federated identity); all traffic TLS-only; errors follow RFC 9457 problem+json. The UI reads all business data through the existing features 001–006 APIs — this contract covers only the UI-owned additions.

**Base path**: `/api/v1`

---

## 1. Static SPA serving

### GET / — serve the UI

Serves the built SPA (`index.html` + assets). Non-API routes fall back to `index.html` for client-side routing (R-05). `/api/*` and `/healthz` are never swallowed by the fallback.

Responses:
- `200` — HTML/asset.
- `404` — unknown asset (not an SPA route).

---

## 2. Saved queries (FR-010, US4-AC4)

### POST /ui/saved-queries — save a query

Request: `{ "name", "sql_text", "dataset_bindings": ["uuid"], "sharing": "private|shared" }`.

Responses:
- `201` — `{ "query_id": "uuid" }`
- `422` — all errors at once (invalid SQL, missing binding, secret-scan hit).

### GET /ui/saved-queries — list my saved queries

`200` → `{ "items": [ { "query_id", "name", "owner_identity", "sharing", "created_at" } ] }`.

### GET /ui/saved-queries/{query_id} — get a saved query

`200` → `{ "query_id", "name", "sql_text", "dataset_bindings", "sharing", "owner_identity", "created_at" }`.
`403` if the caller is not the owner and the query is not shared with them (US4-AC4).
`404` if not found.

### POST /ui/saved-queries/{query_id}/share — share a query

Request: `{ "shared_with_identity": "user@example.com" }`.

Responses:
- `201` — `{ "share_id": "uuid" }`
- `403` — caller is not the owner.
- `409` — already shared with that user.

### POST /ui/saved-queries/{query_id}/run — run a saved query

Executes the query through the existing query API, re-evaluating the **runner's** access rights (spec Key Entity).

Responses:
- `200` — query results (subject to the caller's access/protection policies, FR-010, SC-006).
- `403` — caller lacks access to a bound dataset.
- `422` — query execution error.

---

## 3. Notification channels (FR-014)

### POST /ui/notifications — configure a channel

Request: `{ "platform_id", "channel_type": "email|webhook|slack", "name", "config", "event_types": ["..."], "enabled": true }`.

Responses:
- `201` — `{ "channel_id": "uuid" }`
- `422` — invalid config, secret-scan hit (FR-022).

### GET /ui/notifications?platform_id= — list channels

`200` → `{ "items": [ { "channel_id", "platform_id", "channel_type", "name", "event_types", "enabled" } ] }` (config never returned — FR-022).

### PUT /ui/notifications/{channel_id} — update a channel

`200` — `{ "channel_id", "updated_at" }`. `403` if not authorised. `409` on concurrent-edit conflict (FR-017).

### DELETE /ui/notifications/{channel_id} — remove a channel

`204`. `403` if not authorised.

---

## 4. UI roles (FR-013, FR-014)

### POST /ui/roles — create a role

Request: `{ "name", "scope": "platform|dataset|column", "permissions": ["..."], "platform_scope": ["uuid"], "dataset_scope": [ { "dataset_id", "columns": ["..."] } ] }`.

Responses:
- `201` — `{ "role_id": "uuid" }`
- `422` — invalid scope/permissions.

### GET /ui/roles — list roles

`200` → `{ "items": [ { "role_id", "name", "scope", "permissions" } ] }`.

### POST /ui/roles/{role_id}/assign — assign a user to a role

Request: `{ "user_identity": "user@example.com" }`.

Responses:
- `201` — `{ "assignment_id": "uuid" }`
- `403` — caller is not an administrator.
- `409` — already assigned.

### GET /ui/roles/{role_id}/assignments — list assignments

`200` → `{ "items": [ { "assignment_id", "user_identity", "granted_at" } ] }`.

---

## 5. Pending approvals (FR-016)

### GET /ui/approvals?type=&state=&platform_id= — list pending approvals

Aggregates existing approval records (production changes, overrides, semantic publications, contracts).

`200` → `{ "items": [ { "approval_id", "approval_type", "requester", "payload_ref", "decision_state", "created_at" } ] }`.

### POST /ui/approvals/{approval_id}/decide — approve or deny

Request: `{ "decision": "approved|denied", "reasoning": "..." }`.

Responses:
- `200` — `{ "approval_id", "decision_state", "decided_at" }`
- `403` — caller is not a configured approver.
- `422` — missing reasoning.

---

## 6. Audit log search (FR-014)

### GET /ui/audit-log?from=&to=&identity=&resource=&action=&cursor=&limit=

Searches the existing audit service (feature 001).

`200` → `{ "items": [ { "id", "actor_identity", "action", "resource", "before_state", "after_state", "created_at" } ], "next_cursor" }`.

---

## Cross-cutting rules

- **Auth**: all `/ui/*` endpoints require an authenticated caller (feature 001 `get_caller`); admin-only actions (roles, approvals) additionally check the caller's role.
- **Errors**: RFC 9457 problem+json; 422 carries `errors[]` (path, code, message, remediation); 403 carries `missing[]`; 409 carries `code` (e.g. `version_conflict`).
- **Audit**: every mutating `/ui/*` action is audited with actor, timestamp, resource, before/after state (FR-015).
- **Secrets**: saved-query SQL, notification config, and role definitions are secret-scanned on write (FR-022); notification config is never returned (FR-022, SC-006).