# Implementation Plan: Semantic Layer

**Branch**: `feature/006-semantic-layer` | **Date**: 2026-09-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/006-semantic-layer/spec.md`

## Summary

Deliver the platform's **semantic layer**: a business abstraction between physical Gold/Silver datasets and consumers (BI, analyst SQL, AI/ML pipelines, applications). Analytics engineers define **metrics** ("Revenue = sum of order amount where status is COMPLETED"), **dimensions**, **measures**, and **relationships** once, bound to Gold (or Silver) datasets, with plain-language definitions and owners. Every consumer requesting "Revenue" receives the same value computed by the same definition — no downstream team re-implements business logic (FR-001, FR-002).

Definitions are **declarative, version controlled**, and change through the GitOps workflow (propose → validate → approve → publish, FR-003). Publication requires passing **semantic tests** (calculation correctness on reference data, relationship validity, aggregation reconciliation, filter behaviour, FR-004). Changes are classified breaking/non-breaking; breaking changes require explicit approval and notify registered consumers (FR-005). Access enforcement reuses feature 005's policies: role-based metric visibility, column protection preserved, row-level restrictions applied (FR-007). Results report underlying data freshness/quality; data known to have failed its quality gate is blocked or flagged (FR-008). Definitions are searchable in the catalog with certified vs draft distinction (FR-011), and the definition version is recorded with every result for reproducibility (FR-012).

This feature consumes Gold/Silver datasets produced by feature 003 and gated by feature 004; it enforces (not defines) access policies owned by feature 005; it supplies semantic metadata for catalog display (feature 003 metadata + feature 007 UI). It reuses the control plane's worker, DB, audit, secret-scan, gateway, and GitOps abstractions.

## Technical Context

**Language/Version**: Python 3.12 (control plane service); the semantic engine is a module *inside* the existing control plane, reusing its worker, DB, gateway, and audit abstractions.

**Primary Dependencies**: FastAPI + Pydantic v2 (API, config/schema validation), SQLAlchemy 2 + Alembic (persistence, same DB as features 001–005), DuckDB (`duckdb`) for metric computation and analyst querying over Gold/Silver datasets (constitution-mandated lightweight query engine), PyArrow (`pyarrow`) for reading zone tables via the existing `CloudGateway`, existing OpenTelemetry + structured-logging + secret-scan infrastructure reused unchanged. Semantic-layer technology choice (Cube / dbt Semantic Layer / custom) is a planning-time decision — see R-01.

**Storage**:
- Control-plane metadata (semantic models, metrics, dimensions, measures, relationships, semantic tests, consumer registrations, publications, query-result version records): the same PostgreSQL 15 provisioned by feature 001 (reuses `db/` models + Alembic; new migration).
- Metric computation reads: Gold/Silver zone prefixes via the existing `CloudGateway` (S3/GCS). The semantic layer defines no storage of its own business data (spec Assumptions).

**Testing**: pytest (unit + API contract + integration); the existing in-memory SQLite harness (feature 001 conftest pattern) extended with a **SimulatedSemanticGateway** (fake zone inventories + reference-data fixtures) so every metric-definition, semantic-test, publication, access, and discovery path is exercisable offline — no docker/terraform/database required locally. Live E2E against sandbox data gated manually.

**Target Platform**: Linux server, containerised; same deployment artifact as features 001–005 (ECS Fargate / Cloud Run). Deployable as a platform capability selected at deployment time (feature 001, FR-012).

**Project Type**: Web service extension (control plane API + engine) + CLI extension. Single monorepo.

**Performance Goals**: Metric computation on a medium dataset completes in interactive time (seconds) for the standard consumption paths (SC-001); a semantic query returns within the platform's query SLA (SC-004).

**Constraints**: Definitions version-controlled through GitOps (FR-003); breaking changes require approval + consumer notification (FR-005); access policies enforced, never bypassed (FR-007, SC-005); stale/failed-quality data surfaced or refused, never silently served as current (FR-008); business-term names unique per domain (FR-009); cloud-independent behaviour (FR-013, SC-008); definition version recorded with every result (FR-012, SC-006).

**Scale/Scope**: MVP — declarative metrics/dimensions/measures/relationships, GitOps publication with semantic tests, access enforcement, catalog discovery, consumer registration + notification, deprecation. BI-tool connectors (Looker/Power BI) and natural-language querying are out of scope (spec Assumptions). Tens of datasets, not thousands.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Requirement | Plan Compliance | Status |
|---|---|---|---|
| I. Cloud Independence via Portable Core | Logical config portable; new provider without touching core | Metric/dimension/measure/relationship definitions are cloud-free; computation reads zones via the existing `CloudGateway` (S3/GCS adapters); identical results on both clouds (FR-013, SC-008) | ✅ PASS |
| II. Infrastructure as Code (Terraform) | All infra reproducible from code | No new infra — the semantic layer reads existing Gold/Silver zones and stores metadata in the existing control-plane DB; deployable as a feature-001 capability | ✅ PASS |
| III. Medallion Architecture with Quality-Gated Promotion | Consume only quality-gated data; never silently serve stale/failed data | Semantic queries surface freshness/quality state; data known to have failed its quality gate is blocked or flagged (FR-008); consumes only Gold/Silver produced under feature 003/004 | ✅ PASS |
| IV. Shift-Left Testing & Data Contracts | Tests before/during; contracts validated; breaking blocks | Semantic tests run at publish time AND on schedule against production data (FR-014); breaking definition changes require approval + notification (FR-005) | ✅ PASS |
| V. AI Agents with Human Oversight | No unrestricted AI production access; deterministic validation before execution | No AI components in this feature; semantic validation is deterministic (reference data → pass/fail); AI/ML consumers get feature datasets under the same access policies as humans (FR-015) | ✅ PASS |
| Security & Data Protection | Encryption at rest/in transit; secrets never plaintext; KMS; auditability | No new secrets; access policies enforced from feature 005 (FR-007, SC-005); protected columns never leak through semantic queries; all publication/access operations audited | ✅ PASS |
| Development Workflow & Quality Gates | GitOps; observability by default; self-service reuse | Semantic definitions version-controlled (reuses `config/gitops.py` pattern, FR-003); per-query version + freshness/quality metadata via OpenTelemetry; semantic engine built once, data teams consume | ✅ PASS |
| Governance | Tech decisions driven by portability/simplicity/cost, not popularity | Semantic-layer technology evaluation recorded in research.md (R-01) with explicit deferral rationale; in-house engine justified on simplicity/portability/cost | ✅ PASS |

**Gate result**: PASS — no violations, Complexity Tracking not required.

## Project Structure

### Documentation (this feature)

```text
specs/006-semantic-layer/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── semantic-api.md
│   ├── semantic-model-schema.md
│   └── semantic-test-schema.md
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
control-plane/src/datafoundry/controlplane/
├── api/                     # NEW routers: semantic, metrics, publications,
│   │                        #   semantic-tests, consumers, discovery
│   ├── semantic.py
│   ├── metrics.py
│   ├── publications.py
│   ├── semantic_tests.py
│   ├── consumers.py
│   └── discovery.py
├── semantic/                # NEW package: the semantic engine
│   ├── model/               #   semantic model composition + validation
│   │   ├── model.py         #     SemanticModel, Metric, Dimension, Measure, Relationship
│   │   └── registry.py      #     domain -> model binding
│   ├── compute/             #   metric computation over Gold/Silver
│   │   ├── engine.py        #     DuckDB metric evaluation
│   │   └── gateway.py       #     SimulatedSemanticGateway + live zone adapters
│   ├── tests/               #   semantic test categories
│   │   ├── base.py          #     SemanticTest ABC
│   │   ├── categories.py    #     calculation/reconciliation/relationship/filter
│   │   └── registry.py      #     category -> test implementation
│   ├── lifecycle.py         #   propose -> validate -> approve -> publish (GitOps)
│   ├── access.py            #   access-policy enforcement (feature 005 reuse)
│   ├── discovery.py         #   catalog search + certified/draft distinction
│   ├── consumers.py         #   consumer registration + notification
│   ├── deprecation.py       #   deprecation + successor + time-bounded availability
│   └── engine.py            #   run a semantic query: resolve version -> compute -> record
├── db/
│   ├── models.py            #   + SemanticModel, Metric, Dimension, Measure, Relationship,
│   │                        #     SemanticTest, SemanticTestResult, Publication,
│   │                        #     ConsumerRegistration, QueryResultVersion
│   └── migrations/          #   + new Alembic migration
├── audit/service.py         #   + semantic audit actions (reused)
├── config/                  #   + semantic-model schema (new module)
│   └── semantic_schema.py
└── health/runners.py        #   + semantic health (optional)

cli/src/datafoundry/cli/commands/
├── semantic.py              # datafoundry semantic model/validate/publish
├── metric.py                # datafoundry metric query/describe
└── consumer.py              # datafoundry consumer register/list

control-plane/tests/
├── unit/                    # metric computation, semantic tests, lifecycle, access,
│                            #   discovery, deprecation
├── contract/                # semantic-api, semantic-model-schema, semantic-test-schema
└── integration/             # quickstart scenarios
```

**Structure Decision**: Single monorepo, mirroring features 001–005. The semantic engine is a new `semantic/` package inside the existing control plane, reusing its DB, worker, gateway, audit, secret-scan, and GitOps abstractions. New API routers under `api/`, new CLI commands under `cli/src/datafoundry/cli/commands/`, new models in `db/models.py` + a new Alembic migration.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations — Complexity Tracking not required.
