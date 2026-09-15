# Implementation Plan: Security and Data Protection

**Branch**: `feature/005-security-data-protection` | **Date**: 2026-09-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/005-security-data-protection/spec.md`

## Summary

Deliver the platform's security and data-protection layer: **classification-driven protection** (PUBLIC … HIGHLY RESTRICTED maps to an enforceable protection policy; sensitive columns protected by policy — encrypt/tokenise/mask/hash/redact/pseudonymise — not by hand), **encryption in depth** (at rest across every layer/metadata/logs/temp/backup, in transit, source-side file encryption with integrity/signature verification, platform- and customer-managed keys), **tokenisation** of highly sensitive values with a secured token service and deterministic mode, **key management** through approved KMS (rotation, versioning, lifecycle, revocation, separation of duties; keys never stored in config or exposed), a **secure access enforcement chain** (identity → authentication → authorisation → classification → protection policy → data access; RBAC at dataset/table/column/row level with least privilege), and **security auditability** (all security-sensitive operations audited, tamper-evident, searchable).

This feature consumes the identity/RBAC model and audit service from feature 001, the ingestion hand-off states and quarantine routing from feature 002, and the gate decisions from feature 004; it supplies the protection metadata that feature 003's processing and feature 006's semantic layer consume. It reuses the control plane's worker, DB, secret-scan, audit, and gateway abstractions.

## Technical Context

**Language/Version**: Python 3.12 (control plane service); the security layer is a module *inside* the existing control plane, reusing its worker, DB, audit, and gateway abstractions.

**Primary Dependencies**: FastAPI + Pydantic v2 (API, config/schema validation), SQLAlchemy 2 + Alembic (persistence, same DB as feature 001/002), `cryptography` (standard-library-backed primitives for source-side file encryption verification and column-level protection in the simulated gateway), existing OpenTelemetry + structured-logging + secret-scan infrastructure reused unchanged. Cloud KMS (AWS KMS / GCP Cloud KMS) resolved behind a logical encryption-service abstraction — see R-01/R-02.

**Storage**:
- Control-plane metadata (classifications, protection policies, key references, token references, security audit records, access decisions, encryption metadata): the same PostgreSQL 15 provisioned by feature 001 (reuses `db/` models + Alembic; new migration).
- Protected payloads: Bronze/Silver/Gold zone prefixes via the existing `CloudGateway` (S3/GCS); source-encrypted files land in the `quarantine/` prefix (feature 002) on verification failure.
- Key material: NEVER stored by the platform — only key *references* (id, version, lifecycle state) in the DB; actual keys live in the cloud KMS.

**Testing**: pytest (unit + API contract + integration); the existing in-memory SQLite harness (feature 001 conftest pattern) extended with a **SimulatedSecurityGateway** (in-memory KMS, token vault, protection engine, source-encryption fixtures) so every classification, protection, tokenisation, key-rotation, access-enforcement, and audit path is exercisable offline — no docker/terraform/database required locally. Live E2E against sandbox data gated manually.

**Target Platform**: Linux server, containerised; same deployment artifact as feature 001/002 (ECS Fargate / Cloud Run).

**Project Type**: Web service extension (control plane API + engine) + CLI extension. Single monorepo.

**Performance Goals**: Protection/encryption applied to a medium dataset in interactive time (seconds); a security audit record is retrievable within one minute of search (SC-004); key rotation completes without data loss or downtime (SC-006).

**Constraints**: Fail closed — when a protection service is unavailable or a policy cannot be enforced, affected processing blocks rather than proceeding unprotected (FR-019); keys never stored in application configuration or exposed via catalog/UI (FR-008, SC-003); classification downgrades require authorisation and never retroactively expose protected data (FR-020); identical logical protection behaviour on both clouds (FR-010, SC-007); all security-sensitive operations audited (FR-014, SC-004).

**Scale/Scope**: MVP — classification-driven protection, encryption at rest/in transit, source-side file encryption verification, column-level protection (encrypt/tokenise/mask/hash/redact/pseudonymise), key management integration (rotation/versioning/revocation), access enforcement chain, security auditability. Advanced tokenisation (detokenisation UX, purpose-bound authorisation) is BRD Phase 2 — this feature defines the tokenisation behaviour required when enabled; deterministic tokenisation may be delivered in Phase 2. AI-agent integration is Phase 3 (spec Assumptions).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Requirement | Plan Compliance | Status |
|---|---|---|---|
| I. Cloud Independence via Portable Core | Logical config portable; new provider without touching core | Protection policies, classifications, key references are cloud-free; cloud KMS resolved behind a logical encryption-service abstraction (FR-010); identical protection behaviour on both clouds (SC-007) | ✅ PASS |
| II. Infrastructure as Code (Terraform) | All infra reproducible from code | KMS keys, encryption config, and storage encryption are provisioned via terraform modules (feature 001 storage/iam/secrets); no new infra — protected payloads land in existing zone prefixes | ✅ PASS |
| III. Medallion Architecture with Quality-Gated Promotion | Gates at every layer transition; quarantine rather than propagate | Protection applied at every layer (Bronze/Silver/Gold); source-encrypted files failing verification rejected to quarantine (FR-006); fail-closed on protection-service unavailability (FR-019) | ✅ PASS |
| IV. Shift-Left Testing & Data Contracts | Tests before/during ingestion; contracts validated | Source-side encryption verified at ingestion before processing (FR-006); protection metadata recorded per column (FR-017); lineage records protection state transitions (FR-018) | ✅ PASS |
| V. AI Agents with Human Oversight | No unrestricted AI production access; deterministic validation before execution | AI agents MUST NOT retrieve keys, decrypt, detokenise, change policies, grant access, disable encryption, or export protected data without explicit authorisation (constitution V, spec Assumptions); agent integration deferred to Phase 3 | ✅ PASS |
| Security & Data Protection | Encryption in depth; column-level protection; source-side encryption; KMS; classification-driven; RBAC; auditability | This feature IS the security layer: encryption at rest/in transit/source-side/column-level (FR-004/005/006/003), KMS with rotation/versioning/revocation (FR-008/009), classification-driven protection (FR-001/002), RBAC enforcement chain (FR-013), full auditability (FR-014) | ✅ PASS |
| Development Workflow & Quality Gates | GitOps; observability by default; self-service reuse | Protection policies/classifications version-controlled (reuses `config/gitops.py` pattern); security events observable via OpenTelemetry; protection engine built once, data teams consume | ✅ PASS |
| Governance | Tech decisions driven by portability/simplicity/cost, not popularity | KMS abstraction and protection-mechanism choices recorded in research.md (R-01/R-02) with explicit rationale; standard cryptography only (FR-006 — no proprietary crypto) | ✅ PASS |

**Gate result**: PASS — no violations, Complexity Tracking not required.

## Project Structure

### Documentation (this feature)

```text
specs/005-security-data-protection/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── security-api.md
│   ├── protection-policy-schema.md
│   └── encryption-metadata-schema.md
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
control-plane/src/datafoundry/controlplane/
├── api/                     # NEW routers: classification, protection, keys,
│   │                        #   tokens, access, security-audit
│   ├── classification.py
│   ├── protection.py
│   ├── keys.py
│   ├── tokens.py
│   ├── access.py
│   └── security_audit.py
├── security/                # NEW package: the security & protection engine
│   ├── classification.py    #   classification levels + org mapping
│   ├── policy.py            #   classification -> protection policy resolution
│   ├── protection.py        #   column-level mechanisms (encrypt/tokenise/mask/
│   │                        #     hash/redact/pseudonymise)
│   ├── encryption.py        #   at-rest + source-side file encryption verification
│   ├── keys.py              #   logical encryption service (KMS abstraction)
│   ├── tokens.py            #   token service (deterministic + vault)
│   ├── access.py            #   enforcement chain (identity -> ... -> data access)
│   ├── audit.py             #   security audit records (tamper-evident)
│   ├── engine.py            #   apply protection during processing
│   └── gateway.py           #   SimulatedSecurityGateway + live KMS adapters
├── db/
│   ├── models.py            #   + Classification, ProtectionPolicy, KeyReference,
│   │                        #     TokenReference, SecurityAuditRecord, AccessDecision,
│   │                        #     EncryptionMetadata
│   └── migrations/          #   + new Alembic migration
├── audit/service.py         #   + security audit actions (reused)
├── config/                  #   + protection-policy schema (new module)
│   └── security_schema.py
└── health/runners.py        #   + security health (optional)

