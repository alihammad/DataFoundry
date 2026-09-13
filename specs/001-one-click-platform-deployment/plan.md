# Implementation Plan: One-Click Platform Deployment

**Branch**: `feature/001-one-click-platform-deployment` | **Date**: 2026-09-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-one-click-platform-deployment/spec.md`

## Summary

Deliver a control plane that deploys a complete governed lakehouse environment on AWS or GCP from one user-initiated operation. A declarative, version-controlled **Platform Configuration** (cloud-independent YAML) is validated, compiled into per-provider **Terraform** module invocations, applied as an ordered **Deployment Run** with per-step status, and followed by storage-zone/catalog initialisation and health checks. Failure handling offers retry-from-failed-step or scoped rollback. The logical capability model (storage, IAM, networking, compute, orchestration, catalog, ingestion, quality, semantic layer, monitoring) maps to cloud-specific Terraform modules isolated under `terraform/aws/` and `terraform/gcp/`, satisfying the constitution's cloud-independence and IaC mandates. The web UI itself is feature 007; this feature exposes the REST API and CLI that the UI will consume.

## Technical Context

**Language/Version**: Python 3.12 (control plane service); Terraform >= 1.9 (HCL) for all infrastructure; Bash for bootstrap/init scripts.

**Primary Dependencies**: FastAPI + Pydantic v2 (API, config schema/validation), SQLAlchemy 2 (ORM), `python-terraform`-style subprocess wrapper around the Terraform CLI (pinned version), PyYAML (configuration), OpenTelemetry SDK (observability), boto3 / google-cloud-storage (state backend + init jobs), Great Expectations *not* in scope here (feature 004).

**Storage**:
- Control-plane metadata (platforms, runs, steps, audit): PostgreSQL 15+ (managed per cloud: RDS / Cloud SQL — itself provisioned by this feature's bootstrap).
- Terraform state: cloud object storage backend with locking (S3 + DynamoDB lock table on AWS; GCS with native locking on GCP), encrypted at rest via KMS.
- Lakehouse data zones: S3 / GCS buckets with Bronze/Silver/Gold prefixes, Iceberg table format (feature 003 consumes; zones created here).

**Testing**: pytest (unit + API contract tests), `terraform validate` + `terraform plan -detailed-exitcode` in CI, LocalStack (AWS) and `gcloud` emulators where feasible for integration tests; end-to-end deploy against sandbox accounts gated manually.

**Target Platform**: Linux server, containerised with Docker; runs in the target cloud (ECS/Cloud Run for the control plane itself after bootstrap). Bootstrap of the control plane's own infrastructure is a documented two-step: `terraform apply` of `terraform/control-plane/` then normal operation.

**Project Type**: Web service (control plane API) + infrastructure-as-code module library + CLI. Single repository, monorepo layout (see Project Structure).

**Performance Goals**: Full standard platform deployment < 30 minutes (SC-001, FR-016); validation response < 2 s; deployment status polling < 500 ms p95.

**Constraints**: Zero plaintext secrets in config, records, or logs (SC-006); encryption at rest from creation on every store (FR-017); one active deployment run per platform; adding a new provider must not change the logical config schema or existing providers (FR-015).

**Scale/Scope**: MVP — 2 providers (AWS, GCP), 4 environment types, ~10 logical capabilities, 2 core user stories + health dashboard data API. Tens of concurrent platforms, not thousands.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Requirement | Plan Compliance | Status |
|---|---|---|---|
| I. Cloud Independence via Portable Core | Logical capabilities map to cloud-specific implementations; no lowest-common-denominator; new provider without touching core | Logical `PlatformConfig` schema is cloud-free; provider adapters + isolated Terraform modules under `terraform/aws/`, `terraform/gcp/`; capability registry pattern allows new providers (FR-015) | ✅ PASS |
| II. Infrastructure as Code (Terraform) | All infra reproducible from code; no console steps | Every resource provisioned via Terraform; state in versioned, locked, encrypted backends; config export/re-apply (FR-006, FR-011, SC-002) | ✅ PASS |
| III. Medallion Architecture | Bronze/Silver/Gold zones | Deployment initialises zone structure + catalog entries before "ready" (FR-005); promotion logic itself is feature 003/004 | ✅ PASS (scope boundary) |
| IV. Shift-Left Testing & Contracts | Tests early; contracts validated | Configuration validated pre-provision with all errors at once (FR-003); API contracts defined in `contracts/`; test plan includes contract tests | ✅ PASS |
| V. AI Agents with Human Oversight | No unrestricted AI production access | No AI components in this feature; Production env requires explicit human approval (FR-010) | ✅ PASS |
| Security & Data Protection | Encryption at rest/in transit, KMS, least privilege, auditability | KMS keys created per platform; encryption mandatory from creation (FR-017); IAM least-privilege modules; every deployment audited (FR-014); secrets via cloud secret managers, never in config | ✅ PASS |
| Development Workflow & Quality Gates | GitOps, observability by default | Platform configs version-controlled and PR-gated (US2); OpenTelemetry instrumentation of control plane; deployment audit history | ✅ PASS |
| Governance | Tech decisions driven by portability/simplicity/cost | Choices recorded in `research.md` with rationale and alternatives | ✅ PASS |

**Gate result**: PASS — no violations, Complexity Tracking not required.

## Project Structure

### Documentation (this feature)

```text
specs/001-one-click-platform-deployment/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── deployment-api.md
│   ├── platform-config-schema.md
│   └── capability-catalog.md
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
control-plane/                  # Python service (API + deployment engine)
├── src/datafoundry/controlplane/
│   ├── api/                    # FastAPI routers: platforms, deployments, health
│   ├── config/                 # PlatformConfig pydantic schema, validation, export/import
│   ├── engine/                 # Deployment run orchestrator: steps, retry, rollback
│   ├── providers/              # Provider adapters: aws.py, gcp.py (registry pattern)
│   ├── capabilities/           # Logical capability definitions -> terraform module refs
│   ├── health/                 # Health check runners per capability
│   ├── db/                     # SQLAlchemy models & migrations (alembic)
│   └── audit/                  # Deployment audit records
├── tests/
│   ├── unit/
│   ├── contract/
│   └── integration/
└── pyproject.toml

