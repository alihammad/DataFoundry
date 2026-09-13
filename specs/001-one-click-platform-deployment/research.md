# Phase 0 Research: One-Click Platform Deployment

**Feature**: 001-one-click-platform-deployment | **Date**: 2026-09-13

All Technical Context unknowns resolved. Format: Decision / Rationale / Alternatives considered.

---

## R-01: Deployment execution model — how Terraform is driven

**Decision**: The control plane invokes the **Terraform CLI as a subprocess** (`terraform init/plan/apply/destroy` with `-json` machine-readable output), one workspace/state per platform, executed by an async deployment worker inside the control plane. Step boundaries are derived from a generated root module per platform that composes capability modules in a fixed dependency order.

**Rationale**:
- Constitution mandates Terraform as the authoritative IaC mechanism; the CLI is the only fully supported execution surface for both AWS and GCP providers.
- `-json` output gives per-resource progress, enabling FR-008 (ordered steps with per-step status) without a second orchestration system.
- A generated root module per platform keeps capability selection (FR-012) trivial: enabled capabilities = included module blocks.
- Avoids long-lived stateful infrastructure for the engine itself; the deployment run is a supervised subprocess with checkpoints in PostgreSQL.

**Alternatives considered**:
- *terraform-exec / python-terraform libraries*: thin wrappers over the same CLI; add dependency risk without capability gain. Use a minimal in-house wrapper instead.
- *Atlantis / TFC (Terraform Cloud)*: external SaaS or extra self-hosted service; conflicts with cloud-independence and self-contained one-click promise; TFC licensing cost.
- *Crossplane / Pulumi*: violate constitution Principle II (Terraform SHALL be primary IaC).
- *CDKTF*: still Terraform but adds a compile step; HCL modules are simpler to review in PRs (GitOps principle).

## R-02: Capability → module mapping (cloud independence)

**Decision**: A **capability registry** maps each logical capability (networking, storage-zones, iam, compute, orchestration, catalog, ingestion, quality, semantic-layer, monitoring, secrets) to a provider-specific Terraform module path (`terraform/<provider>/<capability>/`) with a **common variable/output contract** per capability. The contract is documented in `contracts/capability-catalog.md`. Provider adapters (`control-plane/.../providers/`) only supply provider constants (region validation, backend config, service availability matrix).

**Rationale**: Satisfies Principle I: logical config stays cloud-free; each capability module has identical input variables (name, environment, encryption refs, tags/labels) and identical outputs (endpoints, ARNs/URIs, health-check targets) regardless of provider. Adding a provider = new directory + adapter registration (FR-015).

**Alternatives considered**:
- *Single multi-cloud module set with provider aliases inside*: Terraform's multi-provider-in-one-module pattern explodes complexity and couples providers — rejected as it would make adding Azure a modification of existing code.
- *Lowest-common-denominator abstraction library (e.g. libcloud)*: explicitly forbidden by Principle I.

## R-03: Orchestration engine choice (deployed *into* platforms)

**Decision**: For MVP, the `orchestration` capability module deploys **Apache Airflow** (managed where sensible: MWAA on AWS, Cloud Composer on GCP) behind the logical capability contract. The control plane's own deployment sequencing does **not** use Airflow — it is a lightweight Python async worker with PostgreSQL-persisted step state.

**Rationale**: BRD lists Airflow/Dagster/cloud-native as candidates and requires a "cloud-neutral orchestration abstraction"; managed Airflow on both clouds gives capability parity with least operational burden for MVP. Keeping the deployment engine dependency-free (no Airflow needed to deploy Airflow) avoids a chicken-and-egg bootstrap problem and keeps the <30-minute budget.

**Alternatives considered**:
- *Dagster*: strong OSS option, but no managed equivalent on either cloud → self-hosted ops burden breaks parity/simplicity for MVP.
- *Cloud-native only (Step Functions + Workflows)*: violates portability (different programming models per cloud).
- *Prefect*: same self-hosting concern as Dagster.
- Revisit at Phase 2 per BRD "evaluated rather than mandated prematurely".

## R-04: Metadata catalog choice

