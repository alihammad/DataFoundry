# Contract: Capability Catalog

**Feature**: 001-one-click-platform-deployment | **Version**: v1 | **Date**: 2026-09-13

Defines the logical capabilities, their dependency graph, and the per-provider Terraform module mapping that delivers cloud independence (constitution Principle I, FR-002, FR-012, FR-015, SC-003). This is the contract between the control plane's capability registry and the `terraform/` module library.

---

## Capability contract (per capability)

Every capability MUST define:

| Element | Requirement |
|---|---|
| `key` | stable logical id (used in config, API, DB) |
| `selectable` | `false` for mandatory core (cannot be disabled) |
| `depends_on` | capability keys that must be enabled first |
| `module_path` | `terraform/{provider}/{key}/` — provider-isolated (Principle II) |
| `inputs` | common variable set (below) |
| `outputs` | common output set (below) |
| `health_check` | runner id producing a HealthCheckResult |
| `deploy_step` | position in the canonical step order (R-11) |

### Common module inputs (identical across providers)

```hcl
variable "platform_name"     { type = string }
variable "environment"       { type = string }        # development|test|uat|production
variable "region"            { type = string }
variable "kms_key_ref"       { type = string }        # from secrets capability output
variable "network_ref"       { type = string }        # from networking capability output
variable "tags"              { type = map(string) }   # incl. owner, platform, environment
variable "encryption_enforced" { type = bool, default = true }  # FR-017, non-overridable false in prod
```

### Common module outputs (identical across providers)

```hcl
output "endpoint"        { }   # logical endpoint (URL/URI) or "" if none
output "resource_ids"    { }   # provider-native ids (ARNs / resource names) for audit
output "health_target"   { }   # what the health check probes (URL/bucket/role)
output "iam_principal"   { }   # service identity created for this capability
```

Provider-specific extras are allowed as *additional* outputs but consumers MUST rely only on the common set (parity guarantee, SC-003).

---

## Capability registry (MVP)

| key | display | selectable | depends_on | deploy step | AWS module | GCP module | health check |
|---|---|---|---|---|---|---|---|
| networking | Network Isolation | no (core) | — | 5 | terraform/aws/networking | terraform/gcp/networking | dns-resolve |
| secrets | Secrets & KMS | no (core) | networking | 6 | terraform/aws/secrets | terraform/gcp/secrets | kms-decrypt-probe |
| storage_zones | Object Storage + Zones | no (core) | secrets | 7 | terraform/aws/storage | terraform/gcp/storage | zone-head (bronze/silver/gold) |
| iam | Identity & Access | no (core) | networking | 8 | terraform/aws/iam | terraform/gcp/iam | token-mint |
| compute | Compute | yes | iam | 9 | terraform/aws/compute | terraform/gcp/compute | instance-ready |
| database | Platform Database | yes* | iam, secrets | 10 | terraform/aws/database | terraform/gcp/database | pg-ping |
| catalog | Metadata Catalog | yes | storage_zones, database | 11 | terraform/aws/catalog | terraform/gcp/catalog | http /health (OpenMetadata) |
| orchestration | Orchestration | yes | compute, database | 12 | terraform/aws/orchestration | terraform/gcp/orchestration | airflow /health |
| ingestion | Ingestion Service | yes | storage_zones, catalog | 13 | terraform/aws/ingestion | terraform/gcp/ingestion | endpoint-responds |
| quality | Data Quality Gates | yes | catalog | 13b | terraform/aws/quality | terraform/gcp/quality | runner-heartbeat |
| semantic_layer | Semantic Layer | yes | catalog | 13c | terraform/aws/semantic | terraform/gcp/semantic | endpoint-responds |
| monitoring | Monitoring & Observability | yes | networking, iam | 14 | terraform/aws/monitoring | terraform/gcp/monitoring | synthetic-datapoint |

\* `database` is auto-enabled when any of catalog/orchestration/ingestion/quality/semantic_layer is enabled (implicit dependency; surfaced in validation).

**Mandatory core** (networking, secrets, storage_zones, iam) is always provisioned — they are the minimum governed lakehouse (US1 independent test: "usable empty governed lakehouse").

---

## Provider mapping rules (FR-015, Principle I)

1. **Isolation**: AWS modules MUST NOT reference GCP providers/resources and vice versa. Shared logic lives in `terraform/modules/` as cloud-neutral variable schemas and init scripts only.
2. **Parity**: a capability is "supported on a provider" only when its module implements the full common input/output contract and has a passing health check. The region-capability matrix (deployment-api.md §3) is generated from actual module availability, not hand-maintained.
3. **Adding a provider** (e.g. Azure): create `terraform/azure/<capability>/` implementing the same contracts + register a provider adapter (`control-plane/.../providers/azure.py`) supplying region list, backend config, and credential probe. **No change** to `PlatformConfig` schema, API contracts, or existing provider modules. Verified by the capability-parity checklist (SC-003).
4. **Cloud-native enrichment**: providers MAY expose extra capabilities (e.g. Glue/Dataplex integration) as *additional* selectable keys namespaced `provider_aws_*`; they never replace the logical capability.

---

## Module → step rendering (R-01, R-11)

The engine renders a per-run root module:

```hcl
# generated: terraform/workspaces/<run_id>/main.tf.json
module "storage_zones" {
  source            = "../../aws/storage"
  platform_name     = var.platform_name
  environment       = var.environment
  region            = var.region
  kms_key_ref       = module.secrets.kms_key_ref
  network_ref       = module.networking.network_ref
  encryption_enforced = true
  tags              = var.tags
}
# ...one module block per enabled capability, in dependency order
```

Disabled capabilities produce **no module block** and their step is recorded `skipped` (FR-012, US3-AC1: no semantic-layer components provisioned when disabled). Each module applies in its own step for granular status/retry (FR-008, FR-009).

---

## Health check contract (FR-007, R-08)

Each runner returns:

```json
{ "component": "catalog", "status": "healthy|unhealthy|unknown", "last_check_at": "ISO8601", "detail": "string|null" }
```

Platform readiness rule: `ready` iff every **enabled** capability's latest result is `healthy`; any `unhealthy` ⇒ `degraded` with the component flagged (US3-AC2/AC3). Checks run automatically as deploy step 15 and on-demand via `POST /platforms/{id}/health-checks`.
