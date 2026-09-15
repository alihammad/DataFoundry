# Contract: UI Component / View Contract

**Feature**: 007-web-ui-control-plane | **Version**: v1 | **Date**: 2026-09-16

Describes the UI's views, navigation, and behaviour contract — the frontend's internal contract for what each view renders and how it behaves. Consumed by the Web UI implementation (this feature). Backed by the existing features 001–006 APIs plus the UI-owned API ([ui-api.md](./ui-api.md)).

**Base path**: `/` (SPA). All data via `/api/v1`.

---

## 1. App shell & navigation

- **Layout**: persistent sidebar (platform context switcher, nav sections) + top bar (user identity, auth status) + content area.
- **Platform context** (FR-020): a selected-platform state scopes all views; switching platform re-renders dashboard, lists, and details.
- **Auth** (R-03): in `cloud_iam` mode the API client attaches `Authorization: Bearer <token>` + `x-datafoundry-provider`; in `dev` mode no headers. On 401/403 the UI surfaces the `missing[]` permission explanation (FR-013).
- **Nav sections**: Dashboard, Configure, Pipelines, Catalog, Quality, Admin.

## 2. Dashboard (US1, FR-002, FR-003)

- **Tiles**: platform identity (cloud/region/environment), infrastructure health, pipeline counts (healthy/failed/running), overall quality score, storage utilisation, compute utilisation, cost summary, recent failures, recent deployments.
- **Refresh**: poll on a 60-second interval (SC-003); stale/unavailable tiles show last-known value + timestamp, never a misleading zero (FR-018).
- **Drill-down**: every tile links to its detail view within two navigation steps (FR-003, SC-005).

## 3. Configure wizards (US2, FR-004, FR-005)

- **Wizards**: platform creation (feature 001), data source (feature 002), quality gates (feature 004), classification/protection (feature 005), semantic approval (feature 006).
- **GitOps**: every wizard save flows through the same validation + approval workflow as code (FR-005, SC-004); the UI never bypasses GitOps.
- **Validation**: inline 422 `errors[]` surfaced per field; partial config never silently applied (spec Edge Cases).
- **Approval**: changes requiring approval show pending state and take effect only after approval (US2-AC2).
- **Permissions**: users without permission for an area see edit actions hidden/disabled with explanation (US2-AC3, FR-013).
- **Wizard state**: preserved across session expiry, resumed after re-auth (FR-021).

## 4. Pipelines & runs (US3, FR-006, FR-007)

- **Pipeline list**: state, trigger/pause/resume/retry actions, execution history, logs, metrics, failure details.
- **Retry**: retry runs without duplicating ingested data; history links retry to original (US3-AC2).
- **Quarantine**: browsable with filters (source, pipeline, batch, reason, date range); replay for authorised users (US3-AC3, FR-007).

## 5. Catalog & dataset exploration (US4, FR-008, FR-009, FR-010)

- **Search**: business-term search over datasets and metrics; results show layer, owner, quality score, freshness, consumers (US4-AC1).
- **Dataset detail**: schema, policy-compliant sample preview, quality history, protection status per column, business metadata, navigable lineage graph (US4-AC2, FR-009).
- **Protection**: previews enforce the same protection policies as queries; no privileged UI path to raw protected values (spec Edge Cases, SC-006).
- **SQL editor**: run over Silver/Gold, save/share/download; execution re-evaluates the runner's access rights (FR-010, US4-AC4).

## 6. Quality & monitoring (US5, FR-011, FR-012)

- **Quality views**: per-dataset scores/trends, gate run history with test-level and record-level drill-down, contract violation feed, anomaly indicators, alert history with filters.
- **Drill-down**: failing run → test → failed records within two navigation steps (US5-AC1, SC-005).
- **Observability**: pipeline success rate, duration, throughput, infrastructure utilisation, cost by pipeline/dataset (FR-012).

## 7. Administration (US6, FR-013, FR-014, FR-015, FR-016)

- **Roles**: create roles scoped to platform/dataset/column; assign users; users see exactly the scoped capabilities (US6-AC1).
- **Approvals**: pending requests (production changes, overrides, semantic publications, contracts) visible to approvers with approve/deny + recorded reasoning (FR-016, US6-AC2).
- **Notifications**: channel configuration per platform (FR-014).
- **Audit log**: search by time, identity, resource, action; every admin action appears with actor, timestamp, before/after state (FR-015, US6-AC3).

## 8. Cross-cutting behaviour

- **Concurrency** (FR-017): conflicting saves rejected with current version shown; no silent overwrites.
- **Degradation** (FR-018): backing-service outage → stale/unavailable state with last-known timestamp.
- **Responsive** (FR-019): usable on small screens; lists paginate or virtualise.
- **Secrets** (FR-022, SC-006): never display secrets, key material, credentials, or unprotected sensitive values in any view, preview, log, or download.
- **Cloud-independence** (FR-023, SC-007): identical screens/workflows regardless of cloud.