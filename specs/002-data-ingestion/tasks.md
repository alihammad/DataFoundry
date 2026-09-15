# Tasks: Self-Service Data Ingestion

**Input**: Design documents from `/specs/002-data-ingestion/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (ingestion-api.md, source-config-schema.md, source-contract-schema.md), quickstart.md

**Tests**: Included — the constitution (Principle IV: Shift-Left Testing & Contracts) and plan.md test plan explicitly mandate contract tests, and quickstart.md defines the test suite map (unit / contract / integration / manual E2E gate).

**Organization**: Tasks are grouped by user story (US1 P1, US2 P2, US3 P2, US4 P3) so each story can be implemented, tested, and delivered independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1, US2, US3, or US4
- Exact file paths included in every task

## Path Conventions

Monorepo per plan.md: `control-plane/src/datafoundry/controlplane/` (FastAPI service), `control-plane/tests/`, `cli/src/datafoundry/cli/`, `terraform/` (provider-isolated modules). This feature extends the existing feature 001 control plane — no new service or infrastructure.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add ingestion dependencies, package skeleton, and shared test harness

- [ ] T001 Add ingestion dependencies to `control-plane/pyproject.toml`: `pyarrow` (file parsing), `pymssql` (SQL Server, pure-python), `psycopg` (PostgreSQL async); dev: `pytest-asyncio` already present. Verify `pip install -e ".[dev]"` resolves in `control-plane/.venv`.
- [ ] T002 [P] Create the `ingestion` package skeleton per plan.md: `control-plane/src/datafoundry/controlplane/ingestion/` with `__init__.py`, `connectors/` (with `__init__.py`), `engine.py`, `validation.py`, `contract.py`, `scheduler.py`, `gateway.py` — empty module stubs with docstrings.
- [ ] T003 [P] Create the `SimulatedSourceGateway` test harness in `control-plane/src/datafoundry/controlplane/ingestion/gateway.py`: in-memory fake PostgreSQL/SQL Server/object-storage inventories (tables, columns, rows, files, checksums) with fault-injection hooks (`force_auth_fail`, `force_network_unreachable`, `force_schema_change`, `force_corrupt_file`) so every connector/validation/quarantine path is exercisable offline — no docker/terraform/database required.
- [ ] T004 [P] Extend `control-plane/tests/conftest.py` with ingestion fixtures: a `simulated_source_gateway` fixture, a `platform` fixture (reuse feature 001 deploy helper), and a `process_ingestion_run` fixture that drives the ingestion worker synchronously (mirroring the feature 001 `process_run` pattern).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core ingestion models, schema, connector framework, and engine primitives that every user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T005 Implement the seven ingestion SQLAlchemy models per data-model.md — `DataSource`, `IngestionConfig`, `SourceContract`, `IngestionPipeline`, `IngestionBatch`, `IngestionRun`, `QuarantineRecord` — in `control-plane/src/datafoundry/controlplane/db/models.py`, including: unique `(platform_id, name)` on DataSource, unique `(source_id, object_name)` on SourceContract, unique `(source_id, version)` on IngestionConfig, partial unique index on IngestionRun `WHERE status IN ('queued','running','paused')` per pipeline (R-10), and JSONB columns via the existing `with_variant` pattern.
- [ ] T006 Create the Alembic migration for the seven new tables (revoke UPDATE/DELETE on any new append-only tables; reuse feature 001 migration conventions) — in `control-plane/src/datafoundry/controlplane/db/migrations/`. Verify offline SQL via `alembic upgrade head --sql`.
- [ ] T007 [P] Implement the ingestion config Pydantic schema per contracts/source-config-schema.md (strict, unknown fields rejected; `apiVersion`/`kind`/`metadata`/`source`/`schedule`/`target`/`validation`; conditional `cursor_column` iff incremental; `filePattern` iff object_storage) — in `control-plane/src/datafoundry/controlplane/config/ingestion_schema.py`.
- [ ] T008 [P] Implement the `Connector` ABC and registry per research R-01: `discover_schema`, `test_connection`, `extract` operations; registry maps `source_type` → connector class (mirrors capability-registry pattern, FR-015 spirit) — in `control-plane/src/datafoundry/controlplane/ingestion/connectors/base.py` and `connectors/registry.py`.
- [ ] T009 [P] Implement the ingestion engine core per research R-05/R-06: batch execution pipeline `extract → validate → land/quarantine`, staging-then-commit Bronze landing (`bronze/<source_object>/source=<source_name>/ingestion_date=<YYYY-MM-DD>/<batch_id>/`), `_batch_metadata.json` write, and per-source-object high-watermark persistence advanced only on validated commit — in `control-plane/src/datafoundry/controlplane/ingestion/engine.py`.
- [ ] T010 [P] Implement ingestion validation module per research R-07: file validation (exists, readable, format, encoding, checksum — FR-006), schema/contract compatibility, and record-count reconciliation (FR-009) — in `control-plane/src/datafoundry/controlplane/ingestion/validation.py`.
- [ ] T011 [P] Implement contract module per research R-07 and contracts/source-contract-schema.md: contract inference from observed schema (marked `pending`, never auto-approved — constitution V), change classification (breaking/non-breaking/warning per the classification table) — in `control-plane/src/datafoundry/controlplane/ingestion/contract.py`.
- [ ] T012 [P] Wire secret-scan (feature 001 `config/secret_scan.py`) into every ingestion write/export path: `config_ref`, `config_yaml`, `metadata_json`, `failure_reason`, `log_ref` (SC-007) — in `control-plane/src/datafoundry/controlplane/ingestion/` and `config/ingestion_schema.py`.
- [ ] T013 [P] Add ingestion audit actions to the existing audit service (feature 001 `audit/service.py`): `source.registered`, `source.tested`, `config.created`, `config.updated`, `pipeline.paused`, `pipeline.resumed`, `run.triggered`, `run.retried`, `contract.approved` — each secret-scanned (FR-014, SC-007).
- [ ] T014 [P] Unit tests for foundational core: ingestion config schema conformance vs source-config-schema.md, connector registry resolution, contract change classification table, high-watermark advance-on-commit semantics, and secret-scan on ingestion payloads — in `control-plane/tests/unit/test_ingestion_core.py`.

**Checkpoint**: Foundation ready — user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Configure and run ingestion from a relational database (Priority: P1) 🎯 MVP

**Goal**: A data engineer registers a PostgreSQL or SQL Server source, tests connectivity (schema discovered within one minute), selects tables with full/incremental modes and a schedule, and the platform auto-creates an ingestion pipeline that lands data into Bronze with full batch metadata — no custom code.

**Independent Test**: quickstart Scenarios 1–3 — register + test a source (schema discovered, actionable auth/network/not-found errors), configure two tables (one incremental), run the pipeline, verify Bronze batches with `_batch_metadata.json`, and confirm a second incremental run produces zero duplicates against the ≥1M-row simulated dataset.

### Tests for User Story 1 ⚠️ (write first, ensure they FAIL before implementation)

- [ ] T015 [P] [US1] Contract tests for `POST /api/v1/sources` (201 shape, 422 all-errors, unknown type, bad secretRef naming), `POST /sources/{id}/test` (200 ok:true with discovered_schema; ok:false with classified detail `authentication_failed`/`network_unreachable`/`database_not_found`; credentials never echoed), `GET /sources`, `GET /sources/{id}` per contracts/ingestion-api.md §1 — in `control-plane/tests/contract/test_sources_api.py`
- [ ] T016 [P] [US1] Contract tests for `POST /sources/{id}/config` (201 with config_id/version/pipeline_id; 422 all-errors incl. invalid schedule, incremental-without-cursor, secret-scan hit) and `GET /sources/{id}/config` (version/config_yaml/config_hash; no plaintext secrets) per contracts/ingestion-api.md §2 — in `control-plane/tests/contract/test_ingestion_config_api.py`
- [ ] T017 [P] [US1] Integration test for quickstart Scenarios 1–3: register + test PostgreSQL source (schema discovered), configure customer (incremental, cursor updated_at) + orders (full), run pipeline, verify Bronze batches + metadata, second run ingests only the delta with zero duplicates — in `control-plane/tests/integration/test_db_ingestion_flow.py`

### Implementation for User Story 1

- [ ] T018 [P] [US1] Implement the PostgreSQL connector (SQLAlchemy Core + `psycopg`): `discover_schema` via inspector (tables/columns/types/nullability), `test_connection` with classified errors, `extract` with server-side streaming and `WHERE cursor_col > :watermark ORDER BY cursor_col` for incremental (R-02) — in `control-plane/src/datafoundry/controlplane/ingestion/connectors/postgres.py`
- [ ] T019 [P] [US1] Implement the SQL Server connector (SQLAlchemy Core + `pymssql`): same contract as PostgreSQL connector — in `control-plane/src/datafoundry/controlplane/ingestion/connectors/sqlserver.py`
- [ ] T020 [US1] Implement the sources API router per contracts/ingestion-api.md §1: `POST /sources`, `POST /sources/{id}/test`, `GET /sources`, `GET /sources/{id}`; secret-scan on `config_ref`; audit writes; classified test errors — in `control-plane/src/datafoundry/controlplane/api/sources.py`
- [ ] T021 [US1] Implement the ingestion config API router per contracts/ingestion-api.md §2: `POST /sources/{id}/config` (validate → version → auto-create pipeline → 201) and `GET /sources/{id}/config` (canonical YAML export, config_hash, secret-scan guarantee) — in `control-plane/src/datafoundry/controlplane/api/ingestion_configs.py`
- [ ] T022 [US1] Implement the ingestion worker path: dispatch a queued `IngestionRun` through the feature 001 dispatcher hook, execute the engine per pipeline, update run/batch statuses, record `records_processed`/`outcome`/`failure_reason` (redacted) — in `control-plane/src/datafoundry/controlplane/ingestion/engine.py` and `api/app.py` wiring
- [ ] T023 [US1] Implement CLI `datafoundry source add/test/list` commands (typer) per quickstart Scenario 1 — in `cli/src/datafoundry/cli/commands/source.py`
- [ ] T024 [US1] Implement CLI `datafoundry source configure` and `datafoundry ingest run` commands per quickstart Scenarios 2–3 — in `cli/src/datafoundry/cli/commands/ingest.py`

**Checkpoint**: US1 fully functional — a relational database source is onboarded and lands validated data in Bronze with zero-duplicate incremental runs

---

## Phase 4: User Story 2 - Ingest files from object storage and file drops (Priority: P2)

**Goal**: A data engineer configures ingestion of CSV/JSON/Parquet files from an S3/GCS location; the platform detects new files, validates them (format, encoding, readability, checksum), ingests valid files into Bronze preserving source layout, and routes invalid files to quarantine with a failure reason — valid files in a partial batch still ingested.

**Independent Test**: quickstart Scenario 4 — drop valid and deliberately corrupted files into a watched location, run ingestion, verify valid files land in Bronze with file-level metadata while corrupted files land in quarantine with reasons, and duplicate checksums are detected and not double-loaded.

### Tests for User Story 2 ⚠️

- [ ] T025 [P] [US2] Contract tests for object-storage source registration (`POST /sources` with `type=object_storage`, `location`, `format`) and config with `filePattern` per contracts/ingestion-api.md §1/§2 — in `control-plane/tests/contract/test_sources_api.py`
- [ ] T026 [P] [US2] Integration test for quickstart Scenario 4: valid Parquet files land in Bronze with file metadata; a corrupted file routes to `quarantine/events/<batch_id>/` with `_quarantine_metadata.json`; valid files still ingested; run `outcome: partial`; duplicate checksum detected and not double-loaded — in `control-plane/tests/integration/test_file_ingestion_flow.py`

### Implementation for User Story 2

- [ ] T027 [P] [US2] Implement the object-storage connector (PyArrow for CSV/JSON/Parquet, routed through the existing `CloudGateway` for S3/GCS parity): `discover_schema`, `test_connection` (incl. `invalid_format` classification), `extract` with per-file record counts, SHA-256 checksums, and file metadata (R-03) — in `control-plane/src/datafoundry/controlplane/ingestion/connectors/object_storage.py`
- [ ] T028 [US2] Implement file validation and quarantine routing in the engine: validate each file (exists, readable, format, encoding, checksum — FR-006), route invalid files to `quarantine/<source_object>/<batch_id>/` with `_quarantine_metadata.json` + `QuarantineRecord` row, continue valid files (partial success, US2-AC2) — in `control-plane/src/datafoundry/controlplane/ingestion/validation.py` and `engine.py`
- [ ] T029 [US2] Implement duplicate-file detection: checksum comparison against previously ingested checksums for that source location; identical checksum → recorded, not double-loaded (FR-007, US2-AC3) — in `control-plane/src/datafoundry/controlplane/ingestion/engine.py`
- [ ] T030 [US2] Implement `GET /api/v1/quarantine` list/filter endpoint (query params `source_id`, `pipeline_id`, `batch_id`, `failed_check`, `since`, `until`) per contracts/ingestion-api.md §5 — in `control-plane/src/datafoundry/controlplane/api/contracts.py`

**Checkpoint**: US1 + US2 both work independently — database and file sources land validated data in Bronze with quarantine routing

---

## Phase 5: User Story 3 - Ingestion validation before promotion (Priority: P2)

**Goal**: Before ingested data becomes available downstream, the platform runs ingestion-level checks: schema/contract compatibility and record-count reconciliation. Breaking changes block promotion (batch stays `ingested`, never `ingestion_validated`), raise an alert naming the offending column/change, and inferred contracts require owner approval before they gate promotion.

**Independent Test**: quickstart Scenario 5 — approve the `customer` contract, mutate the source so `customer_id` becomes `string`, run the pipeline, verify the change is classified `breaking`, the batch is blocked from promotion, an alert names the column/change, and reconciliation reports source-vs-ingested differences.

### Tests for User Story 3 ⚠️

- [ ] T031 [P] [US3] Contract tests for `GET /sources/{id}/contracts` (list with origin/approval_status) and `POST /contracts/{id}/approve` (200 approved; owner authorisation required) per contracts/ingestion-api.md §5 — in `control-plane/tests/contract/test_contracts_api.py`
- [ ] T032 [P] [US3] Integration test for quickstart Scenario 5: approve inferred contract, mutate source schema (integer→string), run pipeline, verify `breaking` classification, batch `ingested` but not `ingestion_validated`, alert raised naming column/change, reconciliation reports difference — in `control-plane/tests/integration/test_contract_validation_flow.py`

### Implementation for User Story 3

- [ ] T033 [US3] Implement contract inference on first successful ingestion: generate `SourceContract` from observed schema, mark `origin=inferred`, `approval_status=pending` (never auto-approved — constitution V, FR-010, US3-AC3) — in `control-plane/src/datafoundry/controlplane/ingestion/contract.py`
- [ ] T034 [US3] Implement contract compatibility check at ingestion: compare observed schema against recorded contract, classify each difference breaking/non-breaking/warning per the classification table; breaking → batch `ingested` but not `ingestion_validated`, promotion blocked (FR-009, FR-010) — in `control-plane/src/datafoundry/controlplane/ingestion/validation.py`
- [ ] T035 [US3] Implement record-count reconciliation: source count vs. ingested count; difference beyond `reconciliation_tolerance` → batch fails reconciliation, promotion blocked until resolved or overridden (FR-009, US3-AC4) — in `control-plane/src/datafoundry/controlplane/ingestion/validation.py`
- [ ] T036 [US3] Implement alerting to the pipeline owner on run failure, breaking schema change, or reconciliation failure (FR-020): structured alert with offending column/change detail, redacted of secrets — in `control-plane/src/datafoundry/controlplane/ingestion/` (reuse observability/audit)
- [ ] T037 [US3] Implement the contracts API router per contracts/ingestion-api.md §5: `GET /sources/{id}/contracts`, `POST /contracts/{id}/approve` (owner authorisation, audit write) — in `control-plane/src/datafoundry/controlplane/api/contracts.py`

**Checkpoint**: US1 + US2 + US3 all work independently — no batch with a failed critical check is promoted without an explicit recorded override (SC-004)

---

## Phase 6: User Story 4 - Manage and monitor ingestion pipelines (Priority: P3)

**Goal**: A data engineer views all sources and pipelines, triggers a run manually, pauses/resumes a schedule, retries a failed run, and inspects execution history, logs, and per-run metrics (records processed, duration, outcome).

**Independent Test**: quickstart Scenario 6 — manually trigger, pause, resume, and retry a configured pipeline; verify history and logs reflect each action accurately, and a paused pipeline does not start runs when its schedule elapses.

### Tests for User Story 4 ⚠️

- [ ] T038 [P] [US4] Contract tests for `GET /pipelines` (list with state/schedule/last_run), `POST /pipelines/{id}/run` (202; 409 if active run), `POST /pipelines/{id}/pause`/`resume`, `POST /runs/{id}/retry` (202 with retry_of; 409), `GET /pipelines/{id}/runs` (history), `GET /runs/{id}` (with batches), `GET /batches/{id}`, `GET /runs/{id}/logs` per contracts/ingestion-api.md §3/§4 — in `control-plane/tests/contract/test_pipelines_api.py`
- [ ] T039 [P] [US4] Integration test for quickstart Scenario 6: manual trigger → run executes and appears in history; force failure → retry re-processes only what's needed with no duplicates; pause → schedule elapses with no run started; resume → runs resume — in `control-plane/tests/integration/test_pipeline_operations.py`

### Implementation for User Story 4

- [ ] T040 [US4] Implement the pipelines API router per contracts/ingestion-api.md §3: `GET /pipelines`, `POST /pipelines/{id}/run` (202; 409 on active run via partial unique index + `SELECT ... FOR UPDATE` lock, R-10), `POST /pipelines/{id}/pause`/`resume` (FR-014) — in `control-plane/src/datafoundry/controlplane/api/pipelines.py`
- [ ] T041 [US4] Implement the ingestion runs API router per contracts/ingestion-api.md §4: `GET /pipelines/{id}/runs` (history), `GET /runs/{id}` (with batches), `GET /batches/{id}` (detail + metadata), `GET /runs/{id}/logs` (log_ref), `POST /runs/{id}/retry` (re-reads from uncommitted watermark, no duplicates — R-06, FR-014) — in `control-plane/src/datafoundry/controlplane/api/ingestion_runs.py`
- [ ] T042 [US4] Implement the in-process scheduler per research R-04: background thread ticker querying due pipelines, dispatching runs through the feature 001 dispatcher hook; schedules evaluated in platform timezone; paused pipelines skipped (FR-011, FR-014) — in `control-plane/src/datafoundry/controlplane/ingestion/scheduler.py` and `api/app.py` wiring
- [ ] T043 [US4] Implement CLI `datafoundry pipeline pause/resume/retry` and `datafoundry ingest history` commands per quickstart Scenario 6 — in `cli/src/datafoundry/cli/commands/pipeline.py` and `cli/src/datafoundry/cli/commands/ingest.py`

**Checkpoint**: All four user stories independently functional — ingestion is fully self-service and operationally controllable

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Docs, quickstart validation, performance verification, security hardening

- [ ] T044 [P] Extend the `terraform/aws/storage/` and `terraform/gcp/storage/` zone contract to create the `quarantine/` prefix alongside Bronze/Silver/Gold (per plan.md Structure Decision) — in `terraform/aws/storage/` and `terraform/gcp/storage/`
- [ ] T045 [P] Write the feature 002 developer guide: ingestion architecture, connector framework, how to add a source type (registry pattern), simulated-gateway testing — in `control-plane/README.md` (append) and `specs/002-data-ingestion/quickstart.md` (verify)
- [ ] T046 Performance verification: connection test + schema discovery < 1 minute for typical schemas (FR-004, US1-AC1); incremental zero-duplicate run over ≥1M-record dataset (SC-005); record results in `docs/runbooks/performance-baseline.md`
- [ ] T047 [P] Security hardening pass: verify zero plaintext credentials in config exports, logs, run/batch/error payloads, and UI responses (SC-007); secret-scan on every ingestion write/export path; encrypted-channel enforcement (FR-016)
- [ ] T048 Run full quickstart.md validation (Scenarios 1–6) against a clean checkout with the simulated gateway and fix any gaps

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundational only
- **US2 (Phase 4)**: Depends on Foundational; shares the engine (T009) and validation (T010) — schedule after US1's engine lands, or staff in parallel
- **US3 (Phase 5)**: Depends on Foundational; contract inference (T033) runs during US1 ingestion — schedule after US1
- **US4 (Phase 6)**: Depends on Foundational; retry (T041) depends on the engine's watermark semantics (T009) — schedule after US1
- **Polish (Phase 7)**: Depends on all desired stories complete (T046 requires US1; T044 requires the storage contract)

### Key Intra-Phase Dependencies

- T005 (models) → T006 (migration) → everything persisting state
- T007 (schema) → T020/T021 (config API) → T024 (CLI configure)
- T008 (connector base/registry) → T018/T019 (DB connectors) → T022 (worker) → T023/T024 (CLI)
- T009 (engine) → T022 (worker), T028/T029 (US2), T041 (retry)
- T010 (validation) → T028 (file validation), T034/T035 (US3)
- T011 (contract) → T033/T034 (US3)
- T012 (secret-scan) → all write/export paths
- T013 (audit) → all mutating endpoints

### Parallel Opportunities

- Phase 1: T002–T004 all [P]
- Phase 2: T007–T014 all [P] (T005 → T006 sequential)
- Phase 3: T015–T017 all [P] (test tasks); T018/T019 [P] (connectors)
- Phase 4: T025–T026 [P] (tests); T027 [P] (connector)
- Phase 5: T031–T032 [P] (tests)
- Phase 6: T038–T039 [P] (tests)
- Phase 7: T044–T045, T047 [P]
- With multiple teams: connector framework (T008, T018/T019, T027) and API routers (T020/T021, T030, T037, T040/T041) proceed concurrently from the Phase 2 checkpoint

---

## Parallel Example: User Story 1

```bash
# Launch all US1 tests together (must fail before implementation):
Task: T015 "Contract tests sources API"
Task: T016 "Contract tests ingestion config API"
Task: T017 "Integration test Scenarios 1-3"

