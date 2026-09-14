# Implementation Plan: Self-Service Data Ingestion

**Branch**: `feature/002-data-ingestion` | **Date**: 2026-09-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/002-data-ingestion/spec.md`

## Summary

Deliver a standardised, self-service ingestion framework that lands data from enterprise sources (PostgreSQL, SQL Server, CSV/JSON/Parquet files, S3/GCS object storage) into the Bronze zone, configured through a guided wizard with no custom code. A declarative, version-controlled **Ingestion Configuration** (cloud-independent YAML, mirroring the Platform Config of feature 001) defines source, selected tables/files, ingestion mode (full/incremental), cursor column, schedule, and target zone. The control plane runs a **connector framework** (thin, in-process, registry-driven) that discovers schema, tests connectivity, executes scheduled/manual/retry runs into source-aligned, ingestion-date-partitioned Bronze layout, records per-batch metadata, runs ingestion-level validation (schema/contract compatibility + record-count reconciliation), and routes invalid files/records to a **quarantine zone** rather than propagating them. Batches follow the promotion hand-off states `INGESTED → INGESTION_VALIDATED`; the Bronze/Silver/Gold promotion logic beyond validation is feature 003/004.

This feature consumes the `ingestion`, `storage_zones`, `catalog`, `orchestration`, and `secrets` capabilities provisioned by feature 001, and exposes the REST API + CLI that the web UI (feature 007) will render as the "Add Data Source" wizard.

## Technical Context

**Language/Version**: Python 3.12 (control plane service); the ingestion engine is a module *inside* the existing control plane, reusing its worker, DB, and gateway abstractions.

**Primary Dependencies**: FastAPI + Pydantic v2 (API, config/schema validation), SQLAlchemy 2 + Alembic (persistence, same DB as feature 001), SQLAlchemy dialects (`psycopg`, `pymssql`/`pyodbc`) for database-source connectivity & schema discovery, PyArrow (`pyarrow`) for Parquet/CSV/JSON file parsing and record-counting, boto3 / google-cloud-storage for object-storage sources (reused), in-process scheduler (control-plane-owned, see R-04). Existing OpenTelemetry + structured-logging + secret-scan infrastructure reused unchanged.

**Storage**:
- Control-plane metadata (sources, configs, contracts, pipelines, batches, runs, quarantine): the same PostgreSQL 15 provisioned by feature 001 (reuses `db/` models + Alembic; new migration).
- Ingested data: the platform's Bronze zone prefix in S3/GCS (provisioned by feature 001 `storage_zones` capability), source-aligned layout partitioned by `ingestion_date` (FR-018).
- Quarantine zone: a `quarantine/` prefix in the same platform bucket (feature 001 created Bronze/Silver/Gold; this feature adds the quarantine path).

**Testing**: pytest (unit + API contract + integration); the existing in-memory SQLite harness (feature 001 conftest pattern) extended with a **SimulatedSourceGateway** (fake PostgreSQL/SQL Server/object-storage inventories) so every connector, incremental/dedup, validation, reconciliation, and quarantine path is exercisable offline — no docker/terraform/database required locally. Live E2E against sandbox sources gated manually.

**Target Platform**: Linux server, containerised; same deployment artifact as feature 001 (ECS Fargate / Cloud Run). Source systems reachable via private connectivity (operational prerequisite per spec Assumptions).

**Project Type**: Web service extension (control plane API + engine) + CLI extension. Single monorepo.

**Performance Goals**: Connection test + schema discovery < 1 minute for typical schemas (FR-004, US1-AC1); common source onboarded end-to-end < 30 minutes (SC-001, FR-019); incremental runs produce zero duplicates across ≥1M-record test dataset (SC-005).

**Constraints**: Zero plaintext source credentials in config, exports, logs, or UI (FR-005, SC-007 — reuses feature 001 secret-scan + `secretRef` model); encrypted channels for all data transfer (FR-016); one active run per pipeline (serialisation, FR-012); declarative, version-controlled, cloud-portable config (FR-017, SC-008); no torn Bronze batches (FR-015).

**Scale/Scope**: MVP — 2 database sources (PostgreSQL, SQL Server), 3 file formats (CSV, JSON, Parquet), 2 object stores (S3, GCS), full + incremental modes, scheduled + manual + retry runs. CDC, SaaS, streaming, Oracle/MySQL, XML/Excel are out of scope (deferred per spec Assumptions). Tens of pipelines, not thousands.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Requirement | Plan Compliance | Status |
|---|---|---|---|
| I. Cloud Independence via Portable Core | Logical config portable; new provider without touching core | Ingestion config schema is cloud-free; connectors are provider-agnostic (DB/file); object-storage sources abstracted behind the existing `CloudGateway` (S3/GCS adapters); adding a source type = new connector in a registry, no core change | ✅ PASS |
| II. Infrastructure as Code (Terraform) | All infra reproducible from code | Ingested data/quarantine land in zones/buckets already provisioned by feature 001 Terraform modules; this feature adds no new infra — the `quarantine/` prefix is created by the existing `storage_zones` contract (extended) | ✅ PASS |
| III. Medallion Architecture with Quality-Gated Promotion | Bronze/Silver/Gold; INGESTED → INGESTION_VALIDATED | Batches follow INGESTED → INGESTION_VALIDATED; failing critical validation blocks promotion (hand-off to feature 004 gates); quarantine rather than propagate | ✅ PASS |
| IV. Shift-Left Testing & Data Contracts | Contracts validated during ingestion; breaking/non-breaking/warning | Source contracts inferred/explicit, validated at ingestion; violations classified breaking/non-breaking/warning; breaking blocks promotion (FR-009, FR-010); test-first default | ✅ PASS |
| V. AI Agents with Human Oversight | No unrestricted AI production access; deterministic validation before execution | No AI components in this feature; contract inference is deterministic (observed schema → pending owner approval), never auto-approved | ✅ PASS |
| Security & Data Protection | Encryption at rest/in transit; secrets never plaintext; KMS | Source credentials stored as `secretRef` in the platform's secret manager (feature 001 `secrets` capability); encrypted channels; secret-scan on every export/log/audit write (reuses feature 001) | ✅ PASS |
| Development Workflow & Quality Gates | GitOps; observability by default; self-service reuse | Ingestion configs version-controlled (reuses `config/gitops.py` pattern); per-run metrics via OpenTelemetry; connector framework built once, data teams consume | ✅ PASS |
| Governance | Tech decisions driven by portability/simplicity/cost, not popularity | Airbyte evaluation recorded in research.md (R-01) with explicit deferral rationale; connector framework justified on simplicity/portability/cost | ✅ PASS |

**Gate result**: PASS — no violations, Complexity Tracking not required.

## Project Structure

### Documentation (this feature)

```text
specs/002-data-ingestion/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── ingestion-api.md
│   ├── source-config-schema.md
│   └── source-contract-schema.md
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
control-plane/src/datafoundry/controlplane/
├── api/                     # NEW routers: sources, ingestion_configs,
│   │                        #   pipelines, runs, contracts, batches
│   ├── sources.py
│   ├── ingestion_configs.py
│   ├── pipelines.py
│   ├── ingestion_runs.py
│   └── contracts.py
├── ingestion/               # NEW package: the ingestion engine
│   ├── connectors/          #   connector registry + per-source connectors
│   │   ├── base.py          #     Connector ABC (discover, test, extract)
│   │   ├── registry.py      #     source-type -> connector mapping
│   │   ├── postgres.py      #     PostgreSQL (schema discovery, full/incremental)
│   │   ├── sqlserver.py     #     SQL Server
│   │   └── object_storage.py#     CSV/JSON/Parquet from S3/GCS (via CloudGateway)
│   ├── engine.py            #   batch execution: extract -> validate -> land/quarantine
│   ├── validation.py        #   file validation + contract compatibility + reconciliation
│   ├── contract.py          #   contract inference + change classification
│   ├── scheduler.py         #   due-pipeline scheduler (in-process)
│   └── gateway.py           #   SimulatedSourceGateway + live source adapters
├── db/
│   ├── models.py            #   + DataSource, IngestionConfig, SourceContract,
│   │                        #     IngestionPipeline, IngestionBatch, IngestionRun,
│   │                        #     QuarantineRecord
│   └── migrations/          #   + new Alembic migration
├── audit/service.py         #   + ingestion audit actions (reused)
├── config/                  #   + ingestion-config schema (new module)
│   └── ingestion_schema.py
└── health/runners.py        #   + ingestion run/pipeline health (optional)

