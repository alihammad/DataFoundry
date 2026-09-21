# Tasks: Semantic Layer

**Input**: Design documents from `/specs/006-semantic-layer/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (semantic-api.md, semantic-model-schema.md, semantic-test-schema.md), quickstart.md

**Tests**: Included — the constitution (Principle IV: Shift-Left Testing & Contracts) and plan.md test plan explicitly mandate contract tests, and quickstart.md defines the test suite map (unit / contract / integration / manual E2E).

**Organization**: Tasks are grouped by user story (US1 P1, US2 P2, US3 P2, US4 P3) so each story can be implemented, tested, and delivered independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1, US2, US3, or US4
- Exact file paths included in every task

## Path Conventions

Monorepo per plan.md: `control-plane/src/datafoundry/controlplane/` (FastAPI service), `control-plane/tests/`, `cli/src/datafoundry/cli/`. This feature extends the existing feature 001–005 control plane — no new service or infrastructure.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add semantic dependencies, package skeleton, and shared test harness

- [X] T001 Add semantic dependencies to `control-plane/pyproject.toml`: `duckdb` (metric computation over Gold/Silver; already present from feature 004), `pyarrow` (zone table reads; already present). Verify `pip install -e ".[dev]"` resolves in `control-plane/.venv`.
- [X] T002 [P] Create the `semantic` package skeleton per plan.md: `control-plane/src/datafoundry/controlplane/semantic/` with `__init__.py`, `model/` (with `__init__.py`), `compute/` (with `__init__.py`), `tests/` (with `__init__.py`), `lifecycle.py`, `access.py`, `discovery.py`, `consumers.py`, `deprecation.py`, `engine.py` — empty module stubs with docstrings.
- [X] T003 [P] Create the `SimulatedSemanticGateway` test harness in `control-plane/src/datafoundry/controlplane/semantic/compute/gateway.py`: in-memory fake Gold/Silver zone inventories + reference-data fixtures (known revenue/order/customer tables with duplicates, protected columns, row-level restrictions, staleness, quality-state flags) with fault-injection hooks (`force_stale_data`, `force_quality_failure`, `force_fanout`) so every metric-definition, semantic-test, publication, access, and discovery path is exercisable offline — no docker/terraform/database required.
- [X] T004 [P] Extend `control-plane/tests/conftest.py` with semantic fixtures: a `simulated_semantic_gateway` fixture, a `semantic_dataset` fixture (reuse feature 003 dataset helper), and a `process_semantic_query` fixture that drives the semantic engine synchronously (mirroring the feature 001 `process_run` pattern).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core semantic models, schema, metric-computation framework, and engine primitives that every user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T005 Implement the nine semantic SQLAlchemy models per data-model.md — `SemanticModel`, `Metric`, `Dimension`, `Measure`, `Relationship`, `SemanticTest`, `SemanticTestResult`, `Publication`, `ConsumerRegistration`, `QueryResultVersion` — in `control-plane/src/datafoundry/controlplane/db/models.py`, including: unique `(domain, version)` on SemanticModel, unique `(domain)` on SemanticModel, JSONB columns via the existing `with_variant` pattern.
- [X] T006 Create the Alembic migration for the ten new tables (revoke UPDATE/DELETE on any new append-only tables; reuse feature 001 migration conventions) — in `control-plane/src/datafoundry/controlplane/db/migrations/`. Verify offline SQL via `alembic upgrade head --sql`.
- [X] T007 [P] Implement the semantic model Pydantic schema per contracts/semantic-model-schema.md (strict, unknown fields rejected; `domain`/`metrics`/`dimensions`/`measures`/`relationships`; business-term names unique per domain; metric formula compiles to a valid query; references resolve) — in `control-plane/src/datafoundry/controlplane/config/semantic_schema.py`.
- [X] T008 [P] Implement the semantic test Pydantic schema per contracts/semantic-test-schema.md (strict; `calculation`/`reconciliation`/`relationship`/`filter` categories; category-specific parameters) — in `control-plane/src/datafoundry/controlplane/config/semantic_schema.py`.
- [X] T009 [P] Implement the `SemanticTest` ABC and registry per research R-04: `evaluate` operation returning a `SemanticTestResult`; registry maps `category` → test implementation (mirrors feature 004 quality-test registry pattern) — in `control-plane/src/datafoundry/controlplane/semantic/tests/base.py` and `tests/registry.py`.
- [X] T010 [P] Implement the metric computation core per research R-02: compile a metric's declarative `formula` (measure + aggregation + optional filter + dimensions) to a DuckDB query over Gold/Silver datasets read through the `CloudGateway`; identical results on both clouds (FR-013, SC-008) — in `control-plane/src/datafoundry/controlplane/semantic/compute/engine.py`.
- [X] T011 [P] Wire secret-scan (feature 001 `config/secret_scan.py`) into every semantic write/export path: `config_yaml`, `business_definition`, `formula`, `parameters` (SC-007) — in `control-plane/src/datafoundry/controlplane/semantic/` and `config/semantic_schema.py`.
- [X] T012 [P] Add semantic audit actions to the existing audit service (feature 001 `audit/service.py`): `semantic.model.defined`, `semantic.model.published`, `semantic.metric.queried`, `semantic.test.run`, `semantic.consumer.registered`, `semantic.metric.deprecated` — each secret-scanned (FR-003, FR-005, FR-010, SC-007).
- [X] T013 [P] Unit tests for foundational core: semantic model schema conformance vs semantic-model-schema.md, semantic test schema conformance vs semantic-test-schema.md, metric formula compilation, semantic test registry resolution, and secret-scan on semantic payloads — in `control-plane/tests/unit/test_semantic_core.py`.

**Checkpoint**: Foundation ready — user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Define business metrics once, consume everywhere (Priority: P1) 🎯 MVP

**Goal**: An analytics engineer defines a business metric in the semantic layer bound to Gold/Silver datasets with dimensions, plain-language definition, and owner. Every consumer (BI, analyst SQL, AI/ML, applications) that requests the metric receives the same value computed by the same definition — no downstream team re-implements business logic.

**Independent Test**: quickstart Scenario 1 — define one metric, consume it through two different consumption paths (analyst SQL + programmatic API), verify identical results; then change the definition through the governed workflow and verify all consumers reflect the new version.

### Tests for User Story 1 ⚠️ (write first, ensure they FAIL before implementation)

- [X] T014 [P] [US1] Contract tests for `POST /semantic/models` (201 with model_id + version; 422 all-errors), `POST /semantic/models/{id}/metrics` (201; 422 invalid formula/duplicate term/secret-scan), `GET /semantic/metrics/{id}` (200 with definition/formula/owner/datasets/lineage), and `POST /semantic/metrics/{id}/query` (200 with value + definition_version + dataset_versions + freshness + quality_state) per contracts/semantic-api.md §1–2 — in `control-plane/tests/contract/test_semantic_api.py`.
- [X] T015 [P] [US1] Integration test for quickstart Scenario 1: define a revenue metric, query it through two consumption paths, verify identical results (FR-002, SC-001); change the definition through the governed workflow and verify consumers reflect the new version — in `control-plane/tests/integration/test_metric_consistency_flow.py`.

### Implementation for User Story 1

- [X] T016 [P] [US1] Create `SemanticModel`, `Metric`, `Dimension`, `Measure`, `Relationship` models in `control-plane/src/datafoundry/controlplane/db/models.py` (foundational T005 already added them; wire any story-specific fields).
- [X] T017 [P] [US1] Implement the semantic model composition + validation in `control-plane/src/datafoundry/controlplane/semantic/model/model.py` (build a `SemanticModel` from validated config; resolve metric/dimension/measure/relationship references).
- [X] T018 [P] [US1] Implement the metric computation engine in `control-plane/src/datafoundry/controlplane/semantic/compute/engine.py` (compile formula → DuckDB query → value; record definition_version + dataset_versions + freshness + quality_state per result, FR-008/FR-012).
- [X] T019 [US1] Implement the semantic API routers in `control-plane/src/datafoundry/controlplane/api/semantic.py` and `api/metrics.py` (define model, define metric, describe metric, query metric; audit writes; secret-scan; 422/403/409/410 paths).
- [X] T020 [US1] Implement the CLI commands in `cli/src/datafoundry/cli/commands/semantic.py` and `cli/commands/metric.py` (`datafoundry semantic model set`, `datafoundry metric query`, `datafoundry metric describe`); register in `cli/src/datafoundry/cli/main.py`.
- [X] T021 [US1] Add logging for semantic operations (structured logs via existing OpenTelemetry) in `control-plane/src/datafoundry/controlplane/semantic/`.

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently

---

## Phase 4: User Story 2 - Governed metric lifecycle (Priority: P2)

**Goal**: Semantic definitions are version controlled and change through the GitOps workflow (propose → validate → approve → publish). Validation includes semantic tests; breaking changes require explicit approval and notify registered consumers.

**Independent Test**: quickstart Scenario 2 — submit a metric change that fails a semantic test (aggregation no longer reconciles) and verify publication is blocked; then submit a correct change and verify it publishes with version history.

### Tests for User Story 2 ⚠️ (write first, ensure they FAIL before implementation)

- [ ] T022 [P] [US2] Contract tests for `POST /semantic/models/{id}/tests` (201), `POST /semantic/tests/{id}/run` (200 passed/failed), `POST /semantic/models/{id}/publish` (201 pending; 422 blocked on failed tests), `POST /publications/{id}/approve` (200 approved + published_at; notifies consumers), and `GET /semantic/models/{id}/publications` (history) per contracts/semantic-api.md §3–4 — in `control-plane/tests/contract/test_semantic_api.py`.
- [ ] T023 [P] [US2] Integration test for quickstart Scenario 2: submit a metric change that fails a semantic test → publication blocked with failure detail; submit a correct change → publishes with version history; query "as of" a prior period records the definition version (FR-012, US2-AC3) — in `control-plane/tests/integration/test_semantic_lifecycle_flow.py`.

### Implementation for User Story 2

- [ ] T024 [P] [US2] Create `SemanticTest`, `SemanticTestResult`, `Publication` models in `control-plane/src/datafoundry/controlplane/db/models.py` (foundational T005 already added them; wire any story-specific fields).
- [ ] T025 [P] [US2] Implement the semantic test categories in `control-plane/src/datafoundry/controlplane/semantic/tests/categories.py` (calculation, reconciliation, relationship, filter; run at publish time AND on schedule against production data, FR-014).
- [ ] T026 [US2] Implement the GitOps lifecycle in `control-plane/src/datafoundry/controlplane/semantic/lifecycle.py` (propose → validate → approve → publish; classify breaking/non-breaking; breaking requires approval + consumer notification, FR-005; reuse feature 001 `config/gitops.py` pattern).
- [ ] T027 [US2] Implement the publication + semantic-test API routers in `control-plane/src/datafoundry/controlplane/api/publications.py` and `api/semantic_tests.py` (define/run tests, propose/approve publication; audit writes; 422 blocked on failed tests).
- [ ] T028 [US2] Implement the CLI commands in `cli/src/datafoundry/cli/commands/semantic.py` (`datafoundry semantic model publish`, `datafoundry semantic model approve`, `datafoundry semantic test run`); register in `cli/src/datafoundry/cli/main.py`.

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently

---

## Phase 5: User Story 3 - Access policies on semantic consumption (Priority: P2)

**Goal**: Semantic-layer access respects the platform's security model: consumers only see metrics and dimension members they are authorised for, protected columns remain protected through semantic queries, and row-level restrictions apply.

**Independent Test**: quickstart Scenario 3 — query the same metric as two roles with different authorisations and verify different visibility/results; verify protected column values never appear in semantic query output without authorised detokenisation.

### Tests for User Story 3 ⚠️ (write first, ensure they FAIL before implementation)

- [ ] T029 [P] [US3] Contract tests for `POST /semantic/metrics/{id}/query` access paths: 403 for unauthorised user over a RESTRICTED dataset (US3-AC1), protected column values masked/tokenised per policy (US3-AC2, SC-005), row-level restrictions applied (US3-AC3) per contracts/semantic-api.md §2 — in `control-plane/tests/contract/test_semantic_api.py`.
- [ ] T030 [P] [US3] Integration test for quickstart Scenario 3: query the same metric as two roles with different authorisations → different visibility/results; protected column values never appear without authorised detokenisation — in `control-plane/tests/integration/test_semantic_access_flow.py`.

### Implementation for User Story 3

- [ ] T031 [P] [US3] Implement access-policy enforcement in `control-plane/src/datafoundry/controlplane/semantic/access.py` (role-based metric visibility, column-level protection preserved in results, row-level restrictions applied; reuse feature 005 access module, FR-007).
- [ ] T032 [US3] Wire access enforcement into the metric query path in `control-plane/src/datafoundry/controlplane/semantic/engine.py` and `api/metrics.py` (403 on unauthorised classification; protected columns masked/tokenised; row-level filters applied before computation).

**Checkpoint**: At this point, User Stories 1, 2, AND 3 should all work independently

---

## Phase 6: User Story 4 - Discover and understand business terms (Priority: P3)

**Goal**: A business user searches the catalog for a business term and finds the certified metric with its definition, owner, quality score, freshness, and consuming teams. Certified definitions are visually distinguished from drafts.

**Independent Test**: quickstart Scenario 4 — search business terms and verify the correct certified metrics surface with complete metadata; verify draft definitions are clearly distinguished.

### Tests for User Story 4 ⚠️ (write first, ensure they FAIL before implementation)

- [ ] T033 [P] [US4] Contract tests for `GET /semantic/discovery?q=...` (200 with certified metrics + definition/owner/quality_score/freshness/lineage/consuming_teams; drafts hidden or clearly marked) per contracts/semantic-api.md §6 — in `control-plane/tests/contract/test_semantic_api.py`.
- [ ] T034 [P] [US4] Integration test for quickstart Scenario 4: search a business term → certified metric surfaces with complete metadata; draft definitions clearly distinguished — in `control-plane/tests/integration/test_semantic_discovery_flow.py`.

### Implementation for User Story 4

- [ ] T035 [P] [US4] Implement catalog discovery in `control-plane/src/datafoundry/controlplane/semantic/discovery.py` (search business terms; certified vs draft distinction; surface definition/owner/quality_score/freshness/lineage/consuming_teams, FR-011).
- [ ] T036 [US4] Implement the discovery API router in `control-plane/src/datafoundry/controlplane/api/discovery.py` (`GET /semantic/discovery`; drafts hidden from general users or clearly marked, US4-AC2).

**Checkpoint**: At this point, all user stories should be independently functional

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T037 [P] Implement consumer registration + notification in `control-plane/src/datafoundry/controlplane/semantic/consumers.py` and `api/consumers.py` (`POST /semantic/metrics/{id}/consumers`, `GET /semantic/metrics/{id}/consumers`; breaking-change + deprecation notification, FR-005/FR-010).
- [ ] T038 [P] Implement metric deprecation in `control-plane/src/datafoundry/controlplane/semantic/deprecation.py` and `api/metrics.py` (`POST /semantic/metrics/{id}/deprecate`; successor reference; time-bounded continued availability; deprecation notice in results, FR-010).
- [ ] T039 [P] Add semantic health runner (optional) in `control-plane/src/datafoundry/controlplane/health/runners.py` (semantic-layer health check).
- [ ] T040 [P] Additional unit tests for consumer registration, deprecation, and discovery edge cases in `control-plane/tests/unit/test_semantic_core.py`.
- [ ] T041 Run quickstart.md validation (Scenarios 1–5) end to end; verify ruff check + format clean repo-wide; verify alembic offline SQL generates the new tables.
- [ ] T042 [P] Documentation updates: expand `control-plane/README.md` and `cli/README.md` with semantic-layer usage; update `docs/` if needed.

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

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) — No dependencies on other stories
- **User Story 2 (P2)**: Can start after Foundational (Phase 2) — Depends on US1 (definitions must exist to govern)
- **User Story 3 (P2)**: Can start after Foundational (Phase 2) — Depends on US1 (metrics must exist to enforce access)
- **User Story 4 (P3)**: Can start after Foundational (Phase 2) — Depends on US1 (definitions must exist to discover)

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
Task: "Contract test for semantic API in tests/contract/test_semantic_api.py"
Task: "Integration test for metric consistency in tests/integration/test_metric_consistency_flow.py"

# Launch all models for User Story 1 together:
Task: "Create SemanticModel/Metric/Dimension/Measure/Relationship models in db/models.py"
Task: "Implement semantic model composition in semantic/model/model.py"
Task: "Implement metric computation engine in semantic/compute/engine.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL - blocks all stories)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: Test User Story 1 independently
5. Deploy/demo if ready

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 → Test independently → Deploy/Demo (MVP!)
3. Add User Story 2 → Test independently → Deploy/Demo
4. Add User Story 3 → Test independently → Deploy/Demo
5. Add User Story 4 → Test independently → Deploy/Demo
6. Each story adds value without breaking previous stories

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: User Story 1
   - Developer B: User Story 2
   - Developer C: User Story 3
   - Developer D: User Story 4
3. Stories complete and integrate independently

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Verify tests fail before implementing
- Commit after each task or logical group
- Stop at any checkpoint to validate and get approval