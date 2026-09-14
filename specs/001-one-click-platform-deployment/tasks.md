# Tasks: One-Click Platform Deployment

**Input**: Design documents from `/specs/001-one-click-platform-deployment/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (deployment-api.md, platform-config-schema.md, capability-catalog.md), quickstart.md

**Tests**: Included — the constitution (Principle IV: Shift-Left Testing & Contracts) and plan.md test plan explicitly mandate contract tests, and quickstart.md defines the test suite map (unit / contract / terraform / integration / manual E2E gate).

**Organization**: Tasks are grouped by user story (US1 P1, US2 P2, US3 P3) so each story can be implemented, tested, and delivered independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1, US2, or US3
- Exact file paths included in every task

## Path Conventions

Monorepo per plan.md: `control-plane/src/datafoundry/controlplane/` (FastAPI service), `control-plane/tests/`, `cli/src/datafoundry/cli/`, `terraform/` (provider-isolated modules), `platform-configs/`, `docker/`, `docs/runbooks/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Repository scaffolding, toolchain, and local development environment

- [X] T001 Create monorepo directory structure per plan.md Project Structure: `control-plane/src/datafoundry/controlplane/{api,config,engine,providers,capabilities,health,db,audit}`, `control-plane/tests/{unit,contract,integration}`, `cli/src/datafoundry/cli/`, `terraform/{control-plane/{aws,gcp},aws,gcp,modules}`, `platform-configs/examples/`, `docker/`, `docs/runbooks/`
- [X] T002 [P] Create `control-plane/pyproject.toml` — Python 3.12; dependencies: fastapi, pydantic>=2, sqlalchemy>=2, alembic, pyyaml, opentelemetry-sdk, opentelemetry-instrumentation-fastapi, boto3, google-cloud-storage, uvicorn; dev: pytest, pytest-asyncio, httpx, ruff
- [X] T003 [P] Create `cli/pyproject.toml` — `datafoundry` console script; dependencies: httpx, typer, rich, pyyaml
- [X] T004 [P] Create `docker/docker-compose.dev.yml` (PostgreSQL 15, LocalStack with S3/DynamoDB/KMS/STS, OpenMetadata container for dev) and `docker/Dockerfile.control-plane`, `docker/Dockerfile.cli`
- [X] T005 [P] Pin toolchain: `.terraform-version` (>= 1.9), `.tflint.hcl`, `terraform/` provider version pins file `terraform/modules/versions.tf` template
- [X] T006 [P] Configure linting/formatting: `ruff.toml` at repo root (ruff check + format), pre-commit config `.pre-commit-config.yaml` (ruff, tflint, gitleaks)
- [X] T007 [P] Create example platform configs used by quickstart scenarios in `platform-configs/examples/`: `dev-aws-localstack.yaml`, `bad-config.yaml` (semantic_layer without catalog + unsupported region + prod without approval), `fail-at-orchestration.yaml` (dev fault-injection flag), `prod-no-approval.yaml`, `dev-gcp-sandbox.yaml`, `dev-aws-sandbox.yaml` — all conforming to contracts/platform-config-schema.md
- [X] T008 [P] Create CI workflow `.github/workflows/ci.yml`: ruff, pytest (unit/contract), `terraform validate` + `tflint` per module, `terraform plan -detailed-exitcode` on rendered example workspaces, gitleaks scan

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core schemas, registry, persistence, Terraform execution primitives, and API skeleton that every user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T009 Implement `PlatformConfig` Pydantic v2 model (strict mode, unknown fields rejected) exactly per contracts/platform-config-schema.md field reference — in `control-plane/src/datafoundry/controlplane/config/schema.py`
- [X] T010 [P] Implement secret-scan pass (AWS/GCP key patterns, PEM blocks, entropy heuristic) applied to config YAML, audit payloads, error details, and exports (SC-006, R-09) — in `control-plane/src/datafoundry/controlplane/config/secret_scan.py`
- [X] T011 [P] Implement capability registry (MVP keys, `selectable`, `depends_on` graph incl. implicit `database` auto-enable, `module_path` pattern `terraform/{provider}/{key}/`, `health_check` runner id, `deploy_step`) per contracts/capability-catalog.md — in `control-plane/src/datafoundry/controlplane/capabilities/registry.py`
- [X] T012 [P] Implement provider adapter framework + AWS and GCP adapters (region lists, region-capability matrix source, state backend config per R-05, credential probe hooks) using the registry pattern (FR-015: adding a provider must not touch core) — in `control-plane/src/datafoundry/controlplane/providers/base.py`, `providers/aws.py`, `providers/gcp.py`
- [X] T013 Implement SQLAlchemy 2 models for Platform, PlatformConfigVersion, DeploymentRun, DeploymentStep, HealthCheckResult, AuditRecord per data-model.md, including unique constraint `(provider, cloud_scope_id, name)`, partial unique index on DeploymentRun `WHERE status IN ('queued','running','paused')`, and append-only AuditRecord — in `control-plane/src/datafoundry/controlplane/db/models.py`
- [X] T014 Set up Alembic and create initial migration from T013 models (revoke UPDATE/DELETE on audit_records from the application role) — in `control-plane/src/datafoundry/controlplane/db/migrations/` and `control-plane/alembic.ini`
- [X] T015 [P] Implement minimal Terraform CLI subprocess wrapper (`init`, `validate`, `plan`, `apply`, `destroy` with `-json` streaming parse, per-run workspace selection, pinned binary check) per R-01 — in `control-plane/src/datafoundry/controlplane/engine/terraform.py`
- [X] T016 Implement per-run root module generator: render `terraform/workspaces/<run_id>/main.tf.json` composing enabled capability modules in dependency order with the common input/output contract, disabled capabilities produce no block (R-01, R-11, FR-012) — in `control-plane/src/datafoundry/controlplane/engine/generator.py`
- [X] T017 [P] Create FastAPI application skeleton with `/api/v1` base path, RFC 9457 problem+json error handlers, unauthenticated `GET /healthz`, and router registration points — in `control-plane/src/datafoundry/controlplane/api/app.py` and `api/errors.py`
- [X] T018 [P] Implement AuthN/AuthZ dependency (federated cloud IAM identity extraction, caller identity propagation, authorisation check hooks for platform create/update/destroy, 403 with missing-permission detail per FR-018) — in `control-plane/src/datafoundry/controlplane/api/auth.py`
- [X] T019 [P] Implement audit service: append-only AuditRecord writes (actor, action, occurred_at, secret-scanned jsonb payload) for every mutating operation (FR-014) — in `control-plane/src/datafoundry/controlplane/audit/service.py`
- [X] T020 [P] Wire OpenTelemetry SDK (FastAPI instrumentation, traces/metrics export) and structured JSON logging with secret-pattern redaction (R-09, R-10) — in `control-plane/src/datafoundry/controlplane/observability.py`
- [X] T021 [P] Implement environment/settings management (DATABASE_URL, terraform binary path, provider credentials mode ambient/per-session, dev fault-injection flag) — in `control-plane/src/datafoundry/controlplane/config/settings.py`
- [X] T022 [P] Unit tests for foundational core: PlatformConfig schema conformance vs platform-config-schema.md, secret-scan detection/false positives, capability registry dependency closure and implicit database enablement — in `control-plane/tests/unit/test_config_core.py`
- [X] T023 [P] Unit tests for state machines: Platform status transitions and DeploymentRun status transitions per data-model.md (incl. paused on credential expiry, one-active-run invariant) — in `control-plane/tests/unit/test_state_machines.py`

