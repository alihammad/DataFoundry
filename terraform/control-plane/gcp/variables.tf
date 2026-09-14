# Control-plane bootstrap inputs (T085). Control-plane-specific, not the
# common capability module inputs.

variable "name_prefix" {
  description = "Name prefix for all bootstrap resources."
  type        = string
  default     = "datafoundry-controlplane"
}

variable "project_id" {
  description = "GCP project id hosting the control plane."
  type        = string
}

variable "region" {
  description = "GCP region for the control plane."
  type        = string
  default     = "us-central1"
}

variable "controlplane_image" {
  description = "Control-plane container image (Artifact Registry / GCR)."
  type        = string
}

variable "database_username" {
  description = "Metadata-store master username."
  type        = string
  default     = "dfadmin"
}

variable "labels" {
  description = "Common labels for all bootstrap resources."
  type        = map(string)
  default     = {}
}