**Decision**: The `catalog` capability deploys **OpenMetadata** (self-hosted, containerised, backed by the platform's PostgreSQL and search index) and the deployment initialises it with the platform's storage zones, capability inventory, and dataset placeholders (FR-005).

**Rationale**: BRD lists OpenMetadata/DataHub/cloud catalogs; OpenMetadata is Apache-2.0, deployable identically on both clouds (portability), includes ingestion/lineage/quality metadata models needed by features 003–005, and avoids per-cloud catalog divergence (Glue vs Dataplex) that would break SC-003 capability parity. Cloud-native catalogs can be added later as *additional* provider-specific enrichment without changing the logical contract.

**Alternatives considered**:
- *DataHub*: comparable, but heavier deployment footprint (Kafka + Elasticsearch mandatory) threatens the 30-minute budget for MVP.
- *AWS Glue / GCP Dataplex only*: breaks parity (SC-003) and portability (Principle I).
- *Unity Catalog OSS*: young, narrower metadata model at time of decision.

## R-05: Terraform state backend & locking

**Decision**: Per-platform state in the platform's own object storage: **S3 backend + DynamoDB lock table** (AWS) and **GCS backend with native object locking** (GCP). State buckets are created by the platform's `storage-zones` module *first* in the step order (bootstrap step uses a minimal pre-state module), encrypted with the platform KMS key, and versioned.

**Rationale**: State stays inside the customer's account/project (security), encrypted at rest from creation (FR-017), and reproducible/DR-friendly (Principle II). Versioned state gives rollback of state itself if apply corrupts it.

**Alternatives considered**:
- *Central control-plane state store*: single blast radius, cross-account credential complexity — rejected.
- *Terraform Cloud/Enterprise*: external dependency, licensing.
- *Local state*: violates reproducibility and multi-user concurrency (FR-013/edge cases).

## R-06: Retry-from-failed-step and rollback semantics (FR-009, SC-005)

**Decision**: A deployment run is a **linear ordered step list** persisted in PostgreSQL. Each step records: terraform workspace/module, plan hash, status, timestamps, error detail.
- *Retry-from-failed-step*: re-run `terraform apply` for the failed step's module (Terraform's idempotency resumes partial applies naturally), then continue the sequence.
- *Rollback*: `terraform destroy` in reverse step order **scoped to the run's state only** — each run deploys into a fresh workspace, so destroy cannot touch pre-existing resources. Pre-existing platforms have separate states.
- *Credential expiry mid-run*: apply fails → run enters `paused(failed)` state; nothing is destroyed automatically; user refreshes credentials and retries.

**Rationale**: Terraform apply is already resumable per-state; per-run workspaces give the "MUST NOT touch pre-existing resources" guarantee structurally rather than by convention. Reverse-order destroy respects module dependencies.

**Alternatives considered**:
- *Saga/compensation handlers per resource*: unnecessary — Terraform destroy is the compensating action.
- *Automatic rollback on failure*: rejected; spec requires partial state to remain inspectable and rollback to be user-offered, not automatic.

## R-07: Validation approach (FR-003, SC-004)

**Decision**: Two-stage validation, both before any provisioning:
1. **Schema + semantic validation** in the control plane (Pydantic): required fields, naming rules (regex per cloud), region existence, capability dependency closure (e.g. semantic-layer requires catalog), environment-type controls (Production ⇒ approval token + encryption settings mandatory), name-uniqueness check against control-plane DB + live cloud scope.
2. **`terraform validate` + `terraform plan`** on the generated root module; plan errors are translated to user-facing messages.
All errors from stage 1 are collected and returned **in a single response** (Pydantic collects, no fail-fast).

**Rationale**: Catches 100% of invalid configs pre-provision cheaply (SC-004); plan-stage catches quota/permission issues (FR-018 permission pre-check uses `plan` + provider credential probes like STS `GetCallerIdentity` / GCP `gcloud auth` token introspection).

**Alternatives considered**:
- *JSON Schema alone*: no semantic/dependency rules; Pydantic v2 gives both plus typed models reused by the API.
- *OPA/Rego policy layer*: powerful but premature for MVP; environment controls are simple enough for code. Revisit with feature 005 governance policies.

## R-08: Health checks (FR-007)

**Decision**: Per-capability health check runners registered in the capability registry. Each returns `{component, status, last_check, detail}`. MVP checks: storage zone HEAD/list on each zone prefix; catalog HTTP `/health` (OpenMetadata); orchestration API reachability (Airflow `/health`); monitoring: verify metrics pipeline receives a synthetic datapoint; ingestion: service endpoint responds; IAM: assume-role/service-account token mint test; networking: DNS resolution of platform endpoints. Platform is `ready` only when all checks for **enabled** capabilities pass; otherwise `degraded` with failed components flagged (US3 AC3).

**Rationale**: Cheap, provider-neutral probes at the logical-capability level preserve parity (SC-003). Synthetic datapoint check proves observability "by default" rather than assuming it.

**Alternatives considered**:
- *Cloud-native health APIs only (CloudWatch/X-Ray)*: per-cloud divergence, breaks parity.
- *Deep functional tests (run a sample pipeline)*: exceeds 30-minute budget; deferred to quickstart manual validation.

## R-09: Secrets handling (SC-006, FR-011, FR-017)