**Checkpoint**: Foundation ready — user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Deploy a complete lakehouse platform in one click (Priority: P1) 🎯 MVP

**Goal**: An authorised user submits a platform configuration; the system validates it (all errors at once), provisions networking/secrets/storage-zones/IAM/compute/database/catalog/orchestration/ingestion/monitoring via per-step Terraform runs on AWS or GCP, initialises Bronze/Silver/Gold zones and the catalog, runs health checks, and reports the platform ready — with ordered step progress, retry-from-failed-step, and scoped rollback.

**Independent Test**: quickstart.md Scenarios 1–3 — submit valid deploys for AWS (LocalStack) and GCP configs; verify all components exist, zones initialised, health checks pass, platform `ready`; invalid configs rejected pre-provisioning with all errors in one 422; forced mid-deployment failure shows failed step with reason, retry resumes from that step, rollback leaves zero orphaned resources.

### Tests for User Story 1 ⚠️ (write first, ensure they FAIL before implementation)

- [ ] T024 [P] [US1] Contract tests for `POST /api/v1/platforms` (202 shape, 422 all-errors body with `{path,code,message,remediation}`, 409 name_taken, 403 insufficient_permissions, Idempotency-Key replay) and `POST /api/v1/validate` per contracts/deployment-api.md §1/§3 — in `control-plane/tests/contract/test_platform_deploy_api.py`
- [ ] T025 [P] [US1] Contract tests for `GET /api/v1/runs/{run_id}` (ordered steps, per-step status incl. `skipped` with detail, failed step `error_detail`/`attempt`), `POST /runs/{run_id}/retry` (202/409), `POST /runs/{run_id}/rollback` (202/409) per contracts/deployment-api.md §2 — in `control-plane/tests/contract/test_runs_api.py`
- [ ] T026 [P] [US1] Integration test for quickstart Scenarios 1+2: bad-config rejected with all three errors and zero resources created; LocalStack deploy reaches `succeeded`, platform `ready`, zone prefixes exist, catalog lists zones, disabled capabilities recorded `skipped` — in `control-plane/tests/integration/test_deploy_flow.py`
- [ ] T027 [P] [US1] Integration test for quickstart Scenario 3: fault-injected failure at `orchestration` step, earlier steps `succeeded`/later `pending`, partial state inspectable, retry resumes from failed step with attempt increment, rollback destroys only this run's workspace leaving zero orphans — in `control-plane/tests/integration/test_failure_handling.py`

