# Implementation Plan: Shift-Left Data Quality Gates

**Branch**: `feature/004-data-quality-gates` | **Date**: 2026-09-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/004-data-quality-gates/spec.md`

## Summary

Deliver the platform's quality control system: a **quality gate** at every Medallion layer transition (ingestion→Bronze, Bronze→Silver, Silver→Gold, Gold→consumable) composed of configurable **tests** from the standard categories (schema, type, nullability, uniqueness, completeness, validity, referential integrity, reconciliation, freshness, volume, distribution, business rule, security, contract, transformation, statistical). Gates **fail closed**: a CRITICAL/ERROR test that fails — or cannot execute — blocks promotion. Tests carry severity (CRITICAL/ERROR/WARNING/INFORMATIONAL) configurable per dataset and per environment. **Data contracts** are validated at ingestion with violations classified breaking / non-breaking / warning; where no explicit contract exists the platform infers one from observed schema, marked pending approval. Failed records/files route to a **quarantine** area retaining full failure context, with replay after root-cause resolution and retention expiry. A **controlled manual override** (authorisation, reason, expiry, identity, timestamp, impact assessment) is the only path past a failed gate, applies only to the specific blocked run, and is permanently audited. Every test execution is recorded as observable metadata feeding per-dataset **quality scores** and history, with drill-down to failing records and quarantine entries.

This feature supplies the gate decisions that drive the promotion state machine owned by feature 003 (medallion-processing); it consumes the ingestion hand-off states (`INGESTED → INGESTION_VALIDATED`) and quarantine routing built in feature 002, and reuses the control plane's worker, DB, secret-scan, audit, and gateway abstractions.

## Technical Context

**Language/Version**: Python 3.12 (control plane service); the quality engine is a module *inside* the existing control plane, reusing its worker, DB, and gateway abstractions.

**Primary Dependencies**: FastAPI + Pydantic v2 (API, config/schema validation), SQLAlchemy 2 + Alembic (persistence, same DB as feature 001/002), PyArrow (`pyarrow`) for record-level test evaluation over Parquet/CSV/JSON, DuckDB (`duckdb`) for SQL-based tests (reconciliation, distribution, business rule) over Silver/Gold datasets, existing OpenTelemetry + structured-logging + secret-scan infrastructure reused unchanged. Quality framework choice (Great Expectations / Soda / dbt / custom) is a planning-time decision — see R-01.

**Storage**:
- Control-plane metadata (gates, tests, test results, gate reports, contracts, contract violations, quarantine entries, overrides, quality scores): the same PostgreSQL 15 provisioned by feature 001 (reuses `db/` models + Alembic; new migration).
- Quarantine payloads: the `quarantine/` prefix in the platform bucket (feature 002 added the path; this feature adds replay + retention).
- Test evaluation reads: Bronze/Silver/Gold zone prefixes via the existing `CloudGateway` (S3/GCS).

**Testing**: pytest (unit + API contract + integration); the existing in-memory SQLite harness (feature 001 conftest pattern) extended with a **SimulatedQualityGateway** (fake zone inventories + record fixtures) so every gate, contract-classification, quarantine, override, and observability path is exercisable offline — no docker/terraform/database required locally. Live E2E against sandbox data gated manually.

**Target Platform**: Linux server, containerised; same deployment artifact as feature 001/002 (ECS Fargate / Cloud Run).

**Project Type**: Web service extension (control plane API + engine) + CLI extension. Single monorepo.

**Performance Goals**: Gate evaluation on a medium dataset completes in interactive time (seconds) for the standard test categories (SC-004); a blocked promotion raises an alert within 5 minutes of the gate decision (SC-004).

**Constraints**: Gates fail closed (FR-002); overrides require full authorisation record and apply only to the granted run (FR-011, FR-012); quarantine replay must not duplicate processed records (FR-009); test/gate/contract definitions version-controlled through GitOps (FR-018); cloud-independent gate outcomes (FR-019, SC-008); no silent bypass of a failed test (FR-011).

**Scale/Scope**: MVP — the 17 standard test categories, 4 severity levels, per-dataset/per-environment configuration, explicit + inferred contracts, quarantine with replay + retention, overrides, quality scores + history. Statistical/AI anomaly detection and AI-assisted test generation are out of scope (deferred per spec Assumptions). Tens of datasets, not thousands.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Requirement | Plan Compliance | Status |
|---|---|---|---|
| I. Cloud Independence via Portable Core | Logical config portable; new provider without touching core | Gate/test/contract definitions are cloud-free; test evaluation reads zones via the existing `CloudGateway` (S3/GCS adapters); identical gate outcomes on both clouds (FR-019, SC-008) | ✅ PASS |
| II. Infrastructure as Code (Terraform) | All infra reproducible from code | No new infra — quarantine payloads land in the `quarantine/` prefix already provisioned by feature 002's storage contract; test evaluation reads existing zones | ✅ PASS |
| III. Medallion Architecture with Quality-Gated Promotion | Gates at every layer transition; quarantine rather than propagate; override requires full record | Gates at ingestion→Bronze, Bronze→Silver, Silver→Gold, Gold→consumable (FR-001); failed records quarantined never silently dropped (FR-006); override requires authorisation/reason/expiry/identity/timestamp/impact (FR-011) | ✅ PASS |
| IV. Shift-Left Testing & Data Contracts | Tests before/during ingestion; contracts validated; breaking blocks; severity configurable; test-first | Contracts validated at ingestion, violations classified breaking/non-breaking/warning (FR-006); inferred contracts pending approval (FR-007); severity CRITICAL/ERROR/WARNING/INFORMATIONAL per dataset/environment (FR-004, FR-005); test-first supported (FR-020) | ✅ PASS |
| V. AI Agents with Human Oversight | No unrestricted AI production access; deterministic validation before execution | No AI components in this feature; contract inference is deterministic (observed schema → pending owner approval), never auto-approved (FR-007) | ✅ PASS |
| Security & Data Protection | Encryption at rest/in transit; secrets never plaintext; KMS; auditability | No new secrets; quarantine payloads inherit zone encryption; all override/contract/gate operations audited (FR-011, FR-012); secret-scan on every write (reuses feature 001) | ✅ PASS |
| Development Workflow & Quality Gates | GitOps; observability by default; self-service reuse | Test/gate/contract definitions version-controlled (reuses `config/gitops.py` pattern, FR-018); per-run test metrics via OpenTelemetry; quality engine built once, data teams consume | ✅ PASS |
| Governance | Tech decisions driven by portability/simplicity/cost, not popularity | Quality framework evaluation recorded in research.md (R-01) with explicit deferral rationale; in-house engine justified on simplicity/portability/cost | ✅ PASS |

**Gate result**: PASS — no violations, Complexity Tracking not required.

## Project Structure

### Documentation (this feature)

```text
specs/004-data-quality-gates/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── quality-api.md
│   ├── gate-config-schema.md
│   └── contract-schema.md
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
control-plane/src/datafoundry/controlplane/
├── api/                     # NEW routers: gates, tests, contracts, quarantine,
│   │                        #   overrides, quality
│   ├── gates.py
│   ├── tests.py
│   ├── contracts.py
│   ├── quarantine.py
│   ├── overrides.py
│   └── quality.py
├── quality/                 # NEW package: the quality engine
│   ├── gates/               #   gate composition + decision logic
│   │   ├── gate.py          #     Gate model, decision (PROMOTE/BLOCK), fail-closed
│   │   └── registry.py      #     transition -> gate binding
│   ├── tests/               #   test categories + severity
│   │   ├── base.py          #     Test ABC (evaluate, severity, env override)
│   │   ├── categories.py    #     schema/type/nullability/uniqueness/completeness/
│   │   │                    #       validity/referential/reconciliation/freshness/
│   │   │                    #       volume/distribution/business/security/contract/
│   │   │                    #       transformation/statistical
│   │   └── registry.py      #     category -> test implementation
│   ├── contracts/           #   contract validation + inference + classification
│   │   ├── validate.py      #     breaking/non-breaking/warning classification
│   │   └── infer.py         #     inferred contract (pending approval)
│   ├── quarantine.py        #   quarantine write/read + replay + retention
│   ├── override.py          #   override validation + expiry + audit
│   ├── score.py             #   quality score + history computation
│   ├── engine.py            #   run a gate: evaluate tests -> report -> decision
│   └── gateway.py           #   SimulatedQualityGateway + live zone adapters
├── db/
│   ├── models.py            #   + QualityGate, QualityTest, TestResult, GateReport,
│   │                        #     DataContract, ContractViolation, QuarantineEntry,
│   │                        #     GateOverride, QualityScore
│   └── migrations/          #   + new Alembic migration
├── audit/service.py         #   + quality audit actions (reused)
├── config/                  #   + gate-config schema (new module)
│   └── quality_schema.py
└── health/runners.py        #   + quality gate health (optional)

