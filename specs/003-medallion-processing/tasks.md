# Tasks: Medallion Architecture Processing

**Input**: Design documents from `/specs/003-medallion-processing/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (processing-api.md, transformation-schema.md, dataset-schema.md), quickstart.md

**Tests**: Included — the constitution (Principle IV: Shift-Left Testing & Contracts) and plan.md test plan explicitly mandate contract tests, and quickstart.md defines the test suite map (unit / contract / integration / manual E2E gate).

**Organization**: Tasks are grouped by user story (US1 P1, US2 P1, US3 P2, US4 P2, US5 P3) so each story can be implemented, tested, and delivered independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1, US2, US3, US4, or US5
- Exact file paths included in every task

## Path Conventions

Monorepo per plan.md: `control-plane/src/datafoundry/controlplane/` (FastAPI service), `control-plane/tests/`, `cli/src/datafoundry/cli/`, `terraform/` (provider-isolated modules). This feature extends the existing feature 001/002/004 control plane — no new service or infrastructure.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add processing dependencies, package skeleton, and shared test harness

- [X] T001 Add processing dependencies to `control-plane/pyproject.toml`: `pyiceberg` (Iceberg table format, FR-019), `duckdb` (SQL transformations + analyst querying; already present from feature 004), `pyarrow` (record-level transformation; already present). Verify `pip install -e ".[dev]"` resolves in `control-plane/.venv`.
- [X] T002 [P] Create the `processing` package skeleton per plan.md: `control-plane/src/datafoundry/controlplane/processing/` with `__init__.py`, `transformations/` (with `__init__.py`), `promotion.py`, `lineage.py`, `catalog.py`, `query.py`, `engine.py`, `gateway.py` — empty module stubs with docstrings.
- [X] T003 [P] Create the `SimulatedProcessingGateway` test harness in `control-plane/src/datafoundry/controlplane/processing/gateway.py`: in-memory fake zone inventories + record fixtures (Parquet/CSV/JSON tables with known duplicates, type errors, nulls, totals) + Iceberg-in-memory (snapshot/commit semantics) with fault-injection hooks (`force_immutability_violation`, `force_reconciliation_fail`, `force_zero_records`) so every transformation/promotion/lineage/query path is exercisable offline — no docker/terraform/database required.
- [X] T004 [P] Extend `control-plane/tests/conftest.py` with processing fixtures: a `simulated_processing_gateway` fixture, a `dataset` fixture, and a `process_processing_run` fixture that drives the processing engine synchronously (mirroring the feature 001 `process_run` pattern).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core processing models, schema, transformation framework, and engine primitives that every user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T005 Implement the six processing SQLAlchemy models per data-model.md — `Dataset`, `Transformation`, `DatasetVersion`, `PromotionState`, `LineageLink`, `CatalogMetadata` — in `control-plane/src/datafoundry/controlplane/db/models.py`, including: unique `(platform_id, name)` on Dataset, unique `(name, version)` on Transformation, unique `(dataset_id, version)` on DatasetVersion, JSONB columns via the existing `with_variant` pattern.
- [X] T006 Create the Alembic migration for the six new tables (revoke UPDATE/DELETE on any new append-only tables; reuse feature 001 migration conventions) — in `control-plane/src/datafoundry/controlplane/db/migrations/`. Verify offline SQL via `alembic upgrade head --sql`.
- [X] T007 [P] Implement the transformation config Pydantic schema per contracts/transformation-schema.md (strict, unknown fields rejected; `name`/`source_layer`/`target_layer`/`dedup_keys`/`reconciliation_tolerance`/`logic`; source one layer below target; type-specific logic) — in `control-plane/src/datafoundry/controlplane/config/transformation_schema.py`.
- [X] T008 [P] Implement the `Transformation` ABC and registry per research R-01: `apply` operation returning a `DatasetVersion`; registry maps `logic.type` → transformation implementation (mirrors capability-registry pattern, FR-015 spirit) — in `control-plane/src/datafoundry/controlplane/processing/transformations/base.py` and `transformations/registry.py`.
- [X] T009 [P] Implement the promotion state machine core per research R-04: `PromotionState` transitions `INGESTED → INGESTION_VALIDATED → BRONZE → BRONZE_VALIDATED → SILVER → SILVER_VALIDATED → GOLD → GOLD_VALIDATED → CONSUMABLE`, transition only on passing gate (feature 004), `blocked` marker on failed gate, override scoping to the specific run — in `control-plane/src/datafoundry/controlplane/processing/promotion.py`.
- [X] T010 [P] Implement the processing engine core per research R-02/R-03: run a transformation → transform (PyArrow/DuckDB) → write Iceberg snapshot (atomic per version, FR-012) → run gate (feature 004) → promote or block; record `DatasetVersion` + `PromotionState` — in `control-plane/src/datafoundry/controlplane/processing/engine.py`.
- [X] T011 [P] Wire secret-scan (feature 001 `config/secret_scan.py`) into every processing write/export path: `logic_definition`, `metadata_json`, `blocked_reason` (SC-007) — in `control-plane/src/datafoundry/controlplane/processing/` and `config/transformation_schema.py`.
- [X] T012 [P] Add processing audit actions to the existing audit service (feature 001 `audit/service.py`): `dataset.registered`, `transformation.defined`, `transformation.updated`, `transformation.run`, `promotion.transitioned`, `promotion.blocked`, `promotion.overridden`, `lineage.created` — each secret-scanned (FR-008, SC-007).
- [X] T013 [P] Unit tests for foundational core: transformation config schema conformance vs transformation-schema.md, transformation registry resolution, promotion state machine transitions (gate pass/block, override scoping), and secret-scan on processing payloads — in `control-plane/tests/unit/test_processing_core.py`.

**Checkpoint**: Foundation ready — user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Bronze layer preserves raw source data (Priority: P1) 🎯 MVP

**Goal**: Ingested data lands in Bronze exactly as received: immutable, source-aligned, replayable, and auditable. A data engineer can see, for any Bronze dataset, which source it came from, when it was ingested, how many records it contains, and its ingestion status. Bronze can be replayed to reprocess downstream layers without re-extracting from the source.

**Independent Test**: quickstart Scenario 1 — register a Bronze dataset from an ingested batch, verify it carries full batch metadata (source system, source object, ingestion timestamp, batch id, pipeline id, record count, ingestion status), verify an immutability-violation attempt is rejected and recorded, and replay Bronze into a fresh Silver run without contacting the source.

### Tests for User Story 1 ⚠️ (write first, ensure they FAIL before implementation)

- [X] T014 [P] [US1] Contract tests for `POST /datasets` (201 with dataset_id; 422 all-errors incl. unknown layer, bad name, missing owner), `GET /datasets`, `GET /datasets/{id}` (detail with promotion_state + gate results + transition timestamp) per contracts/processing-api.md §1 — in `control-plane/tests/contract/test_datasets_api.py`
- [X] T015 [P] [US1] Integration test for quickstart Scenario 1: register Bronze dataset from ingested batch, verify full batch metadata (FR-004), verify immutability-violation attempt rejected + recorded (FR-002), replay Bronze into fresh Silver run without source access (FR-003) — in `control-plane/tests/integration/test_bronze_immutability_flow.py`

### Implementation for User Story 1

- [X] T016 [P] [US1] Implement Bronze dataset registration + metadata: register a Bronze dataset from an ingested batch, attach source system, source object, ingestion timestamp, batch id, pipeline id, record count, ingestion status (FR-004) — in `control-plane/src/datafoundry/controlplane/processing/engine.py`
- [X] T017 [P] [US1] Implement Bronze immutability enforcement: reject and record any modification/deletion outside an approved retention policy (FR-002, US1-AC2) — in `control-plane/src/datafoundry/controlplane/processing/engine.py`
- [X] T018 [US1] Implement Bronze replay: reprocess downstream Silver from Bronze data without contacting the source system (FR-003, US1-AC3); replay produces a new consistent version, consumers see old or new atomically (FR-012) — in `control-plane/src/datafoundry/controlplane/processing/engine.py`
- [X] T019 [US1] Implement the datasets API router per contracts/processing-api.md §1: `POST /datasets`, `GET /datasets`, `GET /datasets/{id}`; secret-scan on `metadata_json`; audit writes — in `control-plane/src/datafoundry/controlplane/api/datasets.py`
- [X] T020 [US1] Implement CLI `datafoundry dataset register/list/status` commands (typer) per quickstart Scenario 1 — in `cli/src/datafoundry/cli/commands/dataset.py`

**Checkpoint**: US1 fully functional — Bronze is immutable, replayable, and carries full batch metadata

---

## Phase 4: User Story 2 - Silver layer delivers cleaned, conformed data (Priority: P1)

**Goal**: A data engineer defines Silver transformations (cleansing, type conversion, standardisation, deduplication, schema enforcement, malformed-record handling). When the transformation runs against validated Bronze data, the output lands in Silver only after passing Silver-layer quality checks. Malformed records route to quarantine, not silently dropped. Analysts can consume Silver directly.

**Independent Test**: quickstart Scenario 2 — define a Silver transformation, run it over a Bronze dataset with known duplicates, type errors, and nulls, verify clean records in Silver, bad records in quarantine with reasons, quality check results recorded, dedup per business keys, and version traceability.

### Tests for User Story 2 ⚠️

- [X] T021 [P] [US2] Contract tests for `POST /transformations` (201 with transformation_id/version; 422 all-errors incl. invalid source/target layer, bad logic, secret-scan hit), `GET /transformations/{id}` (logic_definition/logic_hash), `POST /transformations/{id}/run` (output_version, record_count, quarantined_count, gate_report_id, promotion_state), `GET /transformations/{id}/runs` per contracts/processing-api.md §2 — in `control-plane/tests/contract/test_transformations_api.py`
- [X] T022 [P] [US2] Integration test for quickstart Scenario 2: define Silver transform, run over Bronze with duplicates/type-errors/nulls, verify clean records in Silver + bad records quarantined with reasons + quality results recorded + dedup per keys + version traceability — in `control-plane/tests/integration/test_silver_transformation_flow.py`

### Implementation for User Story 2

- [X] T023 [P] [US2] Implement the Silver transformation type (PyArrow): cleansing, type conversion, standardisation, schema enforcement, dedup per `dedup_keys` (US2-AC3), malformed-record routing to quarantine with reasons (FR-006) — in `control-plane/src/datafoundry/controlplane/processing/transformations/silver.py`
- [X] T024 [P] [US2] Implement schema evolution handling: tolerate additive changes (new nullable column) per contract classification; breaking changes (type change, column removal) block promotion (FR-013) — in `control-plane/src/datafoundry/controlplane/processing/transformations/silver.py`
- [X] T025 [P] [US2] Implement zero-record detection: a transformation producing zero records from a non-empty input is flagged suspicious and blocked from promotion pending review (FR-020) — in `control-plane/src/datafoundry/controlplane/processing/engine.py`
- [X] T026 [US2] Implement the transformations API router per contracts/processing-api.md §2: `POST /transformations`, `GET /transformations/{id}`, `POST /transformations/{id}/run`, `GET /transformations/{id}/runs`; secret-scan on `logic_definition`; audit writes — in `control-plane/src/datafoundry/controlplane/api/transformations.py`
- [X] T027 [US2] Implement CLI `datafoundry transform define/run/history` commands per quickstart Scenario 2 — in `cli/src/datafoundry/cli/commands/transform.py`

**Checkpoint**: US1 + US2 both work independently — Bronze immutable/replayable, Silver delivers cleaned conformed data with quarantine routing

---

## Phase 5: User Story 3 - Gold layer delivers business-ready datasets (Priority: P2)

**Goal**: An analytics engineer defines Gold datasets (e.g. customer 360, sales performance) built from validated Silver data. Each Gold dataset has a clear owner, documented business definition, quality rules, and business metadata. Gold datasets are discoverable in the catalog, version controlled, and optimised for consumption. Gold promotion requires passing the strongest validation, including business reconciliation against Silver.

**Independent Test**: quickstart Scenario 3 — define a Gold aggregate dataset over a Silver dataset with known totals, run the build, verify reconciliation (Gold totals match Silver within tolerance), ownership metadata, and catalog discoverability; verify a reconciliation failure blocks promotion to CONSUMABLE.

### Tests for User Story 3 ⚠️

- [ ] T028 [P] [US3] Contract tests for Gold dataset registration (201; Gold requires owner/description/quality_score/refresh_metadata before CONSUMABLE — FR-009) and Gold transformation run (reconciliation pass → GOLD_VALIDATED → CONSUMABLE; reconciliation fail → blocked + discrepancy reported; non-SILVER_VALIDATED input refused — FR-010, FR-011) per contracts/processing-api.md §1/§2 — in `control-plane/tests/contract/test_transformations_api.py`
- [ ] T029 [P] [US3] Integration test for quickstart Scenario 3: define Gold aggregate over Silver with known totals, run build, verify reconciliation + ownership metadata + catalog discoverability; reconciliation failure blocks CONSUMABLE + reports discrepancy; non-SILVER_VALIDATED input refused — in `control-plane/tests/integration/test_gold_reconciliation_flow.py`

### Implementation for User Story 3

- [ ] T030 [P] [US3] Implement the Gold transformation type (DuckDB): aggregation (group_by + measures), reconciliation against Silver inputs within `reconciliation_tolerance` (FR-010, US3-AC1) — in `control-plane/src/datafoundry/controlplane/processing/transformations/gold.py`
- [ ] T031 [P] [US3] Implement Gold metadata + catalog registration: owner, business definition, quality rules, business metadata required before CONSUMABLE (FR-010); refuse non-SILVER_VALIDATED inputs (FR-011); reconciliation failure blocks promotion + reports discrepancy (FR-010, US3-AC3) — in `control-plane/src/datafoundry/controlplane/processing/catalog.py` and `engine.py`
- [ ] T032 [US3] Implement catalog registration per research R-07: register every dataset in the catalog with owner, steward, domain, description, classification, quality score, lineage, refresh metadata (FR-014); Gold discoverable in catalog (US3-AC2) — in `control-plane/src/datafoundry/controlplane/processing/catalog.py`
- [ ] T033 [US3] Implement CLI `datafoundry dataset register` Gold variant (owner/description/quality-score/refresh) per quickstart Scenario 3 — in `cli/src/datafoundry/cli/commands/dataset.py`

**Checkpoint**: US1 + US2 + US3 all work independently — Bronze, Silver, and Gold layers with reconciliation and catalog discoverability

---

## Phase 6: User Story 4 - Explicit promotion states with gate enforcement (Priority: P2)

**Goal**: Every dataset moves through explicit states INGESTED → INGESTION_VALIDATED → BRONZE → BRONZE_VALIDATED → SILVER → SILVER_VALIDATED → GOLD → GOLD_VALIDATED → CONSUMABLE. A dataset only transitions when the relevant quality gate passes. Any state, and the reason for it, is visible to engineers. A failed gate blocks promotion automatically; an authorised override (with reason, expiry, identity, timestamp, impact assessment) is the only path past a failed gate.

**Independent Test**: quickstart Scenario 4 — attempt to promote a dataset with a failed critical gate and verify promotion is refused; then apply a recorded override and verify promotion proceeds and the override is auditable.

### Tests for User Story 4 ⚠️

- [ ] T034 [P] [US4] Contract tests for `GET /datasets/{id}/promotion` (current state + history with gate_report_id + transitioned_at + blocked_reason), `POST /datasets/{id}/promotion/override` (201 active; 422 incomplete; 403 unauthorised + recorded) per contracts/processing-api.md §3 — in `control-plane/tests/contract/test_promotion_api.py`
- [ ] T035 [P] [US4] Integration test for quickstart Scenario 4: attempt promotion on failed critical gate → refused + BLOCKED; grant override → promotion proceeds + auditable; incomplete override rejected; expired override grants no permission — in `control-plane/tests/integration/test_promotion_override_flow.py`

### Implementation for User Story 4

- [ ] T036 [P] [US4] Implement promotion enforcement in the engine: transition only on passing gate (feature 004), `blocked` marker on failed gate with reason, gate results + transition timestamp recorded (FR-007, US4-AC1, US4-AC3) — in `control-plane/src/datafoundry/controlplane/processing/promotion.py` and `engine.py`
- [ ] T037 [P] [US4] Implement override integration with feature 004: consume `GateReport` decision (promote/block) as the promotion condition; override applies only to the specific blocked run, expires automatically, permanently audited (FR-008) — in `control-plane/src/datafoundry/controlplane/processing/promotion.py` (consumes feature 004 `GateOverride)
- [ ] T038 [US4] Implement the promotion API router per contracts/processing-api.md §3: `GET /datasets/{id}/promotion`, `POST /datasets/{id}/promotion/override`; authorisation check; audit writes — in `control-plane/src/datafoundry/controlplane/api/promotion.py`
- [ ] T039 [US4] Implement CLI `datafoundry promote status/override` commands per quickstart Scenario 4 — in `cli/src/datafoundry/cli/commands/promote.py`

