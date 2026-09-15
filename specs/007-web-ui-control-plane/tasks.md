# Tasks: Web UI Control Plane

**Input**: Design documents from `/specs/007-web-ui-control-plane/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (ui-api.md, ui-contract.md), quickstart.md

**Tests**: Included — the constitution (Principle IV: Shift-Left Testing & Contracts) and plan.md test plan explicitly mandate contract tests, and quickstart.md defines the test suite map (unit / contract / integration / manual E2E).

**Organization**: Tasks are grouped by user story (US1 P1, US2 P1, US3 P2, US4 P2, US5 P3, US6 P3) so each story can be implemented, tested, and delivered independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1, US2, US3, US4, US5, or US6
- Exact file paths included in every task

## Path Conventions

Monorepo per plan.md: `ui/` (new Vite + React + TypeScript SPA), `control-plane/src/datafoundry/controlplane/` (FastAPI service + UI-owned backend additions), `control-plane/tests/`, `docker/`. This feature is the first frontend in the monorepo; it consumes the existing features 001–006 APIs and adds a small set of UI-owned backend capabilities.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Frontend package skeleton, backend static-serving, and shared test harness

- [ ] T001 Create the `ui/` frontend package skeleton per plan.md: `ui/package.json`, `ui/vite.config.ts`, `ui/tsconfig.json`, `ui/index.html`, `ui/src/main.tsx`, `ui/src/app/App.tsx` — Vite + React 18 + TypeScript, with `npm run dev` proxying `/api` to the control plane (R-01).
- [ ] T002 [P] Add frontend dependencies to `ui/package.json`: `react`, `react-dom`, `react-router-dom`, `@tanstack/react-query`, a headless component library (Radix UI primitives), `@tanstack/react-table`; dev deps `typescript`, `vite`, `vitest`, `@testing-library/react`, `@playwright/test` (R-01, R-02). Verify `npm install` resolves.
- [ ] T003 [P] Add backend static SPA serving to `control-plane/src/datafoundry/controlplane/api/ui.py`: mount the built `ui/dist` via `StaticFiles` and a catch-all fallback to `index.html` for non-API routes (excluding `/api/*` and `/healthz`); add `DF_UI_STATIC_DIR` + `DF_UI_BASE_PATH` settings to `config/settings.py` (R-05). Register in `api/app.py`.
- [ ] T004 [P] Create the UI-owned backend package skeleton: `control-plane/src/datafoundry/controlplane/config/ui_schema.py` (strict Pydantic schemas for saved query, notification channel, UI role per data-model.md) and empty router stubs `api/saved_queries.py`, `api/notifications.py`, `api/roles.py`, `api/approvals.py`, `api/audit_log.py` with docstrings.
- [ ] T005 [P] Extend `control-plane/tests/conftest.py` with UI fixtures: a `ui_caller` fixture (dev identity), a `saved_query` fixture, and a `process_ui_action` fixture that drives UI-owned backend actions synchronously (mirroring the feature 001 `process_run` pattern).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: UI-owned persistence, typed API client, app shell, and auth handling that every user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T006 Implement the UI-owned SQLAlchemy models per data-model.md — `UIRole`, `UIRoleAssignment`, `SavedQuery`, `SavedQueryShare`, `NotificationChannel` — in `control-plane/src/datafoundry/controlplane/db/models.py`, including unique constraints and JSONB columns via the existing `with_variant` pattern.
- [ ] T007 Create the Alembic migration for the five new tables (reuse feature 001 migration conventions) — in `control-plane/src/datafoundry/controlplane/db/migrations/`. Verify offline SQL via `alembic upgrade head --sql`.
- [ ] T008 [P] Implement the UI-owned Pydantic schemas per data-model.md (strict, unknown fields rejected; saved-query SQL secret-scanned; notification config secret-scanned; role scope/permissions validated) — in `control-plane/src/datafoundry/controlplane/config/ui_schema.py`.
- [ ] T009 [P] Add UI-originated audit actions to the existing audit service (feature 001 `audit/service.py`): `ui.saved_query.created`, `ui.saved_query.shared`, `ui.notification.configured`, `ui.role.created`, `ui.role.assigned`, `ui.approval.decided` — each secret-scanned (FR-015, FR-022).
- [ ] T010 [P] Create the typed API client in `ui/src/app/api.ts`: base URL from `DF_API_PREFIX`, bearer-token + `x-datafoundry-provider` header attachment in `cloud_iam` mode (R-03), uniform RFC 9457 problem+json parsing (422 `errors[]`, 403 `missing[]`, 409 `code`), and typed wrappers for the features 001–006 endpoints the UI consumes.
- [ ] T011 [P] Create the app shell + routing in `ui/src/app/App.tsx` and `ui/src/app/router.tsx`: persistent sidebar (platform context switcher, nav sections Dashboard/Configure/Pipelines/Catalog/Quality/Admin), top bar (user identity, auth status), content area; selected-platform state scopes all views (FR-020).
- [ ] T012 [P] Create the auth context in `ui/src/app/auth.tsx`: reads the bearer token (memory/sessionStorage), attaches it via the API client, surfaces 401/403 `missing[]` explanations (FR-013), and preserves wizard draft state across session expiry (FR-021).
- [ ] T013 [P] Unit tests for foundational core: UI schema conformance vs data-model.md, secret-scan on saved-query SQL + notification config, audit actions, and the API client's problem+json parsing — in `control-plane/tests/unit/test_ui_core.py` and `ui/tests/`.

**Checkpoint**: Foundation ready — user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Platform dashboard (Priority: P1) 🎯 MVP

**Goal**: An authorised user opens the dashboard and sees the platform at a glance: cloud, region, environment, infrastructure health, pipeline counts (healthy/failed/running), overall data quality score, storage utilisation, compute utilisation, cost summary, recent failures, and recent deployments. From any summary tile the user drills into the underlying detail (FR-002, FR-003).

**Independent Test**: quickstart Scenario 1 — deploy a platform with known state (some healthy pipelines, one failure) and verify every dashboard figure matches the real state and drill-downs navigate correctly.

### Tests for User Story 1 ⚠️ (write first, ensure they FAIL before implementation)

- [ ] T014 [P] [US1] Contract tests for the dashboard data sources: `GET /platforms`, `GET /platforms/{id}`, `GET /platforms/{id}/runs`, `GET /datasets/{id}/quality`, `POST /platforms/{id}/health-checks` return the figures the dashboard renders (health, pipeline counts, quality score, storage/compute utilisation, cost, recent failures/deployments) per ui-contract.md §2 — in `control-plane/tests/contract/test_ui_dashboard_api.py`.
- [ ] T015 [P] [US1] Integration test for quickstart Scenario 1: deploy a platform with known state, render the dashboard, verify every figure matches real state and drill-downs navigate within two steps (FR-003, SC-005) — in `control-plane/tests/integration/test_ui_dashboard_flow.py` and `ui/tests/`.

### Implementation for User Story 1

- [ ] T016 [P] [US1] Implement the dashboard data hook in `ui/src/features/dashboard/useDashboard.ts`: compose platform list/detail, runs, quality, health, and cost via TanStack Query with a 60-second polling interval (SC-003); stale/unavailable tiles show last-known value + timestamp, never a misleading zero (FR-018).
- [ ] T017 [P] [US1] Implement the dashboard view in `ui/src/features/dashboard/Dashboard.tsx`: tiles for platform identity, infrastructure health, pipeline counts, quality score, storage/compute utilisation, cost, recent failures, recent deployments; each tile links to its detail view (FR-003).
- [ ] T018 [US1] Implement the platform context switcher in `ui/src/app/App.tsx`: multi-platform selection re-renders the whole UI for the selected platform (FR-020); drill-down targets deleted since render report "resource no longer exists" and return to a valid view (FR-018).

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently

---

## Phase 4: User Story 2 - Configure everything through the UI (Priority: P1)

**Goal**: A user performs all day-to-day configuration through guided UI experiences: create a platform (feature 001's deployment wizard), add and configure data sources (feature 002's wizard), define and bind quality tests and gates (feature 004), set classifications and protection policies (feature 005), and manage semantic definitions' approval workflows (feature 006). Every configuration change flows through the same version-controlled, approval-based workflow as code-made changes (FR-004, FR-005).

**Independent Test**: quickstart Scenario 2 — complete an end-to-end journey purely in the UI (create platform, add source, configure tests, classify data) and verify each change appears in version control with the correct approval state and takes effect.

### Tests for User Story 2 ⚠️ (write first, ensure they FAIL before implementation)

- [ ] T019 [P] [US2] Contract tests for the UI-owned config endpoints: `POST /ui/saved-queries` (201; 422 invalid SQL/secret-scan), `POST /ui/notifications` (201; 422 invalid config/secret-scan), `POST /ui/roles` (201; 422 invalid scope) per ui-api.md §2–4 — in `control-plane/tests/contract/test_ui_config_api.py`.
- [ ] T020 [P] [US2] Integration test for quickstart Scenario 2: complete the data source wizard in the UI, verify the ingestion config is created/validated/version-controlled/deployable without manual file editing (US2-AC1); a Production change enters the approval workflow and takes effect only after approval (US2-AC2); a user without permission sees edit actions hidden/disabled (US2-AC3, FR-013) — in `control-plane/tests/integration/test_ui_config_flow.py` and `ui/tests/`.

### Implementation for User Story 2

- [ ] T021 [P] [US2] Implement the wizard framework in `ui/src/features/config/wizard.tsx`: multi-step guided forms with inline 422 `errors[]` surfacing per field (spec Edge Cases), draft-state preservation across session expiry (FR-021), and optimistic-concurrency version tokens on save (FR-017).
- [ ] T022 [P] [US2] Implement the platform creation wizard in `ui/src/features/config/PlatformWizard.tsx`: consumes `POST /platforms` + `GET /capabilities` + `GET /providers/{p}/regions` (feature 001), surfaces 202 run + polls `GET /runs/{id}`.
- [ ] T023 [P] [US2] Implement the data source wizard in `ui/src/features/config/SourceWizard.tsx`: consumes the feature 002 ingestion config API, validates + version-controls + makes deployable without manual file editing (US2-AC1).
- [ ] T024 [P] [US2] Implement the quality gate + classification wizards in `ui/src/features/config/QualityWizard.tsx` and `ui/src/features/config/ProtectionWizard.tsx`: consume the feature 004 gate/contract APIs and feature 005 classification/protection APIs.
- [ ] T025 [US2] Implement the approval-aware save flow in `ui/src/features/config/approval.tsx`: changes requiring approval show pending state and take effect only after approval (US2-AC2); UI-made changes are indistinguishable in governance terms from code-made changes (US2-AC4, SC-004).

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently

---

## Phase 5: User Story 3 - Pipeline and run management (Priority: P2)

**Goal**: A data engineer manages pipelines through the UI: view all pipelines with state, trigger runs, pause/resume schedules, retry failures, and inspect execution history, logs, metrics, and failure details per run. Quarantine queues are browsable with filters (source, pipeline, batch, reason, date) and replay can be triggered for fixed entries (FR-006, FR-007).

**Independent Test**: quickstart Scenario 3 — exercise each pipeline action in the UI against a live pipeline and verify the resulting state, history, and logs match.

### Tests for User Story 3 ⚠️ (write first, ensure they FAIL before implementation)

- [ ] T026 [P] [US3] Contract tests for the pipeline/run data sources: `GET /platforms/{id}/runs`, `GET /runs/{id}`, `POST /runs/{id}/retry`, `POST /runs/{id}/rollback`, `GET /datasets/{id}/quarantine`, `POST /quarantine/{id}/replay` per ui-contract.md §4 — in `control-plane/tests/contract/test_ui_pipelines_api.py`.
- [ ] T027 [P] [US3] Integration test for quickstart Scenario 3: trigger a manual run → live status → execution history (US3-AC1); retry a failed run without duplicating data, history links retry to original (US3-AC2); filter quarantine by reason and replay fixed entries (US3-AC3) — in `control-plane/tests/integration/test_ui_pipelines_flow.py` and `ui/tests/`.

### Implementation for User Story 3

- [ ] T028 [P] [US3] Implement the pipeline list view in `ui/src/features/pipelines/PipelineList.tsx`: state, trigger/pause/resume/retry actions, execution history, logs, metrics, failure details (FR-006).
- [ ] T029 [P] [US3] Implement the run detail view in `ui/src/features/pipelines/RunDetail.tsx`: ordered step progress, logs, failure details, retry/rollback actions; retry links to original run (US3-AC2).
- [ ] T030 [US3] Implement the quarantine view in `ui/src/features/pipelines/Quarantine.tsx`: browsable with filters (source, pipeline, batch, reason, date range) and replay for authorised users (FR-007, US3-AC3).

**Checkpoint**: At this point, User Stories 1, 2, AND 3 should all work independently

---

## Phase 6: User Story 4 - Catalog browsing and dataset exploration (Priority: P2)

**Goal**: An analyst searches the catalog ("customer revenue"), sees results with layer, owner, quality score, freshness, and consumers, and opens a dataset to view: schema, sample (subject to protection policies), quality history, lineage graph (upstream and downstream, navigable), protection status per column, and business metadata. From the dataset the analyst launches a query in the SQL editor, saves and shares queries, and downloads results per policy (FR-008, FR-009, FR-010).

**Independent Test**: quickstart Scenario 4 — search a seeded catalog, open a dataset, verify all metadata tabs render real data, run and save a query, and download results with protection policies applied.

### Tests for User Story 4 ⚠️ (write first, ensure they FAIL before implementation)

- [ ] T031 [P] [US4] Contract tests for the catalog/query data sources: catalog search, dataset detail (schema/sample/quality/lineage/protection), `POST /ui/saved-queries` + `POST /ui/saved-queries/{id}/run` + `POST /ui/saved-queries/{id}/share` per ui-api.md §2 and ui-contract.md §5 — in `control-plane/tests/contract/test_ui_catalog_api.py`.
- [ ] T032 [P] [US4] Integration test for quickstart Scenario 4: search a business term → ranked results with owner/quality/freshness (US4-AC1); open a dataset with lineage → navigable graph (US4-AC2); preview/query protected columns → masked/tokenised per rights (US4-AC3, SC-006); share a saved query → colleague opens/runs subject to their own access rights (US4-AC4) — in `control-plane/tests/integration/test_ui_catalog_flow.py` and `ui/tests/`.

### Implementation for User Story 4

- [ ] T033 [P] [US4] Implement the catalog search view in `ui/src/features/catalog/CatalogSearch.tsx`: business-term search over datasets and metrics, results show layer/owner/quality/freshness/consumers (US4-AC1).
- [ ] T034 [P] [US4] Implement the dataset detail view in `ui/src/features/catalog/DatasetDetail.tsx`: schema, policy-compliant sample preview, quality history, protection status per column, business metadata, navigable lineage graph (FR-009, US4-AC2); previews enforce the same protection policies as queries (SC-006).
- [ ] T035 [P] [US4] Implement the SQL editor in `ui/src/features/catalog/SqlEditor.tsx`: run over Silver/Gold via the query API, save/share/download; execution re-evaluates the runner's access rights (FR-010, US4-AC4); download applies the same protection policies (SC-006).
- [ ] T036 [US4] Implement the saved-query + share UI in `ui/src/features/catalog/SavedQueries.tsx`: list/save/share/run saved queries via the UI-owned API (ui-api.md §2).

**Checkpoint**: At this point, User Stories 1, 2, 3, AND 4 should all work independently

---

## Phase 7: User Story 5 - Quality and monitoring views (Priority: P3)

**Goal**: A user monitors data quality across the platform: per-dataset quality scores and trends, gate run history with drill-down to failing tests and records, contract violation feed, freshness and volume anomalies, and alert history. An operations user sees observability dashboards: pipeline success rates, durations, throughput, infrastructure utilisation, and cost by pipeline/dataset (FR-011, FR-012).

**Independent Test**: quickstart Scenario 5 — generate known quality events (failed gate, contract violation, stale data) and verify each appears in the correct view with accurate drill-down.

### Tests for User Story 5 ⚠️ (write first, ensure they FAIL before implementation)

- [ ] T037 [P] [US5] Contract tests for the quality/monitoring data sources: `GET /datasets/{id}/quality`, `GET /datasets/{id}/quality/history`, `GET /reports/{id}`, `GET /datasets/{id}/contracts`, `GET /datasets/{id}/overrides` per ui-contract.md §6 — in `control-plane/tests/contract/test_ui_quality_api.py`.
- [ ] T038 [P] [US5] Integration test for quickstart Scenario 5: a gate failure's failing run/test/failed-record drill-down reachable within two steps (US5-AC1, SC-005); alert history filtered by time/severity shows matching alerts with delivery status (US5-AC2); cost-by-pipeline reconciles with the cost observability source (US5-AC3) — in `control-plane/tests/integration/test_ui_quality_flow.py` and `ui/tests/`.

### Implementation for User Story 5

- [ ] T039 [P] [US5] Implement the quality views in `ui/src/features/quality/QualityViews.tsx`: per-dataset scores/trends, gate run history with test-level and record-level drill-down, contract violation feed, anomaly indicators, alert history with filters (FR-011).
- [ ] T040 [P] [US5] Implement the observability views in `ui/src/features/quality/Observability.tsx`: pipeline success rate, duration, throughput, infrastructure utilisation, cost by pipeline/dataset (FR-012).

**Checkpoint**: At this point, User Stories 1, 2, 3, 4, AND 5 should all work independently

---

## Phase 8: User Story 6 - Administration and access management (Priority: P3)

**Goal**: A platform administrator manages the platform through the UI: users and roles (RBAC at platform, dataset, and column scope), approval workflows (who can approve Production changes, overrides, semantic publications), notification channel configuration, environment settings, and audit log search. All administration actions are themselves audited (FR-013, FR-014, FR-015, FR-016).

**Independent Test**: quickstart Scenario 6 — create a role with scoped permissions, assign a user, and verify the user's UI capabilities match exactly; then search the audit log for the administration actions performed.

### Tests for User Story 6 ⚠️ (write first, ensure they FAIL before implementation)

- [ ] T041 [P] [US6] Contract tests for the admin endpoints: `POST /ui/roles` + `POST /ui/roles/{id}/assign` (201; 403 non-admin; 409 duplicate), `GET /ui/approvals` + `POST /ui/approvals/{id}/decide` (200; 403 non-approver; 422 missing reasoning), `GET /ui/audit-log` (filters by time/identity/resource/action) per ui-api.md §4–6 — in `control-plane/tests/contract/test_ui_admin_api.py`.
- [ ] T042 [P] [US6] Integration test for quickstart Scenario 6: create a role scoped to datasets with column restrictions → user sees exactly the scoped capabilities (US6-AC1); a gate-override request reaches configured approvers who approve/deny with recorded reasoning (US6-AC2, FR-016); searching the audit log shows every admin action with actor/timestamp/before-after (US6-AC3, FR-015) — in `control-plane/tests/integration/test_ui_admin_flow.py` and `ui/tests/`.

### Implementation for User Story 6

- [ ] T043 [P] [US6] Implement the roles + assignments UI in `ui/src/features/admin/Roles.tsx`: create roles scoped to platform/dataset/column, assign users, users see exactly the scoped capabilities (FR-013, FR-014, US6-AC1).
- [ ] T044 [P] [US6] Implement the approvals UI in `ui/src/features/admin/Approvals.tsx`: pending requests (production changes, overrides, semantic publications, contracts) visible to approvers with approve/deny + recorded reasoning (FR-016, US6-AC2).
- [ ] T045 [P] [US6] Implement the notification channels UI in `ui/src/features/admin/Notifications.tsx`: per-platform channel configuration (FR-014); config never displayed (FR-022, SC-006).
- [ ] T046 [US6] Implement the audit log search UI in `ui/src/features/admin/AuditLog.tsx`: search by time, identity, resource, action (FR-014); every admin action appears with actor/timestamp/before-after (FR-015, US6-AC3).

**Checkpoint**: At this point, all user stories should be independently functional

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T047 [P] Add the UI Dockerfile `docker/Dockerfile.ui` (build the SPA, serve via the control plane) and register a `ui` service in `docker/docker-compose.dev.yml` (dev).
- [ ] T048 [P] Add Playwright E2E tests for the quickstart scenarios in `ui/tests/e2e/` (dashboard, config wizard, pipeline actions, catalog query, quality drill-down, admin roles) against a running control plane in `dev` auth mode.
- [ ] T049 [P] Add unit tests for the UI-owned backend core in `control-plane/tests/unit/test_ui_core.py` (schema conformance, secret-scan, audit actions, concurrency version-conflict handling).
- [ ] T050 [P] Security hardening: verify no secrets/key material/credentials/protected values appear in any UI view, preview, export, or network response (FR-022, SC-006); previews enforce the same protection policies as queries (spec Edge Cases).
- [ ] T051 [P] Documentation updates: expand `ui/README.md` (dev/build/run), `control-plane/README.md` (UI serving), and root `README.md` (UI feature) per plan.md.
- [ ] T052 Run quickstart validation: execute all six quickstart scenarios in the UI; verify ruff + alembic offline SQL clean for the backend additions and `npm run build` + `npm test` clean for the frontend.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational phase completion
  - User stories can then proceed in parallel (if staffed)
  - Or sequentially in priority order (P1 → P2 → P3)
- **Polish (Final Phase)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) — no dependencies on other stories
- **User Story 2 (P1)**: Can start after Foundational (Phase 2) — may integrate with US1 but independently testable
- **User Story 3 (P2)**: Can start after Foundational (Phase 2) — may integrate with US1/US2 but independently testable
- **User Story 4 (P2)**: Can start after Foundational (Phase 2) — may integrate with US1/US2/US3 but independently testable
- **User Story 5 (P3)**: Can start after Foundational (Phase 2) — may integrate with US1/US3 but independently testable
- **User Story 6 (P3)**: Can start after Foundational (Phase 2) — may integrate with US2 but independently testable

### Within Each User Story

- Tests (if included) MUST be written and FAIL before implementation
- Models before services
- Services before endpoints
- Core implementation before integration
- Story complete before moving to next priority

### Parallel Opportunities

- All Setup tasks marked [P] can run in parallel
- All Foundational tasks marked [P] can run in parallel (within Phase 2)
- Once Foundational phase completes, all user stories can start in parallel (if team capacity allows)
- All tests for a user story marked [P] can run in parallel
- Models within a story marked [P] can run in parallel
- Different user stories can be worked on in parallel by different team members

---

## Parallel Example: User Story 1

```bash
# Launch all tests for User Story 1 together:
Task: "Contract tests for dashboard data sources in control-plane/tests/contract/test_ui_dashboard_api.py"
Task: "Integration test for quickstart Scenario 1 in control-plane/tests/integration/test_ui_dashboard_flow.py"

# Launch all implementation for User Story 1 together:
Task: "Dashboard data hook in ui/src/features/dashboard/useDashboard.ts"
Task: "Dashboard view in ui/src/features/dashboard/Dashboard.tsx"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: Test User Story 1 independently
5. Deploy/demo if ready

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 → Test independently → Deploy/Demo (MVP!)
3. Add User Story 2 → Test independently → Deploy/Demo
4. Add User Story 3 → Test independently → Deploy/Demo
5. Each story adds value without breaking previous stories

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: User Story 1
   - Developer B: User Story 2
   - Developer C: User Story 3
3. Stories complete and integrate independently

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Verify tests fail before implementing
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Avoid: vague tasks, same file conflicts, cross-story dependencies that break independence