**Decision**: Platform configs may only contain **secret references** (`secretRef: <name>`), never values. Secrets live in AWS Secrets Manager / GCP Secret Manager, created by the `secrets` capability module with KMS encryption. Terraform state is treated as secret-sensitive (encrypted, access-audited). Exported configs and audit records are scanned by a secret-detection pass (regex + entropy heuristics) before being returned/stored; logs redact known secret patterns. Deploying user's cloud credentials are never persisted — they are ambient (instance role / workload identity) or supplied per-session.

**Rationale**: Structurally guarantees SC-006 rather than relying on discipline; ambient credentials solve the mid-deployment expiry edge case cleanly (short-lived, auto-refreshed).

**Alternatives considered**:
- *Vault (HashiCorp)*: extra stateful service to bootstrap and secure; cloud KMS/secret managers are mandated by constitution and already present.
- *Encrypting secrets inside config YAML*: still plaintext-adjacent, key-management chicken-and-egg.

## R-10: Control-plane runtime & API framework

**Decision**: Python 3.12, **FastAPI + Pydantic v2**, PostgreSQL 15 (SQLAlchemy 2 + Alembic), Docker containers, deployed via `terraform/control-plane/` (ECS Fargate on AWS, Cloud Run on GCP). OpenTelemetry SDK for traces/metrics; structured JSON logs.

**Rationale**: BRD technology table (REST APIs, Docker, OpenTelemetry-compatible); Pydantic v2 doubles as the config-schema engine (R-07); async FastAPI suits long-running deployment supervision with status polling. Same code artifact deploys on both clouds (portability).

**Alternatives considered**:
- *Go + custom CLI-first*: viable, but Python ecosystem (Terraform JSON parsing, cloud SDKs, later GX/dbt integration in features 003–004) favours Python; team velocity for MVP.
- *Django*: heavier than needed; API-first product.

## R-11: Deployment step ordering (the 15-step BRD flow)

**Decision**: Canonical step sequence for the engine (each step = one or more Terraform modules + optional init job):

1. `validate-config` (R-07 stage 1)
2. `generate-tf` (render root module from config + capability registry)
3. `validate-tf` (R-07 stage 2: validate + plan)
4. `permission-check` (FR-018 fail-fast)
5. `networking`
6. `secrets-kms` (KMS keys, secret manager entries)
7. `storage-zones` (buckets + Bronze/Silver/Gold prefixes + state backend)
8. `iam` (roles, policies, least privilege)
9. `compute`
10. `database` (platform PostgreSQL for catalog/orchestration metadata)
11. `catalog` (OpenMetadata deploy + zone/dataset initialisation — FR-005)
12. `orchestration` (Airflow, if enabled)
13. `ingestion` (ingestion service runtime, if enabled)
14. `monitoring` (OTel collector, dashboards, alerts)
15. `health-checks` (R-08) → mark `ready`

Disabled capabilities skip their steps (recorded as `skipped`). Production environments insert an `approval-gate` step before step 5 (FR-010).

**Rationale**: Mirrors BRD §7.1 flow; dependency-safe ordering (network/secrets before everything; catalog after storage+database; health last). Persisted as the run's step list, driving FR-008 progress display and R-06 retry/rollback.

**Alternatives considered**:
- *Single monolithic `terraform apply`*: loses per-step status/retry granularity required by FR-008/FR-009.
- *Fully parallel DAG execution*: faster but complicates failure reporting and the 30-min budget is met comfortably with the sequential critical path (~20–25 min measured estimate for managed services).

## R-12: Name uniqueness & concurrency (FR-013, edge cases)

**Decision**: Platform name unique per `(cloud, account/project id)` — enforced by DB unique constraint on `(provider, cloud_scope_id, name)` plus a pre-flight live check (list existing platform states/tags in the cloud scope) during validation. Deployment runs serialised per platform via a `SELECT ... FOR UPDATE` advisory lock on the platform row (one active run per platform, per spec assumption). Concurrent distinct platforms run in parallel workers.

**Rationale**: DB constraint gives race-free enforcement; live check catches out-of-band resources. Row-level locking is sufficient at MVP scale (tens of platforms).

**Alternatives considered**:
- *Distributed lock service (Redis/etcd)*: extra infrastructure for no MVP-scale benefit.
- *Name uniqueness global*: too strict; two clouds may legitimately reuse names.

---

## Resolution Summary

| Unknown from Technical Context | Resolved by |
|---|---|
| How Terraform is executed & step tracking | R-01, R-11 |
| Cloud-independence mechanism | R-02 |
| Orchestration/catalog technology picks (BRD "evaluate") | R-03, R-04 |
| State management, retry, rollback | R-05, R-06 |
| Validation & permission pre-check | R-07 |
| Health check design | R-08 |
| Secrets & encryption enforcement | R-09 |
| Service framework/runtime | R-10 |
| Concurrency & naming | R-12 |

No NEEDS CLARIFICATION items remain. Proceed to Phase 1 design artifacts.
