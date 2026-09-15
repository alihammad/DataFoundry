# Implementation Plan: Medallion Architecture Processing

**Branch**: `feature/003-medallion-processing` | **Date**: 2026-09-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/003-medallion-processing/spec.md`

## Summary

Deliver the Medallion processing layer on top of the Bronze zone built in feature 002: **Bronze** (raw, immutable, replayable — already landed by feature 002), **Silver** (cleaned, conformed, deduplicated), and **Gold** (business-ready aggregates). Declarative, version-controlled **Transformation** definitions (Bronze→Silver and Silver→Gold) support cleansing, type conversion, standardisation, deduplication, schema enforcement, and aggregation. The **promotion state machine** `INGESTED → INGESTION_VALIDATED → BRONZE → BRONZE_VALIDATED → SILVER → SILVER_VALIDATED → GOLD → GOLD_VALIDATED → CONSUMABLE` is enforced: a dataset transitions only when the relevant quality gate passes (gates supplied by feature 004), and a failed gate blocks promotion automatically. An **override** (authorisation, reason, expiry, identity, timestamp, impact assessment) is the only path past a failed gate. Gold datasets require owner, business definition, quality rules, and business metadata before CONSUMABLE, and Gold builds include **reconciliation** against Silver inputs. Datasets are registered in the catalog with full metadata and end-to-end **lineage** (source → Bronze → Silver → Gold → consumers). Authorised analysts query Silver/Gold directly with SQL (DuckDB, lightweight, no warehouse load) and download results subject to protection policies. Dataset writes are **atomic per version** (Iceberg table format, FR-019) so consumers never see a torn mix.

This feature consumes the Bronze zone + ingestion hand-off states from feature 002 and the gate decisions from feature 004; it reuses the control plane's worker, DB, secret-scan, audit, and gateway abstractions.

## Technical Context

**Language/Version**: Python 3.12 (control plane service); the processing engine is a module *inside* the existing control plane, reusing its worker, DB, and gateway abstractions.

**Primary Dependencies**: FastAPI + Pydantic v2 (API, config/schema validation), SQLAlchemy 2 + Alembic (persistence, same DB as feature 001/002/004), PyArrow (`pyarrow`) for record-level transformation + dedup + schema enforcement, DuckDB (`duckdb`) for SQL-based transformations (Silver→Gold aggregation) and lightweight analyst querying (FR-016, constitution "DuckDB SHALL be evaluated"), PyIceberg (`pyiceberg`) for the Iceberg table format (FR-019, ACID, schema evolution, time travel), existing OpenTelemetry + structured-logging + secret-scan infrastructure reused unchanged. Transformation tooling choice (dbt / SQL / Spark) is a planning-time decision — see R-01.

**Storage**:
- Control-plane metadata (datasets, transformations, promotion states, dataset versions, lineage links, catalog metadata): the same PostgreSQL 15 provisioned by feature 001 (reuses `db/` models + Alembic; new migration).
- Layer data: Bronze/Silver/Gold zone prefixes in the platform bucket (feature 001 provisioned the zones; feature 002 lands Bronze). Silver/Gold written as Iceberg tables (FR-019).
- Analyst querying: DuckDB over Silver/Gold Iceberg tables (lightweight, no warehouse load, FR-016).

**Testing**: pytest (unit + API contract + integration); the existing in-memory SQLite harness (feature 001 conftest pattern) extended with a **SimulatedProcessingGateway** (fake zone inventories + record fixtures + Iceberg-in-memory) so every transformation, promotion, reconciliation, lineage, and query path is exercisable offline — no docker/terraform/database required locally. Live E2E against sandbox data gated manually.

**Target Platform**: Linux server, containerised; same deployment artifact as feature 001/002/004 (ECS Fargate / Cloud Run).

**Project Type**: Web service extension (control plane API + engine) + CLI extension. Single monorepo.

**Performance Goals**: A representative analyst query on a medium Silver/Gold dataset completes in interactive time (seconds) without a warehouse load (SC-004); a Silver transformation over a medium Bronze batch completes in interactive time.

**Constraints**: Bronze immutable in practice (FR-002); promotion only on passing gate (FR-007); override requires full record + applies only to the granted run (FR-008); Gold requires owner/business metadata before CONSUMABLE (FR-009); Gold reconciliation against Silver (FR-010); Gold refuses non-SILVER_VALIDATED inputs (FR-011); atomic per-version writes (FR-012); schema evolution additive tolerated, breaking blocks (FR-013); zero-record output from non-empty input flagged suspicious (FR-020); cloud-independent layer model/transformations/states (FR-018, SC-007).

**Scale/Scope**: MVP — Bronze→Silver and Silver→Gold transformations (cleansing, type conversion, standardisation, dedup, schema enforcement, aggregation), the full promotion state machine, overrides, Gold metadata + reconciliation, catalog registration + lineage, DuckDB analyst querying + download. Streaming into Bronze, warehouse integration, and API consumption of Gold are out of scope (deferred per spec Assumptions). Tens of datasets, not thousands.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Requirement | Plan Compliance | Status |
|---|---|---|---|
| I. Cloud Independence via Portable Core | Logical config portable; new provider without touching core | Layer model, transformation definitions, promotion states, and metadata are cloud-free; layer reads/writes via the existing `CloudGateway` (S3/GCS adapters); identical behaviour on both clouds (FR-018, SC-007) | ✅ PASS |
| II. Infrastructure as Code (Terraform) | All infra reproducible from code | No new infra — Silver/Gold land in zones already provisioned by feature 001 `storage_zones`; Iceberg tables written into existing zone prefixes | ✅ PASS |
| III. Medallion Architecture with Quality-Gated Promotion | Bronze/Silver/Gold; INGESTED→…→CONSUMABLE; gates at every transition; override requires full record | Full state machine enforced (FR-007); transitions only on passing gate (gates from feature 004); override requires authorisation/reason/expiry/identity/timestamp/impact (FR-008); Bronze immutable (FR-002) | ✅ PASS |
| IV. Shift-Left Testing & Data Contracts | Tests before/during ingestion; contracts validated; breaking blocks | Consumes feature 004 gates/contracts; this feature enforces promotion only on passing gates (FR-007); schema evolution additive tolerated, breaking blocks (FR-013) | ✅ PASS |
| V. AI Agents with Human Oversight | No unrestricted AI production access; deterministic validation before execution | No AI components in this feature; transformations are deterministic declarative definitions; no auto-approval of any promotion | ✅ PASS |
| Security & Data Protection | Encryption at rest/in transit; secrets never plaintext; KMS; column-level protection; auditability | No new secrets; layer data inherits zone encryption; column-level protection policies enforced on query/download (FR-016, US5-AC3); all promotion/override/lineage operations audited; secret-scan on every write (reuses feature 001) | ✅ PASS |
| Development Workflow & Quality Gates | GitOps; observability by default; self-service reuse | Transformation definitions version-controlled (reuses `config/gitops.py` pattern, FR-005); per-run metrics via OpenTelemetry; processing engine built once, data teams consume | ✅ PASS |
| Governance | Tech decisions driven by portability/simplicity/cost, not popularity | Transformation tooling + Iceberg/DuckDB evaluation recorded in research.md (R-01, R-02) with explicit rationale; in-house engine justified on simplicity/portability/cost | ✅ PASS |

**Gate result**: PASS — no violations, Complexity Tracking not required.

## Project Structure

### Documentation (this feature)

```text
specs/003-medallion-processing/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── processing-api.md
│   ├── transformation-schema.md
│   └── dataset-schema.md
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
control-plane/src/datafoundry/controlplane/
├── api/                     # NEW routers: datasets, transformations, promotion,
│   │                        #   lineage, query
│   ├── datasets.py
│   ├── transformations.py
│   ├── promotion.py
│   ├── lineage.py
│   └── query.py
├── processing/              # NEW package: the processing engine
│   ├── transformations/     #   transformation definitions + execution
│   │   ├── base.py          #     Transformation ABC (apply, version)
│   │   ├── registry.py      #     registry of transformation types
│   │   ├── silver.py        #     Bronze→Silver: cleanse/type-convert/dedup/schema
│   │   └── gold.py          #     Silver→Gold: aggregate/reconcile
│   ├── promotion.py         #   promotion state machine + gate enforcement + override
│   ├── lineage.py           #   lineage links (source→Bronze→Silver→Gold→consumers)
│   ├── catalog.py           #   catalog registration + metadata (owner, quality, refresh)
│   ├── query.py             #   DuckDB analyst querying + download + column protection
│   ├── engine.py            #   run a transformation: transform -> gate -> promote
│   └── gateway.py           #   SimulatedProcessingGateway + live zone adapters
├── db/
│   ├── models.py            #   + Dataset, Transformation, DatasetVersion, LineageLink,
│   │                        #     PromotionState, CatalogMetadata
│   └── migrations/          #   + new Alembic migration
├── audit/service.py          #   + processing audit actions (reused)
├── config/                   #   + transformation schema (new module)
│   └── transformation_schema.py
└── health/runners.py         #   + processing health (optional)

