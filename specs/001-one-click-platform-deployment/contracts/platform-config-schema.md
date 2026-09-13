# Contract: Platform Configuration Schema

**Feature**: 001-one-click-platform-deployment | **Version**: v1 | **Date**: 2026-09-13

The cloud-independent declarative configuration for a platform (FR-011, US2). Stored version-controlled under `platform-configs/<platform-name>/<env>.yaml`, exported/imported via the API, and rendered into Terraform by the capability registry. **Contains no plaintext secrets** — only `secretRef` pointers (SC-006).

Authoritative machine-readable schema: Pydantic v2 model `PlatformConfig` in `control-plane/src/datafoundry/controlplane/config/`. This document is the human contract; the Pydantic model is the source of truth and MUST stay in sync (enforced by contract tests).

---

## Full example

```yaml
apiVersion: datafoundry/v1
kind: PlatformConfig

platform:
  name: customer-analytics          # ^[a-z][a-z0-9-]{2,62}$, unique per cloud scope
  provider: gcp                      # aws | gcp
  region: australia-southeast1       # must exist for provider & support all capabilities
  environment: production            # development | test | uat | production

capabilities:
  storage_zones: { enabled: true }   # mandatory core — cannot be disabled
  networking:    { enabled: true }   # mandatory core
  iam:           { enabled: true }   # mandatory core
  secrets:       { enabled: true }   # mandatory core
  compute:       { enabled: true, size: medium }       # small | medium | large
  catalog:       { enabled: true }
  orchestration: { enabled: true }
  ingestion:     { enabled: true }
  quality:       { enabled: false }
  semantic_layer:{ enabled: false }  # requires catalog when enabled
  monitoring:    { enabled: true }

storage:
  table_format: iceberg              # iceberg (default; BRD-evaluated standard)
  zones:
    bronze: { retention_days: -1 }   # -1 = immutable/forever (constitution Principle III)
    silver: { retention_days: 365 }
    gold:   { retention_days: 365 }

encryption:                          # MANDATORY explicit block when environment=production
  at_rest:
    kms_key_ref: platform-cmk        # secretRef -> cloud KMS key alias/created by secrets step
    algorithm: AES-256
  in_transit:
    min_tls: "1.2"                   # enforced on all platform endpoints (FR-017)

networking:
  isolation: private                 # private | internal | public (public forbidden in production)
  cidr: 10.20.0.0/16

secrets:
  backend: cloud_native              # aws_secrets_manager | gcp_secret_manager (auto per provider)
  refs:
    platform-credentials: platform-credentials   # logical name -> secret manager entry

observability:
  tracing: opentelemetry             # OpenTelemetry-compatible (constitution)
  log_retention_days: 90

approval:                            # REQUIRED when environment=production (FR-010)
  ref: APPROVAL-2026-0912-017        # external approval ticket/token
  approved_by: platform-lead@corp
```

---

## Field reference

| Path | Type | Required | Rules |
|---|---|---|---|
| apiVersion | const `datafoundry/v1` | yes | schema version gate |
| kind | const `PlatformConfig` | yes | |
| platform.name | string | yes | regex `^[a-z][a-z0-9-]{2,62}$`; unique per `(provider, cloud_scope_id)` (FR-013) |
| platform.provider | enum | yes | `aws`,`gcp` (FR-002); extensible without schema change (FR-015) |
| platform.region | string | yes | must exist for provider and support every enabled capability (edge case: region-capability) |
| platform.environment | enum | yes | `development`,`test`,`uat`,`production` (FR-010) |
| capabilities.* | object | yes | each `{enabled: bool, ...}`; core four cannot be `enabled:false` |
| capabilities.semantic_layer | object | no | if enabled ⇒ `catalog.enabled` must be true (dependency closure) |
| capabilities.orchestration | object | no | if enabled ⇒ `compute.enabled` must be true |
| capabilities.ingestion | object | no | if enabled ⇒ `storage_zones.enabled` (always true) |
| storage.table_format | enum | no | `iceberg` default (constitution: Iceberg SHALL be evaluated standard) |
| storage.zones.bronze.retention_days | int | no | `-1` = immutable/forever; Bronze is raw/immutable per Principle III |
| encryption.at_rest.kms_key_ref | string | prod: yes | secretRef only; never a literal key (SC-006) |
| encryption.in_transit.min_tls | string | no | default `1.2`; enforced on all endpoints (FR-017) |
| networking.isolation | enum | no | `public` forbidden when environment=production |
| networking.cidr | string | no | valid CIDR; required when isolation != public |
| secrets.refs | map | no | logical→entry name; values NEVER inline |
| observability.tracing | enum | no | `opentelemetry` default |
| approval.ref | string | prod: yes | production deployments refuse without it (FR-010, edge case) |
| approval.approved_by | string | prod: yes | identity of approver |

---

## Validation contract (FR-003, SC-004)

Validation is **collect-all, not fail-fast**: every rule below is evaluated and all violations returned together in one `422` response (see deployment-api.md §1).

1. **Structural**: YAML parses; `apiVersion`/`kind` match; unknown fields rejected (strict mode).
2. **Type/enum/format**: per field reference above.
3. **Naming**: `platform.name` regex; reserved-name blocklist (`datafoundry`, `system`).
4. **Region-capability**: for each enabled capability, region must appear in the provider region-capability matrix (R-02). Error suggests supported regions.
5. **Capability dependency closure**: transitive `depends_on` from the capability registry must all be enabled.
6. **Environment controls** (production): `approval.ref` + `approval.approved_by` present; `encryption.at_rest` explicit; `networking.isolation != public`.
7. **Secret scan**: no field value matches secret patterns (AWS keys, PEM blocks, high-entropy strings). Violation ⇒ reject (SC-006).
8. **Uniqueness**: `(provider, cloud_scope_id, name)` not already registered (FR-013) — checked live at deploy time (R-12).

Each error carries `{path, code, message, remediation}` so a first-time user can self-correct (SC-007).

---

## Reproducibility contract (SC-002, US2)

- The config is **complete**: it plus the pinned Terraform module versions fully determines the platform. No hidden console state.
- **Export** (`GET /platforms/{id}/config`) returns the exact stored YAML + hash; re-applying it recreates an identical platform.
- **Determinism**: `config_hash` = SHA-256 of canonically-serialised YAML (sorted keys, normalised whitespace). Same logical config ⇒ same hash ⇒ idempotent deploy.
- **Version control**: configs live in `platform-configs/` and flow through Git → PR → validation → approval → deploy (constitution GitOps). `source`/`git_ref` recorded on each PlatformConfigVersion.