cli/                            # datafoundry CLI (deploy, validate, export, status, rollback)
└── src/datafoundry/cli/

terraform/
├── control-plane/              # Bootstrap infra for the control plane itself
│   ├── aws/
│   └── gcp/
├── aws/                        # Provider modules (constitution: isolated per cloud)
│   ├── networking/  storage/  iam/  compute/  orchestration/
│   ├── catalog/  ingestion/  monitoring/  secrets/
├── gcp/
│   └── (mirrors aws/ module set)
└── modules/                    # Cloud-neutral glue: variable schemas, shared init scripts

platform-configs/               # Version-controlled declarative platform configs (GitOps)
└── <platform-name>/<env>.yaml

docker/                         # Dockerfiles for control-plane, cli
docs/runbooks/                  # Bootstrap & disaster-recovery runbooks
```

**Structure Decision**: Monorepo with three delivery units — `control-plane/` (FastAPI service), `cli/`, and `terraform/` (module library, provider-isolated per constitution Principle II). `platform-configs/` is the GitOps source of truth for deployed platforms. The web UI (feature 007) will later add `frontend/` and consume `contracts/deployment-api.md` unchanged.

## Phase 0 Output

See [research.md](./research.md). All Technical Context items resolved; no NEEDS CLARIFICATION remains.

## Phase 1 Output

- [data-model.md](./data-model.md) — Platform, PlatformConfig, DeploymentRun, DeploymentStep, Capability, EnvironmentType, HealthCheckResult, AuditRecord entities with states and validation rules.
- [contracts/deployment-api.md](./contracts/deployment-api.md) — REST API for platforms, deployments, runs, health.
- [contracts/platform-config-schema.md](./contracts/platform-config-schema.md) — cloud-independent declarative configuration schema.
- [contracts/capability-catalog.md](./contracts/capability-catalog.md) — logical capability → per-provider Terraform module mapping contract.
- [quickstart.md](./quickstart.md) — end-to-end validation guide.

## Post-Design Constitution Re-Check

Re-evaluated after Phase 1 design:

- **Principle I**: `capability-catalog.md` fixes the logical capability contract; provider adapters implement it; adding Azure later = new `terraform/azure/` + adapter, no schema change. ✅
- **Principle II**: All modules Terraform; state backends locked + encrypted; `platform-configs/` versioned. ✅
- **Security**: `platform-config-schema.md` forbids secret fields (references only, e.g. `secretRef: platform-credentials`); FR-017 enforced as non-overridable module defaults. ✅
- **Shift-left**: Config validation returns all errors in one response (SC-004); contract tests cover the API. ✅

**Gate result**: PASS. Proceed to `/speckit-tasks`.

## Complexity Tracking

No constitution violations — section intentionally empty.