### Implementation for User Story 1

- [ ] T028 [US1] Implement two-stage validation engine (collect-all, never fail-fast): schema/semantic rules 1–8 from contracts/platform-config-schema.md (naming regex + reserved names, region-capability matrix, transitive dependency closure, production controls, secret scan, uniqueness pre-check incl. live cloud scope per R-12) plus stage-2 `terraform validate`/`plan` error translation (R-07) — in `control-plane/src/datafoundry/controlplane/config/validation.py`
- [ ] T029 [US1] Implement permission pre-check (FR-018 fail-fast): STS `GetCallerIdentity` + required-permission probes on AWS, token introspection on GCP; produce precise missing-permission list for 403 responses — in `control-plane/src/datafoundry/controlplane/providers/permissions.py`
- [ ] T030 [US1] Implement deployment orchestrator: canonical 15-step sequence per R-11 (with `approval-gate` inserted before step 5 for production, FR-010), DeploymentStep persistence with per-step status/timestamps/error_detail, `skipped` for disabled capabilities, platform status transitions, `SELECT ... FOR UPDATE` advisory lock enforcing one active run per platform (R-12) — in `control-plane/src/datafoundry/controlplane/engine/orchestrator.py`
- [ ] T031 [US1] Implement retry-from-failed-step and scoped rollback (R-06, FR-009): retry re-applies the failed step's module in the same per-run workspace and continues; rollback runs `terraform destroy` in reverse step order scoped to the run's workspace only; credential-expiry → `paused`, resumable, never auto-destroys — in `control-plane/src/datafoundry/controlplane/engine/recovery.py`
- [ ] T032 [US1] Implement async deployment worker supervising Terraform subprocess runs, streaming `-json` progress into DeploymentStep updates, checkpointing to PostgreSQL (R-01) — in `control-plane/src/datafoundry/controlplane/engine/worker.py`
- [ ] T033 [US1] Implement health check framework and MVP runners registered per capability (R-08): dns-resolve, kms-decrypt-probe, zone-head (bronze/silver/gold), token-mint, instance-ready, pg-ping, http /health (OpenMetadata), airflow /health, endpoint-responds, synthetic-datapoint; write HealthCheckResult rows; platform `ready` only when all enabled capabilities healthy (FR-007) — in `control-plane/src/datafoundry/controlplane/health/runners.py` and `health/framework.py`
- [ ] T034 [US1] Implement storage-zone + catalog initialisation job (FR-005): create Bronze/Silver/Gold prefixes, register zones and capability inventory in OpenMetadata before readiness — in `control-plane/src/datafoundry/controlplane/engine/init_jobs.py`
- [ ] T035 [US1] Implement API router `POST /api/v1/platforms` (the "one click": validate → register Platform + PlatformConfigVersion → queue run → 202; 422/409/403 paths; Idempotency-Key; audit write) and `GET /api/v1/platforms` (cursor pagination, PlatformSummary) — in `control-plane/src/datafoundry/controlplane/api/platforms.py`
- [ ] T036 [US1] Implement API router `GET /api/v1/runs/{run_id}`, `POST /api/v1/runs/{run_id}/retry`, `POST /api/v1/runs/{run_id}/rollback` per contracts/deployment-api.md §2 — in `control-plane/src/datafoundry/controlplane/api/runs.py`
- [ ] T037 [US1] Implement API router `POST /api/v1/validate` (no side effects, same all-errors 422 body) — in `control-plane/src/datafoundry/controlplane/api/validate.py`
- [ ] T038 [P] [US1] Create cloud-neutral shared Terraform glue: common variable schema file, tags/labels convention, shared init scripts per capability contract common inputs/outputs — in `terraform/modules/`
- [ ] T039 [P] [US1] AWS `networking` module (VPC, private isolation, CIDR, TLS-enforcing endpoints; common inputs/outputs contract) — in `terraform/aws/networking/`
- [ ] T040 [P] [US1] AWS `secrets` module (KMS CMK, Secrets Manager entries, encryption from creation, FR-017) — in `terraform/aws/secrets/`
- [ ] T041 [P] [US1] AWS `storage` module (S3 bucket, Bronze/Silver/Gold prefixes, versioned S3+DynamoDB Terraform state backend per R-05, KMS encryption, Bronze immutability) — in `terraform/aws/storage/`
- [ ] T042 [P] [US1] AWS `iam` module (least-privilege roles/policies per capability, service identities) — in `terraform/aws/iam/`
- [ ] T043 [P] [US1] AWS `compute` module (size small/medium/large per config) — in `terraform/aws/compute/`
- [ ] T044 [P] [US1] AWS `database` module (RDS PostgreSQL 15, KMS-encrypted, pg-ping health target) — in `terraform/aws/database/`
- [ ] T045 [P] [US1] AWS `catalog` module (OpenMetadata containerised deployment backed by platform database, http /health target, R-04) — in `terraform/aws/catalog/`
- [ ] T046 [P] [US1] AWS `orchestration` module (MWAA managed Airflow behind the logical contract, R-03) — in `terraform/aws/orchestration/`
- [ ] T047 [P] [US1] AWS `ingestion` module (ingestion service runtime, endpoint-responds health target) — in `terraform/aws/ingestion/`
- [ ] T048 [P] [US1] AWS `monitoring` module (OTel collector, dashboards, alerts, synthetic-datapoint health target) — in `terraform/aws/monitoring/`
- [ ] T049 [P] [US1] AWS placeholder modules `quality` and `semantic` implementing the common contract with runner-heartbeat/endpoint-responds targets (full behaviour delivered by features 004/006) — in `terraform/aws/quality/` and `terraform/aws/semantic/`
- [ ] T050 [P] [US1] GCP `networking` module (VPC, private isolation, CIDR; mirrors AWS contract) — in `terraform/gcp/networking/`
- [ ] T051 [P] [US1] GCP `secrets` module (Cloud KMS key, Secret Manager entries) — in `terraform/gcp/secrets/`
- [ ] T052 [P] [US1] GCP `storage` module (GCS bucket, zone prefixes, GCS native-locking state backend per R-05, CMEK encryption, Bronze immutability) — in `terraform/gcp/storage/`
- [ ] T053 [P] [US1] GCP `iam` module (least-privilege roles/service accounts) — in `terraform/gcp/iam/`
- [ ] T054 [P] [US1] GCP `compute` module — in `terraform/gcp/compute/`
- [ ] T055 [P] [US1] GCP `database` module (Cloud SQL PostgreSQL 15, CMEK-encrypted) — in `terraform/gcp/database/`
- [ ] T056 [P] [US1] GCP `catalog` module (OpenMetadata, identical logical contract to AWS) — in `terraform/gcp/catalog/`
- [ ] T057 [P] [US1] GCP `orchestration` module (Cloud Composer managed Airflow, R-03) — in `terraform/gcp/orchestration/`
- [ ] T058 [P] [US1] GCP `ingestion` module — in `terraform/gcp/ingestion/`
- [ ] T059 [P] [US1] GCP `monitoring` module (OTel collector + Cloud Monitoring dashboards/alerts) — in `terraform/gcp/monitoring/`
- [ ] T060 [P] [US1] GCP placeholder modules `quality` and `semantic` — in `terraform/gcp/quality/` and `terraform/gcp/semantic/`
- [ ] T061 [US1] Generate the region-capability matrix from actual module availability per provider (contract rule: generated, not hand-maintained) and expose it to validation and adapters — in `control-plane/src/datafoundry/controlplane/providers/region_matrix.py`
- [ ] T062 [US1] CLI skeleton (typer app, API client, auth token handling) and `datafoundry validate --config` command (exit 1 with all errors + remediation) — in `cli/src/datafoundry/cli/main.py` and `cli/src/datafoundry/cli/commands/validate.py`
- [ ] T063 [US1] CLI `datafoundry deploy --config [--wait]` command: POST /platforms, stream ordered step progress from GET /runs/{run_id}, surface failures with error_detail — in `cli/src/datafoundry/cli/commands/deploy.py`
- [ ] T064 [US1] CLI `datafoundry status --platform` command (run progress, step list, failure reasons) — in `cli/src/datafoundry/cli/commands/status.py`
- [ ] T065 [US1] End-to-end integration pass on LocalStack: run Scenarios 1–3, fix step-ordering/timing issues, confirm run wall time recorded and disabled capabilities skipped, confirm audit records written for deploy/retry/rollback