# Launch all US1 connectors together:
Task: T018 "PostgreSQL connector"
Task: T019 "SQL Server connector"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: quickstart Scenarios 1–3 with the simulated gateway
5. Deploy/demo: relational database source onboarded and landing data in Bronze

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. US1 → Scenarios 1–3 green → **MVP shipped** (database ingestion)
3. US2 → Scenario 4 green → file ingestion + quarantine
4. US3 → Scenario 5 green → validation before promotion (SC-004)
5. US4 → Scenario 6 green → operational control
6. Polish → quarantine prefix, docs, performance baseline, full quickstart pass

### Parallel Team Strategy

1. Team completes Setup + Foundational together
2. After the Foundational checkpoint:
   - Developer A: US1 engine/API/CLI (T018–T024)
   - Developer B: US2 file ingestion (T027–T030)
   - Developer C: US3 validation (T033–T037) then US4 (T040–T043)
3. Stories integrate at the Scenario checkpoints

---

## Notes

- [P] = different files/directories, no incomplete dependencies
- Commit after each task or logical group; configs flow through Git (GitOps principle)
- Every mutating endpoint must write an AuditRecord (T013) — verify in contract tests
- No plaintext secrets anywhere (SC-007): secret-scan (T012) is on every write/export path
- Adding a source type later = new connector module + registry entry only (FR-015 spirit) — do not modify the ingestion config schema or existing connectors
- Stop at any checkpoint to validate the story independently