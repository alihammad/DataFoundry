# Control-plane bootstrap inputs (T084). These are control-plane-specific,
# not the common capability module inputs — the control plane provisions
# platforms, so it needs its own image, metadata-store, and TLS settings.

variable "name_prefix" {
  description = "Name prefix for all bootstrap resources."
  type        = string
  default     = "datafoundry-controlplane"
}

variable "region" {
  description = "AWS region for the control plane."
  type        = string
  default     = "us-east-1"
}

variable "vpc_cidr" {
  description = "CIDR block for the control-plane VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "controlplane_image" {
  description = "Control-plane container image (ECR repo:tag)."
  type        = string
}

variable "database_username" {
  description = "Metadata-store master username."
  type        = string
  default     = "dfadmin"
}

variable "tls_certificate_arn" {
  description = "ARN of the ACM certificate for the API TLS endpoint."
  type        = string
}

variable "allowed_cidrs" {
  description = "CIDRs allowed to reach the API (ingress)."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "tags" {
  description = "Common tags for all bootstrap resources."
  type        = map(string)
  default     = {}
}
