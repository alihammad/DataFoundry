# Tasks: Shift-Left Data Quality Gates

**Input**: Design documents from `/specs/004-data-quality-gates/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (quality-api.md, gate-config-schema.md, contract-schema.md), quickstart.md

**Tests**: Included — the constitution (Principle IV: Shift-Left Testing & Contracts) and plan.md test plan explicitly mandate contract tests, and quickstart.md defines the test suite map (unit / contract / integration / manual E2E gate).

**Organization**: Tasks are grouped by user story (US1 P1, US2 P1, US3 P2, US4 P2, US5 P3, US6 P3) so each story can be implemented, tested, and delivered independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1, US2, US3, US4, US5, or US6
- Exact file paths included in every task

## Path Conventions

Monorepo per plan.md: `control-plane/src/datafoundry/controlplane/` (FastAPI service), `control-plane/tests/`, `cli/src/datafoundry/cli/`, `terraform/` (provider-isolated modules). This feature extends the existing feature 001/002 control plane — no new service or infrastructure.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add quality dependencies, package skeleton, and shared test harness

- [ ] T001 Add quality dependencies to `control-plane/pyproject.toml`: `duckdb` (SQL-based tests over Silver/Gold), `pyarrow` (record-level test evaluation; already present from feature 002). Verify `pip install -e ".[dev]"` resolves in `control-plane/.venv`.
- [ ] T002 [P] Create the `quality` package skeleton per plan.md: `control-plane/src/datafoundry/controlplane/quality/` with `__init__.py`, `gates/` (with `__init__.py`), `tests/` (with `__init__.py`), `contracts/` (with `__init__.py`), `quarantine.py`, `override.py`, `score.py`, `engine.py`, `gateway.py` — empty module stubs with docstrings.
- [ ] T003 [P] Create the `SimulatedQualityGateway` test harness in `control-plane/src/datafoundry/controlplane/quality/gateway.py`: in-memory fake zone inventories + record fixtures (Parquet/CSV/JSON tables with known duplicates, type errors, nulls, staleness, volumes) with fault-injection hooks (`force_test_error`, `force_stale_data`, `force_volume_anomaly`) so every gate/contract/quarantine/override/score path is exercisable offline — no docker/terraform/database required.
- [ ] T004 [P] Extend `control-plane/tests/conftest.py` with quality fixtures: a `simulated_quality_gateway` fixture, a `dataset` fixture (reuse feature 003 dataset helper or a minimal stub), and a `process_quality_run` fixture that drives the quality engine synchronously (mirroring the feature 001 `process_run` pattern).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core quality models, schema, gate/test framework, and engine primitives that every user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T005 Implement the eight quality SQLAlchemy models per data-model.md — `QualityGate`, `QualityTest`, `TestResult`, `GateReport`, `DataContract`, `ContractViolation`, `QuarantineEntry`, `GateOverride`, `QualityScore` — in `control-plane/src/datafoundry/controlplane/db/models.py`, including: unique `(dataset_id, transition, config_version)` on QualityGate, unique `(dataset_id, version)` on DataContract, unique `(dataset_id, transition)` on QualityGate, JSONB columns via the existing `with_variant` pattern.
- [X] T006 Create the Alembic migration for the nine new tables (revoke UPDATE/DELETE on any new append-only tables; reuse feature 001 migration conventions) — in `control-plane/src/datafoundry/controlplane/db/migrations/`. Verify offline SQL via `alembic upgrade head --sql`.
- [X] T007 [P] Implement the gate config Pydantic schema per contracts/gate-config-schema.md (strict, unknown fields rejected; `transition`/`environment_overrides`/`tests`; at least one CRITICAL/ERROR test; category-specific parameters) — in `control-plane/src/datafoundry/controlplane/config/quality_schema.py`.
- [X] T008 [P] Implement the `Test` ABC and registry per research R-01: `evaluate` operation returning a `TestResult`; registry maps `category` → test implementation (mirrors capability-registry pattern, FR-015 spirit) — in `control-plane/src/datafoundry/controlplane/quality/tests/base.py` and `tests/registry.py`.
- [X] T009 [P] Implement the gate decision core per research R-03: `Gate` model, decision function (BLOCK iff any CRITICAL/ERROR test `failed` or `not_run`; else PROMOTE), fail-closed semantics, gate config version recorded per run — in `control-plane/src/datafoundry/controlplane/quality/gates/gate.py`.
- [X] T010 [P] Implement the quality engine core per research R-02/R-03: run a gate → evaluate each test (PyArrow for record-level, DuckDB for SQL-based) → aggregate `GateReport` → decision; record `TestResult` per test — in `control-plane/src/datafoundry/controlplane/quality/engine.py`.
- [X] T011 [P] Wire secret-scan (feature 001 `config/secret_scan.py`) into every quality write/export path: `config_yaml`, `metadata_json`, `failure_reason`, `impact_assessment` (SC-007) — in `control-plane/src/datafoundry/controlplane/quality/` and `config/quality_schema.py`.
- [X] T012 [P] Add quality audit actions to the existing audit service (feature 001 `audit/service.py`): `gate.defined`, `gate.updated`, `gate.run`, `contract.registered`, `contract.inferred`, `contract.approved`, `quarantine.replayed`, `override.granted`, `override.expired` — each secret-scanned (FR-011, FR-012, SC-007).
- [X] T013 [P] Unit tests for foundational core: gate config schema conformance vs gate-config-schema.md, test registry resolution, gate decision function (fail-closed, `not_run` blocks), contract change classification table, and secret-scan on quality payloads — in `control-plane/tests/unit/test_quality_core.py`.

**Checkpoint**: Foundation ready — user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Quality gates block bad data at every layer transition (Priority: P1) 🎯 MVP

**Goal**: A data engineer defines a quality gate (composed of configurable tests with severity) on a layer transition; when a dataset is processed, the gate runs automatically, blocks promotion on any CRITICAL/ERROR failure (fail-closed), and produces a gate report listing every test with pass/fail/warning status and failed-record counts.

**Independent Test**: quickstart Scenario 1 — define a Bronze→Silver gate with a critical uniqueness test, run it against a batch with duplicate `customer_id` values, verify `decision: block`, promotion does not occur, and the report lists the failing test + failed-record count.

### Tests for User Story 1 ⚠️ (write first, ensure they FAIL before implementation)

- [X] T014 [P] [US1] Contract tests for `POST /datasets/{id}/gates/{transition}` (201 with gate_id/config_version; 422 all-errors incl. unknown category, invalid severity, no CRITICAL/ERROR test, secret-scan hit), `GET /datasets/{id}/gates/{transition}` (config_yaml/config_hash), `POST /gates/{id}/run` (promote/block decision, per-test results), `GET /gates/{id}/reports/{report_id}` per contracts/quality-api.md §1 — in `control-plane/tests/contract/test_gates_api.py`
- [X] T015 [P] [US1] Integration test for quickstart Scenario 1: define gate, run against batch with duplicates, verify `block`, promotion refused, report lists failing test + count — in `control-plane/tests/integration/test_gate_block_flow.py`

### Implementation for User Story 1

- [X] T016 [P] [US1] Implement the record-level test categories (PyArrow): `schema`, `type`, `nullability`, `uniqueness`, `completeness`, `validity`, `referential_integrity`, `contract`, `transformation`, `security` — each returning status + failed-record count/refs (R-02) — in `control-plane/src/datafoundry/controlplane/quality/tests/categories.py`
- [X] T017 [P] [US1] Implement the SQL-based test categories (DuckDB): `reconciliation`, `distribution`, `business_rule`, `volume`, `freshness`, `statistical` — each returning status + measured value (R-02) — in `control-plane/src/datafoundry/controlplane/quality/tests/categories.py`
- [X] T018 [US1] Implement the gates API router per contracts/quality-api.md §1: `POST /datasets/{id}/gates/{transition}`, `GET /datasets/{id}/gates/{transition}`, `POST /gates/{id}/run`, `GET /gates/{id}/reports/{report_id}`; secret-scan on `config_yaml`; audit writes — in `control-plane/src/datafoundry/controlplane/api/gates.py`
- [X] T019 [US1] Implement the tests listing helper per contracts/quality-api.md §2: `GET /datasets/{id}/tests` — in `control-plane/src/datafoundry/controlplane/api/tests.py`
- [X] T020 [US1] Implement CLI `datafoundry gate set/run/report` commands (typer) per quickstart Scenario 1 — in `cli/src/datafoundry/cli/commands/gate.py`

**Checkpoint**: US1 fully functional — a gate blocks bad data at a layer transition with a fail-closed decision and a drillable report

---

## Phase 4: User Story 2 - Data contracts validated at ingestion (Priority: P1)

**Goal**: Producers and consumers agree a data contract per dataset; the platform validates incoming data against it during ingestion, classifies violations breaking/non-breaking/warning, and blocks promotion on breaking changes; where no explicit contract exists, the platform infers one marked pending approval.

**Independent Test**: quickstart Scenario 2 — register an explicit contract, feed a batch that changes a column type, verify `breaking` classification + blocked promotion; infer a contract on first ingestion, verify `pending`, approve it, verify it then gates promotion.

### Tests for User Story 2 ⚠️

- [X] T021 [P] [US2] Contract tests for `POST /datasets/{id}/contracts/register` (201 explicit approved; 422 invalid schema), `POST /datasets/{id}/contracts/infer` (201 pending), `POST /contracts/{id}/approve` (200 approved; owner authorisation), `GET /datasets/{id}/contracts` (list + violations) per contracts/quality-api.md §3 — in `control-plane/tests/contract/test_contracts_api.py`
- [X] T022 [P] [US2] Integration test for quickstart Scenario 2: register explicit contract, mutate column type, verify `breaking` + blocked; infer, approve, verify it gates promotion — in `control-plane/tests/integration/test_contract_validation_flow.py`

### Implementation for User Story 2

- [X] T023 [P] [US2] Implement contract validation module per research R-04: compare observed schema against recorded contract, classify each difference breaking/non-breaking/warning per the classification table; breaking → block promotion (FR-006, SC-007) — in `control-plane/src/datafoundry/controlplane/quality/contracts/validate.py`
- [X] T024 [P] [US2] Implement contract inference per research R-04: generate `DataContract` from observed schema on first successful ingestion, mark `origin=inferred`, `approval_status=pending` (never auto-approved — constitution V, FR-007) — in `control-plane/src/datafoundry/controlplane/quality/contracts/infer.py`
- [X] T025 [US2] Implement the contracts API router per contracts/quality-api.md §3: `POST /datasets/{id}/contracts/register`, `POST /datasets/{id}/contracts/infer`, `POST /contracts/{id}/approve`, `GET /datasets/{id}/contracts`; owner authorisation on approve; audit writes — in `control-plane/src/datafoundry/controlplane/api/contracts.py`
- [X] T026 [US2] Implement CLI `datafoundry contract register/infer/approve` commands per quickstart Scenario 2 — in `cli/src/datafoundry/cli/commands/contract.py`

**Checkpoint**: US1 + US2 both work independently — contracts validated at ingestion with breaking changes blocking promotion and inferred contracts requiring approval

---

## Phase 5: User Story 3 - Quarantine with investigation and replay (Priority: P2)

**Goal**: Failed records/files go to quarantine with full failure context; an engineer investigates through the API, fixes the root cause, and replays the records so they re-enter processing without full re-extraction; replay must not duplicate processed records and respect retention expiry.

**Independent Test**: quickstart Scenario 3 — ingest a batch with known bad records, verify each appears in quarantine with reason/failed test/batch id/timestamp, filter by source/pipeline/batch/reason/date, fix the cause, replay, verify records land correctly with no duplicates, and replay after retention expiry refused.

### Tests for User Story 3 ⚠️

- [ ] T027 [P] [US3] Contract tests for `GET /datasets/{id}/quarantine` (list + filters), `POST /quarantine/{id}/replay` (202 replay_run_id; 409 on retention expiry / not eligible), `GET /quarantine/{id}` (full entry) per contracts/quality-api.md §4 — in `control-plane/tests/contract/test_quarantine_api.py`
- [ ] T028 [P] [US3] Integration test for quickstart Scenario 3: ingest bad records, verify quarantine entries with full context, fix cause, replay, verify no duplicates + removal from active queue, verify retention-expired replay refused — in `control-plane/tests/integration/test_quarantine_replay_flow.py`

### Implementation for User Story 3

- [ ] T029 [P] [US3] Implement quarantine module per research R-05: write `QuarantineEntry` with full failure context (payload_ref, failure_reason, failed_test, batch_id, retention_expiry, attempt_count), read/filter, retention policy (FR-008, FR-010) — in `control-plane/src/datafoundry/controlplane/quality/quarantine.py`
- [ ] T030 [US3] Implement replay per research R-05: re-enter records at the appropriate stage, idempotent (no duplicate processed records), increment `attempt_count` on failure, escalate to owner beyond threshold (FR-009), refuse replay after `retention_expiry` (FR-010) — in `control-plane/src/datafoundry/controlplane/quality/quarantine.py`
- [ ] T031 [US3] Implement the quarantine API router per contracts/quality-api.md §4: `GET /datasets/{id}/quarantine`, `POST /quarantine/{id}/replay`, `GET /quarantine/{id}`; audit writes — in `control-plane/src/datafoundry/controlplane/api/quarantine.py` (note: path is `control-plane/src/datafoundry/controlplane/api/quarantine.py`)
- [ ] T032 [US3] Implement CLI `datafoundry quarantine list/replay` commands per quickstart Scenario 3 — in `cli/src/datafoundry/cli/commands/quarantine.py`

**Checkpoint**: US1 + US2 + US3 all work independently — gates, contracts, and quarantine with replay are independently testable

---

## Phase 6: User Story 4 - Configurable tests and severity per dataset and environment (Priority: P2)

**Goal**: A data engineer configures tests from the standard categories with severity (CRITICAL/ERROR/WARNING/INFORMATIONAL), configurable per dataset and per environment (stricter in Production, looser in Development); severity behaviour is visible in the configuration.

**Independent Test**: quickstart Scenario 1 (env override) — configure the same test as WARNING in Development and CRITICAL in Production, feed identical borderline data, verify the different gate outcomes.

### Tests for User Story 4 ⚠️

- [X] T033 [P] [US4] Contract tests for `POST /datasets/{id}/gates/{transition}` with `environment_overrides` (per-environment severity applied; Development vs Production different outcomes) per contracts/gate-config-schema.md — in `control-plane/tests/contract/test_gates_api.py`
- [X] T034 [P] [US4] Integration test for quickstart Scenario 1 env-override: same test WARNING in Development, CRITICAL in Production, identical data → Development continues, Production blocks — in `control-plane/tests/integration/test_env_severity_flow.py`

### Implementation for User Story 4

- [X] T035 [US4] Implement per-environment severity resolution in the gate engine: apply `environment_overrides` from `QualityGate.environment_overrides` to each test's effective severity before decision (FR-005); environment difference visible in config export — in `control-plane/src/datafoundry/controlplane/quality/gates/gate.py`
- [X] T036 [US4] Implement severity semantics in the decision function: CRITICAL/ERROR block by default, WARNING continues with notification, INFORMATIONAL records only (FR-004); WARNING/INFORMATIONAL failures recorded in the report but do not block — in `control-plane/src/datafoundry/controlplane/quality/gates/gate.py`

**Checkpoint**: US1–US4 all work — gates are configurable per dataset and per environment with correct severity semantics

---

## Phase 7: User Story 5 - Controlled manual override of a failed gate (Priority: P3)

**Goal**: An authorised user overrides a failed gate with a full record (authorisation, reason, expiry, identity, timestamp, impact assessment); the override applies only to the specific blocked run, expires automatically, and is permanently audited; incomplete overrides and unauthorised attempts are rejected.

**Independent Test**: quickstart Scenario 4 — block a gate, apply an override with all required fields, verify promotion proceeds and the override is auditable; verify an incomplete override is rejected and an expired override no longer permits promotion.

### Tests for User Story 5 ⚠️

- [X] T037 [P] [US5] Contract tests for `POST /reports/{id}/override` (201 active; 422 incomplete; 403 unauthorised + recorded), `GET /datasets/{id}/overrides` (audit history) per contracts/quality-api.md §5 — in `control-plane/tests/contract/test_overrides_api.py`
- [X] T038 [P] [US5] Integration test for quickstart Scenario 4: block gate, grant override, verify promotion proceeds + auditable; incomplete override rejected; expired override grants no permission — in `control-plane/tests/integration/test_override_flow.py`

### Implementation for User Story 5

- [X] T039 [P] [US5] Implement override module per research R-06: validate required fields (authorisation, reason, expiry, identity, timestamp, impact assessment), reject incomplete overrides, scope to the specific blocked run, auto-expire, permanent audit (FR-011, FR-012) — in `control-plane/src/datafoundry/controlplane/quality/override.py`
- [X] T040 [US5] Implement the overrides API router per contracts/quality-api.md §5: `POST /reports/{id}/override`, `GET /datasets/{id}/id/overrides`; authorisation check; audit writes — in `control-plane/src/datafoundry/controlplane/api/overrides.py`
- [X] T041 [US5] Implement CLI `datafoundry override grant` command per quickstart Scenario 4 — in `cli/src/datafoundry/cli/commands/override.py`

**Checkpoint**: US1–US5 all work — overrides are the only path past a failed gate, fully audited and scoped to the granted run

---

## Phase 8: User Story 6 - Test results as observable metadata (Priority: P3)

**Goal**: Every test execution is recorded as metadata (dataset, pipeline, run id, tests run/passed/warned/failed, overall status, failed record counts, gate config version); the platform computes a deterministic quality score per dataset with history and drill-down from a summary into an individual run, failing test, failed records, and quarantine entries.

**Independent Test**: quickstart Scenario 5 — run the pipeline several times with varying outcomes, verify the score + history reflect the runs accurately, drill into a failed run to reach the failing test, its failed records, and quarantine entries.

### Tests for User Story 6 ⚠️

- [X] T042 [P] [US6] Contract tests for `GET /datasets/{id}/quality` (score + history), `GET /datasets/{id}/quality/history` (per-run results), `GET /reports/{id}` (drill-down to failing test + failed records + quarantine) per contracts/quality-api.md §6 — in `control-plane/tests/contract/test_quality_api.py`
- [X] T043 [P] [US6] Integration test for quickstart Scenario 5: run pipeline with varying outcomes, verify score + history reflect runs, drill into failed run reaches failing test + failed records + quarantine — in `control-plane/tests/integration/test_quality_observability_flow.py`

### Implementation for User Story 6

- [X] T044 [P] [US6] Implement quality score module per research R-07: deterministic formula over recent gate results (0–100), history computation, drill-down data (FR-014, FR-015) — in `control-plane/src/datafoundry/controlplane/quality/score.py`
- [X] T045 [US6] Implement the quality API router per contracts/quality-api.md §6: `GET /datasets/{id}/quality`, `GET /datasets/{id}/quality/history`, `GET /reports/{id}` (drill-down) — in `control-plane/src/datafoundry/controlplane/api/quality.py` (note: path is `control-plane/src/datafoundry/controlplane/api/quality.py`)
- [X] T046 [US6] Implement CLI `datafoundry quality get/history` and `datafoundry gate report` drill-down per quickstart Scenario 5 — in `cli/src/datafoundry/cli/commands/gate.py`

**Checkpoint**: US1–US6 all work — quality is observable with scores, history, and drill-down to failing records and quarantine

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Alerting, GitOps versioning, cloud-independence verification, and final validation

- [ ] T047 [P] Implement alerting on gate failures, contract violations, warning-threshold breaches through the platform's notification channels (FR-016): structured alert with failing test detail, redacted of secrets — in `control-plane/src/datafoundry/controlplane/quality/` (reuse observability/audit)
- [ ] T048 [P] Implement GitOps versioning for test/gate/contract definitions through the existing `config/gitops.py` pattern (FR-018); test-first support: contracts/tests definable before transformation exists (FR-020) — in `control-plane/src/datafoundry/controlplane/config/quality_schema.py` and `config/gitops.py`
- [ ] T049 [P] Verify cloud-independence of gate outcomes (FR-019, SC-008): identical gate outcomes for identical data/config on both clouds — extend `scripts/parity_checklist.py` with a quality parity check (mirroring feature 002 SC-003 pattern)
- [ ] T050 [P] Run full test suite + ruff clean: `control-plane/.venv/bin/python -m pytest` (all unit + contract + integration) and `ruff check` + `ruff format` clean across control-plane + cli; verify `alembic upgrade head --sql` offline SQL — final gate.

**Checkpoint (Final)**: Feature 004 complete — all 6 user stories independently testable, ruff clean, tests pass, cloud-independent gate outcomes verified