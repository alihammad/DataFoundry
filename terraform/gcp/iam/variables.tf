# Common module inputs (capability-catalog.md — identical across providers).

variable "platform_name" {
  description = "Platform name."
  type        = string
}

variable "environment" {
  description = "development | test | uat | production."
  type        = string
}

variable "region" {
  description = "Provider region."
  type        = string
}

variable "kms_key_ref" {
  description = "KMS key ref from the secrets capability (never a literal key, SC-006)."
  type        = string
}

variable "network_ref" {
  description = "Network reference from the networking capability."
  type        = string
}

variable "tags" {
  description = "Common tags/labels (platform, environment, managed_by, owner)."
  type        = map(string)
  default     = {}
}

variable "encryption_enforced" {
  description = "FR-017: encryption enforced; non-overridable false in production."
  type        = bool
  default     = true
}