**Checkpoint**: US1–US4 all work independently — promotion states enforced with gate decisions and audited overrides as the only bypass

---

## Phase 7: User Story 5 - Analysts query Silver and Gold directly (Priority: P3)

**Goal**: An analyst browses the catalog, picks a Silver or Gold dataset, and queries it directly with SQL — including lightweight local querying without loading data into a warehouse — and downloads results. The analyst sees the schema, quality score, and freshness before querying.

**Independent Test**: quickstart Scenario 5 — query a CONSUMABLE Gold dataset, verify results return correctly and reflect the current version; query an unauthorised dataset returns 403, and a download respects column-level protection policies.

### Tests for User Story 5 ⚠️

- [ ] T040 [P] [US5] Contract tests for `POST /datasets/{id}/query` (200 columns/rows/row_count; 403 unauthorised), `POST /datasets/{id}/query/download` (CSV/Parquet; column-level protection applied) per contracts/processing-api.md §5 — in `control-plane/tests/contract/test_query_api.py`
- [ ] T041 [P] [US5] Integration test for quickstart Scenario 5: query CONSUMABLE Gold dataset, verify results reflect current version; query unauthorised dataset → 403; download respects column-level protection (masked/tokenised per policy) — in `control-plane/tests/integration/test_query_flow.py`