**Checkpoint**: US1 fully functional — a usable empty governed lakehouse deploys in one click on both providers with progress, retry, and rollback

---

## Phase 4: User Story 2 - Declarative, reproducible environments (Priority: P2)

**Goal**: Platform configurations are versioned, exportable (no plaintext secrets), and re-appliable to recreate an identical platform; configuration changes flow through GitOps into update runs; full deployment history is auditable; platforms can be destroyed and reproduced from code.

**Independent Test**: quickstart Scenarios 4–5 — export a deployed platform's config, destroy it, redeploy from the export and verify identical capabilities/settings/zones and matching `config_hash`; gitleaks clean export; production-without-approval rejected; duplicate name in same cloud scope returns 409 with first platform untouched.

### Tests for User Story 2 ⚠️

- [ ] T066 [P] [US2] Contract tests for `GET /api/v1/platforms/{platform_id}/config` (version, config_yaml, config_hash, git_ref; secret-scan guarantee), `DELETE /api/v1/platforms/{platform_id}` (202 destroy run; approval_ref required for production), `GET /api/v1/platforms/{platform_id}/runs` (auditable history fields incl. duration_seconds, outcome) — in `control-plane/tests/contract/test_config_export_api.py`
- [ ] T067 [P] [US2] Integration test for quickstart Scenario 4: export → destroy → redeploy produces matching platform (diff only timestamps/run ids), identical config_hash (determinism), gitleaks-clean export — in `control-plane/tests/integration/test_reproducibility.py`
- [ ] T068 [P] [US2] Integration test for quickstart Scenario 5: production deploy without approval rejected in validation with nothing provisioned; duplicate platform name in same cloud scope → 409 name_taken, first platform untouched — in `control-plane/tests/integration/test_prod_controls.py`