cli/src/datafoundry/cli/commands/
├── classify.py              # datafoundry classify set/get
├── protect.py               # datafoundry protect apply/export
├── key.py                   # datafoundry key rotate/revoke/status
├── token.py                 # datafoundry token detokenise (authorised)
└── security-audit.py        # datafoundry security-audit search

control-plane/tests/
├── unit/                    # classification mapping, protection mechanisms, key
│                            #   rotation, tokenisation, access chain, audit
├── contract/                # security-api, protection-policy-schema,
│                            #   encryption-metadata-schema
└── integration/             # classify -> protect -> ingest -> verify -> audit flows

terraform/aws/{storage,iam,secrets}/   # + KMS key provisioning, storage encryption
terraform/gcp/{storage,iam,secrets}/   # + Cloud KMS key provisioning, storage encryption
```

**Structure Decision**: Extend the existing control plane rather than create a separate service — the security engine shares the worker, DB, secret-scan, audit, and gateway abstractions already built in feature 001/002, avoiding a second runtime and its operational burden (portability + simplicity). Protection mechanisms follow the same registry pattern as the capability registry and feature 002's connector registry (Principle I). Cloud KMS is resolved behind a logical encryption-service abstraction so S3/GCS parity is structural, not per-mechanism (FR-010, SC-007). The web UI (feature 007) consumes `contracts/security-api.md` unchanged.

## Phase 0 Output

See [research.md](./research.md) — all Technical Context unknowns resolved.

## Phase 1 Output

See [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md).