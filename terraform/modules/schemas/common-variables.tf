# Common module input schema (cloud-neutral reference, T038).
#
# This file is the canonical variable set every capability module under
# terraform/{aws,gcp}/<capability>/ declares verbatim (capability-catalog.md
# "Common module inputs"). It is documentation-as-code: modules copy this
# block so `terraform validate` checks each module independently (no shared
# Terraform state between providers — Principle II).

variable "platform_name" {
  description = "Platform name (^[a-z][a-z0-9-]{2,62}$)."
  type        = string
}

variable "environment" {
  description = "Environment type: development | test | uat | production."
  type        = string
}

variable "region" {
  description = "Provider region for all resources."
  type        = string
}

variable "kms_key_ref" {
  description = "KMS key ref/alias from the secrets capability output (SC-006: never a literal key)."
  type        = string
}

variable "network_ref" {
  description = "Network reference from the networking capability output (VPC id / network name)."
  type        = string
}

variable "tags" {
  description = "Common tags/labels: platform, environment, managed_by, owner."
  type        = map(string)
  default     = {}
}

variable "encryption_enforced" {
  description = "FR-017: encryption at rest + TLS in transit enforced. Non-overridable false in production."
  type        = bool
  default     = true
}