### Implementation for User Story 2

- [ ] T069 [US2] Implement config export service: canonical YAML serialisation (sorted keys, normalised whitespace), SHA-256 `config_hash`, mandatory secret-scan before returning/storing (FR-011, SC-006) — in `control-plane/src/datafoundry/controlplane/config/export.py`
- [ ] T070 [US2] Implement PlatformConfigVersion lifecycle: immutable versioned snapshots, version increment per platform, idempotent deploy on identical config_hash, source (`api`/`cli`/`git`) + git_ref provenance recording — in `control-plane/src/datafoundry/controlplane/config/versioning.py`
- [ ] T071 [US2] Implement update flow: config change on a `ready`/`degraded` platform → validation → new config version → `update` run (state transition ready→deploying per data-model.md), re-rendering only affected modules — in `control-plane/src/datafoundry/controlplane/engine/orchestrator.py` (update path) and `api/platforms.py`
- [ ] T072 [US2] Implement destroy flow: `DELETE /api/v1/platforms/{platform_id}` (production requires `?approval_ref=`), `destroy` run type, reverse-order teardown, platform → `destroyed` — in `control-plane/src/datafoundry/controlplane/api/platforms.py` and `engine/recovery.py`
- [ ] T073 [US2] Implement `GET /api/v1/platforms/{platform_id}/runs` auditable history endpoint (FR-014: who, when, configuration version, outcome, duration) — in `control-plane/src/datafoundry/controlplane/api/platforms.py`
- [ ] T074 [US2] GitOps workflow: `platform-configs/<platform-name>/<env>.yaml` layout enforcement, git-source ingestion recording (`source=git`, `git_ref`), PR-gated change documentation — in `platform-configs/README.md` and `control-plane/src/datafoundry/controlplane/config/gitops.py`
- [ ] T075 [US2] CLI `datafoundry export --platform` (writes secret-free YAML to stdout) and `datafoundry destroy --platform [--wait]` commands — in `cli/src/datafoundry/cli/commands/export.py` and `cli/src/datafoundry/cli/commands/destroy.py`