cli/src/datafoundry/cli/commands/
├── gate.py                  # datafoundry gate list/run/report
├── contract.py              # datafoundry contract register/infer/approve
├── quarantine.py            # datafoundry quarantine list/replay
└── override.py              # datafoundry override grant/expire

control-plane/tests/
├── unit/                    # test categories, gate decision, contract classification,
│                            #   quarantine replay, override, score
├── contract/                # quality-api, gate-config-schema, contract-schema
└── integration/             # gate -> block/override -> promote, quarantine -> replay flows

terraform/aws/storage/       # + quarantine retention policy (TBD in tasks)
terraform/gcp/storage/
```

**Structure Decision**: Extend the existing control plane rather than create a separate service — the quality engine shares the worker, DB, secret-scan, audit, and gateway abstractions already built in feature 001/002, avoiding a second runtime and its operational burden (portability + simplicity). Test categories follow the same registry pattern as the capability registry and feature 002's connector registry (Principle I, FR-015 spirit). Test evaluation reads zones through `CloudGateway` so S3/GCS parity is structural, not per-test. The web UI (feature 007) consumes `contracts/quality-api.md` unchanged.

## Phase 0 Output

See [research.md](./research.md) — all Technical Context unknowns resolved.

## Phase 1 Output

See [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md).
