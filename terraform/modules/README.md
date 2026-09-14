# Cloud-neutral shared glue (T038, capability-catalog.md "Provider mapping rules")
#
# Shared logic lives here ONLY as cloud-neutral variable schemas, tag/label
# conventions and init scripts. Provider modules (terraform/{aws,gcp}/<cap>/)
# MUST NOT reference each other (Principle II: provider isolation).
#
# ## Common module inputs (identical across providers)
#
#   variable "platform_name"       { type = string }
#   variable "environment"         { type = string }  # development|test|uat|production
#   variable "region"              { type = string }
#   variable "kms_key_ref"         { type = string }  # from secrets capability output
#   variable "network_ref"         { type = string }  # from networking capability output
#   variable "tags"                { type = map(string) }  # incl. owner, platform, environment
#   variable "encryption_enforced" { type = bool, default = true }  # FR-017; never false in prod
#
# ## Common module outputs (identical across providers)
#
#   output "endpoint"      { }  # logical endpoint (URL/URI) or "" if none
#   output "resource_ids"  { }  # provider-native ids (ARNs / resource names) for audit
#   output "health_target" { }  # what the health check probes (URL/bucket/role)
#   output "iam_principal" { }  # service identity created for this capability
#
# Provider-specific extras are allowed as ADDITIONAL outputs (e.g. AWS
# `kms_key_ref`, `network_ref` used for cross-module wiring) but consumers
# rely only on the common set (parity guarantee, SC-003).
#
# ## Tag/label convention
#
# Every resource carries: platform, environment, managed_by=datafoundry,
# capability=<key>. AWS uses tags; GCP uses labels (same key/value set).
#
# ## Shared init scripts
#
# scripts/init_zones.sh — Bronze/Silver/Gold zone initialisation contract
# (FR-005); invoked by the control-plane init job (engine/init_jobs.py),
# cloud-neutral (uses the gateway, not provider CLIs).