cli/src/datafoundry/cli/commands/
├── dataset.py                # datafoundry dataset register/list/status
├── transform.py              # datafoundry transform define/run/history
├── promote.py                # datafoundry promote status/override
└── query.py                  # datafoundry query run/download

control-plane/tests/
├── unit/                    # transformation types, promotion state machine, dedup,
│                            #   reconciliation, lineage, query
├── contract/                # processing-api, transformation-schema, dataset-schema
└── integration/             # bronze->silver->gold flows, promotion/override, lineage, query

terraform/aws/storage/       # + Iceberg table format config (TBD in tasks)
terraform/gcp/storage/
```

**Structure Decision**: Extend the existing control plane rather than create a separate service — the processing engine shares the worker, DB, secret-scan, audit, and gateway abstractions already built in feature 001/002/004, avoiding a second runtime and its operational burden (portability + simplicity). Transformation types follow the same registry pattern as the capability registry and feature 002's connector registry (Principle I, FR-015 spirit). Layer reads/writes go through `CloudGateway` so S3/GCS parity is structural, not per-transformation. The web UI (feature 007) consumes `contracts/processing-api.md` unchanged.

## Phase 0 Output

See [research.md](./research.md) — all Technical Context unknowns resolved.

## Phase 1 Output

See [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md).
