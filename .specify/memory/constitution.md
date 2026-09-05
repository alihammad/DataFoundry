<!--
Sync Impact Report
==================
Version change: (none) → 1.0.0 (initial adoption)
Modified principles: N/A (initial)
Added sections: Core Principles, Security & Data Protection Requirements, Development Workflow & Quality Gates, Governance
Removed sections: N/A
Follow-up TODOs: none
-->

# DataFoundry Constitution

## Core Principles

### I. Cloud Independence via a Portable Core

The platform MUST be cloud-agnostic at the abstraction level, not by pretending AWS
and GCP services are identical. Every logical capability (object storage, compute,
orchestration, metadata, catalog, identity, secrets, monitoring, streaming, data
warehouse, API gateway) MUST map to cloud-specific implementations where they provide
meaningful value.

- The platform MUST NOT create a lowest-common-denominator abstraction that blocks
  teams from using cloud-native capabilities.
- Business logic, metadata, ingestion definitions, and logical datasets MUST remain
  portable across AWS and GCP.
- Each new cloud target MUST be introducible without a fundamental platform redesign.

Rationale: Portability is a stated product requirement; sacrificing cloud capability to
achieve naive symmetry is explicitly forbidden by the business requirements.

### II. Infrastructure as Code (Terraform)

Terraform SHALL be the primary infrastructure-as-code technology. All infrastructure —
networking, object storage, IAM, compute, databases, messaging, orchestration,
monitoring, secrets, and API infrastructure — MUST be reproducible from code.

- Cloud implementations MUST be isolated under `terraform/aws/` and `terraform/gcp/`.
- Logical configuration MUST remain cloud-independent; cloud-specific details MUST be
  encapsulated behind a single platform abstraction.
- Infrastructure MUST be reproducible from code such that recreation from versioned
  sources is always possible (disaster recovery requirement).

Rationale: One-click deployment, GitOps, and disaster recovery all depend on a single
authoritative, versioned IaC source of truth.

### III. Medallion Architecture with Quality-Gated Promotion

All data MUST flow through the Medallion Architecture: Bronze (raw/immutable) →
Silver (cleaned/conformed) → Gold (business-ready). No data MAY be promoted to the next
layer unless it passes the quality, schema, security, and contractual requirements
defined for that layer.

- Invalid, incomplete, corrupted, or structurally incompatible data MUST be
  quarantined, never silently propagated.
- Quality gates MUST exist and be enforced at every layer transition.
- Promotion MUST follow explicit states: INGESTED → VALIDATED → BRONZE → SILVER
  VALIDATED → SILVER → GOLD VALIDATED → GOLD → CONSUMABLE.
- Any override of a failed gate MUST require authorisation, reason, expiry, user
  identity, timestamp, and impact assessment.

Rationale: "Quality before promotion" and "quarantine rather than propagation" are the
platform's core correctness guarantees, and directly serve the stated zero-contamination
success metric.

### IV. Shift-Left Testing and Data Contracts

Testing MUST be a pipeline control mechanism applied as early as possible, not an
afterthought following consumer-facing failure. Data contracts MUST define the
agreement between producers and consumers and be validated during ingestion.

- Tests MUST begin before or during ingestion (file, schema, and security validation).
- Contract violations MUST be classified as breaking, non-breaking, or warning, and
  breaking changes MUST block promotion.
- Tests MUST support severity levels (CRITICAL, ERROR, WARNING, INFORMATIONAL),
  configurable per dataset and environment.
- Test-first development is the preferred workflow: define contract → define tests →
  develop transformation → run tests → deploy.

Rationale: Early detection and prevention are favoured over downstream remediation;
failed data must never knowingly reach consumers.

### V. AI Agents with Human Oversight

AI MUST be a platform capability — not a bolt-on chatbot — and AI agents MUST NOT have
unrestricted production access by default.

- Low-risk actions (documentation, metadata enrichment, query suggestions) MAY execute
  automatically.
- Medium-risk actions (pipeline configuration, quality rule, and schema changes) MUST
  require approval.
- High-risk actions (production infrastructure changes, data deletion, access or
  security-policy changes) MUST require explicit human approval.
- Agents MUST NEVER bypass encryption or security policies, retrieve keys, decrypt,
  detokenise, or export protected data unless explicitly authorised.

Rationale: Automation is a requirement, but security-sensitive and production-impacting
actions require human accountability.

## Security & Data Protection Requirements

Security MUST be designed in, not added afterwards. The following are non-negotiable:

- **Encryption in depth**: at rest, in transit, at the source before transmission, and
  at column level where required.
- **Column-level protection**: sensitive columns MUST support encryption, tokenisation,
  masking, hashing, redaction, and pseudonymisation, driven by policy rather than a
  single mandated mechanism.
- **Source-side encryption**: files containing sensitive data MUST be encrypted before
  they leave the source environment (e.g. PGP/GPG, envelope encryption, KMS).
- **Key management**: keys MUST be managed through approved KMS (AWS KMS / GCP Cloud
  KMS) with rotation, versioning, lifecycle management, and access auditing; keys MUST
  never be stored in application configuration or exposed through catalog/UI.
- **Classification-driven protection**: data classification (PUBLIC / INTERNAL /
  CONFIDENTIAL / RESTRICTED / HIGHLY RESTRICTED) MUST map to an enforceable protection
  policy.
- **Access control**: RBAC with dataset-, table-, column-, and row-level permissions,
  and least-privilege enforcement.
- **Auditability**: all security-sensitive operations (encryption, decryption,
  tokenisation, key usage, policy changes, restricted access) MUST be audited.

## Development Workflow & Quality Gates

- **GitOps / CI/CD**: Terraform, pipelines, data models, quality rules, semantic
  models, and configuration MUST be version controlled; changes MUST flow through Git →
  Pull Request → validation (Terraform validation, unit tests, data tests, security and
  policy checks) → approval → deployment.
- **Self-service reuse**: the platform team builds capabilities once; data teams
  consume them repeatedly. Engineers MUST NOT rebuild IAM, buckets, networking, or
  orchestration per project.
- **Observability**: pipeline, infrastructure, data (freshness/volume/quality), and
  cost MUST be observable by default (OpenTelemetry-compatible).
- **Metadata & lineage**: every dataset MUST carry owner, steward, domain, description,
  classification, quality score, lineage (upstream and downstream), and refresh
  metadata in a searchable catalog.
- **Open lakehouse standards**: Apache Iceberg SHALL be the evaluated table format, and
  DuckDB SHALL be evaluated for lightweight/analyst querying of Silver and Gold
  datasets.

## Governance

- This constitution supersedes all other development practices and conventions.
- Amendments MUST be documented, approved, and, where behaviour changes, accompanied by
  a migration or remediation plan.
- Constitution versioning follows Semantic Versioning: MAJOR for backward-incompatible
  principle removals or redefinitions; MINOR for new principles or materially expanded
  guidance; PATCH for clarifications and wording.
- All pull requests and reviews MUST verify compliance with these principles; any
  deviation MUST be explicitly justified and approved.
- Technology stack decisions (table format, ingestion, query engine, orchestration,
  catalog, quality, semantic layer, agent framework) MUST be driven by portability,
  operational simplicity, cost, interoperability, and long-term maintainability —
  not popularity.

**Version**: 1.0.0 | **Ratified**: 2026-09-05 | **Last Amended**: 2026-09-05