cli/src/datafoundry/cli/commands/
├── source.py                # datafoundry source add/test/list
├── ingest.py                # datafoundry ingest run/history
└── pipeline.py              # datafoundry pipeline pause/resume/retry

control-plane/tests/
├── unit/                    # connectors, contract classification, validation, dedup
├── contract/                # ingestion-api, source-config-schema, contract-schema
└── integration/             # wizard -> run -> validate -> quarantine flows (simulated)

terraform/aws/storage/       # + quarantine/ prefix in zone contract (TBD in tasks)
terraform/gcp/storage/
```

**Structure Decision**: Extend the existing control plane rather than create a separate service — the ingestion engine shares the worker, DB, secret-scan, audit, and gateway abstractions already built in feature 001, avoiding a second runtime and its operational burden (portability + simplicity). Connectors follow the same registry pattern as the capability registry (Principle I, FR-015 spirit). Object-storage sources go through `CloudGateway` so S3/GCS parity is structural, not per-connector. The web UI (feature 007) consumes `contracts/ingestion-api.md` unchanged.

## Phase 0 Output

See [research.md](./research.md). All Technical Context items resolved; no NEEDS CLARIFICATION remains.

## Phase 1 Output

- [data-model.md](./data-model.md) — DataSource, IngestionConfig, SourceContract, IngestionPipeline, IngestionBatch, IngestionRun, QuarantineRecord entities with states and validation rules.
- [contracts/ingestion-api.md](./contracts/ingestion-api.md) — REST API for sources, ingestion configs, pipelines, runs, contracts, batches.
- [contracts/source-config-schema.md](./contracts/source-config-schema.md) — cloud-independent declarative ingestion configuration schema.
- [contracts/source-contract-schema.md](./contracts/source-contract-schema.md) — source data contract schema + change classification rules.
- [quickstart.md](./quickstart.md) — end-to-end validation guide.