**Checkpoint**: US1 + US2 both work independently — platforms are fully reproducible from versioned code (SC-002)

---

## Phase 5: User Story 3 - Capability selection and platform health (Priority: P3)

**Goal**: Users select capabilities at deploy time (unselected capabilities are not provisioned and can be enabled later via config change) and get a dashboard-data view: cloud, region, environment, per-component health with last check time and failure detail, storage utilisation, latest run, recent failures.

**Independent Test**: quickstart Scenario 7 + US3 acceptance — deploy two platforms with different capability selections and verify only selected components exist; GET platform detail reflects real component state; breaking a component flips platform to `degraded` with the component flagged, reason, and last check time.

### Tests for User Story 3 ⚠️

- [ ] T076 [P] [US3] Contract tests for `GET /api/v1/platforms/{platform_id}` (health array, storage_utilisation, latest_run, recent_failures shape), `GET /api/v1/capabilities`, `GET /api/v1/providers/{provider}/regions?capability=`, `POST /api/v1/platforms/{platform_id}/health-checks` per contracts/deployment-api.md §1/§3/§4 — in `control-plane/tests/contract/test_health_api.py`
- [ ] T077 [P] [US3] Integration test for quickstart Scenario 7: stop catalog container in dev, trigger re-check, platform flips to `degraded`, failed component flagged with detail + `last_check_at`; capability-disabled platform has no semantic-layer resources (US3-AC1) — in `control-plane/tests/integration/test_health_dashboard.py`

### Implementation for User Story 3

- [ ] T078 [US3] Implement platform detail endpoint `GET /api/v1/platforms/{platform_id}`: capabilities_enabled, health results, storage_utilisation, latest_run, recent_failures per contract — in `control-plane/src/datafoundry/controlplane/api/platforms.py`
- [ ] T079 [US3] Implement `GET /api/v1/capabilities` (registry catalog incl. providers list) and `GET /api/v1/providers/{provider}/regions?capability=` (generated matrix from T061) — in `control-plane/src/datafoundry/controlplane/api/capabilities.py`
- [ ] T080 [US3] Implement on-demand health re-check `POST /api/v1/platforms/{platform_id}/health-checks` (202 + check_id) and readiness rule engine: `ready` iff all enabled capabilities' latest results healthy, any unhealthy → `degraded` with component flagged (FR-007, US3-AC3) — in `control-plane/src/datafoundry/controlplane/health/service.py`
- [ ] T081 [US3] Implement storage utilisation collection (bronze/silver/gold byte counts per zone via provider adapters) — in `control-plane/src/datafoundry/controlplane/health/utilisation.py`
- [ ] T082 [US3] Implement enable-capability-later path: config change enabling a previously omitted capability runs an `update` run that adds only the new modules (FR-012, US3-AC1), with dependency-closure validation — extends `engine/orchestrator.py` update path and `config/validation.py`

**Checkpoint**: All three user stories independently functional

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Bootstrap deliverables, parity/performance verification, security hardening, docs