### Implementation for User Story 5

- [ ] T042 [P] [US5] Implement the query module per research R-03: DuckDB analyst querying over Silver/Gold Iceberg tables (lightweight, no warehouse load, FR-016), schema/quality score/freshness surfaced before querying (US5-AC1), column-level protection on download (masking/tokenisation per policy, FR-016, US5-AC3) — in `control-plane/src/datafoundry/controlplane/processing/query.py`
- [ ] T043 [P] [US5] Implement lineage module per research R-07: lineage links source → Bronze → Silver → Gold → consumers, navigable both directions (FR-015, SC-006) — in `control-plane/src/datafoundry/controlplane/processing/lineage.py` and `api/lineage.py` (GET /datasets/{id}/lineage)
- [ ] T044 [US5] Implement the query API router per contracts/processing-api.md §5: `POST /datasets/{id}/query`, `POST /datasets/{id}/query/download`; authorisation check; column-level protection on download — in `control-plane/src/datafoundry/controlplane/api/query.py`
- [ ] T045 [US5] Implement CLI `datafoundry query run/download` commands per quickstart Scenario 5 — in `cli/src/datafoundry/cli/commands/query.py`

**Checkpoint**: US1–US5 all work — analysts query Silver/Gold directly with column-level protection and navigable lineage

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: GitOps versioning, cloud-independence verification, and final validation

- [ ] T046 [P] Implement GitOps versioning for transformation definitions through the existing `config/gitops.py` pattern (FR-005, FR-017); every run records transformation version, input versions, output version, gate results, quarantined counts (FR-017); prior runs traceable to producing version (US2-AC4) — in `control-plane/src/datafoundry/controlplane/config/transformation_schema.py` and `config/gitops.py`
- [ ] T047 [P] Verify cloud-independence of layer model, transformation definitions, promotion states, and metadata (FR-018, SC-007): identical behaviour on both clouds — extend `scripts/parity_checklist.py` with a processing parity check (mirroring feature 002 SC-003 pattern)
- [ ] T048 [P] Run full test suite + ruff clean: `control-plane/.venv/bin/python -m pytest` (all unit + contract + integration) and `ruff check` + `ruff format` clean across control-plane + cli; verify `alembic upgrade head --sql` offline SQL — final gate.

**Checkpoint (Final)**: Feature 003 complete — all 5 user stories independently testable, ruff clean, tests pass, cloud-independent processing verified