- [ ] T083 [P] Write bootstrap runbook (two-step: apply `terraform/control-plane/` then normal operation) and disaster-recovery runbook (recreate platform from exported config) — in `docs/runbooks/bootstrap.md` and `docs/runbooks/disaster-recovery.md`
- [ ] T084 [P] Control-plane bootstrap Terraform for AWS (ECS Fargate, RDS metadata store, KMS-encrypted, TLS endpoints) — in `terraform/control-plane/aws/`
- [ ] T085 [P] Control-plane bootstrap Terraform for GCP (Cloud Run, Cloud SQL metadata store, CMEK, TLS) — in `terraform/control-plane/gcp/`
- [ ] T086 [P] Capability-parity checklist generator (SC-003): produce checklist from `GET /capabilities` + module contract conformance for AWS-vs-GCP comparison runs — in `scripts/parity_checklist.py`
- [ ] T087 Performance verification: standard platform deploy < 30 min in sandbox accounts (SC-001, FR-016, manual E2E gate Scenario 6), validation response < 2 s, run status polling < 500 ms p95 — record results in `docs/runbooks/performance-baseline.md`
- [ ] T088 [P] Security hardening pass: TLS-only enforcement on all endpoints, `encryption_enforced` non-overridable false in production modules (FR-017), log/response redaction audit against SC-006, gitleaks gate in CI verified
- [ ] T089 Run full quickstart.md validation (Scenarios 1–7) against a clean checkout and fix any gaps
- [ ] T090 [P] Repository documentation: root `README.md` (architecture, quickstart link, monorepo layout) and `control-plane/README.md` / `cli/README.md` developer guides

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundational only
- **US2 (Phase 4)**: Depends on Foundational; T071/T072 extend the US1 orchestrator (T030/T031) — schedule US2 after US1's engine tasks land, or staff sequentially (P1 → P2)
- **US3 (Phase 5)**: Depends on Foundational; T082 extends the US2 update path (T071) — schedule after US2 update flow, otherwise independently testable via health endpoints
- **Polish (Phase 6)**: Depends on all desired stories complete (T087 requires US1; T086 requires US1+US3)

### Key Intra-Phase Dependencies

- T009 (schema) → T028 (validation) → T030 (orchestrator) → T032 (worker) → T035–T037 (API routers) → T065 (E2E pass)
- T011 (registry) → T016 (generator) and → T061 (region matrix) → T028
- T012 (adapters) → T029 (permissions), T061, T081
- T015 (tf wrapper) → T030/T031/T032
- Terraform modules T038–T060 are independent of control-plane code and can proceed fully in parallel with T028–T037 (contract fixed by capability-catalog.md); T065 requires both
- T013 → T014 (migration) → everything persisting state

### Parallel Opportunities

- Phase 1: T002–T008 all [P]
- Phase 2: T010, T011, T012, T015, T017–T023 [P] (T009 → T022; T013 → T014 sequential)
- Phase 3: all four test tasks [P]; all 23 Terraform module tasks T038–T060 [P] (different directories, contract-fixed); CLI tasks T062–T064 parallel with API/engine work
- Phase 4: T066–T068 [P]
- Phase 5: T076–T077 [P]
- Phase 6: T083–T086, T088, T090 [P]
- With multiple teams: Terraform module library (infra team) and control-plane engine/API (service team) proceed concurrently from the Phase 2 checkpoint

---

## Parallel Example: User Story 1

```bash
# Launch all US1 tests together (must fail before implementation):
Task: T024 "Contract tests POST /platforms + POST /validate"
Task: T025 "Contract tests runs/retry/rollback"
Task: T026 "Integration test Scenarios 1+2"
Task: T027 "Integration test Scenario 3"

# Launch all AWS + GCP capability modules together (23 tasks, different dirs):
Task: T039 "terraform/aws/networking"  Task: T050 "terraform/gcp/networking"
Task: T040 "terraform/aws/secrets"     Task: T051 "terraform/gcp/secrets"
# ... (T041–T049, T052–T060)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1 (parallelise Terraform modules vs control-plane code)
4. **STOP and VALIDATE**: quickstart Scenarios 1–3 on LocalStack
5. Deploy/demo: one-click governed lakehouse on AWS + GCP — the headline promise (SC-001)

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. US1 → Scenarios 1–3 green → **MVP shipped**
3. US2 → Scenarios 4–5 green → reproducibility + GitOps + destroy (SC-002)
4. US3 → Scenario 7 green → capability selection + health dashboard data
5. Polish → bootstrap runbooks, parity checklist (SC-003), performance baseline, full quickstart pass

### Parallel Team Strategy

1. Team completes Setup + Foundational together
2. After the Foundational checkpoint:
   - Developer A: US1 engine/API/CLI (T028–T037, T062–T065)
   - Developer B: Terraform module library (T038–T060)
   - Developer C: US2 then US3 (after A's orchestrator lands)
3. Stories integrate at the Scenario checkpoints

---

## Notes

- [P] = different files/directories, no incomplete dependencies
- Commit after each task or logical group; configs flow through Git (GitOps principle)
- Every mutating endpoint must write an AuditRecord (T019) — verify in contract tests
- No plaintext secrets anywhere (SC-006): secret-scan (T010) is on every write/export path
- Adding a provider later = new `terraform/<provider>/` + adapter registration only (FR-015) — do not modify `PlatformConfig` schema or existing modules
- Stop at any checkpoint to validate the story independently
